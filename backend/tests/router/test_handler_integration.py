"""Task 16.2: router dispatch and error-mapping integration suite.

A fuller companion to ``test_handler_smoke.py`` (task 16.1). Where the smoke
test proves the wiring works end-to-end for a handful of representative calls,
this suite exercises the router as an integration boundary against a
``moto``-backed DynamoDB table (base + GSI1 + GSI2) and S3 bucket wired via
``handler_module.configure(...)``:

* **Dispatch** — a representative request for *each* resource area reaches its
  service and comes back with the right shape and status code (properties,
  transactions, assets/schedules, reports, dashboard, categories,
  per-property dashboard).
* **Error mapping** — every :class:`Result` error ``kind`` maps to its HTTP
  status: validation → 400 (with ``field``), not_found → 404, conflict → 409,
  unauthorized → 401, and router-owned shapes: unknown route → 404, malformed
  JSON body → 400, an unconfigured adapter → 503.
* **Money serialization** — created money renders as a **string** in the JSON
  body, never a float.
* **Path templating** — nested templates dispatch correctly and
  ``/properties/enrich`` is not swallowed by ``/properties/{propertyId}``.

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
from logstead.services.category import seed_categories

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-integration"
REGION = "us-east-1"
USER_SUB = "user-integration-1"


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
    query: dict | None = None,
    raw_body: str | None = None,
):
    """Build an API Gateway HTTP API v2 proxy event.

    Args:
        method: HTTP method (e.g. ``"GET"``).
        path: Request path (e.g. ``"/properties"``).
        claims: JWT claims to place on the request context; ``None`` means an
            unauthenticated request (no ``authorizer`` block at all).
        body: A dict/list serialized to a JSON body.
        query: Query-string parameters.
        raw_body: A raw (possibly malformed) body string, used to exercise the
            bad-JSON path; takes precedence over ``body``.
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
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    return event


def _claims() -> dict:
    return {"sub": USER_SUB, "cognito:username": "integration@example.com"}


def _create_property(name: str = "Cedar Fourplex", address: str = "500 Cedar Ave") -> dict:
    """Create a property via the handler and return the parsed created body."""
    resp = handler(
        _event("POST", "/properties", claims=_claims(),
               body={"name": name, "address_text": address})
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _create_transaction(property_id: str, **overrides) -> dict:
    """Create an expense transaction under a property; return the parsed body."""
    body = {
        "date": "2023-06-15",
        "amount": "1250.50",
        "type": "expense",
        "category_id": "repairs",
    }
    body.update(overrides)
    resp = handler(
        _event("POST", f"/properties/{property_id}/transactions",
               claims=_claims(), body=body)
    )
    return resp


def _create_asset(property_id: str, **overrides) -> dict:
    """Create a depreciable asset under a property; return the raw response."""
    body = {
        "description": "HVAC system",
        "cost_basis": "27500.00",
        "placed_in_service_date": "2023-01-10",
    }
    body.update(overrides)
    return handler(
        _event("POST", f"/properties/{property_id}/assets",
               claims=_claims(), body=body)
    )


# ============================================================================
# Dispatch: each resource area reaches its service with the right status/shape
# ============================================================================


def test_dispatch_create_property_then_list(wired):
    """POST /properties (201) then GET /properties lists the created property."""
    created = _create_property()
    assert created["user_id"] == USER_SUB

    resp = handler(_event("GET", "/properties", claims=_claims()))
    assert resp["statusCode"] == 200
    listed = json.loads(resp["body"])
    assert isinstance(listed, list)
    assert [p["id"] for p in listed] == [created["id"]]


def test_dispatch_get_single_property(wired):
    """GET /properties/{id} dispatches to the property service and returns it."""
    created = _create_property()
    resp = handler(
        _event("GET", f"/properties/{created['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["id"] == created["id"]


def test_dispatch_create_transaction_then_list(wired):
    """POST a transaction (201) then GET the property's transaction list (200)."""
    prop = _create_property()
    create_resp = _create_transaction(prop["id"])
    assert create_resp["statusCode"] == 201
    txn = json.loads(create_resp["body"])
    assert txn["schedule_e_line"] == 14  # repairs → Line 14

    list_resp = handler(
        _event("GET", f"/properties/{prop['id']}/transactions", claims=_claims())
    )
    assert list_resp["statusCode"] == 200
    txns = json.loads(list_resp["body"])
    assert [t["id"] for t in txns] == [txn["id"]]


def test_dispatch_create_asset_then_get_schedule(wired):
    """POST an asset (201) then GET its depreciation schedule (200)."""
    prop = _create_property()
    create_resp = _create_asset(prop["id"])
    assert create_resp["statusCode"] == 201
    asset = json.loads(create_resp["body"])

    sched_resp = handler(
        _event("GET", f"/properties/{prop['id']}/assets/{asset['id']}/schedule",
               claims=_claims())
    )
    assert sched_resp["statusCode"] == 200
    schedule = json.loads(sched_resp["body"])
    assert isinstance(schedule, list)
    assert len(schedule) > 0
    # Rows carry the year-by-year amount and remaining basis.
    assert {"tax_year", "amount", "remaining_basis"} <= set(schedule[0])


def test_dispatch_list_assets(wired):
    """GET /properties/{id}/assets returns the asset list (200)."""
    prop = _create_property()
    asset = json.loads(_create_asset(prop["id"])["body"])

    resp = handler(
        _event("GET", f"/properties/{prop['id']}/assets", claims=_claims())
    )
    assert resp["statusCode"] == 200
    assets = json.loads(resp["body"])
    assert [a["id"] for a in assets] == [asset["id"]]


def test_dispatch_property_report(wired):
    """GET /properties/{id}/report?taxYear=... returns a Schedule E report (200)."""
    prop = _create_property()
    _create_transaction(prop["id"], category_id="rents-received",
                        type="income", amount="3000.00", date="2023-05-01")

    resp = handler(
        _event("GET", f"/properties/{prop['id']}/report",
               claims=_claims(), query={"taxYear": 2023})
    )
    assert resp["statusCode"] == 200
    report = json.loads(resp["body"])
    assert report["header"]["property_id"] == prop["id"]
    assert report["header"]["tax_year"] == 2023
    assert "lines" in report and "totals" in report


def test_dispatch_report_reflects_usage_days(wired):
    """The report header reflects usage days set via PUT /properties/{id}/usage."""
    prop = _create_property()
    usage_resp = handler(
        _event("PUT", f"/properties/{prop['id']}/usage", claims=_claims(),
               body={"tax_year": 2023, "fair_rental_days": 300,
                     "personal_use_days": 15})
    )
    assert usage_resp["statusCode"] == 200

    resp = handler(
        _event("GET", f"/properties/{prop['id']}/report",
               claims=_claims(), query={"taxYear": 2023})
    )
    header = json.loads(resp["body"])["header"]
    assert header["fair_rental_days"] == 300
    assert header["personal_use_days"] == 15


def test_dispatch_dashboard_portfolio(wired):
    """GET /dashboard returns the numeric portfolio summary (200)."""
    prop = _create_property()
    _create_transaction(prop["id"], category_id="rents-received",
                        type="income", amount="5000.00", date="2023-04-01")

    resp = handler(
        _event("GET", "/dashboard", claims=_claims(), query={"taxYear": 2023})
    )
    assert resp["statusCode"] == 200
    summary = json.loads(resp["body"])
    assert summary["tax_year"] == 2023
    assert summary["has_properties"] is True
    assert len(summary["properties"]) == 1


def test_dispatch_dashboard_per_property(wired):
    """GET /dashboard/properties returns the per-property summary list (200)."""
    prop = _create_property()

    resp = handler(
        _event("GET", "/dashboard/properties", claims=_claims(),
               query={"taxYear": 2023})
    )
    assert resp["statusCode"] == 200
    summaries = json.loads(resp["body"])
    assert isinstance(summaries, list)
    assert [s["property_id"] for s in summaries] == [prop["id"]]


def test_dispatch_categories_public_no_claims(wired):
    """GET /categories is public: it dispatches with no JWT claims (200)."""
    seed_categories(wired)
    resp = handler(_event("GET", "/categories"))  # no claims
    assert resp["statusCode"] == 200
    catalog = json.loads(resp["body"])
    lines = {c["schedule_e_line"] for c in catalog}
    assert {3, 4, 19} <= lines
    assert 18 not in lines


# ============================================================================
# Error mapping
# ============================================================================


def test_validation_blank_property_name_400_with_field(wired):
    """Validation error → 400 with the offending ``field`` (blank name)."""
    resp = handler(
        _event("POST", "/properties", claims=_claims(),
               body={"name": "   ", "address_text": "1 Main St"})
    )
    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "name"


def test_validation_nonpositive_amount_400_with_field(wired):
    """Transaction amount <= 0 → 400 with ``field: amount``."""
    prop = _create_property()
    resp = _create_transaction(prop["id"], amount="0.00")
    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "amount"


def test_validation_other_without_description_400_with_field(wired):
    """The Other category (Line 19) without a description → 400 field=description."""
    prop = _create_property()
    resp = _create_transaction(prop["id"], category_id="other", description="")
    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "description"


def test_validation_nonpositive_cost_basis_400_with_field(wired):
    """Asset cost basis <= 0 → 400 with ``field: cost_basis``."""
    prop = _create_property()
    resp = _create_asset(prop["id"], cost_basis="0.00")
    assert resp["statusCode"] == 400
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "cost_basis"


def test_not_found_missing_property_404(wired):
    """GET a property that does not exist → 404."""
    resp = handler(
        _event("GET", "/properties/does-not-exist", claims=_claims())
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_not_found_missing_transaction_404(wired):
    """GET a transaction that does not exist → 404."""
    prop = _create_property()
    resp = handler(
        _event("GET", f"/properties/{prop['id']}/transactions/missing-txn",
               claims=_claims())
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_not_found_missing_asset_404(wired):
    """GET an asset that does not exist → 404."""
    prop = _create_property()
    resp = handler(
        _event("GET", f"/properties/{prop['id']}/assets/missing-asset",
               claims=_claims())
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_not_found_report_unknown_property_404(wired):
    """A report for an unknown property → 404 (propagated from the service)."""
    resp = handler(
        _event("GET", "/properties/unknown/report",
               claims=_claims(), query={"taxYear": 2023})
    )
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_conflict_delete_property_with_transaction_409(wired):
    """Deleting a property that still has a transaction → 409 conflict."""
    prop = _create_property()
    assert _create_transaction(prop["id"])["statusCode"] == 201

    resp = handler(
        _event("DELETE", f"/properties/{prop['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["error"] == "conflict"


def test_unauthorized_protected_route_without_claims_401(wired):
    """A protected route hit without JWT claims → 401 unauthorized."""
    resp = handler(_event("GET", "/properties"))  # no claims
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


def test_unknown_route_404(wired):
    """A path matching no route → 404 (router-owned)."""
    resp = handler(_event("GET", "/no/such/route", claims=_claims()))
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_malformed_json_body_400(wired):
    """A present-but-malformed JSON body → 400 (router-owned)."""
    resp = handler(
        _event("POST", "/properties", claims=_claims(),
               raw_body="{not valid json")
    )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "validation"


def test_unconfigured_files_adapter_returns_503(repo):
    """A route needing the (unconfigured) S3 adapter degrades to 503.

    Photos require the file adapter; wiring here provides only the repo, so the
    router surfaces a clean 503 rather than crashing.
    """
    handler_module.configure(repo=repo)  # files=None
    prop = _create_property()

    resp = handler(
        _event("POST", f"/properties/{prop['id']}/photos", claims=_claims(),
               body={"filename": "front.jpg", "content_type": "image/jpeg"})
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_unconfigured_enrichment_adapter_returns_503(repo):
    """Enrichment needs rentcast + autocomplete; unconfigured → 503."""
    handler_module.configure(repo=repo)  # rentcast/autocomplete=None

    resp = handler(
        _event("POST", "/properties/enrich", claims=_claims(),
               body={"address": "1 Market St"})
    )
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


# ============================================================================
# Money serialization: money renders as a string, never a float
# ============================================================================


def test_transaction_money_serialized_as_string(wired):
    """A created transaction renders ``amount`` as a two-decimal string."""
    prop = _create_property()
    resp = _create_transaction(prop["id"], amount="1250.50")
    assert resp["statusCode"] == 201

    # Parse without float coercion so we can inspect the raw JSON type.
    payload = json.loads(resp["body"])
    assert payload["amount"] == "1250.50"
    assert isinstance(payload["amount"], str)
    # And it is literally a string in the raw body (quoted), not a bare number.
    assert '"amount": "1250.50"' in resp["body"]


def test_asset_money_serialized_as_string(wired):
    """A created asset renders ``cost_basis`` as a string, not a float."""
    prop = _create_property()
    resp = _create_asset(prop["id"], cost_basis="27500.00")
    assert resp["statusCode"] == 201

    payload = json.loads(resp["body"])
    assert isinstance(payload["cost_basis"], str)
    assert payload["cost_basis"] == "27500.00"
    # recovery_period_years (27.5) is also a decimal string, never a float.
    assert isinstance(payload["recovery_period_years"], str)


# ============================================================================
# Path templating
# ============================================================================


def test_nested_receipt_path_dispatches(wired):
    """`.../transactions/{txnId}/receipts` dispatches to the receipt handler."""
    prop = _create_property()
    txn = json.loads(_create_transaction(prop["id"])["body"])

    # Attach a receipt (uses the deepest nested template with the file adapter).
    attach = handler(
        _event("POST",
               f"/properties/{prop['id']}/transactions/{txn['id']}/receipts",
               claims=_claims(),
               body={"filename": "receipt.pdf", "content_type": "application/pdf"})
    )
    assert attach["statusCode"] == 201

    # Listing the same nested path returns the receipt (correct dispatch).
    listing = handler(
        _event("GET",
               f"/properties/{prop['id']}/transactions/{txn['id']}/receipts",
               claims=_claims())
    )
    assert listing["statusCode"] == 200
    receipts = json.loads(listing["body"])
    assert isinstance(receipts, list)
    assert len(receipts) == 1


def test_delete_receipt_deepest_template_dispatches(wired):
    """`.../receipts/{documentId}` (deepest template) dispatches to delete."""
    prop = _create_property()
    txn = json.loads(_create_transaction(prop["id"])["body"])
    attach = json.loads(
        handler(
            _event("POST",
                   f"/properties/{prop['id']}/transactions/{txn['id']}/receipts",
                   claims=_claims(),
                   body={"filename": "r.pdf", "content_type": "application/pdf"})
        )["body"]
    )

    doc_id = attach["document"]["id"]
    resp = handler(
        _event("DELETE",
               f"/properties/{prop['id']}/transactions/{txn['id']}/receipts/{doc_id}",
               claims=_claims())
    )
    assert resp["statusCode"] == 200


def test_enrich_not_captured_by_property_id_template(repo):
    """`/properties/enrich` matches the enrich route, not `/properties/{id}`.

    Enrichment has no adapter configured here, so a correct dispatch surfaces
    503 (the enrich handler) — a *200/404 property body* would prove the literal
    ``enrich`` segment was wrongly captured as a ``{propertyId}``.
    """
    handler_module.configure(repo=repo)  # no enrichment adapters

    resp = handler(
        _event("POST", "/properties/enrich", claims=_claims(),
               body={"address": "742 Evergreen Terrace"})
    )
    # 503 from the enrich handler (adapter unconfigured), NOT a property result.
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "unavailable"


def test_get_property_by_id_still_matches_after_enrich_route(wired):
    """A real `GET /properties/{id}` still resolves (enrich route doesn't shadow it)."""
    prop = _create_property()
    resp = handler(
        _event("GET", f"/properties/{prop['id']}", claims=_claims())
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["id"] == prop["id"]


# --- GET /addresses/units (secondary/unit addresses) -------------------------


class _StubAutocomplete:
    """Autocomplete adapter stub returning fixed suggestion / unit lists."""

    def __init__(self, units=None):
        self._units = units or []
        self.unit_calls: list[str] = []

    def suggestions(self, query):
        return []

    def secondary_addresses(self, address):
        self.unit_calls.append(address)
        return self._units


class _StubRentCast:
    """RentCast adapter stub (unused by the units route)."""

    def get_property_record(self, address):  # pragma: no cover - not exercised
        from logstead.models.result import Result

        return Result.success(None)


def test_units_route_returns_secondary_addresses(repo):
    """GET /addresses/units returns the building's units via the enrichment service."""
    from logstead.models.property import AddressSuggestion

    units = [
        AddressSuggestion(
            formatted_address="123 Main St Unit 101, Springfield, IL 62704",
            provider_place_id="u101",
        ),
        AddressSuggestion(
            formatted_address="123 Main St Unit 102, Springfield, IL 62704",
            provider_place_id="u102",
        ),
    ]
    autocomplete = _StubAutocomplete(units=units)
    handler_module.configure(repo=repo, rentcast=_StubRentCast(), autocomplete=autocomplete)

    resp = handler(
        _event(
            "GET",
            "/addresses/units",
            claims=_claims(),
            query={"address": "123 Main St, Springfield, IL 62704"},
        )
    )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert [u["formatted_address"] for u in body] == [
        "123 Main St Unit 101, Springfield, IL 62704",
        "123 Main St Unit 102, Springfield, IL 62704",
    ]
    assert autocomplete.unit_calls == ["123 Main St, Springfield, IL 62704"]


def test_units_route_accepts_q_alias(repo):
    """GET /addresses/units also reads the ``q`` query param."""
    autocomplete = _StubAutocomplete(units=[])
    handler_module.configure(repo=repo, rentcast=_StubRentCast(), autocomplete=autocomplete)

    resp = handler(
        _event("GET", "/addresses/units", claims=_claims(), query={"q": "1 Main St"})
    )

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == []
    assert autocomplete.unit_calls == ["1 Main St"]


def test_units_route_requires_auth(repo):
    """GET /addresses/units is protected: no JWT claims → 401."""
    handler_module.configure(repo=repo, rentcast=_StubRentCast(), autocomplete=_StubAutocomplete())

    resp = handler(_event("GET", "/addresses/units", query={"address": "1 Main St"}))

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


def test_property_notes_get_set_round_trip(wired):
    """GET /notes defaults empty; PUT stores; GET returns the saved text."""
    prop = _create_property()

    got = handler(_event("GET", f"/properties/{prop['id']}/notes", claims=_claims()))
    assert got["statusCode"] == 200
    assert json.loads(got["body"]) == {"text": ""}

    put = handler(
        _event("PUT", f"/properties/{prop['id']}/notes", claims=_claims(),
               body={"text": "  Roof replaced 2024; tenant month-to-month.  "})
    )
    assert put["statusCode"] == 200
    assert json.loads(put["body"]) == {
        "text": "Roof replaced 2024; tenant month-to-month."
    }

    got2 = handler(_event("GET", f"/properties/{prop['id']}/notes", claims=_claims()))
    assert json.loads(got2["body"])["text"] == "Roof replaced 2024; tenant month-to-month."


def test_property_notes_unknown_property_404(wired):
    resp = handler(_event("GET", "/properties/nope/notes", claims=_claims()))
    assert resp["statusCode"] == 404


def test_property_notes_requires_auth(wired):
    resp = handler(_event("GET", "/properties/any/notes"))  # no claims
    assert resp["statusCode"] == 401
