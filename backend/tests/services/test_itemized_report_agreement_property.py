"""Property-based test: report, summary and downstream consumers agree.

Design Property 5 (Requirements 6.1-6.5): *for any* state of unmarked total
rows and itemized entries across several properties and tax years, the report
line 14 total for each (property, year) equals the Itemized_Summary line total,
the dashboard per-property summary and trend points equal the report totals, the
carryforward Schedule E net equals the sum of report nets, the combined report
equals the sum of per-property reports, and the CSV and JSON exports render the
same line 14 amount. The line's ``includes_imported`` flag equals whether any
contributing unmarked row is imported.

Everything runs the real services over moto-backed DynamoDB and S3. A source
scan example also asserts ``dashboard.py`` and ``carryforward.py`` contain no
reference to ``schedule_e_line`` or ``itemized`` (they consume the report only).
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

import logstead.services.carryforward as carryforward_module
import logstead.services.dashboard as dashboard_module
from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.carryforward import CarryforwardService
from logstead.services.dashboard import DashboardService
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService
from logstead.util.money import money_to_str

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
YEARS = (2021, 2022, 2023)  # all completed, so they are Data_Years
CATEGORY = "repairs"
LINE = 14


@contextlib.contextmanager
def _moto_services():
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
        report = ReportingService(transactions, depreciation, properties, files)
        itemized = ItemizedExpenseService(transactions)
        dashboard = DashboardService(
            properties, report, depreciation, transactions
        )
        carry = CarryforwardService(
            repo, USER, report, properties, transactions, depreciation
        )
        yield properties, transactions, itemized, report, dashboard, carry


# --- Strategies --------------------------------------------------------------

_amounts = st.integers(min_value=1, max_value=9_999_999).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
# (kind, year, amount, imported); kinds: total (unmarked repairs row),
# entry (itemized entry), rent (income), supplies (other expense).
_rows = st.tuples(
    st.sampled_from(("total", "entry", "entry", "rent", "supplies")),
    st.sampled_from(YEARS),
    _amounts,
    st.booleans(),
)
_state = st.lists(  # per property
    st.lists(_rows, max_size=8), min_size=1, max_size=3
)


def _line14_csv_amounts(content: bytes) -> list[str]:
    rows = csv.reader(io.StringIO(content.decode("utf-8")))
    return [r[3] for r in rows if len(r) == 4 and r[0] == str(LINE)]


def _line14_json_amounts(payload: dict) -> list[str]:
    columns = payload["properties"] if "properties" in payload else [payload]
    return [
        next(row["amount"] for row in col["lines"] if row["line"] == LINE)
        for col in columns
    ]


# Feature: itemized-expenses, Property 5: Report, summary and downstream consumers agree
@settings(deadline=None, max_examples=100)
@given(state=_state)
def test_report_summary_and_consumers_agree(state) -> None:
    """**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**"""
    with _moto_services() as (
        properties,
        transactions,
        itemized,
        report,
        dashboard,
        carry,
    ):
        ids: list[str] = []
        for index, rows in enumerate(state):
            created = properties.create(
                PropertyInput(
                    name=f"Agreement {index}",
                    address_text=f"{index} Agreement Way",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id
            ids.append(pid)
            for kind, year, amount, imported in rows:
                date = f"{year}-06-15"
                if kind == "entry":
                    res = itemized.create_entry(
                        pid,
                        CATEGORY,
                        EntryInput(
                            date=date,
                            amount=amount,
                            description="item",
                            tax_year=year,
                        ),
                    )
                else:
                    category_id = {
                        "total": CATEGORY,
                        "rent": "rents-received",
                        "supplies": "supplies",
                    }[kind]
                    res = transactions.create(
                        TransactionInput(
                            property_id=pid,
                            date=date,
                            amount=amount,
                            type="income" if kind == "rent" else "expense",
                            category_id=category_id,
                            imported=imported and kind == "total",
                        )
                    )
                assert res.is_ok, res.error

        # --- Per-(property, year): report vs itemized summary and model -----
        reports: dict[tuple[str, int], object] = {}
        for pid, rows in zip(ids, state):
            for year in YEARS:
                rpt = report.report_for(pid, year)
                assert rpt.is_ok, rpt.error
                reports[(pid, year)] = rpt.value
                summary = itemized.summary(pid, CATEGORY, year)
                assert summary.is_ok, summary.error
                line = rpt.value.line(LINE)
                assert line.total == summary.value.line_total

                totals = [a for k, y, a, _ in rows if k == "total" and y == year]
                entries = [a for k, y, a, _ in rows if k == "entry" and y == year]
                want = sum(totals, Decimal("0")) if totals else sum(
                    entries, Decimal("0")
                )
                assert line.total == Decimal(want).quantize(Decimal("0.01"))
                want_imported = any(
                    imp for k, y, _, imp in rows if k == "total" and y == year
                )
                assert line.includes_imported is want_imported

                # Per-property exports render the same line 14 amount.
                expected = money_to_str(line.total)
                csv_export = report.export_report(pid, year, "csv")
                json_export = report.export_report(pid, year, "json")
                assert csv_export.is_ok and json_export.is_ok
                assert _line14_csv_amounts(csv_export.value.content) == [expected]
                assert _line14_json_amounts(
                    json.loads(json_export.value.content)
                ) == [expected]

        # --- Dashboard per-property summary ---------------------------------
        for year in YEARS:
            summaries = {
                s.property_id: s for s in dashboard.per_property_summary(year)
            }
            for pid in ids:
                totals = reports[(pid, year)].totals
                s = summaries[pid]
                assert s.total_income == totals.total_income
                assert s.total_expenses == totals.total_expenses
                assert s.net == totals.net

        # --- Trend points ---------------------------------------------------
        trends = dashboard.trends_summary()
        for trend_year in trends.years:
            for point in trend_year.properties:
                totals = reports[(point.property_id, trend_year.tax_year)].totals
                assert point.total_income == totals.total_income
                assert point.total_expenses == totals.total_expenses
                assert point.net == totals.net

        # --- Carryforward Schedule E net ------------------------------------
        series = {y.tax_year: y for y in carry.reconcile().years}
        for year in YEARS:
            if year not in series:
                assert all(
                    reports[(pid, year)].totals.net == Decimal("0.00")
                    for pid in ids
                )
                continue
            want_net = sum(
                (reports[(pid, year)].totals.net for pid in ids), Decimal("0.00")
            )
            assert series[year].schedule_e_net == want_net

        # --- Combined report and its exports --------------------------------
        for year in YEARS:
            combined = report.combined_report(ids, year)
            assert combined.is_ok, combined.error
            cols = combined.value.properties
            assert [c.header.property_id for c in cols] == ids
            for field in ("total_income", "total_expenses", "net"):
                assert getattr(combined.value.totals, field) == sum(
                    (getattr(c.totals, field) for c in cols), Decimal("0.00")
                )
            expected = [
                money_to_str(reports[(pid, year)].line(LINE).total) for pid in ids
            ]
            assert [money_to_str(c.line(LINE).total) for c in cols] == expected
            csv_export = report.export_combined_report(ids, year, "csv")
            json_export = report.export_combined_report(ids, year, "json")
            assert csv_export.is_ok and json_export.is_ok
            assert _line14_csv_amounts(csv_export.value.content) == expected
            assert (
                _line14_json_amounts(json.loads(json_export.value.content))
                == expected
            )


def test_dashboard_and_carryforward_do_not_reference_itemized_or_line() -> None:
    """Dashboard and carryforward consume report totals only (Req 6.2-6.4)."""
    for module in (dashboard_module, carryforward_module):
        source = Path(module.__file__).read_text(encoding="utf-8").lower()
        assert "schedule_e_line" not in source, module.__name__
        assert "itemized" not in source, module.__name__
