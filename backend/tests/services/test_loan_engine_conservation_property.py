"""Property-based test for principal conservation in the loan engine.

Feature: loan-balance-anchor, Property 3: Principal conservation.

The oracle works in integer cents, independent of the code under test.

**Validates: Requirements 2.9, 3.4, 3.6**
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given

from logstead.models.loan import Loan
from logstead.services.loan import compute_payment_rows

from .test_loan_engine_property import loans


def _cents(d: Decimal) -> int:
    return int(d.scaleb(2))


@given(loans())
def test_property_3_principal_conservation(loan: Loan) -> None:
    """Feature: loan-balance-anchor, Property 3: Principal conservation.

    **Validates: Requirements 2.9, 3.4, 3.6**
    """
    rows, payoff_balance = compute_payment_rows(loan)
    anchor = _cents(loan.anchor_balance)
    principal_sum = sum(_cents(r.principal) for r in rows)
    payoff_cents = 0 if payoff_balance is None else _cents(payoff_balance)

    # Sum of principal plus payoff balance equals the anchor balance exactly.
    assert principal_sum + payoff_cents == anchor

    last_balance = _cents(rows[-1].balance) if rows else anchor

    if loan.payoff_date is None:
        # No payoff date: the loan fully amortizes and no payoff balance exists.
        assert payoff_balance is None
        assert rows and last_balance == 0
    elif payoff_balance is None:
        # Payoff date did not leave a balance: amortized on or before it.
        assert last_balance == 0
    else:
        # Payoff balance is reported only when positive, and equals the
        # balance of the last row on or before the payoff date.
        assert payoff_balance > 0
        assert last_balance == payoff_cents
        if rows:
            assert date.fromisoformat(rows[-1].date) <= date.fromisoformat(
                loan.payoff_date
            )
        else:
            # No payment fell on or before the payoff date.
            assert payoff_cents == anchor
