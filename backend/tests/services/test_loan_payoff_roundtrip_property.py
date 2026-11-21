"""Property-based test for the payoff date set and clear round trip.

* Property 12: Payoff set and clear is a round trip.

**Validates: Requirements 3.9**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import LoanService

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-payoff-roundtrip-test"
PROPERTY_ID = "prop-1"
_MAX_EXAMPLES = 40


@pytest.fixture(scope="module")
def env():
    """A moto table and a service: ``(service, ddb)``."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
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
        yield LoanService(DynamoRepository(ddb, TABLE_NAME)), ddb


def _rollup_items(ddb: Any, loan_id: str) -> list[dict[str, Any]]:
    """Raw stored yearly rollup rows (not the loan item), sorted by key."""
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "TableName": TABLE_NAME,
        "ConsistentRead": True,
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk)",
        "ExpressionAttributeValues": {
            ":pk": {"S": keys.property_scoped_pk(PROPERTY_ID)},
            ":sk": {"S": keys.loan_sk(loan_id)},
        },
    }
    while True:
        page = ddb.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    rollups = [i for i in items if "taxYear" in i]
    return sorted(rollups, key=lambda i: i["SK"]["S"])


def _cents(value: int) -> Decimal:
    return Decimal(value).scaleb(-2).quantize(Decimal("0.01"))


@st.composite
def _loan_inputs(draw: st.DrawFn) -> LoanInput:
    balance_cents = draw(st.integers(10_000, 100_000_000))
    rate = Decimal(draw(st.integers(0, 150_000))).scaleb(-4)
    interest_cents = int(
        (Decimal(balance_cents) * rate / Decimal(1200)).to_integral_value()
    )
    # Payment covers first-month interest plus at least balance/300 of
    # principal. Principal only grows from there, so the loan pays off in at
    # most 300 payments and stays under the 600-row cap; every drawn loan is
    # valid.
    floor = interest_cents + balance_cents // 300 + 1
    payment_cents = draw(st.integers(floor, floor + 200_000))
    return LoanInput(
        property_id=PROPERTY_ID,
        description="Payoff loan",
        annual_interest_rate=rate,
        monthly_payment=_cents(payment_cents),
        anchor_balance=_cents(balance_cents),
        anchor_date=draw(st.dates(date(2000, 1, 1), date(2030, 12, 31))).isoformat(),
        extra_principal=_cents(draw(st.integers(0, 50_000))),
    )


def _strip(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        copy = dict(item)
        copy.pop("updatedAt", None)
        out.append(copy)
    return out


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(data=st.data(), loan_input=_loan_inputs())
def test_payoff_set_and_clear_is_a_round_trip(
    env: tuple[LoanService, Any],
    data: st.DataObject,
    loan_input: LoanInput,
) -> None:
    """Property 12."""
    service, ddb = env
    listed = service.list_loans(PROPERTY_ID)
    assert listed.error is None, listed.error
    for old in listed.value:
        assert service.delete_loan(PROPERTY_ID, old.id).error is None

    created = service.create_loan(loan_input)
    assert created.error is None, created.error
    loan_id = created.value.id
    before = _strip(_rollup_items(ddb, loan_id))
    assert before

    schedule = service.schedule_for(PROPERTY_ID, loan_id)
    assert schedule.error is None, schedule.error
    payment_dates = [p.date for p in schedule.value.payments]
    # A payoff date anywhere from the next payment date to just past the end.
    payoff = data.draw(st.sampled_from(payment_dates))
    payoff_year = int(payoff[:4])

    with_payoff = service.update_loan(
        PROPERTY_ID, loan_id, replace(loan_input, payoff_date=payoff)
    )
    assert with_payoff.error is None, with_payoff.error
    during = _rollup_items(ddb, loan_id)
    assert during
    assert all(int(i["taxYear"]["N"]) <= payoff_year for i in during)

    cleared = service.update_loan(
        PROPERTY_ID, loan_id, replace(loan_input, payoff_date=None)
    )
    assert cleared.error is None, cleared.error
    assert _strip(_rollup_items(ddb, loan_id)) == before
