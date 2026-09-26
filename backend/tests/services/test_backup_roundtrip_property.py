"""Task 6.1 — Property 1: backup round-trip preserves ids, timestamps, money,
coordinates, and structure.

# Feature: backup-restore, Property 1: Backup round-trip preserves ids, timestamps, money, coordinates, and structure

Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.2, 2.3, 2.4, 13.1,
13.2, 13.3, 13.4

For any valid dataset owned by a user, exporting to a Backup_Document,
restoring that document, and re-exporting produces a document equivalent to the
first (after canonical ordering): every property, transaction, asset, usage
year, note, and details subtree has an identical ``id``, identical
``created_at``/``updated_at``, identical ``property_id`` cross-references, and
money and coordinate values that are string-identical.

Strategy
--------
Hypothesis generates an arbitrary valid dataset — properties with sparse details
(reusing the shape of the existing ``property_details`` strategy from
``tests/repository/test_property_details_roundtrip.py``, but with money fields
constrained to exact two-decimal amounts so they survive the money
quantization boundary string-identically), an optional note, usage years,
transactions with catalog categories and two-decimal amounts, and assets with a
positive cost basis.

The dataset is seeded into a fresh moto store by **restoring a generated valid
document** — the simplest way to reach a clean arbitrary starting state, which
also exercises restore's id/timestamp-preserving write path. Then:

    export() -> BackupDocument  (doc1)
    restore(_to_jsonable(doc1)) -> Result[RestoreSummary]
    export() -> BackupDocument  (doc2)

and doc1 / doc2 are asserted canonically deep-equal after serializing both
through the router's ``_to_jsonable`` (which renders every ``Decimal`` as its
exact decimal string). Canonicalization sorts properties by id, and each
property's usage/transactions/assets by their natural key, so ordering never
causes a spurious mismatch.

``restore`` takes the raw JSON dict shape the validator accepts, so the first
``BackupDocument`` is serialized via ``_to_jsonable`` before being fed back in.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.user import UserContext
from logstead.router.handler import _to_jsonable
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.backup import BackupService
from logstead.services.category import CATEGORY_CATALOG

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"

_CATEGORY_IDS = tuple(c.id for c in CATEGORY_CATALOG)


# --- Generators ---------------------------------------------------------------
#
# Every generated value lands in the shape ``validate_document`` accepts and
# that survives the export/restore/export round-trip string-identically:
#   * money  -> exact two-decimal strings (to_money is a no-op on them)
#   * coords -> bounded fixed-places decimal strings (full-precision preserved)
#   * ids    -> uuid4 strings (preserved verbatim by restore)
#   * timestamps -> ISO-8601 strings (written verbatim by restore)

_text = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")


def _uuid() -> st.SearchStrategy[str]:
    return st.builds(lambda: str(uuid.uuid4()))


# Two-decimal money as an exact string, e.g. "1234.56". Positive so asset cost
# basis and transaction amounts are always valid.
_money_str = st.builds(
    lambda cents: f"{Decimal(cents) / Decimal(100):.2f}",
    st.integers(min_value=1, max_value=99_999_999),
)

# A coordinate as a fixed-precision decimal string that round-trips verbatim
# through _decimal_str / Decimal (full precision preserved, no quantization).
_latitude = st.builds(
    lambda micro: f"{Decimal(micro) / Decimal(1_000_000):.6f}",
    st.integers(min_value=-90_000_000, max_value=90_000_000),
)
_longitude = st.builds(
    lambda micro: f"{Decimal(micro) / Decimal(1_000_000):.6f}",
    st.integers(min_value=-180_000_000, max_value=180_000_000),
)

_iso_timestamp = st.builds(
    lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(),
    st.integers(min_value=0, max_value=2_000_000_000_000),
)


def _opt(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Optional field: a present value or absent (``None``)."""
    return st.one_of(st.none(), strategy)


@st.composite
def _details(draw: st.DrawFn) -> dict[str, Any] | None:
    """A sparse details subtree in the on-wire dict shape ``details_to_dict``
    emits: money as two-decimal strings, coordinates as full-precision strings,
    ``None``/empty fields omitted. Returns ``None`` for a property with no
    stored details."""
    if draw(st.booleans()):
        return None

    out: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value is not None:
            out[key] = value

    put("formatted_address", draw(_opt(_text)))
    put("city", draw(_opt(_text)))
    put("state", draw(_opt(st.sampled_from(["CA", "NY", "TX", "WA", "IL"]))))
    put("zip_code", draw(_opt(st.from_regex(r"[0-9]{5}", fullmatch=True))))
    put("county", draw(_opt(_text)))
    put("latitude", draw(_opt(_latitude)))
    put("longitude", draw(_opt(_longitude)))
    put("year_built", draw(_opt(st.integers(min_value=1800, max_value=2100))))
    put("bedrooms", draw(_opt(st.integers(min_value=0, max_value=20))))
    put("last_sale_price", draw(_opt(_money_str)))

    assessments = draw(
        st.lists(
            st.builds(
                lambda year, value: {"year": year, "value": value},
                st.integers(min_value=1990, max_value=2100),
                _money_str,
            ),
            max_size=3,
        )
    )
    if assessments:
        out["tax_assessments"] = assessments

    return out


@st.composite
def _transaction(draw: st.DrawFn, property_id: str) -> dict[str, Any]:
    """A valid transaction dict for ``property_id``. ``category_id`` is drawn
    from the real catalog so validation and re-export both accept it."""
    year = draw(st.integers(min_value=2018, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))
    return {
        "id": draw(_uuid()),
        "property_id": property_id,
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "amount": draw(_money_str),
        "type": draw(st.sampled_from(["income", "expense"])),
        "category_id": draw(st.sampled_from(_CATEGORY_IDS)),
        "description": draw(_opt(_text)),
        "created_at": draw(_iso_timestamp),
        "updated_at": draw(_iso_timestamp),
    }


@st.composite
def _asset(draw: st.DrawFn, property_id: str) -> dict[str, Any]:
    """A valid depreciable asset dict with a positive cost basis."""
    year = draw(st.integers(min_value=2018, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))
    return {
        "id": draw(_uuid()),
        "property_id": property_id,
        "description": draw(_text),
        "cost_basis": draw(_money_str),
        "placed_in_service_date": f"{year:04d}-{month:02d}-{day:02d}",
        "recovery_period_years": draw(
            st.sampled_from(["27.5", "39", "5", "7", "15"])
        ),
        "created_at": draw(_iso_timestamp),
        "updated_at": draw(_iso_timestamp),
    }


@st.composite
def _usage_year(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "tax_year": draw(st.integers(min_value=2018, max_value=2025)),
        "fair_rental_days": draw(st.integers(min_value=0, max_value=365)),
        "personal_use_days": draw(st.integers(min_value=0, max_value=365)),
    }


@st.composite
def _property(draw: st.DrawFn) -> dict[str, Any]:
    property_id = draw(_uuid())

    # Usage years must be unique per tax_year (one USAGE#<year> row per year).
    usage_years = draw(
        st.lists(_usage_year(), max_size=4, unique_by=lambda u: u["tax_year"])
    )
    transactions = draw(
        st.lists(_transaction(property_id), max_size=5)
    )
    assets = draw(st.lists(_asset(property_id), max_size=3))

    prop: dict[str, Any] = {
        "id": property_id,
        "name": draw(_text),
        "address_text": draw(_text),
        "property_type": draw(
            _opt(st.sampled_from(["single_family", "multi_family", "condo"]))
        ),
        "created_at": draw(_iso_timestamp),
        "updated_at": draw(_iso_timestamp),
        "usage": usage_years,
        "transactions": transactions,
        "assets": assets,
    }
    details = draw(_details())
    if details is not None:
        prop["details"] = details
    note = draw(_opt(_text))
    if note is not None:
        prop["note"] = note
    return prop


@st.composite
def _valid_document(draw: st.DrawFn) -> dict[str, Any]:
    """An arbitrary valid Backup_Document in the raw JSON dict shape the
    validator accepts (schema_version "1", unique property ids)."""
    properties = draw(
        st.lists(_property(), max_size=3, unique_by=lambda p: p["id"])
    )
    return {
        "schema_version": "1",
        "exported_at": draw(_iso_timestamp),
        "properties": properties,
    }


# --- Canonicalization ---------------------------------------------------------


def _canonical(doc: dict[str, Any]) -> dict[str, Any]:
    """Canonically order a serialized document so equality ignores ordering.

    Properties are sorted by id; each property's usage/transactions/assets by
    their natural keys. ``exported_at`` is dropped — it is a fresh timestamp per
    export and intentionally not part of the round-trip identity.
    """
    props = []
    for prop in sorted(doc.get("properties", []), key=lambda p: p["id"]):
        canon = dict(prop)
        canon["usage"] = sorted(
            prop.get("usage", []), key=lambda u: u["tax_year"]
        )
        canon["transactions"] = sorted(
            prop.get("transactions", []), key=lambda t: t["id"]
        )
        canon["assets"] = sorted(
            prop.get("assets", []), key=lambda a: a["id"]
        )
        props.append(canon)
    return {"schema_version": doc.get("schema_version"), "properties": props}


# --- Store fixtures -----------------------------------------------------------


def _create_store():
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
    return ddb, s3


# --- The property -------------------------------------------------------------


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(document=_valid_document())
def test_backup_round_trip_is_identity(document: dict[str, Any]) -> None:
    # Fresh moto store per example keeps examples independent.
    with mock_aws():
        _create_store()
        ddb = boto3.client("dynamodb", region_name=REGION)
        s3 = boto3.client("s3", region_name=REGION)
        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)
        service = BackupService(repo, files, user)

        # Seed a clean arbitrary starting state by restoring the generated
        # valid document (also exercises restore's id/timestamp-preserving
        # write path).
        seed = service.restore(document)
        assert seed.is_ok, (
            f"seeding restore failed: "
            f"{seed.error.message if seed.error else '?'}"
        )

        # export -> restore(serialized) -> export.
        doc1 = service.export()
        raw1 = _to_jsonable(doc1)

        restored = service.restore(raw1)
        assert restored.is_ok, (
            f"round-trip restore failed: "
            f"{restored.error.message if restored.error else '?'}"
        )

        doc2 = service.export()
        raw2 = _to_jsonable(doc2)

        # Canonically deep-equal: identical ids, timestamps, money strings,
        # coordinate strings, cross-references, and structure.
        assert _canonical(raw1) == _canonical(raw2)
