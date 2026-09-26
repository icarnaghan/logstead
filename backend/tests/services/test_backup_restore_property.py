"""Property-based tests for ``BackupService.restore`` (Properties 2, 4, 9, 10).

Each property test drives the real :class:`BackupService` against a fresh moto
DynamoDB (base table + GSI1 + GSI2) and a moto S3 bucket, mirroring the seeding
pattern in ``test_backup_export.py``. Backup documents are generated as raw
dicts (the on-wire shape the router hands to ``restore``): catalog-slug
categories, uuid ids, exact two-decimal money strings, and valid dates. The
generated documents always pass ``validate_document`` (asserted per example) so
any observed failure is attributable to the behaviour under test.

Properties covered:

* Property 2  — restore is replace-all with no leftovers (Req 2.1, 12.1).
* Property 4  — restore recomputes each asset's depreciation schedule (Req 2.5).
* Property 9  — a mid-restore failure after clear surfaces a retryable error
  (Req 12.2).
* Property 10 — restore batches documents exceeding the atomic-write cap and
  still reaches store == document (Req 12.3).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.backup import BackupService, validate_document
from logstead.services.depreciation import compute_schedule_rows
from logstead.services.transaction import category_by_id

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"

# Catalog categories that carry no special requirements (``other`` is excluded
# because it requires a description). Each carries its kind so we can pick a
# type consistent with the category.
_INCOME_CATEGORIES = ["rents-received", "royalties-received"]
_EXPENSE_CATEGORIES = [
    "advertising",
    "cleaning-and-maintenance",
    "insurance",
    "management-fees",
    "repairs",
    "supplies",
    "taxes",
    "utilities",
]


# --- moto table + bucket helpers ---------------------------------------------


def _create_table(ddb) -> None:
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


class _Harness:
    """A fresh moto-backed table + bucket with a wired ``BackupService``."""

    def __init__(self) -> None:
        self.ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(self.ddb)
        self.s3 = boto3.client("s3", region_name=REGION)
        self.s3.create_bucket(Bucket=BUCKET)
        self.repo = DynamoRepository(self.ddb, TABLE_NAME)
        self.files = S3FileAdapter(self.s3, BUCKET)
        self.user = UserContext(user_id=USER_ID)
        self.service = BackupService(self.repo, self.files, self.user)


# --- Hypothesis strategies for a valid raw backup document -------------------


def _money() -> st.SearchStrategy[str]:
    """A positive exact two-decimal money string, e.g. ``"1234.56"``."""
    return st.integers(min_value=1, max_value=9_999_999).map(
        lambda cents: f"{Decimal(cents) / Decimal(100):.2f}"
    )


def _date() -> st.SearchStrategy[str]:
    """An ISO ``YYYY-MM-DD`` date within a fixed, valid window."""
    return st.dates(
        min_value=__import__("datetime").date(2018, 1, 1),
        max_value=__import__("datetime").date(2024, 12, 31),
    ).map(lambda d: d.isoformat())


def _uuid() -> st.SearchStrategy[str]:
    return st.builds(lambda: str(uuid.uuid4()))


def _nonblank_text(max_size: int) -> st.SearchStrategy[str]:
    """Non-empty text that is not whitespace-only.

    ``validate_document`` treats a whitespace-only string as a missing required
    field, so generated names/descriptions must carry at least one non-space
    character.
    """
    return st.text(min_size=1, max_size=max_size).filter(lambda s: s.strip())


@st.composite
def _transaction(draw, property_id: str) -> dict[str, Any]:
    is_income = draw(st.booleans())
    category_id = draw(
        st.sampled_from(_INCOME_CATEGORIES if is_income else _EXPENSE_CATEGORIES)
    )
    return {
        "id": draw(_uuid()),
        "property_id": property_id,
        "date": draw(_date()),
        "amount": draw(_money()),
        "type": "income" if is_income else "expense",
        "category_id": category_id,
        "description": draw(st.none() | st.text(min_size=1, max_size=20)),
    }


@st.composite
def _asset(draw, property_id: str) -> dict[str, Any]:
    return {
        "id": draw(_uuid()),
        "property_id": property_id,
        "description": draw(_nonblank_text(20)),
        "cost_basis": draw(_money()),
        "placed_in_service_date": draw(_date()),
        "recovery_period_years": draw(
            st.sampled_from(["5", "7", "15", "27.5", "39"])
        ),
    }


@st.composite
def _usage_year(draw) -> dict[str, Any]:
    return {
        "tax_year": draw(st.integers(min_value=2018, max_value=2024)),
        "fair_rental_days": draw(st.integers(min_value=0, max_value=365)),
        "personal_use_days": draw(st.integers(min_value=0, max_value=365)),
    }


@st.composite
def _property(draw) -> dict[str, Any]:
    property_id = draw(_uuid())
    # De-dupe usage years by tax_year (one row per year in the store).
    raw_usage = draw(st.lists(_usage_year(), max_size=3))
    usage_by_year = {u["tax_year"]: u for u in raw_usage}
    return {
        "id": property_id,
        "name": draw(_nonblank_text(20)),
        "address_text": draw(_nonblank_text(30)),
        "property_type": draw(st.sampled_from([None, "single_family", "condo"])),
        "usage": list(usage_by_year.values()),
        "transactions": draw(
            st.lists(_transaction(property_id), max_size=4)
        ),
        "assets": draw(st.lists(_asset(property_id), max_size=2)),
    }


@st.composite
def _document(draw, *, min_properties: int = 0) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": draw(
            st.lists(_property(), min_size=min_properties, max_size=3)
        ),
    }


# --- Store read-back helpers -------------------------------------------------


def _stored_ids_by_kind(harness: _Harness) -> dict[str, set[str]]:
    """Collect stored entity ids grouped by kind across the user's data.

    Returns a mapping with keys ``property``/``transaction``/``asset``/``usage``
    whose values are the sets of ids (usage keyed as ``<propertyId>:<taxYear>``).
    """
    ids: dict[str, set[str]] = {
        "property": set(),
        "transaction": set(),
        "asset": set(),
        "usage": set(),
    }
    for row in harness.repo.query(keys.user_pk(USER_ID)):
        sk = str(row["SK"])
        if sk.startswith(keys.PROP_PREFIX):
            property_id = sk[len(keys.PROP_PREFIX):]
            ids["property"].add(property_id)

    for property_id in ids["property"]:
        pk = keys.property_scoped_pk(property_id)
        for row in harness.repo.query(pk):
            sk = str(row["SK"])
            if sk.startswith(keys.TXN_PREFIX) and keys.DOC_PREFIX not in sk:
                ids["transaction"].add(str(row["id"]))
            elif (
                sk.startswith(keys.ASSET_PREFIX)
                and keys.SCHED_PREFIX not in sk
            ):
                ids["asset"].add(str(row["id"]))
            elif sk.startswith(keys.USAGE_PREFIX):
                ids["usage"].add(f"{property_id}:{row['taxYear']}")
    return ids


def _document_ids_by_kind(document: dict[str, Any]) -> dict[str, set[str]]:
    """The same id sets, but derived directly from a backup document."""
    ids: dict[str, set[str]] = {
        "property": set(),
        "transaction": set(),
        "asset": set(),
        "usage": set(),
    }
    for prop in document["properties"]:
        ids["property"].add(prop["id"])
        for txn in prop.get("transactions", []):
            ids["transaction"].add(txn["id"])
        for asset in prop.get("assets", []):
            ids["asset"].add(asset["id"])
        for usage in prop.get("usage", []):
            ids["usage"].add(f"{prop['id']}:{usage['tax_year']}")
    return ids


def _seed_dataset_a(harness: _Harness) -> dict[str, set[str]]:
    """Seed a distinct dataset A directly via restore; return its id sets."""
    property_id = str(uuid.uuid4())
    txn_id = str(uuid.uuid4())
    asset_id = str(uuid.uuid4())
    document_a = {
        "schema_version": "1",
        "exported_at": "2025-01-01T00:00:00+00:00",
        "properties": [
            {
                "id": property_id,
                "name": "Dataset A Property",
                "address_text": "1 A Street",
                "usage": [
                    {
                        "tax_year": 2020,
                        "fair_rental_days": 200,
                        "personal_use_days": 10,
                    }
                ],
                "transactions": [
                    {
                        "id": txn_id,
                        "property_id": property_id,
                        "date": "2020-05-01",
                        "amount": "999.99",
                        "type": "income",
                        "category_id": "rents-received",
                    }
                ],
                "assets": [
                    {
                        "id": asset_id,
                        "property_id": property_id,
                        "description": "A-only asset",
                        "cost_basis": "5000.00",
                        "placed_in_service_date": "2020-06-15",
                        "recovery_period_years": "27.5",
                    }
                ],
            }
        ],
    }
    result = harness.service.restore(document_a)
    assert result.is_ok, f"seeding dataset A failed: {result.error!r}"
    return _document_ids_by_kind(document_a)


# ============================================================================
# Property 2: Restore is replace-all with no leftovers
# ============================================================================

# Feature: backup-restore, Property 2: Restore is replace-all with no leftovers
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(document_b=_document())
def test_restore_is_replace_all_with_no_leftovers(document_b) -> None:
    """Seed dataset A, restore valid B; store == B and no A-only id survives.

    Validates: Requirements 2.1, 12.1
    """
    with mock_aws():
        harness = _Harness()

        # Confirm the generated B is a valid document on its own.
        assert validate_document(document_b).is_ok

        a_ids = _seed_dataset_a(harness)

        result = harness.service.restore(document_b)
        assert result.is_ok, f"restore of B failed: {result.error!r}"

        stored = _stored_ids_by_kind(harness)
        expected = _document_ids_by_kind(document_b)

        # 1. The store equals B: every B id is present, and nothing extra is.
        assert stored == expected, (
            "stored data must equal document B exactly"
        )

        # 2. No A-only id (absent from B) survives the restore.
        for kind, a_kind_ids in a_ids.items():
            leftover = a_kind_ids - expected[kind]
            assert not (leftover & stored[kind]), (
                f"A-only {kind} ids survived the restore: "
                f"{leftover & stored[kind]}"
            )


# ============================================================================
# Property 4: Restore recomputes each asset's depreciation schedule
# ============================================================================


@st.composite
def _document_with_assets(draw) -> dict[str, Any]:
    """A valid document with at least one property carrying >= 1 asset."""
    property_id = draw(_uuid())
    assets = draw(st.lists(_asset(property_id), min_size=1, max_size=3))
    return {
        "schema_version": "1",
        "exported_at": "2025-02-14T10:30:00+00:00",
        "properties": [
            {
                "id": property_id,
                "name": draw(_nonblank_text(20)),
                "address_text": draw(_nonblank_text(30)),
                "transactions": [],
                "assets": assets,
                "usage": [],
            }
        ],
    }


# Feature: backup-restore, Property 4: Restore recomputes each asset's depreciation schedule
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(document=_document_with_assets())
def test_restore_recomputes_each_assets_schedule(document) -> None:
    """Stored SCHED rows equal ``compute_schedule_rows`` and ignore the document.

    The document carries a bogus ``schedule`` field on every asset; restore must
    ignore it and materialize the schedule purely from the recomputation.

    Validates: Requirements 2.5
    """
    with mock_aws():
        harness = _Harness()

        # Salt each asset with bogus schedule data the restore must NOT use.
        for prop in document["properties"]:
            for asset in prop["assets"]:
                asset["schedule"] = [
                    {"tax_year": 1999, "amount": "0.01", "remaining_basis": "0.01"}
                ]
                asset["schedule_rows"] = [{"tax_year": 1999, "amount": "0.01"}]

        assert validate_document(document).is_ok

        result = harness.service.restore(document)
        assert result.is_ok, f"restore failed: {result.error!r}"

        for prop in document["properties"]:
            property_id = prop["id"]
            for asset in prop["assets"]:
                # Read the stored SCHED rows for this asset from the store.
                stored_rows = harness.repo.query(
                    keys.property_scoped_pk(property_id),
                    sk_begins_with=keys.schedule_list_prefix(asset["id"]),
                    money_attrs={"amount", "remainingBasis"},
                )
                stored_by_year = {
                    int(r["taxYear"]): (
                        Decimal(str(r["amount"])),
                        Decimal(str(r["remainingBasis"])),
                    )
                    for r in stored_rows
                }

                # Recompute from the restored asset (as the service should).
                restored_asset = _restored_asset(harness, property_id, asset["id"])
                expected_rows = compute_schedule_rows(restored_asset)
                expected_by_year = {
                    row.tax_year: (row.amount, row.remaining_basis)
                    for row in expected_rows
                }

                assert stored_by_year == expected_by_year, (
                    "stored schedule rows must equal compute_schedule_rows"
                )
                # The bogus 1999 row from the document must never appear.
                assert 1999 not in stored_by_year, (
                    "schedule must not be taken from the document"
                )


def _restored_asset(harness: _Harness, property_id: str, asset_id: str):
    """Read one restored asset back as a typed ``DepreciableAsset``."""
    from logstead.services.depreciation import DepreciationService

    for asset in DepreciationService(harness.repo).list_assets(property_id):
        if asset.id == asset_id:
            return asset
    raise AssertionError(f"restored asset {asset_id} not found")


# ============================================================================
# Property 9: A mid-restore failure after clear surfaces a retryable error
# ============================================================================

# Feature: backup-restore, Property 9: A mid-restore failure after clear surfaces a retryable error
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    document=_document(min_properties=1),
)
def test_mid_restore_failure_surfaces_retryable_error(document) -> None:
    """A write-batch failure after clear yields a non-validation retryable error.

    Validates: Requirements 12.2
    """
    with mock_aws():
        harness = _Harness()
        assert validate_document(document).is_ok

        # Wrap transact_write so it raises on the FIRST non-empty PUT batch —
        # i.e. the first write of the post-clear write phase. Delete batches
        # (the clear phase) and any empty batch pass through untouched, so the
        # clear always completes and the injected failure always lands squarely
        # in the write phase. Failing on the first PUT batch (rather than an
        # nth batch) guarantees the failure fires for EVERY min_properties>=1
        # document: a property always emits its list-row + META PUT batch, even
        # when it carries no usage/transactions/assets. This makes the property
        # ("a failure after clear surfaces a retryable conflict") hold for the
        # whole input space, not just documents large enough to reach a later
        # batch.
        real_transact = harness.repo.transact_write
        state = {"write_phase_seen": False}

        def failing_transact(items, *, money_attrs=None):
            is_put_batch = any("put" in entry for entry in items)
            if is_put_batch:
                # First write of the post-clear write phase: inject the failure.
                state["write_phase_seen"] = True
                raise RuntimeError("injected write failure")
            return real_transact(items, money_attrs=money_attrs)

        harness.repo.transact_write = failing_transact  # type: ignore[method-assign]

        result = harness.service.restore(document)

        # The injected failure must actually have fired in the write phase (the
        # clear ran to completion via delete batches, then the first PUT batch
        # raised). This guards the test against silently never triggering.
        assert state["write_phase_seen"], (
            "the injected failure must fire on a post-clear write batch"
        )
        assert not result.is_ok, "a mid-restore write failure must not succeed"
        # It must be a retryable error, NOT a plain validation error.
        assert result.error.kind != "validation", (
            "a write-phase failure is not a validation error"
        )
        assert result.error.kind == "conflict", (
            f"expected a retryable 'conflict' error, got {result.error.kind!r}"
        )
        assert result.error.message, "the error must carry a retry message"


# ============================================================================
# Property 10: Restore batches documents exceeding the atomic-write cap
# ============================================================================

# Feature: backup-restore, Property 10: Restore batches documents that exceed the atomic-write cap and still reaches store == document
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    txn_count=st.integers(min_value=101, max_value=160),
    seed=st.integers(min_value=0, max_value=1_000_000),
)
def test_restore_batches_documents_exceeding_transact_cap(
    txn_count, seed
) -> None:
    """A > 100-entity document restores across batches; store == document.

    Builds a single property carrying more transactions than a single
    ``transact_write`` can hold (the DynamoDB 100-action cap), restores it, and
    asserts every entity is present and the store equals the document.

    Validates: Requirements 12.3
    """
    with mock_aws():
        harness = _Harness()

        property_id = str(uuid.uuid4())
        transactions = []
        for i in range(txn_count):
            cents = (seed + i) % 9_999_999 + 1
            transactions.append(
                {
                    "id": str(uuid.uuid4()),
                    "property_id": property_id,
                    "date": "2023-01-01",
                    "amount": f"{Decimal(cents) / Decimal(100):.2f}",
                    "type": "income",
                    "category_id": "rents-received",
                }
            )
        document = {
            "schema_version": "1",
            "exported_at": "2025-02-14T10:30:00+00:00",
            "properties": [
                {
                    "id": property_id,
                    "name": "Batched Property",
                    "address_text": "100 Batch Ave",
                    "usage": [],
                    "transactions": transactions,
                    "assets": [],
                }
            ],
        }

        assert validate_document(document).is_ok
        # Precondition: this really does exceed one atomic write.
        assert txn_count > BackupService._TRANSACT_MAX

        result = harness.service.restore(document)
        assert result.is_ok, f"batched restore failed: {result.error!r}"
        assert result.value.transactions == txn_count

        stored = _stored_ids_by_kind(harness)
        expected = _document_ids_by_kind(document)
        assert stored == expected, (
            "every batched entity must be present and the store == document"
        )
