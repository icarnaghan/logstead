"""Property test for package job state classification (accountant-package task 6.4).

Feature: accountant-package, Property 8: Job state classification
**Validates: Requirements 7.5, 7.8, 7.10, 14.4**
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.package_config import JOB_STALE_SECONDS
from logstead.services.package_jobs import (
    PackageJobService,
    effective_status,
    is_active,
    is_expired,
)
from logstead.services.property import PropertyService

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
NOW = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
STATUSES = ["queued", "running", "complete", "failed"]
ACTIVE = ("queued", "running")

# Offsets in seconds relative to NOW; dense around the stale boundary.
_offsets = st.one_of(
    st.integers(min_value=-200_000, max_value=200_000),
    st.sampled_from(
        [
            -JOB_STALE_SECONDS - 1,
            -JOB_STALE_SECONDS,
            -JOB_STALE_SECONDS + 1,
            0,
            1,
            -1,
        ]
    ),
)


@st.composite
def job_items(draw):
    job = {
        "id": "job-1",
        "taxYear": 2024,
        "status": draw(st.sampled_from(STATUSES)),
        "createdAt": (NOW + timedelta(seconds=draw(_offsets))).isoformat(),
        "ttl": int(NOW.timestamp()) + draw(_offsets),
    }
    if draw(st.booleans()):
        job["startedAt"] = (NOW + timedelta(seconds=draw(_offsets))).isoformat()
    return job


def _last_change(job) -> datetime:
    return datetime.fromisoformat(job.get("startedAt") or job["createdAt"])


def _stale(job) -> bool:
    return (NOW - _last_change(job)).total_seconds() > JOB_STALE_SECONDS


# Feature: accountant-package, Property 8: Job state classification
@settings(max_examples=100)
@given(job=job_items())
def test_pure_classification(job):
    stale_active = job["status"] in ACTIVE and _stale(job)
    expected_status = "failed" if stale_active else job["status"]
    assert effective_status(job, NOW) == expected_status
    assert is_active(job, NOW) == (job["status"] in ACTIVE and not _stale(job))
    assert is_expired(job, NOW) == (job["ttl"] <= NOW.timestamp())


def test_stale_boundary_is_exclusive():
    base = {"status": "running", "createdAt": (NOW - timedelta(days=1)).isoformat()}
    at = {**base, "startedAt": (NOW - timedelta(seconds=JOB_STALE_SECONDS)).isoformat()}
    past = {
        **base,
        "startedAt": (NOW - timedelta(seconds=JOB_STALE_SECONDS + 1)).isoformat(),
    }
    assert effective_status(at, NOW) == "running" and is_active(at, NOW)
    assert effective_status(past, NOW) == "failed" and not is_active(past, NOW)


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
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def invoke(self, user_id: str, job_id: str) -> None:
        self.calls.append((user_id, job_id))


@st.composite
def job_sets(draw):
    """Jobs whose ttl is in the future, so only status and staleness vary."""
    jobs = []
    for i in range(draw(st.integers(min_value=0, max_value=4))):
        job = draw(job_items())
        job["id"] = f"job-{i}"
        job["ttl"] = int(NOW.timestamp()) + 3600
        jobs.append(job)
    return jobs


# Feature: accountant-package, Property 8: Job state classification
@settings(max_examples=100, deadline=None, suppress_health_check=list(HealthCheck))
@given(jobs=job_sets(), target=st.sampled_from(["job-0", "job-1", "job-2", "job-3"]))
def test_create_and_delete_acceptance(jobs, target):
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE)
        created = PropertyService(repo, USER).create(
            PropertyInput(name="P", address_text="1 Main St", property_type="single_family")
        )
        assert created.is_ok, created.error
        for job in jobs:
            repo.put_item(
                {
                    "PK": keys.user_pk(USER),
                    "SK": keys.package_job_sk(job["id"]),
                    "userId": USER,
                    **job,
                }
            )
        invoker = _Invoker()
        service = PackageJobService(
            repo, USER, S3FileAdapter(s3, BUCKET), invoker, clock=lambda: NOW
        )

        by_id = {j["id"]: j for j in jobs}
        if target in by_id:
            deleted = service.delete(target)
            assert deleted.is_ok == (not is_active(by_id[target], NOW))
            if not deleted.is_ok:
                assert deleted.error.kind == "conflict"
        else:
            assert service.delete(target).error.kind == "not_found"

        # Delete never touches other jobs, so the active set is unchanged.
        any_active = any(is_active(j, NOW) for j in jobs)
        result = service.create(2024, None)
        assert result.is_ok == (not any_active)
        if result.is_ok:
            assert result.value.status == "queued"
            assert len(invoker.calls) == 1
        else:
            assert result.error.kind == "conflict"
            assert invoker.calls == []
