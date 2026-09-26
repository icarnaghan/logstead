"""Expense Import Service: PDF-to-draft lifecycle (Requirement 6).

This service turns an uploaded property-manager expense-summary PDF into a set
of **draft** transactions that the user reviews, edits, and finally confirms
into real ``Transaction`` items. The single hard invariant that shapes the whole
design:

    **No ``Transaction`` is ever created before the user confirms** (Requirement
    6.6). Everything produced during parsing and review is a ``DraftTransaction``
    staging item that lives under the import session partition and never surfaces
    in Schedule E aggregation until :meth:`confirm` converts it.

Lifecycle
---------
* :meth:`create_session` (a.k.a. :meth:`start_import`) — associate the import
  with a property + tax year (Requirement 6.1), reject non-PDF uploads with a
  "PDF required" message (Requirement 6.2), parse the PDF into line items
  (Requirement 6.3), map each to a Schedule E expense category via keyword
  heuristics (Requirement 6.4), and persist an ``ImportSession`` plus one
  ``DraftTransaction`` per line item. Each draft is flagged with **exactly** the
  required fields it is missing (Requirement 6.9). On parse failure the session
  is stored with ``status="failed"`` and a clear message, and **no drafts** are
  written (Requirement 6.12). No ``Transaction`` is created (Requirement 6.6).
* :meth:`get_session` / :meth:`list_drafts` (a.k.a. :meth:`get_drafts`) — read
  the session and its drafts for review (Requirement 6.5).
* :meth:`update_draft` — edit a draft's date/amount/description/type/category and
  **recompute** the missing-fields flag (Requirements 6.7, 6.9).
* :meth:`remove_draft` — drop a draft before confirming (Requirement 6.8).
* :meth:`confirm` — partition the remaining drafts into **complete** vs
  **incomplete**. Only complete drafts are converted into real ``Transaction``
  items in the session's selected tax year (Requirements 6.10, 6.11); incomplete
  drafts are left as drafts (never converted, never silently dropped). When every
  complete draft converts, the session is marked ``confirmed``.

The transaction-creator seam
-----------------------------
Confirmation needs the Transaction Service (task 10.1), which is being written
concurrently and may not yet be importable. To keep this service testable and
decoupled we accept an injectable ``transaction_creator``: a callable
``(TransactionInput) -> Result[Transaction-like]``. When one is not supplied,
:meth:`confirm` imports ``logstead.services.transaction.TransactionService``
lazily and adapts its ``create`` method. Tests pass a stub creator so they never
hard-depend on 10.1's exact surface.

Keys and item shapes follow the design's single-table conventions
(design.md "ImportSession"/"DraftTransaction"); keys are built exclusively
through :mod:`logstead.repository.keys`. Money is ``decimal.Decimal`` in code and
a two-decimal string in DynamoDB (Requirement 13.3), handled by the repository.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Callable

from logstead.models.category import ScheduleECategory
from logstead.models.imports import DraftTransaction, ImportSession
from logstead.models.result import Result
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
from logstead.services.category import CATEGORY_CATALOG

if TYPE_CHECKING:
    from logstead.adapters.pdf_parse import ParsedLineItem
    from logstead.repository.dynamo_repo import DynamoRepository

__all__ = [
    "ExpenseImportService",
    "ConfirmOutcome",
    "RejectedDraft",
    "TransactionCreator",
    "ParseFn",
]


# A transaction creator turns a validated draft into a real transaction. It is
# injectable so confirmation does not hard-depend on the Transaction Service
# (task 10.1). The return value is a ``Result`` whose success value is a
# transaction-like object exposing an ``id`` attribute.
TransactionCreator = Callable[[TransactionInput], "Result"]

# A parser turns raw PDF bytes into a Result of parsed line items. Injectable so
# tests can drive the lifecycle without the PDF stack. Defaults to
# ``parse_expense_summary`` from the pdf_parse adapter.
ParseFn = Callable[[bytes], "Result[list[ParsedLineItem]]"]


# --- Confirmation outcome ----------------------------------------------------


@dataclass
class RejectedDraft:
    """A draft that could not be converted into a Transaction on confirm.

    Attributes:
        draft_id: The rejected draft's id.
        message: A human-readable reason (identifies the failing/missing field).
        field: The offending field name, when the rejection is field-specific
            (Requirement 6.11).
    """

    draft_id: str
    message: str
    field: str | None = None


@dataclass
class ConfirmOutcome:
    """The result of confirming an import session (Requirements 6.10, 6.11).

    Attributes:
        created_ids: Ids of the ``Transaction`` items created from complete
            drafts (Requirement 6.10).
        rejected: Drafts that were left as drafts because they were incomplete
            or failed Transaction validation (Requirement 6.11). None are
            silently dropped.
        session: The (possibly updated) import session; ``confirmed`` once every
            complete draft has been converted.
    """

    created_ids: list[str] = field(default_factory=list)
    rejected: list[RejectedDraft] = field(default_factory=list)
    session: ImportSession | None = None

    @property
    def converted_count(self) -> int:
        return len(self.created_ids)

    @property
    def remaining_incomplete(self) -> int:
        return len(self.rejected)


# --- Category keyword heuristics (Requirement 6.4) ---------------------------
#
# Property-manager summaries describe each line item in free text. We map a
# draft to a Schedule E *expense* category by scanning its description for
# characteristic keywords. This is a best-effort hint only: an unmatched draft
# simply has no category (and is flagged as missing "category" per 6.9), and the
# user can correct any mapping during review (6.7). Income categories are never
# auto-assigned — an expense summary lists expenses.

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "advertising": ("advertis", "listing fee", "marketing"),
    "auto-and-travel": ("mileage", "travel", "auto", "fuel", "gas "),
    "cleaning-and-maintenance": (
        "clean", "maintenance", "landscap", "lawn", "yard", "snow", "pest",
    ),
    "commissions": ("commission", "leasing fee", "lease-up"),
    "insurance": ("insurance", "premium"),
    "legal-and-professional-fees": (
        "legal", "attorney", "accountant", "accounting", "cpa", "professional",
    ),
    "management-fees": ("management fee", "mgmt fee", "property management"),
    "mortgage-interest-banks": ("mortgage interest", "mortgage"),
    "other-interest": ("interest",),
    "repairs": ("repair", "plumb", "electric", "hvac", "roof repair", "fix"),
    "supplies": ("supplies", "supply", "materials"),
    "taxes": ("property tax", "tax", "taxes"),
    "utilities": ("utilit", "water", "sewer", "electric bill", "trash", "gas bill"),
}

# Index the catalog by id for quick lookups (label, requires_description).
_CATALOG_BY_ID: dict[str, ScheduleECategory] = {c.id: c for c in CATEGORY_CATALOG}


def _guess_category_id(description: str | None) -> str | None:
    """Best-effort keyword mapping of a description to an expense category id.

    Returns ``None`` when nothing matches; the draft is then flagged as missing
    a category (Requirement 6.9) and the user assigns one during review.
    """
    if not description:
        return None
    text = description.lower()
    for category_id, needles in _CATEGORY_KEYWORDS.items():
        for needle in needles:
            if needle in text:
                return category_id
    return None


# --- Helpers -----------------------------------------------------------------


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (created-at stamp)."""
    return datetime.now(timezone.utc).isoformat()


def _blank(value: str | None) -> bool:
    """True when a text field is missing or whitespace-only."""
    return value is None or str(value).strip() == ""


def _looks_like_pdf(content_type: str | None, pdf_bytes: bytes | None) -> bool:
    """True if the upload is a PDF by declared content type or magic bytes.

    A PDF is accepted when the declared ``content_type`` is ``application/pdf``
    or when the bytes begin with the ``%PDF-`` signature. Either signal is
    sufficient; a mismatch on both means "not a PDF" and is rejected with the
    "PDF required" message (Requirement 6.2).
    """
    if content_type is not None and content_type.strip().lower() == "application/pdf":
        return True
    if pdf_bytes is not None and bytes(pdf_bytes[:5]) == b"%PDF-":
        return True
    return False


class ExpenseImportService:
    """PDF import session + draft lifecycle, scoped to one property/tax year.

    Args:
        repo: The single-table DynamoDB repository (staging store for the
            session and its drafts).
        parser: Injectable ``bytes -> Result[list[ParsedLineItem]]`` parser;
            defaults to :func:`logstead.adapters.pdf_parse.parse_expense_summary`.
        transaction_creator: Injectable ``(TransactionInput) -> Result`` used by
            :meth:`confirm` to create real transactions from complete drafts.
            When ``None``, :meth:`confirm` lazily builds one from the Transaction
            Service (task 10.1). Tests inject a stub so they need not depend on
            10.1's exact API.
    """

    def __init__(
        self,
        repo: "DynamoRepository",
        *,
        parser: ParseFn | None = None,
        transaction_creator: TransactionCreator | None = None,
    ) -> None:
        self._repo = repo
        self._parser = parser
        self._transaction_creator = transaction_creator

    # --- Missing-field computation (Requirement 6.9) ------------------------

    @staticmethod
    def _missing_fields(draft: DraftTransaction) -> list[str]:
        """Return exactly the required fields that are unset on a draft (6.9).

        The always-required fields are ``date``, ``amount``, and ``category``
        (Requirement 6.9). ``description`` is required **only** when the assigned
        category requires it (the Other/Line 19 category; Requirement 7.4) — so
        an Other draft with no description also flags ``description``. The list
        is returned in a stable order so callers/tests can compare it directly.
        """
        missing: list[str] = []
        if _blank(draft.date):
            missing.append("date")
        if draft.amount is None:
            missing.append("amount")
        if _blank(draft.category_id):
            missing.append("category")
        else:
            category = _CATALOG_BY_ID.get(str(draft.category_id))
            if (
                category is not None
                and category.requires_description
                and _blank(draft.description)
            ):
                missing.append("description")
        return missing

    # --- Serialization boundary ---------------------------------------------

    @staticmethod
    def _session_item(session: ImportSession) -> dict[str, object]:
        """Render an ImportSession as its ``IMPORT#<id> / META`` row."""
        gsi1_pk, gsi1_sk = keys.gsi1_import_keys(session.property_id, session.id)
        return {
            "PK": keys.import_pk(session.id),
            "SK": keys.import_meta_sk(),
            "id": session.id,
            "propertyId": session.property_id,
            "taxYear": session.tax_year,
            "pdfS3Key": session.pdf_s3_key,
            "status": session.status,
            "createdAt": session.created_at,
            "GSI1PK": gsi1_pk,
            "GSI1SK": gsi1_sk,
        }

    @staticmethod
    def _session_from_item(item: dict[str, object]) -> ImportSession:
        """Reconstruct an ImportSession from its stored META row."""
        return ImportSession(
            id=str(item["id"]),
            property_id=str(item["propertyId"]),
            tax_year=int(item["taxYear"]),  # type: ignore[arg-type]
            pdf_s3_key=str(item["pdfS3Key"]),
            status=str(item["status"]),  # type: ignore[arg-type]
            created_at=(
                str(item["createdAt"]) if item.get("createdAt") is not None else None
            ),
        )

    @staticmethod
    def _draft_item(draft: DraftTransaction) -> dict[str, object]:
        """Render a DraftTransaction as its ``IMPORT#<id> / DRAFT#<draftId>`` row.

        Absent optional fields are ``None`` so the repository omits them (sparse
        write). ``missingFields`` is always stored (possibly an empty list) so a
        read reconstructs the flag without recomputation.
        """
        return {
            "PK": keys.import_pk(draft.import_session_id),
            "SK": keys.draft_sk(draft.id),
            "id": draft.id,
            "importSessionId": draft.import_session_id,
            "date": draft.date,
            "amount": draft.amount,
            "description": draft.description,
            "type": draft.type,
            "categoryId": draft.category_id,
            "missingFields": list(draft.missing_fields),
        }

    @staticmethod
    def _draft_from_item(item: dict[str, object]) -> DraftTransaction:
        """Reconstruct a DraftTransaction from its stored DRAFT# row."""
        amount = item.get("amount")
        return DraftTransaction(
            id=str(item["id"]),
            import_session_id=str(item["importSessionId"]),
            date=(str(item["date"]) if item.get("date") is not None else None),
            amount=(amount if isinstance(amount, Decimal) else None),
            description=(
                str(item["description"])
                if item.get("description") is not None
                else None
            ),
            type=(str(item["type"]) if item.get("type") is not None else None),
            category_id=(
                str(item["categoryId"])
                if item.get("categoryId") is not None
                else None
            ),
            missing_fields=[str(f) for f in item.get("missingFields", []) or []],
        )

    def _persist_draft(self, draft: DraftTransaction) -> None:
        """Recompute the missing-fields flag and write the draft."""
        draft.missing_fields = self._missing_fields(draft)
        self._repo.put_item(self._draft_item(draft))

    # --- Create session (Requirements 6.1, 6.2, 6.3, 6.4, 6.9, 6.12) --------

    def create_session(
        self,
        property_id: str,
        tax_year: int,
        *,
        pdf_bytes: bytes | None = None,
        pdf_s3_key: str | None = None,
        content_type: str | None = None,
    ) -> Result[ImportSession]:
        """Create an import session and stage draft transactions (Requirement 6).

        The import is associated with ``property_id`` and ``tax_year``
        (Requirement 6.1). A non-PDF upload is rejected up front with a "PDF
        required" message (Requirement 6.2). The PDF is parsed into line items
        (Requirement 6.3); each becomes a ``DraftTransaction`` with a best-effort
        category (Requirement 6.4) and a missing-fields flag (Requirement 6.9).
        The session and its drafts are persisted as staging items — **no
        ``Transaction`` is created** (Requirement 6.6).

        On parse failure (unreadable, oversized, too slow, or zero line items),
        the session is stored with ``status="failed"`` and a clear message, and
        **no drafts** are written (Requirement 6.12); the caller surfaces the
        message so the user can enter transactions manually.

        Args:
            property_id: The property the import is associated with.
            tax_year: The tax year selected for the import.
            pdf_bytes: The uploaded PDF bytes (required for parsing when no
                custom parser is injected).
            pdf_s3_key: S3 key of the uploaded PDF, recorded on the session.
            content_type: The declared upload content type; used with the byte
                signature to enforce the PDF-required check (Requirement 6.2).

        Returns:
            * ``Result.success(ImportSession)`` in ``review`` status when parsing
              produced at least one draft.
            * ``Result.failure("validation", ...)`` for a non-PDF upload.
            * ``Result.failure("unavailable", ...)`` when parsing fails; the
              failed session is still persisted for auditability.
        """
        if pdf_bytes is None and pdf_s3_key is None:
            return Result.failure(
                "validation",
                "A PDF file is required.",
                field="file",
            )

        # Requirement 6.2: reject anything that is not a PDF.
        if not _looks_like_pdf(content_type, pdf_bytes):
            return Result.failure(
                "validation",
                "A PDF file is required.",
                field="file",
            )

        session = ImportSession(
            id=str(uuid.uuid4()),
            property_id=property_id,
            tax_year=tax_year,
            pdf_s3_key=pdf_s3_key or "",
            status="parsing",
            created_at=_now_iso(),
        )

        parse_result = self._parse(pdf_bytes)
        if not parse_result.is_ok:
            # Requirement 6.12: persist a failed session, write no drafts, and
            # surface the parser's message. No Transaction is created.
            session.status = "failed"
            self._repo.put_item(self._session_item(session))
            error = parse_result.error
            return Result.failure(
                "unavailable",
                error.message if error is not None else
                "No transactions could be extracted from the document.",
            )

        line_items = parse_result.value

        # Persist the session (now in review) and one draft per line item.
        session.status = "review"
        self._repo.put_item(self._session_item(session))

        for item in line_items:
            draft = DraftTransaction(
                id=str(uuid.uuid4()),
                import_session_id=session.id,
                date=item.date,
                amount=item.amount,
                description=item.description,
                type="expense",  # expense summaries list expenses (Req 6.4).
                category_id=_guess_category_id(item.description),
            )
            self._persist_draft(draft)

        return Result.success(session)

    def start_import(
        self,
        file_key: str,
        property_id: str,
        tax_year: int,
        content_type: str,
        *,
        pdf_bytes: bytes | None = None,
    ) -> Result[ImportSession]:
        """Design-named alias for :meth:`create_session` (design ``start_import``).

        Matches the design's ``start_import(file_key, prop_id, tax_year,
        content_type)`` signature. The PDF bytes are optional here because in the
        deployed flow the object is already in S3 at ``file_key`` and the parser
        fetches it; tests inject bytes and/or a stub parser instead.
        """
        return self.create_session(
            property_id,
            tax_year,
            pdf_bytes=pdf_bytes,
            pdf_s3_key=file_key,
            content_type=content_type,
        )

    def _parse(self, pdf_bytes: bytes | None) -> "Result[list[ParsedLineItem]]":
        """Run the configured parser (default: the pdf_parse adapter)."""
        if self._parser is not None:
            return self._parser(pdf_bytes or b"")
        # Lazy import so the PDF stack is only pulled in when actually parsing.
        from logstead.adapters.pdf_parse import parse_expense_summary

        return parse_expense_summary(pdf_bytes or b"")

    # --- Read (Requirement 6.5) ---------------------------------------------

    def get_session(self, session_id: str) -> Result[ImportSession]:
        """Fetch an import session, or ``not_found`` (Requirement 6.5)."""
        item = self._repo.get_item(
            keys.import_pk(session_id), keys.import_meta_sk()
        )
        if item is None:
            return Result.failure("not_found", "Import session not found.")
        return Result.success(self._session_from_item(item))

    def list_drafts(self, session_id: str) -> list[DraftTransaction]:
        """List the drafts staged for an import session (Requirement 6.5)."""
        items = self._repo.query(
            keys.import_pk(session_id),
            sk_begins_with=keys.draft_list_prefix(),
        )
        return [self._draft_from_item(item) for item in items]

    # Design-named alias.
    def get_drafts(self, session_id: str) -> list[DraftTransaction]:
        """Alias for :meth:`list_drafts` (design ``get_drafts``)."""
        return self.list_drafts(session_id)

    def _get_draft(
        self, session_id: str, draft_id: str
    ) -> DraftTransaction | None:
        item = self._repo.get_item(
            keys.import_pk(session_id), keys.draft_sk(draft_id)
        )
        if item is None:
            return None
        return self._draft_from_item(item)

    # --- Update / remove (Requirements 6.7, 6.8, 6.9) -----------------------

    def update_draft(
        self, session_id: str, draft_id: str, fields: dict[str, object]
    ) -> Result[DraftTransaction]:
        """Edit a draft and recompute its missing-fields flag (6.7, 6.9).

        Editable fields: ``date``, ``amount``, ``description``, ``type``, and
        ``category_id`` (Requirement 6.7). Any subset may be supplied; only the
        provided keys are changed. ``amount`` is coerced to a two-decimal
        ``Decimal`` when given as a string. After applying the edits the
        missing-fields flag is recomputed and persisted (Requirement 6.9), so a
        completed draft clears its flag and a newly emptied field re-flags it.

        Setting a field to ``None`` explicitly clears it. Unknown field names are
        ignored so the caller's payload shape is forgiving.
        """
        draft = self._get_draft(session_id, draft_id)
        if draft is None:
            return Result.failure("not_found", "Draft not found.")

        if "date" in fields:
            value = fields["date"]
            draft.date = None if value is None else str(value)
        if "description" in fields:
            value = fields["description"]
            draft.description = None if value is None else str(value)
        if "type" in fields:
            value = fields["type"]
            draft.type = None if value is None else str(value)
        if "category_id" in fields:
            value = fields["category_id"]
            draft.category_id = None if value is None else str(value)
        if "amount" in fields:
            value = fields["amount"]
            if value is None:
                draft.amount = None
            else:
                try:
                    from logstead.util.money import to_money

                    draft.amount = to_money(value)  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    return Result.failure(
                        "validation",
                        "Amount is not a valid monetary value.",
                        field="amount",
                    )

        self._persist_draft(draft)
        return Result.success(draft)

    def remove_draft(self, session_id: str, draft_id: str) -> Result[None]:
        """Remove a draft before confirmation (Requirement 6.8)."""
        if self._get_draft(session_id, draft_id) is None:
            return Result.failure("not_found", "Draft not found.")
        self._repo.delete_item(
            keys.import_pk(session_id), keys.draft_sk(draft_id)
        )
        return Result.success(None)

    # --- Confirm (Requirements 6.6, 6.10, 6.11) -----------------------------

    def confirm(self, session_id: str) -> Result[ConfirmOutcome]:
        """Convert only complete drafts into transactions (6.10, 6.11).

        Partitions the session's remaining drafts:

        * **Complete** — no missing required fields (date, amount, category, and
          a description when the category requires one). Each is validated
          against the Transaction rules of Requirement 5 and, on success, created
          as a real ``Transaction`` in the session's selected tax year
          (Requirements 6.10). A complete draft that still fails Transaction
          validation (e.g. amount ≤ 0) is reported as rejected with a
          field-identifying message rather than silently dropped (Requirement
          6.11); it remains a draft.
        * **Incomplete** — one or more missing required fields. Left as a draft
          and reported in ``rejected`` (never converted, never dropped;
          Requirement 6.11).

        The session is marked ``confirmed`` only when there are no rejected
        drafts (i.e. every remaining draft was complete and converted). Otherwise
        it stays in ``review`` so the user can finish the incomplete drafts.

        Before this call, no ``Transaction`` exists for the import (Requirement
        6.6) — conversion happens here and only here.
        """
        session_result = self.get_session(session_id)
        if not session_result.is_ok:
            return Result.failure("not_found", "Import session not found.")
        session = session_result.value

        creator = self._resolve_creator()

        drafts = self.list_drafts(session_id)
        outcome = ConfirmOutcome()

        for draft in drafts:
            # Recompute freshly so a stale stored flag never lets an incomplete
            # draft through (Requirement 6.9/6.10).
            missing = self._missing_fields(draft)
            if missing:
                outcome.rejected.append(
                    RejectedDraft(
                        draft_id=draft.id,
                        message=(
                            "Draft is missing required field(s): "
                            + ", ".join(missing)
                            + "."
                        ),
                        field=missing[0],
                    )
                )
                continue

            # Complete draft: build the transaction input and delegate creation
            # to the (seam) transaction creator, which enforces Requirement 5.
            txn_input = TransactionInput(
                property_id=session.property_id,
                date=draft.date,
                amount=draft.amount,
                type=draft.type or "expense",  # type: ignore[arg-type]
                category_id=draft.category_id,
                description=draft.description,
            )
            created = creator(txn_input)
            if not created.is_ok:
                # Passed our completeness check but failed Requirement 5
                # validation (e.g. amount <= 0). Report, do not drop (6.11).
                error = created.error
                outcome.rejected.append(
                    RejectedDraft(
                        draft_id=draft.id,
                        message=(
                            error.message
                            if error is not None
                            else "Draft failed transaction validation."
                        ),
                        field=error.field if error is not None else None,
                    )
                )
                continue

            outcome.created_ids.append(self._created_id(created.value))
            # Converted drafts are removed so they cannot be re-converted.
            self._repo.delete_item(
                keys.import_pk(session_id), keys.draft_sk(draft.id)
            )

        # Mark confirmed only when nothing was left behind (all complete +
        # converted). Otherwise keep the session in review for the user to
        # finish the incomplete drafts.
        if not outcome.rejected:
            session.status = "confirmed"
            self._repo.put_item(self._session_item(session))
        outcome.session = session

        return Result.success(outcome)

    # --- Transaction-creator seam -------------------------------------------

    def _resolve_creator(self) -> TransactionCreator:
        """Return the injected creator, or build one from the Transaction Service.

        Keeps :meth:`confirm` independent of task 10.1's exact API: when a creator
        was injected (tests, or an explicit wiring) it is used directly; otherwise
        the Transaction Service is imported lazily and its ``create`` adapted to
        the ``(TransactionInput) -> Result`` seam. The lazy import means this
        module imports cleanly even before 10.1 lands.
        """
        if self._transaction_creator is not None:
            return self._transaction_creator

        # Lazy, defensive import: 10.1 may not be present yet.
        from logstead.services.transaction import (  # type: ignore
            TransactionService,
        )

        service = TransactionService(self._repo)  # type: ignore[call-arg]
        return service.create  # (TransactionInput) -> Result

    @staticmethod
    def _created_id(created_value: object) -> str:
        """Extract the created transaction's id from a creator's success value.

        Tolerant of shape: accepts an object with an ``id`` attribute, a mapping
        with an ``"id"`` key, or a bare string id — so the seam does not pin us
        to one concrete Transaction representation.
        """
        if isinstance(created_value, str):
            return created_value
        if isinstance(created_value, dict):
            return str(created_value.get("id", ""))
        return str(getattr(created_value, "id", ""))
