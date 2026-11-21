"""Task 7.5: handler/integration tests for the Schedule E PDF-extraction routes.

Drives the router end-to-end against a ``moto``-backed DynamoDB table
(base + GSI1 + GSI2) and S3 bucket, plus a **fake** ``TextractAdapter`` injected
via ``handler_module.configure(..., textract=fake)`` — **live Amazon Textract is
never called**. Requests are API Gateway HTTP API v2 proxy events carrying a
Cognito-claims stub, exactly like ``test_schedule_e_import_routes.py``.

Covered (design "Route surface + wiring" / "Error Handling"; Req 2.2, 2.4, 3.1,
3.4, 3.5, 3.6, 13.1, 13.2):

* ``POST /imports/schedule-e/extractions`` with a PDF content type → ``201``
  ``{job_id, upload_url}``; a non-PDF content type → ``400`` (``validation``,
  ``field="file"``).
* ``POST .../{jobId}/start`` → ``200`` ``processing`` once the object is in S3.
* ``GET .../{jobId}`` → ``200`` with the job view: a ``SUCCEEDED`` Textract
  result carrying Schedule E blocks → ``complete``/``draft``; ``FAILED`` →
  ``failed``.
* a job id not in the user's scope → ``404``.
* Textract unconfigured (``configure`` without ``textract``) → ``503``.

**Regression:** the extraction routes do not shadow the existing surfaces —
``/imports/{sessionId}`` still resolves to the expense ``ExpenseImport`` handler,
and ``/imports/schedule-e`` + ``/imports/schedule-e/{propertyId}/{taxYear}`` still
resolve to the layer-1 handlers (not the extraction handlers).
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.adapters.textract import TextractResult
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-se-extraction"
REGION = "us-east-1"
USER_SUB = "user-se-extract-1"
OTHER_SUB = "user-se-extract-2"
PDF_CONTENT_TYPE = "application/pdf"

_PARSER_FIXTURES = (
    Path(__file__).parent.parent / "services" / "fixtures" / "schedule_e_parser"
)


def _load_blocks(name: str) -> list[dict]:
    data = json.loads((_PARSER_FIXTURES / name).read_text())
    return data["blocks"]


# --- Fake Textract adapter ---------------------------------------------------


class FakeTextract:
    """In-memory stand-in for ``TextractAdapter`` (never touches AWS).

    ``start_document_analysis`` records the (bucket, key) and returns a canned
    job id; ``get_document_analysis`` returns the seeded :class:`TextractResult`.
    """

    def __init__(self, result: TextractResult | None = None) -> None:
        self.result = result
        self.start_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []
        self.job_id = "textract-job-1"

    def start_document_analysis(self, bucket: str, key: str) -> str:
        self.start_calls.append((bucket, key))
        return self.job_id

    def get_document_analysis(self, job_id: str) -> TextractResult:
        self.get_calls.append(job_id)
        assert self.result is not None, "no TextractResult seeded on the fake"
        return self.result


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
def s3_client(aws):
    _, s3 = aws
    return s3


@pytest.fixture
def s3_files(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


@pytest.fixture(autouse=True)
def _reset_wiring_after():
    yield
    handler_module.reset_wiring()


# --- event / request helpers -------------------------------------------------


def _event(method, path, *, claims=None, body=None, query=None):
    """Build an API Gateway HTTP API v2 proxy event."""
    event: dict = {
        "requestContext": {"http": {"method": method, "path": path}},
        "rawPath": path,
    }
    if claims is not None:
        event["requestContext"]["authorizer"] = {"jwt": {"claims": claims}}
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    return event


def _claims(sub: str = USER_SUB) -> dict:
    return {"sub": sub, "cognito:username": f"{sub}@example.com"}


def _create_property(name="Maple Duplex", address="12 Maple St", sub=USER_SUB) -> dict:
    """Create a property via the handler and return the parsed created body."""
    resp = handler(
        _event("POST", "/properties", claims=_claims(sub),
               body={"name": name, "address_text": address})
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])


def _put_pdf(s3_client, key: str, body: bytes = b"%PDF-1.7 minimal body") -> None:
    s3_client.put_object(
        Bucket=BUCKET, Key=key, Body=body, ContentType=PDF_CONTENT_TYPE
    )


def _start_job(repo, s3_files, textract) -> str:
    """Drive POST /imports/schedule-e/extractions and return the new job id."""
    handler_module.configure(repo=repo, files=s3_files, textract=textract)
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions", claims=_claims(),
               body={"filename": "2023-return.pdf", "content_type": PDF_CONTENT_TYPE})
    )
    assert resp["statusCode"] == 201, resp["body"]
    return json.loads(resp["body"])["job_id"]


def _uploaded_key(job_id: str) -> str:
    return f"imports/schedule-e/{USER_SUB}/{job_id}.pdf"


# ============================================================================
# POST /imports/schedule-e/extractions  (start_extraction → 201)
# ============================================================================


def test_start_extraction_pdf_201_with_job_id_and_upload_url(repo, s3_files):
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions", claims=_claims(),
               body={"filename": "2023.pdf", "content_type": PDF_CONTENT_TYPE})
    )
    assert resp["statusCode"] == 201, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["job_id"]
    assert payload["upload_url"].startswith("https://")
    assert BUCKET in payload["upload_url"]


def test_start_extraction_camelcase_content_type_tolerated(repo, s3_files):
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions", claims=_claims(),
               body={"filename": "x.pdf", "contentType": PDF_CONTENT_TYPE})
    )
    assert resp["statusCode"] == 201, resp["body"]
    assert json.loads(resp["body"])["job_id"]


def test_start_extraction_non_pdf_400_validation_field_file(repo, s3_files):
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions", claims=_claims(),
               body={"filename": "photo.png", "content_type": "image/png"})
    )
    assert resp["statusCode"] == 400, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "file"


def test_start_extraction_requires_auth(repo, s3_files):
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions",
               body={"filename": "x.pdf", "content_type": PDF_CONTENT_TYPE})
    )
    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "unauthorized"


def test_start_extraction_textract_unconfigured_503(repo, s3_files):
    # configure WITHOUT a textract collaborator → the route surfaces a clean 503.
    handler_module.configure(repo=repo, files=s3_files)
    resp = handler(
        _event("POST", "/imports/schedule-e/extractions", claims=_claims(),
               body={"filename": "x.pdf", "content_type": PDF_CONTENT_TYPE})
    )
    assert resp["statusCode"] == 503, resp["body"]
    assert json.loads(resp["body"])["error"] == "unavailable"


# ============================================================================
# POST /imports/schedule-e/extractions/{jobId}/start  (begin_extraction → 200)
# ============================================================================


def test_begin_extraction_200_processing_after_upload(repo, s3_files, s3_client):
    textract = FakeTextract()
    job_id = _start_job(repo, s3_files, textract)
    _put_pdf(s3_client, _uploaded_key(job_id))

    resp = handler(
        _event("POST", f"/imports/schedule-e/extractions/{job_id}/start",
               claims=_claims())
    )
    assert resp["statusCode"] == 200, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["job_id"] == job_id
    assert payload["status"] == "processing"
    assert textract.start_calls == [(BUCKET, _uploaded_key(job_id))]


def test_begin_extraction_absent_object_404_textract_never_called(repo, s3_files):
    textract = FakeTextract()
    job_id = _start_job(repo, s3_files, textract)
    # The browser never completed the upload → object absent.

    resp = handler(
        _event("POST", f"/imports/schedule-e/extractions/{job_id}/start",
               claims=_claims())
    )
    assert resp["statusCode"] == 404, resp["body"]
    assert json.loads(resp["body"])["error"] == "not_found"
    assert textract.start_calls == []


# ============================================================================
# GET /imports/schedule-e/extractions/{jobId}  (get_status → 200)
# ============================================================================


def test_get_extraction_succeeded_schedule_e_200_complete_draft(
    repo, s3_files, s3_client
):
    # Seed a property so the fuzzy matcher has a candidate to suggest.
    _create_property()
    blocks = _load_blocks("clean_two_columns.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    job_id = _start_job(repo, s3_files, textract)
    _put_pdf(s3_client, _uploaded_key(job_id))
    handler(
        _event("POST", f"/imports/schedule-e/extractions/{job_id}/start",
               claims=_claims())
    )

    resp = handler(
        _event("GET", f"/imports/schedule-e/extractions/{job_id}", claims=_claims())
    )
    assert resp["statusCode"] == 200, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["job_id"] == job_id
    assert payload["status"] == "complete"
    assert payload["outcome"] == "draft"
    draft = payload["review_draft"]
    assert draft is not None
    assert draft["tax_year"] == 2023
    assert len(draft["columns"]) == 2
    col_a = draft["columns"][0]
    lines = {ln["schedule_e_line"]: ln for ln in col_a["lines"]}
    # Money rendered as two-decimal strings.
    assert lines[3]["amount"] == "24000.00"
    # Line 18 (Depreciation) never appears.
    assert 18 not in lines
    # Fuzzy suggestion is attached (12 Maple Street ~ 12 Maple St), not applied.
    assert col_a["suggested_property_name"] == "Maple Duplex"


def test_get_extraction_no_schedule_e_200_complete_no_draft(
    repo, s3_files, s3_client
):
    blocks = _load_blocks("no_schedule_e.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    job_id = _start_job(repo, s3_files, textract)
    _put_pdf(s3_client, _uploaded_key(job_id))
    handler(
        _event("POST", f"/imports/schedule-e/extractions/{job_id}/start",
               claims=_claims())
    )

    resp = handler(
        _event("GET", f"/imports/schedule-e/extractions/{job_id}", claims=_claims())
    )
    # A negative outcome is still a successful 200 poll — the job ran.
    assert resp["statusCode"] == 200, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["status"] == "complete"
    assert payload["outcome"] == "no_schedule_e_found"
    assert payload["review_draft"] is None
    assert payload["message"]


def test_get_extraction_failed_200_status_failed(repo, s3_files, s3_client):
    textract = FakeTextract(
        TextractResult(status="FAILED", blocks=[], status_message="boom")
    )
    job_id = _start_job(repo, s3_files, textract)
    _put_pdf(s3_client, _uploaded_key(job_id))
    handler(
        _event("POST", f"/imports/schedule-e/extractions/{job_id}/start",
               claims=_claims())
    )

    resp = handler(
        _event("GET", f"/imports/schedule-e/extractions/{job_id}", claims=_claims())
    )
    # FAILED is a successful 200 poll whose body carries the negative outcome.
    assert resp["statusCode"] == 200, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["status"] == "failed"
    assert payload["message"] == "boom"
    assert payload["review_draft"] is None


def test_get_extraction_other_user_job_404(repo, s3_files, s3_client):
    blocks = _load_blocks("clean_two_columns.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    job_id = _start_job(repo, s3_files, textract)
    _put_pdf(s3_client, _uploaded_key(job_id))

    # A different user polling the same job id never resolves it (user-scoped key).
    resp = handler(
        _event("GET", f"/imports/schedule-e/extractions/{job_id}",
               claims=_claims(OTHER_SUB))
    )
    assert resp["statusCode"] == 404, resp["body"]
    assert json.loads(resp["body"])["error"] == "not_found"


def test_get_extraction_textract_unconfigured_503(repo, s3_files):
    handler_module.configure(repo=repo, files=s3_files)  # no textract
    resp = handler(
        _event("GET", "/imports/schedule-e/extractions/some-job", claims=_claims())
    )
    assert resp["statusCode"] == 503, resp["body"]
    assert json.loads(resp["body"])["error"] == "unavailable"


# ============================================================================
# Regression: extraction routes do not shadow the existing surfaces
# ============================================================================


def test_expense_import_session_route_still_resolves(repo, s3_files):
    """GET /imports/{sessionId} still dispatches to the expense (PDF) handler.

    A 2-segment GET for an unknown session resolves to the untouched
    ExpenseImportService handler → not_found, never the extraction handler.
    """
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(_event("GET", "/imports/some-session-id", claims=_claims()))
    assert resp["statusCode"] == 404
    assert json.loads(resp["body"])["error"] == "not_found"


def test_layer1_confirm_route_not_shadowed(repo, s3_files):
    """POST /imports/schedule-e still resolves to the layer-1 confirm handler.

    The 2-segment POST reaches ``_import_schedule_e``; an empty submission is a
    layer-1 validation (field=tax_year), proving it is NOT the 3-segment
    extraction start handler (which would 201 on a PDF body or 400 field=file).
    """
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("POST", "/imports/schedule-e", claims=_claims(),
               body={"entries": []})
    )
    assert resp["statusCode"] == 400, resp["body"]
    payload = json.loads(resp["body"])
    assert payload["error"] == "validation"
    assert payload["field"] == "tax_year"


def test_layer1_undo_route_not_shadowed_by_extraction_get(repo, s3_files):
    """DELETE /imports/schedule-e/{propertyId}/{taxYear} resolves to layer-1 undo.

    This 4-segment DELETE shares its segment count with the 4-segment extraction
    GET; the method (DELETE vs GET) and the literal ``extractions`` 3rd segment
    keep them distinct. An unknown property → not_found from the layer-1 undo
    handler (not a 400 from any extraction path, not an unknown-route 404).
    """
    handler_module.configure(repo=repo, files=s3_files, textract=FakeTextract())
    resp = handler(
        _event("DELETE", "/imports/schedule-e/unknown-prop/2023", claims=_claims())
    )
    assert resp["statusCode"] == 404, resp["body"]
    assert json.loads(resp["body"])["error"] == "not_found"
