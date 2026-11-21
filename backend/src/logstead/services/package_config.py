"""Limits for the accountant package and generated PDF downloads.

This module is the only place these numbers are defined in the backend.
The retention values are mirrored by the one-day lifecycle rules in
``infra/template.yaml``.
"""

from __future__ import annotations

PACKAGE_MAX_BYTES = 400 * 1024 * 1024
PACKAGE_MAX_RECEIPTS = 2000
DOWNLOAD_LINK_SECONDS = 900
JOB_TTL_SECONDS = 24 * 60 * 60
JOB_STALE_SECONDS = 900
JOB_LIST_LIMIT = 10
COPY_CHUNK_BYTES = 1024 * 1024
