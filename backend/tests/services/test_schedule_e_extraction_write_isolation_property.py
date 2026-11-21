"""Property-based test for Schedule E PDF extraction write isolation (task 8.1).

# Feature: schedule-e-pdf-extraction, Property 1: Extraction never writes a transaction or property

Validates: Requirements 9.1, 7.2, 12.5

For any randomized sequence of extraction operations (``start_extraction`` →
upload the object to moto S3 → ``begin_extraction`` → one or more
``get_status`` polls) over any uploaded document and any of the three Textract
outcomes (``SUCCEEDED`` with a Schedule E draft, ``SUCCEEDED`` with no Schedule
E, or ``FAILED``), the user's ``Transaction`` rows AND ``Property`` rows are
exactly what they were before extraction began.

Extraction's only durable writes are transient ``Extraction_Job`` rows
(``SEEXTRACT#``) plus the delete of the uploaded PDF; it must create, modify,
or delete NO transaction and NO property. Only the layer-1 confirm path
(``POST /imports/schedule-e``) ever writes domain rows — and this test never
calls it.

The oracle is a whole-table raw DynamoDB ``scan`` snapshot filtered to the
domain-row prefixes extraction could conceivably touch — the user-view
property rows (``PROP#``), the property-scoped partitions holding the property
META mirror and its transactions (``PROPERTY#…`` with ``META`` / ``TXN#`` sort
keys) — taken once before extraction and again after the full operation
sequence. The two snapshots must be byte-for-byte identical. Real data is
pre-seeded (one or more properties, and some user-tracked transactions) so
there is genuine ``PROP#`` / ``PROPERTY#`` / ``TXN#`` content that must stay
put.

The ``FakeTextract`` fake and the canned Schedule-E / no-Schedule-E block
fixtures are reused from the sibling unit-test module
(``test_schedule_e_extraction``) so live Amazon Textract is never called.
Per-example moto table + bucket provisioning is not instantaneous, so the
deadline is disabled while ``max_examples`` is held at 100.
"""

from __future__ import annotations

from datetime import date

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

# Reuse the fake Textract adapter and the canned block fixtures the unit tests
# already use (never touches live AWS).
from tests.services.test_schedule_e_extraction import FakeTextract, _load_blocks

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-aaa"

# The three Textract outcomes the extraction poll path can observe. Each maps to
# a canned result the fake returns:
#   * "draft"           -> SUCCEEDED with a Schedule E block fixture
#   * "no_schedule_e"   -> SUCCEEDED with a non-Schedule-E block fixture
#   * "failed"          -> FAILED, no blocks
_OUTCOMES = ["draft", "no_schedule_e", "failed"]

# SK prefixes that name domain rows extraction must never create/modify/delete.
# The property user-view row (PROP#) lives under USER#<id>; the property META
# mirror and the property's transactions (TXN#) live under PROPERTY#<id>.
_PROPERTY_PK_PREFIX = keys.PROPERTY_PREFIX  # "PROPERTY#"
_PROP_SK_PREFIX = keys.PROP_PREFIX  # "PROP#"
_TXN_SK_PREFIX = keys.TXN_PREFIX  # "TXN#"


def _create_table(ddb) -> None:
    """Provision the single-table Logstead schema (base + GSI1 + GSI2)."""
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


def _is_domain_row(pk: str, sk: str) -> bool:
    """True for a Transaction or Property row the extraction must never touch.

    Covers the three domain prefixes:
      * ``USER#… / PROP#…``             — a user's property list row
      * ``PROPERTY#… / META``           — the property META mirror
      * ``PROPERTY#… / TXN#…``          — a transaction under its property
    The ``SEEXTRACT#`` job rows extraction legitimately writes are intentionally
    excluded, so the oracle isolates domain mutations from the transient job
    bookkeeping.
    """
    if sk.startswith(_PROP_SK_PREFIX):
        return True
    if pk.startswith(_PROPERTY_PK_PREFIX) and (
        sk == keys.META_SK or sk.startswith(_TXN_SK_PREFIX)
    ):
        return True
    return False


def _snapshot_domain(ddb) -> dict[tuple[str, str], dict]:
    """Snapshot every Transaction/Property row in the table, keyed by (PK, SK).

    Pages through a raw DynamoDB ``scan`` of the whole table and keeps only the
    rows ``_is_domain_row`` recognizes, giving a whole-table "no transaction or
    property changed" oracle that still ignores the ``SEEXTRACT#`` job rows the
    service is allowed to write.
    """
    snapshot: dict[tuple[str, str], dict] = {}
    kwargs: dict = {"TableName": TABLE_NAME}
    while True:
        resp = ddb.scan(**kwargs)
        for item in resp.get("Items", []):
            pk = item["PK"]["S"]
            sk = item["SK"]["S"]
            if _is_domain_row(pk, sk):
                snapshot[(pk, sk)] = item
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return snapshot


def _result_for(outcome: str) -> TextractResult:
    """Build the canned ``TextractResult`` the fake returns for an outcome."""
    if outcome == "draft":
        return TextractResult(
            status="SUCCEEDED", blocks=_load_blocks("clean_two_columns.json")
        )
    if outcome == "no_schedule_e":
        return TextractResult(
            status="SUCCEEDED", blocks=_load_blocks("no_schedule_e.json")
        )
    # failed
    return TextractResult(status="FAILED", blocks=[], status_message="boom")


def _seed_transaction(repo: DynamoRepository, property_id: str, index: int) -> None:
    """Write one realistic Transaction row directly under its property partition.

    Mirrors the shape ``TransactionService`` persists (base PK/SK with the
    inverted-date sort key plus the GSI2 tax-year keys) so the snapshot holds
    genuine ``TXN#`` content that must survive extraction untouched. Seeding via
    the repo keeps the test free of the category reference-data dependency the
    full ``TransactionService.create`` path would require.
    """
    txn_id = f"txn-{property_id}-{index}"
    txn_date = date(2023, 1, 1 + index)
    amount = f"{100 + index}.00"
    repo.put_item(
        {
            "PK": keys.property_scoped_pk(property_id),
            "SK": keys.transaction_sk(txn_date, txn_id),
            "GSI2PK": keys.gsi2_year_pk(property_id, txn_date.year),
            "GSI2SK": keys.gsi2_transaction_sk(txn_date, txn_id),
            "id": txn_id,
            "propertyId": property_id,
            "date": txn_date.isoformat(),
            "amount": amount,
            "type": "expense" if index % 2 else "income",
            "scheduleELine": 3,
            "imported": False,
        }
    )


# Strategies -----------------------------------------------------------------

# A randomized sequence of extraction outcomes to walk through — but each
# ExtractionService job is one-shot (one terminal transition), so a single
# outcome per example captures the whole start→upload→begin→poll lifecycle.
_outcomes = st.sampled_from(_OUTCOMES)

# A roster of 1-3 properties to pre-seed (real PROP#/PROPERTY# rows), each with
# a name/address and a count of transactions (0-4) to attach.
_roster = st.lists(
    st.fixed_dictionaries(
        {
            "name": st.text(
                alphabet=st.characters(
                    min_codepoint=65, max_codepoint=122
                ),
                min_size=1,
                max_size=12,
            ),
            "address": st.text(
                alphabet=st.characters(
                    min_codepoint=48, max_codepoint=122
                ),
                min_size=1,
                max_size=20,
            ),
            "txn_count": st.integers(min_value=0, max_value=4),
        }
    ),
    min_size=1,
    max_size=3,
)

# How many times to poll get_status after begin_extraction (>= 1). Later polls
# must return the cached terminal result and never re-touch any domain row.
_poll_counts = st.integers(min_value=1, max_value=4)


@settings(deadline=None, max_examples=100)
@given(outcome=_outcomes, roster=_roster, poll_count=_poll_counts)
# Feature: schedule-e-pdf-extraction, Property 1: Extraction never writes a transaction or property
def test_extraction_never_writes_a_transaction_or_property(
    outcome: str,
    roster: list[dict],
    poll_count: int,
) -> None:
    """Validates: Requirements 9.1, 7.2, 12.5"""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER)

        # --- Legitimate setup: real properties + transactions for this user. --
        properties = PropertyService(repo, USER)
        for spec in roster:
            created = properties.create(
                PropertyInput(name=spec["name"], address_text=spec["address"])
            )
            assert created.is_ok
            property_id = created.value.id
            for i in range(spec["txn_count"]):
                _seed_transaction(repo, property_id, i)

        # Snapshot of every Transaction/Property row after all setup. Extraction
        # must leave this byte-for-byte unchanged.
        baseline = _snapshot_domain(ddb)
        # Precondition: the roster really did seed domain rows for the oracle to
        # protect (at least one PROP# row per property).
        assert len(baseline) >= len(roster)

        # --- Full extraction lifecycle over the chosen Textract outcome. ------
        textract = FakeTextract(_result_for(outcome))
        service = ExtractionService(repo, user, files=files, textract=textract)

        start = service.start_extraction("return.pdf", PDF_CONTENT_TYPE)
        assert start.is_ok
        job_id = start.value.job_id

        # Browser uploads the PDF bytes directly to S3 (presigned PUT seam).
        job = repo.get_item(keys.user_pk(USER), keys.extraction_job_sk(job_id))
        assert job is not None
        key = str(job["uploadedKey"])
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=b"%PDF-1.7 minimal body",
            ContentType=PDF_CONTENT_TYPE,
        )

        begin = service.begin_extraction(job_id)
        assert begin.is_ok

        for _ in range(poll_count):
            poll = service.get_status(job_id)
            assert poll.is_ok

        # --- The oracle: no Transaction and no Property row changed. ----------
        assert _snapshot_domain(ddb) == baseline
