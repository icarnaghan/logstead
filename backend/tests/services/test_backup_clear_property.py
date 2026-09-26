"""Property-based tests for ``BackupService.clear`` (Properties 5, 6, 7).

These exercise the three universal invariants of clear over arbitrary datasets,
each with Hypothesis ``max_examples`` >= 100 (design "Property test
configuration"). A fresh moto DynamoDB table (base + GSI1 + GSI2) and moto S3
bucket back every example so nothing leaks between runs; data is seeded through
the *real* services (``PropertyService`` / ``TransactionService`` /
``DepreciationService`` / ``PhotoService``) so the stored rows match production
shape exactly, then ``BackupService(repo, files, user).clear()`` is invoked.

* **Property 5** (test_clear_empties_the_users_store) — after clear, ZERO rows
  remain across every SK prefix in the user partition and every property
  partition.
* **Property 6** (test_clear_removes_every_s3_binary_with_its_metadata_row) —
  ``delete_object`` is called for every photo/receipt ``s3Key`` and no
  ``PHOTO#`` / ``#DOC#`` metadata rows remain.
* **Property 7** (test_clear_continues_past_s3_delete_failures) — when the S3
  fake raises for a random subset of keys, all metadata rows are still deleted
  and ``ClearSummary.failed_s3_keys`` lists exactly the failing subset.

Property 6/7 use a *recording* S3 fake (records every ``delete_object`` call,
optionally raising for a chosen key subset) rather than moto S3, so the tests
can assert on the exact keys purged. Property 5 uses no S3 objects, so the moto
S3 adapter is used only to construct the collaborators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.depreciation import AssetInput
from logstead.models.property import PropertyDetails, PropertyInput, TaxAssessment
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.backup import BackupService
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.depreciation import DepreciationService
from logstead.services.photo import PhotoService
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"

# Assignable catalog category ids, split by kind so a generated transaction's
# ``type`` always matches its category (matching how the real services validate).
_INCOME_CATEGORY_IDS = [c.id for c in CATEGORY_CATALOG if c.kind == "income"]
# Exclude the "other" category: it requires a free-text description, an
# orthogonal constraint that would only complicate seeding.
_EXPENSE_CATEGORY_IDS = [
    c.id for c in CATEGORY_CATALOG if c.kind == "expense" and not c.requires_description
]

# All child-row SK prefixes/markers that must be absent from a property
# partition after clear (Property 5). ``META`` is an exact SK, the rest are
# begins-with prefixes.
_PROPERTY_SK_PREFIXES = (
    keys.DETAILS_SK,
    keys.NOTE_SK,
    keys.USAGE_PREFIX,
    keys.PHOTO_PREFIX,
    keys.TXN_PREFIX,  # covers base TXN rows and TXN#…#DOC# receipt rows
    keys.ASSET_PREFIX,  # covers base ASSET rows and ASSET#…#SCHED# rows
)


# --- moto table + bucket fixture ---------------------------------------------


def _make_table(ddb: Any) -> None:
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


# --- Recording S3 fake (Property 6, 7) ---------------------------------------


@dataclass
class RecordingS3Fake:
    """A minimal S3 stand-in that records ``delete_object`` calls.

    Substitutable for :class:`S3FileAdapter` in ``BackupService`` because clear
    only calls :meth:`delete_object`. ``fail_keys`` names keys for which the
    delete raises, letting Property 7 drive best-effort failure handling.
    """

    fail_keys: frozenset[str] = frozenset()
    deleted: list[str] = field(default_factory=list)
    attempted: list[str] = field(default_factory=list)

    def delete_object(self, key: str) -> None:
        self.attempted.append(key)
        if key in self.fail_keys:
            raise RuntimeError(f"simulated S3 delete failure for {key!r}")
        self.deleted.append(key)


# --- Hypothesis strategies for an arbitrary dataset --------------------------

_money = st.builds(
    lambda whole, cents: Decimal(f"{whole}.{cents:02d}"),
    st.integers(min_value=1, max_value=50_000),
    st.integers(min_value=0, max_value=99),
)


def _transaction_strategy() -> st.SearchStrategy[dict[str, Any]]:
    income = st.fixed_dictionaries(
        {
            "type": st.just("income"),
            "category_id": st.sampled_from(_INCOME_CATEGORY_IDS),
        }
    )
    expense = st.fixed_dictionaries(
        {
            "type": st.just("expense"),
            "category_id": st.sampled_from(_EXPENSE_CATEGORY_IDS),
        }
    )
    return st.fixed_dictionaries(
        {
            "date": st.dates(
                min_value=date(2020, 1, 1),
                max_value=date(2024, 12, 31),
            ).map(lambda d: d.isoformat()),
            "amount": _money,
            "kindcat": st.one_of(income, expense),
        }
    )


def _asset_strategy() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "description": st.text(min_size=1, max_size=20).filter(
                lambda s: s.strip() != ""
            ),
            "cost_basis": _money,
            "placed_in_service_date": st.dates(
                min_value=date(2018, 1, 1),
                max_value=date(2024, 12, 31),
            ).map(lambda d: d.isoformat()),
        }
    )


def _usage_strategy() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "tax_year": st.integers(min_value=2018, max_value=2024),
            "fair_rental_days": st.integers(min_value=0, max_value=365),
            "personal_use_days": st.integers(min_value=0, max_value=365),
        }
    )


def _property_strategy() -> st.SearchStrategy[dict[str, Any]]:
    return st.fixed_dictionaries(
        {
            "name": st.text(min_size=1, max_size=25).filter(
                lambda s: s.strip() != ""
            ),
            "address_text": st.text(min_size=1, max_size=40).filter(
                lambda s: s.strip() != ""
            ),
            "has_details": st.booleans(),
            "has_note": st.booleans(),
            # usage keyed by year in the seeder, so dedupe there.
            "usage": st.lists(_usage_strategy(), max_size=4),
            "transactions": st.lists(_transaction_strategy(), max_size=5),
            "assets": st.lists(_asset_strategy(), max_size=3),
        }
    )


_dataset_strategy = st.lists(_property_strategy(), min_size=1, max_size=4)


# --- Seeding through the real services ---------------------------------------


def _seed_dataset(
    dataset: list[dict[str, Any]],
    *,
    repo: DynamoRepository,
    files: Any,
    user: UserContext,
    with_binaries: bool = False,
) -> dict[str, list[str]]:
    """Seed ``dataset`` through the real services; return collected s3 keys.

    When ``with_binaries`` is set, a photo is attached to each property and a
    receipt to each created transaction so Properties 6/7 have S3-backed rows.
    Returns ``{"photo_keys": [...], "receipt_keys": [...]}`` of every stored
    ``s3Key`` so the caller can assert on the exact purge set.
    """
    properties = PropertyService(repo, user)
    transactions = TransactionService(repo, files)
    depreciation = DepreciationService(repo)
    photos = PhotoService(repo, files)

    photo_keys: list[str] = []
    receipt_keys: list[str] = []

    for spec in dataset:
        details = None
        if spec["has_details"]:
            details = PropertyDetails(
                formatted_address=spec["address_text"],
                latitude=Decimal("39.781721"),
                longitude=Decimal("-89.650148"),
                year_built=1998,
                last_sale_price=Decimal("245000.00"),
                tax_assessments=[
                    TaxAssessment(year=2023, value=Decimal("230000.00"))
                ],
            )
        created = properties.create(
            PropertyInput(
                name=spec["name"],
                address_text=spec["address_text"],
                property_type="single_family",
                details=details,
            )
        )
        assert created.is_ok
        prop = created.value

        if spec["has_note"]:
            assert properties.set_note(prop.id, "A note.").is_ok

        for usage in {u["tax_year"]: u for u in spec["usage"]}.values():
            assert properties.set_usage_days(
                prop.id,
                usage["tax_year"],
                usage["fair_rental_days"],
                usage["personal_use_days"],
            ).is_ok

        for txn_spec in spec["transactions"]:
            kindcat = txn_spec["kindcat"]
            created_txn = transactions.create(
                TransactionInput(
                    property_id=prop.id,
                    date=txn_spec["date"],
                    amount=txn_spec["amount"],
                    type=kindcat["type"],
                    category_id=kindcat["category_id"],
                    description=None,
                )
            )
            assert created_txn.is_ok, created_txn.error
            if with_binaries:
                attached = transactions.attach_receipt(
                    prop.id,
                    created_txn.value.id,
                    "receipt.pdf",
                    "application/pdf",
                )
                assert attached.is_ok
                receipt_keys.append(attached.value.document.s3_key)

        for asset_spec in spec["assets"]:
            created_asset = depreciation.create_asset(
                AssetInput(
                    property_id=prop.id,
                    description=asset_spec["description"],
                    cost_basis=asset_spec["cost_basis"],
                    placed_in_service_date=asset_spec["placed_in_service_date"],
                    recovery_period_years=Decimal("27.5"),
                )
            )
            assert created_asset.is_ok

        if with_binaries:
            upload = photos.request_upload(prop.id, "photo.jpg", "image/jpeg")
            assert upload.is_ok
            photo_keys.append(upload.value.photo.s3_key)

    return {"photo_keys": photo_keys, "receipt_keys": receipt_keys}


# --- Store inspection helpers ------------------------------------------------


def _user_rows(repo: DynamoRepository, user_id: str) -> list[dict[str, Any]]:
    """All rows in the user partition (property list rows + profile)."""
    return repo.query(keys.user_pk(user_id))


def _all_property_partition_rows(
    repo: DynamoRepository, property_ids: list[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for property_id in property_ids:
        rows.extend(repo.query(keys.property_scoped_pk(property_id)))
    return rows


def _list_property_ids_before_clear(repo: DynamoRepository, user: UserContext) -> list[str]:
    """The user's owned property ids, read the same way clear enumerates them."""
    return [p.id for p in PropertyService(repo, user).list()]


# --- Property 5 --------------------------------------------------------------

# Feature: backup-restore, Property 5: Clear empties the user's store


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(dataset=_dataset_strategy)
def test_clear_empties_the_users_store(dataset: list[dict[str, Any]]) -> None:
    """After clear, no rows remain in the user or any property partition."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _make_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)

        _seed_dataset(dataset, repo=repo, files=files, user=user)

        # Property ids owned by the user, captured before the wipe.
        property_ids = _list_property_ids_before_clear(repo, user)

        # Precondition: something really was seeded across the partitions.
        assert property_ids
        assert _all_property_partition_rows(repo, property_ids)

        result = BackupService(repo, files, user).clear()
        assert result.is_ok

        # User partition: no property list rows remain (any residual PROFILE
        # row is not property data and is not created by the seeding here).
        remaining_user_rows = [
            row
            for row in _user_rows(repo, USER_ID)
            if str(row.get("SK", "")).startswith(keys.PROP_PREFIX)
        ]
        assert remaining_user_rows == []

        # Every property partition is empty across every SK prefix.
        for property_id in property_ids:
            partition_rows = repo.query(keys.property_scoped_pk(property_id))
            assert partition_rows == [], (
                f"property {property_id} still has rows: "
                f"{[r.get('SK') for r in partition_rows]}"
            )
            # And explicitly per prefix, so a regression names the leftover kind.
            for prefix in _PROPERTY_SK_PREFIXES:
                leftover = repo.query(
                    keys.property_scoped_pk(property_id),
                    sk_begins_with=prefix,
                )
                assert leftover == [], (
                    f"property {property_id} still has {prefix!r} rows"
                )
            # META row gone too.
            assert (
                repo.get_item(
                    keys.property_scoped_pk(property_id), keys.META_SK
                )
                is None
            )


# --- Property 6 --------------------------------------------------------------

# Feature: backup-restore, Property 6: Clear removes every S3 binary together with its metadata row


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(dataset=_dataset_strategy)
def test_clear_removes_every_s3_binary_with_its_metadata_row(
    dataset: list[dict[str, Any]],
) -> None:
    """delete_object is called for every s3Key; no PHOTO#/#DOC# rows survive."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _make_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        # Real adapter only used for seeding (issuing pre-signed URLs); the
        # clear path runs against the recording fake so we can assert on it.
        seed_files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)

        seeded = _seed_dataset(
            dataset, repo=repo, files=seed_files, user=user, with_binaries=True
        )
        expected_keys = set(seeded["photo_keys"]) | set(seeded["receipt_keys"])

        property_ids = _list_property_ids_before_clear(repo, user)

        recorder = RecordingS3Fake()
        result = BackupService(repo, recorder, user).clear()
        assert result.is_ok

        # Every stored s3Key had delete_object invoked exactly for it.
        assert set(recorder.deleted) == expected_keys
        # No key deleted that we did not seed.
        assert set(recorder.attempted) == expected_keys

        # Summary counts match the seeded binaries.
        summary = result.value
        assert summary.photos == len(seeded["photo_keys"])
        assert summary.receipts == len(seeded["receipt_keys"])
        assert summary.failed_s3_keys == []

        # No orphaned PHOTO# or #DOC# metadata rows remain.
        for property_id in property_ids:
            photo_rows = repo.query(
                keys.property_scoped_pk(property_id),
                sk_begins_with=keys.PHOTO_PREFIX,
            )
            assert photo_rows == []
            doc_rows = [
                row
                for row in repo.query(keys.property_scoped_pk(property_id))
                if keys.DOC_PREFIX in str(row.get("SK", ""))
            ]
            assert doc_rows == []


# --- Property 7 --------------------------------------------------------------

# Feature: backup-restore, Property 7: Clear continues past individual S3 delete failures and reports them


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(dataset=_dataset_strategy, fail_seed=st.randoms(use_true_random=False))
def test_clear_continues_past_s3_delete_failures(
    dataset: list[dict[str, Any]], fail_seed: Any
) -> None:
    """All metadata rows still deleted; failed_s3_keys == the failing subset."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _make_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        seed_files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)

        seeded = _seed_dataset(
            dataset, repo=repo, files=seed_files, user=user, with_binaries=True
        )
        all_keys = list(seeded["photo_keys"]) + list(seeded["receipt_keys"])

        # Choose a random subset of keys whose S3 delete will fail.
        fail_keys = frozenset(
            key for key in all_keys if fail_seed.random() < 0.5
        )

        property_ids = _list_property_ids_before_clear(repo, user)

        recorder = RecordingS3Fake(fail_keys=fail_keys)
        result = BackupService(repo, recorder, user).clear()
        assert result.is_ok

        # Best-effort: every key was attempted; only the non-failing ones
        # actually "deleted"; failures are reported exactly.
        assert set(recorder.attempted) == set(all_keys)
        assert set(result.value.failed_s3_keys) == set(fail_keys)
        # No duplicates in the reported failure list.
        assert len(result.value.failed_s3_keys) == len(set(fail_keys))

        # Despite S3 failures, ALL metadata rows are deleted — the store is
        # empty (a failed S3 delete never blocks a row delete).
        for property_id in property_ids:
            assert repo.query(keys.property_scoped_pk(property_id)) == []
        remaining_user_rows = [
            row
            for row in _user_rows(repo, USER_ID)
            if str(row.get("SK", "")).startswith(keys.PROP_PREFIX)
        ]
        assert remaining_user_rows == []
