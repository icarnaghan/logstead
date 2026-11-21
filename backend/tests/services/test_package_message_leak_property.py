"""Property test for package messages (accountant-package task 6.6).

Feature: accountant-package, Property 14: Messages never leak internals
**Validates: Requirements 13.9**
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.accountant_package import PackageBuildError
from logstead.services.package_jobs import PackageJobService
from logstead.services.property import PropertyService
from logstead.worker import package_worker

TABLE = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"
JOB = "job-1"
NOW = datetime(2025, 3, 1, 12, 0, 0, tzinfo=timezone.utc)

_token = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=3, max_size=12)


@st.composite
def leaks(draw):
    """Exception text carrying an S3 key, a bucket, a table, or a stack trace."""
    kind = draw(st.sampled_from(["key", "bucket", "table", "trace"]))
    t = draw(_token)
    if kind == "key":
        secret = f"exports/packages/{USER}/{t}/package-{t}.zip"
    elif kind == "bucket":
        secret = f"bucket-{t}-files"
    elif kind == "table":
        secret = f"table-{t}-Logstead"
    else:
        secret = f'Traceback (most recent call last):\n  File "/var/task/{t}.py", line 7, in run'
    text = draw(st.sampled_from(["{s}", "boom {s} boom", "AccessDenied on {s}: denied"]))
    return secret, text.format(s=secret)


def _contains_none(blob: str, secret: str) -> bool:
    return secret not in blob and "Traceback" not in blob


class _Repo:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    def get_item(self, pk, sk):
        item = self.items.get((pk, sk))
        return dict(item) if item else None

    def put_item(self, item):
        self.items[(item["PK"], item["SK"])] = dict(item)


class _Files:
    def __init__(self, exc: Exception | None) -> None:
        self.exc = exc

    def upload_file(self, *_a, **_k):
        if self.exc:
            raise self.exc


# stage: where the failure is injected
_STAGES = ["service", "build", "upload"]
_EXC = ["generic", "build_error", "not_found_error"]


def _make(exc_kind: str, text: str) -> Exception:
    if exc_kind == "generic":
        return RuntimeError(text)
    if exc_kind == "build_error":
        return PackageBuildError(text, "internal")
    return PackageBuildError(text, "not_found")


# Feature: accountant-package, Property 14: Messages never leak internals
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    leak=leaks(),
    stage=st.sampled_from(_STAGES),
    exc_kind=st.sampled_from(_EXC),
)
def test_worker_job_message_never_leaks(monkeypatch, leak, stage, exc_kind):
    secret, text = leak
    exc = _make(exc_kind, text)
    repo = _Repo()
    repo.items[(keys.user_pk(USER), keys.package_job_sk(JOB))] = {
        "PK": keys.user_pk(USER),
        "SK": keys.package_job_sk(JOB),
        "userId": USER,
        "id": JOB,
        "taxYear": 2024,
        "status": "queued",
        "propertyIds": ["p1"],
    }
    wiring = SimpleNamespace(repo=repo, files=_Files(exc if stage == "upload" else None))

    class Builder:
        def __init__(self, **_k):
            pass

        def build(self, *_a, **_k):
            if stage == "build":
                raise exc
            raise AssertionError("unreachable")

    def build_service(*_a, **_k):
        if stage == "service":
            raise exc
        return SimpleNamespace(reports=None, itemized=None, transactions=None, properties=None)

    monkeypatch.setattr(package_worker, "get_wiring", lambda: wiring)
    monkeypatch.setattr(package_worker, "build_package_service", build_service)
    monkeypatch.setattr(package_worker, "PackageBuilder", Builder)
    monkeypatch.setattr(package_worker, "default_checklist_provider", lambda *_a: None)

    if stage == "upload":
        # Builder must succeed for the upload stage to be reached.
        class OkBuilder(Builder):
            def build(self, tax_year, ids, zip_path):
                return SimpleNamespace(
                    size_bytes=1, sha256="x", file_count=1, receipt_count=0, skipped_receipt_count=0
                )

        monkeypatch.setattr(package_worker, "PackageBuilder", OkBuilder)

    result = package_worker.handler({"user_id": USER, "job_id": JOB})
    assert result["status"] == "failed"
    job = repo.items[(keys.user_pk(USER), keys.package_job_sk(JOB))]
    assert job["status"] == "failed"
    blob = json.dumps(job, default=str)
    assert _contains_none(blob, secret)
    assert job["message"] in (
        package_worker.GENERIC_MESSAGE,
        package_worker.PROPERTY_GONE_MESSAGE,
    )


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


class _FailingInvoker:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def invoke(self, user_id: str, job_id: str) -> None:
        raise self.exc


class _FailingDeleteFiles:
    """Wraps the real adapter but fails delete with leaking text."""

    def __init__(self, inner, exc: Exception) -> None:
        self._inner, self._exc = inner, exc

    def delete_object(self, key):
        raise self._exc

    def __getattr__(self, name):
        return getattr(self._inner, name)


# Feature: accountant-package, Property 14: Messages never leak internals
@settings(max_examples=50, deadline=None, suppress_health_check=list(HealthCheck))
@given(leak=leaks())
def test_service_messages_never_leak(leak):
    secret, text = leak
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
        files = S3FileAdapter(s3, BUCKET)

        service = PackageJobService(
            repo, USER, files, _FailingInvoker(RuntimeError(text)), clock=lambda: NOW
        )
        result = service.create(2024, None)
        assert not result.is_ok
        assert _contains_none(result.error.message, secret)
        listed = service.list()
        assert listed.is_ok
        for view in listed.value:
            assert _contains_none(json.dumps(view.__dict__, default=str), secret)
            assert view.message is None or _contains_none(view.message, secret)

        # Delete failure on a completed job.
        repo.put_item(
            {
                "PK": keys.user_pk(USER),
                "SK": keys.package_job_sk("done"),
                "userId": USER,
                "id": "done",
                "taxYear": 2023,
                "status": "complete",
                "objectKey": secret,
                "createdAt": NOW.isoformat(),
                "ttl": int(NOW.timestamp()) + 3600,
            }
        )
        deleter = PackageJobService(
            repo, USER, _FailingDeleteFiles(files, RuntimeError(text)), None, clock=lambda: NOW
        )
        deleted = deleter.delete("done")
        assert not deleted.is_ok
        assert _contains_none(deleted.error.message, secret)
