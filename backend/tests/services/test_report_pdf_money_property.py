"""Property test for the PDF money format.

# Feature: accountant-package, Property 2: Money format round trip
**Validates: Requirements 2.3, 16.2, 16.4**
"""
from __future__ import annotations

import re
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.report_pdf import format_money

# Two-decimal values across the range of exact report values, negatives included.
_VALUES = st.decimals(
    min_value=Decimal("-999999999999.99"),
    max_value=Decimal("999999999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_FORM = re.compile(r"^\(?\$\d{1,3}(,\d{3})*\.\d{2}\)?$")


def _parse(text: str) -> Decimal:
    negative = text.startswith("(") and text.endswith(")")
    digits = text.strip("()").replace("$", "").replace(",", "")
    value = Decimal(digits)
    return -value if negative else value


@settings(max_examples=200)
@given(_VALUES)
def test_format_money_round_trips_and_wraps_only_negatives(value: Decimal) -> None:
    text = format_money(value)
    assert _FORM.match(text)
    assert _parse(text) == value
    assert text.startswith("(") == text.endswith(")")
    if value < 0:
        assert text.startswith("(") and text.endswith(")")
    else:
        assert "(" not in text and ")" not in text
