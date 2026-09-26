"""Integration test for Schedule E report export (task 14.8, Requirement 10.7).

This is an **integration** test: it exercises the full report-export path against
a real ``moto``-backed DynamoDB table (base + GSI1 + GSI2) and S3 bucket, and it
drives the returned pre-signed download URL the way a browser would — with an
actual HTTP client (``requests``) — so the whole *generate -> serialize -> store
-> download* round-trip is verified end to end, not just the shape of the export.

It deliberately goes further than, and complements:

* ``tests/services/test_report.py`` — inline export verification that asserts the
  object lands in S3 under ``exports/`` and that ``export.content`` parses back
  with the expected totals. That test reads the stored bytes with the boto3
  client (``get_object``); it never fetches the ``download_url``.
* ``tests/integration/test_s3_operations.py`` — the moto pre-signed URL /
  ``requests`` round-trip pattern this test reuses, but for photos/receipts, not
  a generated report.

What this integration test adds on top of the above:

* the returned ``download_url`` is **actually usable** — a GET through it returns
  the exact ``export.content`` bytes (Requirements 10.7, 4.1/4.3 for the URL);
* the downloaded bytes **parse back into the expected report** — line totals and
  net rendered as fixed two-decimal strings (Requirement 13.3), Line 18 sourced
  from depreciation (Requirement 10.3), Line 19 "Other" itemized
  (Requirement 10.5);
* both CSV and JSON exports round-trip through the download URL;
* the **combined** portfolio export round-trips through its download URL too
  (Requirement 10.6/10.7).

The report is seeded through the *real* Property, Transaction, and Depreciation
services so nothing about the aggregation is faked.

moto's ``generate_presigned_url`` produces URLs its in-memory S3 backend accepts
over HTTP, so a ``requests`` round-trip against them is genuine within the mock.
"""

from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

import boto3
import pytest
import requests
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
TAX_YEAR = 2024


# --- moto fixtures (base + GSI1 + GSI2 + S3) ---------------------------------


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
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def files(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


@pytest.fixture
def properties(repo):
    return PropertyService(repo, USER)


@pytest.fixture
def transactions(files, repo):
    return TransactionService(repo, files)


@pytest.fixture
def depreciation(repo):
    return DepreciationService(repo)


@pytest.fixture
def service(transactions, depreciation, properties, files):
    return ReportingService(transactions, depreciation, properties, files)


# --- Seeding helpers ---------------------------------------------------------


def _make_property(properties: PropertyService, name: str) -> str:
    result = properties.create(
        PropertyInput(
            name=name, address_text=f"{name} St", property_type="single_family"
        )
    )
    assert result.is_ok, result.error
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


def _object_keys(s3_client) -> set[str]:
    listed = s3_client.list_objects_v2(Bucket=BUCKET)
    return {obj["Key"] for obj in listed.get("Contents", [])}


def _seed_full_property(properties, transactions, depreciation, name: str) -> str:
    """Seed a property with income, expenses (incl. Other + description), an
    asset (Line 18), and usage days, exercising the real services.

    Returns the property id. Totals for the seeded data:
        income   = 1200 + 1300 + 150               = 2650.00
        expenses = 500 (repairs) + 200 (utilities)
                   + 100 (two Other) + depreciation
    """
    pid = _make_property(properties, name)
    properties.set_usage_days(pid, TAX_YEAR, fair_rental_days=300, personal_use_days=10)

    # Income: two rents (Line 3) + a royalty (Line 4).
    _txn(transactions, pid, date="2024-01-05", amount="1200.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-02-05", amount="1300.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid, date="2024-03-05", amount="150.00",
         type="income", category_id="royalties-received")

    # Expenses: repairs (Line 14), utilities (Line 17), two Other (Line 19).
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
    assert asset.is_ok, asset.error
    return pid


def _download(url: str) -> requests.Response:
    """Fetch a moto pre-signed GET URL over HTTP the way a browser would."""
    resp = requests.get(url)
    assert resp.status_code == 200, resp.text
    return resp


def _two_decimal(value: str) -> bool:
    """True if a rendered money string is a fixed two-decimal string."""
    return isinstance(value, str) and "." in value and len(value.split(".")[1]) == 2


# --- CSV export: download URL round-trip -------------------------------------


def test_csv_export_download_url_returns_exact_bytes_and_parses_back(
    service, depreciation, properties, transactions, s3_client
):
    """Export CSV, download via the pre-signed URL, and verify the bytes equal
    ``export.content`` and parse back to the expected line totals + net."""
    pid = _seed_full_property(properties, transactions, depreciation, "CsvExporter")
    dep = depreciation.property_depreciation_for_year(pid, TAX_YEAR)
    assert dep > Decimal("0.00")

    result = service.export_report(pid, TAX_YEAR, "csv")
    assert result.is_ok, result.error
    export = result.value

    # The object exists in S3 under the exports/ prefix at the returned key.
    assert export.key.startswith("exports/")
    assert pid in export.key
    assert str(TAX_YEAR) in export.key
    assert export.key in _object_keys(s3_client)
    assert export.content_type == "text/csv"

    # Download through the returned pre-signed GET URL returns the EXACT bytes.
    assert export.download_url.startswith("https://")
    assert BUCKET in export.download_url
    resp = _download(export.download_url)
    assert resp.content == export.content

    # The downloaded bytes parse back to the expected report.
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
    line_rows = {r[0]: r for r in rows if len(r) == 4 and r[0].isdigit()}
    assert line_rows["3"][3] == "2500.00"    # rents 1200 + 1300
    assert line_rows["4"][3] == "150.00"     # royalties
    assert line_rows["14"][3] == "500.00"    # repairs
    assert line_rows["17"][3] == "200.00"    # utilities
    assert line_rows["19"][3] == "100.00"    # two Other, 75 + 25
    # Line 18 is sourced from depreciation, not a transaction category.
    assert line_rows["18"][3] == f"{dep:.2f}"

    # Line 19 "Other" is itemized with descriptions in the CSV.
    flat = resp.content.decode("utf-8")
    assert "HOA dues" in flat
    assert "Bank fees" in flat

    # Totals + net render as fixed two-decimal strings.
    total_income = next(r for r in rows if r and r[0] == "Total Income")
    total_expenses = next(r for r in rows if r and r[0] == "Total Expenses")
    net_row = next(r for r in rows if r and r[0] == "Net")
    assert total_income[1] == "2650.00"
    expected_expenses = Decimal("800.00") + dep  # 500 + 200 + 100 + dep
    assert total_expenses[1] == f"{expected_expenses:.2f}"
    assert net_row[1] == f"{(Decimal('2650.00') - expected_expenses):.2f}"
    assert all(_two_decimal(cell[3]) for cell in line_rows.values())


# --- JSON export: download URL round-trip ------------------------------------


def test_json_export_download_url_returns_exact_bytes_and_parses_back(
    service, depreciation, properties, transactions, s3_client
):
    """Export JSON, download via the pre-signed URL, and verify the bytes equal
    ``export.content`` and parse back to the expected report structure."""
    pid = _seed_full_property(properties, transactions, depreciation, "JsonExporter")
    dep = depreciation.property_depreciation_for_year(pid, TAX_YEAR)

    result = service.export_report(pid, TAX_YEAR, "json")
    assert result.is_ok, result.error
    export = result.value

    assert export.key.startswith("exports/")
    assert export.key in _object_keys(s3_client)
    assert export.content_type == "application/json"

    resp = _download(export.download_url)
    assert resp.content == export.content

    payload = json.loads(resp.content.decode("utf-8"))
    lines = {row["line"]: row["amount"] for row in payload["lines"]}
    assert lines[3] == "2500.00"
    assert lines[4] == "150.00"
    assert lines[14] == "500.00"
    assert lines[17] == "200.00"
    assert lines[19] == "100.00"
    assert lines[18] == f"{dep:.2f}"  # Line 18 from depreciation

    # Line 19 "Other" is itemized and reconciles to the line total.
    other_items = {
        (item["description"], item["amount"]) for item in payload["other_items"]
    }
    assert other_items == {("HOA dues", "75.00"), ("Bank fees", "25.00")}
    other_sum = sum(
        (Decimal(item["amount"]) for item in payload["other_items"]), Decimal("0.00")
    )
    assert f"{other_sum:.2f}" == lines[19]

    # Totals + net render as fixed two-decimal strings.
    totals = payload["totals"]
    expected_expenses = Decimal("800.00") + dep
    assert totals["total_income"] == "2650.00"
    assert totals["total_expenses"] == f"{expected_expenses:.2f}"
    assert totals["net"] == f"{(Decimal('2650.00') - expected_expenses):.2f}"
    assert all(_two_decimal(v) for v in lines.values())
    assert all(_two_decimal(v) for v in totals.values())


# --- Combined portfolio export: download URL round-trip (10.6/10.7) ----------


def test_combined_export_download_url_round_trips(
    service, depreciation, properties, transactions, s3_client
):
    """A combined portfolio export downloads through its pre-signed URL and the
    downloaded bytes parse back to the portfolio totals."""
    pid_a = _make_property(properties, "PortA")
    pid_b = _make_property(properties, "PortB")
    _txn(transactions, pid_a, date="2024-01-05", amount="1000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_a, date="2024-02-05", amount="200.00",
         type="expense", category_id="repairs")
    _txn(transactions, pid_b, date="2024-03-05", amount="3000.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-04-05", amount="500.00",
         type="expense", category_id="utilities")

    result = service.export_combined_report([pid_a, pid_b], TAX_YEAR, "json")
    assert result.is_ok, result.error
    export = result.value

    assert export.key.startswith("exports/combined/")
    assert str(TAX_YEAR) in export.key
    assert export.key in _object_keys(s3_client)

    resp = _download(export.download_url)
    assert resp.content == export.content

    payload = json.loads(resp.content.decode("utf-8"))
    assert payload["tax_year"] == TAX_YEAR
    assert len(payload["properties"]) == 2
    # Portfolio totals equal the per-property sums, two-decimal strings.
    totals = payload["totals"]
    assert totals["total_income"] == "4000.00"      # 1000 + 3000
    assert totals["total_expenses"] == "700.00"     # 200 + 500
    assert totals["net"] == "3300.00"               # 4000 - 700
    assert all(_two_decimal(v) for v in totals.values())


def test_combined_csv_export_download_url_round_trips(
    service, depreciation, properties, transactions, s3_client
):
    """The combined CSV export is downloadable via its URL and the bytes match."""
    pid_a = _make_property(properties, "CsvPortA")
    pid_b = _make_property(properties, "CsvPortB")
    _txn(transactions, pid_a, date="2024-01-05", amount="1500.00",
         type="income", category_id="rents-received")
    _txn(transactions, pid_b, date="2024-01-05", amount="500.00",
         type="income", category_id="rents-received")

    result = service.export_combined_report([pid_a, pid_b], TAX_YEAR, "csv")
    assert result.is_ok, result.error
    export = result.value

    assert export.key.startswith("exports/combined/")
    assert export.content_type == "text/csv"
    assert export.key in _object_keys(s3_client)

    resp = _download(export.download_url)
    assert resp.content == export.content

    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
    assert ["Combined Schedule E Report"] in rows
    # Portfolio totals block ends the file; the last Net row is the portfolio net.
    portfolio_net = [r for r in rows if r and r[0] == "Net" and len(r) == 2][-1]
    assert portfolio_net[1] == "2000.00"  # 1500 + 500, no expenses
