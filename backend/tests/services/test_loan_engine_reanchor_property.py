"""Property-based test for re-anchoring consistency.

Feature: loan-balance-anchor, Property 7: Re-anchoring consistency.

Re-anchoring a loan on the date and balance of any non-final row must
reproduce every later row. Dates are compared only when the original
anchor day is 28 or less (a clamped month-end day cannot be recovered
from a re-anchor on the clamped date).

**Validates: Requirements 2.1, 2.16**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from fractions import Fraction

from hypothesis import assume, given
from hypothesis import strategies as st

from logstead.models.loan import MAX_MONEY, Loan
from logstead.services.loan import ScheduleError, compute_payment_rows

_MAX_CENTS = int(MAX_MONEY * 100)


def _interest_cents(balance_cents: int, rate: Decimal) -> int:
    exact = Fraction(balance_cents, 100) * Fraction(rate) / 1200 * 100
    return (exact + Fraction(1, 2)).__floor__()


def _dec(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2)


_balances = st.one_of(
    st.integers(min_value=1, max_value=100_000_000),
    st.integers(min_value=1, max_value=_MAX_CENTS),
)

_rates = st.one_of(
    st.sampled_from([Decimal("0"), Decimal("6.875"), Decimal("3"), Decimal("0.0001")]),
    st.integers(min_value=0, max_value=1500).map(lambda n: Decimal(n).scaleb(-2)),
)


@st.composite
def loans_and_row_index(draw) -> tuple[Loan, int]:
    balance = draw(_balances)
    rate = draw(_rates)
    first_interest = _interest_cents(balance, rate)
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

    anchor = draw(st.dates(min_value=date(1900, 1, 1), max_value=date(2060, 12, 31)))
    loan = Loan(
        id="loan-1",
        property_id="prop-1",
        description="Test loan",
        annual_interest_rate=rate,
        monthly_payment=_dec(payment),
        anchor_balance=_dec(balance),
        anchor_date=anchor.isoformat(),
        extra_principal=_dec(extra),
        payoff_date=None,
        original_principal=None,
        closing_date=None,
        include_in_report=True,
        interest_overrides={},
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )
    try:
        rows, _ = compute_payment_rows(loan)
    except ScheduleError:
        assume(False)
    assume(len(rows) >= 2)
    k = draw(st.integers(min_value=0, max_value=len(rows) - 2))  # non-final row
    return loan, k


@given(loans_and_row_index())
def test_property_7_reanchoring_consistency(case: tuple[Loan, int]) -> None:
    """Feature: loan-balance-anchor, Property 7: Re-anchoring consistency.

    **Validates: Requirements 2.1, 2.16**
    """
    loan, k = case
    rows, _ = compute_payment_rows(loan)
    anchor_row = rows[k]

    reanchored = replace(
        loan,
        anchor_date=anchor_row.date,
        anchor_balance=anchor_row.balance,
    )
    new_rows, _ = compute_payment_rows(reanchored)
    expected = rows[k + 1 :]

    assert len(new_rows) == len(expected)
    compare_dates = date.fromisoformat(loan.anchor_date).day <= 28
    for new, old in zip(new_rows, expected):
        assert new.payment == old.payment
        assert new.interest == old.interest
        assert new.principal == old.principal
        assert new.balance == old.balance
        if compare_dates:
            assert new.date == old.date
