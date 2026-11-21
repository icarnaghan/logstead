"""ActivityRecorder: item shape, best-effort recording, purge scopes (moto)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.activity import ActivityRecorder, NewEvent
from logstead.services.activity_config import ACTIVITY_CONFIG

TABLE = "Logstead"
AT = datetime(2025, 3, 4, 5, 6, 7, 891000, tzinfo=timezone.utc)


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK")
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
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoRepository(ddb, TABLE)


def _recorder(repo, user="u1", **kw):
    return ActivityRecorder(repo, user, clock=lambda: AT, **kw)


def _event(**kw):
    base = dict(
        action="delete",
        entity="asset",
        summary="Deleted asset: Fridge",
        record_id="a1",
        property_id="p1",
        property_name="Main St",
        before={"description": "Fridge"},
        restorable=True,
        restore_payload={"description": "Fridge", "cost_basis": "100.00"},
    )
    base.update(kw)
    return NewEvent(**base)


def _acts(repo, user="u1"):
    return repo.query(keys.user_pk(user), sk_begins_with="ACT#", money_attrs=set())


def test_item_shape_restorable_delete(repo):
    _recorder(repo).record(_event())
    (item,) = _acts(repo)
    assert item["PK"] == "USER#u1"
    assert item["SK"] == keys.activity_sk(AT, item["eventId"])
    assert item["GSI1PK"] == "PROPERTY#p1" and item["GSI1SK"] == item["SK"]
    assert item["entityType"] == "ACTIVITY"
    assert item["at"] == "2025-03-04T05:06:07.891Z"
    assert (item["action"], item["entity"], item["recordId"]) == ("delete", "asset", "a1")
    assert item["propertyId"] == "p1" and item["propertyName"] == "Main St"
    assert json.loads(item["beforeJson"]) == {"description": "Fridge"}
    assert "afterJson" not in item and "truncated" not in item
    assert item["restorable"] is True
    assert json.loads(item["restorePayload"])["cost_basis"] == "100.00"
    assert int(item["ttl"]) == int(
        (AT + timedelta(days=ACTIVITY_CONFIG.retention_days)).timestamp()
    )


def test_non_restorable_event_has_no_payload_and_backup_has_no_gsi(repo):
    ev = NewEvent(
        action="import", entity="backup", summary="Restored from backup",
        restorable=False, restore_payload={"x": "y"},
    )
    _recorder(repo).record(ev)
    (item,) = _acts(repo)
    for absent in ("restorable", "restorePayload", "GSI1PK", "GSI1SK", "propertyId", "recordId"):
        assert absent not in item


def test_oversized_restore_payload_is_not_stored_as_restorable(repo):
    big = {"description": "x" * 5000}
    _recorder(repo).record(_event(restore_payload=big))
    (item,) = _acts(repo)
    assert "restorable" not in item and "restorePayload" not in item


def test_long_values_are_truncated_and_flagged(repo):
    _recorder(repo).record(_event(before={"description": "y" * 500}))
    (item,) = _acts(repo)
    assert item["truncated"] is True
    assert len(json.loads(item["beforeJson"])["description"]) == ACTIVITY_CONFIG.value_max_chars


def test_one_write_per_event():
    calls = []

    class Spy:
        def put_item(self, item, **kw):
            calls.append(item)

    _recorder(Spy()).record(_event())
    assert len(calls) == 1


def test_failure_is_swallowed_and_logged(caplog):
    class Boom:
        def put_item(self, item, **kw):
            raise RuntimeError("secret amount 123.45")

    with caplog.at_level(logging.WARNING):
        _recorder(Boom()).record(_event())
    (rec,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "activity_record_failed" in rec.getMessage()
    assert "secret" not in rec.getMessage()


def test_malformed_event_does_not_raise():
    _recorder(object()).record(None)  # type: ignore[arg-type]


def test_purge_user_removes_only_that_users_events(repo):
    _recorder(repo, "u1").record(_event())
    _recorder(repo, "u1").record(_event(property_id="p2"))
    _recorder(repo, "u2").record(_event())
    repo.put_item({"PK": "USER#u1", "SK": "PROP#keep"})
    assert _recorder(repo, "u1").purge_user() == 2
    assert _acts(repo, "u1") == [] and len(_acts(repo, "u2")) == 1
    assert repo.get_item("USER#u1", "PROP#keep") is not None


def test_purge_property_removes_only_that_property(repo):
    r = _recorder(repo)
    r.record(_event(property_id="p1"))
    r.record(_event(property_id="p2"))
    r.record(NewEvent(action="import", entity="backup", summary="b"))
    assert r.purge_property("p1") == 1
    assert sorted(i["propertyId"] for i in _acts(repo) if "propertyId" in i) == ["p2"]
    assert len(_acts(repo)) == 2


def test_purge_batches_over_25(repo):
    r = _recorder(repo)
    for _ in range(60):
        r.record(_event())
    # Same clock tick, distinct uuids: 60 distinct items.
    assert len(_acts(repo)) == 60
    assert r.purge_user() == 60
    assert _acts(repo) == []
