"""Accountant package worker Lambda.

Started by an asynchronous invoke whose event carries only ``user_id`` and
``job_id``. Those are lookup keys; the tax year and property ids come from the
stored job. The worker moves the job ``queued`` -> ``running`` -> ``complete``
or ``failed``. Job messages are fixed strings (or the builder's own limit
message); internal error text, keys, and bucket names never reach the job.
"""
from __future__ import annotations

import logging
import os
import tempfile
import traceback
from datetime import datetime, timezone
from typing import Any

from logstead.adapters.s3_files import package_key
from logstead.repository import keys
from logstead.router.handler import build_package_service, get_wiring, to_jsonable
from logstead.services.accountant_package import (
    PackageBuilder,
    PackageBuildError,
    PackageTooLarge,
    default_checklist_provider,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

GENERIC_MESSAGE = "The package could not be built. Try again."
PROPERTY_GONE_MESSAGE = "A selected property no longer exists."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _put(wiring: Any, user_id: str, job: dict[str, Any]) -> None:
    wiring.repo.put_item(
        {
            "PK": keys.user_pk(user_id),
            "SK": keys.package_job_sk(str(job["id"])),
            "userId": user_id,
            **job,
        }
    )


def _fail(wiring: Any, user_id: str, job: dict[str, Any], message: str) -> str:
    job.pop("objectKey", None)
    job["status"] = "failed"
    job["message"] = message
    job["finishedAt"] = _now().isoformat()
    _put(wiring, user_id, job)
    return "failed"


def _log_failure(exc: BaseException) -> None:
    """Log the error type and the innermost location only (no message text)."""
    frames = traceback.extract_tb(exc.__traceback__)
    where = f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}" if frames else "unknown"
    logger.error("package build failed: %s at %s", type(exc).__name__, where)


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Build the package for the job named in ``event``."""
    event = event if isinstance(event, dict) else {}
    user_id, job_id = event.get("user_id"), event.get("job_id")
    if not isinstance(user_id, str) or not isinstance(job_id, str) or not user_id or not job_id:
        return to_jsonable({"status": "ignored"})

    wiring = get_wiring()
    stored = wiring.repo.get_item(keys.user_pk(user_id), keys.package_job_sk(job_id))
    if (
        stored is None
        or str(stored.get("userId")) != user_id
        or stored.get("status") != "queued"
    ):
        return to_jsonable({"status": "ignored"})

    job: dict[str, Any] = {
        k: v for k, v in stored.items() if k not in ("PK", "SK", "userId")
    }
    job["status"] = "running"
    job["startedAt"] = _now().isoformat()
    _put(wiring, user_id, job)

    status = "failed"
    with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
        try:
            tax_year = int(job["taxYear"])
            services = build_package_service(wiring, user_id)
            builder = PackageBuilder(
                reports=services.reports,
                itemized=services.itemized,
                transactions=services.transactions,
                properties=services.properties,
                files=wiring.files,
                checklist=default_checklist_provider(wiring, user_id),
                clock=_now,
            )
            zip_path = os.path.join(tmp, "package.zip")
            result = builder.build(
                tax_year, [str(p) for p in job.get("propertyIds") or []], zip_path
            )
            key = package_key(user_id, job_id, tax_year)
            wiring.files.upload_file(zip_path, key, "application/zip")
            job.update(
                status="complete",
                objectKey=key,
                sizeBytes=result.size_bytes,
                sha256=result.sha256,
                fileCount=result.file_count,
                receiptCount=result.receipt_count,
                skippedReceiptCount=result.skipped_receipt_count,
                finishedAt=_now().isoformat(),
            )
            job.pop("message", None)
            _put(wiring, user_id, job)
            status = "complete"
        except PackageTooLarge as exc:
            status = _fail(wiring, user_id, job, str(exc))
        except PackageBuildError as exc:
            if exc.kind == "not_found":
                status = _fail(wiring, user_id, job, PROPERTY_GONE_MESSAGE)
            else:
                _log_failure(exc)
                status = _fail(wiring, user_id, job, GENERIC_MESSAGE)
        except Exception as exc:  # noqa: BLE001 - never leak internals to the job
            _log_failure(exc)
            status = _fail(wiring, user_id, job, GENERIC_MESSAGE)
    return to_jsonable({"status": status})
