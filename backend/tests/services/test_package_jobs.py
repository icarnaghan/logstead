"""Example tests for ``PackageJobService`` (accountant-package task 6.7)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.package_config import (
    DOWNLOAD_LINK_SECONDS,
    JOB_LIST_LIMIT,
    JOB_STALE_SECONDS,
    JOB_TTL_SECONDS,
)
from logstead.services.package_jobs import (
    INVOKE_FAILED_MESSAGE,
    PackageJobService,
)
from logstead.services.property import PropertyService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
NOW = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


def _create_table(ddb) -> None:
    ddb.create_table(
        TableName=TABLE,
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


class _Invoker:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def invoke(self, user_id: str, job_id: str) -> None:
        self.calls.append((user_id, job_id))
        if self.fail:
            raise RuntimeError("lambda down arn:aws:lambda:secret")


class _Files(S3FileAdapter):
    """Real adapter that records calls and can fail deletes."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.events: list[str] = []
        self.fail_delete = False
        self.presign_calls = 0

    def delete_object(self, key: str):
        self.events.append(f"s3:{key}")
        if self.fail_delete:
            raise RuntimeError("s3 down")
        return super().delete_object(key)

    def presigned_get_url(self, key, **kwargs):
        self.presign_calls += 1
        return super().presigned_get_url(key, **kwargs)


class _Repo(DynamoRepository):
    """Repository that records delete order relative to the S3 adapter."""

    log: list[str]

    def delete_item(self, pk, sk):
        self.log.append("ddb")
        return super().delete_item(pk, sk)


@pytest.fixture
def env():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = _Repo(ddb, TABLE)
        files = _Files(s3, BUCKET)
        repo.log = files.events
        prop = PropertyService(repo, USER).create(
            PropertyInput(name="P", address_text="1 Main St", property_type="single_family")
        )
        assert prop.is_ok, prop.error
        invoker = _Invoker()
        clock = {"now": NOW}
        service = PackageJobService(repo, USER, files, invoker, clock=lambda: clock["now"])
        yield type(
            "Env",
            (),
            dict(
                repo=repo,
                files=files,
                s3=s3,
                invoker=invoker,
                service=service,
                prop_id=prop.value.id,
                clock=clock,
            ),
        )


def _put_job(env, job_id: str, **fields) -> None:
    job = {
        "id": job_id,
        "status": "complete",
        "taxYear": 2024,
        "propertyIds": [env.prop_id],
        "createdAt": NOW.isoformat(),
        "ttl": int(NOW.timestamp()) + 3600,
        **fields,
    }
    env.repo.put_item(
        {"PK": keys.user_pk(USER), "SK": keys.package_job_sk(job_id), "userId": USER, **job}
    )


def _stored(env, job_id: str):
    return env.repo.get_item(keys.user_pk(USER), keys.package_job_sk(job_id))


def test_create_writes_queued_job_with_ttl_and_invokes(env):
    result = env.service.create(2024, None)
    assert result.is_ok, result.error
    view = result.value
    assert view.status == "queued"
    assert view.tax_year == 2024
    assert view.property_ids == [env.prop_id]
    assert view.download_url is None
    assert env.invoker.calls == [(USER, view.id)]
    stored = _stored(env, view.id)
    assert stored["status"] == "queued"
    assert int(stored["ttl"]) == int(NOW.timestamp()) + JOB_TTL_SECONDS
    assert stored["createdAt"] == NOW.isoformat()


def test_create_with_explicit_ids_and_rejections(env):
    ok = env.service.create(2024, [env.prop_id, env.prop_id])
    assert ok.is_ok and ok.value.property_ids == [env.prop_id]
    # a fresh service with no active job: unknown property and empty set
    for job in env.repo.query(keys.user_pk(USER), sk_begins_with=keys.PACKAGE_JOB_PREFIX):
        env.repo.delete_item(job["PK"], job["SK"])
    missing = env.service.create(2024, ["nope"])
    assert not missing.is_ok and missing.error.kind == "not_found"
    empty = env.service.create(2024, [])
    assert not empty.is_ok
    assert empty.error.kind == "validation" and empty.error.field == "property_ids"


def test_one_active_job_blocks_create(env):
    first = env.service.create(2024, None)
    assert first.is_ok
    second = env.service.create(2023, None)
    assert not second.is_ok and second.error.kind == "conflict"
    assert len(env.invoker.calls) == 1
    # a stale active job no longer blocks
    env.clock["now"] = NOW + timedelta(seconds=JOB_STALE_SECONDS + 1)
    assert env.service.create(2023, None).is_ok


def test_invoke_failure_marks_job_failed_and_returns_unavailable(env):
    env.invoker.fail = True
    result = env.service.create(2024, None)
    assert not result.is_ok
    assert result.error.kind == "unavailable"
    assert result.error.message == INVOKE_FAILED_MESSAGE
    assert "arn" not in result.error.message
    (job,) = env.repo.query(keys.user_pk(USER), sk_begins_with=keys.PACKAGE_JOB_PREFIX)
    assert job["status"] == "failed"
    assert job["message"] == INVOKE_FAILED_MESSAGE
    assert "secret" not in str(job)
    # the failed job is not active, so a retry is accepted
    env.invoker.fail = False
    assert env.service.create(2024, None).is_ok


def test_list_is_newest_first_and_limited(env):
    total = JOB_LIST_LIMIT + 3
    for i in range(total):
        _put_job(
            env,
            f"job-{i:02d}",
            createdAt=(NOW - timedelta(minutes=total - i)).isoformat(),
            objectKey=f"exports/packages/{USER}/job-{i:02d}/x.zip",
        )
    result = env.service.list()
    assert result.is_ok
    ids = [v.id for v in result.value]
    assert len(ids) == JOB_LIST_LIMIT
    assert ids == [f"job-{i:02d}" for i in range(total - 1, total - 1 - JOB_LIST_LIMIT, -1)]


def test_list_hides_expired_jobs(env):
    _put_job(env, "old", ttl=int(NOW.timestamp()) - 1)
    _put_job(env, "new")
    assert [v.id for v in env.service.list().value] == ["new"]


def test_get_complete_job_issues_fresh_link_each_read_and_stores_none(env):
    key = f"exports/packages/{USER}/job-1/logstead-accountant-package-2024.zip"
    env.s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    _put_job(env, "job-1", objectKey=key, sizeBytes=3, sha256="ab", fileCount=2)
    first = env.service.get("job-1").value
    assert first.download_url and "logstead-accountant-package-2024.zip" in first.download_url
    assert first.download_expires_in_seconds == DOWNLOAD_LINK_SECONDS
    assert env.files.presign_calls == 1
    # later read, later clock: a new link is issued rather than a stored one
    env.clock["now"] = NOW + timedelta(seconds=60)
    second = env.service.get("job-1").value
    assert env.files.presign_calls == 2
    assert second.download_url
    stored = _stored(env, "job-1")
    assert not any("url" in k.lower() for k in stored)
    assert first.download_url not in str(stored)


def test_get_issues_no_link_for_other_statuses(env):
    for status in ("queued", "running", "failed"):
        _put_job(env, f"job-{status}", status=status, objectKey="exports/packages/k.zip")
        view = env.service.get(f"job-{status}").value
        assert view.download_url is None and view.download_expires_in_seconds is None
    assert env.files.presign_calls == 0


def test_get_unknown_and_expired_are_not_found(env):
    _put_job(env, "gone", ttl=int(NOW.timestamp()) - 1)
    for job_id in ("gone", "missing"):
        result = env.service.get(job_id)
        assert not result.is_ok and result.error.kind == "not_found"
        assert env.service.delete(job_id).error.kind == "not_found"
    assert env.files.presign_calls == 0


def test_stale_job_reads_as_failed(env):
    _put_job(
        env,
        "stale",
        status="running",
        createdAt=(NOW - timedelta(days=1)).isoformat(),
        startedAt=(NOW - timedelta(seconds=JOB_STALE_SECONDS + 1)).isoformat(),
    )
    view = env.service.get("stale").value
    assert view.status == "failed" and view.message


def test_delete_removes_s3_object_before_item(env):
    key = f"exports/packages/{USER}/job-1/logstead-accountant-package-2024.zip"
    env.s3.put_object(Bucket=BUCKET, Key=key, Body=b"zip")
    _put_job(env, "job-1", objectKey=key)
    assert env.service.delete("job-1").is_ok
    assert env.files.events == [f"s3:{key}", "ddb"]
    assert _stored(env, "job-1") is None
    assert "Contents" not in env.s3.list_objects_v2(Bucket=BUCKET, Prefix=key)


def test_delete_s3_failure_keeps_item(env):
    key = "exports/packages/k.zip"
    _put_job(env, "job-1", objectKey=key)
    env.files.fail_delete = True
    result = env.service.delete("job-1")
    assert not result.is_ok and result.error.kind == "unavailable"
    assert _stored(env, "job-1") is not None
    assert "ddb" not in env.files.events


def test_delete_without_object_key_removes_item_only(env):
    _put_job(env, "job-1", status="failed")
    assert env.service.delete("job-1").is_ok
    assert env.files.events == ["ddb"]


def test_delete_active_job_is_conflict(env):
    _put_job(env, "job-1", status="running", startedAt=NOW.isoformat())
    result = env.service.delete("job-1")
    assert not result.is_ok and result.error.kind == "conflict"
    assert _stored(env, "job-1") is not None
    assert env.files.events == []
