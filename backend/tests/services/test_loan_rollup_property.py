"""Property-based test for yearly rollups, anchor year, and override-only rows.

Feature: loan-balance-anchor, Property 8: Yearly rollup consistency, anchor
year, and override-only rows.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 6.2**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from logstead.models.loan import MIN_ANCHOR_YEAR, Loan
from logstead.services.loan import (
    build_yearly_rollups,
    compute_payment_rows,
    override_year_allowed,
)

from tests.services.test_loan_engine_property import _cents, loans


@st.composite
def loans_with_overrides(draw) -> Loan:
    loan = draw(loans())
    rows, _ = compute_payment_rows(loan)
    generated = {int(r.date[:4]) for r in rows}
    anchor_year = int(loan.anchor_date[:4])

    candidates = st.one_of(
        st.integers(MIN_ANCHOR_YEAR, anchor_year),
        st.sampled_from(sorted(generated)) if generated else st.nothing(),
        st.integers(MIN_ANCHOR_YEAR, 9999),  # filtered to permitted years
    )
    years = draw(st.lists(candidates, max_size=8, unique=True))
    years = [y for y in years if override_year_allowed(y, anchor_year, generated)]
    amounts = draw(
        st.lists(
            st.integers(0, 99_999_999_99).map(lambda c: Decimal(c).scaleb(-2)),
            min_size=len(years),
            max_size=len(years),
        )
    )
    return replace(loan, interest_overrides=dict(zip(years, amounts)))


@given(loans_with_overrides())
def test_property_8_rollup_consistency_anchor_year_override_only(loan: Loan) -> None:
    """Feature: loan-balance-anchor, Property 8: Yearly rollup consistency,
    anchor year, and override-only rows.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 6.2**
    """
    rows, _ = compute_payment_rows(loan)
    rollups = build_yearly_rollups(loan, rows)
    anchor = date.fromisoformat(loan.anchor_date)

    by_year: dict[int, list] = {}
    for row in rows:
        by_year.setdefault(int(row.date[:4]), []).append(row)

    # 5.1: rollup years = row years united with override years (one each).
    years = [r.tax_year for r in rollups]
    assert len(years) == len(set(years))
    assert set(years) == set(by_year) | set(loan.interest_overrides)

    for r in rollups:
        assert r.loan_id == loan.id
        if r.tax_year in by_year:
            year_rows = by_year[r.tax_year]
            # 5.2: no generated rollup before the anchor year.
            assert r.tax_year >= anchor.year
            # 5.3: anchor-year rollup holds only rows dated after the anchor.
            assert all(date.fromisoformat(x.date) > anchor for x in year_rows)
            # 5.4: exact sums, no proration; ending balance of last row.
            assert r.payments == len(year_rows)
            assert _cents(r.interest) == sum(_cents(x.interest) for x in year_rows)
            assert _cents(r.principal) == sum(_cents(x.principal) for x in year_rows)
            assert _cents(r.total_paid) == sum(_cents(x.payment) for x in year_rows)
            assert r.ending_balance == year_rows[-1].balance
            assert r.interest_override == loan.interest_overrides.get(r.tax_year)
        else:
            # 5.5 / 6.2: override-only rollup.
            override = loan.interest_overrides[r.tax_year]
            assert r.payments == 0
            assert r.interest == Decimal("0.00")
            assert r.principal == Decimal("0.00")
            assert r.total_paid == Decimal("0.00")
            assert r.ending_balance is None
            assert r.interest_override == override
            assert r.effective_interest == override
