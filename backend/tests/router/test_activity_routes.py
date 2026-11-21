"""Task 9.9: router tests for activity recording and the activity routes (moto)."""
from __future__ import annotations

import json
import uuid

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import _dispatch, handler

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-activity"
REGION = "us-east-1"
USER = "activity-user-a"
OTHER = "activity-user-b"


@pytest.fixture
def env():
    with mock_aws():
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
                    "IndexName": f"GSI{i}",
                    "KeySchema": [
                        {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                        {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for i in (1, 2)
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)
        handler_module.configure(repo=repo, files=S3FileAdapter(s3, BUCKET))
        yield repo
        handler_module.reset_wiring()


def _raw(method, path, *, body=None, query=None, sub=USER):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = {k: str(v) for k, v in query.items()}
    return handler(event)


def _call(method, path, *, body=None, query=None, sub=USER):
    resp = _raw(method, path, body=body, query=query, sub=sub)
    return resp["statusCode"], (json.loads(resp["body"]) if resp["body"] else None)


def _ok(result, expected=(200, 201, 204)):
    status, payload = result
    assert status in expected, (status, payload)
    return payload


def _events(sub=USER, **query):
    return _ok(_call("GET", "/activity", query=query or None, sub=sub))["events"]


def _kinds(sub=USER):
    """(action, entity) of every event, oldest first."""
    return [(e["action"], e["entity"]) for e in reversed(_events(sub, limit=100))]


def _act_items(repo, sub=USER):
    return repo.query(keys.user_pk(sub), sk_begins_with=keys.activity_list_prefix())


def _new_property(name="House", sub=USER):
    return _ok(_call("POST", "/properties", body={"name": name, "address_text": "1 St"}, sub=sub))["id"]


TXN = {"date": "2023-05-01", "amount": "100.00", "type": "expense", "category_id": "repairs"}
ASSET = {"description": "Roof", "cost_basis": "10000.00", "placed_in_service_date": "2023-01-10"}
LOAN = {
    "description": "Mortgage", "annual_interest_rate": "6.5", "monthly_payment": "1500.00",
    "anchor_balance": "200000.00", "anchor_date": "2023-06-01", "original_principal": "250000.00",
}


# --- recording ---------------------------------------------------------------


def test_each_handler_records_exactly_one_event_of_the_right_kind(env):
    pid = _new_property()
    assert _kinds() == [("create", "property")]
    expected: list[tuple[str, str]] = [("create", "property")]

    def step(result, *kinds):
        _ok(result)
        expected.extend(kinds)
        assert _kinds() == expected

    base = f"/properties/{pid}"
    step(_call("PUT", base, body={"name": "Renamed", "address_text": "1 St"}), ("update", "property"))

    txn = _ok(_call("POST", f"{base}/transactions", body=TXN))
    expected.append(("create", "transaction"))
    assert _kinds() == expected
    step(_call("PUT", f"{base}/transactions/{txn['id']}", body={**TXN, "amount": "101.00"}),
         ("update", "transaction"))
    step(_call("DELETE", f"{base}/transactions/{txn['id']}"), ("delete", "transaction"))

    entry = _ok(_call("POST", f"{base}/itemized/repairs/entries",
                      body={"date": "2022-03-04", "amount": "75.00", "description": "Plumber"}))
    expected.append(("create", "itemized_entry"))
    assert _kinds() == expected
    step(_call("PUT", f"{base}/itemized/repairs/entries/{entry['id']}",
               body={"date": "2022-03-04", "amount": "80.00", "description": "Plumber"}),
         ("update", "itemized_entry"))
    step(_call("DELETE", f"{base}/itemized/repairs/entries/{entry['id']}"), ("delete", "itemized_entry"))

    step(_call("PUT", f"{base}/itemized/repairs/total", body={"tax_year": 2021, "amount": "500.00"}),
         ("create", "transaction"))
    step(_call("DELETE", f"{base}/itemized/repairs/total", query={"taxYear": 2021}),
         ("delete", "transaction"))

    asset = _ok(_call("POST", f"{base}/assets", body=ASSET))
    expected.append(("create", "asset"))
    assert _kinds() == expected
    step(_call("PUT", f"{base}/assets/{asset['id']}", body={**ASSET, "description": "New roof"}),
         ("update", "asset"))
    step(_call("DELETE", f"{base}/assets/{asset['id']}"), ("delete", "asset"))

    loan = _ok(_call("POST", f"{base}/loans", body=LOAN))
    expected.append(("create", "loan"))
    assert _kinds() == expected
    step(_call("PUT", f"{base}/loans/{loan['id']}", body={**LOAN, "monthly_payment": "1600.00"}),
         ("update", "loan"))
    ov = f"{base}/loans/{loan['id']}/interest-overrides/2025"
    step(_call("PUT", ov, body={"interest": "1.00"}), ("update", "loan"))
    step(_call("DELETE", ov), ("update", "loan"))
    step(_call("DELETE", f"{base}/loans/{loan['id']}"), ("delete", "loan"))


def test_events_carry_property_and_record_ids(env):
    pid = _new_property("Oak")
    txn = _ok(_call("POST", f"/properties/{pid}/transactions", body=TXN))
    (event, _) = _events(limit=2)
    assert event["property_id"] == pid and event["property_name"] == "Oak"
    assert event["record_id"] == txn["id"]
    assert event["action"] == "create" and event["entity"] == "transaction"
    assert "event_id" not in event and event["id"]


def test_400_and_404_record_nothing(env):
    pid = _new_property()
    base = f"/properties/{pid}"
    count = len(_act_items(env))
    assert _call("POST", f"{base}/transactions", body={**TXN, "amount": "-1"})[0] == 400
    assert _call("POST", f"{base}/transactions", body={})[0] == 400
    ghost = str(uuid.uuid4())
    assert _call("PUT", f"{base}/transactions/{ghost}", body=TXN)[0] == 404
    assert _call("DELETE", f"{base}/transactions/{ghost}")[0] == 404
    assert _call("DELETE", f"{base}/assets/{ghost}")[0] == 404
    assert _call("PUT", f"{base}/loans/{ghost}", body=LOAN)[0] == 404
    assert _call("POST", f"/properties/{ghost}/transactions", body=TXN)[0] == 404
    assert _call("DELETE", f"/properties/{ghost}")[0] == 404
    assert _call("PUT", f"/properties/{pid}", body={"name": ""})[0] == 400
    assert len(_act_items(env)) == count


def test_unchanged_update_records_nothing(env):
    pid = _new_property()
    base = f"/properties/{pid}"
    txn = _ok(_call("POST", f"{base}/transactions", body=TXN))
    asset = _ok(_call("POST", f"{base}/assets", body=ASSET))
    count = len(_act_items(env))
    _ok(_call("PUT", f"{base}/transactions/{txn['id']}", body=TXN))
    _ok(_call("PUT", f"{base}/assets/{asset['id']}", body=ASSET))
    assert len(_act_items(env)) == count


def test_schedule_e_import_records_one_event(env):
    pid = _new_property()
    body = {
        "tax_year": 2023,
        "entries": [{
            "property_id": pid,
            "lines": [
                {"schedule_e_line": 3, "amount": "24000.00"},
                {"schedule_e_line": 14, "amount": "1875.50"},
            ],
        }],
    }
    _ok(_call("POST", "/imports/schedule-e", body=body))
    assert _kinds() == [("create", "property"), ("import", "schedule_e")]
    # Several transactions were created, none individually recorded.
    assert len(_ok(_call("GET", f"/properties/{pid}/transactions"))) == 2


def test_backup_restore_purges_then_records_one_event_and_clear_purges(env):
    pid = _new_property()
    _ok(_call("POST", f"/properties/{pid}/transactions", body=TXN))
    assert len(_act_items(env)) == 2
    doc = _ok(_call("GET", "/backup"))
    _ok(_call("POST", "/backup/restore", body=doc))
    assert _kinds() == [("import", "backup")]
    _ok(_call("POST", "/backup/clear"))
    assert _act_items(env) == []


def test_property_delete_purges_that_propertys_events_only(env):
    keep = _new_property("Keep")
    gone = _new_property("Gone")
    txn = _ok(_call("POST", f"/properties/{gone}/transactions", body=TXN))
    _ok(_call("POST", f"/properties/{keep}/transactions", body=TXN))
    _ok(_call("DELETE", f"/properties/{gone}/transactions/{txn['id']}"))
    assert any(e["property_id"] == gone for e in _events(limit=100))
    _ok(_call("DELETE", f"/properties/{gone}"))
    events = _events(limit=100)
    # Earlier events for the property are gone; only its own delete event remains.
    assert [(e["action"], e["entity"]) for e in events if e["property_id"] == gone] == [
        ("delete", "property")
    ]
    assert sum(1 for e in events if e["property_id"] == keep) == 2


def test_export_has_no_activity_items_and_schema_version_stays_1(env):
    pid = _new_property()
    _ok(_call("POST", f"/properties/{pid}/transactions", body=TXN))
    assert _act_items(env)
    doc = _ok(_call("GET", "/backup"))
    assert doc["schema_version"] == "1"
    assert "ACT#" not in json.dumps(doc)
    assert not any("activ" in k.lower() for k in doc)


def test_recording_failure_does_not_change_the_response(env, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("recorder down")

    monkeypatch.setattr(handler_module, "_activity_recorder", boom)
    pid = _new_property()
    assert _call("POST", f"/properties/{pid}/transactions", body=TXN)[0] == 201


# --- list ---------------------------------------------------------------------


def test_list_filters_and_property_scope(env):
    a, b = _new_property("A"), _new_property("B")
    _ok(_call("POST", f"/properties/{a}/transactions", body=TXN))
    _ok(_call("POST", f"/properties/{b}/assets", body=ASSET))
    assert {e["entity"] for e in _events(entity="asset")} == {"asset"}
    assert {e["action"] for e in _events(action="create")} == {"create"}
    assert [e["entity"] for e in _events(propertyId=a, entity="transaction")] == ["transaction"]
    own = _ok(_call("GET", f"/properties/{b}/activity"))["events"]
    assert {e["property_id"] for e in own} == {b}
    assert _events(entity="loan") == []


def test_pagination_walks_every_event_newest_first_without_overlap(env):
    pid = _new_property()
    for i in range(5):
        _ok(_call("POST", f"/properties/{pid}/transactions", body={**TXN, "amount": f"{i + 1}.00"}))
    full = [e["id"] for e in _events(limit=100)]
    assert len(full) == 6
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        query = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = _ok(_call("GET", "/activity", query=query))
        seen += [e["id"] for e in page["events"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == full and pages >= 3
    # The per-property list paginates the same way.
    first = _ok(_call("GET", f"/properties/{pid}/activity", query={"limit": 2}))
    assert len(first["events"]) == 2 and first["next_cursor"]
    rest = _ok(_call("GET", f"/properties/{pid}/activity",
                     query={"limit": 100, "cursor": first["next_cursor"]}))
    assert [e["id"] for e in first["events"] + rest["events"]] == full


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ({"limit": "abc"}, "limit"),
        ({"limit": "0"}, "limit"),
        ({"limit": "101"}, "limit"),
        ({"limit": "2.5"}, "limit"),
        ({"entity": "bogus"}, "entity"),
        ({"action": "bogus"}, "action"),
        ({"cursor": "not-a-cursor!"}, "cursor"),
    ],
)
def test_invalid_list_parameters_are_400(env, query, field):
    pid = _new_property()
    for path in ("/activity", f"/properties/{pid}/activity"):
        status, body = _call("GET", path, query=query)
        assert status == 400, body
        assert body["field"] == field


def test_foreign_missing_and_malformed_property_give_identical_404(env):
    foreign = _new_property(sub=OTHER)
    ghosts = [foreign, str(uuid.uuid4()), "x" * 100]
    lists = [_raw("GET", "/activity", query={"propertyId": g}) for g in ghosts + ["bad id#!", "x" * 200]]
    lists += [_raw("GET", f"/properties/{g}/activity") for g in ghosts]
    lists += [_raw("POST", f"/properties/{g}/activity/20240101000000.abc/restore") for g in ghosts]
    assert all(r["statusCode"] == 404 for r in lists), [r["statusCode"] for r in lists]
    assert len({r["body"] for r in lists}) == 1
    assert json.loads(lists[0]["body"])["message"] == "Property not found."
    # A malformed id in the path gets the router's generic 404, like every property route.
    for bad in ("bad id#!", "x" * 200):
        assert _call("GET", f"/properties/{bad}/activity") == _call("GET", f"/properties/{bad}/transactions")


def test_user_only_sees_their_own_events(env):
    _new_property("Mine")
    _new_property("Theirs", sub=OTHER)
    assert [e["property_name"] for e in _events()] == ["Mine"]
    assert [e["property_name"] for e in _events(sub=OTHER)] == ["Theirs"]


# --- restore ------------------------------------------------------------------


def _delete_txn(pid):
    txn = _ok(_call("POST", f"/properties/{pid}/transactions", body=TXN))
    _ok(_call("DELETE", f"/properties/{pid}/transactions/{txn['id']}"))
    return _events(action="delete", limit=1)[0]


def test_restore_succeeds_once_then_409_already_restored(env):
    pid = _new_property()
    event = _delete_txn(pid)
    assert event["restorable"] is True
    status, out = _call("POST", f"/properties/{pid}/activity/{event['id']}/restore")
    assert status == 200, out
    assert out["event_id"] == event["id"] and out["record_id"]
    assert len(_ok(_call("GET", f"/properties/{pid}/transactions"))) == 1
    assert _kinds()[-1] == ("restore", "transaction")
    status, again = _call("POST", f"/properties/{pid}/activity/{event['id']}/restore")
    assert status == 409 and "already restored" in again["message"]
    assert len(_ok(_call("GET", f"/properties/{pid}/transactions"))) == 1


def test_restore_409_reasons_for_non_delete_and_non_restorable(env):
    pid = _new_property()
    txn = _ok(_call("POST", f"/properties/{pid}/transactions", body=TXN))
    create = _events(limit=1)[0]
    status, body = _call("POST", f"/properties/{pid}/activity/{create['id']}/restore")
    assert (status, body["message"]) == (409, "Only a delete event can be restored.")
    # A property delete event is never restorable.
    _ok(_call("DELETE", f"/properties/{pid}/transactions/{txn['id']}"))
    other = _new_property("Other")
    _ok(_call("DELETE", f"/properties/{other}"))
    prop_delete = _events(action="delete", entity="property", limit=1)[0]
    assert prop_delete["restorable"] is False
    # The property is gone, so the route's property check answers first.
    assert _call("POST", f"/properties/{other}/activity/{prop_delete['id']}/restore")[0] == 404


def test_restore_unknown_malformed_and_wrong_property_event_is_event_404(env):
    pid, other = _new_property(), _new_property("Other")
    event = _delete_txn(pid)
    results = [
        _raw("POST", f"/properties/{pid}/activity/{bad}/restore")
        for bad in ("nope", "20240101000000.unknown", "x" * 90)
    ]
    results.append(_raw("POST", f"/properties/{other}/activity/{event['id']}/restore"))
    assert all(r["statusCode"] == 404 for r in results)
    assert len({r["body"] for r in results}) == 1
    assert json.loads(results[0]["body"])["message"] != "Property not found."
    # Nothing was restored.
    assert _ok(_call("GET", f"/properties/{pid}/transactions")) == []


# --- methods ------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/activity", "/properties/{p}/activity"])
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_list_routes_resolve_only_for_get(path, method):
    path = path.format(p="abc")
    assert _dispatch("GET", path) is not None
    assert _dispatch(method, path) is None


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
def test_restore_route_resolves_only_for_post(method):
    path = "/properties/abc/activity/20240101000000.x/restore"
    assert _dispatch("POST", path) is not None
    assert _dispatch(method, path) is None
    assert _dispatch("GET", "/properties/abc/activity/20240101000000.x") is None


def test_activity_requires_authentication(env):
    resp = handler({"requestContext": {"http": {"method": "GET", "path": "/activity"}},
                    "rawPath": "/activity"})
    assert resp["statusCode"] == 401

