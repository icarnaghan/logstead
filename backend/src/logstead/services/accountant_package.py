"""Accountant package builder.

Assembles one ZIP for a user and a tax year from data the app already holds:
Schedule E reports (PDF, CSV, JSON), a transactions CSV, the year's receipts,
an optional year-end checklist, a README, and a manifest with SHA-256
checksums. Every figure comes from ``ReportingService``; this module sums
nothing. Receipt metadata is read without presigning or purging, and receipt
bytes are streamed into a local ZIP file in chunks.

The only writes are to the ZIP file path given to :meth:`PackageBuilder.build`.
Uploading the file and updating the job item belong to the worker.
"""
from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import os
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from logstead.adapters.s3_files import MAX_DOCUMENT_BYTES
from logstead.models.result import Result
from logstead.services import package_config as config
from logstead.services.category import CATEGORY_CATALOG
from logstead.services.csv_safe import neutralize_cell
from logstead.services.package_paths import (
    dedupe_entry_path,
    is_safe_entry_path,
    receipt_entry_path,
    slugify,
    unique_slugs,
)
from logstead.services.report import serialize_combined, serialize_report
from logstead.services.report_pdf import (
    RepairsDetail,
    RepairsEntry,
    render_combined_pdf,
    render_property_pdf,
)
from logstead.util.money import money_to_str, to_money

if TYPE_CHECKING:  # pragma: no cover
    from logstead.adapters.s3_files import S3FileAdapter
    from logstead.models.transaction import Document, Transaction
    from logstead.services.itemized import ItemizedExpenseService
    from logstead.services.property import PropertyService
    from logstead.services.report import ReportingService
    from logstead.services.transaction import TransactionService

DISCLAIMER = "Built from your own records. An organizing aid, not tax advice."
CHECKLIST_NOT_AVAILABLE = "not available in this release"
CHECKLIST_FAILED = "could not be generated"

_CATEGORY_LABELS = {c.id: c.label for c in CATEGORY_CATALOG}

TRANSACTION_COLUMNS = (
    "property",
    "transaction_id",
    "date",
    "type",
    "category",
    "schedule_e_line",
    "amount",
    "description",
    "notes",
    "imported",
    "itemized",
    "document_count",
    "document_paths",
)


# --- Results and errors -------------------------------------------------------


@dataclass(frozen=True)
class PackageResult:
    size_bytes: int
    sha256: str
    file_count: int
    receipt_count: int
    skipped_receipt_count: int


class PackageTooLarge(Exception):
    """The package exceeds a configured limit. The message names the limit."""


class PackageBuildError(Exception):
    """A source service failed. ``kind`` is the failing ``Result`` error kind."""

    def __init__(self, message: str, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


class ChecklistProvider(Protocol):
    def checklist_for(self, property_id: str, tax_year: int) -> Result[Any]: ...


def default_checklist_provider(wiring: Any, user: Any) -> ChecklistProvider | None:
    """Return the year-end checklist provider, or ``None`` when unavailable.

    The checklist module is imported at run time so the package works when it
    is absent. A missing module, a missing ``provider_for``, or a provider
    that raises all mean "no checklist".
    """
    try:
        module = importlib.import_module("logstead.services.checklist")
    except ImportError:
        return None
    hook = getattr(module, "provider_for", None)
    if hook is None:
        return None
    try:
        return hook(wiring, user)
    except Exception:  # noqa: BLE001 - an optional hook must not fail the build
        return None


# --- Internal entry model -----------------------------------------------------


@dataclass
class _Entry:
    path: str
    kind: str
    data: bytes | None = None  # in-memory text entries
    s3_key: str | None = None  # receipts, streamed at write time


@dataclass(frozen=True)
class _SkippedReceipt:
    transaction_id: str
    document_id: str
    original_filename: str
    reason: str


@dataclass
class _Plan:
    entries: list[_Entry] = field(default_factory=list)
    skipped: list[_SkippedReceipt] = field(default_factory=list)


def _jsonable(value: Any) -> Any:
    """JSON-ready copy of ``value``; ``Decimal`` becomes a two-decimal string."""
    if isinstance(value, Decimal):
        return money_to_str(to_money(value))
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _limit_message(what: str) -> str:
    return f"{what} Select fewer properties and try again."


# --- Builder ------------------------------------------------------------------


class PackageBuilder:
    """Builds the accountant package ZIP for a user, year, and property set."""

    def __init__(
        self,
        reports: "ReportingService",
        itemized: "ItemizedExpenseService",
        transactions: "TransactionService",
        properties: "PropertyService",
        files: "S3FileAdapter",
        checklist: ChecklistProvider | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._reports = reports
        self._itemized = itemized
        self._transactions = transactions
        self._properties = properties
        self._files = files
        self._checklist = checklist
        self._clock = clock

    # --- public ---------------------------------------------------------------

    def build(
        self, tax_year: int, property_ids: Sequence[str], zip_path: str
    ) -> PackageResult:
        generated = _utc(self._clock()).replace(microsecond=0)
        generated_at = generated.isoformat()
        generated_on: date = generated.date()
        ids = list(dict.fromkeys(property_ids))

        # 1. Reports and Repairs detail, straight from the services.
        reports = []
        repairs: dict[str, RepairsDetail | None] = {}
        for pid in ids:
            reports.append(self._unwrap(self._reports.report_for(pid, tax_year)))
            repairs[pid] = self._repairs_detail(pid, tax_year)
        combined = (
            self._unwrap(self._reports.combined_report(ids, tax_year))
            if len(ids) >= 2
            else None
        )

        slugs = unique_slugs(
            [(r.header.property_id, r.header.property_name) for r in reports]
        )

        # 2. Transactions and receipt metadata.
        rows: list[tuple[str, "Transaction", list["Document"]]] = []
        receipt_total = 0
        for report in reports:
            pid = report.header.property_id
            listed = self._unwrap(self._transactions.list_for_property(pid, tax_year))
            for txn in listed:
                docs = sorted(
                    self._transactions.receipt_documents(pid, txn), key=lambda d: d.id
                )
                receipt_total += len(docs)
                rows.append((pid, txn, docs))
            if receipt_total > config.PACKAGE_MAX_RECEIPTS:
                raise PackageTooLarge(
                    _limit_message(
                        f"This package would hold more than "
                        f"{config.PACKAGE_MAX_RECEIPTS} receipts."
                    )
                )

        # 3. Plan the entries. Receipts are resolved first so the transactions
        #    CSV can list the paths of the receipts that are really included.
        plan = _Plan()
        taken: set[str] = set()

        def add_fixed(path: str, kind: str, data: bytes) -> None:
            if not is_safe_entry_path(path) or path in taken:
                raise PackageBuildError("A package file name was not valid.")
            taken.add(path)
            plan.entries.append(_Entry(path=path, kind=kind, data=data))

        for report in reports:
            pid = report.header.property_id
            base = f"reports/schedule-e-{slugs[pid]}-{tax_year}"
            add_fixed(
                f"{base}.pdf",
                "report_pdf",
                render_property_pdf(report, repairs.get(pid), generated_on),
            )
            add_fixed(f"{base}.csv", "report_csv", serialize_report(report, "csv"))
            add_fixed(f"{base}.json", "report_json", serialize_report(report, "json"))
        if combined is not None:
            base = f"reports/schedule-e-combined-{tax_year}"
            add_fixed(
                f"{base}.pdf", "report_pdf", render_combined_pdf(combined, repairs, generated_on)
            )
            add_fixed(f"{base}.csv", "report_csv", serialize_combined(combined, "csv"))
            add_fixed(f"{base}.json", "report_json", serialize_combined(combined, "json"))

        checklist_section = self._add_checklist(
            tax_year, reports, lambda p, d: add_fixed(p, "checklist", d)
        )

        doc_paths: dict[str, list[str]] = {}
        receipt_count = 0
        for pid, txn, docs in rows:
            for doc in docs:
                status = self._probe(doc.s3_key)
                if status is not None:
                    plan.skipped.append(
                        _SkippedReceipt(txn.id, doc.id, doc.original_filename, status)
                    )
                    continue
                category_slug = slugify(
                    _CATEGORY_LABELS.get(txn.category_id, txn.category_id),
                    "uncategorized",
                )
                path = dedupe_entry_path(
                    receipt_entry_path(
                        slugs[pid], category_slug, txn.date, txn.id, doc.original_filename
                    ),
                    taken | {"manifest.json"},
                )
                if not is_safe_entry_path(path):
                    raise PackageBuildError("A package file name was not valid.")
                taken.add(path)
                plan.entries.append(_Entry(path=path, kind="receipt", s3_key=doc.s3_key))
                doc_paths.setdefault(txn.id, []).append(path)
                receipt_count += 1

        add_fixed(
            f"transactions/transactions-{tax_year}.csv",
            "transactions_csv",
            self._transactions_csv(reports, rows, doc_paths),
        )
        add_fixed(
            "README.txt",
            "readme",
            self._readme(tax_year, generated_at, reports, checklist_section).encode("utf-8"),
        )

        # 4. Write the ZIP: sorted entries, then the manifest last.
        manifest_files: list[dict[str, Any]] = []
        stamp = (max(generated.year, 1980), generated.month, generated.day,
                 generated.hour, generated.minute, generated.second)
        with zipfile.ZipFile(zip_path, "w", allowZip64=True) as zf:
            for entry in sorted(plan.entries, key=lambda e: e.path):
                size, digest = self._write_entry(zf, entry, stamp)
                manifest_files.append(
                    {"path": entry.path, "kind": entry.kind, "size_bytes": size, "sha256": digest}
                )
                self._check_size(zf, zip_path)
            manifest = self._manifest(
                tax_year, generated_at, reports, manifest_files, plan.skipped,
                checklist_section, receipt_count,
            )
            self._write_entry(
                zf, _Entry("manifest.json", "manifest", data=manifest), stamp
            )
            self._check_size(zf, zip_path)

        return PackageResult(
            size_bytes=os.path.getsize(zip_path),
            sha256=self._file_sha256(zip_path),
            file_count=len(manifest_files),
            receipt_count=receipt_count,
            skipped_receipt_count=len(plan.skipped),
        )

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _unwrap(result: Result[Any]) -> Any:
        if not result.is_ok:
            raise PackageBuildError(result.error.message, result.error.kind)
        return result.value

    def _repairs_detail(self, property_id: str, tax_year: int) -> RepairsDetail:
        summary = self._unwrap(self._itemized.summary(property_id, "repairs", tax_year))
        entries = sorted(summary.entries, key=lambda t: (t.date, t.id))
        return RepairsDetail(
            entries=tuple(
                RepairsEntry(
                    id=t.id, date=t.date, description=t.description or "", amount=t.amount
                )
                for t in entries
            ),
            entered_total=summary.entered_total,
            itemized_sum=summary.itemized_sum,
            line_total=summary.line_total,
            line_source=str(summary.line_source),
        )

    def _probe(self, s3_key: str) -> str | None:
        """Return a skip reason (``missing`` or ``oversized``), or ``None``."""
        opened = self._files.open_stream(s3_key)
        if opened is None:
            return "missing"
        body, length = opened
        try:
            if length > MAX_DOCUMENT_BYTES:
                return "oversized"
        finally:
            _close(body)
        return None

    def _add_checklist(
        self,
        tax_year: int,
        reports: Sequence[Any],
        add: Callable[[str, bytes], None],
    ) -> dict[str, Any]:
        if self._checklist is None:
            return {"included": False, "reason": CHECKLIST_NOT_AVAILABLE}
        items: list[dict[str, Any]] = []
        try:
            for report in reports:
                result = self._checklist.checklist_for(report.header.property_id, tax_year)
                if not result.is_ok:
                    return {"included": False, "reason": CHECKLIST_FAILED}
                items.append(
                    {
                        "property_id": report.header.property_id,
                        "property_name": report.header.property_name,
                        "checklist": _jsonable(result.value),
                    }
                )
        except Exception:  # noqa: BLE001 - the checklist is optional
            return {"included": False, "reason": CHECKLIST_FAILED}
        path = f"checklist/year-end-checklist-{tax_year}.json"
        payload = {"tax_year": tax_year, "properties": items}
        add(path, json.dumps(payload, indent=2).encode("utf-8"))
        return {"included": True, "path": path}

    @staticmethod
    def _transactions_csv(
        reports: Sequence[Any],
        rows: Sequence[tuple[str, "Transaction", list["Document"]]],
        doc_paths: dict[str, list[str]],
    ) -> bytes:
        names = {r.header.property_id: r.header.property_name for r in reports}
        ordered = sorted(rows, key=lambda r: (names[r[0]], r[1].date, r[1].id))
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(TRANSACTION_COLUMNS)
        for pid, txn, docs in ordered:
            writer.writerow(
                [
                    neutralize_cell(names[pid]),
                    txn.id,
                    txn.date,
                    txn.type,
                    neutralize_cell(_CATEGORY_LABELS.get(txn.category_id, txn.category_id)),
                    txn.schedule_e_line,
                    money_to_str(txn.amount),
                    neutralize_cell(txn.description or ""),
                    neutralize_cell(txn.notes or ""),
                    "true" if txn.imported else "false",
                    "true" if txn.itemized else "false",
                    len(docs),
                    ";".join(doc_paths.get(txn.id, [])),
                ]
            )
        return buf.getvalue().encode("utf-8")

    @staticmethod
    def _readme(
        tax_year: int,
        generated_at: str,
        reports: Sequence[Any],
        checklist_section: dict[str, Any],
    ) -> str:
        checklist_line = (
            f"  {checklist_section['path']}\n"
            "      A year-end checklist for each property. It is a reminder aid and\n"
            "      not tax advice."
            if checklist_section["included"]
            else f"  checklist/ is not included ({checklist_section['reason']})."
        )
        names = "\n".join(f"  - {r.header.property_name}" for r in reports)
        return (
            f"Logstead accountant package, tax year {tax_year}\n"
            f"Generated: {generated_at}\n\n"
            f"{DISCLAIMER}\n\n"
            f"Properties included:\n{names}\n\n"
            "Contents\n"
            "  reports/\n"
            "      Schedule E worksheets as PDF, CSV, and JSON for each property, plus a\n"
            "      combined set when two or more properties are included. The PDF is a\n"
            "      worksheet laid out like Schedule E Part I. It is not an IRS form.\n"
            f"  transactions/transactions-{tax_year}.csv\n"
            "      Every stored transaction row for the year. The Schedule E report\n"
            "      applies the entered-total and loan-interest rules, so the sum of this\n"
            "      CSV can differ from a report line.\n"
            "  receipts/<property>/<category>/\n"
            "      Receipts attached to the year's transactions. Receipts that could not\n"
            "      be read are listed in manifest.json under receipts_skipped.\n"
            f"{checklist_line}\n"
            "  manifest.json\n"
            "      Every file with its size and SHA-256 checksum.\n\n"
            "Verify a file\n"
            "  Run: shasum -a 256 <file>\n"
            "  and compare the result with the checksum listed in manifest.json.\n"
        )

    def _manifest(
        self,
        tax_year: int,
        generated_at: str,
        reports: Sequence[Any],
        files: list[dict[str, Any]],
        skipped: list[_SkippedReceipt],
        checklist_section: dict[str, Any],
        receipt_count: int,
    ) -> bytes:
        payload = {
            "schema_version": 1,
            "app": "Logstead",
            "tax_year": tax_year,
            "generated_at": generated_at,
            "disclaimer": DISCLAIMER,
            "properties": [
                {"property_id": r.header.property_id, "name": r.header.property_name}
                for r in reports
            ],
            "files": files,
            "receipts_skipped": [
                {
                    "transaction_id": s.transaction_id,
                    "document_id": s.document_id,
                    "original_filename": s.original_filename,
                    "reason": s.reason,
                }
                for s in skipped
            ],
            "sections": {"checklist": checklist_section},
            "totals": {
                "files": len(files),
                "receipts_included": receipt_count,
                "receipts_skipped": len(skipped),
                "bytes": sum(f["size_bytes"] for f in files),
            },
        }
        return json.dumps(payload, indent=2).encode("utf-8")

    def _write_entry(
        self, zf: zipfile.ZipFile, entry: _Entry, stamp: tuple[int, ...]
    ) -> tuple[int, str]:
        info = zipfile.ZipInfo(entry.path, date_time=stamp)  # type: ignore[arg-type]
        info.external_attr = 0o644 << 16
        digest = hashlib.sha256()
        size = 0
        if entry.data is not None:
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, entry.data)
            digest.update(entry.data)
            return len(entry.data), digest.hexdigest()

        info.compress_type = zipfile.ZIP_STORED
        opened = self._files.open_stream(entry.s3_key or "")
        if opened is None:
            raise PackageBuildError("A receipt changed while the package was built. Try again.")
        body, _length = opened
        try:
            with zf.open(info, "w") as dest:
                while True:
                    chunk = body.read(config.COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    dest.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        finally:
            _close(body)
        return size, digest.hexdigest()

    @staticmethod
    def _check_size(zf: zipfile.ZipFile, zip_path: str) -> None:
        if zf.fp is not None:
            zf.fp.flush()
        if os.path.getsize(zip_path) > config.PACKAGE_MAX_BYTES:
            limit_mb = config.PACKAGE_MAX_BYTES // (1024 * 1024)
            raise PackageTooLarge(
                _limit_message(f"This package would be larger than {limit_mb} MB.")
            )

    @staticmethod
    def _file_sha256(path: str) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(config.COPY_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()


def _close(body: Any) -> None:
    close = getattr(body, "close", None)
    if close is not None:
        close()
