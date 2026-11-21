"""Property-based test: Invariant_Sum holds for arbitrary valid override maps.

Feature: depreciation-override-and-whole-dollar-display, Property 1:
Invariant_Sum holds for arbitrary valid override maps.

For any asset and any VALID override map (non-negative two-decimal amounts for
years in the computed span, sum <= cost_basis, tail reconcilable), the
Effective_Schedule's per-year amounts sum to exactly the asset's cost basis.

Validates: Requirements 2.3, 2.6, 4.4
"""

from __future__ import annotations

import calendar
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import DepreciableAsset
from logstead.services.depreciation import compute_schedule_rows
from logstead.util.money import to_money

_RECOVERY_PERIODS = [
    Decimal("5"),
    Decimal("7"),
    Decimal("15"),
    Decimal("27.5"),
    Decimal("39"),
]
_CENT = Decimal("0.01")


def _positive_cost_basis() -> st.SearchStrategy[Decimal]:
    cents = st.integers(min_value=1, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _placed_in_service_date(year: int, month: int) -> st.SearchStrategy[str]:
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


def _base_asset(cost_basis, placed_date, recovery) -> DepreciableAsset:
    return DepreciableAsset(
        id="a",
        property_id="p",
        description="Building",
        cost_basis=cost_basis,
        placed_in_service_date=placed_date,
        recovery_period_years=recovery,
    )


def _valid_overrides(draw, base_rows) -> dict[int, Decimal]:
    """Draw a valid override map composed from the base schedule.

    Overrides a subset of the NON-tail years, assigning each an amount in
    [0, base_amount_for_that_year]. Since each override <= the base amount for
    its year, the sum of overrides <= cost_basis and the tail delta
    (sum(base over overridden) - sum(overrides)) is >= 0, so the tail stays
    non-negative and the map is accepted by validation.
    """
    non_tail = base_rows[:-1]
    if not non_tail:
        return {}
    chosen = draw(
        st.lists(
            st.sampled_from([r.tax_year for r in non_tail]),
            unique=True,
            max_size=len(non_tail),
        )
    )
    base_by_year = {r.tax_year: r.amount for r in base_rows}
    overrides: dict[int, Decimal] = {}
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
def test_effective_schedule_sums_to_cost_basis_with_overrides(
    cost_basis, month, recovery, year, data
) -> None:
    placed_date = data.draw(_placed_in_service_date(year, month))
    base_asset = _base_asset(cost_basis, placed_date, recovery)
    base_rows = compute_schedule_rows(base_asset)

    overrides = _valid_overrides(data.draw, base_rows)
    asset = _base_asset(cost_basis, placed_date, recovery)
    asset.depreciation_overrides = overrides

    rows = compute_schedule_rows(asset)

    for row in rows:
        assert row.amount == row.amount.quantize(_CENT)
    total = sum((r.amount for r in rows), Decimal("0.00"))
    assert total == to_money(cost_basis)
