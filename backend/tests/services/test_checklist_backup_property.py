"""Property test: edited classification survives backup and restore.

# Feature: year-end-checklist, Property 15: Edited classification survives backup and restore

**Validates: Requirements 14.3, 14.4**
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router.handler import _to_jsonable
from logstead.services.backup import BackupService
from logstead.services.checklist import is_edited
from logstead.services.transaction import TransactionService
from tests.services.test_backup_imported_property import (
    BUCKET,
    REGION,
    TABLE_NAME,
    USER_ID,
    _create_store,
)

BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# (offset seconds of updated_at relative to created_at): equal, later, earlier.
_pair = st.tuples(
    st.integers(min_value=0, max_value=10_000),
    st.sampled_from([0, 1, 59, 3600, 86_400 * 30, -1, -3600]),
)


def _txn(created: str, updated: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "property_id": "prop-1",
        "date": "2023-12-31",
        "amount": "100.00",
        "type": "expense",
        "category_id": "repairs",
        "description": None,
        "imported": True,
        "created_at": created,
        "updated_at": updated,
    }


def _doc(transactions: list[dict[str, Any]]) -> dict:
    return {
        "schema_version": "1",
        "exported_at": BASE.isoformat(),
        "properties": [
            {
                "id": "prop-1",
                "name": "Maple",
                "address_text": "123 Maple St",
                "transactions": transactions,
            }
        ],
    }


def _classification(txns_service: TransactionService) -> dict[str, tuple[bool, bool]]:
    result = txns_service.list_for_property("prop-1", 2023)
    assert result.is_ok, result.error
    return {t.id: (t.imported, is_edited(t)) for t in result.value}


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(pairs=st.lists(_pair, min_size=1, max_size=5))
def test_edited_classification_survives_backup_and_restore(pairs) -> None:
    """**Validates: Requirements 14.3, 14.4**"""
    txns = []
    for start, delta in pairs:
        created = BASE + timedelta(seconds=start)
        updated = created + timedelta(seconds=delta)
        txns.append(_txn(created.isoformat(), updated.isoformat()))

    with mock_aws():
        _create_store()
        repo = DynamoRepository(boto3.client("dynamodb", region_name=REGION), TABLE_NAME)
        files = S3FileAdapter(boto3.client("s3", region_name=REGION), BUCKET)
        user = UserContext(user_id=USER_ID)
        backup = BackupService(repo, files, user)
        reader = TransactionService(repo, files)

        # Seed through a first restore, then classify the stored rows.
        assert backup.restore(_doc(txns)).is_ok
        before = _classification(reader)
        assert len(before) == len(txns)

        # Export, wipe, restore the exported document, classify again.
        exported = _to_jsonable(backup.export())
        assert backup.restore(exported).is_ok
        after = _classification(reader)

        assert after == before
        expected = {
            t["id"]: (True, datetime.fromisoformat(t["updated_at"]) > datetime.fromisoformat(t["created_at"]))
            for t in txns
        }
        assert after == expected
