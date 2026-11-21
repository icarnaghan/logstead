"""Task 6.8: router tests for the accountant package job routes (moto-backed)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.router import handler as handler_module
from logstead.router.handler import _dispatch, handler
from logstead.services.package_config import JOB_LIST_LIMIT, JOB_STALE_SECONDS

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-package-routes"
REGION = "us-east-1"
USER = "package-routes-user-sub"


class FakeInvoker:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def invoke(self, user_id: str, job_id: str) -> None:
        self.calls.append((user_id, job_id))
        if self.fail:
            raise RuntimeError("boom")


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
        invoker = FakeInvoker()
        handler_module.configure(
            repo=repo, files=S3FileAdapter(s3, BUCKET), package_invoker=invoker
        )
        yield repo, s3, invoker
        handler_module.reset_wiring()


def _call(method, path, *, body=None, sub=USER):
    event = {
        "requestContext": {
            "http": {"method": method, "path": path},
            "authorizer": {"jwt": {"claims": {"sub": sub}}},
        },
        "rawPath": path,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    resp = handler(event)
    return resp["statusCode"], (json.loads(resp["body"]) if resp["body"] else None)


def _make_property(name="Oak House"):
    status, prop = _call("POST", "/properties", body={"name": name, "address_text": "1 St"})
    assert status in (200, 201), prop
    return prop["id"]


def _put_job(repo, job_id, status, *, created=None, **extra):
    created = created or datetime.now(timezone.utc)
    repo.put_item(
        {
            "PK": keys.user_pk(USER),
            "SK": keys.package_job_sk(job_id),
            "userId": USER,
            "id": job_id,
            "status": status,
            "taxYear": 2023,
            "propertyIds": [],
            "createdAt": created.isoformat(),
            "ttl": int(created.timestamp()) + 86400,
            **extra,
        }
    )


def _item(repo, job_id):
    return repo.get_item(keys.user_pk(USER), keys.package_job_sk(job_id))


# --- create ------------------------------------------------------------------


def test_create_returns_202_and_invokes_worker_once(env):
    repo, _, invoker = env
    pid = _make_property()
    status, body = _call("POST", "/accountant-packages", body={"tax_year": 2023})
    assert status == 202, body
    assert body["status"] == "queued"
    assert body["tax_year"] == 2023
    assert body["property_ids"] == [pid]
    assert body["download_url"] is None
    assert invoker.calls == [(USER, body["id"])]
    assert _item(repo, body["id"]) is not None


def test_create_with_explicit_property_ids(env):
    _, _, invoker = env
    a = _make_property("A")
    _make_property("B")
    status, body = _call(
        "POST", "/accountant-packages", body={"tax_year": 2023, "property_ids": [a]}
    )
    assert status == 202, body
    assert body["property_ids"] == [a]
    assert len(invoker.calls) == 1


def test_create_conflicts_while_a_job_is_active(env):
    repo, _, invoker = env
    _make_property()
    first = _call("POST", "/accountant-packages", body={"tax_year": 2023})[1]
    status, body = _call("POST", "/accountant-packages", body={"tax_year": 2022})
    assert status == 409, body
    assert "2023" in body["message"] or "2023" in json.dumps(body)
    assert len(invoker.calls) == 1
    assert len(_call("GET", "/accountant-packages")[1]["jobs"]) == 1
    assert first["id"] == invoker.calls[0][1]


def test_invoke_failure_is_503_and_marks_job_failed(env):
    repo, _, invoker = env
    invoker.fail = True
    _make_property()
    status, body = _call("POST", "/accountant-packages", body={"tax_year": 2023})
    assert status == 503, body
    jobs = _call("GET", "/accountant-packages")[1]["jobs"]
    assert [j["status"] for j in jobs] == ["failed"]
    assert jobs[0]["message"]


def test_no_worker_configured_is_503_and_creates_nothing(env):
    repo, s3, _ = env
    handler_module.configure(repo=repo, files=S3FileAdapter(s3, BUCKET), package_invoker=None)
    _make_property()
    status, body = _call("POST", "/accountant-packages", body={"tax_year": 2023})
    assert status == 503, body
    assert _call("GET", "/accountant-packages")[1] == {"jobs": []}


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize("year", ["abc", 1899, 2201, None, True, 2023.5])
def test_bad_year_is_400_on_tax_year(env, year):
    _, _, invoker = env
    _make_property()
    body = {} if year is None else {"tax_year": year}
    status, resp = _call("POST", "/accountant-packages", body=body)
    assert status == 400, resp
    assert resp["field"] == "tax_year"
    assert invoker.calls == []


@pytest.mark.parametrize(
    "ids", ["notalist", ["bad id!"], ["../x"], [1], ["a"] * 101]
)
def test_bad_property_ids_is_400_on_property_ids(env, ids):
    _, _, invoker = env
    _make_property()
    status, resp = _call(
        "POST", "/accountant-packages", body={"tax_year": 2023, "property_ids": ids}
    )
    assert status == 400, resp
    assert resp["field"] == "property_ids"
    assert invoker.calls == []


def test_no_properties_is_400_on_property_ids(env):
    status, resp = _call("POST", "/accountant-packages", body={"tax_year": 2023})
    assert status == 400, resp
    assert resp["field"] == "property_ids"


# --- list / get --------------------------------------------------------------


def test_list_is_newest_first_and_limited(env):
    repo, _, _ = env
    base = datetime.now(timezone.utc) - timedelta(minutes=60)
    for i in range(JOB_LIST_LIMIT + 3):
        _put_job(repo, f"job-{i:02d}", "complete", created=base + timedelta(minutes=i))
    status, body = _call("GET", "/accountant-packages")
    assert status == 200
    ids = [j["id"] for j in body["jobs"]]
    assert len(ids) == JOB_LIST_LIMIT
    assert ids == [f"job-{i:02d}" for i in range(JOB_LIST_LIMIT + 2, 2, -1)]


def test_get_complete_job_has_fresh_download_link(env):
    repo, s3, _ = env
    key = f"exports/packages/{USER}/j1/logstead-accountant-package-2023.zip"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    _put_job(repo, "j1", "complete", objectKey=key, sizeBytes=3)
    status, body = _call("GET", "/accountant-packages/j1")
    assert status == 200, body
    assert body["status"] == "complete"
    assert body["download_url"].startswith("http")
    assert body["download_expires_in_seconds"] > 0
    assert _item(repo, "j1").get("downloadUrl") is None


def test_stale_job_reads_as_failed_and_does_not_block_create(env):
    repo, _, invoker = env
    _make_property()
    old = datetime.now(timezone.utc) - timedelta(seconds=JOB_STALE_SECONDS + 60)
    _put_job(repo, "stale", "running", created=old)
    status, body = _call("GET", "/accountant-packages/stale")
    assert status == 200
    assert body["status"] == "failed"
    assert body["message"]
    assert body["download_url"] is None
    assert _call("POST", "/accountant-packages", body={"tax_year": 2023})[0] == 202
    assert len(invoker.calls) == 1
    # A stale job can be deleted.
    assert _call("DELETE", "/accountant-packages/stale")[0] == 200


def test_get_missing_job_is_404(env):
    assert _call("GET", "/accountant-packages/nope")[0] == 404


# --- delete ------------------------------------------------------------------


def test_delete_active_job_is_409_and_deletes_nothing(env):
    repo, s3, _ = env
    key = f"exports/packages/{USER}/j2/x.zip"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    _put_job(repo, "j2", "running", objectKey=key)
    status, body = _call("DELETE", "/accountant-packages/j2")
    assert status == 409, body
    assert _item(repo, "j2") is not None
    assert s3.list_objects_v2(Bucket=BUCKET)["KeyCount"] == 1


def test_delete_finished_job_removes_item_and_object(env):
    repo, s3, _ = env
    key = f"exports/packages/{USER}/j3/x.zip"
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    _put_job(repo, "j3", "complete", objectKey=key)
    assert _call("DELETE", "/accountant-packages/j3")[0] == 200
    assert _item(repo, "j3") is None
    assert s3.list_objects_v2(Bucket=BUCKET)["KeyCount"] == 0
    assert _call("GET", "/accountant-packages/j3")[0] == 404


# --- route resolution --------------------------------------------------------


@pytest.mark.parametrize("method", ["PUT", "PATCH"])
@pytest.mark.parametrize("path", ["/accountant-packages", "/accountant-packages/j1"])
def test_put_and_patch_resolve_to_no_route(method, path):
    assert _dispatch(method, path) is None


def test_package_routes_resolve():
    assert _dispatch("POST", "/accountant-packages") is not None
    assert _dispatch("GET", "/accountant-packages") is not None
    assert _dispatch("GET", "/accountant-packages/j1") is not None
    assert _dispatch("DELETE", "/accountant-packages/j1") is not None
    assert _dispatch("DELETE", "/accountant-packages") is None
