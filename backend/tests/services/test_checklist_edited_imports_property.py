"""Property 14: Imported values later edited (Requirements 14.1-14.5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.transaction import Transaction
from logstead.services.checklist import _rule_imported_values_edited
from logstead.services.checklist_config import CHECKLIST_CONFIG

_BASE = datetime(2024, 3, 1, 12, 0, 0)
_UTC = timezone.utc
_OFFSET = timezone(timedelta(hours=-5))


def _aware_or_naive(dt: datetime, aware: bool, tz) -> datetime:
    return dt.replace(tzinfo=tz) if aware else dt


@st.composite
def _timestamp_pair(draw):
    """Return (created_at, updated_at, expected_edited)."""
    kind = draw(
        st.sampled_from(
            ["valid", "equal", "reversed", "missing", "unparseable", "mixed"]
        )
    )
    seconds = draw(st.integers(min_value=0, max_value=10**6))
    micro = draw(st.sampled_from([0, 0, 5, 999999]))
    created = _BASE.replace(microsecond=micro)
    later = created + timedelta(seconds=seconds, microseconds=draw(st.integers(0, 3)))
    aware = draw(st.booleans())
    tz = draw(st.sampled_from([_UTC, _OFFSET]))
    c = _aware_or_naive(created, aware, tz)

    if kind == "valid":
        u = _aware_or_naive(later, aware, tz)
        return c.isoformat(), u.isoformat(), later > created
    if kind == "equal":
        return c.isoformat(), c.isoformat(), False
    if kind == "reversed":
        u = _aware_or_naive(created - timedelta(seconds=seconds + 1), aware, tz)
        return c.isoformat(), u.isoformat(), False
    if kind == "missing":
        which = draw(st.sampled_from(["created", "updated", "both"]))
        cs = None if which in ("created", "both") else c.isoformat()
        us = None if which in ("updated", "both") else _aware_or_naive(
            later, aware, tz
        ).isoformat()
        if draw(st.booleans()):  # empty string counts as missing too
            cs = "" if cs is None else cs
        return cs, us, False
    if kind == "unparseable":
        bad = draw(st.sampled_from(["not-a-date", "2024-13-45T00:00:00", "yesterday"]))
        u = _aware_or_naive(later, aware, tz).isoformat()
        if draw(st.booleans()):
            return bad, u, False
        return c.isoformat(), bad, False
    # mixed: one naive and one aware, never comparable
    u = later.replace(tzinfo=_UTC)
    return created.isoformat(), u.isoformat(), False


@st.composite
def _transactions(draw):
    n = draw(st.integers(min_value=0, max_value=10))
    rows = []
    expected_edited = []
    imported_ids = []
    for i in range(n):
        created, updated, edited = draw(_timestamp_pair())
        imported = draw(st.booleans())
        txn = Transaction(
            id=f"t{i}",
            property_id="p1",
            date="2024-05-01",
            amount=Decimal("100.00"),
            type="income",
            category_id="rents",
            schedule_e_line=3,
            created_at=created,
            updated_at=updated,
            imported=imported,
        )
        rows.append(txn)
        if imported:
            imported_ids.append(txn.id)
            if edited:
                expected_edited.append(txn.id)
    return tuple(rows), imported_ids, expected_edited


def _snapshot(transactions):
    return SimpleNamespace(
        property_id="p1", tax_year=2024, transactions=transactions
    )


# Feature: year-end-checklist, Property 14: Imported values later edited
@settings(max_examples=200, deadline=None)
@given(_transactions())
def test_imported_values_edited(data):
    """**Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5**"""
    rows, imported_ids, expected_edited = data
    item = _rule_imported_values_edited(_snapshot(rows), CHECKLIST_CONFIG)

    assert item.id == "imported_values_edited"
    if not imported_ids:
        assert item.status == "not_applicable"
    elif expected_edited:
        assert item.status == "needs_attention"
    else:
        assert item.status == "done"

    assert item.details["imported_count"] == len(imported_ids)
    # The design names the list ``rows``; the implementation uses ``edited``.
    listed = item.details["edited"]
    assert [r["id"] for r in listed] == expected_edited
    assert "Re-importing a Schedule E for this year replaces imported values." in item.reason


def test_equal_reversed_and_mixed_timestamps_are_not_edited():
    def txn(i, c, u):
        return Transaction(
            id=i, property_id="p1", date="2024-01-01", amount=Decimal("1.00"),
            type="income", category_id="rents", schedule_e_line=3,
            created_at=c, updated_at=u, imported=True,
        )

    rows = (
        txn("eq", "2024-03-01T12:00:00", "2024-03-01T12:00:00.000000"),
        txn("rev", "2024-03-02T12:00:00", "2024-03-01T12:00:00"),
        txn("mix", "2024-03-01T12:00:00", "2024-03-02T12:00:00+00:00"),
        txn("bad", "oops", "2024-03-02T12:00:00"),
    )
    item = _rule_imported_values_edited(_snapshot(rows), CHECKLIST_CONFIG)
    assert item.status == "done"
    assert item.details["edited"] == []
