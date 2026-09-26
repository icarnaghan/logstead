"""Property-based test for the money round-trip (design Property 28).

This test validates that persisting a monetary amount as a two-decimal string
(:func:`money_to_str`) and parsing it back to a ``decimal.Decimal``
(:func:`to_money`) returns the exact same value with no floating-point or
numeric-type drift, for any two-decimal amount.

Validates: Requirements 13.3
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from logstead.util.money import money_to_str, to_money


def two_decimal_money() -> st.SearchStrategy[Decimal]:
    """Generate two-decimal ``Decimal`` amounts across the valid input space.

    Amounts are built from an integer number of cents so every generated value
    has exactly two decimal places. The range spans zero, the smallest unit
    (``0.01``), large amounts, and negative amounts (allowed at the money
    boundary), so the round-trip is exercised across the whole space.
    """
    # +/- ~10 trillion dollars expressed in cents; comfortably covers 0.00,
    # 0.01, and large real-world amounts.
    cents = st.integers(min_value=-1_000_000_000_000_00, max_value=1_000_000_000_000_00)
    return cents.map(lambda c: (Decimal(c) / 100).quantize(Decimal("0.01")))


# Feature: logstead, Property 28: Monetary amounts preserve two-decimal precision
@given(amount=two_decimal_money())
def test_money_round_trip_preserves_two_decimal_precision(amount: Decimal) -> None:
    assert to_money(money_to_str(amount)) == amount
