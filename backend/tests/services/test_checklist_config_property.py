"""Property 3: Config validation (Requirements 3.3, 3.6)."""
from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.checklist_config import ChecklistConfig, ChecklistConfigError

_decimals = st.decimals(
    min_value=Decimal("-100000"),
    max_value=Decimal("100000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_bad_types = st.one_of(
    st.floats(allow_nan=False, allow_infinity=False),
    st.integers(),
    st.text(max_size=5),
    st.none(),
    st.booleans(),
)
_money = st.one_of(_decimals, _bad_types)
_percent = st.one_of(_decimals, _bad_types)
_count = st.one_of(st.integers(min_value=-5, max_value=30), _bad_types)


def _is_decimal(v: object) -> bool:
    return isinstance(v, Decimal)


def _is_count(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _expected_valid(large, capital, pct, minimum, months, years) -> bool:
    return (
        all(_is_decimal(m) and m >= 0 for m in (large, capital, minimum))
        and _is_decimal(pct)
        and pct > 0
        and _is_count(months)
        and _is_count(years)
    )


# Feature: year-end-checklist, Property 3: Config validation
@settings(max_examples=300, deadline=None)
@given(_money, _money, _percent, _money, _count, _count)
def test_config_validation(large, capital, pct, minimum, months, years):
    """**Validates: Requirements 3.3, 3.6**"""
    valid = _expected_valid(large, capital, pct, minimum, months, years)
    try:
        cfg = ChecklistConfig(large, capital, pct, minimum, months, years)
    except ChecklistConfigError:
        assert not valid
        return
    assert valid
    for value in (cfg.large_entry_amount, cfg.capital_candidate_amount, cfg.swing_minimum_amount):
        assert value >= 0
        assert value.as_tuple().exponent == -2
