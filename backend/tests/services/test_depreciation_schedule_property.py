"""Property-based test for the straight-line + mid-month schedule engine.

Exercises the pure schedule engine
(:func:`logstead.services.depreciation.compute_schedule_rows`) across random
cost bases, placed-in-service months (all twelve), and realistic recovery
periods. It asserts the schedule spans the correct number of consecutive tax
years, uses the mid-month first-year proration, and applies the full annual
straight-line amount to the interior (full) years — all robust to two-decimal
money rounding.

Validates: Requirements 9.1, 9.2, 8.5
"""

from __future__ import annotations

import calendar
import math
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

_MONTHS_PER_YEAR = Decimal("12")
_MID_MONTH_OFFSET = Decimal("12.5")
_CENT = Decimal("0.01")


def _positive_cost_basis() -> st.SearchStrategy[Decimal]:
    """Positive two-decimal cost bases, built from an integer number of cents.

    Ranges from one cent up to ~$10M so the schedule is exercised on tiny
    amounts (where rounding dominates) through large realistic building bases.
    """
    cents = st.integers(min_value=1, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _engine_expected_amounts(
    basis: Decimal,
    annual: Decimal,
    first_fraction: Decimal,
    num_years: int,
) -> list[Decimal]:
    """Reproduce the engine's exact per-year amounts (a faithful mirror).

    Mirrors :func:`logstead.services.depreciation.compute_schedule_rows`
    step-for-step: build the ideal (unrounded) cumulative depreciation at the
    end of each year (year 0 = mid-month-prorated, interior years accrue a full
    ``annual``, both capped at ``basis``, and the final year pinned to the exact
    ``basis``), quantize each cumulative with the engine's ``to_money``
    (ROUND_HALF_UP), and take each year's amount as the difference of
    consecutive quantized cumulatives. Using the engine's own ``to_money`` here
    is what keeps the expected values from drifting against the engine at the
    tiny-basis half-cent boundary.
    """
    # Ideal cumulative depreciation at the end of each year (matches the engine).
    cumulative_ideal: list[Decimal] = []
    running = annual * first_fraction
    for i in range(num_years):
        if i == num_years - 1:
            cumulative_ideal.append(basis)
        else:
            cumulative_ideal.append(min(running, basis))
            running += annual

    amounts: list[Decimal] = []
    prev_cum_money = Decimal("0.00")
    for i in range(num_years):
        if i == num_years - 1:
            cum_money = basis  # already two decimals
        else:
            cum_money = to_money(cumulative_ideal[i])
            if cum_money > basis:
                cum_money = basis
        amounts.append(cum_money - prev_cum_money)
        prev_cum_money = cum_money
    return amounts


def _placed_in_service_date(year: int, month: int) -> st.SearchStrategy[str]:
    """An ISO ``YYYY-MM-DD`` date with a valid day for the given month/year."""
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


# Feature: logstead, Property 17: Depreciation schedule is straight-line with mid-month convention
@settings(deadline=None, max_examples=200)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_schedule_is_straight_line_with_mid_month_convention(
    cost_basis: Decimal,
    month: int,
    recovery: Decimal,
    year: int,
    data: st.DataObject,
) -> None:
    placed_date = data.draw(_placed_in_service_date(year, month))
    asset = DepreciableAsset(
        id="asset-prop",
        property_id="prop-prop",
        description="Building",
        cost_basis=cost_basis,
        placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )

    rows = compute_schedule_rows(asset)

    # (a) Span: ceil(recovery) + 1 tax years (partial first year spills over).
    expected_years = math.ceil(recovery) + 1
    assert len(rows) == expected_years

    # (b) Tax years are consecutive, starting at the placed-in-service year.
    assert [r.tax_year for r in rows] == list(range(year, year + expected_years))

    # Straight-line full-year amount and the mid-month first-year fraction.
    basis = to_money(cost_basis)
    annual = basis / recovery
    first_fraction = (_MID_MONTH_OFFSET - Decimal(month)) / _MONTHS_PER_YEAR

    # Faithfully mirror the engine's own computation so the expected values use
    # the engine's exact quantization (``to_money`` / ROUND_HALF_UP) rather than
    # a parallel calculation with a different rounding mode. The engine builds
    # the *ideal* (unrounded) cumulative depreciation at the end of each year,
    # quantizes each with ``to_money`` (capped at the basis), pins the final
    # year's cumulative to the exact basis, and derives each year's amount as the
    # difference of consecutive quantized cumulatives. Reconstructing that here
    # eliminates rounding-mode drift at the tiny-basis half-cent boundary.
    expected_amounts = _engine_expected_amounts(
        basis, annual, first_fraction, expected_years
    )

    # (c) First year uses the mid-month proration of the annual amount, quantized
    # exactly as the engine quantizes it.
    expected_first = to_money(annual * first_fraction)
    assert expected_first == expected_amounts[0]
    assert rows[0].amount == expected_first

    # (d) Every subsequent year's amount matches the engine's exact per-year
    # step (the difference of consecutive ``to_money``-quantized cumulatives).
    # This is robust to the tiny-basis case, where the mid-month remainder
    # exhausts the basis before the final row and the trailing interior rows are
    # exactly zero.
    for row, expected in zip(rows[1:], expected_amounts[1:]):
        assert row.amount == expected

    # (e) All amounts are two-decimal Decimals and non-negative.
    for row in rows:
        assert row.amount == row.amount.quantize(_CENT)
        assert row.amount >= Decimal("0.00")

    # (f) Sum equals the cost basis exactly (mid-month remainder absorbed).
    assert sum((r.amount for r in rows), Decimal("0.00")) == basis


def test_schedule_first_year_tiny_basis_half_cent_boundary_regression() -> None:
    """Regression for the reported half-cent boundary counterexample.

    cost_basis=0.04, month=2, recovery=7, year=1990. The engine quantizes the
    mid-month-prorated first-year cumulative with ROUND_HALF_UP (``to_money``),
    producing 0.01 for the first row; a parallel computation using Decimal's
    default ROUND_HALF_EVEN quantization produced 0.00 and disagreed. The
    expected value must be derived with the engine's own quantization.

    Validates: Requirements 9.1, 9.2, 8.5
    """
    asset = DepreciableAsset(
        id="asset-regression",
        property_id="prop-regression",
        description="Building",
        cost_basis=Decimal("0.04"),
        placed_in_service_date="1990-02-15",
        recovery_period_years=Decimal("7"),
    )

    rows = compute_schedule_rows(asset)

    basis = to_money(Decimal("0.04"))
    annual = basis / Decimal("7")
    first_fraction = (_MID_MONTH_OFFSET - Decimal("2")) / _MONTHS_PER_YEAR

    # Engine quantizes with ROUND_HALF_UP: 0.04/7 * (10.5/12) ~= 0.005 -> 0.01.
    expected_first = to_money(annual * first_fraction)
    assert expected_first == Decimal("0.01")
    assert rows[0].amount == expected_first

    # Whole schedule still sums to the exact basis.
    assert sum((r.amount for r in rows), Decimal("0.00")) == basis
