"""Loan interest confirmed property (Requirement 8)."""
from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.checklist import LoanFact, _rule_loan_interest_confirmed
from logstead.services.checklist_config import CHECKLIST_CONFIG

_ZERO = Decimal("0.00")


def _window_start(year: int, months: int) -> date:
    """Independent oracle: N months before Dec 31, day clamped to month length."""
    index = year * 12 + 11 - months  # zero-based month index of the target
    y, m = divmod(index, 12)
    m += 1
    return date(y, m, min(31, calendar.monthrange(y, m)[1]))


def _in_window(anchor: date, year: int, months: int) -> bool:
    return _window_start(year, months) <= anchor <= date(year, 12, 31)


def _snapshot(year, source, loans):
    report = SimpleNamespace(line12=SimpleNamespace(source=source))
    return SimpleNamespace(
        property_id="p1", tax_year=year, report=report, loans=tuple(loans)
    )


_dates = st.dates(min_value=date(1995, 1, 1), max_value=date(2040, 12, 31))


@st.composite
def _loan(draw, index=0):
    return LoanFact(
        loan_id=f"loan-{index}",
        description=f"Loan {index}",
        anchor_date=draw(_dates).isoformat(),
        include_in_report=draw(st.booleans()),
        interest=draw(
            st.one_of(
                st.just(_ZERO),
                st.decimals(Decimal("0.01"), Decimal("50000.00"), places=2),
            )
        ),
        has_override=draw(st.booleans()),
    )


@st.composite
def _loans(draw):
    n = draw(st.integers(0, 6))
    return [draw(_loan(index=i)) for i in range(n)]


# Feature: year-end-checklist, Property 8: Loan interest confirmed
# **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8**
@settings(max_examples=300, deadline=None)
@given(
    year=st.integers(1996, 2038),
    months=st.integers(1, 36),
    source=st.sampled_from(["loan-generated", "transaction-entered"]),
    loans=_loans(),
)
def test_loan_interest_confirmed(year, months, source, loans):
    config = replace(CHECKLIST_CONFIG, anchor_max_age_months=months)
    item = _rule_loan_interest_confirmed(_snapshot(year, source, loans), config)
    if source != "loan-generated":
        assert item.status == "not_applicable"
        return
    evaluated = [l for l in loans if l.include_in_report and l.interest > _ZERO]
    confirmed = [
        l.has_override
        or _in_window(date.fromisoformat(l.anchor_date), year, months)
        for l in evaluated
    ]
    assert [r["loan_id"] for r in item.details["loans"]] == [
        l.loan_id for l in evaluated
    ]
    assert [r["confirmed"] for r in item.details["loans"]] == confirmed
    for row, l in zip(item.details["loans"], evaluated):
        assert row["name"] == l.description
        assert row["anchor_date"] == l.anchor_date
        assert Decimal(str(row["interest"])) == l.interest
    unconfirmed = confirmed.count(False)
    if unconfirmed == 0:
        assert item.status == "done"
    else:
        assert item.status == "needs_attention"
        assert str(unconfirmed) in item.reason
    assert item.link.endswith("loans")


# Feature: year-end-checklist, Property 8: Loan interest confirmed (boundary)
# **Validates: Requirements 8.4, 8.5, 8.6**
@settings(max_examples=200, deadline=None)
@given(year=st.integers(1996, 2038), months=st.integers(1, 36))
def test_anchor_window_boundaries(year, months):
    config = replace(CHECKLIST_CONFIG, anchor_max_age_months=months)
    start = _window_start(year, months)
    end = date(year, 12, 31)

    def status(anchor: date) -> str:
        loan = LoanFact("a", "A", anchor.isoformat(), True, Decimal("10.00"), False)
        return _rule_loan_interest_confirmed(
            _snapshot(year, "loan-generated", [loan]), config
        ).status

    assert status(start) == "done"
    assert status(end) == "done"
    assert status(start - timedelta(days=1)) == "needs_attention"
    assert status(end + timedelta(days=1)) == "needs_attention"


def test_leap_year_month_end_clamping():
    # Ten months before Dec 31 lands in February; day 31 clamps to its length.
    assert _window_start(2023, 10) == date(2023, 2, 28)
    assert _window_start(2024, 10) == date(2024, 2, 29)
