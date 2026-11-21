"""Accountant package job records and lifecycle (API side).

A job is a transient item at ``USER#<userId> / ACCTPKG#<jobId>`` with a ``ttl``.
Ownership is the partition key, so another user's job id is ``not_found``,
identical to a missing id. The worker (a separate Lambda) moves the job through
``running`` to ``complete`` or ``failed``; this module creates it, reads it,
applies the stale rule at read time, and deletes it.

``effective_status``, ``is_active`` and ``is_expired`` are pure.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from logstead.adapters.package_invoker import PackageInvoker
from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.result import Result
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.auth import UserContext, user_id_of
from logstead.services.package_config import (
    DOWNLOAD_LINK_SECONDS,
    JOB_LIST_LIMIT,
    JOB_STALE_SECONDS,
    JOB_TTL_SECONDS,
)
from logstead.services.property import PropertyService

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"

STALE_MESSAGE = "The package did not finish. Try again."
INVOKE_FAILED_MESSAGE = "The package could not be started. Try again."
_NOT_FOUND = "Package not found."


@dataclass
class PackageJobView:
    """Wire view of a package job (snake_case fields)."""

    id: str
    status: str
    tax_year: int
    property_ids: list[str]
    created_at: str | None
    finished_at: str | None
    message: str | None
    size_bytes: int | None
    sha256: str | None
    file_count: int | None
    receipt_count: int | None
    skipped_receipt_count: int | None
    download_url: str | None
    download_expires_in_seconds: int | None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _last_change(job: Mapping[str, Any]) -> datetime | None:
    return _parse(job.get("startedAt")) or _parse(job.get("createdAt"))


def _is_stale(job: Mapping[str, Any], now: datetime) -> bool:
    if job.get("status") not in (STATUS_QUEUED, STATUS_RUNNING):
        return False
    changed = _last_change(job)
    if changed is None:
        return False
    return (now - changed).total_seconds() > JOB_STALE_SECONDS


def effective_status(job: Mapping[str, Any], now: datetime) -> str:
    """Stored status, or ``failed`` for a stale ``queued``/``running`` job."""
    if _is_stale(job, now):
        return STATUS_FAILED
    return str(job.get("status"))


def is_active(job: Mapping[str, Any], now: datetime) -> bool:
    """True for a stored ``queued``/``running`` job that is not stale."""
    return job.get("status") in (STATUS_QUEUED, STATUS_RUNNING) and not _is_stale(
        job, now
    )


def is_expired(job: Mapping[str, Any], now: datetime) -> bool:
    """True when the job's ``ttl`` (epoch seconds) has passed."""
    ttl = job.get("ttl")
    if ttl is None:
        return False
    return float(ttl) <= now.timestamp()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


class PackageJobService:
    """Create, list, read, and delete package jobs for one user."""

    def __init__(
        self,
        repo: DynamoRepository,
        user: UserContext | str,
        files: S3FileAdapter,
        invoker: PackageInvoker,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._user_id = user_id_of(user) if isinstance(user, UserContext) else user
        self._files = files
        self._invoker = invoker
        self._clock = clock
        self._properties = PropertyService(repo, self._user_id)

    # --- create ---------------------------------------------------------------
    def create(
        self, tax_year: int, property_ids: list[str] | None
    ) -> Result[PackageJobView]:
        resolved = self._resolve_properties(property_ids)
        if not resolved.is_ok:
            return Result.failure(
                resolved.error.kind,  # type: ignore[union-attr]
                resolved.error.message,  # type: ignore[union-attr]
                resolved.error.field,  # type: ignore[union-attr]
            )
        ids = resolved.value

        now = self._clock()
        for job in self._load_jobs():
            if not is_expired(job, now) and is_active(job, now):
                return Result.failure(
                    "conflict",
                    f"A package for tax year {int(job['taxYear'])} is already "
                    "being prepared.",
                )

        job_id = str(uuid.uuid4())
        job: dict[str, Any] = {
            "id": job_id,
            "status": STATUS_QUEUED,
            "taxYear": int(tax_year),
            "propertyIds": ids,
            "createdAt": now.isoformat(),
            "ttl": int(now.timestamp()) + JOB_TTL_SECONDS,
        }
        self._put(job)
        try:
            self._invoker.invoke(self._user_id, job_id)
        except Exception:  # noqa: BLE001 - any invoke failure maps to unavailable
            job["status"] = STATUS_FAILED
            job["message"] = INVOKE_FAILED_MESSAGE
            job["finishedAt"] = self._clock().isoformat()
            self._put(job)
            return Result.failure("unavailable", INVOKE_FAILED_MESSAGE)
        return Result.success(self._view(job, now))

    # --- read -----------------------------------------------------------------
    def list(self) -> Result[list[PackageJobView]]:
        now = self._clock()
        jobs = [j for j in self._load_jobs() if not is_expired(j, now)]
        jobs.sort(key=lambda j: str(j.get("createdAt") or ""), reverse=True)
        return Result.success([self._view(j, now) for j in jobs[:JOB_LIST_LIMIT]])

    def get(self, job_id: str) -> Result[PackageJobView]:
        now = self._clock()
        job = self._load_job(job_id)
        if job is None or is_expired(job, now):
            return Result.failure("not_found", _NOT_FOUND)
        return Result.success(self._view(job, now))

    # --- delete ---------------------------------------------------------------
    def delete(self, job_id: str) -> Result[None]:
        now = self._clock()
        job = self._load_job(job_id)
        if job is None or is_expired(job, now):
            return Result.failure("not_found", _NOT_FOUND)
        if is_active(job, now):
            return Result.failure(
                "conflict", "The package is still being prepared. Try again later."
            )
        key = job.get("objectKey")
        if key:
            try:
                self._files.delete_object(str(key))
            except Exception:  # noqa: BLE001 - keep the item so delete can retry
                return Result.failure(
                    "unavailable", "The package could not be deleted. Try again."
                )
        self._repo.delete_item(
            keys.user_pk(self._user_id), keys.package_job_sk(job_id)
        )
        return Result.success(None)

    # --- internals --------------------------------------------------------------
    def _resolve_properties(
        self, property_ids: list[str] | None
    ) -> Result[list[str]]:
        if property_ids is None:
            ids = [p.id for p in self._properties.list()]
        else:
            ids = list(dict.fromkeys(str(p) for p in property_ids))
            for pid in ids:
                found = self._properties.get(pid)
                if not found.is_ok:
                    return Result.failure("not_found", "Property not found.")
        if not ids:
            return Result.failure(
                "validation", "Select at least one property.", "property_ids"
            )
        return Result.success(ids)

    def _put(self, job: dict[str, Any]) -> None:
        self._repo.put_item(
            {
                "PK": keys.user_pk(self._user_id),
                "SK": keys.package_job_sk(str(job["id"])),
                "userId": self._user_id,
                **job,
            }
        )

    def _load_job(self, job_id: str) -> dict[str, Any] | None:
        item = self._repo.get_item(
            keys.user_pk(self._user_id), keys.package_job_sk(job_id)
        )
        if item is None or str(item.get("userId")) != self._user_id:
            return None
        return item

    def _load_jobs(self) -> list[dict[str, Any]]:
        return self._repo.query(
            keys.user_pk(self._user_id), sk_begins_with=keys.PACKAGE_JOB_PREFIX
        )

    def _view(self, job: Mapping[str, Any], now: datetime) -> PackageJobView:
        status = effective_status(job, now)
        stale = status != job.get("status")
        message = STALE_MESSAGE if stale else job.get("message")
        url: str | None = None
        expires: int | None = None
        if status == STATUS_COMPLETE and job.get("objectKey"):
            url = self._files.presigned_get_url(
                str(job["objectKey"]),
                expires_in=DOWNLOAD_LINK_SECONDS,
                download_filename=(
                    f"logstead-accountant-package-{int(job['taxYear'])}.zip"
                ),
            )
            expires = DOWNLOAD_LINK_SECONDS
        return PackageJobView(
            id=str(job["id"]),
            status=status,
            tax_year=int(job["taxYear"]),
            property_ids=[str(p) for p in job.get("propertyIds") or []],
            created_at=job.get("createdAt"),
            finished_at=job.get("finishedAt"),
            message=None if message is None else str(message),
            size_bytes=_opt_int(job.get("sizeBytes")),
            sha256=job.get("sha256"),
            file_count=_opt_int(job.get("fileCount")),
            receipt_count=_opt_int(job.get("receiptCount")),
            skipped_receipt_count=_opt_int(job.get("skippedReceiptCount")),
            download_url=url,
            download_expires_in_seconds=expires,
        )
