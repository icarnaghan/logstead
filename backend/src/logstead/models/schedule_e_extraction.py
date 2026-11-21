"""Service-layer models for Schedule E PDF Extraction ("layer 2").

These dataclasses describe the input and output shapes exchanged between the
router and the ``ExtractionService``. The governing principle is *extraction
proposes, the human confirms, layer 1 persists*: nothing in this module is a
durable domain record. A :class:`ReviewDraft` is the transient, pre-filled
layer-1 ``ImportSubmission`` presented for review; it mirrors the layer-1 shape
(one ``tax_year`` and one column per property) so the existing SPA form can seed
itself directly, then hand the user-confirmed values to the **unchanged** layer-1
``ImportService`` write path.

No money is parsed in this module. Each :class:`ExtractedLine.amount` is already
a two-decimal money string normalized by the service through the ``util/money``
boundary (``to_money`` / ``money_to_str``), consistent with layer-1's
``LineAmountInput.amount`` (Req 5.3). An unreadable amount becomes ``"0.00"``
with ``needs_verification=True`` rather than being dropped (Req 5.2).

Line 18 (Depreciation) is intentionally unrepresentable: ``ExtractedLine`` carries
a single ``schedule_e_line`` int, and the pure parser's allow-set
``{3,4,5-17,19}`` — never the type — is what excludes 18. The type cannot
distinguish 18 from any other int; it is the parser allow-set that guarantees a
Line 18 amount is never read or carried into a :class:`ReviewDraft` (Req 4.5,
8.4).

These dataclasses serialize through the handler's existing ``_to_jsonable``
(dataclasses → snake_case dicts, ``Decimal`` → string).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["pending", "processing", "complete", "failed"]
CompleteOutcome = Literal["draft", "no_schedule_e_found"]


@dataclass
class StartExtractionOutcome:
    """Result of ``start_extraction`` (Req 1).

    Attributes:
        job_id: The newly minted extraction job id (scoped to the user).
        upload_url: A presigned S3 PUT URL the SPA uploads the PDF bytes to,
            directly (never through the Lambda).
    """

    job_id: str
    upload_url: str


@dataclass
class ExtractedLine:
    """One pre-filled Schedule E line within an :class:`ExtractedColumn`.

    Attributes:
        schedule_e_line: The IRS Schedule E Part I line number. Income lines are
            3 (Rents) and 4 (Royalties); expense lines are 5-17 and 19 (Other).
            The parser's allow-set ``{3,4,5-17,19}`` — not this type — is what
            excludes Line 18 (Depreciation), which never appears (Req 4.5, 8.4).
        amount: The pre-filled amount as a two-decimal money string ("0.00" when
            the value could not be read/normalized, Req 5.1/5.2).
        needs_verification: ``True`` when confidence is low or the value was
            unreadable, so the SPA surfaces a "please verify" indicator
            (Req 5.2, 8.3).
        confidence: The contributing Textract block confidence (0-100) when
            available, else ``None``.
    """

    schedule_e_line: int
    amount: str
    needs_verification: bool
    confidence: float | None = None


@dataclass
class ExtractedColumn:
    """One Schedule E Part I property column (A, B, C, ...) → one Property_Entry.

    Attributes:
        address_text: The extracted physical address text, or ``None`` when not
            read.
        address_confidence: The address block confidence (0-100), or ``None``.
        suggested_property_id: A fuzzy-match suggestion from the user's own
            properties (Req 7), or ``None`` when no candidate cleared the
            threshold. Never auto-applied — the user confirms it in the form.
        suggested_property_name: The suggested property's display name, or
            ``None``.
        mapping_confidence: The fuzzy-match confidence score, or ``None`` when
            there is no suggestion.
        lines: The pre-filled per-line amounts for this property column;
            defaults to an empty list.
    """

    address_text: str | None
    address_confidence: float | None
    suggested_property_id: str | None
    suggested_property_name: str | None
    mapping_confidence: float | None
    lines: list[ExtractedLine] = field(default_factory=list)


@dataclass
class ReviewDraft:
    """The transient pre-filled Import_Submission presented for review (Req 8).

    Mirrors the layer-1 ``ImportSubmission`` structure (one ``tax_year``, one
    column per property) so the SPA can seed the existing ``ScheduleEImportForm``
    directly. Never copied into any durable domain record.

    Attributes:
        tax_year: The detected single Tax_Year, or ``None`` when not confidently
            detected (Req 6.2).
        tax_year_needs_verification: ``True`` when the year was absent or
            low-confidence, so the SPA flags it for verification (Req 6.2).
        columns: One :class:`ExtractedColumn` per detected property column;
            defaults to an empty list.
    """

    tax_year: int | None
    tax_year_needs_verification: bool
    columns: list[ExtractedColumn] = field(default_factory=list)


@dataclass
class ExtractionJobView:
    """What a status poll returns to the SPA (Req 3).

    A ``failed`` / ``no_schedule_e_found`` poll is itself a successful poll — the
    job ran; the outcome is just negative.

    Attributes:
        job_id: The extraction job id.
        status: The current job status.
        outcome: Set only when ``status == "complete"`` — ``"draft"`` when a
            Review_Draft is available, ``"no_schedule_e_found"`` otherwise.
        message: A failure / no-Schedule-E message, else ``None``.
        review_draft: The pre-filled draft, set only when
            ``outcome == "draft"``.
    """

    job_id: str
    status: JobStatus
    outcome: CompleteOutcome | None = None
    message: str | None = None
    review_draft: ReviewDraft | None = None


__all__ = [
    "JobStatus",
    "CompleteOutcome",
    "StartExtractionOutcome",
    "ExtractedLine",
    "ExtractedColumn",
    "ReviewDraft",
    "ExtractionJobView",
]
