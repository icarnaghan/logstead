"""Property test for task 11.7 — property-year depreciation equals asset sum.

Property 20 (design.md): *For any* property and tax year, the total property
depreciation equals the sum of each asset's scheduled depreciation amount for
that year.

Validates: Requirements 9.5

Strategy
--------
For each example we create N (1..k) real depreciable assets under a single
property via :meth:`DepreciationService.create_asset`, each with a random
positive two-decimal ``cost_basis``, a random ``placed_in_service_date``, and a
random ``recovery_period_years``. Creating an asset materializes its full
schedule in DynamoDB (base table rows plus the GSI2 tax-year partition), so
this exercises the real GSI2 aggregation rather than any in-memory shortcut.

We then pick a target tax year that appears in at least one asset's schedule
and assert:

    property_depreciation_for_year(property_id, target_year)
        == sum over assets of (that asset's schedule-row amount for
                               target_year, or 0.00 if the asset has no row
                               in that year)

as exact ``Decimal`` values. A fresh moto-backed table (base + GSI2) is created
per example so no state leaks between iterations.
"""

from __future__ import annotations

from decimal import Decimal

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.depreciation import AssetInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
PROPERTY_ID = "prop-1"

TWO_PLACES = Decimal("0.01")


def _make_table(ddb) -> None:
    """Create the single-table Logstead schema with GSI2 (tax-year partition)."""
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


# Positive two-decimal cost basis, bounded so schedules stay small enough to
# materialize quickly under moto but wide enough to exercise rounding.
_cost_basis = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("5000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Placed-in-service dates across all twelve months and a spread of years so
# different assets' schedules overlap on some tax years and not others.
_placed_date = st.builds(
    lambda y, m, d: f"{y:04d}-{m:02d}-{d:02d}",
    st.integers(min_value=2018, max_value=2024),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=28),
)

# A mix of the residential-rental default and shorter/longer periods so the
# per-asset schedule spans differ (some assets fall out of the target year).
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


# Feature: logstead, Property 20: Property-year depreciation equals the sum across assets
@settings(
    deadline=None,
    max_examples=150,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    specs=st.lists(_asset_spec, min_size=1, max_size=5),
    year_pick=st.data(),
)
def test_property_year_depreciation_equals_sum_across_assets(specs, year_pick):
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _make_table(ddb)
        service = DepreciationService(DynamoRepository(ddb, TABLE_NAME))

        # Create every asset; each create materializes its schedule (base + GSI2).
        schedules: list[dict[int, Decimal]] = []
        for i, spec in enumerate(specs):
            created = service.create_asset(
                AssetInput(
                    property_id=PROPERTY_ID,
                    description=f"Asset {i}",
                    cost_basis=spec["cost_basis"],
                    placed_in_service_date=spec["placed_in_service_date"],
                    recovery_period_years=spec["recovery_period_years"],
                )
            )
            assert created.is_ok, created.error
            rows = service.schedule_for(PROPERTY_ID, created.value.id)
            schedules.append({r.tax_year: r.amount for r in rows})

        # Choose a target tax year that appears in at least one asset schedule.
        candidate_years = sorted({yr for sched in schedules for yr in sched})
        target_year = year_pick.draw(st.sampled_from(candidate_years))

        # Expected total: sum of each asset's amount for that year (0 if absent).
        expected = sum(
            (sched.get(target_year, Decimal("0.00")) for sched in schedules),
            Decimal("0.00"),
        ).quantize(TWO_PLACES)

        actual = service.property_depreciation_for_year(PROPERTY_ID, target_year)

        assert actual == expected
