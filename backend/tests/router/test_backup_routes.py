"""Task 8.2: backup/restore/clear route handler + integration suite.

Drives the router as an integration boundary (mirroring
``test_handler_integration.py``): a ``moto``-backed DynamoDB table (base +
GSI1 + GSI2) and S3 bucket are wired via ``handler_module.configure(...)``, and
requests are built as API Gateway HTTP API v2 proxy events with the verified
Cognito identity placed at
``event["requestContext"]["authorizer"]["jwt"]["claims"]`` — exactly how the
JWT authorizer delivers it.

Coverage:

* **GET /backup** → 200 with the exported document for the authenticated user.
* **POST /backup/restore** — a valid document → 200 with a restore summary; an
  *invalid* document → 400 carrying the offending validation ``field`` and
  message.
* **POST /backup/clear** → 200 with a clear summary.
* **503 path** — with wiring that has no S3 bucket (``files=None``), restore and
  clear both surface a clean 503 (via ``_require_files``), never a crash.
* **Property 8 (user scoping)** — a Hypothesis property (``max_examples>=100``):
  export/clear/restore run as user A never read, return, or mutate any row owned
  by user B; A's export never contains B's data and B's partitions are
  byte-for-byte untouched.

Everything runs against in-memory AWS; wiring is reset between tests.
"""

from __future__ import annotations

import json

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-backup-routes"
REGION = "us-east-1"

USER_A = "user-backup-A"
USER_B = "user-backup-B"


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
    """Clear wiring after every test, even those that reconfigure it."""
    yield
    handler_module.reset_wiring()


@pytest.fixture
def wired(repo, s3_files):
    """Inject fully-configured moto-backed wiring (repo + S3 files)."""
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
    body=None,
    raw_body: str | None = None,
):
    """Build an API Gateway HTTP API v2 proxy event with an optional identity."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if sub is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": _claims(sub)}}
    if raw_body is not None:
        event["body"] = raw_body
    elif body is not None:
        event["body"] = json.dumps(body)
    return event


def _create_property(sub: str, name: str, address: str) -> dict:
    resp = handler(
        _event("POST", "/properties", sub=sub,
               body={"name": name, "address_text": address})
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _create_transaction(sub: str, property_id: str, **overrides) -> dict:
    body = {
        "date": "2023-06-15",
        "amount": "1250.50",
        "type": "expense",
        "category_id": "repairs",
    }
    body.update(overrides)
    resp = handler(
        _event("POST", f"/properties/{property_id}/transactions", sub=sub, body=body)
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _create_asset(sub: str, property_id: str, **overrides) -> dict:
    body = {
        "description": "HVAC system",
        "cost_basis": "27500.00",
        "placed_in_service_date": "2023-01-10",
    }
    body.update(overrides)
    resp = handler(
        _event("POST", f"/properties/{property_id}/assets", sub=sub, body=body)
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _seed_user(sub: str, *, prefix: str) -> dict:
    """Seed a property with a note, usage, an income + expense txn, and an asset.

    Returns the created identifiers so a test can assert on them.
    """
    prop = _create_property(sub, f"{prefix} Fourplex", f"{prefix} 100 Main St")
    handler(
        _event("PUT", f"/properties/{prop['id']}/notes", sub=sub,
               body={"text": f"{prefix} note"})
    )
    handler(
        _event("PUT", f"/properties/{prop['id']}/usage", sub=sub,
               body={"tax_year": 2023, "fair_rental_days": 300,
                     "personal_use_days": 10})
    )
    income = _create_transaction(
        sub, prop["id"], category_id="rents-received", type="income",
        amount="3000.00", date="2023-05-01",
    )
    expense = _create_transaction(sub, prop["id"], amount="450.75")
    asset = _create_asset(sub, prop["id"])
    return {
        "property_id": prop["id"],
        "income_id": income["id"],
        "expense_id": expense["id"],
        "asset_id": asset["id"],
    }


# --- store inspection helpers ------------------------------------------------


def _user_rows(repo: DynamoRepository, sub: str) -> list[dict]:
    """All rows in the user's ``USER#<sub>`` partition (property list rows, etc.)."""
    from logstead.repository import keys

    return repo.query(keys.user_pk(sub))


def _property_rows(repo: DynamoRepository, property_id: str) -> list[dict]:
    """All rows in a property's ``PROPERTY#<id>`` partition."""
    from logstead.repository import keys

    return repo.query(keys.property_scoped_pk(property_id))


# ============================================================================
# GET /backup
# ============================================================================


def test_get_backup_returns_exported_document(wired):
    """GET /backup → 200 with the authenticated user's exported document."""
    ids = _seed_user(USER_A, prefix="A")

    resp = handler(_event("GET", "/backup", sub=USER_A))
    assert resp["statusCode"] == 200, resp["body"]
    doc = json.loads(resp["body"])

    assert doc["schema_version"] == "1"
    assert doc["exported_at"]  # a timestamp is set
    assert len(doc["properties"]) == 1
    prop = doc["properties"][0]
    assert prop["id"] == ids["property_id"]
    assert prop["note"] == "A note"
    assert {t["id"] for t in prop["transactions"]} == {
        ids["income_id"], ids["expense_id"]
    }
    assert [a["id"] for a in prop["assets"]] == [ids["asset_id"]]
    # Money renders as a two-decimal string, never a float.
    amounts = {t["amount"] for t in prop["transactions"]}
    assert amounts == {"3000.00", "450.75"}
    assert all(isinstance(t["amount"], str) for t in prop["transactions"])


def test_get_backup_requires_auth(wired):
    """GET /backup is protected: no JWT claims → 401."""
    resp = handler(_event("GET", "/backup"))  # no sub
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# POST /backup/restore
# ============================================================================


def test_restore_valid_document_returns_200_summary(wired):
    """POST /backup/restore with a valid document → 200 with a restore summary."""
    # Export a seeded user's document, then restore it verbatim.
    _seed_user(USER_A, prefix="A")
    exported = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])

    resp = handler(_event("POST", "/backup/restore", sub=USER_A, body=exported))
    assert resp["statusCode"] == 200, resp["body"]
    summary = json.loads(resp["body"])
    assert summary["properties"] == 1
    assert summary["transactions"] == 2
    assert summary["assets"] == 1
    assert summary["usage_years"] == 1

    # The store still exports the same shape after the replace-all restore.
    re_exported = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])
    assert len(re_exported["properties"]) == 1


def test_restore_invalid_document_returns_400_with_field(wired):
    """An invalid document → 400 carrying the offending field + message; no mutation."""
    _seed_user(USER_A, prefix="A")
    before = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])

    # Unknown category_id on a transaction is a validation failure.
    bad_doc = {
        "schema_version": "1",
        "exported_at": "2025-01-01T00:00:00+00:00",
        "properties": [
            {
                "id": "p-1",
                "name": "Bad Property",
                "address_text": "1 Bad St",
                "transactions": [
                    {
                        "id": "t-1",
                        "property_id": "p-1",
                        "date": "2023-01-01",
                        "amount": "10.00",
                        "type": "expense",
                        "category_id": "not-a-real-category",
                    }
                ],
            }
        ],
    }
    resp = handler(_event("POST", "/backup/restore", sub=USER_A, body=bad_doc))
    assert resp["statusCode"] == 400, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "category_id"
    assert "not-a-real-category" in payload["message"]

    # Validation runs before any write: the existing data is untouched.
    after = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])
    assert after["properties"] == before["properties"]


def test_restore_missing_schema_version_returns_400(wired):
    """A document missing schema_version → 400 field=schema_version."""
    resp = handler(
        _event("POST", "/backup/restore", sub=USER_A, body={"properties": []})
    )
    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "schema_version"


def test_restore_malformed_json_body_returns_400(wired):
    """A present-but-malformed JSON body → 400 (router-owned)."""
    resp = handler(
        _event("POST", "/backup/restore", sub=USER_A, raw_body="{not valid json")
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation"


def test_restore_requires_auth(wired):
    """POST /backup/restore is protected: no JWT claims → 401."""
    resp = handler(_event("POST", "/backup/restore", body={"schema_version": "1",
                                                            "properties": []}))
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# POST /backup/clear
# ============================================================================


def test_clear_returns_200_summary_and_empties_store(wired, repo):
    """POST /backup/clear → 200 with a clear summary; the user's store is emptied."""
    ids = _seed_user(USER_A, prefix="A")

    resp = handler(_event("POST", "/backup/clear", sub=USER_A))
    assert resp["statusCode"] == 200, resp["body"]
    # The clear summary is a JSON object (counts / failed S3 keys).
    assert isinstance(json.loads(resp["body"]), dict)

    # No rows remain in the user or property partitions.
    assert _user_rows(repo, USER_A) == []
    assert _property_rows(repo, ids["property_id"]) == []

    # And an export now returns an empty document.
    exported = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])
    assert exported["properties"] == []


def test_clear_requires_auth(wired):
    """POST /backup/clear is protected: no JWT claims → 401."""
    resp = handler(_event("POST", "/backup/clear"))
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


# ============================================================================
# 503 path: no S3 bucket configured (files=None)
# ============================================================================


def test_restore_without_bucket_returns_503(repo):
    """Restore needs the S3 adapter; an unconfigured bucket → clean 503."""
    handler_module.configure(repo=repo)  # files=None
    resp = handler(
        _event("POST", "/backup/restore", sub=USER_A,
               body={"schema_version": "1", "properties": []})
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_clear_without_bucket_returns_503(repo):
    """Clear needs the S3 adapter; an unconfigured bucket → clean 503."""
    handler_module.configure(repo=repo)  # files=None
    resp = handler(_event("POST", "/backup/clear", sub=USER_A))
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


# ============================================================================
# Property 8: All operations are scoped to the authenticated user
# ============================================================================
# Feature: backup-restore, Property 8: All operations are scoped to the
# authenticated user
#
# Validates: Requirements 11.1, 11.2, 11.3
#
# For any two distinct users A and B with data, running export, restore, or
# clear as A never reads, returns, or mutates any row owned by B.


@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    # An operation to run as user A, plus a small dataset shape for both users.
    operation=st.sampled_from(["export", "clear", "restore"]),
    a_income=st.decimals(min_value=1, max_value=99999, places=2),
    b_income=st.decimals(min_value=1, max_value=99999, places=2),
    b_note=st.text(min_size=0, max_size=20).map(lambda s: s.strip()),
)
def test_property8_operations_scoped_to_authenticated_user(
    wired, repo, operation, a_income, b_income, b_note
):
    """Any backup operation as A never reads/returns/mutates B's rows."""
    # Fresh isolation per example: both users start from an empty store.
    handler(_event("POST", "/backup/clear", sub=USER_A))
    handler(_event("POST", "/backup/clear", sub=USER_B))

    # Seed B first and snapshot B's partitions so we can prove they are untouched.
    b_prop = _create_property(USER_B, "B Property", "B 200 Oak St")
    if b_note:
        handler(_event("PUT", f"/properties/{b_prop['id']}/notes", sub=USER_B,
                       body={"text": b_note}))
    b_txn = _create_transaction(
        USER_B, b_prop["id"], category_id="rents-received", type="income",
        amount=str(b_income), date="2022-04-01",
    )
    _create_asset(USER_B, b_prop["id"])

    b_user_rows_before = _user_rows(repo, USER_B)
    b_prop_rows_before = _property_rows(repo, b_prop["id"])
    assert b_user_rows_before  # sanity: B actually owns data

    # Seed A.
    a_prop = _create_property(USER_A, "A Property", "A 100 Main St")
    _create_transaction(
        USER_A, a_prop["id"], category_id="rents-received", type="income",
        amount=str(a_income), date="2023-05-01",
    )

    if operation == "export":
        exported = json.loads(handler(_event("GET", "/backup", sub=USER_A))["body"])
        exported_ids = {p["id"] for p in exported["properties"]}
        # A's export contains only A's property, never B's.
        assert b_prop["id"] not in exported_ids
        assert exported_ids == {a_prop["id"]}
    elif operation == "clear":
        resp = handler(_event("POST", "/backup/clear", sub=USER_A))
        assert resp["statusCode"] == 200, resp["body"]
        # A's own store is emptied.
        assert _user_rows(repo, USER_A) == []
    else:  # restore
        # Restore A with an independent single-property document.
        restore_doc = {
            "schema_version": "1",
            "exported_at": "2025-01-01T00:00:00+00:00",
            "properties": [
                {
                    "id": a_prop["id"],
                    "name": "A Restored",
                    "address_text": "A 100 Main St",
                    "transactions": [
                        {
                            "id": "a-restored-txn",
                            "property_id": a_prop["id"],
                            "date": "2023-07-01",
                            "amount": str(a_income),
                            "type": "expense",
                            "category_id": "repairs",
                        }
                    ],
                }
            ],
        }
        resp = handler(_event("POST", "/backup/restore", sub=USER_A, body=restore_doc))
        assert resp["statusCode"] == 200, resp["body"]

    # In every case, B's partitions are byte-for-byte unchanged.
    assert _user_rows(repo, USER_B) == b_user_rows_before
    assert _property_rows(repo, b_prop["id"]) == b_prop_rows_before
    # B's transaction row is specifically still present and readable by B.
    b_txn_resp = handler(
        _event("GET", f"/properties/{b_prop['id']}/transactions/{b_txn['id']}",
               sub=USER_B)
    )
    assert b_txn_resp["statusCode"] == 200
