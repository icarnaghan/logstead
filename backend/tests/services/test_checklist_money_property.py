"""Property 20: money values have the wire form.

Requirements 15.9, 21.1, 21.4.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from hypothesis import given, settings

from logstead.router.handler import _to_jsonable
from logstead.services.checklist import YearSnapshot, build_checklist
from logstead.services.checklist_config import ChecklistConfig

from .test_checklist_shape_property import _configs, _snapshots

_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")
_DOLLAR_RE = re.compile(r"-?\$\d[\d,]*(?:\.\d+)?")
_DOLLAR_OK = re.compile(r"^-?\$\d{1,3}(?:,\d{3})*\.\d{2}$|^-?\$\d+\.\d{2}$")
# Decimal-valued keys that are percentages, not money.
_NON_MONEY_KEYS = {"percent", "swing_percent"}


def _walk(raw: Any, wire: Any, key: str | None, found: list[int]) -> None:
    """Walk the pre-serialization tree and its JSON form in parallel."""
    assert not isinstance(raw, float), f"float at {key}"
    assert not isinstance(wire, float), f"JSON float at {key}"
    if isinstance(raw, Decimal):
        if key in _NON_MONEY_KEYS:
            assert isinstance(wire, str)
            return
        assert isinstance(wire, str), f"{key} is {type(wire).__name__}, not a string"
        assert _MONEY_RE.match(wire), f"{key}={wire!r}"
        found[0] += 1
    elif isinstance(raw, dict):
        for k, v in raw.items():
            _walk(v, wire[str(k)], str(k), found)
    elif isinstance(raw, (list, tuple)):
        assert len(raw) == len(wire)
        for r, w in zip(raw, wire):
            _walk(r, w, key, found)
    elif hasattr(raw, "__dataclass_fields__"):
        for name in raw.__dataclass_fields__:
            _walk(getattr(raw, name), wire[name], name, found)


# Feature: year-end-checklist, Property 20: Money values have the wire form
@settings(max_examples=200, deadline=None)
@given(snapshot=_snapshots(), config=_configs)
def test_money_values_have_wire_form(
    snapshot: YearSnapshot, config: ChecklistConfig
) -> None:
    """**Validates: Requirements 15.9, 21.1, 21.4**"""
    checklist = build_checklist(snapshot, config)
    wire = json.loads(json.dumps(_to_jsonable(checklist)))

    found = [0]
    for item, wire_item in zip(checklist.items, wire["items"]):
        _walk(item.details, wire_item["details"], "details", found)
    # Thresholds: money fields use the wire form; the percentage and counts do not.
    for name in ("large_entry_amount", "capital_candidate_amount", "swing_minimum_amount"):
        value = wire["thresholds"][name]
        assert isinstance(value, str) and _MONEY_RE.match(value), (name, value)
    assert isinstance(wire["thresholds"]["swing_percent"], str)

    # Every dollar amount in a Reason has exactly two decimal places.
    for item in checklist.items:
        for amount in _DOLLAR_RE.findall(item.reason):
            assert _DOLLAR_OK.match(amount), (item.id, amount, item.reason)
