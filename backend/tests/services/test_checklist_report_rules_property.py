"""Report-derived rule properties (Requirements 5.x, 6.x)."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.checklist import _rule_expenses_entered, _rule_income_entered
from logstead.services.checklist_config import CHECKLIST_CONFIG
from logstead.services.report import ReportLine

_ZERO = Decimal("0.00")
_INCOME_LINES = (3, 4)
_EXPENSE_LINES = (5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)

_total = st.one_of(
    st.just(_ZERO),
    st.decimals(
        min_value=Decimal("0.00"),
        max_value=Decimal("100000.00"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)


def _snapshot(lines):
    report = SimpleNamespace(lines=tuple(lines), line=lambda n: next(
        (row for row in lines if row.line == n), None
    ))
    return SimpleNamespace(property_id="p1", tax_year=2024, report=report)


@st.composite
def _lines(draw):
    rows = [
        ReportLine(n, f"L{n}", "income", draw(_total)) for n in _INCOME_LINES
    ]
    rows += [
        ReportLine(n, f"L{n}", "expense", draw(_total)) for n in _EXPENSE_LINES
    ]
    return rows


# Feature: year-end-checklist, Property 5: Income and expenses entered
# **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
@settings(max_examples=200, deadline=None)
@given(_lines())
def test_income_and_expenses_entered(rows):
    snap = _snapshot(rows)
    income = sum((r.total for r in rows if r.kind == "income"), _ZERO)
    expenses = sum(
        (r.total for r in rows if r.kind == "expense" and r.line != 18), _ZERO
    )

    income_item = _rule_income_entered(snap, CHECKLIST_CONFIG)
    expense_item = _rule_expenses_entered(snap, CHECKLIST_CONFIG)

    assert income_item.status == ("done" if income > 0 else "needs_attention")
    assert expense_item.status == ("done" if expenses > 0 else "needs_attention")
    assert income_item.details["income_total"] == income
    assert expense_item.details["expense_total"] == expenses


def test_only_line_18_expense_needs_attention():
    rows = [ReportLine(3, "Rents", "income", Decimal("100.00"))]
    rows += [
        ReportLine(n, f"L{n}", "expense", Decimal("500.00") if n == 18 else _ZERO)
        for n in _EXPENSE_LINES
    ]
    item = _rule_expenses_entered(_snapshot(rows), CHECKLIST_CONFIG)
    assert item.status == "needs_attention"
    assert item.details["expense_total"] == _ZERO

# --- Property 6: Depreciation present ----------------------------------------
from decimal import Decimal as _DepDecimal

from hypothesis import given as _dep_given, settings as _dep_settings
from hypothesis import strategies as _dep_st

from logstead.services.checklist_config import CHECKLIST_CONFIG as _DEP_CONFIG
from logstead.services.checklist import (
    YearSnapshot as _DepYearSnapshot,
    _rule_depreciation_present as _dep_rule,
)
from logstead.services.itemized import resolve_category_rows as _dep_resolve_rows
from logstead.services.report import (
    ReportHeader as _DepHeader,
    ReportLine as _DepLine,
    ReportTotals as _DepTotals,
    ScheduleEReport as _DepReport,
)


def _dep_report(year: int, line18: _DepDecimal) -> _DepReport:
    zero = _DepDecimal("0.00")
    return _DepReport(
        header=_DepHeader("p1", "P", "addr", None, year, 365, 0),
        lines=(_DepLine(18, "Depreciation expense or depletion", "expense", line18),),
        other_items=(),
        totals=_DepTotals(zero, line18, zero - line18),
    )


def _dep_snapshot(count: int, line18: _DepDecimal, year: int) -> _DepYearSnapshot:
    return _DepYearSnapshot(
        property_id="p1",
        tax_year=year,
        report=_dep_report(year, line18),
        prior_report=_dep_report(year - 1, _DepDecimal("0.00")),
        transactions=(),
        repairs=_dep_resolve_rows([], "repairs"),
        assets_with_rows=count,
        loans=(),
        carryforward=None,
        status_tolerance=_DepDecimal("2.00"),
        receipt_present={},
    )


# Feature: year-end-checklist, Property 6: Depreciation present
@_dep_settings(max_examples=100, deadline=None)
@_dep_given(
    count=_dep_st.integers(min_value=0, max_value=50),
    line18=_dep_st.one_of(
        _dep_st.just(_DepDecimal("0.00")),
        _dep_st.decimals(
            min_value=0, max_value=_DepDecimal("9999999.99"), places=2
        ),
    ),
    year=_dep_st.integers(min_value=1990, max_value=2100),
)
def test_depreciation_present_decision_table(
    count: int, line18: _DepDecimal, year: int
) -> None:
    """**Validates: Requirements 6.1, 6.2, 6.3, 6.5**"""
    item = _dep_rule(_dep_snapshot(count, line18, year), _DEP_CONFIG)
    assert item.id == "depreciation_present"
    if count == 0:
        assert item.status == "not_applicable"
    elif line18 > 0:
        assert item.status == "done"
    else:
        assert item.status == "needs_attention"
    assert item.details is not None
    assert item.details["assets_with_schedule_rows"] == count
    assert item.details["line_18_total"] == line18


# --- Property 7: Line 12 source ----------------------------------------------
from datetime import date as _l12_date
from decimal import Decimal as _L12Decimal

from hypothesis import given as _l12_given, settings as _l12_settings
from hypothesis import strategies as _l12_st

from logstead.services.checklist import (
    LoanFact as _L12LoanFact,
    _rule_line12_source as _l12_rule,
)
from logstead.services.checklist_config import CHECKLIST_CONFIG as _L12_CONFIG
from logstead.services.report import (
    Line12Detail as _L12Detail,
    ReportHeader as _L12Header,
    ReportLine as _L12Line,
    ReportTotals as _L12Totals,
    ScheduleEReport as _L12Report,
    SupersededManualInterest as _L12Superseded,
)

_L12_YEAR = 2024


def _l12_report(source, line12_total, sup_count, sup_amount) -> _L12Report:
    zero = _L12Decimal("0.00")
    return _L12Report(
        header=_L12Header("p1", "P", "addr", None, _L12_YEAR, 365, 0),
        lines=(_L12Line(12, "Mortgage interest", "expense", line12_total),),
        other_items=(),
        totals=_L12Totals(zero, line12_total, zero - line12_total),
        line12=_L12Detail(source, _L12Superseded(sup_amount, sup_count)),
    )


_l12_money = _l12_st.decimals(
    min_value=_L12Decimal("0.01"),
    max_value=_L12Decimal("99999.99"),
    places=2,
)
_l12_loan = _l12_st.builds(
    _L12LoanFact,
    loan_id=_l12_st.text(alphabet="abcdef0123456789", min_size=1, max_size=8),
    description=_l12_st.just("Loan"),
    anchor_date=_l12_st.dates(
        min_value=_l12_date(2015, 1, 1), max_value=_l12_date(2035, 12, 31)
    ).map(lambda d: d.isoformat()),
    include_in_report=_l12_st.booleans(),
    interest=_l12_money,
    has_override=_l12_st.booleans(),
)


@_l12_st.composite
def _l12_case(draw):
    source = draw(_l12_st.sampled_from(["loan-generated", "transaction-entered"]))
    total = draw(_l12_st.one_of(_l12_st.just(_L12Decimal("0.00")), _l12_money))
    if source == "loan-generated":
        total = draw(_l12_money)
    count = draw(_l12_st.integers(min_value=0, max_value=5))
    amount = draw(_l12_money) if count else _L12Decimal("0.00")
    loans = tuple(draw(_l12_st.lists(_l12_loan, max_size=5)))
    return source, total, count, amount, loans


def _l12_snapshot(report, loans):
    return SimpleNamespace(
        property_id="p1", tax_year=_L12_YEAR, report=report, loans=loans
    )


# Feature: year-end-checklist, Property 7: Line 12 source
@_l12_settings(max_examples=200, deadline=None)
@_l12_given(_l12_case())
def test_line12_source_decision_table(case) -> None:
    """**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**"""
    source, total, count, amount, loans = case
    item = _l12_rule(
        _l12_snapshot(_l12_report(source, total, count, amount), loans), _L12_CONFIG
    )
    cutoff = _l12_date(_L12_YEAR, 12, 31).isoformat()
    applicable = [
        ln for ln in loans if ln.include_in_report and ln.anchor_date <= cutoff
    ]

    if source == "loan-generated":
        expected = "done" if count == 0 else "needs_attention"
    elif total > 0:
        expected = "done"
    elif not applicable:
        expected = "not_applicable"
    else:
        expected = "needs_attention"
    assert item.id == "line12_source"
    assert item.status == expected

    if source == "loan-generated" or applicable:
        assert item.link == "/properties/p1/loans"
    else:
        assert item.link == f"/properties/p1/transactions?year={_L12_YEAR}"

    assert item.details["source"] == source
    assert item.details["line_12_total"] == total
    assert item.details["superseded_count"] == count
    assert item.details["superseded_amount"] == amount
    if source == "loan-generated" and count:
        assert str(count) in item.reason


# Feature: year-end-checklist, Property 7: Line 12 source
@_l12_settings(max_examples=100, deadline=None)
@_l12_given(extra=_l12_st.lists(_l12_loan, max_size=5))
def test_non_applicable_loans_never_change_zero_line12(extra) -> None:
    """**Validates: Requirements 7.4, 7.5**"""
    cutoff = _l12_date(_L12_YEAR, 12, 31).isoformat()
    inert = tuple(
        ln
        for ln in extra
        if not ln.include_in_report or ln.anchor_date > cutoff
    )
    item = _l12_rule(
        _l12_snapshot(
            _l12_report("transaction-entered", _L12Decimal("0.00"), 0, _L12Decimal("0.00")),
            inert,
        ),
        _L12_CONFIG,
    )
    assert item.status == "not_applicable"
    assert item.link == f"/properties/p1/transactions?year={_L12_YEAR}"
