"""Property-based test: Invariant_Monotonic holds for valid override maps.

Feature: depreciation-override-and-whole-dollar-display, Property 2:
Invariant_Monotonic holds for arbitrary valid override maps.

For any asset and any valid override map, every Effective_Schedule amount is
>= 0, each remaining_basis equals cost_basis minus the cumulative amount
through that year, remaining_basis is non-increasing, and the final row's
remaining_basis is exactly 0.00.

Validates: Requirements 2.4, 2.6
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import compute_schedule_rows
from logstead.util.money import to_money

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


def _asset(cost_basis, placed_date, recovery):
    return DepreciableAsset(
        id="a", property_id="p", description="Building",
        cost_basis=cost_basis, placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )


def _valid_overrides(draw, base_rows):
    non_tail = base_rows[:-1]
    if not non_tail:
        return {}
    chosen = draw(st.lists(
        st.sampled_from([r.tax_year for r in non_tail]),
        unique=True, max_size=len(non_tail)))
    base_by_year = {r.tax_year: r.amount for r in base_rows}
    overrides = {}
    for year in chosen:
        cap_cents = int((base_by_year[year] * 100).to_integral_value())
        amt_cents = draw(st.integers(min_value=0, max_value=cap_cents))
        overrides[year] = (Decimal(amt_cents) / 100).quantize(_CENT)
    return overrides


@settings(deadline=None, max_examples=100)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_effective_schedule_remaining_basis_monotone(
    cost_basis, month, recovery, year, data
):
    placed_date = data.draw(_placed_in_service_date(year, month))
    base_rows = compute_schedule_rows(_asset(cost_basis, placed_date, recovery))
    overrides = _valid_overrides(data.draw, base_rows)
    asset = _asset(cost_basis, placed_date, recovery)
    asset.depreciation_overrides = overrides

    rows = compute_schedule_rows(asset)
    basis = to_money(cost_basis)

    cumulative = Decimal("0.00")
    prev_remaining = None
    for row in rows:
        assert row.amount >= Decimal("0.00")
        cumulative = (cumulative + row.amount).quantize(_CENT)
        assert row.remaining_basis == (basis - cumulative).quantize(_CENT)
        if prev_remaining is not None:
            assert row.remaining_basis <= prev_remaining
        prev_remaining = row.remaining_basis
    assert rows[-1].remaining_basis == Decimal("0.00")
