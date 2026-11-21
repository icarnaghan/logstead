"""Task 4.1: cross-tenant authorization audit tests.

User A creates one of every resource type; user B (a different verified ``sub``)
then tries to read, write and delete each of them through the router using A's
real ids. For every route the response must be:

* ``404`` (never 403, never 200), and
* byte-identical to the response for an id that does not exist at all, so
  existence is not leaked, and
* A's data must be untouched afterwards.

Also covered: the user id comes only from the verified JWT claims (a ``user_id``
in the body/query is ignored), and ``POST /backup/restore`` refuses a document
that reuses another user's property id.

Runs against moto-backed DynamoDB (base table + GSI1 + GSI2) and S3. No live AWS.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.pdf_parse import ParsedLineItem
from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.result import Result
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler
from logstead.services.expense_import import ExpenseImportService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-xuser"
REGION = "us-east-1"
USER_A = "user-a-sub"
USER_B = "user-b-sub"


# --- fixtures ----------------------------------------------------------------


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": f"GSI{i}",
                    "KeySchema": [
                        {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                        {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for i in (1, 2)
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield ddb, s3


class _FakeTextract:
    def __init__(self) -> None:
        self.calls = 0

    def start_document_analysis(self, bucket: str, key: str) -> str:
        self.calls += 1
        return "tx-job"

    def get_document_analysis(self, job_id: str):  # pragma: no cover - never reached
        self.calls += 1
        raise AssertionError("Textract must not be reached for a foreign job")


@pytest.fixture
def env(aws):
    ddb, s3 = aws
    repo = DynamoRepository(ddb, TABLE_NAME)
    textract = _FakeTextract()
    handler_module.configure(
        repo=repo, files=S3FileAdapter(s3, BUCKET), textract=textract
    )
    yield repo, textract
    handler_module.reset_wiring()


def _call(sub, method, path, *, body=None, query=None):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    resp = handler(event)
    payload = json.loads(resp["body"]) if resp["body"] else None
    return resp["statusCode"], payload


def _ok(result, expected=(200, 201)):
    status, payload = result
    assert status in expected, (status, payload)
    return payload


@pytest.fixture
def a_data(env):
    """Create one of every resource type as user A; return their ids."""
    repo, _ = env
    prop = _ok(_call(USER_A, "POST", "/properties",
                     body={"name": "A House", "address_text": "1 A St"}))
    pid = prop["id"]
    txn = _ok(_call(USER_A, "POST", f"/properties/{pid}/transactions", body={
        "date": "2023-05-01", "amount": "100.00", "type": "expense",
        "category_id": "repairs"}))
    receipt = _ok(_call(USER_A, "POST",
                        f"/properties/{pid}/transactions/{txn['id']}/receipts",
                        body={"filename": "r.pdf", "content_type": "application/pdf"}))
    photo = _ok(_call(USER_A, "POST", f"/properties/{pid}/photos",
                      body={"filename": "p.png", "content_type": "image/png"}))
    asset = _ok(_call(USER_A, "POST", f"/properties/{pid}/assets", body={
        "description": "Roof", "cost_basis": "10000.00",
        "placed_in_service_date": "2023-01-10"}))
    loan = _ok(_call(USER_A, "POST", f"/properties/{pid}/loans", body={
        "description": "Mortgage", "annual_interest_rate": "6.5",
        "monthly_payment": "1500.00", "anchor_balance": "200000.00",
        "anchor_date": "2023-06-01", "original_principal": "250000.00"}))
    biz = _ok(_call(USER_A, "POST", "/businesses",
                    body={"legal_name": "A LLC", "entity_type": "llc"}))
    doc = _ok(_call(USER_A, "POST", f"/businesses/{biz['id']}/documents",
                    body={"filename": "d.pdf", "content_type": "application/pdf"}))
    job = _ok(_call(USER_A, "POST", "/imports/schedule-e/extractions",
                    body={"filename": "se.pdf", "content_type": "application/pdf"}))

    # Itemized entry and entered total (tax year 2022, so the 2023 repairs
    # transaction above is not an unmarked total for the same line-year).
    entry = _ok(_call(USER_A, "POST", f"/properties/{pid}/itemized/repairs/entries",
                      body={"date": "2022-03-04", "amount": "75.00",
                            "description": "Plumber", "notes": "inv 1"}))
    total = _ok(_call(USER_A, "PUT", f"/properties/{pid}/itemized/repairs/total",
                      body={"tax_year": 2022, "amount": "500.00"}))
    total_id = total["entered_total_rows"][0]["id"]
    entry_receipt = _ok(_call(USER_A, "POST",
                              f"/properties/{pid}/transactions/{entry['id']}/receipts",
                              body={"filename": "e.pdf", "content_type": "application/pdf"}))

    # Expense-import session for A's property (stub parser: no PDF stack).
    svc = ExpenseImportService(
        repo,
        parser=lambda _b: Result.success(
            [ParsedLineItem(date="2023-03-01", amount=Decimal("50.00"),
                            description="plumbing repair")]
        ),
    )
    session = svc.create_session(pid, 2023, pdf_bytes=b"%PDF-1.4 x").value
    draft = svc.list_drafts(session.id)[0]

    return {
        "propertyId": pid,
        "transactionId": txn["id"],
        "documentId": receipt["document"]["id"],
        "entryId": entry["id"],
        "totalId": total_id,
        "entryDocId": entry_receipt["document"]["id"],
        "photoId": photo["photo"]["id"],
        "assetId": asset["id"],
        "loanId": loan["id"],
        "businessId": biz["id"],
        "businessDocId": doc["document"]["id"],
        "jobId": job["job_id"],
        "sessionId": session.id,
        "draftId": draft.id,
    }


# --- route matrix ------------------------------------------------------------

_TXN_BODY = {"date": "2023-06-01", "amount": "9.99", "type": "expense",
             "category_id": "repairs"}
_ASSET_BODY = {"description": "Hijack", "cost_basis": "1.00",
               "placed_in_service_date": "2023-01-10"}
_LOAN_BODY = {"description": "Hijack", "annual_interest_rate": "5",
              "monthly_payment": "10.00", "anchor_balance": "1000.00",
              "anchor_date": "2023-06-01"}
_PROP = "/properties/{propertyId}"
_TXN = _PROP + "/transactions/{transactionId}"
_LOAN = _PROP + "/loans/{loanId}"
_BIZ = "/businesses/{businessId}"
_ITEM = _PROP + "/itemized/repairs"
_ENTRY_BODY = {"date": "2022-06-01", "amount": "9.99", "description": "Hijack"}

# (method, template, body, query)
ROUTES = [
    # Properties
    ("GET", _PROP, None, None),
    ("PUT", _PROP, {"name": "Hijacked", "address_text": "x"}, None),
    ("DELETE", _PROP, None, None),
    ("PUT", _PROP + "/usage",
     {"tax_year": 2023, "fair_rental_days": 1, "personal_use_days": 1}, None),
    ("GET", _PROP + "/usage", None, {"taxYear": 2023}),
    ("GET", _PROP + "/notes", None, None),
    ("PUT", _PROP + "/notes", {"text": "pwned"}, None),
    ("GET", _PROP + "/earliest-year", None, None),
    ("PUT", _PROP + "/business", {"business_id": None}, None),
    # Photos
    ("POST", _PROP + "/photos",
     {"filename": "x.png", "content_type": "image/png"}, None),
    ("GET", _PROP + "/photos", None, None),
    ("DELETE", _PROP + "/photos/{photoId}", None, None),
    ("PUT", _PROP + "/photos/{photoId}/cover", None, None),
    # Transactions (base table + GSI2 tax-year listing)
    ("POST", _PROP + "/transactions", _TXN_BODY, None),
    ("GET", _PROP + "/transactions", None, None),
    ("GET", _PROP + "/transactions", None, {"taxYear": 2023}),
    ("GET", _TXN, None, None),
    ("PUT", _TXN, _TXN_BODY, None),
    ("DELETE", _TXN, None, None),
    # Receipts
    ("POST", _TXN + "/receipts",
     {"filename": "x.pdf", "content_type": "application/pdf"}, None),
    ("GET", _TXN + "/receipts", None, None),
    ("DELETE", _TXN + "/receipts/{documentId}", None, None),
    # Itemized expenses (summary, entries, total) and the entry's receipts
    ("GET", _ITEM, None, {"taxYear": 2022}),
    ("POST", _ITEM + "/entries", _ENTRY_BODY, None),
    ("PUT", _ITEM + "/entries/{entryId}", _ENTRY_BODY, None),
    ("DELETE", _ITEM + "/entries/{entryId}", None, None),
    ("PUT", _ITEM + "/total", {"tax_year": 2022, "amount": "1.00"}, None),
    ("DELETE", _ITEM + "/total", None, {"taxYear": 2022}),
    ("POST", _PROP + "/transactions/{entryId}/receipts",
     {"filename": "x.pdf", "content_type": "application/pdf"}, None),
    ("GET", _PROP + "/transactions/{entryId}/receipts", None, None),
    ("DELETE", _PROP + "/transactions/{entryId}/receipts/{entryDocId}", None, None),
    ("GET", _PROP + "/transactions/{entryId}", None, None),
    ("PUT", _PROP + "/transactions/{totalId}", _TXN_BODY, None),
    ("DELETE", _PROP + "/transactions/{entryId}", None, None),
    # Assets
    ("POST", _PROP + "/assets", _ASSET_BODY, None),
    ("GET", _PROP + "/assets", None, None),
    ("GET", _PROP + "/assets/{assetId}", None, None),
    ("PUT", _PROP + "/assets/{assetId}", _ASSET_BODY, None),
    ("DELETE", _PROP + "/assets/{assetId}", None, None),
    ("GET", _PROP + "/assets/{assetId}/schedule", None, None),
    # Loans
    ("POST", _PROP + "/loans", _LOAN_BODY, None),
    ("GET", _PROP + "/loans", None, None),
    ("GET", _PROP + "/loans/line-12-impact", None, None),
    ("GET", _LOAN, None, None),
    ("PUT", _LOAN, _LOAN_BODY, None),
    ("DELETE", _LOAN, None, None),
    ("GET", _LOAN + "/schedule", None, None),
    ("PUT", _LOAN + "/interest-overrides/2023", {"interest": "1.00"}, None),
    ("DELETE", _LOAN + "/interest-overrides/2023", None, None),
    # Reports
    ("GET", _PROP + "/report", None, {"taxYear": 2023}),
    ("GET", "/reports/combined", None,
     {"taxYear": 2023, "propertyIds": "{propertyId}"}),
    # Expense imports (session -> property ownership)
    ("POST", "/imports", {"property_id": "{propertyId}", "tax_year": 2023,
                          "pdf_base64": "JVBERi0xLjQgeA=="}, None),
    ("GET", "/imports/{sessionId}", None, None),
    ("GET", "/imports/{sessionId}/drafts", None, None),
    ("PUT", "/imports/{sessionId}/drafts/{draftId}", {"amount": "1.00"}, None),
    ("DELETE", "/imports/{sessionId}/drafts/{draftId}", None, None),
    ("POST", "/imports/{sessionId}/confirm", None, None),
    # Schedule E import (layer 1) and extraction jobs (layer 2)
    ("DELETE", "/imports/schedule-e/{propertyId}/2023", None, None),
    ("POST", "/imports/schedule-e/extractions/{jobId}/start", None, None),
    ("GET", "/imports/schedule-e/extractions/{jobId}", None, None),
    # Year-end checklist (read-only)
    ("GET", _PROP + "/checklist", None, {"taxYear": 2023}),
    ("GET", _PROP + "/checklist", None, None),
    ("GET", _PROP + "/checklist/summary", None, None),
    # Global search filtered to a property
    ("GET", "/search", None, {"q": "oak", "propertyId": "{propertyId}"}),
    # Businesses
    ("GET", _BIZ, None, None),
    ("PUT", _BIZ, {"legal_name": "Hijacked", "entity_type": "llc"}, None),
    ("DELETE", _BIZ, None, None),
    ("POST", _BIZ + "/documents",
     {"filename": "x.pdf", "content_type": "application/pdf"}, None),
    ("GET", _BIZ + "/documents", None, None),
    ("DELETE", _BIZ + "/documents/{businessDocId}", None, None),
]


def _fill(value, ids):
    if isinstance(value, str):
        for k, v in ids.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _route_id(r):
    return f"{r[0]} {r[1]}" + (f"?{r[3]}" if r[3] else "")


@pytest.mark.parametrize("route", ROUTES, ids=_route_id)
def test_user_b_gets_404_indistinguishable_from_missing(env, a_data, route):
    method, template, body, query = route
    real = _call(USER_B, method, _fill(template, a_data),
                 body=_fill(body, a_data), query=_fill(query, a_data))
    ghost_ids = {k: str(uuid.uuid4()) for k in a_data}
    ghost = _call(USER_B, method, _fill(template, ghost_ids),
                  body=_fill(body, ghost_ids), query=_fill(query, ghost_ids))

    assert real[0] == 404, real
    assert real == ghost, (real, ghost)


def test_user_b_attempts_do_not_change_user_a_data(env, a_data):
    """Run every B attempt, then verify A's data is intact."""
    for method, template, body, query in ROUTES:
        _call(USER_B, method, _fill(template, a_data),
              body=_fill(body, a_data), query=_fill(query, a_data))

    pid = a_data["propertyId"]
    prop = _ok(_call(USER_A, "GET", f"/properties/{pid}"))
    assert prop["name"] == "A House"
    note = _ok(_call(USER_A, "GET", f"/properties/{pid}/notes"))
    assert note["text"] == ""
    assert len(_ok(_call(USER_A, "GET", f"/properties/{pid}/transactions"))) == 3
    summary = _ok(_call(USER_A, "GET", f"/properties/{pid}/itemized/repairs",
                        query={"taxYear": 2022}))
    assert summary["entered_total"] == "500.00"
    assert [e["id"] for e in summary["entries"]] == [a_data["entryId"]]
    assert summary["entries"][0]["amount"] == "75.00"
    assert summary["entries"][0]["description"] == "Plumber"
    assert len(_ok(_call(USER_A, "GET",
                         f"/properties/{pid}/transactions/{a_data['entryId']}/receipts"))) == 1
    txn = _ok(_call(USER_A, "GET",
                    f"/properties/{pid}/transactions/{a_data['transactionId']}"))
    assert txn["amount"] == "100.00"
    receipts = _ok(_call(USER_A, "GET",
                         f"/properties/{pid}/transactions/{a_data['transactionId']}/receipts"))
    assert len(receipts) == 1
    assert len(_ok(_call(USER_A, "GET", f"/properties/{pid}/photos"))) == 1
    assert len(_ok(_call(USER_A, "GET", f"/properties/{pid}/assets"))) == 1
    loans = _ok(_call(USER_A, "GET", f"/properties/{pid}/loans"))
    assert [item["id"] for item in loans] == [a_data["loanId"]]
    biz = _ok(_call(USER_A, "GET", f"/businesses/{a_data['businessId']}"))
    assert biz["legal_name"] == "A LLC"
    assert len(_ok(_call(USER_A, "GET",
                         f"/businesses/{a_data['businessId']}/documents"))) == 1
    drafts = _ok(_call(USER_A, "GET", f"/imports/{a_data['sessionId']}/drafts"))
    assert len(drafts) == 1 and drafts[0]["amount"] == "50.00"
    session = _ok(_call(USER_A, "GET", f"/imports/{a_data['sessionId']}"))
    assert session["status"] == "review"


def test_user_b_collection_reads_never_include_user_a_data(env, a_data):
    assert _ok(_call(USER_B, "GET", "/properties")) == []
    assert _ok(_call(USER_B, "GET", "/businesses")) == []
    portfolio = _ok(_call(USER_B, "GET", "/dashboard", query={"taxYear": 2023}))
    assert "A House" not in json.dumps(portfolio)
    per_prop = _ok(_call(USER_B, "GET", "/dashboard/properties", query={"taxYear": 2023}))
    assert per_prop == []
    assert "A House" not in json.dumps(_ok(_call(USER_B, "GET", "/dashboard/trends")))
    combined = _ok(_call(USER_B, "GET", "/reports/combined", query={"taxYear": 2023}))
    assert combined["properties"] == []
    backup = _ok(_call(USER_B, "GET", "/backup"))
    assert backup["properties"] == []


def test_user_id_comes_only_from_jwt_claims(env):
    """A user id smuggled in the body or query string is ignored."""
    created = _ok(_call(
        USER_B, "POST", "/properties",
        body={"name": "B House", "address_text": "2 B St",
              "user_id": USER_A, "userId": USER_A, "sub": USER_A},
        query={"userId": USER_A, "sub": USER_A},
    ))
    assert created["user_id"] == USER_B
    assert [p["id"] for p in _ok(_call(USER_B, "GET", "/properties",
                                       query={"userId": USER_A}))] == [created["id"]]
    assert _ok(_call(USER_A, "GET", "/properties")) == []


def test_unauthenticated_request_is_401(env, a_data):
    event = {"requestContext": {"http": {"method": "GET",
                                         "path": f"/properties/{a_data['propertyId']}/transactions"}}}
    assert handler(event)["statusCode"] == 401


def test_restore_refuses_to_take_over_another_users_property(env, a_data):
    pid = a_data["propertyId"]
    doc = _ok(_call(USER_A, "GET", "/backup"))

    status, payload = _call(USER_B, "POST", "/backup/restore", body=doc)
    assert status == 400, payload
    assert payload["field"] == "id"

    # A still owns the property and all of its data.
    assert _ok(_call(USER_A, "GET", f"/properties/{pid}"))["user_id"] == USER_A
    assert len(_ok(_call(USER_A, "GET", f"/properties/{pid}/transactions"))) == 3
    assert _call(USER_B, "GET", f"/properties/{pid}")[0] == 404
    assert _ok(_call(USER_B, "GET", "/properties")) == []


def test_restore_still_works_for_the_owner(env, a_data):
    doc = _ok(_call(USER_A, "GET", "/backup"))
    summary = _ok(_call(USER_A, "POST", "/backup/restore", body=doc))
    assert summary["properties"] == 1


def test_user_b_own_property_cannot_reach_a_entry_ids(env, a_data):
    """Requirement 13.3: an entry id from another property is just not found."""
    own = _ok(_call(USER_B, "POST", "/properties",
                    body={"name": "B House", "address_text": "2 B St"}))["id"]
    base = f"/properties/{own}/itemized/repairs"
    for method, suffix, body in [
        ("PUT", f"/entries/{a_data['entryId']}", _ENTRY_BODY),
        ("DELETE", f"/entries/{a_data['entryId']}", None),
    ]:
        real = _call(USER_B, method, base + suffix, body=body)
        ghost = _call(USER_B, method, base + suffix.replace(
            a_data["entryId"], str(uuid.uuid4())), body=body)
        assert real[0] == 404 and real == ghost, (real, ghost)
    # A's entry is still there.
    pid = a_data["propertyId"]
    summary = _ok(_call(USER_A, "GET", f"/properties/{pid}/itemized/repairs",
                        query={"taxYear": 2022}))
    assert summary["itemized_count"] == 1


class _CountingRepo:
    """Delegating proxy that records every repository call."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            self.calls.append(name)
            return attr(*args, **kwargs)

        return wrapper


@pytest.mark.parametrize("suffix,query", [
    ("/checklist", {"taxYear": 2023}),
    ("/checklist/summary", None),
])
def test_checklist_foreign_property_stops_after_ownership_check(
        env, a_data, aws, suffix, query):
    """Requirements 16.1-16.3: B's request for A's checklist is a 404 that
    reads exactly what a missing id reads (only the ownership check)."""
    ddb, s3 = aws
    counting = _CountingRepo(DynamoRepository(ddb, TABLE_NAME))
    handler_module.configure(
        repo=counting, files=S3FileAdapter(s3, BUCKET), textract=_FakeTextract()
    )
    real = _call(USER_B, "GET", f"/properties/{a_data['propertyId']}{suffix}",
                 query=query)
    real_calls = list(counting.calls)
    counting.calls.clear()
    ghost = _call(USER_B, "GET", f"/properties/{uuid.uuid4()}{suffix}", query=query)
    ghost_calls = list(counting.calls)

    assert real[0] == 404 and real == ghost, (real, ghost)
    assert real_calls == ghost_calls
    assert set(real_calls) <= {"get_item"}, real_calls


def test_user_b_dashboard_checklist_summary_omits_user_a_property(env, a_data):
    status, payload = _call(USER_B, "GET", "/checklist/summary",
                            query={"taxYear": 2023})
    assert status == 200, payload
    assert payload["properties"] == []
    assert "A House" not in json.dumps(payload)
    # Sanity: the same call for A does list the property.
    own = _ok(_call(USER_A, "GET", "/checklist/summary", query={"taxYear": 2023}))
    assert [p["property_id"] for p in own["properties"]] == [a_data["propertyId"]]


# --- accountant package + PDF routes (task 6.8) --------------------------------


class _RecordingFiles:
    """Delegating proxy over the S3 adapter that records every call."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            self.calls.append(name)
            return attr(*args, **kwargs)

        return wrapper


class _FakeInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def invoke(self, user_id: str, job_id: str) -> None:
        self.calls.append((user_id, job_id))


@pytest.fixture
def pkg_env(env, aws, a_data):
    """A has a property and a finished package job with an S3 object."""
    ddb, s3 = aws
    files = _RecordingFiles(S3FileAdapter(s3, BUCKET))
    invoker = _FakeInvoker()
    handler_module.configure(
        repo=DynamoRepository(ddb, TABLE_NAME), files=files, package_invoker=invoker
    )
    # B needs a property of their own so "all properties" is not the failure.
    _ok(_call(USER_B, "POST", "/properties",
              body={"name": "B House", "address_text": "2 B St"}))
    from logstead.repository import keys as _keys

    key = f"exports/packages/{USER_A}/jobA/logstead-accountant-package-2023.zip"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    DynamoRepository(ddb, TABLE_NAME).put_item({
        "PK": _keys.user_pk(USER_A), "SK": _keys.package_job_sk("jobA"),
        "userId": USER_A, "id": "jobA", "status": "complete", "taxYear": 2023,
        "propertyIds": [a_data["propertyId"]],
        "createdAt": "2099-01-01T00:00:00+00:00", "ttl": 4_102_444_800,
        "objectKey": key,
    })
    files.calls.clear()
    return files, invoker, s3, key


def _s3_keys(s3):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def test_package_get_and_delete_of_foreign_job_match_missing_id(pkg_env, aws):
    files, _, s3, key = pkg_env
    before = _s3_keys(s3)
    for method in ("GET", "DELETE"):
        real = _call(USER_B, method, "/accountant-packages/jobA")
        ghost = _call(USER_B, method, f"/accountant-packages/{uuid.uuid4()}")
        assert real[0] == 404 and real == ghost, (method, real, ghost)
    assert files.calls == []
    assert _s3_keys(s3) == before and key in before
    # A's job is untouched and still downloadable.
    mine = _ok(_call(USER_A, "GET", "/accountant-packages/jobA"))
    assert mine["status"] == "complete" and mine["download_url"]


def test_package_list_omits_foreign_jobs(pkg_env):
    assert _ok(_call(USER_B, "GET", "/accountant-packages")) == {"jobs": []}
    assert len(_ok(_call(USER_A, "GET", "/accountant-packages"))["jobs"]) == 1


def test_package_create_naming_foreign_property_matches_missing_id(pkg_env, a_data):
    files, invoker, s3, _ = pkg_env
    real = _call(USER_B, "POST", "/accountant-packages",
                 body={"tax_year": 2023, "property_ids": [a_data["propertyId"]]})
    ghost = _call(USER_B, "POST", "/accountant-packages",
                  body={"tax_year": 2023, "property_ids": [str(uuid.uuid4())]})
    assert real[0] == 404 and real == ghost, (real, ghost)
    assert invoker.calls == []
    assert files.calls == []
    assert _ok(_call(USER_B, "GET", "/accountant-packages")) == {"jobs": []}


@pytest.mark.parametrize("path,query", [
    ("/properties/{pid}/report/pdf", {"taxYear": 2023}),
    ("/reports/combined/pdf", {"taxYear": 2023, "propertyIds": "{pid}"}),
])
def test_pdf_routes_foreign_property_match_missing_id_and_write_nothing(
        pkg_env, a_data, path, query):
    files, _, s3, _ = pkg_env
    before = _s3_keys(s3)

    def go(pid):
        q = {k: (v.format(pid=pid) if isinstance(v, str) else v) for k, v in query.items()}
        return _call(USER_B, "POST", path.format(pid=pid), query=q)

    real = go(a_data["propertyId"])
    ghost = go(str(uuid.uuid4()))
    assert real[0] == 404 and real == ghost, (real, ghost)
    assert _s3_keys(s3) == before
    assert "put_object" not in files.calls
    assert "presigned_get_url" not in files.calls


# --- activity routes (task 9.9) -------------------------------------------------


@pytest.fixture
def a_deleted_txn(env, a_data):
    """A deletes a transaction; return (property id, restorable delete event)."""
    pid = a_data["propertyId"]
    txn = _ok(_call(USER_A, "POST", f"/properties/{pid}/transactions", body={
        "date": "2023-07-01", "amount": "42.00", "type": "expense",
        "category_id": "repairs"}))
    _ok(_call(USER_A, "DELETE", f"/properties/{pid}/transactions/{txn['id']}"),
        expected=(200, 204))
    events = _ok(_call(USER_A, "GET", "/activity", query={"action": "delete", "limit": 1}))["events"]
    assert events and events[0]["restorable"] is True
    return pid, events[0]


def test_user_b_activity_list_never_includes_user_a_events(env, a_data, a_deleted_txn):
    assert _ok(_call(USER_A, "GET", "/activity"))["events"]
    assert _ok(_call(USER_B, "GET", "/activity")) == {"events": [], "next_cursor": None}
    # With B's own property the global list still holds only B's events.
    _ok(_call(USER_B, "POST", "/properties", body={"name": "B House", "address_text": "2 B St"}))
    names = {e["property_name"] for e in _ok(_call(USER_B, "GET", "/activity"))["events"]}
    assert names == {"B House"}
    assert "A House" not in json.dumps(_call(USER_B, "GET", "/activity"))


def test_user_b_activity_for_a_property_matches_a_missing_id(env, a_data, a_deleted_txn):
    pid, _ = a_deleted_txn
    for path, query in [
        ("/activity", lambda p: {"propertyId": p}),
        ("/properties/{p}/activity", lambda p: None),
    ]:
        real = _call(USER_B, "GET", path.format(p=pid), query=query(pid))
        ghost_id = str(uuid.uuid4())
        ghost = _call(USER_B, "GET", path.format(p=ghost_id), query=query(ghost_id))
        assert real[0] == 404 and real == ghost, (path, real, ghost)
        assert real[1]["message"] == "Property not found."


def test_user_b_cannot_restore_a_event_and_nothing_is_created(env, a_data, a_deleted_txn):
    pid, event = a_deleted_txn
    path = f"/properties/{pid}/activity/{event['id']}/restore"
    real = _call(USER_B, "POST", path)
    ghost = _call(USER_B, "POST", f"/properties/{uuid.uuid4()}/activity/{event['id']}/restore")
    assert real[0] == 404 and real == ghost, (real, ghost)
    # B's own property cannot restore A's event id either.
    own = _ok(_call(USER_B, "POST", "/properties",
                    body={"name": "B House", "address_text": "2 B St"}))["id"]
    own_try = _call(USER_B, "POST", f"/properties/{own}/activity/{event['id']}/restore")
    unknown = _call(USER_B, "POST", f"/properties/{own}/activity/20240101000000.nothere/restore")
    assert own_try[0] == 404 and own_try == unknown, (own_try, unknown)
    assert _ok(_call(USER_B, "GET", f"/properties/{own}/transactions")) == []
    # A's event is still unclaimed and restorable by A.
    again = _ok(_call(USER_A, "GET", "/activity", query={"action": "delete", "limit": 1}))["events"][0]
    assert again["restored_at"] is None and again["restorable"] is True
    assert _call(USER_A, "POST", path)[0] == 200
