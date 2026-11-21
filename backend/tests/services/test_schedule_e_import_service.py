"""Example / edge tests for the Schedule E ``ImportService`` (task 3.6).

Exercised against a ``moto``-backed single table (with GSI1 for property rows
and GSI2 for tax-year transaction queries) and an S3 bucket, mirroring the
existing service-test fixtures. These cover the discrete scenarios the design's
Testing Strategy classifies as EXAMPLE / EDGE_CASE:

* synthesis of exactly one summary transaction per non-zero line (none for
  zero/blank);
* Dec 31 dating lands rows in the tax-year GSI2 partition;
* Line 19 default description applied;
* empty entries -> validation ``field="entries"``;
* missing / out-of-range four-digit tax_year -> validation ``field="tax_year"``;
* duplicate property mapping -> validation ``field="entries[i]"``;
* all-zero entry -> validation ``field="entries[i]"``;
* ``schedule_e_line == 18`` rejected;
* the structured dotted ``field`` path shapes;
* a not-owned property -> ``not_found``;
* replace-on-reimport removes the prior imported set for an included pair while
  leaving omitted pairs and user-tracked rows untouched;
* ``remove_imported_set`` happy path + ``not_found``.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.repository import keys
from logstead.services.property import PropertyService
from logstead.services.schedule_e_import import ImportService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-sub-1"
OTHER_USER_ID = "user-sub-2"


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def aws():
    """Moto table with GSI1 (property rows) + GSI2 (txn tax-year) and an S3 bucket."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield ddb, s3


@pytest.fixture
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture
def service(repo, files):
    return ImportService(repo, UserContext(user_id=USER_ID), files)


def _seed_property(repo, files, user_id=USER_ID, name="Maple Duplex") -> str:
    """Create a property owned by ``user_id`` and return its id."""
    properties = PropertyService(repo, user_id)
    created = properties.create(PropertyInput(name=name, address_text="1 Main St"))
    assert created.is_ok
    return created.value.id


def _all_txns(repo, property_id):
    """List a property's transactions (newest-first) via the base table."""
    svc = TransactionService(repo, S3FileAdapter(None, "unused"))
    return svc.list_for_property(property_id).value


# --- Synthesis ---------------------------------------------------------------


def test_synthesizes_one_txn_per_non_zero_line_and_none_for_zero_or_blank(
    repo, files, service
):
    prop_id = _seed_property(repo, files)
    submission = ImportSubmission(
        tax_year=2023,
        entries=[
            PropertyEntryInput(
                property_id=prop_id,
                lines=[
                    LineAmountInput(schedule_e_line=3, amount="24000.00"),
                    LineAmountInput(schedule_e_line=14, amount="1875.50"),
                    LineAmountInput(schedule_e_line=5, amount="0.00"),   # zero
                    LineAmountInput(schedule_e_line=6, amount=None),     # blank
                ],
            )
        ],
    )

    result = service.import_schedule_e(submission)

    assert result.is_ok
    outcome = result.value
    assert outcome.tax_year == 2023
    assert len(outcome.entries) == 1
    entry = outcome.entries[0]
    assert entry.property_id == prop_id
    assert entry.deleted_prior_count == 0
    assert entry.created_inline_property is False
    assert len(entry.created_transaction_ids) == 2

    txns = _all_txns(repo, prop_id)
    assert len(txns) == 2
    by_line = {t.schedule_e_line: t for t in txns}
    assert set(by_line) == {3, 14}
    assert by_line[3].type == "income"
    assert by_line[3].amount == Decimal("24000.00")
    assert by_line[3].imported is True
    assert by_line[14].type == "expense"
    assert by_line[14].amount == Decimal("1875.50")
    assert by_line[14].imported is True


def test_rows_dated_year_end_and_land_in_tax_year_gsi2_partition(repo, files, service):
    prop_id = _seed_property(repo, files)
    service.import_schedule_e(
        ImportSubmission(
            tax_year=2022,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[LineAmountInput(schedule_e_line=3, amount="100.00")],
                )
            ],
        )
    )

    # The GSI2 tax-year query (via list_for_property with a tax_year) must return
    # the synthesized row, confirming the Dec 31 dating lands in the partition.
    svc = TransactionService(repo, files)
    in_year = svc.list_for_property(prop_id, 2022).value
    assert len(in_year) == 1
    assert in_year[0].date == "2022-12-31"
    # A different tax year's partition is empty.
    assert svc.list_for_property(prop_id, 2021).value == []


def test_line_19_uses_default_description_when_none_provided(repo, files, service):
    prop_id = _seed_property(repo, files)
    service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[LineAmountInput(schedule_e_line=19, amount="320.00")],
                )
            ],
        )
    )

    txns = _all_txns(repo, prop_id)
    assert len(txns) == 1
    assert txns[0].schedule_e_line == 19
    assert txns[0].description == "Imported Schedule E Other"


def test_line_19_uses_provided_description(repo, files, service):
    prop_id = _seed_property(repo, files)
    service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[
                        LineAmountInput(
                            schedule_e_line=19, amount="320.00", description="HOA dues"
                        )
                    ],
                )
            ],
        )
    )

    txns = _all_txns(repo, prop_id)
    assert txns[0].description == "HOA dues"


def test_inline_property_creation(repo, files, service):
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    new_property=PropertyInput(
                        name="New Place", address_text="9 Oak Ave"
                    ),
                    lines=[LineAmountInput(schedule_e_line=3, amount="18000.00")],
                )
            ],
        )
    )

    assert result.is_ok
    entry = result.value.entries[0]
    assert entry.created_inline_property is True
    # The property now exists and is owned by the user.
    assert PropertyService(repo, USER_ID).get(entry.property_id).is_ok
    txns = _all_txns(repo, entry.property_id)
    assert len(txns) == 1
    assert txns[0].amount == Decimal("18000.00")


# --- Validation (all-or-nothing, structured field paths) ---------------------


def test_empty_entries_rejected(service):
    result = service.import_schedule_e(ImportSubmission(tax_year=2023, entries=[]))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries"


def test_missing_tax_year_rejected(service):
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=None,
            entries=[
                PropertyEntryInput(
                    property_id="p", lines=[LineAmountInput(3, "1.00")]
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "tax_year"


@pytest.mark.parametrize("bad_year", [999, 10000, 0, -5])
def test_out_of_range_tax_year_rejected(service, bad_year):
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=bad_year,
            entries=[
                PropertyEntryInput(
                    property_id="p", lines=[LineAmountInput(3, "1.00")]
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "tax_year"


def test_duplicate_property_mapping_rejected(repo, files, service):
    prop_id = _seed_property(repo, files)
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id, lines=[LineAmountInput(3, "100.00")]
                ),
                PropertyEntryInput(
                    property_id=prop_id, lines=[LineAmountInput(4, "200.00")]
                ),
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[1]"
    # Nothing was written for the duplicate submission.
    assert _all_txns(repo, prop_id) == []


def test_all_zero_entry_rejected(repo, files, service):
    prop_id = _seed_property(repo, files)
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[
                        LineAmountInput(3, "0.00"),
                        LineAmountInput(14, None),
                    ],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0]"


def test_line_18_rejected(repo, files, service):
    prop_id = _seed_property(repo, files)
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[LineAmountInput(schedule_e_line=18, amount="500.00")],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0].lines[18]"


def test_negative_amount_rejected_with_line_field(repo, files, service):
    prop_id = _seed_property(repo, files)
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[LineAmountInput(schedule_e_line=14, amount="-5.00")],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0].lines[14]"


def test_non_monetary_amount_rejected_with_line_field(repo, files, service):
    prop_id = _seed_property(repo, files)
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[LineAmountInput(schedule_e_line=14, amount="abc")],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0].lines[14]"


def test_inline_missing_name_structured_field(service):
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    new_property=PropertyInput(name="  ", address_text="9 Oak"),
                    lines=[LineAmountInput(3, "100.00")],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0].new_property.name"


def test_entry_without_mapping_rejected(service):
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[PropertyEntryInput(lines=[LineAmountInput(3, "100.00")])],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entries[0]"


# --- Ownership ---------------------------------------------------------------


def test_not_owned_property_rejected_not_found(repo, files, service):
    # A property owned by a different user: resolution must fail not_found and
    # write nothing.
    other_prop = _seed_property(repo, files, user_id=OTHER_USER_ID, name="Theirs")
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=other_prop,
                    lines=[LineAmountInput(3, "100.00")],
                )
            ],
        )
    )
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert _all_txns(repo, other_prop) == []


# --- Replace-on-reimport -----------------------------------------------------


def test_reimport_replaces_prior_imported_set_only_for_included_pair(
    repo, files
):
    user = UserContext(user_id=USER_ID)
    service = ImportService(repo, user, files)
    prop_a = _seed_property(repo, files, name="A")
    prop_b = _seed_property(repo, files, name="B")

    # Seed a user-tracked transaction on prop_a for the same year.
    txn_svc = TransactionService(repo, files)
    user_tracked = txn_svc.create(
        TransactionInput(
            property_id=prop_a,
            date="2023-06-01",
            amount=Decimal("50.00"),
            type="expense",
            category_id="repairs",
            description=None,
        )
    )
    assert user_tracked.is_ok
    user_tracked_id = user_tracked.value.id

    # Initial import of both A and B.
    service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_a,
                    lines=[
                        LineAmountInput(3, "24000.00"),
                        LineAmountInput(14, "1000.00"),
                    ],
                ),
                PropertyEntryInput(
                    property_id=prop_b,
                    lines=[LineAmountInput(3, "18000.00")],
                ),
            ],
        )
    )
    # A has 2 imported + 1 user-tracked; B has 1 imported.
    a_txns = _all_txns(repo, prop_a)
    assert len([t for t in a_txns if t.imported]) == 2
    assert len([t for t in a_txns if not t.imported]) == 1
    b_imported_before = [t for t in _all_txns(repo, prop_b) if t.imported]
    assert len(b_imported_before) == 1
    b_id_before = b_imported_before[0].id

    # Re-import ONLY A: change line 3, drop line 14 to zero, add line 5.
    result = service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_a,
                    lines=[
                        LineAmountInput(3, "25000.00"),
                        LineAmountInput(14, "0.00"),
                        LineAmountInput(5, "300.00"),
                    ],
                )
            ],
        )
    )
    assert result.is_ok
    assert result.value.entries[0].deleted_prior_count == 2

    # A's imported set now equals exactly the re-import's non-zero lines (3, 5);
    # the zeroed line 14 leaves no residual imported row.
    a_after = _all_txns(repo, prop_a)
    a_imported = {t.schedule_e_line: t for t in a_after if t.imported}
    assert set(a_imported) == {3, 5}
    assert a_imported[3].amount == Decimal("25000.00")
    assert a_imported[5].amount == Decimal("300.00")

    # The user-tracked transaction on A is untouched.
    user_rows = [t for t in a_after if not t.imported]
    assert len(user_rows) == 1
    assert user_rows[0].id == user_tracked_id
    assert user_rows[0].amount == Decimal("50.00")

    # B was omitted from the re-import: its imported set is untouched.
    b_after = [t for t in _all_txns(repo, prop_b) if t.imported]
    assert len(b_after) == 1
    assert b_after[0].id == b_id_before


# --- remove_imported_set -----------------------------------------------------


def test_remove_imported_set_happy_path(repo, files):
    user = UserContext(user_id=USER_ID)
    service = ImportService(repo, user, files)
    prop_id = _seed_property(repo, files)

    # One user-tracked + two imported rows for 2023.
    txn_svc = TransactionService(repo, files)
    txn_svc.create(
        TransactionInput(
            property_id=prop_id,
            date="2023-03-01",
            amount=Decimal("12.00"),
            type="expense",
            category_id="supplies",
            description=None,
        )
    )
    service.import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id=prop_id,
                    lines=[
                        LineAmountInput(3, "100.00"),
                        LineAmountInput(14, "200.00"),
                    ],
                )
            ],
        )
    )

    result = service.remove_imported_set(prop_id, 2023)
    assert result.is_ok
    assert result.value.deleted_count == 2
    assert result.value.property_id == prop_id
    assert result.value.tax_year == 2023

    remaining = _all_txns(repo, prop_id)
    assert len(remaining) == 1
    assert remaining[0].imported is False
    assert remaining[0].amount == Decimal("12.00")


def test_remove_imported_set_not_found_for_unowned_property(repo, files):
    service = ImportService(repo, UserContext(user_id=USER_ID), files)
    other_prop = _seed_property(repo, files, user_id=OTHER_USER_ID, name="Theirs")

    result = service.remove_imported_set(other_prop, 2023)
    assert not result.is_ok
    assert result.error.kind == "not_found"


def test_remove_imported_set_missing_property_not_found(service):
    result = service.remove_imported_set("does-not-exist", 2023)
    assert not result.is_ok
    assert result.error.kind == "not_found"
