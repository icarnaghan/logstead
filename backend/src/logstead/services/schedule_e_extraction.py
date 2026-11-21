"""Schedule E PDF Extraction service ("layer 2").

The ``ExtractionService`` turns a prior-year tax-return PDF into a pre-filled,
reviewable layer-1 ``Import_Submission`` draft. The governing principle is
**extraction proposes, the human confirms, layer 1 persists**: this service
performs **no** persistent domain writes. Its only durable write is a transient,
per-user, TTL'd ``Extraction_Job`` record (design "Extraction_Job — a new
transient DynamoDB entity"), and the uploaded PDF is auto-deleted from S3 the
instant a job reaches a terminal state (``complete`` or ``failed``). Only the
user-confirmed numbers persist, and only via the unchanged layer-1
``ImportService`` write path (``POST /imports/schedule-e``).

The service composes four collaborators, all injected:

* a :class:`~logstead.repository.dynamo_repo.DynamoRepository` for job persistence,
* an :class:`~logstead.adapters.s3_files.S3FileAdapter` for the presigned PUT, the
  PDF-signature read, and the terminal-state delete,
* a :class:`~logstead.adapters.textract.TextractAdapter` for async document analysis,
* a user-scoped :class:`~logstead.services.property.PropertyService` (constructed
  internally) as the fuzzy-match source for suggested property mappings.

Every method is **user-scoped**: a ``job_id`` resolving to a job owned by a
different user returns ``not_found`` (Req 11.2), because the job is keyed under
``USER#<userId>``.

The async flow is a two-step start plus a poll (design "The async-completion
mechanism"):

* :meth:`start_extraction` validates the declared content type, mints a job id,
  issues a presigned PUT, and persists the job ``pending`` (Req 1).
* :meth:`begin_extraction` confirms the uploaded object exists and is a PDF, then
  starts the Textract job and marks it ``processing`` (Req 2).
* :meth:`get_status` polls Textract; on the first ``SUCCEEDED`` poll it parses the
  blocks once into a :class:`ReviewDraft`, caches it on the job, marks the job
  terminal, and deletes the PDF. Later polls return the cached result without
  re-calling Textract or re-parsing (Req 3).
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from logstead.adapters.s3_files import (
    IMPORT_PREFIX,
    MAX_IMPORT_PDF_BYTES,
    S3FileAdapter,
    build_key,
)
from logstead.adapters.textract import TextractAdapter
from logstead.models.result import Result
from logstead.models.schedule_e_extraction import (
    ExtractedColumn,
    ExtractedLine,
    ExtractionJobView,
    ReviewDraft,
    StartExtractionOutcome,
)
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.address_match import best_match
from logstead.services.auth import user_id_of
from logstead.services.property import PropertyService
from logstead.services.schedule_e_parser import ParsedExtraction, parse_schedule_e
from logstead.util.money import money_to_str, to_money

__all__ = [
    "ExtractionService",
    "PDF_CONTENT_TYPE",
    "DEFAULT_MIN_CONFIDENCE",
    "MAX_UPLOAD_PAGES",
]

#: The one content type an uploaded tax-return document may declare (Req 1.4).
#: ``start_extraction`` rejects anything else, and the presigned PUT is bound to
#: this exact type so the eventual upload must declare it too.
PDF_CONTENT_TYPE = "application/pdf"

#: The ``%PDF-`` magic bytes that open every valid PDF. ``begin_extraction``
#: reads the leading bytes of the uploaded object and requires this signature so
#: a mislabeled / corrupt upload is caught before Textract is ever called
#: (design Error Handling: "Object present but not a readable PDF").
_PDF_SIGNATURE = b"%PDF-"

#: The sub-prefix under ``imports/`` this feature's uploads land on, so the S3
#: lifecycle rule (``ExpireScheduleEImports``) scopes precisely to them and the
#: expense feature's ``imports/`` objects are never touched.
_SCHEDULE_E_IMPORT_SEGMENT = "schedule-e"

#: Confidence floor (0-100) handed to the pure parser. A line/address/year with a
#: contributing-block confidence below this — or that could not be read — is
#: flagged ``needs_verification`` (Req 5.2, 8.3). 80.0 is a sensible middle
#: ground: Textract reports high confidence (95-99) on clean machine-printed form
#: text, so 80 keeps those unflagged while surfacing genuinely marginal OCR reads
#: (sub-80) for human review.
DEFAULT_MIN_CONFIDENCE = 80.0

#: How long a job item (and its cached draft) lives before DynamoDB TTL reaps it.
#: 24 hours is ample for an interactive upload → review → confirm session while
#: keeping extracted PII short-lived (design "Extraction_Job" item shape).
_JOB_TTL_SECONDS = 24 * 60 * 60

# Job status / outcome literals (kept as plain strings on the stored item).
_STATUS_PENDING = "pending"
_STATUS_PROCESSING = "processing"
_STATUS_COMPLETE = "complete"
_STATUS_FAILED = "failed"
_OUTCOME_DRAFT = "draft"
_OUTCOME_NO_SCHEDULE_E = "no_schedule_e_found"

# Textract async JobStatus values.
_TX_IN_PROGRESS = "IN_PROGRESS"
_TX_SUCCEEDED = "SUCCEEDED"
_TX_FAILED = "FAILED"
_TX_PARTIAL = "PARTIAL_SUCCESS"

_NO_SCHEDULE_E_MESSAGE = "No Schedule E was located in the uploaded document."
_INVALID_PDF_MESSAGE = "The document could not be read; a valid PDF is required."

#: The most pages an extraction upload may have. Schedule E itself is 1-2
#: pages; Textract bills per page per feature, so a whole ~50-page return costs
#: ~25x more than the pages the parser actually reads. The guard runs before
#: Textract is called, so a rejected upload costs nothing.
MAX_UPLOAD_PAGES = 5

_TOO_MANY_PAGES_MESSAGE = (
    "This PDF has {pages} pages. Upload only your Schedule E pages "
    "(usually 1-2), not the whole tax return."
)
_TOO_LARGE_MESSAGE = "The uploaded file is too large."
_TEXTRACT_FAILED_MESSAGE = "The document could not be processed."


def _now() -> datetime:
    """Current UTC time (seam kept tiny so the TTL math is testable)."""
    return datetime.now(timezone.utc)


class ExtractionService:
    """Schedule E PDF extraction, scoped to one authenticated user.

    Args:
        repo: The single-table DynamoDB repository (job persistence only).
        user: The authenticated :class:`UserContext` or a raw user id string.
            Every operation is scoped to this user.
        files: The S3 file adapter (presigned PUT, PDF-signature read, delete).
        textract: The Textract adapter (async start/get).

    The service constructs a user-scoped :class:`PropertyService` internally as
    the fuzzy-match source for suggested property mappings (Req 7.5); it is never
    used to write.
    """

    def __init__(
        self,
        repo: DynamoRepository,
        user: UserContext | str,
        files: S3FileAdapter,
        textract: TextractAdapter,
    ) -> None:
        self._repo = repo
        self._user_id = (
            user_id_of(user) if isinstance(user, UserContext) else user
        )
        self._files = files
        self._textract = textract
        # User-scoped, read-only here: only ``list()`` is called, as the fuzzy
        # match source. The service performs no domain writes of any kind.
        self._properties = PropertyService(repo, self._user_id)

    # --- Req 1: start_extraction --------------------------------------------

    def start_extraction(
        self, filename: str, content_type: str
    ) -> Result[StartExtractionOutcome]:
        """Issue a presigned PUT and create the job ``pending`` (Req 1).

        Validates that ``content_type`` is exactly ``application/pdf``; a non-PDF
        type returns a ``validation`` failure identifying ``file`` with **no**
        job created and **no** URL issued (Req 1.4). On success a job id is
        minted, the key ``imports/schedule-e/<userId>/<jobId>.pdf`` is built, a
        presigned PUT bound to ``application/pdf`` is issued, and the job is
        persisted ``pending`` with a TTL (Req 1.1-1.3, 2.3).

        Args:
            filename: The client-supplied filename (informational; the stored
                key is derived from the job id, not the filename).
            content_type: The declared MIME type of the upload.

        Returns:
            ``Result`` carrying a :class:`StartExtractionOutcome`
            (``job_id`` + ``upload_url``) on success, or a ``validation`` failure.
        """
        if (content_type or "").strip().lower() != PDF_CONTENT_TYPE:
            return Result.failure(
                "validation",
                f"A PDF upload is required (expected {PDF_CONTENT_TYPE}).",
                field="file",
            )

        job_id = str(uuid.uuid4())
        key = build_key(
            IMPORT_PREFIX,
            _SCHEDULE_E_IMPORT_SEGMENT,
            self._user_id,
            f"{job_id}.pdf",
        )
        upload_url = self._files.presigned_put_url(key, PDF_CONTENT_TYPE)

        self._put_job(
            {
                "id": job_id,
                "status": _STATUS_PENDING,
                "outcome": None,
                "uploadedKey": key,
                "textractJobId": None,
                "message": None,
                "reviewDraftJson": None,
                "createdAt": _now().isoformat(),
                "ttl": self._ttl_epoch(),
            }
        )
        return Result.success(
            StartExtractionOutcome(job_id=job_id, upload_url=upload_url)
        )

    # --- Req 2: begin_extraction --------------------------------------------

    def begin_extraction(self, job_id: str) -> Result[ExtractionJobView]:
        """Confirm the upload is a PDF, start Textract, mark ``processing`` (Req 2).

        Loads the job scoped to the user (``not_found`` when missing or owned by
        another user — Req 11.2). Confirms the uploaded object exists and carries
        the ``%PDF-`` signature:

        * absent object → ``not_found`` and Textract is **never** called (Req 2.4);
        * present but not a PDF → the job is marked ``failed`` with "a valid PDF
          is required" and the object is deleted (Req 1.5, 12.1).

        On success it starts ``StartDocumentAnalysis``, stores the Textract job
        id, marks the job ``processing``, and returns the view (Req 2.1, 2.2).
        """
        job = self._load_job(job_id)
        if job is None:
            return Result.failure("not_found", "Extraction job not found.")

        key = str(job["uploadedKey"])
        # A presigned PUT cannot cap size, so check it on the confirm step and
        # delete an oversized object before anything reads it.
        if self._files.purge_if_oversized(key, MAX_IMPORT_PDF_BYTES):
            self._mark_failed(job, _TOO_LARGE_MESSAGE)
            return Result.success(self._view(job))
        head = self._read_pdf_head(key)
        if head is None:
            # The browser never completed the upload (or it is gone): the object
            # is not in the user's scope. Textract is never called.
            return Result.failure("not_found", "Uploaded document not found.")

        if not head.startswith(_PDF_SIGNATURE):
            # Present but not a readable PDF: terminal failure + delete the PDF.
            self._mark_failed(job, _INVALID_PDF_MESSAGE)
            return Result.success(self._view(job))

        # Cost guard: Textract bills per page, and the parser only reads the one
        # or two Schedule E pages. Reject an oversized upload (a whole return)
        # before Textract is called. Fails open when the page count cannot be
        # determined, so an upload that works today is never blocked by this.
        pages = self._count_pdf_pages(key)
        if pages is not None and pages > MAX_UPLOAD_PAGES:
            self._mark_failed(job, _TOO_MANY_PAGES_MESSAGE.format(pages=pages))
            return Result.success(self._view(job))

        textract_job_id = self._textract.start_document_analysis(
            self._files.bucket, key
        )
        job["textractJobId"] = textract_job_id
        job["status"] = _STATUS_PROCESSING
        self._put_job(job)
        return Result.success(self._view(job))

    # --- Req 3: get_status (poll, parse-once, cache) ------------------------

    def get_status(self, job_id: str) -> Result[ExtractionJobView]:
        """Poll a job; parse+cache once on the first ``SUCCEEDED`` (Req 3).

        Loads the job scoped to the user (``not_found`` otherwise — Req 3.6,
        11.2). When the job is already terminal (``complete``/``failed``) the
        cached result is returned immediately, **without** re-calling Textract or
        re-parsing (design caching note). While ``processing`` it calls
        ``GetDocumentAnalysis``:

        * ``IN_PROGRESS`` → still ``processing``;
        * ``FAILED`` / ``PARTIAL_SUCCESS`` with no usable blocks → ``failed`` +
          message, delete the PDF (Req 3.5, 12.3);
        * ``SUCCEEDED`` → parse the aggregated blocks once; build + cache a
          :class:`ReviewDraft` (``complete`` / ``draft``), or record
          ``no_schedule_e_found`` with no draft; either way delete the PDF
          (Req 3.3, 3.4, 12.2).
        """
        job = self._load_job(job_id)
        if job is None:
            return Result.failure("not_found", "Extraction job not found.")

        status = str(job.get("status"))
        if status in (_STATUS_COMPLETE, _STATUS_FAILED):
            # Terminal: return the cached result, never touch Textract again.
            return Result.success(self._view(job))

        if status != _STATUS_PROCESSING:
            # pending (upload not yet begun) — nothing to poll yet.
            return Result.success(self._view(job))

        textract_job_id = job.get("textractJobId")
        if not textract_job_id:
            return Result.success(self._view(job))

        result = self._textract.get_document_analysis(str(textract_job_id))
        tx_status = result.status

        if tx_status == _TX_IN_PROGRESS:
            return Result.success(self._view(job))

        # FAILED always terminates; PARTIAL_SUCCESS terminates only when it
        # carried no usable blocks (otherwise it is parsed like SUCCEEDED).
        if tx_status == _TX_FAILED or (tx_status == _TX_PARTIAL and not result.blocks):
            message = result.status_message or _TEXTRACT_FAILED_MESSAGE
            self._mark_failed(job, message)
            return Result.success(self._view(job))

        # SUCCEEDED (or PARTIAL_SUCCESS carrying usable blocks): parse once.
        parsed = parse_schedule_e(
            result.blocks, min_confidence=DEFAULT_MIN_CONFIDENCE
        )
        if parsed.no_schedule_e_found:
            self._mark_no_schedule_e(job)
            return Result.success(self._view(job))

        draft = self._build_review_draft(parsed)
        self._mark_complete_with_draft(job, draft)
        return Result.success(self._view(job))

    # --- Review draft assembly ----------------------------------------------

    def _build_review_draft(self, parsed: ParsedExtraction) -> ReviewDraft:
        """Map a :class:`ParsedExtraction` to a service-layer :class:`ReviewDraft`.

        Normalizes each raw amount token through ``util/money`` to a two-decimal
        money string (Req 5.1): a readable token becomes ``money_to_str(to_money(
        token))``; an unreadable/blank token becomes ``"0.00"`` with
        ``needs_verification=True`` and the column is kept, never dropped
        (Req 5.2, 4.6). The column address is fuzzy-matched against the user's
        own properties (``PropertyService.list()`` → ``best_match``) to attach a
        suggestion that is **never** auto-applied (Req 7.1-7.3, 7.5).
        """
        candidates = self._properties.list()

        columns: list[ExtractedColumn] = []
        for pcol in parsed.columns:
            lines: list[ExtractedLine] = []
            for pline in pcol.lines:
                amount, unreadable = self._normalize_amount(pline.raw_amount)
                lines.append(
                    ExtractedLine(
                        schedule_e_line=pline.schedule_e_line,
                        amount=amount,
                        needs_verification=pline.needs_verification or unreadable,
                        confidence=pline.confidence,
                    )
                )

            suggested_id: str | None = None
            suggested_name: str | None = None
            mapping_confidence: float | None = None
            if pcol.address_text:
                match = best_match(pcol.address_text, candidates)
                if match is not None:
                    suggested_id = match.property_id
                    suggested_name = match.property_name
                    mapping_confidence = match.confidence

            columns.append(
                ExtractedColumn(
                    address_text=pcol.address_text,
                    address_confidence=pcol.address_confidence,
                    suggested_property_id=suggested_id,
                    suggested_property_name=suggested_name,
                    mapping_confidence=mapping_confidence,
                    lines=lines,
                )
            )

        return ReviewDraft(
            tax_year=parsed.tax_year,
            tax_year_needs_verification=parsed.tax_year_needs_verification,
            columns=columns,
        )

    @staticmethod
    def _normalize_amount(raw_amount: str) -> tuple[str, bool]:
        """Normalize a raw OCR token to a two-decimal money string (Req 5.1/5.2).

        Returns ``(amount_string, unreadable)``. A token that ``to_money`` can
        parse yields its two-decimal rendering and ``unreadable=False``; a blank
        or un-normalizable token (e.g. ``""``, ``"n/a"``, a stray glyph) yields
        ``"0.00"`` and ``unreadable=True`` so the caller flags it for
        verification while keeping the column (Req 4.6, 5.2). Parenthesized and
        ``$``/comma-formatted tokens are reduced to a plain decimal first.
        """
        token = (raw_amount or "").strip()
        if not token:
            return "0.00", True
        cleaned = _clean_money_token(token)
        try:
            return money_to_str(to_money(cleaned)), False
        except (ValueError, TypeError):
            return "0.00", True

    # --- Terminal transitions (each deletes the PDF — Req 10) ---------------

    def _mark_complete_with_draft(
        self, job: dict[str, Any], draft: ReviewDraft
    ) -> None:
        """Transition the job to ``complete`` / ``draft`` and delete the PDF."""
        job["status"] = _STATUS_COMPLETE
        job["outcome"] = _OUTCOME_DRAFT
        job["message"] = None
        job["reviewDraftJson"] = _serialize_review_draft(draft)
        self._put_job(job)
        self._delete_upload(job)

    def _mark_no_schedule_e(self, job: dict[str, Any]) -> None:
        """Transition the job to ``complete`` / ``no_schedule_e_found`` (no draft)."""
        job["status"] = _STATUS_COMPLETE
        job["outcome"] = _OUTCOME_NO_SCHEDULE_E
        job["message"] = _NO_SCHEDULE_E_MESSAGE
        job["reviewDraftJson"] = None
        self._put_job(job)
        self._delete_upload(job)

    def _mark_failed(self, job: dict[str, Any], message: str) -> None:
        """Transition the job to ``failed`` with a message and delete the PDF."""
        job["status"] = _STATUS_FAILED
        job["outcome"] = None
        job["message"] = message
        job["reviewDraftJson"] = None
        self._put_job(job)
        self._delete_upload(job)

    def _delete_upload(self, job: dict[str, Any]) -> None:
        """Delete the uploaded PDF (idempotent) — the primary PII deletion (Req 10).

        Called on every terminal transition. ``uploadedKey`` is kept on the job
        only to target this delete; after deletion the key names an absent
        object, which is harmless because S3 delete is idempotent. Extraction
        creates/modifies/deletes **no** transaction or Property (Req 12.5).
        """
        key = job.get("uploadedKey")
        if key:
            self._files.delete_object(str(key))

    # --- Job persistence (Req 6.1: serialize / deserialize) -----------------

    def _put_job(self, job: dict[str, Any]) -> None:
        """Persist a job item at ``USER#<userId> / SEEXTRACT#<jobId>``.

        ``userId``, ``PK``, and ``SK`` are derived here so callers only manage
        the domain fields. ``None``-valued optional attributes are dropped by the
        repository's sparse write, so an unset ``outcome`` / ``textractJobId`` /
        ``message`` / ``reviewDraftJson`` simply does not appear on the item.
        """
        job_id = str(job["id"])
        item = {
            "PK": keys.user_pk(self._user_id),
            "SK": keys.extraction_job_sk(job_id),
            "userId": self._user_id,
            **job,
        }
        self._repo.put_item(item)

    def _load_job(self, job_id: str) -> dict[str, Any] | None:
        """Load a job scoped to the user, or ``None`` when absent / not owned.

        The item is keyed under the user's own ``USER#<userId>`` partition, so a
        ``job_id`` created by another user simply does not resolve here —
        ownership is a partition-level fact (Req 11.1, 11.2). The stored
        ``userId`` is re-checked as a defense-in-depth guard.
        """
        item = self._repo.get_item(
            keys.user_pk(self._user_id), keys.extraction_job_sk(job_id)
        )
        if item is None:
            return None
        if str(item.get("userId")) != self._user_id:
            return None
        return item

    def _read_pdf_head(self, key: str, *, length: int = 8) -> bytes | None:
        """Read the leading bytes of the uploaded object, or ``None`` if absent.

        Uses a ranged ``get_object`` so only a few bytes are fetched (enough to
        test the ``%PDF-`` signature). A missing object (the upload never landed,
        or it was already deleted) returns ``None`` so the caller maps it to
        ``not_found`` without ever calling Textract (Req 2.4). Any S3 client
        error is treated as "absent" for the same reason.
        """
        s3 = self._files._s3  # the adapter owns the client; reuse it here.
        try:
            response = s3.get_object(
                Bucket=self._files.bucket,
                Key=key,
                Range=f"bytes=0-{length - 1}",
            )
        except Exception:
            return None
        body = response.get("Body")
        if body is None:
            return b""
        return body.read()

    def _count_pdf_pages(self, key: str) -> int | None:
        """Return the uploaded PDF's page count, or ``None`` if it can't be read.

        Reads the object and counts pages with ``pypdf`` (imported lazily so
        unrelated requests keep their cold start). Any failure -- S3 error,
        encrypted or malformed PDF, ``pypdf`` unavailable -- returns ``None`` so
        the caller proceeds exactly as before this guard existed.
        """
        try:
            from pypdf import PdfReader

            s3 = self._files._s3
            response = s3.get_object(Bucket=self._files.bucket, Key=key)
            data = response["Body"].read()
            return len(PdfReader(io.BytesIO(data)).pages)
        except Exception:
            return None

    # --- View / TTL helpers --------------------------------------------------

    def _view(self, job: dict[str, Any]) -> ExtractionJobView:
        """Build the SPA-facing :class:`ExtractionJobView` from a job item.

        A cached ``reviewDraftJson`` is deserialized back into a
        :class:`ReviewDraft` only when the job completed with a ``draft``
        outcome; ``failed`` / ``no_schedule_e_found`` carry a ``message`` and no
        draft.
        """
        status = str(job.get("status"))
        outcome = job.get("outcome")
        message = job.get("message")
        draft = None
        raw_draft = job.get("reviewDraftJson")
        if outcome == _OUTCOME_DRAFT and raw_draft:
            draft = _deserialize_review_draft(str(raw_draft))
        return ExtractionJobView(
            job_id=str(job["id"]),
            status=status,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            message=str(message) if message is not None else None,
            review_draft=draft,
        )

    @staticmethod
    def _ttl_epoch() -> int:
        """Epoch-seconds TTL ~24h out, for DynamoDB to reap the job + draft."""
        return int((_now() + timedelta(seconds=_JOB_TTL_SECONDS)).timestamp())


# --- Money token cleaning ----------------------------------------------------


def _clean_money_token(token: str) -> str:
    """Reduce an OCR money token to a form ``to_money`` accepts.

    Strips the currency symbol and thousands commas, and converts a
    parenthesized amount ``(123.45)`` to a negative ``-123.45`` (the accountancy
    negative convention Textract preserves from the form). The result is handed
    to :func:`to_money`, which raises on anything still non-numeric so the
    caller can flag it.
    """
    text = token.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = text.replace("$", "").replace(",", "").strip()
    if negative and text and not text.startswith("-"):
        text = f"-{text}"
    return text


# --- ReviewDraft (de)serialization (two-decimal money strings) ---------------


def _serialize_review_draft(draft: ReviewDraft) -> str:
    """Serialize a :class:`ReviewDraft` to the ``reviewDraftJson`` string.

    Line amounts are already two-decimal money strings (produced by
    :meth:`ExtractionService._normalize_amount`), so they serialize verbatim and
    round-trip with no drift. The JSON shape mirrors the dataclass field names.
    """
    return json.dumps(
        {
            "tax_year": draft.tax_year,
            "tax_year_needs_verification": draft.tax_year_needs_verification,
            "columns": [
                {
                    "address_text": col.address_text,
                    "address_confidence": col.address_confidence,
                    "suggested_property_id": col.suggested_property_id,
                    "suggested_property_name": col.suggested_property_name,
                    "mapping_confidence": col.mapping_confidence,
                    "lines": [
                        {
                            "schedule_e_line": line.schedule_e_line,
                            "amount": line.amount,
                            "needs_verification": line.needs_verification,
                            "confidence": line.confidence,
                        }
                        for line in col.lines
                    ],
                }
                for col in draft.columns
            ],
        }
    )


def _deserialize_review_draft(raw: str) -> ReviewDraft:
    """Inverse of :func:`_serialize_review_draft`.

    Rebuilds the :class:`ReviewDraft` dataclass tree from the cached JSON string,
    with amounts restored as the exact two-decimal strings they were stored as.
    """
    data = json.loads(raw)
    columns = [
        ExtractedColumn(
            address_text=col.get("address_text"),
            address_confidence=col.get("address_confidence"),
            suggested_property_id=col.get("suggested_property_id"),
            suggested_property_name=col.get("suggested_property_name"),
            mapping_confidence=col.get("mapping_confidence"),
            lines=[
                ExtractedLine(
                    schedule_e_line=int(line["schedule_e_line"]),
                    amount=str(line["amount"]),
                    needs_verification=bool(line["needs_verification"]),
                    confidence=line.get("confidence"),
                )
                for line in col.get("lines", [])
            ],
        )
        for col in data.get("columns", [])
    ]
    return ReviewDraft(
        tax_year=data.get("tax_year"),
        tax_year_needs_verification=bool(data.get("tax_year_needs_verification")),
        columns=columns,
    )
