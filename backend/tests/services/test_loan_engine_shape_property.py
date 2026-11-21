"""Property-based test for the loan engine's schedule shape.

Feature: loan-balance-anchor, Property 2: Schedule shape, dates,
termination, and determinism.

Dates are checked against an independent oracle built on ``calendar``.
Final-payment detection uses the exact ``Fraction`` interest oracle from the
Property 1 test.

**Validates: Requirements 2.1, 2.2, 2.5, 2.6, 2.7, 2.11, 2.12**
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from hypothesis import assume, given

from logstead.models.loan import MAX_PAYMENTS, Loan
from logstead.services.loan import compute_payment_rows
from tests.services.test_loan_engine_property import (
    _cents,
    _interest_cents,
    loans,
)


def _oracle_date(anchor: date, k: int) -> date:
    """``k`` calendar months after ``anchor``, clamped from the anchor day."""
    months = anchor.year * 12 + (anchor.month - 1) + k
    year, month = divmod(months, 12)
    month += 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


@given(loans())
def test_property_2_schedule_shape_dates_termination_determinism(loan: Loan) -> None:
    """Feature: loan-balance-anchor, Property 2: Schedule shape, dates, termination, and determinism.

    **Validates: Requirements 2.1, 2.2, 2.5, 2.6, 2.7, 2.11, 2.12**
    """
    anchor = date.fromisoformat(loan.anchor_date)
    # A valid Loan's payoff date is not before the next payment date
    # (Requirement 3.5); the shared generator can draw earlier ones.
    if loan.payoff_date is not None:
        assume(date.fromisoformat(loan.payoff_date) >= _oracle_date(anchor, 1))
    rows, payoff_balance = compute_payment_rows(loan)
    due = _cents(loan.monthly_payment) + _cents(loan.extra_principal)

    # 2.6: remaining payments are derived; the schedule is bounded.
    n = len(rows)
    assert 1 <= n <= MAX_PAYMENTS
    assert [r.number for r in rows] == list(range(1, n + 1))

    # 2.1 / 2.2: row k is exactly k months after the anchor, strictly later
    # than the anchor, and dates strictly ascend.
    prev_date = anchor
    for row in rows:
        expected = _oracle_date(anchor, row.number)
        assert row.date == expected.isoformat()
        current = date.fromisoformat(row.date)
        assert current > anchor
        assert current > prev_date
        prev_date = current

    # 2.5: only the last row can be the final payment.
    prev = _cents(loan.anchor_balance)
    for idx, row in enumerate(rows):
        interest = _interest_cents(prev, loan.annual_interest_rate)
        is_final = prev + interest <= due
        if idx < n - 1:
            assert not is_final
        elif loan.payoff_date is None:
            assert is_final
        # 2.12: a zero rate never accrues interest.
        if loan.annual_interest_rate == 0:
            assert row.interest == Decimal("0.00")
        prev = _cents(row.balance)

    # 2.7: without a payoff date the schedule fully amortizes, and the
    # projected payoff date is the last row's date.
    if loan.payoff_date is None:
        assert rows[-1].balance == Decimal("0.00")
        assert payoff_balance is None
        assert date.fromisoformat(rows[-1].date) == _oracle_date(anchor, n)
    else:
        payoff = date.fromisoformat(loan.payoff_date)
        assert date.fromisoformat(rows[-1].date) <= payoff
        if rows[-1].balance != 0:
            # The next row would have fallen after the payoff date.
            assert _oracle_date(anchor, n + 1) > payoff

    # 2.11: determinism.
    assert compute_payment_rows(loan) == (rows, payoff_balance)
