"""Checklist details agree with the report, through the real services over moto.

# Feature: year-end-checklist, Property 16: Details line totals equal the report

**Validates: Requirements 4.1, 4.7**

For generated stored data (income and expense transactions across categories
and two years, itemized repairs entries, a loan, an asset) the line totals in
the checklist ``details`` equal ``ReportingService.report_for`` line totals,
and the swing lines' prior totals equal the prior-year report's totals.
"""
from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.depreciation import AssetInput
from logstead.models.loan import LoanInput
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.services.carryforward import CarryforwardService
from logstead.services.checklist import ChecklistService
from logstead.services.depreciation import DepreciationService
from logstead.services.itemized import EntryInput, ItemizedExpenseService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService
from tests.services.test_imported_marker_update_property import (
    USER_ID,
    _Env,
)

YEAR = 2023
INCOME_CATS = ("rents-received", "royalties-received")
EXPENSE_CATS = ("insurance", "utilities", "advertising", "repairs")

_amount = st.integers(min_value=1, max_value=900_000).map(
    lambda cents: Decimal(cents) / Decimal(100)
)
_txn = st.tuples(
    st.sampled_from((YEAR, YEAR - 1)),
    st.sampled_from(INCOME_CATS + EXPENSE_CATS),
    _amount,
)
_state = st.fixed_dictionaries(
    {
        "txns": st.lists(_txn, max_size=6),
        "entries": st.lists(_amount, max_size=3),
        "loan": st.booleans(),
        "asset": st.booleans(),
    }
)


def _services(env: _Env):
    user = UserContext(user_id=USER_ID)
    properties = PropertyService(env.repo, user)
    depreciation = DepreciationService(env.repo)
    loans = LoanService(env.repo)
    reports = ReportingService(
        env.txns, depreciation, properties, loans=loans
    )
    carry = CarryforwardService(
        env.repo, user, reports, properties, env.txns, depreciation, loans=loans
    )
    checklist = ChecklistService(
        reports, env.txns, depreciation, loans, properties, carry
    )
    return properties, depreciation, loans, reports, checklist


def _seed(env: _Env, state, properties, depreciation, loans) -> str:
    created = properties.create(
        PropertyInput(name="Agree", address_text="1 Agree St")
    )
    assert created.is_ok, created.error
    pid = created.value.id
    for year, category, amount in state["txns"]:
        kind = "income" if category in INCOME_CATS else "expense"
        made = env.txns.create(
            TransactionInput(
                property_id=pid,
                date=f"{year}-04-10",
                amount=amount,
                type=kind,
                category_id=category,
                description="x",
            )
        )
        assert made.is_ok, made.error
    itemized = ItemizedExpenseService(env.txns)
    for amount in state["entries"]:
        made = itemized.create_entry(
            pid,
            "repairs",
            EntryInput(date=f"{YEAR}-05-05", amount=amount, description="e"),
        )
        assert made.is_ok, made.error
    if state["loan"]:
        made = loans.create_loan(
            LoanInput(
                property_id=pid,
                description="Mortgage",
                annual_interest_rate=Decimal("0.05"),
                monthly_payment=Decimal("1000.00"),
                anchor_balance=Decimal("100000.00"),
                anchor_date=f"{YEAR - 1}-12-31",
                original_principal=None,
                closing_date=None,
            )
        )
        assert made.is_ok, made.error
    if state["asset"]:
        made = depreciation.create_asset(
            AssetInput(
                property_id=pid,
                description="Roof",
                cost_basis=Decimal("20000.00"),
                placed_in_service_date=f"{YEAR - 1}-06-01",
            )
        )
        assert made.is_ok, made.error
    return pid


@settings(max_examples=100, deadline=None)
@given(state=_state)
def test_details_line_totals_equal_report(state):
    with mock_aws():
        _check(_Env(), state)


def _check(env: _Env, state) -> None:
    properties, depreciation, loans, reports, checklist = _services(env)
    pid = _seed(env, state, properties, depreciation, loans)

    report = reports.report_for(pid, YEAR).value
    prior = reports.report_for(pid, YEAR - 1).value
    result = checklist.checklist_for(pid, YEAR)
    assert result.is_ok, result.error
    items = {item.id: item for item in result.value.items}

    def total(rep, line: int) -> Decimal:
        row = rep.line(line)
        return row.total if row is not None else Decimal("0.00")

    income = sum((r.total for r in report.lines if r.kind == "income"), Decimal(0))
    expense = sum(
        (r.total for r in report.lines if r.kind == "expense" and r.line != 18),
        Decimal(0),
    )
    assert items["income_entered"].details["income_total"] == income
    assert items["expenses_entered"].details["expense_total"] == expense
    assert items["depreciation_present"].details["line_18_total"] == total(report, 18)
    assert items["line12_source"].details["line_12_total"] == total(report, 12)
    assert items["line12_source"].details["source"] == report.line12.source

    for swing in items["yoy_swings"].details["swings"]:
        assert swing["current_total"] == total(report, swing["line"])
        assert swing["prior_total"] == total(prior, swing["line"])
