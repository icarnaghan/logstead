"""Backup document domain models (Requirements 1, 2, 5, 13).

These frozen dataclasses model a parsed :class:`BackupDocument` — the portable
JSON export/restore format for a single user's Schedule E data. They mirror the
document shape described in the design's "Data Models -> Backup_Document"
section.

Money and coordinate fields are typed as :class:`decimal.Decimal`: the raw JSON
carries them as exact strings, and :func:`logstead.services.backup.validate_document`
parses them into ``Decimal`` (money via :func:`logstead.util.money.to_money`,
coordinates as full-precision ``Decimal``) so no value passes through a float.

The document deliberately excludes photos, receipts, import sessions, PDF
drafts, the category catalog, and depreciation schedule rows (recomputed on
restore). ``schedule_e_line`` is carried on a parsed transaction but is ignored
on restore — it is re-derived from ``category_id`` — so it is optional here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from logstead.models.property import PropertyDetails

__all__ = [
    "SCHEMA_VERSION",
    "BackupUsageYear",
    "BackupTransaction",
    "BackupAsset",
    "BackupProperty",
    "BackupDocument",
    "RestoreSummary",
    "ClearSummary",
]

#: The single Schema_Version this build produces and accepts (Requirement 1.11,
#: 5). Validation rejects any document whose ``schema_version`` differs.
SCHEMA_VERSION: Final[str] = "1"


@dataclass(frozen=True)
class BackupUsageYear:
    """A property's per-tax-year usage days inside a backup (Requirement 1.5)."""

    tax_year: int
    fair_rental_days: int
    personal_use_days: int


@dataclass(frozen=True)
class BackupTransaction:
    """A transaction as carried in a backup document (Requirement 1.6).

    ``amount`` is an exact two-decimal ``Decimal`` after parsing. ``schedule_e_line``
    is optional and ignored on restore — it is re-derived from ``category_id``
    against the current catalog — so the document stays decoupled from Schedule E
    line assignments.
    """

    id: str
    property_id: str
    date: str
    amount: Decimal
    type: str
    category_id: str
    schedule_e_line: int | None = None
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class BackupAsset:
    """A depreciable asset as carried in a backup document (Requirement 1.7).

    ``cost_basis`` is an exact two-decimal ``Decimal`` (money) and
    ``recovery_period_years`` is a plain full-precision ``Decimal`` (not money)
    after parsing. Schedule rows are never carried; they are recomputed on
    restore (Requirement 2.5).
    """

    id: str
    property_id: str
    description: str
    cost_basis: Decimal
    placed_in_service_date: str
    recovery_period_years: Decimal
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class BackupProperty:
    """A property and its nested children inside a backup (Requirement 1.1-1.7).

    ``details`` is the parsed sparse :class:`PropertyDetails` tree (via
    :func:`details_from_dict`) when present. ``note`` is the free-text note when
    set. ``usage``/``transactions``/``assets`` are ordered lists; empty lists are
    permitted and simply produce no child writes on restore.
    """

    id: str
    name: str
    address_text: str
    property_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    details: PropertyDetails | None = None
    note: str | None = None
    usage: list[BackupUsageYear] = field(default_factory=list)
    transactions: list[BackupTransaction] = field(default_factory=list)
    assets: list[BackupAsset] = field(default_factory=list)


@dataclass(frozen=True)
class BackupDocument:
    """A parsed, versioned backup document (Requirements 1, 5, 13).

    ``schema_version`` identifies the format (always :data:`SCHEMA_VERSION` for a
    document this build accepts). ``exported_at`` is an informational ISO-8601
    timestamp not used for restore decisions. ``properties`` holds every
    exported property with its nested children.
    """

    schema_version: str
    exported_at: str
    properties: list[BackupProperty] = field(default_factory=list)


@dataclass(frozen=True)
class RestoreSummary:
    """Counts returned by a successful restore (Requirement 2)."""

    properties: int
    transactions: int
    assets: int
    usage_years: int


@dataclass(frozen=True)
class ClearSummary:
    """Counts returned by a clear, plus best-effort S3 failures (Requirement 8).

    ``failed_s3_keys`` lists any S3 object whose deletion failed; the clear
    records them and continues rather than aborting (Requirement 8.4).
    """

    properties: int
    transactions: int
    assets: int
    photos: int
    receipts: int
    failed_s3_keys: list[str] = field(default_factory=list)
