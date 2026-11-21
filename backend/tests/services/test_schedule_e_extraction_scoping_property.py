"""Property-based test for Schedule E PDF extraction per-user scoping (task 8.4).

# Feature: schedule-e-pdf-extraction, Property 4: Per-user scoping isolates jobs, drafts, and uploaded objects

Validates: Requirements 11.1, 11.2, 1.1, 1.2, 2.2, 3.6, 7.5

For any two distinct authenticated users A and B — each driving its own
user-scoped ``ExtractionService`` over the same ``moto``-backed single-table
DynamoDB + ``moto`` S3 bucket and its own fake Textract adapter — an
``Extraction_Job`` (and its cached ``Review_Draft``) created and advanced by A
to any randomized state SHALL be scoped to A's ``USER#<subA>`` partition and
SHALL never be readable, pollable, or begin-able by B: every B-side
``begin_extraction``/``get_status`` on A's ``job_id`` resolves to ``not_found``
(Req 11.2, 2.2, 3.6), while A still reaches its own job (Req 1.1, 1.2). The
job item is keyed under A's ``USER#<subA>`` partition, so ownership is a
partition-level fact (Req 11.1).

Folded in: the fuzzy-match source is scoped to the caller (Req 7.5). B is
seeded with a property whose address is *exactly* one of A's extracted
addresses; because A's ``ReviewDraft`` suggestions are drawn only from A's own
``PropertyService.list()``, A's draft never suggests B's property — every
suggested id A produces is one of A's own property ids (never B's).

The job state, both users' property rosters, and the content-type casing are
Hypothesis-generated so the isolation + matcher-scoping invariants are
exercised across the full space of job lifecycles and rosters. Live Amazon
Textract is never called: the adapter seam is an in-memory fake returning the
same canned Textract-shaped block fixture the parser's own tests use.
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.adapters.textract import TextractResult
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService
from logstead.services.schedule_e_extraction import (
    PDF_CONTENT_TYPE,
    ExtractionService,
)

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"

_PARSER_FIXTURES = Path(__file__).parent / "fixtures" / "schedule_e_parser"

# The addresses the parser reads from this fixture (verified: two columns,
# "12 Maple Street" and "90 Oak Avenue", tax year 2023). Used to seed B with a
# property whose address *exactly* equals one of A's extracted addresses so the
# matcher-scoping assertion is meaningful (B would be a perfect match if the
# candidate list were not scoped to A).
_FIXTURE = "clean_two_columns.json"
_A_EXTRACTED_ADDRESSES = ("12 Maple Street", "90 Oak Avenue")


def _load_blocks(name: str) -> list[dict]:
    data = json.loads((_PARSER_FIXTURES / name).read_text())
    return data["blocks"]


class FakeTextract:
    """In-memory stand-in for ``TextractAdapter`` — never touches AWS.

    Returns a canned :class:`TextractResult` and records its calls so a test
    can assert Textract is never invoked on B's not-found path.
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


def _create_table(ddb) -> None:
    """Provision the single-table Logstead schema (base + GSI1 for property rows)."""
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
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
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _put_pdf(s3, key: str) -> None:
    s3.put_object(
        Bucket=BUCKET, Key=key, Body=b"%PDF-1.7 minimal body",
        ContentType=PDF_CONTENT_TYPE,
    )


def _raw_job(repo, user: str, job_id: str):
    return repo.get_item(keys.user_pk(user), keys.extraction_job_sk(job_id))


# A property roster: a small list of (name, address) pairs. Addresses are drawn
# from a modest pool (including A's extracted fixture addresses) so B can be
# seeded with an exact-match address while A's own list stays independent.
_address_pool = st.sampled_from(
    [
        "12 Maple Street",
        "90 Oak Avenue",
        "1 Birch Road",
        "55 Cedar Lane",
        "7 Pine Court",
        "100 Elm Boulevard",
    ]
)
_roster = st.lists(
    st.tuples(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=1, max_size=12
        ).map(str.strip).filter(lambda s: bool(s)),
        _address_pool,
    ),
    min_size=0,
    max_size=4,
)

# The lifecycle state A drives its job to before B attempts to reach it.
_job_state = st.sampled_from(["pending", "processing", "complete", "failed"])

# Content-type casing: ``start_extraction`` accepts PDF case-insensitively; vary
# it so the start path is exercised across spellings (Req 1).
_pdf_content_type = st.sampled_from(
    ["application/pdf", "APPLICATION/PDF", "Application/Pdf"]
)


def _advance_job(service, s3, repo, job_id: str, state: str, fake) -> None:
    """Drive A's job to ``state`` (pending | processing | complete | failed)."""
    if state == "pending":
        return  # start_extraction already left it pending.

    key = _raw_job(repo, USER_A, job_id)["uploadedKey"]
    if state == "failed":
        # Upload a non-PDF object: begin_extraction marks the job failed.
        s3.put_object(
            Bucket=BUCKET, Key=key, Body=b"not a pdf",
            ContentType=PDF_CONTENT_TYPE,
        )
        service.begin_extraction(job_id)
        return

    # processing / complete both need a valid PDF uploaded and Textract started.
    _put_pdf(s3, key)
    service.begin_extraction(job_id)
    if state == "complete":
        # Seeded SUCCEEDED result → the first poll parses, caches, completes.
        service.get_status(job_id)


@settings(deadline=None, max_examples=100)
@given(
    job_state=_job_state,
    content_type=_pdf_content_type,
    a_roster=_roster,
    b_roster=_roster,
)
# Feature: schedule-e-pdf-extraction, Property 4: Per-user scoping isolates jobs, drafts, and uploaded objects
def test_extraction_jobs_drafts_and_matching_are_user_scoped(
    job_state: str,
    content_type: str,
    a_roster: list[tuple[str, str]],
    b_roster: list[tuple[str, str]],
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)

        # Each user drives its own user-scoped ExtractionService + fake Textract.
        a_fake = FakeTextract(
            TextractResult(status="SUCCEEDED", blocks=_load_blocks(_FIXTURE))
        )
        b_fake = FakeTextract()  # B must never cause a Textract call.
        service_a = ExtractionService(
            repo, UserContext(user_id=USER_A), files=files, textract=a_fake
        )
        service_b = ExtractionService(
            repo, UserContext(user_id=USER_B), files=files, textract=b_fake
        )

        # --- Seed rosters: A owns a_roster; B owns b_roster PLUS a property
        # whose address is EXACTLY one of A's extracted fixture addresses. ------
        a_properties = PropertyService(repo, USER_A)
        b_properties = PropertyService(repo, USER_B)

        a_ids: set[str] = set()
        for name, address in a_roster:
            created = a_properties.create(
                PropertyInput(name=name, address_text=address)
            )
            assert created.is_ok
            a_ids.add(created.value.id)

        b_ids: set[str] = set()
        for name, address in b_roster:
            created = b_properties.create(
                PropertyInput(name=name, address_text=address)
            )
            assert created.is_ok
            b_ids.add(created.value.id)
        # B's exact-match decoy: identical address to one of A's columns.
        b_decoy = b_properties.create(
            PropertyInput(
                name="b decoy", address_text=_A_EXTRACTED_ADDRESSES[0]
            )
        )
        assert b_decoy.is_ok
        b_ids.add(b_decoy.value.id)

        # --- A starts a job and drives it to the generated state. ------------
        start = service_a.start_extraction("return.pdf", content_type)
        assert start.is_ok
        job_id = start.value.job_id

        # Req 11.1: the job item is keyed under A's own USER# partition.
        stored = _raw_job(repo, USER_A, job_id)
        assert stored is not None
        assert stored["PK"] == keys.user_pk(USER_A)
        assert stored["SK"] == keys.extraction_job_sk(job_id)
        assert stored["userId"] == USER_A
        # It is NOT reachable under B's partition at the same SK.
        assert _raw_job(repo, USER_B, job_id) is None

        _advance_job(service_a, s3, repo, job_id, job_state, a_fake)

        # --- Isolation: B can NEVER reach A's job (Req 11.2, 2.2, 3.6). -------
        b_fake.start_calls.clear()
        b_fake.get_calls.clear()

        poll_b = service_b.get_status(job_id)
        assert not poll_b.is_ok
        assert poll_b.error.kind == "not_found"

        begin_b = service_b.begin_extraction(job_id)
        assert not begin_b.is_ok
        assert begin_b.error.kind == "not_found"

        # B's attempts never touched Textract (begin returns not_found before
        # the object read, and never calls StartDocumentAnalysis).
        assert b_fake.start_calls == []
        assert b_fake.get_calls == []

        # B's scoped load resolves to nothing either way.
        assert service_b._load_job(job_id) is None

        # --- A still reaches its own job (Req 1.1, 1.2). ----------------------
        poll_a = service_a.get_status(job_id)
        assert poll_a.is_ok
        view = poll_a.value
        assert view.job_id == job_id

        # --- Matcher scoping (Req 7.5): on a completed draft, every suggested
        # property id A produces belongs to A — never B's exact-address decoy. -
        if view.status == "complete" and view.outcome == "draft":
            draft = view.review_draft
            assert draft is not None
            for col in draft.columns:
                suggested = col.suggested_property_id
                if suggested is not None:
                    assert suggested in a_ids
                    assert suggested not in b_ids
