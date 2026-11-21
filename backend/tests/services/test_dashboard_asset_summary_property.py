"""Property-based reconciliation tests for the dashboard depreciable-assets summary.

Feature: dashboard-assets-and-layout-polish — Requirement 6 (depreciation totals
reconcile with Schedule E Line 18). Design "Correctness Properties" 1 and 2.

``DashboardService.asset_summary(tax_year)`` (``services/dashboard.py``) returns,
per property the user owns, that property's depreciable-asset count and its
depreciation total for the year. The ``depreciation_total`` is derived from
``DepreciationService.property_depreciation_for_year(property_id, year)`` — the
**same** method that feeds Schedule E Line 18 in ``ReportingService``
(``DEPRECIATION_LINE == 18``). These two property tests drive that
reconciliation universally against moto-backed storage:

* **Property 1** asserts, for each generated property and tax year, that the
  endpoint's per-property ``depreciation_total`` equals that property's Schedule
  E report Line 18 total for the year (exact ``Decimal``).
* **Property 2** asserts, for a generated portfolio and tax year, that the sum
  over the endpoint's per-property ``depreciation_total`` equals the combined
  report's total Line 18 depreciation for the year (sum of each property
  column's Line 18 in ``combined_report(None, year)``), exact ``Decimal``.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 for the property-meta mirror + GSI2 for the tax-year partition the
report and ``property_depreciation_for_year`` read through) plus an S3 bucket
needed to construct the ``S3FileAdapter``, mirroring ``test_dashboard_net_property.py``
and ``test_report_depreciation_line_property.py``. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held at 100.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.dashboard import DashboardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import DEPRECIATION_LINE, ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed ``(DashboardService, ReportingService, PropertyService,
    DepreciationService)`` bound to freshly created resources so each Hypothesis
    example runs against a clean store with no aggregate faked. GSI1 is required
    by ``PropertyService.create`` (property-meta mirror); GSI2 is the tax-year
    partition both the report's Line 18 and ``property_depreciation_for_year``
    read through.
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
        reports = ReportingService(transactions, depreciation, properties)
        dashboard = DashboardService(properties, reports, depreciation)
        yield dashboard, reports, properties, depreciation


# --- Strategies --------------------------------------------------------------
#
# A random tax year is chosen per example; assets are placed in service in that
# year or up to a few years before it, so some schedules reach the target year
# with a full-year amount while others contribute a mid-month first-year (or a
# tail-year) amount. Recovery periods come from a realistic set including the
# 27.5-year residential default. Cost basis is a positive two-decimal money
# amount so no float ever enters the money path.

_tax_year = st.integers(min_value=2018, max_value=2030)

_asset_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("500000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_asset_recovery_periods = st.sampled_from(
    [Decimal("5"), Decimal("7"), Decimal("15"), Decimal("27.5"), Decimal("39")]
)


def _placed_dates_for_year(year: int) -> st.SearchStrategy[str]:
    """Placed-in-service dates spanning the target year and the 4 prior years."""
    return st.dates(
        min_value=dt.date(year - 4, 1, 1),
        max_value=dt.date(year, 12, 31),
    ).map(lambda d: d.isoformat())


@st.composite
def _asset_specs_for_year(draw, year: int):
    """A list of ``0..k`` (cost_basis, placed_in_service_date, recovery) specs."""
    n = draw(st.integers(min_value=0, max_value=4))
    placed_dates = _placed_dates_for_year(year)
    specs: list[tuple[Decimal, str, Decimal]] = []
    for _ in range(n):
        specs.append(
            (
                draw(_asset_cost_basis),
                draw(placed_dates),
                draw(_asset_recovery_periods),
            )
        )
    return specs


def _seed_property_with_assets(
    properties: PropertyService,
    depreciation: DepreciationService,
    name: str,
    address: str,
    asset_specs: list[tuple[Decimal, str, Decimal]],
) -> str:
    """Create a property and its depreciable assets through the real services.

    Each ``create_asset`` materializes the asset's schedule rows under the GSI2
    tax-year partition. Returns the new property id.
    """
    created = properties.create(
        PropertyInput(
            name=name,
            address_text=address,
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id

    for cost_basis, placed_date, recovery in asset_specs:
        asset_result = depreciation.create_asset(
            AssetInput(
                property_id=pid,
                description="Asset",
                cost_basis=cost_basis,
                placed_in_service_date=placed_date,
                recovery_period_years=recovery,
            )
        )
        assert asset_result.is_ok, asset_result.error
    return pid


def _report_line_18(reports: ReportingService, pid: str, year: int) -> Decimal:
    """The Schedule E report's Line 18 depreciation total for a property + year."""
    report = reports.report_for(pid, year)
    assert report.is_ok, report.error
    line_18 = report.value.line(DEPRECIATION_LINE)
    assert line_18 is not None
    return line_18.total


# Feature: dashboard-assets-and-layout-polish, Property 1: Per-property depreciation reconciles with Schedule E Line 18
@settings(deadline=None, max_examples=100)
@given(data=st.data(), year=_tax_year)
def test_per_property_depreciation_reconciles_with_schedule_e_line_18(
    data: st.DataObject, year: int
) -> None:
    """Endpoint per-property ``depreciation_total`` == that property's Line 18.

    Validates: Requirements 6.1, 6.2, 6.3
    """
    asset_specs = data.draw(_asset_specs_for_year(year))

    with _moto_service() as (dashboard, reports, properties, depreciation):
        pid = _seed_property_with_assets(
            properties,
            depreciation,
            name="Reconciliation Subject",
            address="1 Reconciliation Way",
            asset_specs=asset_specs,
        )

        summary = dashboard.asset_summary(year)
        assert summary.tax_year == year
        rows_by_pid = {row.property_id: row for row in summary.properties}
        assert pid in rows_by_pid

        row = rows_by_pid[pid]
        expected_line_18 = _report_line_18(reports, pid, year)

        # The dashboard figure and Schedule E Line 18 are the same authoritative
        # number — exact two-decimal Decimal equality.
        assert row.depreciation_total == expected_line_18, (
            f"asset_summary depreciation_total {row.depreciation_total} != "
            f"Schedule E Line 18 {expected_line_18} for {year}"
        )
        # And both equal the service's authoritative per-(property, year) figure.
        assert row.depreciation_total == depreciation.property_depreciation_for_year(
            pid, year
        )
        # Asset count reflects the seeded assets (schedule rows excluded).
        assert row.asset_count == len(asset_specs)


# Feature: dashboard-assets-and-layout-polish, Property 2: Portfolio depreciation reconciles with the combined report
@settings(deadline=None, max_examples=100)
@given(data=st.data(), year=_tax_year)
def test_portfolio_depreciation_reconciles_with_combined_report(
    data: st.DataObject, year: int
) -> None:
    """Sum of endpoint ``depreciation_total`` == combined report's summed Line 18.

    Validates: Requirements 6.1, 6.2, 6.3
    """
    portfolio_specs = data.draw(
        st.lists(_asset_specs_for_year(year), min_size=1, max_size=4)
    )

    with _moto_service() as (dashboard, reports, properties, depreciation):
        for p_index, asset_specs in enumerate(portfolio_specs):
            _seed_property_with_assets(
                properties,
                depreciation,
                name=f"Prop{p_index}",
                address=f"{p_index} Main St",
                asset_specs=asset_specs,
            )

        summary = dashboard.asset_summary(year)
        assert summary.tax_year == year

        # Sum of the endpoint's per-property depreciation totals.
        endpoint_total = sum(
            (row.depreciation_total for row in summary.properties),
            Decimal("0.00"),
        )

        # Combined report's total Line 18: sum of each property column's Line 18.
        combined = reports.combined_report(None, year)
        assert combined.is_ok, combined.error
        combined_line_18_total = Decimal("0.00")
        for column in combined.value.properties:
            line_18 = column.line(DEPRECIATION_LINE)
            assert line_18 is not None
            combined_line_18_total += line_18.total

        assert endpoint_total == combined_line_18_total, (
            f"portfolio asset_summary depreciation sum {endpoint_total} != "
            f"combined report Line 18 sum {combined_line_18_total} for {year}"
        )
