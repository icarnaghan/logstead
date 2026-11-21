"""Property-based test: extra principal never slows or costs a loan more.

Feature: loan-balance-anchor, Property 5: Extra principal never makes a
loan slower or costlier.

**Validates: Requirements 3.8**
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from logstead.models.loan import MAX_MONEY, Loan
from logstead.services.loan import ScheduleError, compute_payment_rows

from .test_loan_engine_property import loans

_MAX_CENTS = int(MAX_MONEY * 100)


@given(
    loans(),
    st.one_of(
        st.just(0),
        st.integers(1, 100),
        st.integers(1, 5_000_00),
        st.integers(1, _MAX_CENTS),
    ),
)
def test_property_5_extra_principal_never_slower_or_costlier(
    generated: Loan, extra_cents: int
) -> None:
    """Feature: loan-balance-anchor, Property 5: Extra principal never makes a loan slower or costlier.

    **Validates: Requirements 3.8**
    """
    # Compare full schedules (no payoff-date truncation) so the zero-extra
    # baseline and the extra schedule both run to completion.
    base = replace(generated, extra_principal=Decimal("0.00"), payoff_date=None)
    extra = replace(
        base, extra_principal=Decimal(extra_cents).scaleb(-2)
    )

    try:
        base_rows, _ = compute_payment_rows(base)
    except ScheduleError:
        assume(False)  # baseline exceeds 600 rows / year 9999
    # With more money per month, the extra schedule can only be shorter, so
    # it never raises ScheduleError when the baseline succeeds.
    extra_rows, _ = compute_payment_rows(extra)

    # No more rows than the baseline.
    assert len(extra_rows) <= len(base_rows)

    # No greater total interest.
    assert sum(r.interest for r in extra_rows) <= sum(r.interest for r in base_rows)

    # Balance after row k is never above the baseline's, for every shared k.
    for k in range(min(len(extra_rows), len(base_rows))):
        assert extra_rows[k].balance <= base_rows[k].balance
