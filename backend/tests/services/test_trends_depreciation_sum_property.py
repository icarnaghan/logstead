"""Property-based test: portfolio depreciation is the exact sum across properties.

Design Property 3 (Requirements 6.4): *for any* Data_Year, the Trends_Series
entry's ``depreciation_total`` equals the exact-cent ``Decimal`` sum over the
user's properties of
:meth:`DepreciationService.property_depreciation_for_year(property_id, year)`
for that year, with no floating-point drift.

``DashboardService.trends_summary()`` (``services/dashboard.py``) loops the
user's properties once per Data_Year, summing
``property_depreciation_for_year(prop.id, year)`` into each
:class:`TrendYear`'s ``depreciation_total`` via :func:`to_money`. This property
drives that aggregation universally: it generates ``1..k`` properties, each with
an arbitrary set of depreciable assets placed in service across a spread of
years, persists them through the real composed services (so each asset
materializes its real schedule in the GSI2 tax-year partition), then for every
year in the returned series asserts (exact ``Decimal``):

    TrendYear.depreciation_total
        == sum over the user's properties of
           property_depreciation_for_year(prop.id, TrendYear.tax_year)

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring the fixture pattern in ``test_dashboard_net_property.py``.
Per-example provisioning is not instantaneous, so the deadline is disabled and
the example count is held at 100 to keep the moto-backed run reasonable.

Validates: Requirements 6.4
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
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.dashboard import DashboardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

TWO_PLACES = Decimal("0.01")


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed Dashboard, Depreciation, and Property services bound to
    freshly created resources so each Hypothesis example runs against a clean
    store with no aggregate faked. The transaction service is wired into the
    dashboard so Data_Year derivation sees the real query paths, matching the
    router's ``_dashboard_service_or_503`` composition.
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
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        depreciation = DepreciationService(repo)
        reports = ReportingService(transactions, depreciation, properties)
        dashboard = DashboardService(properties, reports, depreciation, transactions)
        yield dashboard, depreciation, properties


# --- Strategies ---------------------------------------------------------------
#
# Each property owns an arbitrary (possibly empty) set of depreciable assets.
# Every asset carries a positive two-decimal cost basis, a placed-in-service
# date spread across months and a range of years, and a mix of recovery periods
# so the per-asset schedules overlap on some tax years and not others. Creating
# an asset materializes its full schedule in the GSI2 tax-year partition, so the
# depreciation totals exercise the real aggregation rather than any shortcut.

_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("5000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_placed_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.integers(min_value=2018, max_value=2024),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

_recovery = st.sampled_from(
    [Decimal("27.5"), Decimal("5"), Decimal("7"), Decimal("15"), Decimal("39")]
)

_asset_spec = st.fixed_dictionaries(
    {
        "cost_basis": _cost_basis,
        "placed_in_service_date": _placed_date,
        "recovery_period_years": _recovery,
    }
)

# A property is an arbitrary (possibly empty) list of asset specs.
_property_assets = st.lists(_asset_spec, min_size=0, max_size=4)


# Feature: dashboard-year-over-year-trends, Property 3: Portfolio depreciation is the exact sum across properties
@settings(deadline=None, max_examples=100)
@given(properties_assets=st.lists(_property_assets, min_size=1, max_size=4))
def test_portfolio_depreciation_is_exact_sum_across_properties(
    properties_assets: list[list[dict]],
) -> None:
    """Each TrendYear.depreciation_total == exact-cent sum across properties.

    Validates: Requirements 6.4
    """
    with _moto_service() as (dashboard, depreciation, properties):
        property_ids: list[str] = []
        for p_index, assets in enumerate(properties_assets):
            created = properties.create(
                PropertyInput(
                    name=f"Prop{p_index}",
                    address_text=f"{p_index} Main St",
                    property_type="single_family",
                )
            )
            assert created.is_ok, created.error
            pid = created.value.id
            property_ids.append(pid)

            for spec in assets:
                result = depreciation.create_asset(
                    AssetInput(
                        property_id=pid,
                        description="Asset",
                        cost_basis=spec["cost_basis"],
                        placed_in_service_date=spec["placed_in_service_date"],
                        recovery_period_years=spec["recovery_period_years"],
                    )
                )
                assert result.is_ok, result.error

        summary = dashboard.trends_summary()

        for trend_year in summary.years:
            # The year's portfolio depreciation total equals the exact-Decimal
            # sum of each property's depreciation for that same year, with no
            # floating-point or rounding drift.
            expected = sum(
                (
                    depreciation.property_depreciation_for_year(
                        pid, trend_year.tax_year
                    )
                    for pid in property_ids
                ),
                Decimal("0.00"),
            ).quantize(TWO_PLACES)

            assert trend_year.depreciation_total == expected
