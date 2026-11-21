"""Report surfacing of the imported marker (schedule-e-import task 1.5, Req 7.4).

Verifies the additive report-surfacing fields added in task 1.4 against a
``moto``-backed table, composing the real Property, Transaction, and
Depreciation services (no faked aggregates), mirroring ``test_report.py``:

* a :class:`ReportLine` fed only by user-tracked transactions reports
  ``includes_imported`` False;
* a line with any imported contribution reports ``includes_imported`` True
  (even when it also has a user-tracked contribution);
* each :class:`OtherItem` carries the imported marker of its source
  transaction;
* line totals and ``net`` are identical whether the contributions are imported
  or user-tracked — the marker is purely surfacing and changes no aggregation
  math (schedule-e-import Req 7.4).
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import OTHER_LINE, ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI1 + GSI2) and S3 bucket."""
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
def properties(repo):
    return PropertyService(repo, USER)


@pytest.fixture
def transactions(aws, repo):
    _, s3 = aws
    return TransactionService(repo, S3FileAdapter(s3, BUCKET))


@pytest.fixture
def depreciation(repo):
    return DepreciationService(repo)


@pytest.fixture
def service(transactions, depreciation, properties):
    return ReportingService(transactions, depreciation, properties)


# --- Seeding helpers ---------------------------------------------------------


def _make_property(properties: PropertyService, name: str) -> str:
    result = properties.create(
        PropertyInput(
            name=name, address_text=f"{name} St", property_type="single_family"
        )
    )
    assert result.is_ok
    return result.value.id


def _txn(
    transactions: TransactionService,
    property_id: str,
    *,
    date: str,
    amount: str,
    type: str,
    category_id: str,
    description: str | None = None,
    imported: bool = False,
) -> None:
    result = transactions.create(
        TransactionInput(
            property_id=property_id,
            date=date,
            amount=Decimal(amount),
            type=type,
            category_id=category_id,
            description=description,
            imported=imported,
        )
    )
    assert result.is_ok, result.error


def _seed_mixed(transactions: TransactionService, pid: str, *, imported: bool) -> None:
    """Seed the same fixture either entirely user-tracked or entirely imported.

    Line 3 (rents): two income contributions.
    Line 14 (repairs): one expense contribution.
    Line 19 (other): two itemized contributions.
    """
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received", imported=imported)
    _txn(transactions, pid, date="2024-02-05", amount="1300.00",
         type="income", category_id="rents-received", imported=imported)
    _txn(transactions, pid, date="2024-04-05", amount="500.00",
         type="expense", category_id="repairs", imported=imported)
    _txn(transactions, pid, date="2024-06-05", amount="75.00",
         type="expense", category_id="other", description="HOA dues",
         imported=imported)
    _txn(transactions, pid, date="2024-07-05", amount="25.00",
         type="expense", category_id="other", description="Bank fees",
         imported=imported)


# --- Surfacing: includes_imported on lines -----------------------------------


def test_line_fed_only_by_user_tracked_is_not_marked_imported(
    service, properties, transactions
):
    pid = _make_property(properties, "UserOnly")
    _seed_mixed(transactions, pid, imported=False)

    report = service.report_for(pid, TAX_YEAR).value

    assert report.line(3).includes_imported is False
    assert report.line(14).includes_imported is False
    assert report.line(OTHER_LINE).includes_imported is False
    # Lines with no activity are also unmarked.
    assert report.line(5).includes_imported is False


def test_line_with_any_imported_contribution_is_marked(
    service, properties, transactions
):
    pid = _make_property(properties, "AllImported")
    _seed_mixed(transactions, pid, imported=True)

    report = service.report_for(pid, TAX_YEAR).value

    assert report.line(3).includes_imported is True
    assert report.line(14).includes_imported is True
    assert report.line(OTHER_LINE).includes_imported is True
    # A line with no contribution at all stays unmarked.
    assert report.line(5).includes_imported is False


def test_mixed_contributions_on_one_line_mark_the_line_imported(
    service, properties, transactions
):
    pid = _make_property(properties, "Mixed")
    # Line 3 gets one user-tracked and one imported contribution; the OR of the
    # per-contribution markers must mark the whole line imported.
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received", imported=False)
    _txn(transactions, pid, date="2024-02-05", amount="1300.00",
         type="income", category_id="rents-received", imported=True)
    # Line 14 is purely user-tracked and must remain unmarked.
    _txn(transactions, pid, date="2024-04-05", amount="500.00",
         type="expense", category_id="repairs", imported=False)

    report = service.report_for(pid, TAX_YEAR).value

    assert report.line(3).includes_imported is True
    assert report.line(14).includes_imported is False


# --- Surfacing: imported on each OtherItem -----------------------------------


def test_other_items_reflect_their_source_transaction_marker(
    service, properties, transactions
):
    pid = _make_property(properties, "OtherMix")
    _txn(transactions, pid, date="2024-06-05", amount="75.00",
         type="expense", category_id="other", description="HOA dues",
         imported=True)
    _txn(transactions, pid, date="2024-07-05", amount="25.00",
         type="expense", category_id="other", description="Bank fees",
         imported=False)

    report = service.report_for(pid, TAX_YEAR).value

    by_description = {item.description: item.imported for item in report.other_items}
    assert by_description == {"HOA dues": True, "Bank fees": False}


# --- Invariance: the marker changes no aggregation math ----------------------


def test_totals_and_net_unchanged_whether_contributions_are_imported(
    service, properties, transactions
):
    """The same fixture, once all user-tracked and once all imported, must
    produce identical per-line totals and ``net`` — the marker is additive
    surfacing only (schedule-e-import Req 7.4)."""
    pid_user = _make_property(properties, "InvariantUser")
    pid_imported = _make_property(properties, "InvariantImported")
    _seed_mixed(transactions, pid_user, imported=False)
    _seed_mixed(transactions, pid_imported, imported=True)

    user_report = service.report_for(pid_user, TAX_YEAR).value
    imported_report = service.report_for(pid_imported, TAX_YEAR).value

    # Every modeled line's total is identical regardless of the marker.
    user_totals = {ln.line: ln.total for ln in user_report.lines}
    imported_totals = {ln.line: ln.total for ln in imported_report.lines}
    assert user_totals == imported_totals

    # Spot-check the expected pre-feature totals so this isn't vacuously equal.
    assert user_totals[3] == Decimal("2500.00")       # 1200 + 1300
    assert user_totals[14] == Decimal("500.00")        # repairs
    assert user_totals[OTHER_LINE] == Decimal("100.00")  # 75 + 25

    # Report-level totals and net are unchanged by the marker.
    assert user_report.totals.total_income == imported_report.totals.total_income
    assert user_report.totals.total_expenses == imported_report.totals.total_expenses
    assert user_report.totals.net == imported_report.totals.net
    assert user_report.totals.net == Decimal("2500.00") - Decimal("600.00")

    # The Line 19 itemization amounts reconcile the same way in both.
    assert sum((i.amount for i in user_report.other_items), Decimal("0.00")) == (
        user_report.line(OTHER_LINE).total
    )
    assert sum(
        (i.amount for i in imported_report.other_items), Decimal("0.00")
    ) == imported_report.line(OTHER_LINE).total
