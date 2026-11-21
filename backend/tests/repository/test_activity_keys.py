"""Activity key helpers and the repository start-key / conditional-put seams."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import ConditionFailed, DynamoRepository

TABLE_NAME = "Logstead"
SERVICES_DIR = Path(__file__).resolve().parents[2] / "src" / "logstead" / "services"


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
        yield DynamoRepository(ddb, TABLE_NAME)


def test_activity_key_format():
    at = datetime(2025, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc)
    epoch_ms = int(at.timestamp() * 1000)
    sk = keys.activity_sk(at, "abc")
    assert sk == f"ACT#{99999999999999 - epoch_ms:014d}#abc"
    assert re.fullmatch(r"ACT#\d{14}#abc", sk)
    assert keys.activity_list_prefix() == "ACT#" == keys.ACT_PREFIX
    assert keys.activity_gsi1_pk("p1") == keys.property_scoped_pk("p1") == "PROPERTY#p1"


def test_newer_events_sort_first():
    older = keys.activity_sk(datetime(2024, 1, 1, tzinfo=timezone.utc), "a")
    newer = keys.activity_sk(datetime(2024, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc), "b")
    assert newer < older


def test_act_prefix_collides_with_no_existing_prefix():
    others = [
        v
        for name, v in vars(keys).items()
        if name.endswith("_PREFIX") and name != "ACT_PREFIX" and isinstance(v, str)
    ]
    others += [keys.PROFILE_SK, keys.META_SK, keys.DETAILS_SK, keys.NOTE_SK, keys.PLCF_OPENING_SK]
    for other in others:
        assert not other.startswith(keys.ACT_PREFIX)
        assert not keys.ACT_PREFIX.startswith(other)


def _call_text(src: str, start: int) -> str:
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "(":
            depth += 1
        elif src[i] == ")":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return src[start:]


def test_every_user_partition_query_uses_a_prefix():
    checked = 0
    for path in SERVICES_DIR.glob("*.py"):
        src = path.read_text()
        for m in re.finditer(r"\.query\(", src):
            call = _call_text(src, m.end() - 1)
            if "user_pk(" in call:
                checked += 1
                assert "sk_begins_with" in call, f"{path.name}: unprefixed USER# query"
    assert checked > 0


def test_start_key_pages_from_after_the_key(repo):
    for i in range(5):
        repo.put_item({"PK": "USER#u", "SK": f"ACT#{i}"})
    first = repo.query("USER#u", sk_begins_with="ACT#", limit=2)
    assert [r["SK"] for r in first] == ["ACT#0", "ACT#1"]
    rest = repo.query(
        "USER#u",
        sk_begins_with="ACT#",
        start_key={"PK": "USER#u", "SK": first[-1]["SK"]},
    )
    assert [r["SK"] for r in rest] == ["ACT#2", "ACT#3", "ACT#4"]


def test_conditional_put_success_then_failure(repo):
    item = {"PK": "USER#u", "SK": "ACT#1", "n": "one"}
    cond = dict(condition="attribute_not_exists(#r)", names={"#r": "restoredAt"})
    repo.put_item(item, **cond)
    with pytest.raises(ConditionFailed):
        repo.put_item({**item, "restoredAt": "x"}, condition="#n = :v", names={"#n": "n"}, values={":v": "other"})
    repo.put_item({**item, "restoredAt": "x"}, condition="#n = :v", names={"#n": "n"}, values={":v": "one"})
    with pytest.raises(ConditionFailed):
        repo.put_item(item, condition="attribute_not_exists(#r)", names={"#r": "restoredAt"})
    assert repo.get_item("USER#u", "ACT#1")["restoredAt"] == "x"
