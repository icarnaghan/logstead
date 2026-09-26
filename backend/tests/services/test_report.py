"""Verification for the Schedule E Report Service (task 14.1, Requirement 10).

Exercises :class:`ReportingService` end-to-end against a ``moto``-backed table
(base + GSI2) and S3 bucket, composing the real Property, Transaction, and
Depreciation services so no aggregate is faked. Coverage mirrors task 14.1:

* per-line aggregation sums a year's transactions onto their Schedule E line
  (Requirement 10.1);
* the header carries the property address / type and stored fair-rental /
  personal-use days (Requirement 10.2);
* Line 18 comes from the depreciation schedules (Requirement 10.3);
* Line 19 "Other" is itemized and the items reconcile to the line total
  (Requirement 10.5);
* total income, total expenses (incl. Line 18), and net balance
  (Requirement 10.4);
* the combined report sums two properties into a portfolio totals column
  (Requirement 10.6).

The Property-based tests (14.3-14.7), export (14.2), and the export integration
test (14.8) are intentionally out of scope here.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import (
    DEPRECIATION_LINE,
    OTHER_LINE,
    ReportingService,
)
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
        PropertyInput(name=name, address_text=f"{name} St", property_type="single_family")
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
) -> None:
    result = transactions.create(
        TransactionInput(
            property_id=property_id,
            date=date,
            amount=Decimal(amount),
            type=type,
            category_id=category_id,
            description=description,
        )
    )
    assert result.is_ok, result.error


# --- Per-property report -----------------------------------------------------


def test_report_aggregates_lines_itemizes_other_and_balances(
    service, properties, transactions, depreciation
):
    pid = _make_property(properties, "Alpha")
    properties.set_usage_days(pid, TAX_YEAR, fair_rental_days=300, personal_use_days=10)

    # Income: two rent transactions (Line 3) + a royalty (Line 4).
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-02-05", amount="1300.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-03-05", amount="150.00",
         type="income", category_id="royalties-received")

    # Expenses: repairs (Line 14), utilities (Line 17), and two Other (Line 19).
    _txn(transactions, pid, date="2024-04-05", amount="500.00",
         type="expense", category_id="repairs")
    _txn(transactions, pid, date="2024-05-05", amount="200.00",
         type="expense", category_id="utilities")
    _txn(transactions, pid, date="2024-06-05", amount="75.00",
         type="expense", category_id="other", description="HOA dues")
    _txn(transactions, pid, date="2024-07-05", amount="25.00",
         type="expense", category_id="other", description="Bank fees")

    # An asset placed in service in 2024 -> Line 18 depreciation for the year.
    asset = depreciation.create_asset(
        AssetInput(
            property_id=pid,
            description="Appliances",
            cost_basis=Decimal("13750.00"),
            placed_in_service_date="2024-01-15",
            recovery_period_years=Decimal("27.5"),
        )
    )
    assert asset.is_ok
    dep_2024 = depreciation.property_depreciation_for_year(pid, TAX_YEAR)
    assert dep_2024 > Decimal("0.00")

    result = service.report_for(pid, TAX_YEAR)
    assert result.is_ok
    report = result.value

    # Header (Requirement 10.2).
    assert report.header.property_name == "Alpha"
    assert report.header.address == "Alpha St"
    assert report.header.property_type == "single_family"
    assert report.header.tax_year == TAX_YEAR
    assert report.header.fair_rental_days == 300
    assert report.header.personal_use_days == 10

    # Per-line sums (Requirement 10.1).
    assert report.line(3).total == Decimal("2500.00")   # rents 1200 + 1300
    assert report.line(4).total == Decimal("150.00")    # royalties
    assert report.line(14).total == Decimal("500.00")   # repairs
    assert report.line(17).total == Decimal("200.00")   # utilities
    assert report.line(OTHER_LINE).total == Decimal("100.00")  # 75 + 25
    # A line with no activity is present and zero.
    assert report.line(5).total == Decimal("0.00")

    # Line 18 comes from the depreciation schedules (Requirement 10.3).
    assert report.line(DEPRECIATION_LINE).total == dep_2024
    assert report.line(DEPRECIATION_LINE).kind == "expense"

    # Line 19 itemization reconciles to the line total (Requirement 10.5).
    assert {(i.description, i.amount) for i in report.other_items} == {
        ("HOA dues", Decimal("75.00")),
        ("Bank fees", Decimal("25.00")),
    }
    assert sum((i.amount for i in report.other_items), Decimal("0.00")) == (
        report.line(OTHER_LINE).total
    )

    # Totals + net (Requirement 10.4). Expenses include Line 18.
    expected_income = Decimal("2650.00")
    expected_expenses = Decimal("800.00") + dep_2024  # 500 + 200 + 100 + dep
    assert report.totals.total_income == expected_income
    assert report.totals.total_expenses == expected_expenses
    assert report.totals.net == expected_income - expected_expenses

    # Net balances against the summed line totals directly.
    income_from_lines = sum(
        (ln.total for ln in report.lines if ln.kind == "income"), Decimal("0.00")
    )
    expense_from_lines = sum(
        (ln.total for ln in report.lines if ln.kind == "expense"), Decimal("0.00")
    )
    assert report.totals.net == income_from_lines - expense_from_lines


def test_report_defaults_missing_usage_days_to_zero(service, properties, transactions):
    pid = _make_property(properties, "NoUsage")
    _txn(transactions, pid, date="2024-01-05", amount="100.00",
         type="income", category_id="rents-received")

    report = service.report_for(pid, TAX_YEAR).value
    assert report.header.fair_rental_days == 0
    assert report.header.personal_use_days == 0


def test_report_excludes_out_of_year_transactions(service, properties, transactions):
    pid = _make_property(properties, "YearScoped")
    _txn(transactions, pid, date="2024-06-01", amount="1000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2023-06-01", amount="9999.00",
         type="income", category_id="rents-received")

    report = service.report_for(pid, TAX_YEAR).value
    assert report.line(3).total == Decimal("1000.00")


def test_report_for_unknown_property_is_not_found(service):
    result = service.report_for("does-not-exist", TAX_YEAR)
    assert not result.is_ok
    assert result.error.kind == "not_found"


def test_report_is_reproducible(service, properties, transactions):
    pid = _make_property(properties, "Repro")
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-02-05", amount="300.00",
         type="expense", category_id="repairs")

    first = service.report_for(pid, TAX_YEAR).value
    second = service.report_for(pid, TAX_YEAR).value
    assert first == second


# --- Combined portfolio report (Requirement 10.6) ----------------------------


def test_combined_report_totals_equal_per_property_sums(
    service, properties, transactions
):
    pid_a = _make_property(properties, "PropA")
    pid_b = _make_property(properties, "PropB")

    _txn(transactions, pid_a, date="2024-01-05", amount="2000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_a, date="2024-02-05", amount="500.00",
         type="expense", category_id="repairs")

    _txn(transactions, pid_b, date="2024-03-05", amount="3000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-04-05", amount="1200.00",
         type="expense", category_id="utilities")

    result = service.combined_report([pid_a, pid_b], TAX_YEAR)
    assert result.is_ok
    combined = result.value

    assert combined.tax_year == TAX_YEAR
    assert len(combined.properties) == 2

    sum_income = sum(
        (c.totals.total_income for c in combined.properties), Decimal("0.00")
    )
    sum_expenses = sum(
        (c.totals.total_expenses for c in combined.properties), Decimal("0.00")
    )
    sum_net = sum((c.totals.net for c in combined.properties), Decimal("0.00"))

    assert combined.totals.total_income == sum_income      # 5000.00
    assert combined.totals.total_expenses == sum_expenses  # 1700.00
    assert combined.totals.net == sum_net                  # 3300.00
    assert combined.totals.total_income == Decimal("5000.00")
    assert combined.totals.total_expenses == Decimal("1700.00")
    assert combined.totals.net == Decimal("3300.00")


def test_combined_report_over_all_user_properties(service, properties, transactions):
    pid_a = _make_property(properties, "OnlyA")
    pid_b = _make_property(properties, "OnlyB")
    _txn(transactions, pid_a, date="2024-01-05", amount="1000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-01-05", amount="500.00",
         type="income", category_id="rents-received")

    combined = service.combined_report(None, TAX_YEAR).value
    assert {c.header.property_id for c in combined.properties} == {pid_a, pid_b}
    assert combined.totals.total_income == Decimal("1500.00")


# --- Report export (task 14.2, Requirement 10.7) ----------------------------
#
# Inline verification only: generate a report, export it, and assert the file
# landed in S3 under the exports/ prefix, that its content parses back with the
# expected line totals + net rendered as two-decimal strings, and that a
# pre-signed GET URL is returned. The full export integration test (14.8) and
# the property tests (14.3-14.7) remain out of scope here.

import csv as _csv
import io as _io
import json as _json


@pytest.fixture
def files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture
def export_service(transactions, depreciation, properties, files):
    return ReportingService(transactions, depreciation, properties, files)


def _s3_object_keys(s3_client) -> set[str]:
    listed = s3_client.list_objects_v2(Bucket=BUCKET)
    return {obj["Key"] for obj in listed.get("Contents", [])}


def test_export_report_csv_stores_in_s3_and_returns_download_url(
    export_service, properties, transactions, aws
):
    _, s3 = aws
    pid = _make_property(properties, "Exporter")
    properties.set_usage_days(pid, TAX_YEAR, fair_rental_days=200, personal_use_days=5)
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-02-05", amount="300.00",
         type="expense", category_id="repairs")
    _txn(transactions, pid, date="2024-03-05", amount="50.00",
         type="expense", category_id="other", description="HOA dues")

    result = export_service.export_report(pid, TAX_YEAR, "csv")
    assert result.is_ok, result.error
    export = result.value

    # Landed in S3 under the exports/ prefix at the returned key.
    assert export.key.startswith("exports/")
    assert pid in export.key
    assert str(TAX_YEAR) in export.key
    assert export.key in _s3_object_keys(s3)
    assert export.content_type == "text/csv"

    # A pre-signed GET URL is returned for download.
    assert export.download_url.startswith("https://")
    assert BUCKET in export.download_url

    # The stored bytes match what was returned.
    stored = s3.get_object(Bucket=BUCKET, Key=export.key)["Body"].read()
    assert stored == export.content

    # Parse the CSV back and verify a couple of line totals + net render as
    # two-decimal strings.
    rows = list(_csv.reader(_io.StringIO(export.content.decode("utf-8"))))
    line_rows = {
        r[0]: r for r in rows if len(r) == 4 and r[0].isdigit()
    }
    assert line_rows["3"][3] == "1200.00"   # rents
    assert line_rows["14"][3] == "300.00"   # repairs
    assert line_rows["19"][3] == "50.00"    # other
    net_row = next(r for r in rows if r and r[0] == "Net")
    assert net_row[1] == "850.00"           # 1200 - (300 + 50)


def test_export_report_json_round_trips_line_totals_and_net(
    export_service, properties, transactions, aws
):
    _, s3 = aws
    pid = _make_property(properties, "JsonExporter")
    _txn(transactions, pid, date="2024-01-05", amount="2000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-02-05", amount="500.00",
         type="expense", category_id="utilities")

    result = export_service.export_report(pid, TAX_YEAR, "json")
    assert result.is_ok, result.error
    export = result.value

    assert export.key.startswith("exports/")
    assert export.key in _s3_object_keys(s3)
    assert export.content_type == "application/json"

    payload = _json.loads(export.content.decode("utf-8"))
    lines = {row["line"]: row["amount"] for row in payload["lines"]}
    assert lines[3] == "2000.00"
    assert lines[17] == "500.00"
    assert payload["totals"]["net"] == "1500.00"
    # Money is serialized as two-decimal strings.
    assert all(isinstance(v, str) and "." in v for v in lines.values())


def test_export_combined_report_stores_under_exports_prefix(
    export_service, properties, transactions, aws
):
    _, s3 = aws
    pid_a = _make_property(properties, "CombA")
    pid_b = _make_property(properties, "CombB")
    _txn(transactions, pid_a, date="2024-01-05", amount="1000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-01-05", amount="500.00",
         type="income", category_id="rents-received")

    result = export_service.export_combined_report([pid_a, pid_b], TAX_YEAR, "json")
    assert result.is_ok, result.error
    export = result.value
    assert export.key.startswith("exports/combined/")
    assert export.key in _s3_object_keys(s3)

    payload = _json.loads(export.content.decode("utf-8"))
    assert len(payload["properties"]) == 2
    assert payload["totals"]["total_income"] == "1500.00"


def test_export_report_rejects_unsupported_format(export_service, properties):
    pid = _make_property(properties, "BadFormat")
    result = export_service.export_report(pid, TAX_YEAR, "pdf")  # type: ignore[arg-type]
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "format"


def test_export_report_unknown_property_is_not_found(export_service):
    result = export_service.export_report("nope", TAX_YEAR, "csv")
    assert not result.is_ok
    assert result.error.kind == "not_found"
