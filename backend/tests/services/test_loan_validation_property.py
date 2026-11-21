"""Property-based test for loan validation (design Property 9).

Property 9: Validation rejects every invalid field and writes nothing.

Each field has a strategy producing a value that violates exactly that
field's rules. A random non-empty subset of fields is made invalid; create
and update must fail with a ``validation`` error naming exactly that subset,
and the (moto) table must be unchanged afterwards. The same cases run through
the service layer and through the real router (POST and PUT, HTTP 400).

Two projection-derived rejections are covered separately: a loan needing more
than 600 payments fails on ``monthly_payment``, and a schedule whose payments
would pass year 9999 fails on ``anchor_date``.

The oracle for "first month's interest" is independent of the code under
test (``fractions.Fraction``).

**Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.14, 2.15, 3.2,
3.5, 4.2, 4.4, 8.8**
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.loan import MAX_MONEY, LoanInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.loan import LoanService

REGION = "us-east-1"
TABLE_NAME = "logstead-loan-validation-test"
USER_SUB = "user-validation-1"

_MAX_CENTS = int(MAX_MONEY * 100)
_RUNS = settings(deadline=None, max_examples=40)

FIELDS = (
    "description",
    "annual_interest_rate",
    "monthly_payment",
    "anchor_balance",
    "anchor_date",
    "extra_principal",
    "payoff_date",
    "original_principal",
    "closing_date",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _scan_all(ddb: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"TableName": TABLE_NAME, "ConsistentRead": True}
    while True:
        page = ddb.scan(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return sorted(items, key=lambda i: (i["PK"]["S"], i["SK"]["S"]))


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": USER_SUB}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    return handler(event)


class Env:
    def __init__(self, service: LoanService, ddb: Any, pid: str, loan_id: str):
        self.service = service
        self.ddb = ddb
        self.pid = pid
        self.loan_id = loan_id


def _valid_input(pid: str) -> LoanInput:
    return LoanInput(
        property_id=pid,
        description="Seed loan",
        annual_interest_rate=Decimal("6.5"),
        monthly_payment=Decimal("1500.00"),
        anchor_balance=Decimal("200000.00"),
        anchor_date="2024-02-29",
        extra_principal=Decimal("0.00"),
        original_principal=Decimal("250000.00"),
        closing_date="2020-01-15",
    )


@pytest.fixture(scope="module")
def env():
    """A moto table, an owned property, and one seeded valid loan."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": a, "AttributeType": "S"}
                for a in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="logstead-files-validation")
        repo = DynamoRepository(ddb, TABLE_NAME)
        handler_module.configure(
            repo=repo, files=S3FileAdapter(s3, "logstead-files-validation")
        )
        resp = _call("POST", "/properties", {"name": "Maple", "address_text": "1 Maple"})
        assert resp["statusCode"] == 201, resp["body"]
        pid = json.loads(resp["body"])["id"]
        service = LoanService(repo)
        created = service.create_loan(_valid_input(pid))
        assert created.error is None
        yield Env(service, ddb, pid, created.value.id)
    handler_module.reset_wiring()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _money(cents: int) -> Decimal:
    return Decimal(cents).scaleb(-2).quantize(Decimal("0.01"))


def _first_interest_cents(balance: Decimal, rate: Decimal) -> int:
    """Exact first-month interest in cents, half-up (independent oracle)."""
    x = Fraction(balance) * Fraction(rate) / 1200 * 100
    return (x + Fraction(1, 2)).__floor__()


_valid_balance = st.integers(1, _MAX_CENTS).map(_money)
_valid_rate = st.integers(0, 1_000_000).map(lambda n: Decimal(n).scaleb(-4))
_valid_anchor = st.one_of(
    st.dates(date(1900, 1, 1), date(2100, 12, 31)),
    st.builds(
        date,
        st.integers(1900, 2100),
        st.sampled_from([1, 3, 5, 7, 8, 10, 12]),
        st.sampled_from([28, 29, 30, 31]),
    ),
)
_valid_desc = st.text(
    st.characters(blacklist_categories=("Cs", "Zs", "Cc")), min_size=1, max_size=200
)

_BAD_FORMATS = [
    "2020-1-05",
    "20200105",
    "2020/01/05",
    "2020-01-05 ",
    " 2020-01-05",
    "2020-01-05\n",
    "2021-02-29",
    "2020-13-01",
    "2020-00-10",
    "2020-01-32",
    "abcd-ef-gh",
    "\uff12\uff10\uff12\uff10-01-05",
]

_bad_desc = st.one_of(
    st.none(),
    st.just(""),
    st.integers(1, 20).map(lambda n: " " * n),
    st.integers(201, 400).map(lambda n: "a" * n),
)

_NONFINITE = [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]

_bad_money_values = st.one_of(
    st.integers(1, 10**11).map(lambda n: -_money(n)),
    st.integers(1, 10**6).map(lambda n: MAX_MONEY + _money(n)),
    st.integers(1, 10**9)
    .filter(lambda n: n % 10 != 0)
    .map(lambda n: Decimal(n).scaleb(-3)),
    st.sampled_from(_NONFINITE),
)
# Positive-only fields also reject zero; required fields also reject absence.
_bad_positive_money = st.one_of(st.just(Decimal("0.00")), _bad_money_values)
_bad_required_money = st.one_of(_bad_positive_money, st.none())

_bad_rate = st.one_of(
    st.integers(1, 10**6).map(lambda n: -Decimal(n).scaleb(-4)),
    st.integers(1_000_001, 10**9).map(lambda n: Decimal(n).scaleb(-4)),
    st.integers(1, 10**8)
    .filter(lambda n: n % 10 != 0)
    .map(lambda n: Decimal(n).scaleb(-5)),
    st.sampled_from(_NONFINITE),
    st.none(),
)

_bad_anchor = st.one_of(
    st.sampled_from(["", "1899-12-31", "0001-01-01"] + _BAD_FORMATS), st.none()
)
# "" is "absent" at the router for optional dates, so exclude it there.
_bad_optional_date = st.sampled_from(_BAD_FORMATS)


@st.composite
def _case(draw: st.DrawFn) -> tuple[dict[str, Any], frozenset[str]]:
    """Return ``(field values, invalid subset)``; values use ``None`` for absent."""
    subset = frozenset(
        draw(st.sets(st.sampled_from(FIELDS), min_size=1, max_size=len(FIELDS)))
    )

    # Valid base values.
    balance = draw(_valid_balance)
    rate = draw(_valid_rate)
    anchor = draw(_valid_anchor)
    interest_cents = _first_interest_cents(balance, rate)
    payment = _money(draw(st.integers(interest_cents + 1, _MAX_CENTS)))
    extra: Decimal | None = draw(st.one_of(st.none(), st.integers(0, 10**6).map(_money)))
    original: Decimal | None = draw(
        st.one_of(st.none(), st.integers(1, _MAX_CENTS).map(_money))
    )
    closing: str | None = draw(
        st.one_of(
            st.none(), st.dates(date(1800, 1, 1), date(2100, 12, 31)).map(str)
        )
    )
    payoff: str | None = draw(
        st.one_of(
            st.none(),
            st.integers(31, 4000).map(lambda n: (anchor + timedelta(days=n)).isoformat()),
        )
    )
    description: str | None = draw(_valid_desc)
    anchor_str: str | None = anchor.isoformat()
    rate_out: Decimal | None = rate
    balance_out: Decimal | None = balance

    # Invalidate the chosen subset.
    if "description" in subset:
        description = draw(_bad_desc)
    if "annual_interest_rate" in subset:
        rate_out = draw(_bad_rate)
    if "anchor_balance" in subset:
        balance_out = draw(_bad_required_money)
    if "anchor_date" in subset:
        anchor_str = draw(_bad_anchor)
    if "monthly_payment" in subset:
        kinds = ["format"]
        # "At or below the first month's interest" is only measurable (and the
        # only error) when the balance and rate are valid.
        if (
            "anchor_balance" not in subset
            and "annual_interest_rate" not in subset
            and interest_cents >= 1
        ):
            kinds.append("low")
        if draw(st.sampled_from(kinds)) == "low":
            payment_out: Decimal | None = _money(draw(st.integers(1, interest_cents)))
        else:
            payment_out = draw(_bad_required_money)
    else:
        payment_out = payment
    if "extra_principal" in subset:
        extra = draw(_bad_money_values)
    if "original_principal" in subset:
        original = draw(_bad_positive_money)
    if "closing_date" in subset:
        closing = draw(_bad_optional_date)
    if "payoff_date" in subset:
        options = [_bad_optional_date]
        # A well-formed payoff before the next payment is only the sole error
        # when the anchor date is valid (otherwise the relation is not checked).
        if "anchor_date" not in subset:
            options.append(
                st.one_of(
                    st.integers(0, 4000).map(
                        lambda n: (anchor - timedelta(days=n)).isoformat()
                    ),
                    st.integers(1, 27).map(
                        lambda n: (anchor + timedelta(days=n)).isoformat()
                    ),
                )
            )
        payoff = draw(st.one_of(options))

    values = {
        "description": description,
        "annual_interest_rate": rate_out,
        "monthly_payment": payment_out,
        "anchor_balance": balance_out,
        "anchor_date": anchor_str,
        "extra_principal": extra,
        "payoff_date": payoff,
        "original_principal": original,
        "closing_date": closing,
        "include_in_report": draw(st.booleans()),
    }
    return values, subset


@st.composite
def _cap_case(draw: st.DrawFn) -> dict[str, Any]:
    """Every field valid, but the loan would need 601 or more payments."""
    anchor = draw(st.dates(date(1900, 1, 1), date(2100, 12, 31)))
    if draw(st.booleans()):
        # Zero rate: B = 600 payments plus 1..payment cents => exactly 601 rows.
        rate = Decimal("0")
        p = draw(st.integers(1, 10**6))
        balance_cents = p * 600 + draw(st.integers(1, p))
        payment_cents = p
    else:
        # Payment barely above interest: principal per month starts at 0.01 and
        # cannot clear a $100k+ balance in 600 months at a rate of at most 10%.
        rate = Decimal(draw(st.integers(10_000, 100_000))).scaleb(-4)
        balance_cents = draw(st.integers(10_000_000, _MAX_CENTS))
        payment_cents = _first_interest_cents(_money(balance_cents), rate) + 1
    return {
        "description": "Cap loan",
        "annual_interest_rate": rate,
        "monthly_payment": _money(payment_cents),
        "anchor_balance": _money(balance_cents),
        "anchor_date": anchor.isoformat(),
        "extra_principal": None,
        "payoff_date": None,
        "original_principal": None,
        "closing_date": None,
        "include_in_report": True,
    }


@st.composite
def _year_9999_case(draw: st.DrawFn) -> dict[str, Any]:
    """Every field valid, but the last payment would be dated after 9999-12-31."""
    anchor = draw(st.dates(date(9960, 1, 1), date(9999, 12, 31)))
    # Payments that still fall in year 9999 (dated up to 9999-12-<day>).
    in_range = (9999 - anchor.year) * 12 + (12 - anchor.month)
    p = draw(st.integers(1, 10**6))
    return {
        "description": "Far future loan",
        "annual_interest_rate": Decimal("0"),
        "monthly_payment": _money(p),
        # Exactly in_range + 1 payments at zero rate: the last one passes 9999.
        "anchor_balance": _money(p * (in_range + 1)),
        "anchor_date": anchor.isoformat(),
        "extra_principal": None,
        "payoff_date": None,
        "original_principal": None,
        "closing_date": None,
        "include_in_report": True,
    }


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------


def _loan_input(pid: str, values: dict[str, Any]) -> LoanInput:
    return LoanInput(property_id=pid, **values)


def _body(values: dict[str, Any]) -> dict[str, Any]:
    """JSON body: decimals as strings (never floats), absent values omitted."""
    body: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        body[key] = format(value, "f") if isinstance(value, Decimal) and value.is_finite() else (
            str(value) if isinstance(value, Decimal) else value
        )
    return body


def _check_service_error(result: Any, expected: frozenset[str], values: Any) -> None:
    assert result.error is not None, values
    assert result.error.kind == "validation"
    named = {field for field, _ in result.error.errors}
    assert named == expected, (named, expected, values)
    assert result.error.field == result.error.errors[0][0]
    assert all(message for _, message in result.error.errors)


def _check_router_error(resp: dict[str, Any], expected: frozenset[str], values: Any) -> None:
    assert resp["statusCode"] == 400, (resp["body"], values)
    body = json.loads(resp["body"])
    assert body["error"] == "validation"
    named = {e["field"] for e in body["errors"]}
    assert named == expected, (named, expected, values)
    assert body["field"] == body["errors"][0]["field"]
    assert all(e["message"] for e in body["errors"])


def _assert_rejected_service(
    env: Env, values: dict[str, Any], expected: frozenset[str]
) -> None:
    before = _scan_all(env.ddb)
    created = env.service.create_loan(_loan_input(env.pid, values))
    updated = env.service.update_loan(env.pid, env.loan_id, _loan_input(env.pid, values))
    _check_service_error(created, expected, values)
    _check_service_error(updated, expected, values)
    assert _scan_all(env.ddb) == before


def _assert_rejected_router(
    env: Env, values: dict[str, Any], expected: frozenset[str]
) -> None:
    before = _scan_all(env.ddb)
    body = _body(values)
    posted = _call("POST", f"/properties/{env.pid}/loans", body)
    putted = _call("PUT", f"/properties/{env.pid}/loans/{env.loan_id}", body)
    _check_router_error(posted, expected, values)
    _check_router_error(putted, expected, values)
    assert _scan_all(env.ddb) == before


# ---------------------------------------------------------------------------
# Property 9
# ---------------------------------------------------------------------------


@_RUNS
@given(case=_case())
def test_service_rejects_every_invalid_field_and_writes_nothing(
    env: Env, case: tuple[dict[str, Any], frozenset[str]]
) -> None:
    values, subset = case
    _assert_rejected_service(env, values, subset)


@_RUNS
@given(case=_case())
def test_router_rejects_every_invalid_field_and_writes_nothing(
    env: Env, case: tuple[dict[str, Any], frozenset[str]]
) -> None:
    values, subset = case
    _assert_rejected_router(env, values, subset)


@_RUNS
@given(values=_cap_case())
def test_more_than_600_payments_fails_on_monthly_payment(
    env: Env, values: dict[str, Any]
) -> None:
    expected = frozenset({"monthly_payment"})
    _assert_rejected_service(env, values, expected)
    _assert_rejected_router(env, values, expected)


@_RUNS
@given(values=_year_9999_case())
def test_payment_past_year_9999_fails_on_anchor_date(
    env: Env, values: dict[str, Any]
) -> None:
    expected = frozenset({"anchor_date"})
    _assert_rejected_service(env, values, expected)
    _assert_rejected_router(env, values, expected)


def test_boundaries_are_accepted_or_rejected_exactly() -> None:
    """Spot checks at the 600-row and year-9999 edges (no table needed)."""
    from logstead.services.loan import validate_loan_fields

    def result(balance: str, payment: str, anchor: str):
        return validate_loan_fields(
            LoanInput(
                property_id="p",
                description="x",
                annual_interest_rate=Decimal("0"),
                monthly_payment=Decimal(payment),
                anchor_balance=Decimal(balance),
                anchor_date=anchor,
            )
        )

    assert result("600.00", "1.00", "2024-01-01").error is None  # exactly 600 rows
    err = result("600.01", "1.00", "2024-01-01").error  # 601 rows
    assert err is not None and err.field == "monthly_payment"
    assert result("1.00", "1.00", "9999-11-30").error is None  # last row 9999-12-30
    err = result("1.00", "1.00", "9999-12-01").error  # first row 10000-01-01
    assert err is not None and err.field == "anchor_date"
