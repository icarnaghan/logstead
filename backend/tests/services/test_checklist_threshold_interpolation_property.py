"""Property 2: applied thresholds are echoed and interpolated.

Requirements 1.7 and 3.4.
"""
from __future__ import annotations

from decimal import ROUND_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.models.transaction import Transaction
from logstead.services.checklist import YearSnapshot, build_checklist
from logstead.services.checklist_config import ChecklistConfig
from logstead.services.itemized import resolve_category_rows
from logstead.services.report import (
    ReportHeader,
    ReportLine,
    ReportTotals,
    ScheduleEReport,
)

_ZERO = Decimal("0.00")
_YEAR = 2024

_money = st.decimals(
    min_value=Decimal("0.00"), max_value=Decimal("20000.00"), places=2
)
_configs = st.builds(
    ChecklistConfig,
    large_entry_amount=_money,
    capital_candidate_amount=_money,
    swing_percent=st.decimals(
        min_value=Decimal("0.1"), max_value=Decimal("500.0"), places=1
    ),
    swing_minimum_amount=_money,
    anchor_max_age_months=st.integers(1, 36),
    summary_year_count=st.integers(1, 20),
)


def _money_text(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def _percent_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _report(year: int, income: Decimal) -> ScheduleEReport:
    return ScheduleEReport(
        header=ReportHeader("p1", "P", "addr", None, year, 365, 0),
        lines=(ReportLine(3, "Rents received", "income", income),),
        other_items=(),
        totals=ReportTotals(income, _ZERO, income),
    )


def _txn(txn_id: str, amount: Decimal, category: str, itemized: bool) -> Transaction:
    return Transaction(
        id=txn_id,
        property_id="p1",
        date=f"{_YEAR}-03-01",
        amount=amount,
        type="expense",
        category_id=category,
        schedule_e_line=14,
        itemized=itemized,
        imported=False,
    )


def _snapshot(transactions, report, prior_report) -> YearSnapshot:
    return YearSnapshot(
        property_id="p1",
        tax_year=_YEAR,
        report=report,
        prior_report=prior_report,
        transactions=tuple(transactions),
        repairs=resolve_category_rows(transactions, "repairs"),
        assets_with_rows=0,
        loans=(),
        carryforward=None,
        status_tolerance=Decimal("2.00"),
        receipt_present={},
    )


# Feature: year-end-checklist, Property 2: Applied thresholds are echoed and interpolated
@settings(max_examples=200, deadline=None)
@given(config=_configs)
def test_thresholds_echoed_for_empty_snapshot(config: ChecklistConfig) -> None:
    """**Validates: Requirements 1.7, 3.4**"""
    result = build_checklist(
        _snapshot([], _report(_YEAR, _ZERO), _report(_YEAR - 1, _ZERO)), config
    )
    assert result.thresholds == config.applied()
    assert result.thresholds.large_entry_amount == config.large_entry_amount
    assert result.thresholds.capital_candidate_amount == config.capital_candidate_amount
    assert result.thresholds.swing_percent == config.swing_percent
    assert result.thresholds.swing_minimum_amount == config.swing_minimum_amount


# Feature: year-end-checklist, Property 2: Applied thresholds are echoed and interpolated
@settings(max_examples=200, deadline=None)
@given(config=_configs)
def test_threshold_reasons_contain_configured_values(config: ChecklistConfig) -> None:
    """**Validates: Requirements 1.7, 3.4**"""
    prior_income = Decimal("1000.00")
    swing_floor = (prior_income * config.swing_percent / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_UP
    )
    current_income = prior_income + max(config.swing_minimum_amount, swing_floor)
    transactions = [
        # A large, non-imported expense with no receipt on record.
        _txn("t1", max(config.large_entry_amount, Decimal("0.01")), "supplies", False),
        # An itemized Repairs entry at the capital-candidate threshold.
        _txn("t2", max(config.capital_candidate_amount, Decimal("0.01")), "repairs", True),
    ]
    result = build_checklist(
        _snapshot(
            transactions,
            _report(_YEAR, current_income),
            _report(_YEAR - 1, prior_income),
        ),
        config,
    )
    items = {item.id: item for item in result.items}
    assert result.thresholds == config.applied()

    receipts = items["receipts_missing"]
    assert receipts.status == "needs_attention"
    assert _money_text(config.large_entry_amount) in receipts.reason

    capital = items["repairs_capital_candidates"]
    assert capital.status == "needs_attention"
    assert _money_text(config.capital_candidate_amount) in capital.reason

    swings = items["yoy_swings"]
    assert swings.status == "needs_attention"
    assert _percent_text(config.swing_percent) + "%" in swings.reason
    assert _money_text(config.swing_minimum_amount) in swings.reason
