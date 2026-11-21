"""Backup tests for the transaction ``imported`` marker (itemized-expenses Req 20).

# Feature: itemized-expenses, Property 20: Backup round trip preserves the imported marker

**Validates: Requirements 20.1, 20.2, 20.3, 20.4, 20.5**

Also covers, as examples, an older backup without ``imported`` restoring with
``imported = false`` (Req 20.2) and restore followed by Schedule E re-import
leaving exactly one total row (Req 20.6).
"""

from __future__ import annotations

import uuid
from typing import Any

import boto3
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _to_jsonable
from logstead.services.backup import BackupService
from logstead.services.schedule_e_import import ImportService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"
TS = "2024-01-01T00:00:00+00:00"


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


@pytest.fixture
def env():
    with mock_aws():
        _create_store()
        repo = DynamoRepository(boto3.client("dynamodb", region_name=REGION), TABLE_NAME)
        files = S3FileAdapter(boto3.client("s3", region_name=REGION), BUCKET)
        user = UserContext(user_id=USER_ID)
        yield repo, files, user


def _txn(property_id: str, **overrides: Any) -> dict[str, Any]:
    txn: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "property_id": property_id,
        "date": "2023-12-31",
        "amount": "100.00",
        "type": "expense",
        "category_id": "repairs",
        "description": None,
        "created_at": TS,
        "updated_at": TS,
    }
    txn.update(overrides)
    return txn


def _doc(transactions: list[dict[str, Any]], property_id: str = "prop-1") -> dict:
    return {
        "schema_version": "1",
        "exported_at": TS,
        "properties": [
            {
                "id": property_id,
                "name": "Maple",
                "address_text": "123 Maple St",
                "transactions": transactions,
            }
        ],
    }


def _exported_txns(service: BackupService) -> list[dict[str, Any]]:
    raw = _to_jsonable(service.export())
    assert raw["schema_version"] == "1"
    return [t for p in raw["properties"] for t in p["transactions"]]


# Feature: itemized-expenses, Property 20: Backup round trip preserves the imported marker
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    flags=st.lists(st.booleans(), min_size=0, max_size=6),
    use_key=st.lists(st.booleans(), min_size=6, max_size=6),
)
def test_round_trip_preserves_imported_marker(
    flags: list[bool], use_key: list[bool]
) -> None:
    """**Validates: Requirements 20.1, 20.5**"""
    with mock_aws():
        _create_store()
        repo = DynamoRepository(boto3.client("dynamodb", region_name=REGION), TABLE_NAME)
        files = S3FileAdapter(boto3.client("s3", region_name=REGION), BUCKET)
        service = BackupService(repo, files, UserContext(user_id=USER_ID))

        txns = []
        for flag in flags:
            txns.append(_txn("prop-1", imported=flag))
        expected = {t["id"]: t["imported"] for t in txns}
        # An absent key must behave exactly like an explicit false (Req 20.2).
        for t, keep in zip(txns, use_key):
            if not t["imported"] and not keep:
                del t["imported"]

        assert service.restore(_doc(txns)).is_ok
        first = _exported_txns(service)
        assert {t["id"]: t["imported"] for t in first} == expected

        # Export -> restore -> export reproduces the marker (Req 20.5).
        assert service.restore(_doc(first)).is_ok
        second = _exported_txns(service)
        assert {t["id"]: t["imported"] for t in second} == expected


def test_older_backup_without_imported_restores_false(env) -> None:
    """Req 20.2: a transaction lacking ``imported`` restores as not imported."""
    repo, files, user = env
    service = BackupService(repo, files, user)
    txn = _txn("prop-1")
    assert "imported" not in txn

    assert service.restore(_doc([txn])).is_ok

    [stored] = _exported_txns(service)
    assert stored["imported"] is False


@pytest.mark.parametrize("bad", ["true", 1, 0, [], {}])
def test_non_boolean_imported_rejected_and_nothing_written(env, bad) -> None:
    """Req 20.3: non-boolean ``imported`` is a validation error on ``imported``."""
    repo, files, user = env
    service = BackupService(repo, files, user)

    result = service.restore(_doc([_txn("prop-1", imported=bad)]))

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "imported"
    assert _to_jsonable(service.export())["properties"] == []


def test_imported_and_itemized_rejected_and_nothing_written(env) -> None:
    """Req 20.4: imported and itemized together is a validation error."""
    repo, files, user = env
    service = BackupService(repo, files, user)
    txn = _txn("prop-1", imported=True, itemized=True)

    result = service.restore(_doc([txn]))

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "itemized"
    assert _to_jsonable(service.export())["properties"] == []


def test_restore_then_reimport_leaves_one_total_row(env) -> None:
    """Req 20.6: re-import replaces the restored imported row, no duplicate."""
    repo, files, user = env
    service = BackupService(repo, files, user)
    restored_txn = _txn("prop-1", imported=True, amount="500.00")
    assert service.restore(_doc([restored_txn])).is_ok

    outcome = ImportService(repo, user, files).import_schedule_e(
        ImportSubmission(
            tax_year=2023,
            entries=[
                PropertyEntryInput(
                    property_id="prop-1",
                    lines=[LineAmountInput(schedule_e_line=14, amount="750.00")],
                )
            ],
        )
    )
    assert outcome.is_ok, outcome.error
    assert outcome.value.entries[0].deleted_prior_count == 1

    rows = [t for t in _exported_txns(service) if t["category_id"] == "repairs"]
    assert len(rows) == 1
    assert rows[0]["imported"] is True
    assert rows[0]["amount"] == "750.00"
    assert rows[0]["id"] != restored_txn["id"]
