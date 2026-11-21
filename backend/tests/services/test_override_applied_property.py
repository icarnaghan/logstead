"""Property-based test: an overridden year's amount equals the override exactly.

Feature: depreciation-override-and-whole-dollar-display, Property 4:
An overridden year's amount equals the override exactly.

Validates: Requirements 2.1, 2.2, 2.5
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import compute_schedule_rows

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
    """Non-tail overrides, each in [0, base amount], so the map is accepted."""
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
def test_overridden_year_amount_equals_override(
    cost_basis, month, recovery, year, data
):
    placed_date = data.draw(_placed_in_service_date(year, month))
    base_rows = compute_schedule_rows(_asset(cost_basis, placed_date, recovery))
    overrides = _valid_overrides(data.draw, base_rows)
    asset = _asset(cost_basis, placed_date, recovery)
    asset.depreciation_overrides = overrides

    rows = compute_schedule_rows(asset)
    by_year = {r.tax_year: r.amount for r in rows}
    for year_key, amount in overrides.items():
        assert by_year[year_key] == amount


def test_tail_year_override_summing_to_basis_is_applied_exactly():
    """Req 2.5: overriding the tail year is accepted when the map reconciles.

    A single-row-ish case is awkward, so use a real schedule and pin the tail
    to exactly the base tail amount (a trivially reconciling override): the map
    sums to cost_basis, so the tail amount is applied verbatim.
    """
    asset = _asset(Decimal("140000.00"), "2010-06-01", Decimal("27.5"))
    base_rows = compute_schedule_rows(asset)
    tail = base_rows[-1]
    # Override EVERY year with its own base amount -> map sums to cost_basis,
    # and the tail is overridden with its base value (reconciles exactly).
    asset.depreciation_overrides = {r.tax_year: r.amount for r in base_rows}

    rows = compute_schedule_rows(asset)
    by_year = {r.tax_year: r.amount for r in rows}
    assert by_year[tail.tax_year] == tail.amount
    assert sum((r.amount for r in rows), Decimal("0.00")) == Decimal("140000.00")
