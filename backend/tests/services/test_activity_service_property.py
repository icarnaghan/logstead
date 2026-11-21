"""Activity service property tests over moto (fresh table per example).

Property 18: Event serialization round trip.  Validates: Requirements 14.7, 14.8, 14.10
Property 20: Pagination completeness.         Validates: Requirements 15.4, 15.5, 15.9
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import boto3
from hypothesis import given, settings, strategies as st
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.activity import ActivityRecorder, ActivityService, NewEvent
from logstead.services.activity_config import ACTIVITY_CONFIG

TABLE = "Logstead"
USER = "u1"
PROP = "p1"
NOW = datetime(2025, 6, 1, tzinfo=timezone.utc)
FORBIDDEN = {"receipt", "receipts", "s3_key", "s3Key", "bucket", "credentials", "password", "token"}


@contextmanager
def _env():
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
        repo = DynamoRepository(ddb, TABLE)
        repo.put_item(
            {"PK": keys.property_scoped_pk(PROP), "SK": keys.property_meta_sk(), "userId": USER}
        )
        yield repo


def _service(repo) -> ActivityService:
    rec = ActivityRecorder(repo, USER, clock=lambda: NOW)
    return ActivityService(
        repo, USER, None, None, None, None, rec, clock=lambda: NOW
    )


_money = st.from_regex(r"-?[0-9]{1,6}\.[0-9]{2}", fullmatch=True)
_text = st.text(min_size=0, max_size=30)
_values = st.dictionaries(
    st.sampled_from(["description", "amount", "category_id", "date", "notes", "cost_basis"]),
    st.one_of(_money, _text),
    max_size=6,
)


@settings(max_examples=40, deadline=None)
@given(
    before=st.one_of(st.none(), _values),
    after=st.one_of(st.none(), _values),
    with_property=st.booleans(),
)
def test_property_18_event_round_trip(before, after, with_property):
    with _env() as repo:
        ActivityRecorder(repo, USER, clock=lambda: NOW).record(
            NewEvent(
                action="update",
                entity="transaction",
                summary="Updated",
                record_id="r1",
                property_id=PROP if with_property else None,
                before=before,
                after=after,
            )
        )
        svc = _service(repo)
        res = svc.list_property(PROP) if with_property else svc.list_user()
        assert res.is_ok
        (event,) = res.value.events
        assert event.before == before
        assert event.after == after
        assert not event.truncated
        for side in (event.before, event.after):
            for k, v in (side or {}).items():
                assert k not in FORBIDDEN
                assert isinstance(v, str)


_event_spec = st.tuples(
    st.integers(0, 40),  # minutes before NOW (collisions give equal timestamps)
    st.sampled_from(["transaction", "asset", "loan"]),
    st.sampled_from(["create", "update", "delete"]),
    st.booleans(),  # expired
    st.booleans(),  # has property
)


@settings(max_examples=30, deadline=None)
@given(
    specs=st.lists(_event_spec, max_size=25),
    page=st.integers(1, 100),
    entity=st.one_of(st.none(), st.sampled_from(["transaction", "asset", "loan"])),
    action=st.one_of(st.none(), st.sampled_from(["create", "update", "delete"])),
    by_property=st.booleans(),
)
def test_property_20_pagination_completeness(specs, page, entity, action, by_property):
    with _env() as repo:
        svc = _service(repo)
        expected: list[tuple[str, str]] = []
        for i, (mins, ent, act, expired, has_prop) in enumerate(specs):
            at = NOW - timedelta(minutes=mins)
            if expired:
                at = NOW - timedelta(days=ACTIVITY_CONFIG.retention_days + 1, minutes=mins)
            rec = ActivityRecorder(repo, USER, clock=lambda at=at: at)
            rec.record(
                NewEvent(
                    action=act,
                    entity=ent,
                    summary=f"e{i}",
                    property_id=PROP if has_prop else None,
                )
            )
        rows = repo.query(keys.user_pk(USER), sk_begins_with="ACT#", money_attrs=set())
        for r in rows:
            live = float(r["ttl"]) > NOW.timestamp()
            if (
                live
                and (entity is None or r["entity"] == entity)
                and (action is None or r["action"] == action)
                and (not by_property or r.get("propertyId") == PROP)
            ):
                expected.append((r["SK"], r["eventId"]))
        expected.sort()  # SK is inverted time: ascending SK is newest first

        seen: list[str] = []
        cursor = None
        for _ in range(len(expected) + 3):
            if by_property:
                res = svc.list_property(
                    PROP, limit=page, cursor=cursor, entity=entity, action=action
                )
            else:
                res = svc.list_user(limit=page, cursor=cursor, entity=entity, action=action)
            assert res.is_ok
            p = res.value
            seen.extend(e.event_id for e in p.events)
            if p.next_cursor is None:
                break
            assert p.events  # a non-final page is never empty
            cursor = p.next_cursor
        else:
            raise AssertionError("pagination did not terminate")

        wire = [sk[len(keys.ACT_PREFIX):].replace("#", ".", 1) for sk, _ in expected]
        assert seen == wire
        assert len(set(seen)) == len(seen)
