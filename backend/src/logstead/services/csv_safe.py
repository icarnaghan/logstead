"""Spreadsheet formula neutralization for CSV text cells."""

from __future__ import annotations

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def neutralize_cell(value: str) -> str:
    """Prefix an apostrophe when ``value`` starts with ``=``, ``+``, ``-``, ``@``, tab, or CR.

    Spreadsheet applications treat such cells as formulas. Any other value,
    including the empty string, is returned unchanged.
    """
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
