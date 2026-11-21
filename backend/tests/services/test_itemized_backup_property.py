"""Backup tests for itemized entries and notes (itemized-expenses Req 12).

# Feature: itemized-expenses, Property 14: Backup round trip preserves itemized data
# Feature: itemized-expenses, Property 15: Restore rejects invalid itemized fields and writes nothing

**Validates: Requirements 12.4, 12.6, 12.7, 12.8**

Also covers, as examples, a legacy document without ``itemized``/``notes``
(Req 12.6) and the unchanged sample fixture (Req 12.8).
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _to_jsonable
from logstead.services.backup import BackupService, validate_document
from logstead.services.itemized import LineAccumulator

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"
TS = "2024-01-01T00:00:00+00:00"
NOTES_MAX = 1000


def _create_store() -> None:
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
                "IndexName": name,
                "KeySchema": [
                    {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name in ("GSI1", "GSI2")
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)


def _service() -> BackupService:
    repo = DynamoRepository(boto3.client("dynamodb", region_name=REGION), TABLE_NAME)
    files = S3FileAdapter(boto3.client("s3", region_name=REGION), BUCKET)
    return BackupService(repo, files, UserContext(user_id=USER_ID))


@pytest.fixture
def service():
    with mock_aws():
        _create_store()
        yield _service()


def _txn(property_id: str, **overrides: Any) -> dict[str, Any]:
    txn: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "property_id": property_id,
        "date": "2023-06-15",
        "amount": "100.00",
        "type": "expense",
        "category_id": "repairs",
        "description": None,
        "created_at": TS,
        "updated_at": TS,
    }
    txn.update(overrides)
    return txn


def _doc(transactions_by_property: dict[str, list[dict[str, Any]]]) -> dict:
    return {
        "schema_version": "1",
        "exported_at": TS,
        "properties": [
            {
                "id": pid,
                "name": f"Prop {pid}",
                "address_text": "123 Maple St",
                "transactions": txns,
            }
            for pid, txns in transactions_by_property.items()
        ],
    }


def _export(service: BackupService) -> dict:
    raw = _to_jsonable(service.export())
    assert raw["schema_version"] == "1"
    return raw


def _rows(raw: dict) -> dict[str, tuple]:
    return {
        t["id"]: (
            p["id"],
            t["date"],
            t["amount"],
            t["type"],
            t["category_id"],
            t["itemized"],
            t["notes"],
        )
        for p in raw["properties"]
        for t in p["transactions"]
    }


def _line_totals(raw: dict) -> dict[tuple[str, int, str], Decimal]:
    """Resolved total per (property, tax year, category) via the precedence rule."""
    accs: dict[tuple[str, int, str], LineAccumulator] = defaultdict(LineAccumulator)
    for p in raw["properties"]:
        for t in p["transactions"]:
            if t["type"] != "expense":
                continue
            key = (p["id"], int(t["date"][:4]), t["category_id"])
            accs[key].add(
                Decimal(t["amount"]),
                itemized=t["itemized"],
                imported=t.get("imported", False),
            )
    return {k: a.resolve().line_total for k, a in accs.items()}


# --- strategies --------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2
).map(str)
_dates = st.sampled_from(["2022-03-01", "2023-06-15", "2023-12-31", "2024-01-02"])
_notes = st.one_of(
    st.none(),
    st.text(alphabet="abcdefghij XYZ0123", min_size=1, max_size=40),
)


@st.composite
def _txn_strategy(draw: st.DrawFn, property_id: str) -> dict[str, Any]:
    kind = draw(st.sampled_from(["total", "itemized", "other", "income"]))
    base = {
        "date": draw(_dates),
        "amount": draw(_amounts),
    }
    if kind == "itemized":
        return _txn(
            property_id, **base, itemized=True, notes=draw(_notes),
        )
    if kind == "total":
        return _txn(property_id, **base, itemized=False, notes=draw(_notes))
    if kind == "other":
        return _txn(property_id, **base, category_id="insurance")
    return _txn(property_id, **base, type="income", category_id="rents-received")


@st.composite
def _datasets(draw: st.DrawFn) -> dict[str, list[dict[str, Any]]]:
    pids = draw(st.lists(st.sampled_from(["prop-a", "prop-b"]), unique=True,
                         min_size=1, max_size=2))
    return {pid: draw(st.lists(_txn_strategy(pid), max_size=8)) for pid in pids}


_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# Feature: itemized-expenses, Property 14: Backup round trip preserves itemized data
@_SETTINGS
@given(data=_datasets())
def test_round_trip_preserves_itemized_data(data) -> None:
    """**Validates: Requirements 12.4, 12.8**"""
    with mock_aws():
        _create_store()
        service = _service()
        assert service.restore(_doc(data)).is_ok

        first = _export(service)
        expected = {
            t["id"]: (
                pid,
                t["date"],
                t["amount"],
                t["type"],
                t["category_id"],
                t.get("itemized", False),
                t.get("notes"),
            )
            for pid, txns in data.items()
            for t in txns
        }
        assert _rows(first) == expected

        # Export -> restore -> export reproduces rows, markers, notes, totals.
        assert service.restore(first).is_ok
        second = _export(service)
        assert second["schema_version"] == "1"
        assert _rows(second) == _rows(first)
        assert _line_totals(second) == _line_totals(first)


# Feature: itemized-expenses, Property 15: Restore rejects invalid itemized fields and writes nothing
_invalid_cases = st.one_of(
    st.sampled_from(
        [
            ({"itemized": True, "category_id": "insurance"}, "itemized"),
            ({"itemized": True, "category_id": "taxes"}, "itemized"),
            ({"itemized": True, "type": "income",
              "category_id": "rents-received"}, "itemized"),
        ]
    ),
    st.sampled_from(["true", 1, 0, "", [], {}]).map(
        lambda v: ({"itemized": v}, "itemized")
    ),
    st.one_of(
        st.sampled_from([5, True, [], {}, 1.5]),
        st.integers(min_value=NOTES_MAX + 1, max_value=NOTES_MAX + 50).map(
            lambda n: "n" * n
        ),
    ).map(lambda v: ({"notes": v}, "notes")),
)


@_SETTINGS
@given(
    case=_invalid_cases,
    position=st.integers(min_value=0, max_value=2),
    valid_count=st.integers(min_value=0, max_value=2),
)
def test_restore_rejects_invalid_itemized_fields(case, position, valid_count) -> None:
    """**Validates: Requirements 12.6, 12.7**"""
    overrides, field = case
    with mock_aws():
        _create_store()
        service = _service()

        # Pre-existing stored data that must stay unchanged.
        existing = [_txn("prop-old", itemized=True, notes="keep")]
        assert service.restore(_doc({"prop-old": existing})).is_ok
        before = _export(service)

        txns = [_txn("prop-1") for _ in range(valid_count)]
        txns.insert(min(position, len(txns)), _txn("prop-1", **overrides))
        result = service.restore(_doc({"prop-1": txns}))

        assert not result.is_ok
        assert result.error.kind == "validation"
        assert result.error.field == field
        assert _export(service)["properties"] == before["properties"]


# --- examples ----------------------------------------------------------------


def test_legacy_document_without_fields_restores_unmarked(service) -> None:
    """Req 12.6: no ``itemized``/``notes`` keys restore as itemized=false, notes=None."""
    txn = _txn("prop-1")
    assert "itemized" not in txn and "notes" not in txn

    assert service.restore(_doc({"prop-1": [txn]})).is_ok

    [row] = _rows(_export(service)).values()
    assert row[5] is False
    assert row[6] is None


def test_unchanged_sample_fixture_restores_and_round_trips(service) -> None:
    """Req 12.8: the sample fixture (no new fields) still validates and round-trips."""
    path = Path(__file__).resolve().parents[3] / "frontend/src/data/sample-backup.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert "itemized" not in json.dumps(document)

    assert validate_document(document).is_ok
    assert service.restore(document).is_ok

    first = _export(service)
    rows = _rows(first)
    assert rows and all(r[5] is False and r[6] is None for r in rows.values())
    assert service.restore(first).is_ok
    assert _rows(_export(service)) == rows
