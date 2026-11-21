# Feature: schedule-e-pdf-extraction, Property 2: The uploaded PDF is always deleted on a terminal state
"""Property-based test for Property 2 of the Schedule E PDF extraction design.

Validates: Requirements 10.1, 10.2, 10.4, 12.3

Property 2 ("The uploaded PDF is always deleted on a terminal state"): for any
extraction job that reaches a terminal ``Job_Status`` — ``complete`` (whether a
``draft`` or ``no_schedule_e_found``) or ``failed`` — the uploaded
``Tax_Return_PDF`` object SHALL be absent from S3 after the terminal transition,
so no uploaded return is retained past completion or failure.

The job is driven to each terminal outcome through the real ``ExtractionService``
against a ``moto``-backed S3 bucket + DynamoDB table and a **fake**
``TextractAdapter`` (live Amazon Textract is never called). The terminal outcome
is chosen by a Hypothesis strategy spanning every terminal path:

* ``complete`` / ``draft``            — Textract ``SUCCEEDED`` with a Schedule E fixture;
* ``complete`` / ``no_schedule_e_found`` — Textract ``SUCCEEDED`` with a non-Schedule-E fixture;
* ``failed`` (late Textract failure) — Textract ``FAILED`` on the poll;
* ``failed`` (not a readable PDF)    — a non-PDF object fails at ``begin_extraction``.

The test also asserts the dual: while a job is still ``processing``
(Textract ``IN_PROGRESS``) the uploaded object is **still present** — the PDF is
not deleted early, only on a terminal transition.
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.adapters.textract import TextractResult
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.schedule_e_extraction import (
    PDF_CONTENT_TYPE,
    ExtractionService,
)

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-prop2"

_PARSER_FIXTURES = Path(__file__).parent / "fixtures" / "schedule_e_parser"


def _load_blocks(name: str) -> list[dict]:
    return json.loads((_PARSER_FIXTURES / name).read_text())["blocks"]


# --- Fake Textract adapter (never touches AWS) -------------------------------


class FakeTextract:
    """In-memory stand-in for ``TextractAdapter`` returning a canned result.

    Mirrors the fake used by the unit tests: ``start_document_analysis`` records
    the (bucket, key) and hands back a fixed job id; ``get_document_analysis``
    returns the pre-seeded :class:`TextractResult`.
    """

    def __init__(self, result: TextractResult | None = None) -> None:
        self.result = result
        self.start_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []
        self.job_id = "textract-job-prop2"

    def start_document_analysis(self, bucket: str, key: str) -> str:
        self.start_calls.append((bucket, key))
        return self.job_id

    def get_document_analysis(self, job_id: str) -> TextractResult:
        self.get_calls.append(job_id)
        assert self.result is not None, "no TextractResult seeded on the fake"
        return self.result


# --- moto-backed S3 + DynamoDB fixtures (reused from the unit suite) ----------


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


def _object_exists(s3_client, key: str) -> bool:
    contents = s3_client.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    return any(obj["Key"] == key for obj in contents)


# --- Terminal-outcome strategy -----------------------------------------------
#
# Each entry names a distinct terminal path. ``via`` selects how the job reaches
# the terminal state: a "poll" outcome is driven to ``processing`` with a valid
# PDF uploaded, then a ``get_status`` poll observes the seeded Textract result;
# a "begin" outcome uploads a non-PDF object so ``begin_extraction`` itself
# terminates the job as ``failed``.
_TERMINAL_OUTCOMES = [
    # complete / draft — SUCCEEDED with a Schedule E document.
    {"via": "poll", "textract": TextractResult(status="SUCCEEDED", blocks=_load_blocks("clean_two_columns.json")), "expected_status": "complete", "expected_outcome": "draft"},
    # complete / no_schedule_e_found — SUCCEEDED without a Schedule E.
    {"via": "poll", "textract": TextractResult(status="SUCCEEDED", blocks=_load_blocks("no_schedule_e.json")), "expected_status": "complete", "expected_outcome": "no_schedule_e_found"},
    # failed — a late Textract failure discovered on the poll.
    {"via": "poll", "textract": TextractResult(status="FAILED", blocks=[], status_message="boom"), "expected_status": "failed", "expected_outcome": None},
    # failed — a PARTIAL_SUCCESS carrying no usable blocks also terminates.
    {"via": "poll", "textract": TextractResult(status="PARTIAL_SUCCESS", blocks=[], status_message="partial"), "expected_status": "failed", "expected_outcome": None},
    # failed — the uploaded object is not a readable PDF (fails at begin).
    {"via": "begin", "textract": None, "expected_status": "failed", "expected_outcome": None},
]

_terminal_outcome = st.sampled_from(_TERMINAL_OUTCOMES)


def _start_and_key(service, repo_, s3) -> tuple[str, str]:
    """``start_extraction`` → return (job_id, uploadedKey) for the new job."""
    result = service.start_extraction("return.pdf", PDF_CONTENT_TYPE)
    assert result.is_ok
    job_id = result.value.job_id
    from logstead.repository import keys

    stored = repo_.get_item(keys.user_pk(USER), keys.extraction_job_sk(job_id))
    return job_id, str(stored["uploadedKey"])


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(outcome=_terminal_outcome)
def test_uploaded_pdf_absent_after_any_terminal_state(
    repo, files, s3_client, outcome
):
    """The uploaded PDF is gone from S3 after the job reaches any terminal state.

    Drives ``start → put object → begin → poll`` to the strategy-selected
    terminal outcome and asserts the uploaded key is absent afterwards (Req 10.1,
    10.2, 10.4, 12.3). Also asserts the object is still present while the job is
    merely ``processing`` (not deleted early) for the poll-driven outcomes.
    """
    textract = FakeTextract(outcome["textract"])
    service = ExtractionService(repo, USER, files=files, textract=textract)

    job_id, key = _start_and_key(service, repo, s3_client)

    if outcome["via"] == "begin":
        # A non-PDF object: begin_extraction itself terminates the job (failed),
        # deletes the object, and never calls Textract.
        s3_client.put_object(
            Bucket=BUCKET, Key=key, Body=b"this is not a pdf", ContentType=PDF_CONTENT_TYPE
        )
        begin = service.begin_extraction(job_id)
        assert begin.is_ok
        assert begin.value.status == outcome["expected_status"]
        assert textract.start_calls == []
    else:
        # A valid PDF object: begin_extraction starts Textract (processing);
        # the terminal transition then happens on the get_status poll.
        s3_client.put_object(
            Bucket=BUCKET, Key=key, Body=b"%PDF-1.7 minimal body", ContentType=PDF_CONTENT_TYPE
        )
        begin = service.begin_extraction(job_id)
        assert begin.is_ok
        assert begin.value.status == "processing"

        # Dual check: while processing, the PDF is NOT deleted early.
        assert _object_exists(s3_client, key)

        poll = service.get_status(job_id)
        assert poll.is_ok
        assert poll.value.status == outcome["expected_status"]
        assert poll.value.outcome == outcome["expected_outcome"]

    # The property: after any terminal transition the uploaded PDF is absent.
    assert not _object_exists(s3_client, key)

    # head_object confirms absence as well (get/head raises on a deleted key).
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        s3_client.head_object(Bucket=BUCKET, Key=key)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_processing_job_still_retains_the_uploaded_pdf(repo, files, s3_client, data):
    """While a job is still ``processing`` (IN_PROGRESS) the PDF is retained.

    The dual of Property 2: a non-terminal poll must not delete the uploaded
    object. Driven across repeated IN_PROGRESS polls to confirm the PDF survives
    every non-terminal transition.
    """
    textract = FakeTextract(TextractResult(status="IN_PROGRESS", blocks=[]))
    service = ExtractionService(repo, USER, files=files, textract=textract)

    job_id, key = _start_and_key(service, repo, s3_client)
    s3_client.put_object(
        Bucket=BUCKET, Key=key, Body=b"%PDF-1.7 minimal body", ContentType=PDF_CONTENT_TYPE
    )
    assert service.begin_extraction(job_id).value.status == "processing"

    polls = data.draw(st.integers(min_value=1, max_value=4))
    for _ in range(polls):
        result = service.get_status(job_id)
        assert result.is_ok
        assert result.value.status == "processing"
        # Not a terminal state → the PDF must still be present.
        assert _object_exists(s3_client, key)
