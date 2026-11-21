"""Property-based tests for interest override round trips (loan-balance-anchor).

* Property 15: Override set then clear is a round trip with a correct variance.
* Property 16 (task 3.11) is added to this module later; the shared moto
  fixture and helpers below are reusable for it.

**Validates: Requirements 6.6, 6.7, 6.8**
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import MAX_MONEY, MIN_ANCHOR_YEAR, LoanInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import LoanService

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-override-roundtrip-test"
PROPERTY_ID = "prop-1"

_TWO_DP = re.compile(r"^\d+\.\d{2}$")
_MAX_CENTS = int(MAX_MONEY * 100)
_MAX_EXAMPLES = 40


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


def _raw_items(ddb: Any, loan_id: str) -> list[dict[str, Any]]:
    """Raw stored items (loan + rollups) for one loan, sorted by key."""
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
    return sorted(items, key=lambda i: i["SK"]["S"])


def _without_updated_at(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        copy = dict(item)
        copy.pop("updatedAt", None)
        out.append(copy)
    return out


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


def _loan_input(
    balance_cents: int, rate: Decimal, extra_cents: int, anchor: date
) -> LoanInput:
    """A valid anchor-shape loan that pays off in well under 600 payments.

    The payment is the first month's interest (rounded up, plus a cent) plus
    at least ``balance / 500``, so it always exceeds first-month interest and
    principal alone retires the loan within about 500 payments.
    """
    balance = _money(balance_cents)
    interest = (balance * rate / Decimal(1200)).to_integral_value(
        rounding=ROUND_CEILING
    )
    interest_cents = int(interest * 100) + 1
    payment = _money(interest_cents + balance_cents // 500 + 1 + extra_cents)
    return LoanInput(
        property_id=PROPERTY_ID,
        description="Override roundtrip loan",
        annual_interest_rate=rate,
        monthly_payment=payment,
        anchor_balance=balance,
        anchor_date=anchor.isoformat(),
    )


def _create(service: LoanService, loan_input: LoanInput) -> str:
    # Keep the shared partition small: drop loans left by earlier examples.
    listed = service.list_loans(PROPERTY_ID)
    assert listed.error is None, listed.error
    for old in listed.value:
        assert service.delete_loan(PROPERTY_ID, old.id).error is None
    created = service.create_loan(loan_input)
    assert created.error is None, created.error
    return created.value.id


def _schedule(service: LoanService, loan_id: str):
    result = service.schedule_for(PROPERTY_ID, loan_id)
    assert result.error is None, result.error
    return result.value


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_loan_inputs = st.builds(
    _loan_input,
    st.integers(100_000, 100_000_000),
    st.integers(0, 150_000).map(lambda n: Decimal(n).scaleb(-4)),
    st.integers(0, 50_000),
    st.dates(date(2000, 1, 1), date(2040, 12, 31)),
)

_amounts = st.integers(0, _MAX_CENTS).map(_money)


# ---------------------------------------------------------------------------
# Property 15
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(data=st.data(), loan_input=_loan_inputs, amount=_amounts)
def test_override_set_then_clear_round_trips_with_correct_variance(
    env: tuple[LoanService, Any],
    data: st.DataObject,
    loan_input: LoanInput,
    amount: Decimal,
) -> None:
    """Property 15."""
    service, ddb = env
    loan_id = _create(service, loan_input)
    before_sched = _schedule(service, loan_id)
    generated = {y.tax_year: y for y in before_sched.yearly}
    anchor_year = int(loan_input.anchor_date[:4])

    # Any permitted year: a year with a row, or 1900 through the anchor year.
    year = data.draw(
        st.one_of(
            st.sampled_from(sorted(generated)),
            st.integers(MIN_ANCHOR_YEAR, anchor_year),
        )
    )
    has_payments = year in generated
    estimated = generated[year].estimated_interest if has_payments else Decimal("0.00")
    before_items = _raw_items(ddb, loan_id)

    set_result = service.set_interest_override(PROPERTY_ID, loan_id, year, amount)
    assert set_result.error is None, set_result.error

    expected_variance = amount - estimated
    row = next(y for y in _schedule(service, loan_id).yearly if y.tax_year == year)
    for view in (set_result.value, row):
        assert view.estimated_interest == estimated
        assert view.interest_override == amount
        assert view.variance == expected_variance
        assert view.variance.as_tuple().exponent == -2
        assert _TWO_DP.match(format(view.variance, "f").lstrip("-"))
        assert (view.variance < 0) == (amount < estimated)

    # An override-only year gains a stored rollup row while the override exists.
    if not has_payments:
        assert len(_raw_items(ddb, loan_id)) == len(before_items) + 1
        assert row.payments == 0
        assert row.ending_balance is None

    cleared = service.clear_interest_override(PROPERTY_ID, loan_id, year)
    assert cleared.error is None, cleared.error
    if has_payments:
        assert cleared.value is not None
        assert cleared.value.variance is None
        assert cleared.value.interest_override is None
        assert cleared.value.interest == estimated
    else:
        # The override-only row is removed, so the year has no view.
        assert cleared.value is None

    # Stored loan item and rollup rows are back to their prior state. The
    # ``updatedAt`` audit stamp is excluded: it moves on any write.
    assert _without_updated_at(_raw_items(ddb, loan_id)) == _without_updated_at(
        before_items
    )
    assert _schedule(service, loan_id) == before_sched


# ---------------------------------------------------------------------------
# Property 16
# ---------------------------------------------------------------------------

_invalid_amounts = st.one_of(
    # Negative amounts, as Decimal and as string.
    st.integers(1, _MAX_CENTS).map(lambda c: -_money(c)),
    st.integers(1, _MAX_CENTS).map(lambda c: str(-_money(c))),
    # More than two decimal places (non-zero third decimal).
    st.integers(0, 10**8).flatmap(
        lambda c: st.integers(1, 9).map(
            lambda d: Decimal(c * 10 + d).scaleb(-3)
        )
    ),
    # Above the maximum.
    st.integers(1, 10**6).map(lambda c: MAX_MONEY + _money(c)),
    # Not numeric or not finite.
    st.sampled_from(
        ["", "abc", "12abc", "1,000.00", "$5.00", "NaN", "Infinity", "-Infinity", "1e999x"]
    ),
    st.sampled_from([Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]),
)


def _stored_overrides(ddb: Any, loan_id: str) -> dict[str, str]:
    loan_sk = keys.loan_sk(loan_id)
    item = next(i for i in _raw_items(ddb, loan_id) if i["SK"]["S"] == loan_sk)
    raw = item.get("interestOverrides", {}).get("M", {})
    return {year: v["S"] for year, v in raw.items()}


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(
    data=st.data(),
    loan_input=_loan_inputs,
    bad_amount=_invalid_amounts,
    valid_amount=_amounts,
)
def test_invalid_overrides_rejected_and_storage_format_fixed(
    env: tuple[LoanService, Any],
    data: st.DataObject,
    loan_input: LoanInput,
    bad_amount: Decimal | str,
    valid_amount: Decimal,
) -> None:
    """Property 16."""
    service, ddb = env
    loan_id = _create(service, loan_input)
    generated = {y.tax_year for y in _schedule(service, loan_id).yearly}
    anchor_year = int(loan_input.anchor_date[:4])
    permitted_max = max(anchor_year, *generated)

    # Seed a prior override so "previously stored value unchanged" is checked.
    seed_year = anchor_year
    seeded = service.set_interest_override(
        PROPERTY_ID, loan_id, seed_year, valid_amount
    )
    assert seeded.error is None, seeded.error
    # Fixed storage format for any accepted override, including "0.00".
    stored = _stored_overrides(ddb, loan_id)
    assert stored == {str(seed_year): format(valid_amount, "f")}
    assert _TWO_DP.match(stored[str(seed_year)])

    before = _raw_items(ddb, loan_id)

    def assert_rejected(year: int, amount: Decimal | str) -> None:
        result = service.set_interest_override(PROPERTY_ID, loan_id, year, amount)
        assert result.error is not None
        assert result.error.kind == "validation"
        assert result.error.field == f"interest_overrides.{year}"
        assert _raw_items(ddb, loan_id) == before

    # Invalid amount, for a permitted year (the seeded one and a fresh one).
    permitted_year = data.draw(
        st.one_of(
            st.just(seed_year),
            st.sampled_from(sorted(generated)),
            st.integers(MIN_ANCHOR_YEAR, anchor_year),
        )
    )
    assert_rejected(permitted_year, bad_amount)

    # Invalid year (valid amount): before 1900 or beyond the permitted range.
    bad_year = data.draw(
        st.one_of(
            st.integers(0, MIN_ANCHOR_YEAR - 1),
            st.integers(permitted_max + 1, permitted_max + 500),
        )
    )
    assert_rejected(bad_year, valid_amount)
