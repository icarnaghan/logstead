"""Retention constant is defined once; basic checks of the pure event helpers."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from logstead.services import activity_events as ev
from logstead.services.activity_config import ACTIVITY_CONFIG

SRC = Path(__file__).resolve().parents[2] / "src" / "logstead"
AT = datetime(2025, 3, 1, 12, 0, 0, 123000, tzinfo=timezone.utc)


def test_retention_is_24_months_and_defined_once():
    assert ACTIVITY_CONFIG.retention_days == 730
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p.name != "activity_config.py" and re.search(r"(?<![\w.])730(?![\w.])", p.read_text())
    ]
    assert offenders == []


def test_ttl_reads_config():
    assert "ACTIVITY_CONFIG" in (SRC / "services" / "activity_events.py").read_text()
    assert ev.ttl_for(AT) - int(AT.timestamp()) == ACTIVITY_CONFIG.retention_days * 86400


def test_diff_and_round_trip():
    b = {"date": "2025-01-01", "amount": "10.00", "type": "expense", "extra": "x"}
    a = {**b, "amount": "12.50"}
    assert ev.diff("transaction", b, a) == ({"amount": "10.00"}, {"amount": "12.50"})
    assert ev.diff("transaction", b, b) == ({}, {})


def test_bound_limits():
    vals = {f: "é" * 500 for f in ev.FIELDS["property"]}
    out, truncated = ev.bound(vals)
    assert truncated and ev._json_size(out) <= ACTIVITY_CONFIG.json_max_bytes
    assert all(len(v) <= 200 for v in out.values())


def test_sk_and_cursor():
    sk = ev.event_sk(AT, "abc-123")
    assert sk == f"ACT#{ev.inverted_millis(AT)}#abc-123"
    assert len(ev.inverted_millis(AT)) == 14
    assert ev.decode_cursor(ev.encode_cursor(sk)) == sk
    for bad in ("", "!!!", ev.encode_cursor("USER#x"), ev.encode_cursor(sk) + "A"):
        assert ev.decode_cursor(bad) is None


def test_summary_length_and_restorable():
    s = ev.summarize("create", "transaction", None, {"description": "x" * 500})
    assert len(s) <= 200
    assert ev.is_restorable("transaction", "delete", {}, 0)
    assert not ev.is_restorable("transaction", "delete", {"imported": True}, 0)
    assert not ev.is_restorable("transaction", "delete", {}, None)
    assert not ev.is_restorable("asset", "update", {}, 0)
    assert not ev.is_restorable("loan", "delete", {"interest_overrides": {"2024": "1.00"}}, 0)
    assert ev.is_restorable("asset", "delete", {}, None)
