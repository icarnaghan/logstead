"""Task 5.2 / Property 8: serialized GET figures are two-decimal money strings,
``fully_allowed`` is a boolean, and the Expected_Carryforward depends only on
the nets + opening balance + user-entered allowed data (no §469 logic).

Design Property 8 — *Every figure is a two-decimal money string; the flag is a
boolean* (Requirements 1.6, 3.5, 3.6, 9.4, 9.5): in the serialized
``GET /carryforward`` body, ``schedule_e_net``, ``expected_carryforward``,
every non-null ``reported_carryforward``, and ``allowed_loss`` match
``^-?\\d+\\.\\d{2}$``; ``fully_allowed`` is a JSON boolean; ``tax_year`` is an
integer; ``status`` is a known literal — and the Expected_Carryforward depends
ONLY on the nets, the opening balance, and the user-entered allowed data (no
IRC §469 allowance/phase-out term enters).

This drives the **real HTTP handler** over ``moto``, mirroring the harness in
``test_carryforward_route.py``: a moto-backed single-table DynamoDB (base +
GSI1 + GSI2) plus an S3 bucket are wired via ``handler_module.configure(...)``,
properties/transactions are seeded through the public ``POST`` endpoints, the
opening balance and per-year allowed data are set via the public
``PUT /carryforward/...`` endpoints, and the serialized ``GET /carryforward``
body is parsed back from JSON.

To drive VALID allowed data the test must know each loss year's magnitude, so it
GETs once to read the nets, PUTs allowed amounts within ``[0, loss_magnitude]``
(and ``fully_allowed`` on some loss years), then GETs again and asserts against
the second body.

The §469-independence check (Req 9.5) re-derives the Expected_Carryforward
series from the response's OWN ``schedule_e_net`` / ``allowed_loss`` /
``fully_allowed`` plus the opening balance, using the documented running-balance
recurrence (``suspended = max(-net - (fully? -net : allowed), 0)``; a gain →
``max(prior - net, 0)``), and asserts it matches the returned
``expected_carryforward`` to the cent — proving no hidden §469 allowance or
phase-out term influences the series.

Each Hypothesis example provisions its own moto resources and runs the full
HTTP path (heavy), so the deadline is disabled and the example count is held at
50.
"""

from __future__ import annotations

import contextlib
import json
import re
from decimal import Decimal

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-carryforward-money"
REGION = "us-east-1"
USER = "user-carryforward-money"

#: Two-decimal money string, e.g. "0.00", "5000.00", "-5000.00" (Req 1.6, 3.5).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")

#: A small spread of distinct, non-contiguous tax years the generated
#: transactions are dated within, so the series spans several Data_Years.
_TAX_YEARS = [2020, 2022, 2023, 2025]


# --- moto wiring -------------------------------------------------------------


@contextlib.contextmanager
def _wired_handler():
    """Provision isolated moto resources and wire the real handler.

    Yields nothing; within the context the module-level ``handler`` routes
    against a freshly created moto DynamoDB (base + GSI1 + GSI2) and S3 bucket,
    composed exactly as production via ``handler_module.configure(repo, files)``.
    Wiring is reset on exit so examples never leak state into one another.
    """
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
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)
        s3_files = S3FileAdapter(s3, BUCKET)
        handler_module.configure(repo=repo, files=s3_files)
        try:
            yield
        finally:
            handler_module.reset_wiring()


# --- event / request helpers (mirrors test_carryforward_route.py) ------------


def _claims(sub: str) -> dict:
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _event(
    method: str,
    path: str,
    *,
    sub: str | None = None,
    body: dict | None = None,
):
    """An API Gateway HTTP API v2 proxy event with an optional identity."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": _claims(sub)}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _create_property(sub: str, name: str, address: str) -> str:
    resp = handler(
        _event("POST", "/properties", sub=sub)
        | {"body": json.dumps({"name": name, "address_text": address})}
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["id"]


def _create_transaction(sub: str, property_id: str, body: dict) -> None:
    resp = handler(
        _event("POST", f"/properties/{property_id}/transactions", sub=sub)
        | {"body": json.dumps(body)}
    )
    assert resp["statusCode"] == 201, resp["body"]


def _get_carryforward(sub: str) -> dict:
    resp = handler(_event("GET", "/carryforward", sub=sub))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


# --- strategies --------------------------------------------------------------
#
# A deliberate mix of income and expense lines across the non-contiguous tax
# years produces varied per-year nets (loss and gain years), exercising both
# arms of the running-balance recurrence. Amounts stay modest so the generated
# loss magnitudes are small, which keeps the allowed-amount draws (in
# [0, magnitude]) cheap and varied.

_amounts = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("20000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

_INCOME_SPECS = [("income", "rents-received"), ("income", "royalties-received")]
_EXPENSE_SPECS = [("expense", "repairs"), ("expense", "utilities")]

_opening_amounts = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("20000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, int]:
    """One (type, category_id, amount, tax_year) transaction spec."""
    ttype, category = draw(st.sampled_from(_INCOME_SPECS + _EXPENSE_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    return ttype, category, amount, year


_property_txns = st.lists(_txn(), min_size=0, max_size=8)


def _iso_date(year: int, index: int) -> str:
    """A deterministic valid in-year ISO date, cycling month/day."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _expected_recurrence(
    years: list[dict], opening: Decimal
) -> dict[int, Decimal]:
    """Re-derive the Expected_Carryforward series from the response's own data.

    Uses ONLY each year's returned ``schedule_e_net`` / ``allowed_loss`` /
    ``fully_allowed`` plus the opening balance, via the documented recurrence:
    a loss adds ``max(-net - effective_allowed, 0)`` (where
    ``effective_allowed`` is ``-net`` when fully allowed, else the stored
    allowed amount); a gain is absorbed, floored at ``0.00``. No §469 term. The
    returned ``years`` are ascending.
    """
    balance = opening
    out: dict[int, Decimal] = {}
    for y in years:
        net = Decimal(y["schedule_e_net"])
        if net < 0:
            loss_magnitude = -net
            if y["fully_allowed"]:
                effective_allowed = loss_magnitude
            else:
                effective_allowed = Decimal(y["allowed_loss"])
            suspended = max(loss_magnitude - effective_allowed, Decimal("0.00"))
            balance = balance + suspended
        else:
            balance = max(balance - net, Decimal("0.00"))
        out[int(y["tax_year"])] = balance
    return out


# Feature: carryforward-allowed-loss, Property 8: Every figure is a two-decimal
# money string; the flag is a boolean
@settings(deadline=None, max_examples=50)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    opening=_opening_amounts,
    allowed_fraction=st.lists(
        st.floats(min_value=0.0, max_value=1.0), min_size=0, max_size=8
    ),
    fully_flags=st.lists(st.booleans(), min_size=0, max_size=8),
    reported_choices=st.lists(st.booleans(), min_size=0, max_size=8),
)
def test_serialized_figures_are_money_strings_and_section_469_independent(
    properties_txns: list[list[tuple[str, str, Decimal, int]]],
    opening: Decimal,
    allowed_fraction: list[float],
    fully_flags: list[bool],
    reported_choices: list[bool],
) -> None:
    """GET body figures are two-decimal money strings + a boolean flag, and the
    expected series is §469-independent (depends only on nets + opening +
    allowed data).

    Validates: Requirements 1.6, 3.5, 3.6, 9.4, 9.5
    """
    with _wired_handler():
        # Seed properties + transactions through the public POST endpoints.
        for p_index, txns in enumerate(properties_txns):
            pid = _create_property(
                USER, f"Prop{p_index}", f"{p_index} Main St"
            )
            for t_index, (ttype, category, amount, year) in enumerate(txns):
                _create_transaction(
                    USER,
                    pid,
                    {
                        "date": _iso_date(year, t_index),
                        "amount": f"{amount:.2f}",
                        "type": ttype,
                        "category_id": category,
                    },
                )

        # Set the opening balance through the public PUT endpoint.
        resp = handler(
            _event(
                "PUT",
                "/carryforward/opening-balance",
                sub=USER,
                body={"amount": f"{opening:.2f}"},
            )
        )
        assert resp["statusCode"] == 200, resp["body"]

        # GET once to read each year's net so we know each loss year's magnitude
        # (allowed amounts must be within [0, magnitude] to be VALID).
        first = _get_carryforward(USER)

        loss_years = [
            y for y in first["years"] if Decimal(y["schedule_e_net"]) < 0
        ]

        # Set VALID per-year allowed data on the loss years: mark some fully
        # allowed, give the rest a partial amount within [0, magnitude], and set
        # a reported value on some so non-null reported figures are exercised.
        for i, y in enumerate(loss_years):
            tax_year = int(y["tax_year"])
            magnitude = -Decimal(y["schedule_e_net"])

            fully = fully_flags[i] if i < len(fully_flags) else False
            if fully:
                put = handler(
                    _event(
                        "PUT",
                        f"/carryforward/years/{tax_year}",
                        sub=USER,
                        body={"fully_allowed": True},
                    )
                )
                assert put["statusCode"] == 200, put["body"]
            else:
                frac = allowed_fraction[i] if i < len(allowed_fraction) else 0.0
                # A valid allowed amount in [0, magnitude], quantized to cents.
                allowed = (magnitude * Decimal(str(frac))).quantize(
                    Decimal("0.01")
                )
                if allowed > magnitude:
                    allowed = magnitude
                if allowed < 0:
                    allowed = Decimal("0.00")
                put = handler(
                    _event(
                        "PUT",
                        f"/carryforward/years/{tax_year}",
                        sub=USER,
                        body={"allowed_loss": f"{allowed:.2f}"},
                    )
                )
                assert put["statusCode"] == 200, put["body"]

            # Record a reported value on some years so non-null
            # reported_carryforward figures are covered by the regex check.
            if i < len(reported_choices) and reported_choices[i]:
                rep = handler(
                    _event(
                        "PUT",
                        f"/carryforward/years/{tax_year}",
                        sub=USER,
                        body={"amount": "0.00"},
                    )
                )
                assert rep["statusCode"] == 200, rep["body"]

        # GET again and assert against the serialized body.
        body = _get_carryforward(USER)

        # Opening balance is a two-decimal money string.
        assert isinstance(body["opening_balance"], str)
        assert _MONEY_RE.match(body["opening_balance"]), body["opening_balance"]
        assert isinstance(body["has_data"], bool)
        assert isinstance(body["years"], list)

        tax_years = [int(y["tax_year"]) for y in body["years"]]
        assert tax_years == sorted(tax_years), "years must be ascending"

        for y in body["years"]:
            # tax_year is an int; status is a known literal.
            assert isinstance(y["tax_year"], int)
            assert y["status"] in {"ok", "mismatch", "carried", "unreported"}

            # schedule_e_net / expected_carryforward / allowed_loss are
            # two-decimal money strings.
            for field in (
                "schedule_e_net",
                "expected_carry_in",
                "expected_carryforward",
                "allowed_loss",
            ):
                value = y[field]
                assert isinstance(value, str), (field, value)
                assert _MONEY_RE.match(value), (field, value)

            # expected and allowed are non-negative; net may be negative.
            assert Decimal(y["expected_carry_in"]) >= 0, y["expected_carry_in"]
            assert Decimal(y["expected_carryforward"]) >= 0, y["expected_carryforward"]
            assert Decimal(y["allowed_loss"]) >= 0, y["allowed_loss"]

            # reported_carryforward is a two-decimal money string or null; when
            # present it is a non-negative magnitude.
            reported = y["reported_carryforward"]
            if reported is not None:
                assert isinstance(reported, str), reported
                assert _MONEY_RE.match(reported), reported
                assert Decimal(reported) >= 0, reported

            # fully_allowed is a JSON boolean (Python bool after json.loads).
            assert isinstance(y["fully_allowed"], bool), y["fully_allowed"]

        # §469 INDEPENDENCE (Req 9.5): the expected series is fully explained by
        # the nets + opening balance + the user-entered allowed data alone. Any
        # hidden §469 allowance/phase-out term would make this re-derivation
        # diverge from the returned expected_carryforward.
        oracle = _expected_recurrence(body["years"], Decimal(body["opening_balance"]))

        # Carry-in semantics: each year's expected_carry_in is the previous
        # year's expected carry-out (the opening balance for the first year),
        # and the summary's next-year fields follow the last year.
        carry_in = Decimal(body["opening_balance"])
        for y in body["years"]:
            assert Decimal(y["expected_carry_in"]) == carry_in, (y["tax_year"], carry_in)
            carry_in = Decimal(y["expected_carryforward"])
        next_year = body["next_year"]
        if body["years"]:
            assert type(next_year) is int
            assert next_year == int(body["years"][-1]["tax_year"]) + 1
        else:
            assert next_year is None
        assert isinstance(body["next_year_expected_carry_in"], str)
        assert _MONEY_RE.match(body["next_year_expected_carry_in"])
        assert isinstance(body["status_tolerance"], str)
        assert re.match(r"^\d+\.\d{2}$", body["status_tolerance"]), body["status_tolerance"]
        assert Decimal(body["next_year_expected_carry_in"]) == carry_in

        for y in body["years"]:
            tax_year = int(y["tax_year"])
            assert Decimal(y["expected_carryforward"]) == oracle[tax_year], (
                tax_year,
                y["schedule_e_net"],
                y["allowed_loss"],
                y["fully_allowed"],
                y["expected_carryforward"],
                oracle[tax_year],
            )
