"""Property-based test: a no-override asset is identical to today.

Feature: depreciation-override-and-whole-dollar-display, Property 3:
A no-override asset is identical to today.

Validates: Requirements 1.3, 5.1
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import _apply_overrides, compute_schedule_rows

_RECOVERY_PERIODS = [Decimal("5"), Decimal("7"), Decimal("15"), Decimal("27.5"), Decimal("39")]
_CENT = Decimal("0.01")


def _positive_cost_basis():
    cents = st.integers(min_value=1, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _placed_in_service_date(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


@settings(deadline=None, max_examples=100)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_empty_override_map_is_identical(cost_basis, month, recovery, year, data):
    placed_date = data.draw(_placed_in_service_date(year, month))
    asset = DepreciableAsset(
        id="a", property_id="p", description="Building",
        cost_basis=cost_basis, placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )
    # Empty overrides (the default) must produce the pre-feature schedule.
    assert asset.depreciation_overrides == {}
    rows = compute_schedule_rows(asset)

    # _apply_overrides with an empty map returns the base rows unchanged.
    assert _apply_overrides(rows, {}) is rows

    # And every field matches a parallel engine run with no overrides.
    again = compute_schedule_rows(asset)
    assert len(rows) == len(again)
    for a, b in zip(rows, again):
        assert (a.tax_year, a.amount, a.remaining_basis, a.method, a.convention) == (
            b.tax_year, b.amount, b.remaining_basis, b.method, b.convention
        )
