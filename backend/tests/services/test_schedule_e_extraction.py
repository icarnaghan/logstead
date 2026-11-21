"""Unit tests for the Schedule E PDF ExtractionService (tasks 6.2/6.4/6.6/6.8/6.10).

Exercises the service against a ``moto``-backed DynamoDB table and S3 bucket plus
a **fake** ``TextractAdapter`` — **live Amazon Textract is never called**. The
fake records its calls and returns canned ``TextractResult`` values built from
the same hand-built Textract block fixtures the pure parser's tests use
(``tests/services/fixtures/schedule_e_parser/``), so the service's parse-and-cache
path runs against realistic block shapes without AWS.

Coverage by task:

* 6.2 — job persistence round-trip (incl. a cached ``ReviewDraft`` with money
  strings + a ``ttl``) under ``USER#<user> / SEEXTRACT#<jobId>`` keys.
* 6.4 — ``start_extraction``: PDF → ``pending`` job + presigned URL under
  ``imports/schedule-e/<user>/``; non-PDF → ``validation(field="file")``,
  no job, no URL.
* 6.6 — ``begin_extraction``: absent/other-user object → ``not_found`` with
  Textract never called; non-PDF object → ``failed`` + "valid PDF" + object
  deleted; valid PDF → ``processing`` + ``textractJobId`` set.
* 6.8 — ``get_status``: IN_PROGRESS→processing; FAILED→failed+message+PDF
  deleted; SUCCEEDED+Schedule-E→complete/draft (money normalized, suggestions
  attached); SUCCEEDED+no-Schedule-E→complete/no_schedule_e_found no draft;
  parse-and-cache runs once (later polls return the cached draft without
  re-calling Textract); a job not in the user's scope → ``not_found``.
* 6.10 — terminal-state PDF deletion: the uploaded object is absent from S3 after
  ``complete`` (draft + no-SE) and after ``failed``, and no transaction/Property
  rows change across any outcome.
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.adapters.textract import TextractResult
from logstead.models.property import PropertyInput
from logstead.models.schedule_e_extraction import (
    ExtractedColumn,
    ExtractedLine,
    ReviewDraft,
)
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService
from logstead.services.schedule_e_extraction import (
    DEFAULT_MIN_CONFIDENCE,
    PDF_CONTENT_TYPE,
    ExtractionService,
    _deserialize_review_draft,
    _serialize_review_draft,
)

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-aaa"
USER_B = "user-bbb"

_PARSER_FIXTURES = Path(__file__).parent / "fixtures" / "schedule_e_parser"


def _load_blocks(name: str) -> list[dict]:
    data = json.loads((_PARSER_FIXTURES / name).read_text())
    return data["blocks"]


# --- Fake Textract adapter ---------------------------------------------------


class FakeTextract:
    """An in-memory stand-in for ``TextractAdapter`` (never touches AWS).

    ``start_document_analysis`` records the (bucket, key) it was handed and
    returns a canned job id; ``get_document_analysis`` returns the pre-seeded
    :class:`TextractResult`. Both call counts are recorded so tests can assert
    Textract is never called on the not-found path and that a terminal poll does
    not re-call it.
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


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
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
def files(s3_client):
    return S3FileAdapter(s3_client, BUCKET)


def _service(repo, files, textract, user=USER_A):
    return ExtractionService(repo, user, files=files, textract=textract)


def _put_pdf(s3_client, key: str, body: bytes = b"%PDF-1.7 minimal body") -> None:
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=PDF_CONTENT_TYPE)


def _object_exists(s3_client, key: str) -> bool:
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    return any(obj["Key"] == key for obj in contents)


def _raw_job(repo, user: str, job_id: str):
    return repo.get_item(keys.user_pk(user), keys.extraction_job_sk(job_id))


# --- 6.2 Job persistence round-trip ------------------------------------------


def test_review_draft_serialize_roundtrip_preserves_money_strings():
    draft = ReviewDraft(
        tax_year=2023,
        tax_year_needs_verification=False,
        columns=[
            ExtractedColumn(
                address_text="12 Maple Street",
                address_confidence=96.4,
                suggested_property_id="prop-1",
                suggested_property_name="Maple Duplex",
                mapping_confidence=0.86,
                lines=[
                    ExtractedLine(3, "24000.00", False, 98.3),
                    ExtractedLine(14, "1875.50", True, 42.0),
                    ExtractedLine(19, "0.00", True, None),
                ],
            )
        ],
    )
    restored = _deserialize_review_draft(_serialize_review_draft(draft))
    assert restored == draft
    # Money survives as the exact two-decimal strings.
    assert restored.columns[0].lines[0].amount == "24000.00"
    assert restored.columns[0].lines[2].amount == "0.00"


def test_job_with_cached_draft_and_ttl_roundtrips_under_seextract_keys(
    repo, files
):
    textract = FakeTextract()
    service = _service(repo, files, textract)

    draft = ReviewDraft(
        tax_year=2022,
        tax_year_needs_verification=True,
        columns=[
            ExtractedColumn(
                address_text="90 Oak Avenue",
                address_confidence=95.9,
                suggested_property_id=None,
                suggested_property_name=None,
                mapping_confidence=None,
                lines=[ExtractedLine(3, "18500.00", False, 97.6)],
            )
        ],
    )
    job = {
        "id": "job-xyz",
        "status": "complete",
        "outcome": "draft",
        "uploadedKey": "imports/schedule-e/user-aaa/job-xyz.pdf",
        "textractJobId": "tx-1",
        "message": None,
        "reviewDraftJson": _serialize_review_draft(draft),
        "createdAt": "2024-01-01T00:00:00+00:00",
        "ttl": 1_900_000_000,
    }
    service._put_job(job)

    stored = _raw_job(repo, USER_A, "job-xyz")
    assert stored is not None
    assert stored["PK"] == keys.user_pk(USER_A)
    assert stored["SK"] == keys.extraction_job_sk("job-xyz")
    assert stored["userId"] == USER_A
    assert stored["status"] == "complete"
    assert stored["outcome"] == "draft"
    assert int(stored["ttl"]) == 1_900_000_000

    loaded = service._load_job("job-xyz")
    assert loaded is not None
    view = service._view(loaded)
    assert view.review_draft == draft


def test_load_job_scoped_to_user_returns_none_for_other_user(repo, files):
    textract = FakeTextract()
    service_a = _service(repo, files, textract, user=USER_A)
    service_a._put_job(
        {
            "id": "job-a",
            "status": "pending",
            "uploadedKey": "imports/schedule-e/user-aaa/job-a.pdf",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "ttl": 1_900_000_000,
        }
    )

    service_b = _service(repo, files, FakeTextract(), user=USER_B)
    assert service_b._load_job("job-a") is None
    assert service_a._load_job("job-a") is not None


# --- 6.4 start_extraction ----------------------------------------------------


def test_start_extraction_pdf_creates_pending_job_and_presigned_url(
    repo, files, s3_client
):
    service = _service(repo, files, FakeTextract())
    result = service.start_extraction("2023-return.pdf", PDF_CONTENT_TYPE)

    assert result.is_ok
    outcome = result.value
    assert outcome.job_id
    assert outcome.upload_url.startswith("https://")
    assert BUCKET in outcome.upload_url

    stored = _raw_job(repo, USER_A, outcome.job_id)
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored["uploadedKey"] == (
        f"imports/schedule-e/{USER_A}/{outcome.job_id}.pdf"
    )
    assert str(stored["uploadedKey"]).startswith(f"imports/schedule-e/{USER_A}/")
    assert "ttl" in stored and int(stored["ttl"]) > 0
    # No outcome / textractJobId yet (sparse).
    assert "outcome" not in stored
    assert "textractJobId" not in stored


@pytest.mark.parametrize(
    "bad_type",
    ["image/png", "text/plain", "application/octet-stream", "", "application/pdf; charset=utf-8"],
)
def test_start_extraction_non_pdf_is_validation_no_job_no_url(
    repo, files, bad_type
):
    service = _service(repo, files, FakeTextract())
    result = service.start_extraction("x.bin", bad_type)

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "file"

    # No job row written at all.
    jobs = repo.query(
        keys.user_pk(USER_A), sk_begins_with=keys.extraction_job_list_prefix()
    )
    assert jobs == []


def test_start_extraction_content_type_case_insensitive(repo, files):
    service = _service(repo, files, FakeTextract())
    result = service.start_extraction("x.pdf", "APPLICATION/PDF")
    assert result.is_ok


# --- 6.6 begin_extraction ----------------------------------------------------


def _start_job(service) -> str:
    result = service.start_extraction("r.pdf", PDF_CONTENT_TYPE)
    assert result.is_ok
    return result.value.job_id


def test_begin_extraction_absent_object_not_found_textract_never_called(
    repo, files
):
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    # Browser never completed the PUT.

    result = service.begin_extraction(job_id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert textract.start_calls == []
    # Job remains pending (not failed) — the object just isn't there yet.
    assert _raw_job(repo, USER_A, job_id)["status"] == "pending"


def test_begin_extraction_other_user_job_not_found_textract_never_called(
    repo, files, s3_client
):
    textract_a = FakeTextract()
    service_a = _service(repo, files, textract_a, user=USER_A)
    job_id = _start_job(service_a)
    _put_pdf(s3_client, _raw_job(repo, USER_A, job_id)["uploadedKey"])

    textract_b = FakeTextract()
    service_b = _service(repo, files, textract_b, user=USER_B)
    result = service_b.begin_extraction(job_id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert textract_b.start_calls == []


def test_begin_extraction_non_pdf_object_fails_and_deletes(repo, files, s3_client):
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    # Upload bytes that are NOT a PDF (no %PDF- signature).
    s3_client.put_object(
        Bucket=BUCKET, Key=key, Body=b"not a pdf at all", ContentType=PDF_CONTENT_TYPE
    )

    result = service.begin_extraction(job_id)
    assert result.is_ok
    view = result.value
    assert view.status == "failed"
    assert "valid PDF" in (view.message or "")
    assert textract.start_calls == []
    # Object deleted on the terminal transition.
    assert not _object_exists(s3_client, key)


def test_begin_extraction_valid_pdf_starts_textract_and_processing(
    repo, files, s3_client
):
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key)

    result = service.begin_extraction(job_id)
    assert result.is_ok
    assert result.value.status == "processing"
    assert textract.start_calls == [(BUCKET, key)]

    stored = _raw_job(repo, USER_A, job_id)
    assert stored["status"] == "processing"
    assert stored["textractJobId"] == textract.job_id


# --- Upload page-count guard (cost protection) -------------------------------


def _real_pdf(pages: int) -> bytes:
    """A genuine, parseable PDF with ``pages`` blank pages (built with pypdf)."""
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_begin_extraction_rejects_oversized_pdf_before_textract(
    repo, files, s3_client
):
    """A whole-return upload is refused with guidance and Textract is never called."""
    from logstead.services.schedule_e_extraction import MAX_UPLOAD_PAGES

    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key, _real_pdf(MAX_UPLOAD_PAGES + 1))

    result = service.begin_extraction(job_id)
    assert result.is_ok
    view = result.value
    assert view.status == "failed"
    assert f"{MAX_UPLOAD_PAGES + 1} pages" in (view.message or "")
    assert "Schedule E" in (view.message or "")
    assert textract.start_calls == []
    # The rejected upload is deleted on the terminal transition.
    assert not _object_exists(s3_client, key)


def test_begin_extraction_accepts_pdf_at_the_page_limit(repo, files, s3_client):
    from logstead.services.schedule_e_extraction import MAX_UPLOAD_PAGES

    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key, _real_pdf(MAX_UPLOAD_PAGES))

    result = service.begin_extraction(job_id)
    assert result.is_ok
    assert result.value.status == "processing"
    assert textract.start_calls == [(BUCKET, key)]


def test_begin_extraction_two_page_schedule_e_is_accepted(repo, files, s3_client):
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key, _real_pdf(2))

    result = service.begin_extraction(job_id)
    assert result.is_ok
    assert result.value.status == "processing"
    assert len(textract.start_calls) == 1


def test_begin_extraction_unreadable_page_count_fails_open(repo, files, s3_client):
    """If the page count can't be determined the guard must not block the upload.

    The existing minimal fixture has a ``%PDF-`` header but is not a parseable
    document, so pypdf cannot count its pages -- behavior is unchanged.
    """
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key)  # b"%PDF-1.7 minimal body"

    result = service.begin_extraction(job_id)
    assert result.is_ok
    assert result.value.status == "processing"
    assert textract.start_calls == [(BUCKET, key)]


# --- 6.8 get_status ----------------------------------------------------------


def _processing_job(repo, files, s3_client, textract) -> tuple[ExtractionService, str, str]:
    """Create a job in ``processing`` with the PDF uploaded; return (svc, id, key)."""
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    _put_pdf(s3_client, key)
    service.begin_extraction(job_id)
    return service, job_id, key


def test_get_status_in_progress_stays_processing(repo, files, s3_client):
    textract = FakeTextract(TextractResult(status="IN_PROGRESS", blocks=[]))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    result = service.get_status(job_id)
    assert result.is_ok
    assert result.value.status == "processing"
    # Still processing: the PDF is retained (not a terminal state).
    assert _object_exists(s3_client, key)


def test_get_status_failed_sets_message_and_deletes_pdf(repo, files, s3_client):
    textract = FakeTextract(
        TextractResult(status="FAILED", blocks=[], status_message="boom")
    )
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    result = service.get_status(job_id)
    assert result.is_ok
    view = result.value
    assert view.status == "failed"
    assert view.message == "boom"
    assert view.review_draft is None
    assert not _object_exists(s3_client, key)


def test_get_status_succeeded_schedule_e_builds_draft(repo, files, s3_client):
    # Seed a property so the fuzzy matcher has a candidate to suggest.
    PropertyService(repo, USER_A).create(
        PropertyInput(name="Maple Duplex", address_text="12 Maple St")
    )
    blocks = _load_blocks("clean_two_columns.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    result = service.get_status(job_id)
    assert result.is_ok
    view = result.value
    assert view.status == "complete"
    assert view.outcome == "draft"
    draft = view.review_draft
    assert draft is not None
    assert draft.tax_year == 2023
    assert len(draft.columns) == 2

    col_a = draft.columns[0]
    lines = {ln.schedule_e_line: ln for ln in col_a.lines}
    # Money normalized to two-decimal strings.
    assert lines[3].amount == "24000.00"
    assert lines[5].amount == "350.00"
    assert lines[14].amount == "1875.50"
    assert lines[19].amount == "120.00"
    # Line 18 is never present (parser allow-set excludes it).
    assert 18 not in lines
    # Fuzzy suggestion attached (12 Maple Street ~ 12 Maple St), not auto-applied.
    assert col_a.suggested_property_id is not None
    assert col_a.suggested_property_name == "Maple Duplex"
    assert col_a.mapping_confidence is not None

    # PDF deleted on completion.
    assert not _object_exists(s3_client, key)


def test_get_status_parses_once_then_returns_cache(repo, files, s3_client):
    blocks = _load_blocks("clean_two_columns.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    first = service.get_status(job_id)
    assert first.value.status == "complete"
    calls_after_first = len(textract.get_calls)
    assert calls_after_first == 1

    # A later poll returns the cached draft WITHOUT re-calling Textract.
    second = service.get_status(job_id)
    assert second.value.status == "complete"
    assert second.value.review_draft == first.value.review_draft
    assert len(textract.get_calls) == calls_after_first  # no new Textract call


def test_get_status_succeeded_no_schedule_e_completes_without_draft(
    repo, files, s3_client
):
    blocks = _load_blocks("no_schedule_e.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    result = service.get_status(job_id)
    assert result.is_ok
    view = result.value
    assert view.status == "complete"
    assert view.outcome == "no_schedule_e_found"
    assert view.review_draft is None
    assert view.message
    assert not _object_exists(s3_client, key)


def test_get_status_job_not_in_user_scope_is_not_found(repo, files, s3_client):
    blocks = _load_blocks("clean_two_columns.json")
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    service_a, job_id, _ = _processing_job(repo, files, s3_client, textract)

    service_b = _service(repo, files, FakeTextract(), user=USER_B)
    result = service_b.get_status(job_id)
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- 6.10 terminal-state PDF deletion + no domain writes ---------------------


def _count_user_domain_rows(repo, user: str) -> int:
    """Count a user's Property list rows (the only domain rows extraction could
    conceivably touch here). Extraction must never change this count."""
    return len(
        repo.query(keys.user_pk(user), sk_begins_with=keys.property_list_prefix())
    )


@pytest.mark.parametrize(
    "fixture,expected_outcome",
    [
        ("clean_two_columns.json", "draft"),
        ("no_schedule_e.json", "no_schedule_e_found"),
    ],
)
def test_pdf_deleted_after_complete(repo, files, s3_client, fixture, expected_outcome):
    before = _count_user_domain_rows(repo, USER_A)
    blocks = _load_blocks(fixture)
    textract = FakeTextract(TextractResult(status="SUCCEEDED", blocks=blocks))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    result = service.get_status(job_id)
    assert result.value.outcome == expected_outcome
    assert not _object_exists(s3_client, key)
    # No Property rows created/removed by extraction.
    assert _count_user_domain_rows(repo, USER_A) == before


def test_pdf_deleted_after_failed(repo, files, s3_client):
    before = _count_user_domain_rows(repo, USER_A)
    textract = FakeTextract(TextractResult(status="FAILED", blocks=[]))
    service, job_id, key = _processing_job(repo, files, s3_client, textract)

    service.get_status(job_id)
    assert not _object_exists(s3_client, key)
    assert _count_user_domain_rows(repo, USER_A) == before


def test_begin_failed_non_pdf_also_leaves_domain_untouched(repo, files, s3_client):
    before = _count_user_domain_rows(repo, USER_A)
    textract = FakeTextract()
    service = _service(repo, files, textract)
    job_id = _start_job(service)
    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=b"nope", ContentType=PDF_CONTENT_TYPE)

    service.begin_extraction(job_id)
    assert not _object_exists(s3_client, key)
    assert _count_user_domain_rows(repo, USER_A) == before
