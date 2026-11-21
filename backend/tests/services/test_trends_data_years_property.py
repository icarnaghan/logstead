"""Property test — the trends series spans exactly the Data_Years.

Feature: dashboard-year-over-year-trends, Property 4: The series contains
exactly the Data_Years, ascending, no gaps, no cap.

Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5

``DashboardService.trends_summary()`` (``services/dashboard.py``) derives the
span of its ``years`` tuple from ``_derive_data_years(properties)``: the union,
across every owned property, of (a) the tax years that have transactions
(``int(txn.date[:4])``) and (b) the tax years that have depreciation schedule
rows (``row.tax_year``). This property drives that derivation universally and
asserts the resulting ``tax_year`` sequence is *exactly* that union —

    * ascending chronological order (Req 2.3),
    * each Data_Year present exactly once, none omitted, no duplicates
      (Req 2.1, 2.2),
    * non-contiguous years preserved with no gap year inserted (Req 2.4), and
    * no fixed window or cap applied, from one Data_Year up to the full set
      (Req 2.5).

Strategy
--------
Each example generates, per property, an explicit set of transaction years
(deliberately non-contiguous and including duplicates so the de-dup and
no-gap behavior is exercised) plus a set of depreciation assets placed in
varied years. Transaction years are fully controllable — ``int(txn.date[:4])``
is exactly the year the generator chose — so they contribute a known, exact
set. Depreciation schedule rows span several years from a placed-in-service
date, so the expected depreciation years are read back from the real
materialized schedules (the same ``list_assets`` + ``schedule_for`` path the
service uses) rather than predicted, keeping the oracle exact without
duplicating the schedule maths.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring ``test_dashboard_net_property.py`` and
``test_dashboard_asset_summary_property.py``. Per-example provisioning is not
instantaneous, so the deadline is disabled and the example count is held at 100.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.dashboard import DashboardService, _latest_tax_year
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed ``(DashboardService, PropertyService,
    TransactionService, DepreciationService)`` bound to freshly created
    resources so each Hypothesis example runs against a clean store. GSI1 is
    required by ``PropertyService.create`` (property-meta mirror); GSI2 is the
    tax-year partition that depreciation schedules read through. The
    ``TransactionService`` is wired into the ``DashboardService`` because the
    trends path uses it to collect transaction tax years.
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
        dashboard = DashboardService(properties, reports, depreciation, transactions)
        yield dashboard, properties, transactions, depreciation


# --- Strategies --------------------------------------------------------------
#
# Transaction years are drawn from a spread wide enough to produce gaps, and a
# property may draw the same year twice (duplicates) — both must collapse to a
# single ascending entry with no gap year inserted. Depreciation assets are
# placed in varied years; their schedules span several years, so the expected
# depreciation years are read back from the real materialized schedules.

_YEAR_POOL = list(range(2016, 2031))

# A set of transaction years for one property, with duplicates allowed and
# deliberately sparse so non-contiguous spans occur.
_txn_years = st.lists(st.sampled_from(_YEAR_POOL), min_size=0, max_size=6)

_asset_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("500000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_recovery = st.sampled_from(
    [Decimal("5"), Decimal("7"), Decimal("15"), Decimal("27.5"), Decimal("39")]
)

# Placed-in-service dates anchored inside the year pool so schedule rows land in
# plausible Data_Years.
_placed_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.sampled_from(_YEAR_POOL),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

_asset_spec = st.fixed_dictionaries(
    {
        "cost_basis": _asset_cost_basis,
        "placed_in_service_date": _placed_date,
        "recovery_period_years": _recovery,
    }
)


@st.composite
def _property_spec(draw: st.DrawFn):
    """One property's (transaction-years, asset-specs) seed."""
    years = draw(_txn_years)
    assets = draw(st.lists(_asset_spec, min_size=0, max_size=3))
    return years, assets


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date; year is what the Data_Year keys on."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


# Feature: dashboard-year-over-year-trends, Property 4: The series contains
# exactly the Data_Years, ascending, no gaps, no cap
@settings(deadline=None, max_examples=100)
@given(property_specs=st.lists(_property_spec(), min_size=1, max_size=3))
def test_series_contains_exactly_the_data_years_ascending(
    property_specs: list[tuple[list[int], list[dict]]],
) -> None:
    """``years`` tax_years == ascending de-duped union of txn + depreciation years.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5
    """
    with _moto_service() as (dashboard, properties, transactions, depreciation):
        expected_years: set[int] = set()

        for p_index, (txn_years, asset_specs) in enumerate(property_specs):
            created = properties.create(
                PropertyInput(
                    name=f"Prop{p_index}",
                    address_text=f"{p_index} Main St",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id

            # (a) Transaction years — exactly the years the generator chose
            # (duplicates collapse, gaps are preserved).
            for t_index, year in enumerate(txn_years):
                result = transactions.create(
                    TransactionInput(
                        property_id=pid,
                        date=_iso_date(year, t_index),
                        amount=Decimal("100.00"),
                        type="income",
                        category_id="rents-received",
                        description=None,
                    )
                )
                assert result.is_ok, result.error
                expected_years.add(year)

            # (b) Depreciation years — read back from the real materialized
            # schedules, the same path the service unions over.
            for spec in asset_specs:
                asset_result = depreciation.create_asset(
                    AssetInput(
                        property_id=pid,
                        description="Asset",
                        cost_basis=spec["cost_basis"],
                        placed_in_service_date=spec["placed_in_service_date"],
                        recovery_period_years=spec["recovery_period_years"],
                    )
                )
                assert asset_result.is_ok, asset_result.error

            for asset in depreciation.list_assets(pid):
                for row in depreciation.schedule_for(pid, asset.id):
                    expected_years.add(row.tax_year)

        # The only ceiling is the latest completed tax year: the current
        # calendar year can't be filed yet, and depreciation schedules run
        # decades into the future (Req 2.5). Cap the oracle the same way.
        latest = _latest_tax_year()
        expected_capped = {year for year in expected_years if year <= latest}

        summary = dashboard.trends_summary()
        actual_years = [ty.tax_year for ty in summary.years]

        expected_sorted = sorted(expected_capped)

        # Exact set, each present once, none omitted, none duplicated
        # (Req 2.1, 2.2).
        assert actual_years == expected_sorted, (
            f"trends years {actual_years} != expected Data_Years "
            f"{expected_sorted}"
        )

        # Ascending chronological order with no duplicates (Req 2.3, 2.2).
        assert actual_years == sorted(actual_years)
        assert len(actual_years) == len(set(actual_years))

        # Non-contiguous years preserved: no gap year inserted, and nothing
        # outside the capped Data_Year set appears (Req 2.4).
        assert set(actual_years) == expected_capped

        # No future / not-yet-filable year leaks in, however many assets exist
        # (Req 2.5).
        assert all(year <= latest for year in actual_years)
