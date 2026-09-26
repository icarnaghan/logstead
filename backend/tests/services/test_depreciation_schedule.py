"""Focused verification for the schedule engine (task 11.2, Requirements 9.1-9.5).

These are targeted example-based checks of the straight-line + mid-month
schedule engine and the per-(property, year) aggregation. The exhaustive
Hypothesis property tests for Properties 17-20 (tasks 11.4-11.7) are out of
scope here; this file only pins down known examples and the invariants the
engine must uphold: sum equals cost basis exactly, remaining basis is
monotone non-increasing to zero, correct span, mid-month first-year proration,
and property-year aggregation across assets.
"""

from __future__ import annotations

import math
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.depreciation import AssetInput, DepreciableAsset
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import (
    DepreciationService,
    compute_schedule_rows,
)

TABLE_NAME = "Logstead"
PROP = "prop-1"


def _asset(**overrides) -> DepreciableAsset:
    base = dict(
        id="asset-1",
        property_id=PROP,
        description="Building",
        cost_basis=Decimal("275000.00"),
        placed_in_service_date="2024-01-15",
        recovery_period_years=Decimal("27.5"),
    )
    base.update(overrides)
    return DepreciableAsset(**base)


# --- pure engine: invariants -------------------------------------------------

@pytest.mark.parametrize("month", list(range(1, 13)))
@pytest.mark.parametrize(
    "cost_basis,recovery",
    [
        (Decimal("275000.00"), Decimal("27.5")),
        (Decimal("10000.00"), Decimal("5")),
        (Decimal("123456.78"), Decimal("39")),
        (Decimal("0.03"), Decimal("27.5")),
    ],
)
def test_sum_equals_cost_basis_exactly(month, cost_basis, recovery):
    """Requirement 9.3: annual amounts sum to the cost basis exactly."""
    asset = _asset(
        cost_basis=cost_basis,
        recovery_period_years=recovery,
        placed_in_service_date=f"2024-{month:02d}-10",
    )
    rows = compute_schedule_rows(asset)
    assert sum((r.amount for r in rows), Decimal("0.00")) == cost_basis


@pytest.mark.parametrize("month", list(range(1, 13)))
def test_remaining_basis_monotone_to_zero(month):
    """Requirement 9.4: remaining basis is non-increasing and ends at zero."""
    asset = _asset(placed_in_service_date=f"2024-{month:02d}-10")
    rows = compute_schedule_rows(asset)

    # Remaining basis equals cost basis minus cumulative through each year,
    # never increases, and terminates at exactly 0.00.
    cumulative = Decimal("0.00")
    prev_remaining = asset.cost_basis
    for row in rows:
        cumulative += row.amount
        assert row.remaining_basis == asset.cost_basis - cumulative
        assert row.remaining_basis <= prev_remaining
        assert row.amount >= Decimal("0.00")
        prev_remaining = row.remaining_basis
    assert rows[-1].remaining_basis == Decimal("0.00")


@pytest.mark.parametrize(
    "recovery,expected_years",
    [(Decimal("27.5"), 29), (Decimal("5"), 6), (Decimal("39"), 40)],
)
def test_schedule_spans_ceil_recovery_plus_one_years(recovery, expected_years):
    """Requirement 9.1/9.2: span is ceil(recovery) + 1 tax years."""
    asset = _asset(recovery_period_years=recovery)
    rows = compute_schedule_rows(asset)
    assert len(rows) == expected_years
    assert len(rows) == math.ceil(recovery) + 1
    # Tax years are consecutive starting at the placed-in-service year.
    assert [r.tax_year for r in rows] == list(range(2024, 2024 + expected_years))


def test_first_year_mid_month_proration_january_vs_july():
    """Requirement 9.2: first-year amount reflects the mid-month fraction.

    275000 over 27.5 years -> 10000/yr full-year. January (M=1) first-year
    fraction = (12.5 - 1)/12 = 11.5/12; July (M=7) = (12.5 - 7)/12 = 5.5/12.
    """
    annual = Decimal("10000")
    jan = compute_schedule_rows(_asset(placed_in_service_date="2024-01-15"))
    jul = compute_schedule_rows(_asset(placed_in_service_date="2024-07-15"))

    expected_jan = (annual * (Decimal("11.5") / Decimal("12"))).quantize(Decimal("0.01"))
    expected_jul = (annual * (Decimal("5.5") / Decimal("12"))).quantize(Decimal("0.01"))

    assert jan[0].amount == expected_jan  # 9583.33
    assert jul[0].amount == expected_jul  # 4583.33
    # Middle (full) years are the full annual amount.
    assert jan[1].amount == annual.quantize(Decimal("0.01"))


# --- materialization + aggregation (moto) ------------------------------------

@pytest.fixture
def client():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
        yield ddb


@pytest.fixture
def service(client):
    return DepreciationService(DynamoRepository(client, TABLE_NAME))


def _create_input(**overrides) -> AssetInput:
    base = dict(
        property_id=PROP,
        description="Building",
        cost_basis=Decimal("275000.00"),
        placed_in_service_date="2024-01-15",
        recovery_period_years=Decimal("27.5"),
    )
    base.update(overrides)
    return AssetInput(**base)


def test_create_materializes_schedule_rows(service):
    asset = service.create_asset(_create_input()).value
    rows = service.schedule_for(PROP, asset.id)
    assert len(rows) == 29
    assert sum((r.amount for r in rows), Decimal("0.00")) == Decimal("275000.00")
    assert rows[0].tax_year == 2024
    assert rows[-1].remaining_basis == Decimal("0.00")


def test_update_recomputes_and_replaces_schedule(service):
    asset = service.create_asset(_create_input()).value
    # Change to a 5-year recovery period: schedule must fully replace.
    service.update_asset(
        PROP,
        asset.id,
        _create_input(cost_basis=Decimal("10000.00"), recovery_period_years=Decimal("5")),
    )
    rows = service.schedule_for(PROP, asset.id)
    assert len(rows) == 6  # ceil(5) + 1, no stale 29-row schedule left behind
    assert sum((r.amount for r in rows), Decimal("0.00")) == Decimal("10000.00")


def test_delete_removes_schedule_rows(service):
    asset = service.create_asset(_create_input()).value
    assert service.schedule_for(PROP, asset.id)  # materialized
    service.delete_asset(PROP, asset.id)
    assert service.schedule_for(PROP, asset.id) == []


def test_property_depreciation_for_year_sums_across_assets(service):
    """Requirement 9.5: property-year total equals the sum across assets."""
    # Two assets placed in Jan 2024, both 27.5yr: first-year amount each.
    a1 = service.create_asset(_create_input(cost_basis=Decimal("275000.00"))).value
    a2 = service.create_asset(
        _create_input(cost_basis=Decimal("110000.00"), description="Roof")
    ).value

    rows1 = service.schedule_for(PROP, a1.id)
    rows2 = service.schedule_for(PROP, a2.id)
    y2024_1 = next(r.amount for r in rows1 if r.tax_year == 2024)
    y2024_2 = next(r.amount for r in rows2 if r.tax_year == 2024)

    total = service.property_depreciation_for_year(PROP, 2024)
    assert total == y2024_1 + y2024_2


def test_property_depreciation_for_year_zero_when_no_assets(service):
    assert service.property_depreciation_for_year(PROP, 2030) == Decimal("0.00")
