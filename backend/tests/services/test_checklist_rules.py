"""Example tests for every rule branch of the year-end checklist (task 2.20).

Items are numbered 1 to 11 in ``ITEM_IDS`` order. Each test pins the status and
the exact Reason text for one branch with concrete amounts.
"""
from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace

from logstead.models.transaction import Transaction
from logstead.services.carryforward import ReconciledYear
from logstead.services.checklist import (
    MAX_RECEIPT_DETAILS,
    LoanFact,
    _rule_carryforward_reconciled,
    _rule_depreciation_present,
    _rule_expenses_entered,
    _rule_imported_values_edited,
    _rule_income_entered,
    _rule_line12_source,
    _rule_loan_interest_confirmed,
    _rule_receipts_missing,
    _rule_repairs_capital_candidates,
    _rule_repairs_exceed_total,
    _rule_yoy_swings,
)
from logstead.services.checklist_config import CHECKLIST_CONFIG as CFG
from logstead.services.itemized import resolve_category_rows
from logstead.services.report import (
    Line12Detail,
    ReportLine,
    SupersededManualInterest,
)

YEAR = 2024
ZERO = D("0.00")


def _lines(**totals):
    """Report lines keyed ``l3``, ``l12`` ...; unspecified lines are 0.00."""
    rows = []
    for n in (3, 4):
        rows.append(ReportLine(n, f"L{n}", "income", D(totals.get(f"l{n}", "0.00"))))
    for n in range(5, 20):
        rows.append(ReportLine(n, f"L{n}", "expense", D(totals.get(f"l{n}", "0.00"))))
    return tuple(rows)


def _report(source="transaction-entered", sup_count=0, sup_amount="0.00", **totals):
    lines = _lines(**totals)
    return SimpleNamespace(
        lines=lines,
        line=lambda n: next((r for r in lines if r.line == n), None),
        line12=Line12Detail(
            source=source,
            superseded_manual_interest=SupersededManualInterest(
                amount=D(sup_amount), count=sup_count
            ),
        ),
    )


def _snap(**kw):
    base = dict(property_id="p1", tax_year=YEAR, report=_report(), loans=())
    base.update(kw)
    return SimpleNamespace(**base)


def _txn(i, amount, *, category="repairs", type="expense", imported=False,
         itemized=False, date="2024-03-01", created="2024-03-01T10:00:00+00:00",
         updated="2024-03-01T10:00:00+00:00", line=14):
    return Transaction(
        id=f"t{i}", property_id="p1", date=date, amount=D(amount), type=type,
        category_id=category, schedule_e_line=line, description=f"desc{i}",
        created_at=created, updated_at=updated, imported=imported,
        itemized=itemized,
    )


def _loan(i="a", *, anchor="2024-06-30", include=True, interest="1000.00",
          override=False):
    return LoanFact(i, f"Loan {i}", anchor, include, D(interest), override)


# --- 1 income_entered --------------------------------------------------------
def test_income_done():
    item = _rule_income_entered(_snap(report=_report(l3="1000.00", l4="250.50")), CFG)
    assert item.status == "done"
    assert item.reason == "Income of $1,250.50 is entered for 2024."
    assert item.link == "/properties/p1/transactions?year=2024"


def test_income_needs_attention():
    item = _rule_income_entered(_snap(), CFG)
    assert item.status == "needs_attention"
    assert item.reason == "No income is entered for 2024."


# --- 2 expenses_entered ------------------------------------------------------
def test_expenses_done_excludes_line_18_note():
    item = _rule_expenses_entered(_snap(report=_report(l9="300.00", l18="900.00")), CFG)
    assert item.status == "done"
    assert item.reason == "Expenses of $300.00 are entered for 2024, not counting depreciation."


def test_expenses_needs_attention_when_only_depreciation():
    item = _rule_expenses_entered(_snap(report=_report(l18="900.00")), CFG)
    assert item.status == "needs_attention"
    assert item.reason == "No expenses are entered for 2024, not counting depreciation."


# --- 3 depreciation_present --------------------------------------------------
def test_depreciation_branches():
    na = _rule_depreciation_present(_snap(assets_with_rows=0), CFG)
    assert (na.status, na.reason) == (
        "not_applicable", "No asset has depreciation scheduled for 2024."
    )
    done = _rule_depreciation_present(
        _snap(assets_with_rows=2, report=_report(l18="1500.00")), CFG
    )
    assert done.status == "done"
    assert done.reason == (
        "Depreciation of $1,500.00 is on Line 18 from 2 asset(s) scheduled for 2024."
    )
    needs = _rule_depreciation_present(_snap(assets_with_rows=1), CFG)
    assert needs.status == "needs_attention"
    assert needs.reason == (
        "1 asset(s) have depreciation scheduled for 2024 but Line 18 is $0.00."
    )
    assert needs.link == "/properties/p1/assets"


# --- 4 line12_source ---------------------------------------------------------
def test_line12_loan_generated_clean():
    item = _rule_line12_source(_snap(report=_report("loan-generated", l12="5000.00")), CFG)
    assert item.status == "done"
    assert item.reason == "Line 12 comes from the loan schedule."
    assert item.link == "/properties/p1/loans"


def test_line12_loan_generated_with_superseded_manual_interest():
    rep = _report("loan-generated", 2, "1200.00", l12="5000.00")
    item = _rule_line12_source(_snap(report=rep), CFG)
    assert item.status == "needs_attention"
    assert item.reason == (
        "Line 12 comes from the loan schedule. 2 manually entered interest "
        "transaction(s) totaling $1,200.00 are not used by the report."
    )


def test_line12_transaction_entered_with_total():
    item = _rule_line12_source(_snap(report=_report(l12="800.00")), CFG)
    assert item.status == "done"
    assert item.reason == "Line 12 comes from entered transactions."
    assert item.link == "/properties/p1/transactions?year=2024"


def test_line12_zero_without_loans_not_applicable():
    item = _rule_line12_source(_snap(), CFG)
    assert item.status == "not_applicable"
    assert item.reason == "No mortgage interest is entered for 2024 and no loan applies."


def test_line12_loan_anchored_after_tax_year_not_applicable():
    item = _rule_line12_source(_snap(loans=(_loan(anchor="2025-01-01"),)), CFG)
    assert item.status == "not_applicable"
    assert item.link == "/properties/p1/transactions?year=2024"


def test_line12_excluded_loan_not_applicable():
    item = _rule_line12_source(_snap(loans=(_loan(include=False),)), CFG)
    assert item.status == "not_applicable"


def test_line12_included_loan_anchored_dec_31_flags():
    item = _rule_line12_source(_snap(loans=(_loan(anchor="2024-12-31"),)), CFG)
    assert item.status == "needs_attention"
    assert item.reason == (
        "A loan applies to 2024 but produced no Line 12 interest, and none is entered."
    )
    assert item.link == "/properties/p1/loans"


# --- 5 loan_interest_confirmed ----------------------------------------------
def test_loan_confirmed_not_applicable_when_not_loan_generated():
    item = _rule_loan_interest_confirmed(_snap(), CFG)
    assert item.status == "not_applicable"
    assert item.reason == "Line 12 for 2024 does not come from the loan schedule."


def _loan_snap(*loans):
    return _snap(report=_report("loan-generated", l12="1000.00"), loans=loans)


def test_loan_confirmed_by_override_or_recent_anchor_done():
    item = _rule_loan_interest_confirmed(
        _loan_snap(_loan("a", anchor="2019-01-01", override=True), _loan("b", anchor="2023-12-31")),
        CFG,
    )
    assert item.status == "done"
    assert item.reason == (
        "Loan interest for 2024 is confirmed by an override or a recent balance checkpoint."
    )
    assert [r["confirmed"] for r in item.details["loans"]] == [True, True]


def test_loan_unconfirmed_needs_attention_with_count():
    item = _rule_loan_interest_confirmed(
        _loan_snap(_loan("a", anchor="2023-12-30"), _loan("b", anchor="2020-01-01"),
                   _loan("c", anchor="2024-02-01")),
        CFG,
    )
    assert item.status == "needs_attention"
    assert item.reason == (
        "2 loan(s) have no confirmed interest or balance checkpoint within 12 "
        "month(s) of year end, so their interest is estimated from the schedule."
    )
    assert len(item.details["loans"]) == 3


def test_loan_excluded_or_zero_interest_not_evaluated():
    item = _rule_loan_interest_confirmed(
        _loan_snap(_loan("a", anchor="2000-01-01", include=False),
                   _loan("b", anchor="2000-01-01", interest="0.00")),
        CFG,
    )
    assert item.status == "done"
    assert item.details["loans"] == []


# --- 6 carryforward_reconciled ----------------------------------------------
TAIL = (
    " This item covers all properties and is the same on every property's "
    "checklist. Status tolerance: $1.00."
)


def _cf(status, *, expected="0.00", reported=None, drift=None, origin=None):
    row = ReconciledYear(
        tax_year=YEAR, schedule_e_net=D("0.00"), expected_carryforward=D("0.00"),
        reported_carryforward=None if reported is None else D(reported),
        status=status, drift=None if drift is None else D(drift),
        carried_from_year=origin, expected_carry_in=D(expected),
    )
    return _snap(carryforward=row, status_tolerance=D("1.00"))


def test_carryforward_branches():
    none = _rule_carryforward_reconciled(_snap(carryforward=None, status_tolerance=D("1.00")), CFG)
    assert none.status == "not_applicable"
    assert none.reason == "The carryforward reconciliation has no row for 2024." + TAIL
    assert none.link == "/carryforward"

    ok = _rule_carryforward_reconciled(_cf("ok", reported="500.00", expected="500.00"), CFG)
    assert (ok.status, ok.reason) == (
        "done", "The reported carry-in for 2024 matches the expected carry-in." + TAIL
    )

    unrep0 = _rule_carryforward_reconciled(_cf("unreported"), CFG)
    assert (unrep0.status, unrep0.reason) == (
        "not_applicable", "No carry-in is expected for 2024." + TAIL
    )

    unrep = _rule_carryforward_reconciled(_cf("unreported", expected="750.00"), CFG)
    assert unrep.status == "needs_attention"
    assert unrep.reason == (
        "No carry-in is reported for 2024; the expected carry-in is $750.00." + TAIL
    )

    mism = _rule_carryforward_reconciled(
        _cf("mismatch", reported="400.00", expected="750.00", drift="-350.00"), CFG
    )
    assert mism.status == "needs_attention"
    assert mism.reason == (
        "The reported carry-in for 2024 is $400.00, the expected carry-in is "
        "$750.00, and the drift is -$350.00." + TAIL
    )

    carried = _rule_carryforward_reconciled(
        _cf("carried", reported="400.00", expected="750.00", origin=2022), CFG
    )
    assert carried.status == "needs_attention"
    assert carried.reason == (
        "The carry-in for 2024 differs from the expected carry-in because of a "
        "difference carried from 2022." + TAIL
    )


# --- 7 repairs_exceed_total --------------------------------------------------
def _repairs_snap(rows):
    return _snap(repairs=resolve_category_rows(rows, "repairs"))


def test_repairs_exceed_total_branches():
    na = _rule_repairs_exceed_total(_repairs_snap([_txn(1, "100.00", itemized=True)]), CFG)
    assert na.status == "not_applicable"
    assert na.reason == (
        "Repairs for 2024 have no entered total or no itemized entries to compare."
    )
    assert na.link == "/properties/p1/repairs?year=2024"

    na2 = _rule_repairs_exceed_total(_repairs_snap([_txn(1, "100.00")]), CFG)
    assert na2.status == "not_applicable"

    over = _rule_repairs_exceed_total(
        _repairs_snap([_txn(1, "1000.00"), _txn(2, "800.00", itemized=True),
                       _txn(3, "700.00", itemized=True)]), CFG)
    assert over.status == "needs_attention"
    assert over.reason == (
        "Itemized repairs of $1,500.00 exceed the entered total of $1,000.00 by $500.00."
    )

    ok = _rule_repairs_exceed_total(
        _repairs_snap([_txn(1, "1000.00"), _txn(2, "1000.00", itemized=True)]), CFG)
    assert ok.status == "done"
    assert ok.reason == (
        "Itemized repairs of $1,000.00 are within the entered total of $1,000.00."
    )


# --- 8 repairs_capital_candidates -------------------------------------------
def test_capital_candidates_branches_and_review_wording():
    na = _rule_repairs_capital_candidates(_repairs_snap([]), CFG)
    assert na.status == "not_applicable"
    assert na.reason == "There are no itemized repairs entries for 2024."

    done = _rule_repairs_capital_candidates(
        _repairs_snap([_txn(1, "2499.99", itemized=True)]), CFG)
    assert done.status == "done"
    assert done.reason == "No itemized repairs entry for 2024 is at or above $2,500.00."

    one = _rule_repairs_capital_candidates(
        _repairs_snap([_txn(1, "2500.00", itemized=True)]), CFG)
    assert one.status == "needs_attention"
    assert one.reason == (
        "1 itemized repairs entry is at or above $2,500.00. Review them: you "
        "decide whether each is a repair or an improvement."
    )

    two = _rule_repairs_capital_candidates(
        _repairs_snap([_txn(1, "2500.00", itemized=True), _txn(2, "9000.00", itemized=True)]),
        CFG)
    assert two.reason == (
        "2 itemized repairs entries are at or above $2,500.00. Review them: you "
        "decide whether each is a repair or an improvement."
    )
    assert "capital improvement" not in two.reason
    assert two.link == "/properties/p1/assets"


# --- 9 receipts_missing ------------------------------------------------------
def test_receipts_branches():
    na = _rule_receipts_missing(
        _snap(transactions=(_txn(1, "249.99"), _txn(2, "900.00", imported=True),
                            _txn(3, "900.00", type="income")),
              receipt_present={}), CFG)
    assert na.status == "not_applicable"
    assert na.reason == (
        "No entered expense for 2024 is at or above $250.00, so no receipts are checked."
    )

    done = _rule_receipts_missing(
        _snap(transactions=(_txn(1, "250.00"), _txn(2, "300.00")),
              receipt_present={"t1": True, "t2": True}), CFG)
    assert done.status == "done"
    assert done.reason == "All 2 expense(s) at or above $250.00 have a receipt attached."

    needs = _rule_receipts_missing(
        _snap(transactions=(_txn(1, "250.00"), _txn(2, "300.00"), _txn(3, "50.00")),
              receipt_present={"t1": True}), CFG)
    assert needs.status == "needs_attention"
    assert needs.reason == "1 of 2 expense(s) at or above $250.00 have no receipt attached."
    assert [t["id"] for t in needs.details["transactions"]] == ["t2"]


def test_receipts_details_capped_at_25_with_30_missing():
    txns = tuple(_txn(i, "300.00") for i in range(30))
    item = _rule_receipts_missing(_snap(transactions=txns, receipt_present={}), CFG)
    assert MAX_RECEIPT_DETAILS == 25
    assert item.status == "needs_attention"
    assert item.reason == "30 of 30 expense(s) at or above $250.00 have no receipt attached."
    assert item.details["missing_count"] == 30
    assert item.details["evaluated_count"] == 30
    assert len(item.details["transactions"]) == 25


# --- 10 yoy_swings -----------------------------------------------------------
def test_yoy_branches_and_review_wording():
    na = _rule_yoy_swings(_snap(prior_report=_report()), CFG)
    assert na.status == "not_applicable"
    assert na.reason == "There is no prior-year data to compare with 2024."
    assert na.link == "/properties/p1/reports?year=2024"

    done = _rule_yoy_swings(
        _snap(prior_report=_report(l3="10000.00"), report=_report(l3="10400.00")), CFG)
    assert done.status == "done"
    assert done.reason == (
        "No line changed from the prior year by a review-worthy amount in 2024."
    )

    needs = _rule_yoy_swings(
        _snap(prior_report=_report(l3="10000.00"),
              report=_report(l3="16000.00", l9="600.00")), CFG)
    assert needs.status == "needs_attention"
    assert needs.reason == (
        "2 line(s) changed by at least 50% and $500.00 from the prior year. "
        "Review these changes for a typing error or a missing entry."
    )
    by_line = {s["line"]: s for s in needs.details["swings"]}
    assert by_line[3]["percent"] == D("60.0")
    assert by_line[3]["change"] == D("6000.00")
    assert by_line[9]["percent"] is None
    assert "wrong" not in needs.reason


# --- 11 imported_values_edited ----------------------------------------------
NOTE = " Re-importing a Schedule E for this year replaces imported values."
EDIT_AT = "2024-05-01T10:00:00+00:00"


def test_imported_branches():
    na = _rule_imported_values_edited(_snap(transactions=(_txn(1, "10.00"),)), CFG)
    assert na.status == "not_applicable"
    assert na.reason == "No values imported from a Schedule E exist for 2024." + NOTE

    done = _rule_imported_values_edited(
        _snap(transactions=(_txn(1, "10.00", imported=True),
                            _txn(2, "10.00", imported=True))), CFG)
    assert done.status == "done"
    assert done.reason == "All 2 imported line(s) are unchanged since import." + NOTE

    needs = _rule_imported_values_edited(
        _snap(transactions=(_txn(1, "10.00", imported=True, updated=EDIT_AT),
                            _txn(2, "10.00", imported=True))), CFG)
    assert needs.status == "needs_attention"
    assert needs.reason == (
        "1 imported line(s) were edited after import and may no longer match "
        "the imported return." + NOTE
    )
    assert needs.details["edited"][0]["id"] == "t1"
    assert needs.details["edited"][0]["updated_at"] == EDIT_AT
