"""Property-based test: validation rejects every unsatisfiable override.

Feature: depreciation-override-and-whole-dollar-display, Property 5:
Validation rejects every unsatisfiable override and persists nothing.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import calendar
import math
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from logstead.models.depreciation import AssetInput
from logstead.services.depreciation import DepreciationService

_RECOVERY_PERIODS = [Decimal("5"), Decimal("7"), Decimal("15"), Decimal("27.5"), Decimal("39")]
_CENT = Decimal("0.01")


def _svc():
    # _validate never touches the repo.
    return DepreciationService(None)  # type: ignore[arg-type]


def _positive_cost_basis():
    cents = st.integers(min_value=100, max_value=1_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(_CENT))


def _placed(year, month):
    last_day = calendar.monthrange(year, month)[1]
    return st.integers(min_value=1, max_value=last_day).map(
        lambda day: f"{year:04d}-{month:02d}-{day:02d}"
    )


def _validate(cost_basis, placed_date, recovery, overrides):
    return _svc()._validate(AssetInput(
        property_id="p", description="Building",
        cost_basis=cost_basis, placed_in_service_date=placed_date,
        recovery_period_years=recovery, depreciation_overrides=overrides,
    ))


def _span(placed_date, recovery):
    y = int(placed_date[:4])
    n = math.ceil(recovery) + 1
    return y, y + n - 1


# Case: negative amount -> field depreciation_overrides.<year>
@settings(deadline=None, max_examples=60)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_reject_negative_amount(cost_basis, month, recovery, year, data):
    placed_date = data.draw(_placed(year, month))
    first, _ = _span(placed_date, recovery)
    result = _validate(cost_basis, placed_date, recovery, {first: Decimal("-1.00")})
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == f"depreciation_overrides.{first}"


# Case: out-of-span year -> field depreciation_overrides.<year>
@settings(deadline=None, max_examples=60)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_reject_out_of_span(cost_basis, month, recovery, year, data):
    placed_date = data.draw(_placed(year, month))
    first, _ = _span(placed_date, recovery)
    bad_year = first - 1
    result = _validate(cost_basis, placed_date, recovery, {bad_year: Decimal("1.00")})
    assert not result.is_ok
    assert result.error.field == f"depreciation_overrides.{bad_year}"


# Case: sum exceeds cost basis -> field depreciation_overrides
@settings(deadline=None, max_examples=60)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_reject_sum_exceeds_basis(cost_basis, month, recovery, year, data):
    placed_date = data.draw(_placed(year, month))
    first, last = _span(placed_date, recovery)
    # Two distinct NON-tail in-span years each at the full cost basis -> the sum
    # strictly exceeds cost_basis. Need at least two non-tail years.
    assume(last - 1 >= first + 1)
    overrides = {first: cost_basis, first + 1: cost_basis}
    result = _validate(cost_basis, placed_date, recovery, overrides)
    assert not result.is_ok
    assert result.error.field == "depreciation_overrides"


# Case: tail overridden, map does not reconcile -> field .<tailYear>
@settings(deadline=None, max_examples=60)
@given(
    cost_basis=_positive_cost_basis(),
    month=st.integers(min_value=1, max_value=12),
    recovery=st.sampled_from(_RECOVERY_PERIODS),
    year=st.integers(min_value=1990, max_value=2100),
    data=st.data(),
)
def test_reject_tail_not_reconciling(cost_basis, month, recovery, year, data):
    placed_date = data.draw(_placed(year, month))
    first, last = _span(placed_date, recovery)
    # Override ONLY the tail year with 0.00 (does not equal cost_basis since
    # cost_basis >= 1.00), so the sole overridden year is the tail and the map
    # does not sum to cost_basis.
    result = _validate(cost_basis, placed_date, recovery, {last: Decimal("0.00")})
    assert not result.is_ok
    assert result.error.field == f"depreciation_overrides.{last}"
