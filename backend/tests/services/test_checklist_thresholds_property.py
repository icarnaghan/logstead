"""Property 4: Threshold comparison is inclusive (Requirements 3.7, 11.2, 12.1, 13.3)."""
from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.checklist import (
    is_capital_candidate,
    is_large_entry,
    swing_for,
)
from logstead.services.checklist_config import ChecklistConfig

# Feature: year-end-checklist, Property 4: Threshold comparison is inclusive

_CENT = Decimal("0.01")
_money = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_amount = st.decimals(
    min_value=Decimal("-1000"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _threshold_and_amount(draw):
    threshold = draw(_money)
    amount = draw(
        st.one_of(
            st.just(threshold),
            st.just(threshold - _CENT),
            st.just(threshold + _CENT),
            _amount,
        )
    )
    return threshold, amount


@settings(max_examples=200, deadline=None)
@given(_threshold_and_amount())
def test_large_entry_is_inclusive(case):
    threshold, amount = case
    config = ChecklistConfig(large_entry_amount=threshold)
    assert is_large_entry(amount, config) == (amount >= threshold)


@settings(max_examples=200, deadline=None)
@given(_threshold_and_amount())
def test_capital_candidate_is_inclusive(case):
    threshold, amount = case
    config = ChecklistConfig(capital_candidate_amount=threshold)
    assert is_capital_candidate(amount, config) == (amount >= threshold)


@settings(max_examples=200, deadline=None)
@given(_threshold_and_amount())
def test_swing_minimum_is_inclusive(case):
    threshold, amount = case
    config = ChecklistConfig(swing_minimum_amount=threshold)
    # A zero prior total removes the percent test, leaving only the minimum.
    result = swing_for(Decimal("0.00"), amount, config)
    assert (result is not None) == (abs(amount) >= threshold)
