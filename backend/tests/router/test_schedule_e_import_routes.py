"""Task 4.3: handler/integration tests for the Schedule E Import routes.

Drives the router end-to-end against a ``moto``-backed DynamoDB table
(base + GSI1 + GSI2) and S3 bucket wired via ``handler_module.configure(...)``,
exactly like ``test_handler_integration.py``. Requests are API Gateway HTTP API
v2 proxy events carrying a Cognito-claims stub.

Covered (design "Route surface + wiring" / "Error Handling"; Req 1.5, 8, 9.6):

* ``POST /imports/schedule-e`` → ``201`` with the per-entry outcome.
* a validation body (negative amount) → ``400`` carrying the structured dotted
  ``field`` (``entries[0].lines[14]``).
* a not-owned property → ``404``.
* ``DELETE /imports/schedule-e/{propertyId}/{taxYear}`` → ``200`` with
  ``deleted_count``.
* a non-integer ``taxYear`` path segment → ``400`` via the router shape guard.
* dual snake/camel body tolerance (``taxYear``/``propertyId``/``scheduleELine``).
* **regression:** the new routes do not shadow the existing ``/imports`` PDF
  routes — ``GET/PUT/DELETE /imports/{sessionId}...`` still resolve to the PDF
  (``ExpenseImportService``) handlers.
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-schedule-e"
REGION = "us-east-1"
USER_SUB = "user-schedule-e-1"
OTHER_SUB = "user-schedule-e-2"


# --- moto fixtures -----------------------------------------------------------


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


@pytest.fixture
def s3_files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture(autouse=True)
def _reset_wiring_after():
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(repo, s3_files):
    """Inject fully-configured moto-backed wiring (repo + S3 files) into the router."""
    handler_module.configure(repo=repo, files=s3_files)
    return repo


# --- event / request helpers -------------------------------------------------


def _event(method, path, *, claims=None, body=None, query=None, raw_body=None):
    """Build an API Gateway HTTP API v2 proxy event."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if raw_body is not None:
        event["body"] = raw_body
    elif body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    return event


def _claims(sub: str = USER_SUB) -> dict:
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _create_property(name="Cedar Fourplex", address="500 Cedar Ave", sub=USER_SUB) -> dict:
    """Create a property via the handler and return the parsed created body."""
    resp = handler(
        _event("POST", "/properties", claims=_claims(sub),
               body={"name": name, "address_text": address})
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


# ============================================================================
# POST /imports/schedule-e
# ============================================================================


def test_import_schedule_e_201_with_per_entry_outcome(wired):
    """A valid submission → 201 with a per-entry ImportOutcome."""
    prop = _create_property()
    body = {
        "tax_year": 2023,
        "entries": [
            {
                "property_id": prop["id"],
                "lines": [
                    {"schedule_e_line": 3, "amount": "24000.00"},
                    {"schedule_e_line": 14, "amount": "1875.50"},
                    {"schedule_e_line": 19, "amount": "320.00",
                     "description": "HOA dues"},
                ],
            }
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 201, resp["body"]
    outcome = json.loads(resp["body"])
    assert outcome["tax_year"] == 2023
    assert len(outcome["entries"]) == 1
    entry = outcome["entries"][0]
    assert entry["property_id"] == prop["id"]
    assert len(entry["created_transaction_ids"]) == 3  # one per non-zero line
    assert entry["deleted_prior_count"] == 0
    assert entry["created_inline_property"] is False

    # The synthesized rows are retrievable in the tax-year listing and marked.
    listing = handler(
        _event("GET", f"/properties/{prop['id']}/transactions",
               claims=_claims(), query={"taxYear": 2023})
    )
    assert listing["statusCode"] == 200
    txns = json.loads(listing["body"])
    assert len(txns) == 3
    assert all(t["imported"] is True for t in txns)
    assert all(t["date"] == "2023-12-31" for t in txns)


def test_import_schedule_e_camelcase_body_tolerated(wired):
    """A camelCase body (taxYear/propertyId/scheduleELine) is accepted → 201."""
    prop = _create_property()
    body = {
        "taxYear": 2022,
        "entries": [
            {
                "propertyId": prop["id"],
                "lines": [{"scheduleELine": 3, "amount": "12000.00"}],
            }
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 201, resp["body"]
    outcome = json.loads(resp["body"])
    assert outcome["tax_year"] == 2022
    assert len(outcome["entries"][0]["created_transaction_ids"]) == 1


def test_import_schedule_e_inline_new_property_camel(wired):
    """newProperty (camelCase) is parsed into a PropertyInput and created inline."""
    body = {
        "taxYear": 2021,
        "entries": [
            {
                "newProperty": {"name": "Maple Duplex B", "addressText": "12 Maple St"},
                "lines": [{"scheduleELine": 3, "amount": "18000.00"}],
            }
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 201, resp["body"]
    entry = json.loads(resp["body"])["entries"][0]
    assert entry["created_inline_property"] is True
    assert entry["property_id"]


def test_import_schedule_e_negative_amount_400_with_structured_field(wired):
    """A negative line amount → 400 carrying the structured dotted field."""
    prop = _create_property()
    body = {
        "tax_year": 2023,
        "entries": [
            {
                "property_id": prop["id"],
                "lines": [{"schedule_e_line": 14, "amount": "-5.00"}],
            }
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 400, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "entries[0].lines[14]"


def test_import_schedule_e_missing_tax_year_400_field_tax_year(wired):
    """A submission without a tax year → 400 with field=tax_year."""
    prop = _create_property()
    body = {
        "entries": [
            {"property_id": prop["id"],
             "lines": [{"schedule_e_line": 3, "amount": "100.00"}]},
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 400, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "tax_year"


def test_import_schedule_e_not_owned_property_404(wired):
    """An entry mapping to a property the user does not own → 404."""
    # Property owned by a different user.
    other = _create_property(name="Not Yours", address="9 Other Rd", sub=OTHER_SUB)
    body = {
        "tax_year": 2023,
        "entries": [
            {"property_id": other["id"],
             "lines": [{"schedule_e_line": 3, "amount": "100.00"}]},
        ],
    }
    resp = handler(_event("POST", "/imports/schedule-e", claims=_claims(), body=body))
    assert resp["statusCode"] == 404, resp["body"]
    assert json.loads(resp["body"])["error"] == "not_found"


def test_import_schedule_e_requires_auth(wired):
    """The route is protected: no JWT claims → 401."""
    resp = handler(_event("POST", "/imports/schedule-e", body={"tax_year": 2023, "entries": []}))
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# DELETE /imports/schedule-e/{propertyId}/{taxYear}
# ============================================================================


def test_remove_schedule_e_import_200_with_deleted_count(wired):
    """DELETE removes the imported set for a (property, year) → 200 deleted_count."""
    prop = _create_property()
    # First import two non-zero lines for 2023.
    handler(_event("POST", "/imports/schedule-e", claims=_claims(), body={
        "tax_year": 2023,
        "entries": [{
            "property_id": prop["id"],
            "lines": [
                {"schedule_e_line": 3, "amount": "24000.00"},
                {"schedule_e_line": 14, "amount": "500.00"},
            ],
        }],
    }))

    resp = handler(
        _event("DELETE", f"/imports/schedule-e/{prop['id']}/2023", claims=_claims())
    )
    assert resp["statusCode"] == 200, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["property_id"] == prop["id"]
    assert payload["tax_year"] == 2023
    assert payload["deleted_count"] == 2

    # The imported rows are gone.
    listing = handler(
        _event("GET", f"/properties/{prop['id']}/transactions",
               claims=_claims(), query={"taxYear": 2023})
    )
    assert json.loads(listing["body"]) == []


def test_remove_schedule_e_import_non_integer_tax_year_400(wired):
    """A non-integer taxYear path segment → 400 via the router shape guard."""
    prop = _create_property()
    resp = handler(
        _event("DELETE", f"/imports/schedule-e/{prop['id']}/notayear", claims=_claims())
    )
    assert resp["statusCode"] == 400, resp["body"]
    assert json.loads(resp["body"])["error"] == "validation"


def test_remove_schedule_e_import_not_owned_property_404(wired):
    """Removing an imported set for a property the user does not own → 404."""
    other = _create_property(name="Not Yours", address="9 Other Rd", sub=OTHER_SUB)
    resp = handler(
        _event("DELETE", f"/imports/schedule-e/{other['id']}/2023", claims=_claims())
    )
    assert resp["statusCode"] == 404, resp["body"]
    assert json.loads(resp["body"])["error"] == "not_found"


# ============================================================================
# Regression: new routes do not shadow the existing /imports PDF routes
# ============================================================================


def test_pdf_import_session_route_still_resolves(wired):
    """GET /imports/{sessionId} still dispatches to the PDF (ExpenseImport) handler.

    An unknown session id resolves to the PDF handler and returns a 404 from the
    ExpenseImportService (not a 405/unknown-route and not the schedule-e handler).
    A schedule-e handler would never be reached for this 2-segment GET.
    """
    resp = handler(
        _event("GET", "/imports/some-session-id", claims=_claims())
    )
    # Dispatched to the PDF get_session handler → service reports not_found.
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_pdf_import_drafts_route_still_resolves(wired):
    """GET /imports/{sessionId}/drafts still dispatches to the PDF drafts handler."""
    resp = handler(
        _event("GET", "/imports/some-session-id/drafts", claims=_claims())
    )
    # The router now proves session ownership first, so an unknown session is a
    # not_found 404 (the same response a foreign user's session gets). Reaching
    # the session lookup shows it dispatched to the PDF handler, not an
    # unknown-route 404 and not the 4-segment schedule-e DELETE template.
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert body["error"] == "not_found"
    assert body["message"] == "Import session not found."


def test_pdf_import_draft_delete_not_shadowed_by_schedule_e_delete(wired):
    """DELETE /imports/{sessionId}/drafts/{draftId} resolves to the PDF handler.

    This 4-segment DELETE shares its segment count with
    DELETE /imports/schedule-e/{propertyId}/{taxYear}; the literal "schedule-e"
    segment keeps them distinct. The PDF route must still resolve (not a 400 from
    the schedule-e taxYear int guard and not an unknown-route 404).
    """
    resp = handler(
        _event("DELETE", "/imports/some-session-id/drafts/some-draft-id",
               claims=_claims())
    )
    # Reached the PDF remove_draft handler → not_found for the unknown ids,
    # NOT a 400 (which the schedule-e handler would raise on a non-int taxYear).
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"
