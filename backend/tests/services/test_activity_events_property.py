"""Property tests for the pure activity event helpers (Properties 16, 17, 19, 21)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.activity_config import ACTIVITY_CONFIG
from logstead.services.activity_events import (
    FIELDS,
    bound,
    diff,
    event_sk,
    is_restorable,
    project,
    summarize,
    ttl_for,
)

ENTITIES = sorted(FIELDS)
SETTINGS = settings(max_examples=100, deadline=None)

money = st.builds(lambda c: f"{c // 100}.{c % 100:02d}", st.integers(0, 10**9))
text = st.text(max_size=300)
field_value = st.one_of(st.none(), st.booleans(), text, money)
entity_st = st.sampled_from(ENTITIES)


def record_for(entity: str):
    return st.fixed_dictionaries({}, optional={f: field_value for f in FIELDS[entity]}).map(
        lambda d: {**d, "id": "x", "receipt_key": "s3://secret", "extra": "ignored"}
    )


entity_and_pair = entity_st.flatmap(
    lambda e: st.tuples(st.just(e), record_for(e), record_for(e))
)


# Feature: ui-polish-and-consistency, Property 16: Event projection, diff and round trip
@SETTINGS
@given(entity_and_pair)
def test_property_16_projection_diff_round_trip(case):
    """**Validates: Requirements 13.10, 14.2, 14.3, 14.4, 14.5, 14.9**"""
    entity, before, after = case
    b, a = project(entity, before), project(entity, after)
    assert set(b) == set(a) == set(FIELDS[entity])  # allow-list only, secrets dropped

    db, da = diff(entity, before, after)
    assert set(db) == set(da)
    assert set(db) == {f for f in FIELDS[entity] if b[f] != a[f]}
    for f in db:
        assert db[f] == b[f] and da[f] == a[f]  # character for character

    if b == a:
        assert db == {} and da == {}
    # Applying `after` over `before` gives the projection of the new record.
    assert {**b, **da} == a
    # diff(b, a) is the inverse of diff(a, b).
    assert diff(entity, after, before) == (da, db)
    # Reverting the change restores the old projection.
    assert {**a, **db} == b
    # No change: diff against itself is empty.
    assert diff(entity, before, before) == ({}, {})


# Feature: ui-polish-and-consistency, Property 17: Event bounds
bound_maps = st.dictionaries(
    st.sampled_from(sorted({f for fs in FIELDS.values() for f in fs})),
    st.one_of(st.none(), st.booleans(), st.text(max_size=1500)),
)


@SETTINGS
@given(bound_maps)
def test_property_17_bound(values):
    """**Validates: Requirements 14.1, 14.6**"""
    cfg = ACTIVITY_CONFIG
    out, truncated = bound(values)
    import json

    size = len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert size <= cfg.json_max_bytes
    assert all(len(v) <= cfg.value_max_chars for v in out.values() if isinstance(v, str))
    assert set(out) == set(values)
    assert truncated == (out != values)
    again, again_truncated = bound(out)
    assert again == out and again_truncated is False


@SETTINGS
@given(
    st.sampled_from(["create", "update", "delete", "restore", "import"]),
    entity_st | st.sampled_from(["backup", "schedule_e"]),
    st.dictionaries(st.sampled_from(["description", "name", "amount", "notes"]), text),
    st.dictionaries(st.sampled_from(["description", "name", "amount", "notes"]), text),
    st.dictionaries(st.sampled_from(["created", "replaced"]), st.integers(0, 10**6)),
)
def test_property_17_summarize_length(action, entity, before, after, extra):
    """**Validates: Requirements 14.1, 14.6**"""
    for b, a in ((before, after), (None, after), (before, None), (None, None)):
        assert len(summarize(action, entity, b, a, extra)) <= ACTIVITY_CONFIG.summary_max_chars


# Feature: ui-polish-and-consistency, Property 19: Event keys and retention
instants = st.datetimes(
    min_value=datetime(2001, 1, 1), max_value=datetime(2200, 1, 1), timezones=st.just(timezone.utc)
)
event_ids = st.uuids().map(str)
SK_RE = re.compile(r"^ACT#\d{14}#[0-9a-f-]{36}$")


@SETTINGS
@given(instants, st.integers(1, 10**10), event_ids, event_ids)
def test_property_19_sk_ordering(t1, delta_ms, id_a, id_b):
    """**Validates: Requirements 18.1, 18.2**"""
    t2 = t1 + timedelta(milliseconds=delta_ms)
    if t2.year > 2200:
        t1, t2 = t2 - timedelta(days=1), t2
    assert event_sk(t2, id_a) < event_sk(t1, id_b)
    for sk in (event_sk(t1, id_a), event_sk(t2, id_b)):
        assert SK_RE.match(sk)
    if id_a != id_b:
        assert (event_sk(t1, id_a) < event_sk(t1, id_b)) == (id_a < id_b)
    else:
        assert event_sk(t1, id_a) == event_sk(t1, id_b)


@SETTINGS
@given(instants)
def test_property_19_ttl(at):
    """**Validates: Requirements 18.1, 18.2**"""
    expected = int((at + timedelta(days=ACTIVITY_CONFIG.retention_days)).timestamp())
    assert ttl_for(at) == expected
    assert ttl_for(at.replace(tzinfo=None)) == expected  # naive treated as UTC
    assert ACTIVITY_CONFIG.retention_days == 730


def test_property_19_sk_uses_uuid_shape():
    """**Validates: Requirements 18.1, 18.2**"""
    assert SK_RE.match(event_sk(datetime.now(timezone.utc), str(uuid.uuid4())))


# Feature: ui-polish-and-consistency, Property 21: Restorable classification
# Shared table of (entity, action, record, receipt_count, expected). The same rules live in
# frontend/src/lib/undoMappers.ts (isTransactionSafeDelete, isItemizedEntrySafeDelete,
# isLoanSafeDelete); the test below checks the table against both implementations' rules.
SHARED_CASES = [
    ("transaction", "delete", {}, 0, True),
    ("transaction", "delete", {}, 1, False),
    ("transaction", "delete", {}, None, False),
    ("transaction", "delete", {"imported": True}, 0, False),
    ("transaction", "delete", {"itemized": True}, 0, False),
    ("itemized_entry", "delete", {}, 0, True),
    ("itemized_entry", "delete", {}, 2, False),
    ("itemized_entry", "delete", {}, None, False),
    ("asset", "delete", {}, None, True),
    ("loan", "delete", {}, None, True),
    ("loan", "delete", {"interest_overrides": {}}, None, True),
    ("loan", "delete", {"interest_overrides": {"2024": "1.00"}}, None, False),
    ("property", "delete", {}, 0, False),
    ("backup", "delete", {}, 0, False),
    ("asset", "update", {}, None, False),
    ("transaction", "create", {}, 0, False),
]


def test_property_21_shared_table():
    """**Validates: Requirements 17.1, 17.2**"""
    for entity, action, record, count, expected in SHARED_CASES:
        assert is_restorable(entity, action, record, count) is expected, (entity, action, record, count)


def test_property_21_agrees_with_undo_mappers_source():
    """**Validates: Requirements 17.1, 17.2**"""
    src = (Path(__file__).parents[3] / "frontend/src/lib/undoMappers.ts").read_text()
    assert "t.itemized !== true && t.imported !== true && receiptCount === 0" in src
    assert re.search(r"isItemizedEntrySafeDelete\([^)]*\)[^{]*\{\s*return receiptCount === 0;", src)
    assert "Object.keys(l.interest_overrides ?? {}).length === 0" in src


records = st.fixed_dictionaries(
    {},
    optional={
        "itemized": st.booleans(),
        "imported": st.booleans(),
        "interest_overrides": st.dictionaries(st.text(min_size=1, max_size=4), st.text(max_size=4), max_size=2),
    },
)


@SETTINGS
@given(
    st.sampled_from(ENTITIES + ["backup", "schedule_e"]),
    st.sampled_from(["create", "update", "delete", "restore", "import"]),
    records,
    st.one_of(st.none(), st.integers(0, 5)),
)
def test_property_21_iff(entity, action, record, count):
    """**Validates: Requirements 17.1, 17.2**"""
    if action != "delete":
        expected = False
    elif entity == "transaction":
        expected = not record.get("itemized") and not record.get("imported") and count == 0
    elif entity == "itemized_entry":
        expected = count == 0
    elif entity == "asset":
        expected = True
    elif entity == "loan":
        expected = not record.get("interest_overrides")
    else:
        expected = False
    assert is_restorable(entity, action, record, count) is expected
