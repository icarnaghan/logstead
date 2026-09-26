"""Property-based test: a depreciation schedule sums to the cost basis exactly.

Exercises the pure schedule engine
(:func:`logstead.services.depreciation.compute_schedule_rows`) across random
positive two-decimal cost bases, all twelve placed-in-service months (with a
valid day), and a realistic set of recovery periods. It asserts the single
Property 18 invariant: the sum of every per-year depreciation amount equals the
asset's cost basis exactly at two-decimal precision, with no floating-point or
rounding drift (the final year absorbs the rounding remainder).

Validates: Requirements 9.3
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import compute_schedule_rows
from logstead.util.money import to_money

# Realistic MACRS-style recovery periods: whole-year periods plus the 27.5-year
# residential-rental default (a fractional period that stresses the mid-month
# spill-over and rounding).
_RECOVERY_PERIODS = [
    Decimal("5"),
    Decimal("7"),
    Decimal("15"),
    Decimal("27.5"),
    Decimal("39"),
]

_CENT = Decimal("0.01")


def _positive_cost_basis() -> st.SearchStrategy[Decimal]:
    """Positive two-decimal cost bases built from an integer number of cents.

    Ranges from a single cent up to ~$10M so the schedule is exercised on tiny
    amounts (where rounding dominates and the mid-month remainder can exhaust
    the basis early) through large realistic building bases.
    """
    cents = st.integers(min_value=1, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _placed_in_service_date(year: int, month: int) -> st.SearchStrategy[str]:
    """An ISO ``YYYY-MM-DD`` date with a valid day for the given month/year."""
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


# Feature: logstead, Property 18: Depreciation sums to the cost basis
@settings(deadline=None, max_examples=200)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_depreciation_sums_to_cost_basis_exactly(
    cost_basis: Decimal,
    month: int,
    recovery: Decimal,
    year: int,
    data: st.DataObject,
) -> None:
    placed_date = data.draw(_placed_in_service_date(year, month))
    asset = DepreciableAsset(
        id="asset-sum",
        property_id="prop-sum",
        description="Building",
        cost_basis=cost_basis,
        placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )

    rows = compute_schedule_rows(asset)

    # Every per-year amount is a two-decimal Decimal (no float, no drift).
    for row in rows:
        assert row.amount == row.amount.quantize(_CENT)

    # Property 18: the annual amounts sum to the cost basis EXACTLY at
    # two-decimal precision. Decimal equality, no float involved anywhere.
    total = sum((r.amount for r in rows), Decimal("0.00"))
    assert total == to_money(cost_basis)
