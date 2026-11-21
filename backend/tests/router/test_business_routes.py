"""Task 7.1: handler/integration tests for the business + link routes.

Exercises the business-entity routes and the property↔business link route in
``router/handler.py`` as an integration boundary, in the same style as
``test_handler_integration.py``: API Gateway HTTP API v2 proxy event dicts, the
Cognito JWT-claims auth stub, a ``moto``-backed DynamoDB table (base + GSI1 +
GSI2) and S3 bucket wired via ``handler_module.configure(...)``, and status-code
assertions on the proxy response.

Coverage (per the task):

* **Status-code mapping per method/route** — ``POST /businesses`` → 201;
  ``GET /businesses``, ``GET``/``PUT /businesses/{businessId}`` → 200; an
  unknown or cross-user id → 404; ``DELETE`` a business that still owns a linked
  property → 409 (conflict).
* **Document routes return 503 when files/bucket are unavailable** — the
  business service for the document routes is built with ``require_files=True``,
  so a wiring with ``files=None`` surfaces a clean 503 for
  ``POST``/``GET /businesses/{businessId}/documents`` and
  ``DELETE .../documents/{documentId}``.
* **The ``PUT /properties/{propertyId}/business`` set/clear link route** — body
  ``{"business_id": "<id>" | null}`` links then clears a property's owning
  business.
* **``GET /businesses/{businessId}`` carries linked property NAMES** — the
  single-business response includes ``linked_properties`` as ``{id, name}``
  refs (never a raw id where a name exists, Req 10.3).

Everything runs against in-memory AWS; no environment or live AWS is touched.
Wiring is reset between tests by the autouse fixture.
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
BUCKET = "logstead-files-business"
REGION = "us-east-1"
USER_SUB = "user-business-1"
OTHER_SUB = "user-business-2"


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
    """Guarantee wiring is cleared after every test, even those that reconfigure it."""
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(repo, s3_files):
    """Inject fully-configured moto-backed wiring (repo + S3 files) into the router."""
    handler_module.configure(repo=repo, files=s3_files)
    return repo


# --- event / request helpers -------------------------------------------------


def _event(
    method: str,
    path: str,
    *,
    claims: dict | None = None,
    body=None,
    raw_body: str | None = None,
):
    """Build an API Gateway HTTP API v2 proxy event.

    ``claims=None`` means an unauthenticated request (no ``authorizer`` block).
    """
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
    return event


def _claims(sub: str = USER_SUB) -> dict:
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _create_business(
    name: str = "Acme Holdings LLC",
    entity_type: str = "llc",
    *,
    sub: str = USER_SUB,
) -> dict:
    """Create a business via the handler and return the parsed created body."""
    resp = handler(
        _event(
            "POST",
            "/businesses",
            claims=_claims(sub),
            body={"legal_name": name, "entity_type": entity_type},
        )
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _create_property(
    name: str = "Maple Duplex",
    address: str = "123 Maple St",
    *,
    sub: str = USER_SUB,
) -> dict:
    """Create a property via the handler and return the parsed created body."""
    resp = handler(
        _event(
            "POST",
            "/properties",
            claims=_claims(sub),
            body={"name": name, "address_text": address},
        )
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


# ============================================================================
# Status-code mapping per method / route
# ============================================================================


def test_post_business_returns_201(wired):
    """POST /businesses creates a business → 201 with the stored record."""
    resp = handler(
        _event(
            "POST",
            "/businesses",
            claims=_claims(),
            body={"legal_name": "Cedar Holdings LLC", "entity_type": "llc"},
        )
    )
    assert resp["statusCode"] == 201
    created = json.loads(resp["body"])
    assert created["legal_name"] == "Cedar Holdings LLC"
    assert created["entity_type"] == "llc"
    assert created["user_id"] == USER_SUB
    assert created["id"]


def test_get_businesses_lists_created_business_200(wired):
    """GET /businesses lists the user's businesses → 200."""
    created = _create_business()

    resp = handler(_event("GET", "/businesses", claims=_claims()))
    assert resp["statusCode"] == 200
    listed = json.loads(resp["body"])
    assert isinstance(listed, list)
    assert [b["id"] for b in listed] == [created["id"]]


def test_get_single_business_200(wired):
    """GET /businesses/{businessId} returns the single business → 200."""
    created = _create_business()

    resp = handler(
        _event("GET", f"/businesses/{created['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == created["id"]
    assert body["legal_name"] == "Acme Holdings LLC"


def test_put_business_updates_200(wired):
    """PUT /businesses/{businessId} updates the business → 200."""
    created = _create_business()

    resp = handler(
        _event(
            "PUT",
            f"/businesses/{created['id']}",
            claims=_claims(),
            body={"legal_name": "Acme Renamed LLC", "entity_type": "s_corporation"},
        )
    )
    assert resp["statusCode"] == 200
    updated = json.loads(resp["body"])
    assert updated["id"] == created["id"]
    assert updated["legal_name"] == "Acme Renamed LLC"
    assert updated["entity_type"] == "s_corporation"


def test_get_unknown_business_404(wired):
    """GET a business id that does not exist → 404."""
    resp = handler(
        _event("GET", "/businesses/does-not-exist", claims=_claims())
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_get_cross_user_business_404(wired):
    """A business owned by another user is not readable → 404.

    User A creates a business; user B's GET of A's id must not leak it.
    """
    created = _create_business(sub=OTHER_SUB)

    resp = handler(
        _event("GET", f"/businesses/{created['id']}", claims=_claims(USER_SUB))
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_put_cross_user_business_404(wired):
    """PUT against another user's business id → 404 (ownership enforced)."""
    created = _create_business(sub=OTHER_SUB)

    resp = handler(
        _event(
            "PUT",
            f"/businesses/{created['id']}",
            claims=_claims(USER_SUB),
            body={"legal_name": "Hijacked LLC", "entity_type": "llc"},
        )
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_delete_business_with_linked_property_409(wired):
    """DELETE a business that still owns a linked property → 409 conflict.

    The delete-guard refuses while any property is linked and mutates nothing;
    the business is still readable afterward.
    """
    business = _create_business()
    prop = _create_property()
    link = handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": business["id"]},
        )
    )
    assert link["statusCode"] == 200

    resp = handler(
        _event("DELETE", f"/businesses/{business['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error"] == "conflict"

    # Nothing was deleted: the business is still there.
    still = handler(
        _event("GET", f"/businesses/{business['id']}", claims=_claims())
    )
    assert still["statusCode"] == 200


def test_delete_business_after_unlink_succeeds_200(wired):
    """Once the property is unlinked the guarded delete succeeds → 200."""
    business = _create_business()
    prop = _create_property()
    assert handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": business["id"]},
        )
    )["statusCode"] == 200

    # Clear the link, then delete.
    assert handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": None},
        )
    )["statusCode"] == 200

    resp = handler(
        _event("DELETE", f"/businesses/{business['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    # And it is gone.
    assert handler(
        _event("GET", f"/businesses/{business['id']}", claims=_claims())
    )["statusCode"] == 404


def test_delete_unlinked_business_200(wired):
    """DELETE a business with no linked properties → 200."""
    business = _create_business()

    resp = handler(
        _event("DELETE", f"/businesses/{business['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200


# ============================================================================
# Document routes degrade to 503 when the file bucket is unavailable
# ============================================================================


def test_post_business_document_without_files_503(repo):
    """POST /businesses/{id}/documents with no bucket wired → 503.

    The document routes build the business service with ``require_files=True``,
    so a repo-only wiring surfaces a clean 503 rather than crashing.
    """
    handler_module.configure(repo=repo)  # files=None
    business = _create_business()

    resp = handler(
        _event(
            "POST",
            f"/businesses/{business['id']}/documents",
            claims=_claims(),
            body={"filename": "formation.pdf", "content_type": "application/pdf"},
        )
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_get_business_documents_without_files_503(repo):
    """GET /businesses/{id}/documents with no bucket wired → 503."""
    handler_module.configure(repo=repo)  # files=None
    business = _create_business()

    resp = handler(
        _event(
            "GET",
            f"/businesses/{business['id']}/documents",
            claims=_claims(),
        )
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_delete_business_document_without_files_503(repo):
    """DELETE /businesses/{id}/documents/{docId} with no bucket wired → 503."""
    handler_module.configure(repo=repo)  # files=None
    business = _create_business()

    resp = handler(
        _event(
            "DELETE",
            f"/businesses/{business['id']}/documents/some-doc-id",
            claims=_claims(),
        )
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_business_document_routes_dispatch_with_files(wired):
    """With a bucket wired the document routes dispatch past the 503 guard.

    A GET on an owned business's (empty) document list returns 200, proving the
    4-segment document path resolves ahead of the 2-segment single-id path and
    that the file adapter is wired for these routes.
    """
    business = _create_business()

    resp = handler(
        _event(
            "GET",
            f"/businesses/{business['id']}/documents",
            claims=_claims(),
        )
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == []


# ============================================================================
# PUT /properties/{propertyId}/business — set / clear link route
# ============================================================================


def test_set_property_business_links_200(wired):
    """PUT .../business with {business_id: <id>} links the property → 200."""
    business = _create_business()
    prop = _create_property()

    resp = handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": business["id"]},
        )
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["business_id"] == business["id"]


def test_clear_property_business_with_null_200(wired):
    """PUT .../business with {business_id: null} clears the link → 200."""
    business = _create_business()
    prop = _create_property()
    assert handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": business["id"]},
        )
    )["statusCode"] == 200

    resp = handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": None},
        )
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["business_id"] is None


def test_set_property_business_unknown_business_404(wired):
    """Linking to an unknown business id → 404 (ownership validated)."""
    prop = _create_property()

    resp = handler(
        _event(
            "PUT",
            f"/properties/{prop['id']}/business",
            claims=_claims(),
            body={"business_id": "no-such-business"},
        )
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_set_property_business_requires_auth_401(wired):
    """The link route is protected: no JWT claims → 401."""
    resp = handler(
        _event("PUT", "/properties/any/business", body={"business_id": None})
    )
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# GET /businesses/{businessId} carries linked property NAMES (Req 10.2/10.3)
# ============================================================================


def test_get_single_business_includes_linked_property_names(wired):
    """The single-business response lists linked properties by name, not raw id.

    Two properties are linked to the business; the ``GET`` response's
    ``linked_properties`` entries carry the human-readable property ``name`` for
    each (Req 10.3: never a raw id where a name exists), keyed to the right id.
    """
    business = _create_business()
    p1 = _create_property(name="Dockside", address="1 Dock St")
    p2 = _create_property(name="Wharf House", address="2 Wharf Ave")
    for p in (p1, p2):
        assert handler(
            _event(
                "PUT",
                f"/properties/{p['id']}/business",
                claims=_claims(),
                body={"business_id": business["id"]},
            )
        )["statusCode"] == 200

    resp = handler(
        _event("GET", f"/businesses/{business['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    assert "linked_properties" in body
    refs = body["linked_properties"]
    assert {(r["id"], r["name"]) for r in refs} == {
        (p1["id"], "Dockside"),
        (p2["id"], "Wharf House"),
    }
    # Every linked ref carries a human-readable name (Req 10.3).
    assert all(r.get("name") for r in refs)


def test_get_single_business_empty_linked_properties(wired):
    """A business with no links reports an empty ``linked_properties`` list."""
    business = _create_business()

    resp = handler(
        _event("GET", f"/businesses/{business['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["linked_properties"] == []
