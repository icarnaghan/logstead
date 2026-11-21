"""Task 4.3: carryforward routes — concrete example integration tests.

Example-based (not property-based) integration tests for the four carryforward
endpoints, mirroring ``test_dashboard_trends_route.py``: a ``moto``-backed
single-table DynamoDB (base + GSI1 + GSI2) plus an S3 bucket are wired via
``handler_module.configure(...)``, properties/transactions are seeded through
the public ``POST`` endpoints, and the serialized responses are parsed back
from JSON.

Covers (per task 4.3):

* **(a) GET /carryforward shape:** 200 with a well-shaped
  ``ReconciliationSummary`` — ascending ``years``, each with
  ``tax_year``/``schedule_e_net``/``expected_carryforward``/
  ``reported_carryforward``/``status``; ``opening_balance``; ``has_data``. A
  loss year raises the running expected; a later gain reduces it, floored at 0.
* **(b) PUT /carryforward/years/{year}:** a reported value round-trips into a
  subsequent GET with the right ``ok``/``mismatch`` status.
* **(c) negative amount → 400** ``validation`` naming ``field: "amount"``.
* **(d) non-integer {taxYear} → 400.**
* **(e) DELETE clears → the year reverts to ``unreported``.**
* **(f) PUT /carryforward/opening-balance:** round-trips and shifts the
  earliest year's expected.
* **(g) unauthenticated GET → 401.**
* **(h) empty user → ``years == []`` and ``has_data == false``.**
* **(i) /carryforward/opening-balance and /carryforward/years/{taxYear} do not
  shadow each other** (the opening route reaches the opening handler, not the
  year handler with ``taxYear == "opening-balance"``).

Everything runs against in-memory AWS; wiring is reset between tests.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-carryforward"
REGION = "us-east-1"

USER_A = "user-carryforward-A"
USER_B = "user-carryforward-B"

#: Two-decimal money string, e.g. "0.00", "5000.00", "-5000.00" (Req 1.4, 7.1).
_MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")


# --- moto fixtures -----------------------------------------------------------


@pytest.fixture
def aws():
    """A moto context with the DynamoDB table (GSI1/GSI2) and the S3 bucket."""
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
        yield ddb, s3


@pytest.fixture
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def s3_files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture(autouse=True)
def _reset_wiring_after():
    """Clear wiring after every test, even those that reconfigure it."""
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(repo, s3_files):
    """Inject fully-configured moto-backed wiring (repo + S3 files).

    The carryforward service composes the reporting + property + transaction +
    depreciation services the dashboard uses; the transaction service needs the
    S3 adapter, so a configured bucket is required — exactly as in production.
    """
    handler_module.configure(repo=repo, files=s3_files)
    return repo


# --- event / request helpers -------------------------------------------------


def _claims(sub: str) -> dict:
    """Build the verified JWT claim map for a user (as the authorizer delivers)."""
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _event(
    method: str,
    path: str,
    *,
    sub: str | None = None,
    query: dict | None = None,
    body: dict | None = None,
):
    """Build an API Gateway HTTP API v2 proxy event with an optional identity."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": _claims(sub)}}
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
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


def _income(date: str, amount: str) -> dict:
    return {"date": date, "amount": amount, "type": "income", "category_id": "rents-received"}


def _expense(date: str, amount: str) -> dict:
    return {"date": date, "amount": amount, "type": "expense", "category_id": "repairs"}


def _get_carryforward(sub: str) -> dict:
    """GET /carryforward; assert 200 and parse the serialized JSON body."""
    resp = handler(_event("GET", "/carryforward", sub=sub))
    assert resp["statusCode"] == 200, resp["body"]
    return json.loads(resp["body"])


def _year_entry(body: dict, tax_year: int) -> dict:
    return next(y for y in body["years"] if y["tax_year"] == tax_year)


def _seed_loss_then_gain(sub: str) -> str:
    """Seed one property with a 2021 loss year then a 2023 gain year.

    * 2021: income 1000, expenses 6000 → net -5000.00 (a loss).
    * 2023: income 10000, expenses 2000 → net +8000.00 (a gain).

    With an opening balance of 0.00 the running expected is:
    2021 → 0 + 5000 = 5000.00; 2023 → max(5000 - 8000, 0) = 0.00.
    """
    prop = _create_property(sub, "Maple Duplex", "100 Maple St")
    _create_transaction(sub, prop, _income("2021-03-01", "1000.00"))
    _create_transaction(sub, prop, _expense("2021-06-15", "6000.00"))
    _create_transaction(sub, prop, _income("2023-02-01", "10000.00"))
    _create_transaction(sub, prop, _expense("2023-07-20", "2000.00"))
    return prop


# ============================================================================
# (a) GET /carryforward — shape, ordering, running balance, statuses
# ============================================================================


def test_reconcile_returns_well_shaped_series_with_running_balance(wired):
    """GET /carryforward → a correctly-shaped, ascending ReconciliationSummary.

    A loss year raises the running expected; a later gain reduces it floored at
    0.00 (Req 1, 2, 4, 6).
    """
    _seed_loss_then_gain(USER_A)

    body = _get_carryforward(USER_A)

    # Top-level shape.
    assert isinstance(body["years"], list)
    assert body["has_data"] is True
    assert body["opening_balance"] == "0.00"
    assert _MONEY_RE.match(body["opening_balance"])

    tax_years = [y["tax_year"] for y in body["years"]]
    assert tax_years == sorted(tax_years), "years must be ascending"
    assert tax_years == [2021, 2023]

    # Per-year shape: tax_year is the ONLY integer; money fields are two-decimal
    # strings; reported is a string or null; status is a known literal.
    for year in body["years"]:
        assert isinstance(year["tax_year"], int)
        for field in ("schedule_e_net", "expected_carry_in", "expected_carryforward"):
            assert isinstance(year[field], str)
            assert _MONEY_RE.match(year[field]), f"{field} not two-decimal: {year[field]!r}"
        reported = year["reported_carryforward"]
        assert reported is None or (isinstance(reported, str) and _MONEY_RE.match(reported))
        assert year["status"] in {"ok", "mismatch", "carried", "unreported"}

    # 2021 is a loss year → expected rises to the loss magnitude.
    y2021 = _year_entry(body, 2021)
    assert Decimal(y2021["schedule_e_net"]) == Decimal("-5000.00")
    assert y2021["expected_carry_in"] == "0.00"  # opening balance enters 2021
    assert y2021["expected_carryforward"] == "5000.00"
    assert y2021["reported_carryforward"] is None
    assert y2021["status"] == "unreported"

    # 2023 is a gain year → the gain absorbs the balance, floored at 0.00.
    y2023 = _year_entry(body, 2023)
    assert Decimal(y2023["schedule_e_net"]) == Decimal("8000.00")
    assert y2023["expected_carry_in"] == "5000.00"  # 2021's carry-out enters 2023
    assert y2023["expected_carryforward"] == "0.00"
    assert y2023["status"] == "unreported"

    # Summary: next year follows the latest data year; carry-in is its carry-out.
    assert body["next_year"] == 2024
    assert type(body["next_year"]) is int
    assert body["next_year_expected_carry_in"] == "0.00"
    # The status tolerance is a fixed two-decimal string (Req 4.1, 4.2).
    assert body["status_tolerance"] == "2.00"
    assert _MONEY_RE.match(body["status_tolerance"])


# ============================================================================
# (b) PUT /carryforward/years/{year} — reported round-trips with status
# ============================================================================


def test_put_reported_matching_expected_is_ok(wired):
    """PUT a reported carry-in equal to expected carry-in → ``ok``.

    Carry-in semantics: 2021 enters with the 0.00 opening balance; 2023 enters
    with 2021's carry-out of 5000.00.
    """
    _seed_loss_then_gain(USER_A)

    for year, amount in ((2021, "0.00"), (2023, "5000.00")):
        resp = handler(
            _event("PUT", f"/carryforward/years/{year}", sub=USER_A, body={"amount": amount})
        )
        assert resp["statusCode"] == 200, resp["body"]

    body = _get_carryforward(USER_A)
    y2021 = _year_entry(body, 2021)
    assert y2021["reported_carryforward"] == "0.00"
    assert y2021["status"] == "ok"
    assert y2021["drift"] == "0.00"
    y2023 = _year_entry(body, 2023)
    assert y2023["reported_carryforward"] == "5000.00"
    assert y2023["expected_carry_in"] == "5000.00"
    assert y2023["status"] == "ok"
    assert y2023["drift"] == "0.00"


def test_put_reported_differing_from_expected_is_mismatch(wired):
    """PUT a reported carry-in that differs from expected carry-in → ``mismatch``."""
    _seed_loss_then_gain(USER_A)

    resp = handler(
        _event("PUT", "/carryforward/years/2021", sub=USER_A, body={"amount": "500.00"})
    )
    assert resp["statusCode"] == 200, resp["body"]

    body = _get_carryforward(USER_A)
    y2021 = _year_entry(body, 2021)
    # Expected carry-in is the 0.00 opening balance; reported 500.00 differs.
    assert y2021["reported_carryforward"] == "500.00"
    assert y2021["expected_carry_in"] == "0.00"
    assert y2021["expected_carryforward"] == "5000.00"  # carry-out is unchanged
    assert y2021["drift"] == "500.00"
    assert y2021["status"] == "mismatch"


# ============================================================================
# (c) negative amount → 400 validation naming the amount field
# ============================================================================


def test_put_reported_negative_amount_is_validation_error(wired):
    """A negative reported amount → 400 ``validation`` with ``field: amount``."""
    _seed_loss_then_gain(USER_A)

    resp = handler(
        _event("PUT", "/carryforward/years/2021", sub=USER_A, body={"amount": "-5.00"})
    )
    assert resp["statusCode"] == 400, resp["body"]
    err = json.loads(resp["body"])
    assert err["error"] == "validation"
    assert err["field"] == "amount"

    # Nothing was persisted: the year is still unreported.
    body = _get_carryforward(USER_A)
    assert _year_entry(body, 2021)["status"] == "unreported"


# ============================================================================
# (d) non-integer {taxYear} → 400
# ============================================================================


def test_put_reported_non_integer_year_is_400(wired):
    """A non-integer {taxYear} path segment → a clean 400."""
    resp = handler(
        _event("PUT", "/carryforward/years/notayear", sub=USER_A, body={"amount": "500.00"})
    )
    assert resp["statusCode"] == 400, resp["body"]


# ============================================================================
# (e) DELETE clears → the year reverts to unreported
# ============================================================================


def test_delete_reported_reverts_year_to_unreported(wired):
    """DELETE a reported value → a subsequent GET shows the year ``unreported``."""
    _seed_loss_then_gain(USER_A)

    # First set a reported value so there is something to clear.
    # (Carry-in: 2021 enters with the 0.00 opening balance.)
    put = handler(
        _event("PUT", "/carryforward/years/2021", sub=USER_A, body={"amount": "0.00"})
    )
    assert put["statusCode"] == 200, put["body"]
    assert _year_entry(_get_carryforward(USER_A), 2021)["status"] == "ok"

    # Clearing it reverts the year to unreported.
    delete = handler(_event("DELETE", "/carryforward/years/2021", sub=USER_A))
    assert delete["statusCode"] == 200, delete["body"]

    y2021 = _year_entry(_get_carryforward(USER_A), 2021)
    assert y2021["reported_carryforward"] is None
    assert y2021["drift"] is None
    assert y2021["status"] == "unreported"
    # An unreported year still shows its expected carry-in.
    assert y2021["expected_carry_in"] == "0.00"


# ============================================================================
# (f) PUT /carryforward/opening-balance — round-trips and shifts the earliest
# ============================================================================


def test_put_opening_balance_round_trips_and_shifts_earliest_expected(wired):
    """PUT the opening balance → it reflects in GET and raises 2021's expected."""
    _seed_loss_then_gain(USER_A)

    # Baseline: opening 0.00 → 2021 expected is the raw 5000.00 loss magnitude.
    assert _year_entry(_get_carryforward(USER_A), 2021)["expected_carryforward"] == "5000.00"

    resp = handler(
        _event("PUT", "/carryforward/opening-balance", sub=USER_A, body={"amount": "1000.00"})
    )
    assert resp["statusCode"] == 200, resp["body"]

    body = _get_carryforward(USER_A)
    assert body["opening_balance"] == "1000.00"
    # 2021 enters with the opening 1000; carry-out = opening 1000 + loss 5000 = 6000.00.
    assert _year_entry(body, 2021)["expected_carry_in"] == "1000.00"
    assert _year_entry(body, 2021)["expected_carryforward"] == "6000.00"
    assert _year_entry(body, 2023)["expected_carry_in"] == "6000.00"
    # 2023 gain still absorbs the balance: max(6000 - 8000, 0) = 0.00.
    assert _year_entry(body, 2023)["expected_carryforward"] == "0.00"


def test_put_opening_balance_negative_is_validation_error(wired):
    """A negative opening balance → 400 ``validation`` naming ``amount``."""
    resp = handler(
        _event("PUT", "/carryforward/opening-balance", sub=USER_A, body={"amount": "-1.00"})
    )
    assert resp["statusCode"] == 400, resp["body"]
    err = json.loads(resp["body"])
    assert err["error"] == "validation"
    assert err["field"] == "amount"


# ============================================================================
# (g) unauthenticated GET → 401
# ============================================================================


def test_reconcile_requires_auth(wired):
    """GET /carryforward is protected: no JWT claims → 401 unauthorized."""
    resp = handler(_event("GET", "/carryforward"))  # no sub
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# (h) empty user → years == [] and has_data == false
# ============================================================================


def test_reconcile_empty_user_has_no_years_and_no_data(wired):
    """A user with no properties and no opening balance → empty, non-error."""
    body = _get_carryforward(USER_A)
    assert body["years"] == []
    assert body["has_data"] is False
    assert body["opening_balance"] == "0.00"
    assert body["next_year"] is None
    assert body["next_year_expected_carry_in"] == "0.00"
    # Always present, even for the empty series (Req 4.4).
    assert body["status_tolerance"] == "2.00"


# ============================================================================
# (i) the opening-balance route and the years/{taxYear} route do not shadow
# ============================================================================


def test_opening_balance_route_is_not_shadowed_by_year_route(wired):
    """PUT /carryforward/opening-balance reaches the opening handler.

    If the templated ``/carryforward/years/{taxYear}`` route shadowed the
    literal opening-balance route, the request would hit the year handler with
    ``taxYear == "opening-balance"`` and fail ``_int_param`` with a 400. Instead
    the opening handler runs, persisting the single Opening_Balance item — proven
    by it surfacing as ``opening_balance`` (not as a reported year) on GET.
    """
    resp = handler(
        _event("PUT", "/carryforward/opening-balance", sub=USER_A, body={"amount": "250.00"})
    )
    assert resp["statusCode"] == 200, resp["body"]

    body = _get_carryforward(USER_A)
    assert body["opening_balance"] == "250.00"
    # The opening balance alone marks the user as having data...
    assert body["has_data"] is True
    # ...but it is NOT a reconciled year (no property data → no years), proving
    # the value landed on the opening item, not a PLCF#<year> reported entry.
    assert body["years"] == []


# ============================================================================
# Task 5.4 — extended per-year route: allowed_loss / fully_allowed field subsets,
# null-clear, DELETE preserving allowed, non-integer guard, and GET body shape.
#
# Feature: carryforward-allowed-loss, Req 2.1, 2.4, 5.6, 6.5
#
# These APPEND to the existing suite: they reuse the ``wired`` fixture, the
# public-POST seeding helpers (``_seed_loss_then_gain`` builds a 2021 loss year
# with Loss_Magnitude 5000.00 and a 2023 gain year), the ``_event``/``handler``
# transport, ``_get_carryforward``/``_year_entry`` JSON parsing, and ``_MONEY_RE``.
# ============================================================================


def _put_year(sub: str, tax_year: int, body: dict) -> dict:
    """PUT /carryforward/years/{taxYear}; return the raw proxy response."""
    return handler(
        _event("PUT", f"/carryforward/years/{tax_year}", sub=sub, body=body)
    )


# --- allowed_loss on a loss year: round-trips, reduces expected --------------


def test_put_allowed_loss_on_loss_year_reduces_expected(wired):
    """Feature: carryforward-allowed-loss, Req 2.1, 6.5.

    PUT a within-magnitude ``allowed_loss`` on the 2021 loss year → 200; a
    subsequent GET shows that year's ``allowed_loss`` == the amount and a reduced
    ``expected_carryforward`` (reported left untouched / absent).
    """
    _seed_loss_then_gain(USER_A)

    # Baseline: 2021 is a 5000.00 loss, fully suspended → expected 5000.00.
    assert _year_entry(_get_carryforward(USER_A), 2021)["expected_carryforward"] == "5000.00"

    resp = _put_year(USER_A, 2021, {"allowed_loss": "2000.00"})
    assert resp["statusCode"] == 200, resp["body"]

    y2021 = _year_entry(_get_carryforward(USER_A), 2021)
    assert y2021["allowed_loss"] == "2000.00"
    # Only the unallowed 3000.00 carries forward now (and enters 2023).
    assert y2021["expected_carryforward"] == "3000.00"
    assert _year_entry(_get_carryforward(USER_A), 2023)["expected_carry_in"] == "3000.00"
    # Reported was never set, so it stays absent / unreported.
    assert y2021["reported_carryforward"] is None
    assert y2021["status"] == "unreported"


# --- fully_allowed on a loss year: whole loss absorbed -----------------------


def test_put_fully_allowed_on_loss_year_absorbs_whole_loss(wired):
    """Feature: carryforward-allowed-loss, Req 2.1, 6.5.

    PUT ``fully_allowed: true`` on the 2021 loss year → 200; GET shows
    ``fully_allowed: true`` and that year fully absorbed (expected 0.00).
    """
    _seed_loss_then_gain(USER_A)

    resp = _put_year(USER_A, 2021, {"fully_allowed": True})
    assert resp["statusCode"] == 200, resp["body"]

    y2021 = _year_entry(_get_carryforward(USER_A), 2021)
    assert y2021["fully_allowed"] is True
    # The full 5000.00 loss is allowed → nothing carries forward.
    assert y2021["expected_carryforward"] == "0.00"


# --- allowed data on a GAIN year is a validation error -----------------------


def test_put_fully_allowed_on_gain_year_is_validation_error(wired):
    """Feature: carryforward-allowed-loss, Req 5.6.

    ``fully_allowed: true`` on the 2023 gain year → 400 validation naming
    ``field: "fullyAllowed"``; nothing persists.
    """
    _seed_loss_then_gain(USER_A)

    resp = _put_year(USER_A, 2023, {"fully_allowed": True})
    assert resp["statusCode"] == 400, resp["body"]
    err = json.loads(resp["body"])
    assert err["error"] == "validation"
    assert err["field"] == "fullyAllowed"

    # Unchanged: the gain year still reports no allowed state.
    y2023 = _year_entry(_get_carryforward(USER_A), 2023)
    assert y2023["fully_allowed"] is False
    assert y2023["allowed_loss"] == "0.00"


def test_put_allowed_loss_on_gain_year_is_validation_error(wired):
    """Feature: carryforward-allowed-loss, Req 5.6.

    A positive ``allowed_loss`` on the 2023 gain year → 400 validation naming
    ``field: "allowedLoss"``; nothing persists.
    """
    _seed_loss_then_gain(USER_A)

    resp = _put_year(USER_A, 2023, {"allowed_loss": "100.00"})
    assert resp["statusCode"] == 400, resp["body"]
    err = json.loads(resp["body"])
    assert err["error"] == "validation"
    assert err["field"] == "allowedLoss"

    assert _year_entry(_get_carryforward(USER_A), 2023)["allowed_loss"] == "0.00"


# --- allowed_loss: null clears, preserving a previously-set reported value ---


def test_put_allowed_loss_null_clears_and_preserves_reported(wired):
    """Feature: carryforward-allowed-loss, Req 2.4.

    ``allowed_loss: null`` clears the allowed amount (GET shows ``allowed_loss``
    back to "0.00"), while a previously-set reported value on that year is
    PRESERVED. Set reported first, then set+clear allowed, and assert reported
    survives the clear.
    """
    _seed_loss_then_gain(USER_A)

    # Seed a reported value and an allowed amount on the same 2021 loss year.
    assert _put_year(USER_A, 2021, {"amount": "3000.00"})["statusCode"] == 200
    assert _put_year(USER_A, 2021, {"allowed_loss": "2000.00"})["statusCode"] == 200

    before = _year_entry(_get_carryforward(USER_A), 2021)
    assert before["reported_carryforward"] == "3000.00"
    assert before["allowed_loss"] == "2000.00"

    # Clearing allowed must not disturb the reported sibling.
    resp = _put_year(USER_A, 2021, {"allowed_loss": None})
    assert resp["statusCode"] == 200, resp["body"]

    after = _year_entry(_get_carryforward(USER_A), 2021)
    assert after["allowed_loss"] == "0.00"
    assert after["reported_carryforward"] == "3000.00"


# --- both amount and allowed_loss in one body both persist -------------------


def test_put_both_amount_and_allowed_loss_persist(wired):
    """Feature: carryforward-allowed-loss, Req 2.1, 6.5.

    A single PUT carrying BOTH ``amount`` and ``allowed_loss`` persists both;
    GET shows each.
    """
    _seed_loss_then_gain(USER_A)

    # Carry-in semantics: 2021 enters with the 0.00 opening balance.
    resp = _put_year(USER_A, 2021, {"amount": "0.00", "allowed_loss": "2000.00"})
    assert resp["statusCode"] == 200, resp["body"]

    y2021 = _year_entry(_get_carryforward(USER_A), 2021)
    assert y2021["allowed_loss"] == "2000.00"
    assert y2021["reported_carryforward"] == "0.00"
    # Unallowed 3000.00 carries out of 2021; reported carry-in 0.00 matches → ok.
    assert y2021["expected_carry_in"] == "0.00"
    assert y2021["expected_carryforward"] == "3000.00"
    assert y2021["status"] == "ok"


# --- DELETE clears only reported; allowed_loss is preserved ------------------


def test_delete_clears_only_reported_and_preserves_allowed(wired):
    """Feature: carryforward-allowed-loss, Req 2.4.

    DELETE /carryforward/years/{taxYear} clears ONLY the reported value; a
    previously-set ``allowed_loss`` on that year is PRESERVED in the next GET.
    """
    _seed_loss_then_gain(USER_A)

    # Both values set on the 2021 loss year.
    assert _put_year(USER_A, 2021, {"amount": "3000.00"})["statusCode"] == 200
    assert _put_year(USER_A, 2021, {"allowed_loss": "2000.00"})["statusCode"] == 200

    delete = handler(_event("DELETE", "/carryforward/years/2021", sub=USER_A))
    assert delete["statusCode"] == 200, delete["body"]

    y2021 = _year_entry(_get_carryforward(USER_A), 2021)
    # Reported is gone...
    assert y2021["reported_carryforward"] is None
    assert y2021["status"] == "unreported"
    # ...but the allowed amount (and its effect on expected) survives.
    assert y2021["allowed_loss"] == "2000.00"
    assert y2021["expected_carryforward"] == "3000.00"


# --- non-integer {taxYear} on the extended PUT → 400 (existing guard) --------


def test_put_allowed_non_integer_year_is_400(wired):
    """Feature: carryforward-allowed-loss, Req 6.5.

    A non-integer ``{taxYear}`` path segment on the allowed PUT → a clean 400
    (the ``_int_param`` guard runs before the service).
    """
    resp = _put_year(USER_A, "notayear", {"allowed_loss": "100.00"})  # type: ignore[arg-type]
    assert resp["statusCode"] == 400, resp["body"]


# --- GET body carries allowed_loss (money string) + fully_allowed (bool) -----


def test_get_body_carries_allowed_loss_and_fully_allowed_on_every_year(wired):
    """Feature: carryforward-allowed-loss, Req 6.5.

    Every year in the GET /carryforward body carries ``allowed_loss`` as a
    non-negative two-decimal money string and ``fully_allowed`` as a JSON
    boolean — on both loss and gain years, with and without stored allowed data.
    """
    _seed_loss_then_gain(USER_A)
    # Put allowed data on the loss year so one row exercises a non-default value.
    assert _put_year(USER_A, 2021, {"allowed_loss": "2000.00"})["statusCode"] == 200

    body = _get_carryforward(USER_A)
    assert [y["tax_year"] for y in body["years"]] == [2021, 2023]

    for year in body["years"]:
        allowed = year["allowed_loss"]
        assert isinstance(allowed, str)
        assert _MONEY_RE.match(allowed), f"allowed_loss not two-decimal: {allowed!r}"
        assert Decimal(allowed) >= Decimal("0.00"), "allowed_loss must be non-negative"
        # JSON boolean (not a truthy string / int): identity against True/False.
        assert year["fully_allowed"] is True or year["fully_allowed"] is False

    # The year we set reads back its stored value; the untouched gain year defaults.
    assert _year_entry(body, 2021)["allowed_loss"] == "2000.00"
    assert _year_entry(body, 2023)["allowed_loss"] == "0.00"
    assert _year_entry(body, 2023)["fully_allowed"] is False
