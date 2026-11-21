"""Property-based test for payoff-date truncation in the loan engine.

Feature: loan-balance-anchor, Property 6: Payoff date truncates the schedule
to a prefix.

**Validates: Requirements 3.3, 3.7**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from hypothesis import assume, given
from hypothesis import strategies as st

from logstead.models.loan import Loan
from logstead.services.loan import ScheduleError, compute_payment_rows, payment_date

from tests.services.test_loan_engine_property import loans


@st.composite
def _loan_and_payoff(draw) -> tuple[Loan, Loan, date]:
    """A loan without a payoff date, plus a valid Payoff_Date for it."""
    base = replace(draw(loans()), payoff_date=None)
    try:
        rows, _ = compute_payment_rows(base)
    except ScheduleError:
        assume(False)  # the uncut schedule needs more than 600 rows
    next_date = payment_date(date.fromisoformat(base.anchor_date), 1)
    # From the next payment date to well past the last payment.
    offset = draw(st.integers(0, (len(rows) + 2) * 31))
    payoff = next_date + timedelta(days=offset)
    return base, replace(base, payoff_date=payoff.isoformat()), payoff


@given(_loan_and_payoff())
def test_property_6_payoff_date_truncates_schedule_to_prefix(
    case: tuple[Loan, Loan, date],
) -> None:
    """Feature: loan-balance-anchor, Property 6: Payoff date truncates the schedule to a prefix.

    **Validates: Requirements 3.3, 3.7**
    """
    base, with_payoff, payoff = case
    full_rows, full_payoff_balance = compute_payment_rows(base)
    cut_rows, _ = compute_payment_rows(with_payoff)

    expected = [r for r in full_rows if date.fromisoformat(r.date) <= payoff]

    # 3.7: exactly the leading rows of the uncut schedule dated on or before
    # the payoff date (same values, same numbering).
    assert cut_rows == expected
    assert cut_rows == full_rows[: len(cut_rows)]
    # 3.3: no row after the payoff date.
    assert all(date.fromisoformat(r.date) <= payoff for r in cut_rows)
    # The uncut schedule never reports a payoff balance.
    assert full_payoff_balance is None
