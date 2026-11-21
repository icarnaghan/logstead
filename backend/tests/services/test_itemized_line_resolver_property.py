"""Property-based tests for the itemized-expenses line resolver.

Targets :class:`logstead.services.itemized.LineAccumulator`.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.itemized import LineAccumulator
from logstead.util.money import money_to_str, to_money

_SETTINGS = settings(max_examples=100, deadline=None)

# Positive two-decimal amounts (0.01 .. 99,999.99).
amounts = st.integers(min_value=1, max_value=9_999_999).map(
    lambda cents: Decimal(cents).scaleb(-2)
)
# A row is (amount, itemized marker).
rows = st.lists(st.tuples(amounts, st.booleans()), max_size=30)
amount_lists = st.lists(amounts, max_size=20)
nonempty_amount_lists = st.lists(amounts, min_size=1, max_size=20)


def _resolve(row_list):
    acc = LineAccumulator()
    for amount, itemized in row_list:
        acc.add(to_money(amount), itemized=itemized)
    return acc.resolve()


def _places(value: Decimal) -> int:
    return -value.as_tuple().exponent


# Feature: itemized-expenses, Property 1: Precedence of total over itemized detail
# **Validates: Requirements 5.1, 5.2, 5.3, 5.6, 5.9**
@_SETTINGS
@given(rows)
def test_property_1_precedence_of_total_over_itemized_detail(row_list):
    unmarked = [a for a, i in row_list if not i]
    marked = [a for a, i in row_list if i]
    itemized_sum = sum(marked, Decimal("0"))

    res = _resolve(row_list)

    if unmarked:
        entered = sum(unmarked, Decimal("0"))
        assert res.source == "entered_total"
        assert res.line_total == entered
        assert res.remainder == entered - itemized_sum
    elif marked:
        assert res.source == "itemized"
        assert res.line_total == itemized_sum
        assert res.remainder is None
    else:
        assert res.source == "none"
        assert res.line_total == Decimal("0.00")
        assert res.remainder is None


# Feature: itemized-expenses, Property 2: Itemized detail never changes a present total
# **Validates: Requirements 5.4, 5.7**
@_SETTINGS
@given(nonempty_amount_lists, amount_lists, amount_lists)
def test_property_2_itemized_detail_never_changes_a_present_total(
    totals, itemized_a, itemized_b
):
    total_rows = [(a, False) for a in totals]
    res_a = _resolve(total_rows + [(a, True) for a in itemized_a])
    res_b = _resolve(total_rows + [(a, True) for a in itemized_b])

    assert res_a.line_total == res_b.line_total
    assert res_a.source == res_b.source == "entered_total"


# Feature: itemized-expenses, Property 3: Amounts stay exact and two-decimal
# **Validates: Requirements 5.5, 14.1, 14.3**
@_SETTINGS
@given(rows)
def test_property_3_amounts_stay_exact_and_two_decimal(row_list):
    marked = [a for a, i in row_list if i]
    res = _resolve(row_list)

    assert res.itemized_sum == sum(marked, Decimal("0"))

    values = [res.line_total, res.itemized_sum]
    if res.entered_total is not None:
        values.append(res.entered_total)
    if res.remainder is not None:
        values.append(res.remainder)

    for value in values:
        assert _places(value) == 2
        # Serialized form is a fixed two-decimal string that round-trips exactly.
        text = money_to_str(value)
        assert len(text.rsplit(".", 1)[1]) == 2
        assert Decimal(text) == value
