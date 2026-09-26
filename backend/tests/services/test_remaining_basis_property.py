"""Property-based test for remaining-basis consistency in the schedule engine.

Exercises the pure schedule engine
(:func:`logstead.services.depreciation.compute_schedule_rows`) across random
cost bases, placed-in-service months (all twelve), and realistic recovery
periods. It asserts that the remaining basis after each tax year equals the
cost basis minus the cumulative depreciation through that year, that the
sequence of remaining bases is non-increasing, that every remaining basis is
non-negative, and that the final year's remaining basis is exactly zero.

Validates: Requirements 9.4
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import compute_schedule_rows
from logstead.util.money import to_money

# Realistic MACRS-style recovery periods, including the 27.5-year residential
# rental default and both whole-year and fractional-year periods.
_RECOVERY_PERIODS = [
    Decimal("5"),
    Decimal("7"),
    Decimal("15"),
    Decimal("27.5"),
    Decimal("39"),
]

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


def _positive_cost_basis() -> st.SearchStrategy[Decimal]:
    """Positive two-decimal cost bases, built from an integer number of cents.

    Ranges from one cent up to ~$10M so the schedule is exercised on tiny
    amounts (where rounding dominates) through large realistic building bases.
    """
    cents = st.integers(min_value=1, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _placed_in_service_date(year: int, month: int) -> st.SearchStrategy[str]:
    """An ISO ``YYYY-MM-DD`` date with a valid day for the given month/year."""
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


# Feature: logstead, Property 19: Remaining basis is consistent and terminates at zero
@settings(deadline=None, max_examples=200)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_remaining_basis_is_consistent_and_terminates_at_zero(
    cost_basis: Decimal,
    month: int,
    recovery: Decimal,
    year: int,
    data: st.DataObject,
) -> None:
    placed_date = data.draw(_placed_in_service_date(year, month))
    asset = DepreciableAsset(
        id="asset-remaining",
        property_id="prop-remaining",
        description="Building",
        cost_basis=cost_basis,
        placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )

    rows = compute_schedule_rows(asset)
    assert rows, "schedule must have at least one row"

    basis = to_money(cost_basis)

    # (a) Each row's remaining basis equals the cost basis minus the cumulative
    #     depreciation through that row.
    cumulative = _ZERO
    for row in rows:
        cumulative += row.amount
        assert row.remaining_basis == basis - cumulative

    # (b) The remaining-basis sequence is non-increasing across rows.
    for earlier, later in zip(rows, rows[1:]):
        assert earlier.remaining_basis >= later.remaining_basis

    # (c) Every remaining basis is non-negative.
    for row in rows:
        assert row.remaining_basis >= _ZERO

    # (d) The final row's remaining basis is exactly zero.
    assert rows[-1].remaining_basis == _ZERO
