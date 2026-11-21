"""Property-based test for informational loan fields.

Feature: loan-balance-anchor, Property 4: Informational fields never affect
results.

``original_principal`` and ``closing_date`` are stored and returned, but the
Payment_Rows, Yearly_Rollups, and Effective_Interest are identical whether
they are absent, present, or changed.

**Validates: Requirements 4.1, 4.3, 4.5**
"""

from __future__ import annotations

import calendar
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import MAX_MONEY, Loan, LoanInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import (
    LoanService,
    build_yearly_rollups,
    compute_payment_rows,
)
from tests.services.test_loan_engine_property import loans

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-informational-test"
PROPERTY_ID = "prop-1"

_MAX_CENTS = int(MAX_MONEY * 100)

_originals = st.one_of(
    st.none(),
    st.integers(1, _MAX_CENTS).map(lambda n: Decimal(n).scaleb(-2)),
)
_closings = st.one_of(
    st.none(),
    st.dates(date(1900, 1, 1), date(9999, 12, 31)).map(lambda d: d.isoformat()),
)


def _results(loan: Loan):
    rows, payoff_balance = compute_payment_rows(loan)
    rollups = build_yearly_rollups(loan, rows)
    effective = [(r.tax_year, r.effective_interest) for r in rollups]
    return rows, payoff_balance, rollups, effective


def _valid_payoff(loan: Loan) -> bool:
    """A valid Loan's payoff date is not before the next payment date."""
    if loan.payoff_date is None:
        return True
    anchor = date.fromisoformat(loan.anchor_date)
    months = anchor.year * 12 + anchor.month
    year, month = divmod(months, 12)
    month += 1
    first = date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))
    return date.fromisoformat(loan.payoff_date) >= first


@settings(max_examples=60, deadline=None)
@given(
    loans(),
    st.data(),
    _originals,
    _closings,
    _originals,
    _closings,
)
def test_property_4_engine_ignores_informational_fields(
    loan: Loan,
    data: st.DataObject,
    original_a: Decimal | None,
    closing_a: str | None,
    original_b: Decimal | None,
    closing_b: str | None,
) -> None:
    """Feature: loan-balance-anchor, Property 4: Informational fields never affect results.

    **Validates: Requirements 4.5**
    """
    assume(_valid_payoff(loan))
    base = replace(loan, original_principal=None, closing_date=None)
    rows, _ = compute_payment_rows(base)
    # Optionally add an override on a year with rows, to cover Effective_Interest.
    if data.draw(st.booleans()):
        year = int(rows[0].date[:4])
        amount = Decimal(data.draw(st.integers(0, 10_000_000))).scaleb(-2)
        base = replace(base, interest_overrides={year: amount})

    expected = _results(base)
    for original, closing in (
        (original_a, closing_a),
        (original_b, closing_b),
        (None, None),
    ):
        variant = replace(base, original_principal=original, closing_date=closing)
        assert _results(variant) == expected


@pytest.fixture(scope="module")
def service():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                        {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name in ("GSI1", "GSI2")
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield LoanService(DynamoRepository(ddb, TABLE_NAME))


def _input(loan: Loan, original: Decimal | None, closing: str | None) -> LoanInput:
    return LoanInput(
        property_id=PROPERTY_ID,
        description=loan.description,
        annual_interest_rate=loan.annual_interest_rate,
        monthly_payment=loan.monthly_payment,
        anchor_balance=loan.anchor_balance,
        anchor_date=loan.anchor_date,
        extra_principal=loan.extra_principal,
        payoff_date=loan.payoff_date,
        original_principal=original,
        closing_date=closing,
    )


def _create_and_read(service: LoanService, loan_input: LoanInput) -> tuple[Any, Any]:
    listed = service.list_loans(PROPERTY_ID)
    assert listed.error is None, listed.error
    for old in listed.value:
        assert service.delete_loan(PROPERTY_ID, old.id).error is None
    created = service.create_loan(loan_input)
    assert created.error is None, created.error
    schedule = service.schedule_for(PROPERTY_ID, created.value.id)
    assert schedule.error is None, schedule.error
    return created.value, schedule.value


@settings(max_examples=15, deadline=None)
@given(loans(), _originals, _closings, _originals, _closings)
def test_property_4_service_stores_and_ignores_informational_fields(
    service: LoanService,
    loan: Loan,
    original_a: Decimal | None,
    closing_a: str | None,
    original_b: Decimal | None,
    closing_b: str | None,
) -> None:
    """Feature: loan-balance-anchor, Property 4: Informational fields never affect results.

    **Validates: Requirements 4.1, 4.3, 4.5**
    """
    assume(_valid_payoff(loan))
    plain_view, plain_sched = _create_and_read(service, _input(loan, None, None))
    for original, closing in ((original_a, closing_a), (original_b, closing_b)):
        view, sched = _create_and_read(service, _input(loan, original, closing))

        # 4.1 / 4.3: stored and returned.
        assert view.original_principal == original
        assert view.closing_date == closing
        if original is not None:
            assert view.original_principal.as_tuple().exponent == -2

        # 4.5: derived results are identical to the loan without them.
        assert sched.payments == plain_sched.payments
        assert sched.yearly == plain_sched.yearly
        assert view.remaining_payments == plain_view.remaining_payments
        assert view.next_payment_date == plain_view.next_payment_date
        assert view.projected_payoff_date == plain_view.projected_payoff_date
        assert view.payoff_balance == plain_view.payoff_balance
        assert view.status == plain_view.status
