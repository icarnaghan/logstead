"""Property test for spreadsheet formula neutralization.
# Feature: accountant-package, Property 10: Spreadsheet formula neutralization
**Validates: Requirements 9.6**
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.csv_safe import neutralize_cell

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

# Mix arbitrary text with text forced to start with a trigger character.
_TEXT = st.one_of(
    st.text(),
    st.builds(lambda t, rest: t + rest, st.sampled_from(_TRIGGERS), st.text()),
)


@settings(max_examples=200)
@given(_TEXT)
def test_neutralize_cell_prefixes_only_formula_starts_and_is_idempotent(text: str) -> None:
    result = neutralize_cell(text)
    if text.startswith(_TRIGGERS):
        assert result == "'" + text
    else:
        assert result == text
    assert neutralize_cell(result) == result
