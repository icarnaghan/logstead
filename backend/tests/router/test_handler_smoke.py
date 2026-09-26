"""Task 16.1 smoke test: the Lambda handler routes representative requests.

A small, representative smoke test that the router wires requests to services
and shapes responses correctly. It is intentionally **not** the full router
dispatch / error-mapping integration suite (that is task 16.2). It exercises:

  * ``GET /categories`` (public route) returns the seeded catalog as JSON;
  * ``POST /properties`` with a JWT-claims event creates a property (201) and the
    money-free dataclass is serialized to JSON;
  * a protected route with **no** verified claims is rejected with ``401`` and no
    side effects;
  * an unknown route yields ``404``;
  * a validation failure from a service maps to ``400`` with the offending field.

Everything runs against a ``moto``-backed DynamoDB table + S3 bucket via the
router's ``configure`` injection seam, so no environment or live AWS is touched.
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.category import seed_categories

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_SUB = "user-smoke-1"


@pytest.fixture
def aws():
    """A moto context with the DynamoDB table (GSI1/GSI2) and S3 bucket created."""
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


@pytest.fixture(autouse=True)
def wired(aws, repo):
    """Inject moto-backed wiring into the router and reset it after each test."""
    _, s3 = aws
    handler_module.configure(repo=repo, files=S3FileAdapter(s3, BUCKET))
    yield
    handler_module.reset_wiring()


def _event(
    method: str,
    path: str,
    *,
    claims: dict | None = None,
    body: dict | None = None,
    stage: str | None = None,
):
    """Build a minimal API Gateway HTTP API v2 proxy event.

    When ``stage`` is given, the path is prefixed with ``/<stage>`` the way a
    non-$default HTTP API stage delivers it, and ``requestContext.stage`` is set,
    so tests can exercise stage-prefix stripping.
    """
    event_path = f"/{stage}{path}" if stage else path
    event: dict = {
        "requestContext": {"http": {"method": method, "path": event_path}},
        "rawPath": event_path,
    }
    if stage:
        event["requestContext"]["stage"] = stage
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _auth_claims() -> dict:
    return {"sub": USER_SUB, "cognito:username": "smoke@example.com"}


# --- GET /categories (public) ------------------------------------------------


def test_get_categories_returns_seeded_catalog(repo):
    seed_categories(repo)

    resp = handler(_event("GET", "/categories"))

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "application/json"
    catalog = json.loads(resp["body"])
    assert isinstance(catalog, list)
    # Rents received (line 3) and Other (line 19) are in the seeded set.
    lines = {c["schedule_e_line"] for c in catalog}
    assert 3 in lines
    assert 19 in lines
    assert 18 not in lines  # depreciation is never an assignable category


# --- POST /properties with JWT claims (create) -------------------------------


def test_post_property_with_claims_creates_property(repo):
    body = {"name": "Maple Duplex", "address_text": "123 Maple St"}
    resp = handler(_event("POST", "/properties", claims=_auth_claims(), body=body))

    assert resp["statusCode"] == 201
    created = json.loads(resp["body"])
    assert created["name"] == "Maple Duplex"
    assert created["address_text"] == "123 Maple St"
    assert created["user_id"] == USER_SUB
    assert created["id"]

    # It really persisted under the user's partition.
    item = repo.get_item(keys.user_pk(USER_SUB), keys.property_user_sk(created["id"]))
    assert item is not None


# --- 401 without claims ------------------------------------------------------


def test_post_property_without_claims_is_401(repo):
    body = {"name": "Should Not Persist", "address_text": "0 Nowhere"}
    resp = handler(_event("POST", "/properties", body=body))  # no claims

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"

    # No side effect: the user has no properties.
    listed = repo.query(keys.user_pk(USER_SUB), sk_begins_with=keys.property_list_prefix())
    assert listed == []


# --- 404 unknown route -------------------------------------------------------


def test_unknown_route_is_404():
    resp = handler(_event("GET", "/nope/nowhere", claims=_auth_claims()))
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


# --- CORS preflight (OPTIONS) ------------------------------------------------


def test_options_preflight_returns_success_without_auth():
    """A CORS preflight OPTIONS request is answered with a 2xx and no body,
    without requiring JWT claims. API Gateway auto-CORS attaches the
    Access-Control-* headers; the Lambda only supplies a success status so the
    browser preflight passes (it must not be gated by the authorizer)."""
    resp = handler(_event("OPTIONS", "/dashboard"))  # no claims, like a browser
    assert 200 <= resp["statusCode"] < 300
    assert resp.get("body", "") == ""


def test_options_preflight_on_unknown_path_still_succeeds():
    """Preflight for any path under the catch-all succeeds; the router does not
    404 an OPTIONS request the way it would a GET to an unknown route."""
    resp = handler(_event("OPTIONS", "/anything/at/all"))
    assert 200 <= resp["statusCode"] < 300


# --- Stage-prefixed paths ----------------------------------------------------


def test_stage_prefixed_path_matches_route(repo):
    """A non-$default stage (e.g. "prod") prefixes the path with /prod. The
    router strips it so /prod/categories resolves the same as /categories."""
    seed_categories(repo)
    resp = handler(_event("GET", "/categories", stage="prod"))
    assert resp["statusCode"] == 200
    catalog = json.loads(resp["body"])
    assert isinstance(catalog, list) and catalog


# --- validation failure maps to 400 with field ------------------------------


def test_blank_name_maps_to_400_with_field(repo):
    body = {"name": "  ", "address_text": "123 Maple St"}
    resp = handler(_event("POST", "/properties", claims=_auth_claims(), body=body))

    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "name"
