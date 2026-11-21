"""Property-based tests for interest overrides on anchor-shape loans.

* Property 14: An override replaces estimated interest for one year and
  nothing else (years before the anchor year included).

* Property 17: Updates retain exactly the overrides whose year is still
  permitted.

**Validates: Requirements 6.1, 6.2, 6.5, 6.9**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import MAX_MONEY, MIN_ANCHOR_YEAR, LoanInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import LoanService

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-override-test"
PROPERTY_ID = "prop-1"

_MAX_CENTS = int(MAX_MONEY * 100)
_MAX_EXAMPLES = 40
_ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Fixtures and helpers (shared with Property 17)
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


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


def _loan_input(
    balance_cents: int,
    rate: Decimal,
    payment_extra_cents: int,
    anchor: date,
    extra_principal_cents: int,
) -> LoanInput:
    """An anchor-shape input whose payment clears the first month's interest.

    The payment is at least the first month's interest plus one cent and at
    least ``balance / 300``, which keeps the schedule short of the 600-row cap
    for any rate.
    """
    balance = _money(balance_cents)
    interest_cents = int(
        (balance_cents * rate / Decimal(1200)).to_integral_value()
    )
    floor_cents = max(interest_cents + 2, -(-balance_cents // 300), 1)
    payment = _money(min(floor_cents + payment_extra_cents, _MAX_CENTS))
    return LoanInput(
        property_id=PROPERTY_ID,
        description="Override loan",
        annual_interest_rate=rate,
        monthly_payment=payment,
        anchor_balance=balance,
        anchor_date=anchor.isoformat(),
        extra_principal=_money(extra_principal_cents),
    )


def _create(service: LoanService, loan_input: LoanInput) -> str:
    # Keep the shared partition small: drop loans left by earlier examples.
    listed = service.list_loans(PROPERTY_ID)
    assert listed.error is None, listed.error
    for old in listed.value:
        assert service.delete_loan(PROPERTY_ID, old.id).error is None
    created = service.create_loan(loan_input)
    # Rare inputs can exceed the 600-row cap; those are not interesting here.
    assume(created.error is None)
    return created.value.id


def _schedule(service: LoanService, loan_id: str):
    result = service.schedule_for(PROPERTY_ID, loan_id)
    assert result.error is None, result.error
    return result.value


def _loan_view(service: LoanService, loan_id: str):
    result = service.get_loan(PROPERTY_ID, loan_id)
    assert result.error is None, result.error
    return result.value


def _stable_item(item: dict[str, Any]) -> dict[str, Any]:
    """A stored item without audit stamps and the override map."""
    copy = dict(item)
    copy.pop("updatedAt", None)
    copy.pop("interestOverrides", None)
    return copy


# ---------------------------------------------------------------------------
# Strategies (shared with Property 17)
# ---------------------------------------------------------------------------

_loan_inputs = st.builds(
    _loan_input,
    st.integers(100_000, 100_000_000),
    st.integers(0, 150_000).map(lambda n: Decimal(n).scaleb(-4)),
    st.integers(0, 200_000),
    st.dates(date(2000, 1, 1), date(2040, 12, 31)),
    st.one_of(st.just(0), st.integers(0, 100_000)),
)

_amounts = st.integers(0, _MAX_CENTS).map(_money)


# ---------------------------------------------------------------------------
# Property 14
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(
    data=st.data(),
    loan_input=_loan_inputs,
    first=_amounts,
    second=_amounts,
)
def test_override_replaces_estimated_interest_for_one_year_and_nothing_else(
    env: tuple[LoanService, Any],
    data: st.DataObject,
    loan_input: LoanInput,
    first: Decimal,
    second: Decimal,
) -> None:
    """Property 14: an override touches only its own year's interest."""
    service, ddb = env
    loan_id = _create(service, loan_input)
    before = _schedule(service, loan_id)
    before_loan = _loan_view(service, loan_id)
    before_items = _raw_items(ddb, loan_id)
    generated_years = {y.tax_year for y in before.yearly}
    anchor_year = int(loan_input.anchor_date[:4])

    # Years with payments, plus years before (and including) the anchor year
    # that have none, so override-only rows are exercised.
    year = data.draw(
        st.one_of(
            st.sampled_from(sorted(generated_years)),
            st.integers(max(MIN_ANCHOR_YEAR, anchor_year - 40), anchor_year),
            st.integers(MIN_ANCHOR_YEAR, anchor_year),
        )
    )
    was_generated = year in generated_years

    def check(expected: Decimal | None) -> None:
        after = _schedule(service, loan_id)

        # Payment rows, balances, and principal totals never change (6.5).
        assert after.payments == before.payments
        assert after.payoff_balance == before.payoff_balance
        loan_after = _loan_view(service, loan_id)
        expected_overrides = {} if expected is None else {str(year): expected}
        assert loan_after.interest_overrides == expected_overrides
        assert replace(
            loan_after, interest_overrides={}, updated_at=""
        ) == replace(before_loan, interest_overrides={}, updated_at="")

        before_by_year = {y.tax_year: y for y in before.yearly}
        after_by_year = {y.tax_year: y for y in after.yearly}
        override_only = not was_generated and expected is not None
        assert set(after_by_year) == generated_years | (
            {year} if override_only else set()
        )
        assert [y.tax_year for y in after.yearly] == sorted(after_by_year)

        # Every other year is identical (6.1).
        for y, view in before_by_year.items():
            if y != year:
                assert after_by_year[y] == view

        if expected is None:
            if was_generated:
                assert after_by_year[year] == before_by_year[year]
            return

        row = after_by_year[year]
        assert row.interest == expected
        assert row.interest_override == expected
        if was_generated:
            b = before_by_year[year]
            assert row.estimated_interest == b.estimated_interest
            assert row.payments == b.payments
            assert row.principal == b.principal
            assert row.total_paid == b.total_paid
            assert row.ending_balance == b.ending_balance
            assert row.variance == expected - b.estimated_interest
        else:
            # Override-only year (6.2): zero payments, no balance.
            assert row.payments == 0
            assert row.estimated_interest == _ZERO
            assert row.principal == _ZERO
            assert row.total_paid == _ZERO
            assert row.ending_balance is None
            assert row.variance == expected

        # Stored items for other years and the loan item (minus overrides)
        # are untouched by the write.
        old = {
            i["SK"]["S"]: _stable_item(i)
            for i in before_items
            if i.get("taxYear", {}).get("N") != str(year)
        }
        new = {
            i["SK"]["S"]: _stable_item(i)
            for i in _raw_items(ddb, loan_id)
            if i.get("taxYear", {}).get("N") != str(year)
        }
        assert new == old

    for amount in (first, second):
        assert (
            service.set_interest_override(PROPERTY_ID, loan_id, year, amount).error
            is None
        )
        check(amount)
    assert service.clear_interest_override(PROPERTY_ID, loan_id, year).error is None
    check(None)
    assert _schedule(service, loan_id) == before


# ---------------------------------------------------------------------------
# Property 17 goes below this line (task 3.9).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Property 17
# ---------------------------------------------------------------------------


def _with_payoff(loan_input: LoanInput, offset_days: int | None) -> LoanInput:
    """Optionally add a Payoff_Date safely after the next payment date."""
    if offset_days is None:
        return loan_input
    payoff = date.fromisoformat(loan_input.anchor_date) + timedelta(
        days=offset_days
    )
    return replace(loan_input, payoff_date=payoff.isoformat())


_payoff_offsets = st.one_of(st.none(), st.integers(40, 2_000))


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(
    data=st.data(),
    old_input=_loan_inputs,
    new_input=_loan_inputs,
    old_offset=_payoff_offsets,
    new_offset=_payoff_offsets,
    amounts=st.lists(_amounts, min_size=1, max_size=5),
)
def test_update_retains_exactly_the_overrides_whose_year_is_still_permitted(
    env: tuple[LoanService, Any],
    data: st.DataObject,
    old_input: LoanInput,
    new_input: LoanInput,
    old_offset: int | None,
    new_offset: int | None,
    amounts: list[Decimal],
) -> None:
    """Property 17: an update keeps overrides only for permitted years."""
    service, ddb = env
    old_input = _with_payoff(old_input, old_offset)
    new_input = _with_payoff(new_input, new_offset)
    loan_id = _create(service, old_input)

    old_schedule = _schedule(service, loan_id)
    old_anchor_year = int(old_input.anchor_date[:4])
    candidates = sorted(
        {y.tax_year for y in old_schedule.yearly}
        | set(range(max(MIN_ANCHOR_YEAR, old_anchor_year - 10), old_anchor_year + 1))
    )
    years = data.draw(
        st.lists(
            st.sampled_from(candidates),
            min_size=len(amounts),
            max_size=len(amounts),
            unique=True,
        )
        if len(candidates) >= len(amounts)
        else st.just(candidates)
    )
    overrides = dict(zip(years, amounts))
    for year, amount in overrides.items():
        assert (
            service.set_interest_override(PROPERTY_ID, loan_id, year, amount).error
            is None
        )

    updated = service.update_loan(PROPERTY_ID, loan_id, new_input)
    # Rare inputs exceed the 600-row cap or fail validation; not of interest.
    assume(updated.error is None)

    new_schedule = _schedule(service, loan_id)
    new_anchor_year = int(new_input.anchor_date[:4])
    generated = {int(p.date[:4]) for p in new_schedule.payments}
    expected = {
        y: a
        for y, a in overrides.items()
        if MIN_ANCHOR_YEAR <= y <= new_anchor_year or y in generated
    }
    dropped = set(overrides) - set(expected)

    loan_after = _loan_view(service, loan_id)
    assert loan_after.interest_overrides == {str(y): a for y, a in expected.items()}
    assert updated.value.interest_overrides == loan_after.interest_overrides

    rows = {y.tax_year: y for y in new_schedule.yearly}
    assert set(rows) == generated | set(expected)
    for year in expected:
        assert rows[year].interest_override == expected[year]
        if year not in generated:
            assert rows[year].payments == 0
    for year in dropped - generated:
        assert year not in rows

    stored_years = {
        int(i["taxYear"]["N"]) for i in _raw_items(ddb, loan_id) if "taxYear" in i
    }
    assert stored_years == generated | set(expected)
