"""Rule properties for carryforward and repairs (Requirements 4, 9, 10)."""
from __future__ import annotations
from types import SimpleNamespace
from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Property 9: Carryforward mapping
# **Validates: Requirements 4.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.10**
# ---------------------------------------------------------------------------
def _cf_money(lo="0.00", hi="100000.00"):
    from decimal import Decimal as _D

    return st.decimals(
        min_value=_D(lo), max_value=_D(hi), places=2,
        allow_nan=False, allow_infinity=False,
    )


@st.composite
def _cf_rows(draw):
    from decimal import Decimal as _D
    from logstead.services.carryforward import ReconciledYear

    status = draw(st.sampled_from(["ok", "unreported", "mismatch", "carried"]))
    expected = draw(st.one_of(st.just(_D("0.00")), _cf_money()))
    reported = None if status == "unreported" else draw(_cf_money())
    drift = None if status == "unreported" else draw(_cf_money("-50000.00", "50000.00"))
    origin = draw(st.integers(2000, 2100)) if status == "carried" else None
    return ReconciledYear(
        tax_year=2024,
        schedule_e_net=draw(_cf_money("-50000.00", "50000.00")),
        expected_carryforward=draw(_cf_money()),
        reported_carryforward=reported,
        status=status,
        drift=drift,
        carried_from_year=origin,
        expected_carry_in=expected,
    )


def _cf_snapshot(row, tolerance):
    return SimpleNamespace(tax_year=2024, carryforward=row, status_tolerance=tolerance)


@settings(max_examples=200, deadline=None)
@given(row=st.one_of(st.none(), _cf_rows()), tolerance=_cf_money("0.00", "100.00"))
def test_property_9_carryforward_mapping(row, tolerance):
    from logstead.services.checklist import _rule_carryforward_reconciled, format_money
    from logstead.services.checklist_config import CHECKLIST_CONFIG

    item = _rule_carryforward_reconciled(_cf_snapshot(row, tolerance), CHECKLIST_CONFIG)
    assert item.id == "carryforward_reconciled"
    assert item.link == "/carryforward"
    assert "all properties" in item.reason
    assert format_money(tolerance) in item.reason
    d = item.details
    if row is None:
        assert item.status == "not_applicable"
        assert d["status"] is None
        return
    assert d["status"] == row.status
    assert d["reported_carry_in"] == row.reported_carryforward
    assert d["expected_carry_in"] == row.expected_carry_in
    assert d["drift"] == row.drift
    if row.status == "ok":
        assert item.status == "done"
    elif row.status == "unreported":
        if row.expected_carry_in == 0:
            assert item.status == "not_applicable"
            assert "no carry-in is expected" in item.reason.lower()
        else:
            assert item.status == "needs_attention"
            assert format_money(row.expected_carry_in) in item.reason
    elif row.status == "mismatch":
        assert item.status == "needs_attention"
        for amount in (row.reported_carryforward, row.expected_carry_in, row.drift):
            assert format_money(amount) in item.reason
    else:
        assert item.status == "needs_attention"
        assert str(row.carried_from_year) in item.reason


# ---------------------------------------------------------------------------
# Property 10: Itemized repairs versus the entered total
# ---------------------------------------------------------------------------
from decimal import Decimal as _D10
from types import SimpleNamespace as _NS10

from hypothesis import given as _given10, settings as _settings10
from hypothesis import strategies as _st10

from logstead.models.transaction import Transaction as _Txn10
from logstead.services.checklist import (
    _rule_repairs_exceed_total,
    format_money as _fmt10,
)
from logstead.services.checklist_config import CHECKLIST_CONFIG as _CFG10
from logstead.services.itemized import resolve_category_rows as _resolve10

_amounts10 = _st10.decimals(_D10("0.01"), _D10("5000.00"), places=2)


@_st10.composite
def _repairs_rows10(draw):
    rows = []
    n = draw(_st10.integers(0, 8))
    for i in range(n):
        rows.append(
            _Txn10(
                id=f"t{i}",
                property_id="p1",
                date="2024-03-01",
                amount=draw(_amounts10),
                type="expense",
                category_id="repairs",
                schedule_e_line=14,
                itemized=draw(_st10.booleans()),
                imported=draw(_st10.booleans()),
            )
        )
    return rows


# Feature: year-end-checklist, Property 10: Itemized repairs versus the entered total
# **Validates: Requirements 4.2, 10.1, 10.2, 10.3, 10.5**
@_settings10(max_examples=300, deadline=None)
@_given10(rows=_repairs_rows10())
def test_repairs_exceed_total(rows):
    repairs = _resolve10(rows, "repairs")
    res = repairs.resolution
    snapshot = _NS10(property_id="p1", tax_year=2024, repairs=repairs)
    item = _rule_repairs_exceed_total(snapshot, _CFG10)

    if res.entered_total is None or res.itemized_count == 0:
        assert item.status == "not_applicable"
    elif res.remainder < _D10("0.00"):
        assert item.status == "needs_attention"
        overage = res.itemized_sum - res.entered_total
        assert overage > 0
        assert _fmt10(overage) in item.reason
        assert _fmt10(res.entered_total) in item.reason
        assert _fmt10(res.itemized_sum) in item.reason
    else:
        assert item.status == "done"

    assert item.details["entered_total"] == res.entered_total
    assert item.details["itemized_sum"] == res.itemized_sum
    assert item.details["remainder"] == res.remainder
    assert item.details["line_source"] == res.source
    assert item.link.endswith("year=2024") or "2024" in item.link


# ---------------------------------------------------------------------------
# Property 11: Large Repairs entries to review
# ---------------------------------------------------------------------------
from logstead.services.checklist import (
    _rule_repairs_capital_candidates,
    property_link as _plink11,
)
from logstead.util.money import to_money as _to_money11

_T11 = _CFG10.capital_candidate_amount
_amounts11 = _st10.one_of(
    _st10.decimals(_D10("0.01"), _D10("6000.00"), places=2),
    _st10.sampled_from([_T11, _T11 - _D10("0.01"), _T11 + _D10("0.01")]),
)


@_st10.composite
def _repairs_rows11(draw):
    n = draw(_st10.integers(0, 8))
    rows = []
    for i in range(n):
        rows.append(
            _Txn10(
                id=f"t{i}",
                property_id="p1",
                date="2024-03-01",
                amount=draw(_amounts11),
                type="expense",
                category_id="repairs",
                schedule_e_line=14,
                itemized=True,
                imported=False,
            )
        )
    return rows


# Feature: year-end-checklist, Property 11: Large Repairs entries to review
# **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.6**
@_settings10(max_examples=300, deadline=None)
@_given10(rows=_repairs_rows11())
def test_repairs_capital_candidates(rows):
    repairs = _resolve10(rows, "repairs")
    snapshot = _NS10(property_id="p1", tax_year=2024, repairs=repairs)
    item = _rule_repairs_capital_candidates(snapshot, _CFG10)

    entries = list(repairs.entries)
    flagged = [e for e in entries if e.amount >= _T11]

    assert item.link == _plink11("p1", "assets")
    if not entries:
        assert item.status == "not_applicable"
    elif flagged:
        assert item.status == "needs_attention"
        assert str(len(flagged)) in item.reason
        assert _fmt10(_T11) in item.reason
        assert "you decide" in item.reason
        assert "capital improvement" not in item.reason
    else:
        assert item.status == "done"

    listed = item.details["entries"]
    assert [d["id"] for d in listed] == [e.id for e in flagged]
    for d, e in zip(listed, flagged):
        assert d["date"] == e.date
        assert d["description"] == e.description
        assert d["amount"] == _to_money11(e.amount)
        assert d["link"] == _plink11("p1", "repairs", 2024)


# ---------------------------------------------------------------------------
# Property 12: Receipts on large expenses
# ---------------------------------------------------------------------------
from logstead.services.checklist import (
    MAX_RECEIPT_DETAILS as _MAX12,
    _rule_receipts_missing,
)

_L12 = _CFG10.large_entry_amount
_amounts12 = _st10.one_of(
    _st10.decimals(_D10("0.01"), _D10("1000.00"), places=2),
    _st10.sampled_from([_L12, _L12 - _D10("0.01"), _L12 + _D10("0.01")]),
)


@_st10.composite
def _receipt_cases12(draw):
    n = draw(_st10.integers(0, 60))
    rows = []
    present = {}
    for i in range(n):
        rows.append(
            _Txn10(
                id=f"t{i}",
                property_id="p1",
                date="2024-03-01",
                amount=draw(_amounts12),
                type=draw(_st10.sampled_from(["expense", "expense", "income"])),
                category_id="repairs",
                description=f"d{i}",
                schedule_e_line=14,
                imported=draw(_st10.booleans()),
            )
        )
        if draw(_st10.booleans()):
            present[f"t{i}"] = draw(_st10.booleans())
    return rows, present


# Feature: year-end-checklist, Property 12: Receipts on large expenses
# **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6**
@_settings10(max_examples=300, deadline=None)
@_given10(case=_receipt_cases12())
def test_receipts_missing(case):
    rows, present = case
    snapshot = _NS10(
        property_id="p1", tax_year=2024, transactions=rows, receipt_present=present
    )
    item = _rule_receipts_missing(snapshot, _CFG10)

    evaluated = [
        t for t in rows
        if t.type == "expense" and not t.imported and t.amount >= _L12
    ]
    missing = [t for t in evaluated if not present.get(t.id, False)]

    assert item.link == _plink11("p1", "transactions", 2024)
    d = item.details
    assert d["evaluated_count"] == len(evaluated)
    assert d["missing_count"] == len(missing)
    assert len(d["transactions"]) == min(len(missing), _MAX12)
    assert len(d["transactions"]) <= 25
    missing_ids = {t.id for t in missing}
    assert all(x["id"] in missing_ids for x in d["transactions"])

    if not evaluated:
        assert item.status == "not_applicable"
    elif missing:
        assert item.status == "needs_attention"
        assert str(len(missing)) in item.reason
        assert str(len(evaluated)) in item.reason
        assert _fmt10(_L12) in item.reason
    else:
        assert item.status == "done"
