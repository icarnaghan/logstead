"""Property-based test for the pure loan engine's row arithmetic.

Feature: loan-balance-anchor, Property 1: Row arithmetic and balance
recurrence.

The oracle is independent of the code under test: it uses
``fractions.Fraction`` for exact rational arithmetic (no ``Decimal``
context, no ``to_money``).

**Validates: Requirements 2.3, 2.4, 2.8, 2.10, 2.13, 3.1**
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

from hypothesis import assume, given
from hypothesis import strategies as st

from logstead.models.loan import MAX_MONEY, Loan
from logstead.services.loan import ScheduleError, compute_payment_rows

_ZERO = Decimal("0.00")
_MAX_CENTS = int(MAX_MONEY * 100)


# ---------------------------------------------------------------------------
# Exact oracle
# ---------------------------------------------------------------------------


def _interest_cents(balance_cents: int, rate: Decimal) -> int:
    """Half-up cents of ``balance * rate / 1200`` using exact Fractions."""
    exact = Fraction(balance_cents, 100) * Fraction(rate) / 1200 * 100
    return (exact + Fraction(1, 2)).__floor__()


def _cents(d: Decimal) -> int:
    return int(d.scaleb(2))


def _is_2dp(d: object) -> bool:
    return isinstance(d, Decimal) and d.as_tuple().exponent == -2


def _dec(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

_balances = st.one_of(
    st.sampled_from([1, 100, 10_000_000, 25_000_000, _MAX_CENTS]),
    st.integers(min_value=1, max_value=100_000_000),
    st.integers(min_value=1, max_value=_MAX_CENTS),
)

_rates = st.one_of(
    st.sampled_from(
        [Decimal("0"), Decimal("6.875"), Decimal("3"), Decimal("100"), Decimal("0.0001")]
    ),
    st.integers(min_value=0, max_value=1_000_000).map(lambda n: Decimal(n).scaleb(-4)),
    st.integers(min_value=0, max_value=1500).map(lambda n: Decimal(n).scaleb(-2)),
)


@st.composite
def _anchor_dates(draw) -> date:
    if draw(st.booleans()):
        year = draw(st.integers(1900, 2060))
        month = draw(st.integers(1, 12))
        last = calendar.monthrange(year, month)[1]
        return date(year, month, draw(st.integers(min(28, last), last)))
    return draw(st.dates(min_value=date(1900, 1, 1), max_value=date(2060, 12, 31)))


@st.composite
def loans(draw) -> Loan:
    balance = draw(_balances)
    rate = draw(_rates)
    first_interest = _interest_cents(balance, rate)

    # payment = first-month interest + a positive surplus, biased so most
    # schedules finish within 600 rows (the rest are filtered below).
    surplus = draw(
        st.one_of(
            st.just(1),
            st.integers(1, max(1, balance // 400)),
            st.integers(1, max(1, balance)),
        )
    )
    payment = first_interest + surplus
    assume(payment <= _MAX_CENTS)

    extra = draw(st.one_of(st.just(0), st.integers(0, 2_000_00)))
    assume(extra <= _MAX_CENTS)

    anchor = draw(_anchor_dates())
    payoff = None
    if draw(st.booleans()):
        payoff = (anchor + timedelta(days=draw(st.integers(0, 600 * 31)))).isoformat()

    loan = Loan(
        id="loan-1",
        property_id="prop-1",
        description="Test loan",
        annual_interest_rate=rate,
        monthly_payment=_dec(payment),
        anchor_balance=_dec(balance),
        anchor_date=anchor.isoformat(),
        extra_principal=_dec(extra),
        payoff_date=payoff,
        original_principal=None,
        closing_date=None,
        include_in_report=True,
        interest_overrides={},
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    try:
        compute_payment_rows(loan)
    except ScheduleError:
        assume(False)  # more than 600 rows, or past year 9999
    return loan


# ---------------------------------------------------------------------------
# Property 1
# ---------------------------------------------------------------------------


@given(loans())
def test_property_1_row_arithmetic_and_balance_recurrence(loan: Loan) -> None:
    """Feature: loan-balance-anchor, Property 1: Row arithmetic and balance recurrence.

    **Validates: Requirements 2.3, 2.4, 2.8, 2.10, 2.13, 3.1**
    """
    rows, _ = compute_payment_rows(loan)
    due = _cents(loan.monthly_payment) + _cents(loan.extra_principal)
    prev = _cents(loan.anchor_balance)

    for idx, row in enumerate(rows):
        # 2.13: exactly two-decimal Decimals, never floats.
        for v in (row.payment, row.interest, row.principal, row.balance):
            assert _is_2dp(v)

        interest = _cents(row.interest)
        principal = _cents(row.principal)
        payment = _cents(row.payment)
        balance = _cents(row.balance)

        # 2.3: interest from the balance before the payment.
        assert interest == _interest_cents(prev, loan.annual_interest_rate)
        # 2.8: row arithmetic and balance recurrence.
        assert interest + principal == payment
        assert balance == prev - principal
        # 2.10: strictly decreasing, never below zero.
        assert 0 <= balance < prev

        is_final = prev + interest <= due
        if is_final:
            # Final_Payment sweeps the balance and ends the schedule.
            assert principal == prev
            assert balance == 0
            assert idx == len(rows) - 1
        else:
            # 2.4 / 3.1: payment plus extra principal minus interest.
            assert principal == due - interest
            assert principal >= 1
            assert payment == due
            assert balance > 0
        prev = balance
