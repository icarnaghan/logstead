"""Example tests for the package worker handler (accountant-package task 6.7)."""
from __future__ import annotations

import logging
import os
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.accountant_package import (
    PackageBuildError,
    PackageResult,
    PackageTooLarge,
)
from logstead.worker import package_worker as worker

from tests.services.test_package_jobs import TABLE, USER, _create_table

JOB = "job-1"
OTHER = "user-other"
ZIP_KEY = f"exports/packages/{USER}/{JOB}/logstead-accountant-package-2024.zip"


class _Files:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, str]] = []
        self.reads: list[str] = []

    def upload_file(self, path: str, key: str, content_type: str) -> None:
        assert os.path.exists(path)
        self.uploads.append((path, key, content_type))


class _Builder:
    """Stands in for ``PackageBuilder``; behaviour is set per test."""

    behaviour = staticmethod(lambda self, year, ids, path: None)
    instances: list["_Builder"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[int, list[str], str]] = []
        _Builder.instances.append(self)

    def build(self, tax_year, property_ids, zip_path):
        self.calls.append((tax_year, list(property_ids), zip_path))
        with open(zip_path, "wb") as fh:
            fh.write(b"zip")
        return type(self).behaviour(self, tax_year, property_ids, zip_path) or PackageResult(
            size_bytes=3, sha256="ab" * 32, file_count=4, receipt_count=2,
            skipped_receipt_count=1,
        )


@pytest.fixture
def env(monkeypatch):
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        _create_table(ddb)
        repo = DynamoRepository(ddb, TABLE)
        files = _Files()
        wiring = SimpleNamespace(repo=repo, files=files)
        served: list[object] = []
        _Builder.instances = []
        _Builder.behaviour = staticmethod(lambda self, y, i, p: None)

        monkeypatch.setattr(worker, "get_wiring", lambda: wiring)
        monkeypatch.setattr(
            worker,
            "build_package_service",
            lambda w, user_id: (
                served.append(user_id)
                or SimpleNamespace(
                    reports="r", itemized="i", transactions="t", properties="p"
                )
            ),
        )
        monkeypatch.setattr(worker, "PackageBuilder", _Builder)
        monkeypatch.setattr(worker, "default_checklist_provider", lambda w, u: None)
        yield SimpleNamespace(repo=repo, files=files, served=served)


def _put(env, job_id=JOB, user=USER, **fields):
    job = {
        "id": job_id,
        "status": "queued",
        "taxYear": 2024,
        "propertyIds": ["p1", "p2"],
        "createdAt": "2025-03-01T12:00:00+00:00",
        "ttl": 1_900_000_000,
        **fields,
    }
    env.repo.put_item(
        {"PK": keys.user_pk(user), "SK": keys.package_job_sk(job_id), "userId": user, **job}
    )


def _stored(env, job_id=JOB, user=USER):
    return env.repo.get_item(keys.user_pk(user), keys.package_job_sk(job_id))


def _run(user=USER, job=JOB):
    return worker.handler({"user_id": user, "job_id": job}, None)


def _tmp_dir() -> str:
    (builder,) = _Builder.instances
    return os.path.dirname(builder.calls[0][2])


def test_missing_job_is_ignored(env):
    assert _run() == {"status": "ignored"}
    assert _Builder.instances == [] and env.files.uploads == []


@pytest.mark.parametrize("status", ["running", "complete", "failed"])
def test_non_queued_job_is_ignored_and_untouched(env, status):
    _put(env, status=status)
    before = _stored(env)
    assert _run() == {"status": "ignored"}
    assert _stored(env) == before
    assert _Builder.instances == []


@pytest.mark.parametrize("event", [None, {}, {"user_id": USER}, {"job_id": JOB}, {"user_id": 1, "job_id": JOB}])
def test_malformed_event_is_ignored(env, event):
    assert worker.handler(event, None) == {"status": "ignored"}


def test_success_marks_complete_and_uploads(env):
    _put(env, message="old")
    assert _run() == {"status": "complete"}
    job = _stored(env)
    assert job["status"] == "complete"
    assert job["objectKey"] == ZIP_KEY
    assert (job["sizeBytes"], job["fileCount"], job["receiptCount"], job["skippedReceiptCount"]) == (3, 4, 2, 1)
    assert job["sha256"] == "ab" * 32
    assert "message" not in job and job["finishedAt"] and job["startedAt"]
    ((_, key, ctype),) = env.files.uploads
    assert (key, ctype) == (ZIP_KEY, "application/zip")
    assert not os.path.exists(_tmp_dir())


def test_running_state_is_written_before_build(env):
    seen = {}

    def peek(self, y, i, p):
        seen.update(_stored(env))

    _Builder.behaviour = staticmethod(peek)
    _put(env)
    _run()
    assert seen["status"] == "running" and seen["startedAt"]


def test_job_ttl_is_preserved(env):
    _put(env, ttl=1_900_000_123)
    _run()
    assert int(_stored(env)["ttl"]) == 1_900_000_123


def test_package_too_large_uses_its_message(env):
    def boom(self, y, i, p):
        raise PackageTooLarge("The package is too large: more than 100 receipts.")

    _Builder.behaviour = staticmethod(boom)
    _put(env, objectKey="stale")
    assert _run() == {"status": "failed"}
    job = _stored(env)
    assert job["status"] == "failed"
    assert job["message"] == "The package is too large: more than 100 receipts."
    assert "objectKey" not in job and job["finishedAt"]
    assert env.files.uploads == []
    assert not os.path.exists(_tmp_dir())


def test_property_gone_uses_fixed_message(env):
    def boom(self, y, i, p):
        raise PackageBuildError("Property p1 abc not found", kind="not_found")

    _Builder.behaviour = staticmethod(boom)
    _put(env)
    assert _run() == {"status": "failed"}
    assert _stored(env)["message"] == worker.PROPERTY_GONE_MESSAGE
    assert not os.path.exists(_tmp_dir())


def test_other_build_error_is_generic(env):
    def boom(self, y, i, p):
        raise PackageBuildError("table Logstead throttled", kind="unavailable")

    _Builder.behaviour = staticmethod(boom)
    _put(env)
    assert _run() == {"status": "failed"}
    assert _stored(env)["message"] == worker.GENERIC_MESSAGE


def test_unexpected_exception_is_generic_logged_without_text(env, caplog):
    def boom(self, y, i, p):
        raise ValueError("secret-bucket exports/packages/user-abc")

    _Builder.behaviour = staticmethod(boom)
    _put(env)
    with caplog.at_level(logging.ERROR, logger=worker.logger.name):
        assert _run() == {"status": "failed"}
    job = _stored(env)
    assert job["message"] == worker.GENERIC_MESSAGE
    assert "secret" not in str(job)
    assert "ValueError" in caplog.text
    assert "secret" not in caplog.text and USER not in caplog.text
    assert not os.path.exists(_tmp_dir())


def test_upload_failure_fails_job_and_removes_temp_dir(env):
    def bad_upload(path, key, content_type):
        raise RuntimeError("s3 secret")

    env.files.upload_file = bad_upload
    _put(env)
    assert _run() == {"status": "failed"}
    job = _stored(env)
    assert job["message"] == worker.GENERIC_MESSAGE and "objectKey" not in job
    assert not os.path.exists(_tmp_dir())


def test_only_stored_job_data_is_used(env):
    _put(env, taxYear=2023, propertyIds=["p9"])
    _put(env, user=OTHER, taxYear=2020, propertyIds=["other"], message="mine")
    # event carries extra fields that must not influence the build
    worker.handler(
        {"user_id": USER, "job_id": JOB, "tax_year": 1999, "property_ids": ["evil"]}, None
    )
    (builder,) = _Builder.instances
    assert builder.calls[0][:2] == (2023, ["p9"])
    assert env.served == [USER]
    assert _stored(env)["taxYear"] == 2023
    # the other user's job is untouched
    assert _stored(env, user=OTHER)["status"] == "queued"


def test_other_users_job_id_is_ignored(env):
    _put(env, user=OTHER)
    assert _run(user=USER, job=JOB) == {"status": "ignored"}
    assert _stored(env, user=OTHER)["status"] == "queued"
    assert _Builder.instances == []
