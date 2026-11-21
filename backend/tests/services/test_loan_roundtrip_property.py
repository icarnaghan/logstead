"""Property-based tests for Loan serialization round trips (design Property 10).

* The API JSON shape (``LoanView`` through the router's ``_to_jsonable`` and
  ``json``) parses back, via the router's body mapper and the shared
  validator, into a Loan equal in every field (anchor shape and informational
  fields), including the exact rate; creating from that JSON and reading the
  loan back reproduces the same JSON.
* ``loan_to_item`` / ``rollup_to_item`` written through the moto-backed
  repository and read back with the strict readers is the identity.
* Money in the JSON and in the stored item is a two-decimal string; the rate
  is a plain decimal string.
* A rate sent as a JSON float is rejected on ``annual_interest_rate``.

**Validates: Requirements 4.1, 4.3, 8.3, 8.4, 8.9, 12.1**
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.loan import MAX_MONEY, Loan, YearlyRollup
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _loan_input, _to_jsonable
from logstead.services.loan import (
    LoanService,
    compute_payment_rows,
    payment_date,
    _loan_from_item,
    _rollup_from_item,
    loan_to_item,
    monthly_interest,
    rollup_to_item,
    validate_loan_fields,
)
from logstead.util.money import money_to_str

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-roundtrip-test"

_TWO_DP = re.compile(r"^\d+\.\d{2}$")
_PLAIN_DECIMAL = re.compile(r"^\d+(\.\d+)?$")
_MAX_CENTS = int(MAX_MONEY * 100)
_MAX_EXAMPLES = 60

_LOAN_MONEY_FIELDS = (
    "monthly_payment",
    "anchor_balance",
    "original_principal",
    "extra_principal",
)
_LOAN_ITEM_MONEY = (
    "monthlyPayment",
    "anchorBalance",
    "originalPrincipal",
    "extraPrincipal",
)
_ROLLUP_ITEM_MONEY = (
    "interest",
    "principal",
    "totalPaid",
    "endingBalance",
    "interestOverride",
    "effectiveInterest",
)
_WRITE_MONEY = set(_LOAN_ITEM_MONEY) | set(_ROLLUP_ITEM_MONEY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env():
    """A moto table and a service: ``(service, repo)``."""
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
        repo = DynamoRepository(ddb, TABLE_NAME)
        yield LoanService(repo), repo


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


def _canonical_rate(units: int) -> Decimal:
    """A rate in ten-thousandths, canonicalised like the validator does."""
    return Decimal(format(Decimal(units).scaleb(-4).normalize(), "f"))


_cents = st.integers(0, _MAX_CENTS).map(_money)
_positive_cents = st.integers(1, _MAX_CENTS).map(_money)
_iso_ts = st.datetimes(
    datetime(2000, 1, 1), datetime(2100, 1, 1), timezones=st.just(timezone.utc)
).map(lambda d: d.replace(microsecond=0).isoformat())
_description = st.text(
    st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=200
).filter(lambda s: s == s.strip() and s != "")
_overrides = st.dictionaries(st.integers(1900, 9999), _cents, max_size=5)
_ids = st.uuids().map(lambda u: u.hex)


@st.composite
def _loans(draw: st.DrawFn) -> Loan:
    """An anchor-shape Loan that passes ``validate_loan_fields``."""
    balance = draw(_positive_cents)
    rate = _canonical_rate(draw(st.integers(0, 1_000_000)))
    # Payment = first-month interest + at least balance/550, so the schedule
    # needs well under 600 rows; the cents above that floor are random.
    floor_cents = (
        int(monthly_interest(balance, rate) * 100)
        + int(balance * 100) // 550
        + 1
    )
    payment_cents = draw(
        st.integers(floor_cents, min(_MAX_CENTS, floor_cents + 50_000_000))
    )
    anchor = draw(st.dates(date(1900, 1, 1), date(2100, 12, 31)))
    payoff = (
        (
            payment_date(anchor, 1) + timedelta(days=draw(st.integers(0, 20000)))
        ).isoformat()
        if draw(st.booleans())
        else None
    )
    closing = (
        (anchor - timedelta(days=draw(st.integers(-400, 4000)))).isoformat()
        if draw(st.booleans())
        else None
    )
    return Loan(
        id=draw(_ids),
        property_id=draw(_ids),
        description=draw(_description),
        annual_interest_rate=rate,
        monthly_payment=_money(payment_cents),
        anchor_balance=balance,
        anchor_date=anchor.isoformat(),
        extra_principal=draw(_cents),
        payoff_date=payoff,
        original_principal=draw(st.none() | _positive_cents),
        closing_date=closing,
        include_in_report=draw(st.booleans()),
        interest_overrides=draw(_overrides),
        created_at=draw(_iso_ts),
        updated_at=draw(_iso_ts),
    )


@st.composite
def _rollups(draw: st.DrawFn) -> YearlyRollup:
    return YearlyRollup(
        loan_id=draw(_ids),
        property_id=draw(_ids),
        tax_year=draw(st.integers(1900, 9999)),
        payments=draw(st.integers(0, 12)),
        interest=draw(_cents),
        principal=draw(_cents),
        total_paid=draw(_cents),
        ending_balance=draw(st.none() | _cents),
        interest_override=draw(st.none() | _cents),
        include_in_report=draw(st.booleans()),
    )


# ---------------------------------------------------------------------------
# Property 10: API JSON shape
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(loan=_loans())
def test_loan_json_round_trips_and_formats_values(
    env: tuple[LoanService, DynamoRepository], loan: Loan
) -> None:
    """Loan -> API JSON -> LoanInput -> validated Loan fields is the identity."""
    service, _ = env
    view = service._view(loan)
    wire = json.loads(json.dumps(_to_jsonable(view)))

    # Formats: money is a two-decimal string; the rate a plain decimal string.
    for name in _LOAN_MONEY_FIELDS + ("payoff_balance",):
        value = wire[name]
        assert value is None or (isinstance(value, str) and _TWO_DP.match(value))
    for name in ("monthly_payment", "anchor_balance"):
        assert wire[name] is not None
    rate_text = wire["annual_interest_rate"]
    assert isinstance(rate_text, str) and _PLAIN_DECIMAL.match(rate_text)
    assert rate_text == format(loan.annual_interest_rate, "f")
    assert set(wire["interest_overrides"]) == {str(y) for y in loan.interest_overrides}
    for year, amount in loan.interest_overrides.items():
        assert wire["interest_overrides"][str(year)] == money_to_str(amount)

    # Derived values come from the engine.
    rows, _ = compute_payment_rows(loan)
    assert wire["remaining_payments"] == len(rows)
    assert wire["next_payment_date"] == payment_date(
        date.fromisoformat(loan.anchor_date), 1
    ).isoformat()

    # Parse the JSON back through the router mapper and the shared validator.
    parsed = _loan_input(wire, loan.property_id)
    assert parsed.is_ok, parsed.error
    validated = validate_loan_fields(parsed.value)
    assert validated.is_ok, validated.error
    v = validated.value
    assert v.property_id == loan.property_id
    assert v.description == loan.description
    assert v.annual_interest_rate == loan.annual_interest_rate
    assert str(v.annual_interest_rate) == rate_text
    assert v.monthly_payment == loan.monthly_payment
    assert v.anchor_balance == loan.anchor_balance
    assert v.anchor_date == loan.anchor_date
    assert v.extra_principal == loan.extra_principal
    assert v.payoff_date == loan.payoff_date
    assert v.original_principal == loan.original_principal
    assert v.closing_date == loan.closing_date
    assert v.include_in_report == loan.include_in_report


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(loan=_loans())
def test_create_from_json_reproduces_the_same_json(
    env: tuple[LoanService, DynamoRepository], loan: Loan
) -> None:
    """JSON -> create_loan -> get_loan -> JSON is the identity (ids/times aside)."""
    service, _ = env
    base = replace(loan, interest_overrides={})
    wire = json.loads(json.dumps(_to_jsonable(service._view(base))))

    parsed = _loan_input(wire, base.property_id)
    assert parsed.is_ok, parsed.error
    created = service.create_loan(parsed.value)
    assert created.is_ok, created.error
    fetched = service.get_loan(base.property_id, created.value.id)
    assert fetched.is_ok, fetched.error
    again = json.loads(json.dumps(_to_jsonable(fetched.value)))

    for volatile in ("id", "created_at", "updated_at"):
        wire.pop(volatile)
        again.pop(volatile)
    assert again == wire


# ---------------------------------------------------------------------------
# Property 10: item builders through the repository
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(loan=_loans())
def test_loan_item_round_trips_through_repository(
    env: tuple[LoanService, DynamoRepository], loan: Loan
) -> None:
    """loan_to_item -> stored -> _loan_from_item is the identity."""
    _, repo = env
    repo.transact_write([{"put": loan_to_item(loan)}], money_attrs=_WRITE_MONEY)
    stored = repo.get_item(
        keys.property_scoped_pk(loan.property_id),
        keys.loan_sk(loan.id),
        money_attrs=set(),
    )
    assert stored is not None

    for name in _LOAN_ITEM_MONEY:
        value = stored.get(name)
        assert value is None or (isinstance(value, str) and _TWO_DP.match(value))
    assert stored["annualInterestRate"] == format(loan.annual_interest_rate, "f")
    assert _PLAIN_DECIMAL.match(stored["annualInterestRate"])
    for amount in (stored.get("interestOverrides") or {}).values():
        assert isinstance(amount, str) and _TWO_DP.match(amount)

    restored = _loan_from_item(stored)
    assert restored == loan
    assert str(restored.annual_interest_rate) == str(loan.annual_interest_rate)
    assert str(restored.original_principal) == str(loan.original_principal)
    assert loan_to_item(restored) == loan_to_item(loan)


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(rollup=_rollups())
def test_rollup_item_round_trips_through_repository(
    env: tuple[LoanService, DynamoRepository], rollup: YearlyRollup
) -> None:
    """rollup_to_item -> stored -> _rollup_from_item is the identity."""
    _, repo = env
    repo.transact_write([{"put": rollup_to_item(rollup)}], money_attrs=_WRITE_MONEY)
    stored = repo.get_item(
        keys.property_scoped_pk(rollup.property_id),
        keys.loan_year_sk(rollup.loan_id, rollup.tax_year),
        money_attrs=set(),
    )
    assert stored is not None

    for name in _ROLLUP_ITEM_MONEY:
        value = stored.get(name)
        assert value is None or (isinstance(value, str) and _TWO_DP.match(value))
    assert ("endingBalance" in stored) == (rollup.ending_balance is not None)
    assert stored["effectiveInterest"] == money_to_str(rollup.effective_interest)

    restored = _rollup_from_item(stored)
    assert restored == rollup
    assert restored.effective_interest == rollup.effective_interest


# ---------------------------------------------------------------------------
# Property 10: JSON float rates are rejected
# ---------------------------------------------------------------------------


@settings(deadline=None, max_examples=_MAX_EXAMPLES)
@given(
    value=st.floats(allow_nan=False, allow_infinity=False),
    field=st.sampled_from(
        ["annual_interest_rate", "monthly_payment", "anchor_balance"]
    ),
)
def test_json_float_decimal_is_rejected(value: float, field: str) -> None:
    body = json.loads(
        '{"description": "x", "annual_interest_rate": "6.5", '
        '"monthly_payment": "1500.00", "anchor_balance": "100000.00", '
        '"anchor_date": "2024-01-01"}'
    )
    body[field] = value
    parsed = _loan_input(body, "prop-1")
    assert not parsed.is_ok
    assert parsed.error.kind == "validation"
    assert parsed.error.field == field


def test_json_string_rate_is_accepted() -> None:
    body = {
        "description": "x",
        "annual_interest_rate": "6.5",
        "monthly_payment": "1500.00",
        "anchor_balance": "100000.00",
        "anchor_date": "2024-01-01",
    }
    parsed = _loan_input(body, "prop-1")
    assert parsed.is_ok
    assert parsed.value.annual_interest_rate == Decimal("6.5")
    assert parsed.value.anchor_balance == Decimal("100000.00")
