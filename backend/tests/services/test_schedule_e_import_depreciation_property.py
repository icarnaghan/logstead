"""Property-based test for Schedule E Import Property 5 (task 5.5).

Design Property 5 (Requirements 5.1, 5.3): *for any* Import_Submission (including
one that attempts to supply a Line 18 amount), the ``ImportService`` SHALL create
no transaction on Schedule E Line 18 and SHALL persist no depreciation data;
consequently the derived report's Line 18 total for each imported
``(Property, Tax_Year)`` comes solely from depreciation schedules (the zero
Money_Value when none exists).

Line 18 (Depreciation) is intentionally absent from the seeded
``CATEGORY_CATALOG``, so it is neither mappable nor synthesizable: a defensive
check in ``ImportService._validate`` rejects any ``schedule_e_line == 18`` in the
payload (Requirement 5.1). ``ReportingService`` fills the report's Line 18 solely
from ``DepreciationService.property_depreciation_for_year`` (Requirement 5.3), so
when the import writes no depreciation schedule the derived Line 18 total is
``0.00``.

This test drives both arms universally. The submission generator produces two
kinds of entries:

* **sneak-18 entries** — an entry that carries a ``schedule_e_line == 18`` line
  (optionally alongside otherwise-valid lines). Any submission containing one
  must be rejected with a ``validation`` failure, and nothing may be written.
* **valid non-18 entries** — one or more lines drawn only from the modeled set
  (income 3-4, expense 5-17, 19), at least one non-zero. After an accepted
  import, no transaction carries ``schedule_e_line == 18`` and the derived
  report's Line 18 total is ``0.00`` because the import wrote no depreciation
  schedule.

Each example provisions its own moto-backed single table (base + GSI1 for the
property meta mirror + GSI2 for the tax-year partition) plus an S3 bucket,
mirroring the sibling service/report property tests. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held at 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import DEPRECIATION_LINE, ReportingService
from logstead.services.schedule_e_import import ImportService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-sub-1"

# The modeled Schedule E lines a submission may carry (income 3-4, expense
# 5-17, 19). Line 18 is intentionally absent from the catalog (Requirement 5.1).
_ALLOWED_LINES = tuple(sorted(c.schedule_e_line for c in CATEGORY_CATALOG))
_DESCRIPTION_LINES = frozenset(
    c.schedule_e_line for c in CATEGORY_CATALOG if c.requires_description
)
_ZERO = Decimal("0.00")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields ``(ImportService, PropertyService, TransactionService,
    ReportingService)`` bound to freshly created resources so each Hypothesis
    example runs against a clean store.
    """
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

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, files)
        depreciation = DepreciationService(repo)
        report = ReportingService(transactions, depreciation, properties)
        imports = ImportService(repo, UserContext(user_id=USER), files)
        yield imports, properties, transactions, report


# --- Strategies --------------------------------------------------------------

_tax_years = st.integers(min_value=2000, max_value=2099)

# Positive two-decimal money strings (so a drawn line is a non-zero amount).
_positive_money = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")

_line_18_money = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")


def _line(line_number: int, amount: str) -> LineAmountInput:
    """Build a line, supplying a Line 19 description where required."""
    description = "Other item" if line_number in _DESCRIPTION_LINES else None
    return LineAmountInput(
        schedule_e_line=line_number, amount=amount, description=description
    )


@st.composite
def _valid_lines(draw) -> list[LineAmountInput]:
    """A non-empty set of distinct modeled lines, each with a positive amount."""
    chosen = draw(
        st.lists(
            st.sampled_from(_ALLOWED_LINES),
            min_size=1,
            max_size=len(_ALLOWED_LINES),
            unique=True,
        )
    )
    return [_line(n, draw(_positive_money)) for n in chosen]


@st.composite
def _sneak_18_lines(draw) -> list[LineAmountInput]:
    """A set of lines that includes a ``schedule_e_line == 18`` amount.

    Mixes in zero or more otherwise-valid modeled lines so the illegal Line 18
    can appear alone or hidden among legitimate lines; order is varied so Line 18
    is not always first.
    """
    other = draw(
        st.lists(
            st.sampled_from(_ALLOWED_LINES),
            min_size=0,
            max_size=4,
            unique=True,
        )
    )
    lines = [_line(n, draw(_positive_money)) for n in other]
    insert_at = draw(st.integers(min_value=0, max_value=len(lines)))
    lines.insert(
        insert_at,
        LineAmountInput(schedule_e_line=18, amount=draw(_line_18_money)),
    )
    return lines


# Feature: schedule-e-import, Property 5: depreciation / Line 18 is never written
@settings(deadline=None, max_examples=100)
@given(
    tax_year=_tax_years,
    attempts_18=st.booleans(),
    valid_lines=_valid_lines(),
    sneak_lines=_sneak_18_lines(),
)
def test_line_18_depreciation_is_never_written(
    tax_year: int,
    attempts_18: bool,
    valid_lines: list[LineAmountInput],
    sneak_lines: list[LineAmountInput],
) -> None:
    """Line 18 is never accepted or written; derived Line 18 stays 0.00.

    Validates: Requirements 5.1, 5.3
    """
    with _moto_service() as (imports, properties, transactions, report):
        created = properties.create(
            PropertyInput(name="Subject", address_text="1 Main St")
        )
        assert created.is_ok, created.error
        pid = created.value.id

        if attempts_18:
            # Arm 1: a submission that tries to sneak a Line 18 amount in must be
            # rejected as validation, and NOTHING may be written (Requirement
            # 5.1 / all-or-nothing).
            submission = ImportSubmission(
                tax_year=tax_year,
                entries=[PropertyEntryInput(property_id=pid, lines=sneak_lines)],
            )
            result = imports.import_schedule_e(submission)

            assert not result.is_ok
            assert result.error.kind == "validation"
            # No transaction was written at all for the rejected submission.
            assert transactions.list_for_property(pid).value == []
            assert transactions.list_for_property(pid, tax_year).value == []
        else:
            # Arm 2: a valid non-18 import. After it is accepted, no transaction
            # may carry schedule_e_line == 18, and the derived report's Line 18
            # total must be 0.00 because the import wrote no depreciation
            # schedule (Requirement 5.3).
            submission = ImportSubmission(
                tax_year=tax_year,
                entries=[PropertyEntryInput(property_id=pid, lines=valid_lines)],
            )
            result = imports.import_schedule_e(submission)
            assert result.is_ok, result.error

            # No synthesized transaction (nor any transaction) carries Line 18.
            all_txns = transactions.list_for_property(pid).value
            assert all_txns, "a valid import must write at least one row"
            assert all(t.schedule_e_line != DEPRECIATION_LINE for t in all_txns)
            in_year = transactions.list_for_property(pid, tax_year).value
            assert all(t.schedule_e_line != DEPRECIATION_LINE for t in in_year)

            # The derived report's Line 18 comes solely from depreciation
            # schedules; the import created none, so it is exactly 0.00.
            rpt = report.report_for(pid, tax_year)
            assert rpt.is_ok, rpt.error
            line_18 = rpt.value.line(DEPRECIATION_LINE)
            assert line_18 is not None
            assert line_18.total == _ZERO
