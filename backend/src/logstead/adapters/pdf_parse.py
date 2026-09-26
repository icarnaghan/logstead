"""Expense-summary PDF parse adapter (Requirements 6.3, 6.12).

Turns a property manager's expense-summary PDF into a list of parsed line
items, each carrying an optional ``date``, ``amount`` (as ``Decimal``), and
``description`` where the source line provides them (Requirement 6.3). The
:class:`ExpenseImportService` (task 13.2) consumes these to stage
``DraftTransaction`` items for review.

Parsing runs inside the API Lambda, so it must stay within the Lambda
execution/payload limits. This adapter therefore enforces three bounds and
treats any breach — plus a document that yields **zero** line items — as a
parse failure (Requirement 6.12):

* ``max_bytes``     — reject an oversized document before touching the parser.
* ``max_pages``     — reject a document with too many pages.
* ``time_budget``   — reject a document that is too slow to extract/parse.

The PDF library call is isolated behind an injectable ``extract_text``
function. The heavy dependency (``pdfplumber``/``pypdf``) is only imported when
the default extractor actually runs, so tests can drive the line-item parser
with raw text — or a stub extractor — without the PDF stack. The pure
text-to-line-items step is exported as :func:`parse_line_items_from_text`.

Design note: parse failure is surfaced as a ``Result.failure("unavailable",
...)`` so it maps cleanly onto the shared ``Result`` type used across the
services; the import service translates it into the user-facing "no
transactions could be extracted" message (Requirement 6.12).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Final

from logstead.models.result import Result
from logstead.util.money import Money, to_money

__all__ = [
    "ParsedLineItem",
    "PdfParseBounds",
    "DEFAULT_BOUNDS",
    "parse_expense_summary",
    "parse_line_items_from_text",
]


@dataclass(frozen=True)
class ParsedLineItem:
    """A single expense-summary line item extracted from the PDF.

    Every field is optional because a source line may be incomplete; the import
    service later flags a draft that is missing a required field (Requirement
    6.9). Money is a ``Decimal`` (never a float) per Requirement 13.3.

    Attributes:
        date: ISO-8601 date string (``YYYY-MM-DD``) when a date was found.
        amount: The line amount as a two-decimal ``Decimal`` when found.
        description: The free-text remainder of the line, when present.
        raw: The original source line, kept for debugging/traceability.
    """

    date: str | None = None
    amount: Money | None = None
    description: str | None = None
    raw: str | None = field(default=None, compare=False)


@dataclass(frozen=True)
class PdfParseBounds:
    """Bounds that keep parsing within the Lambda execution/payload limits.

    A document that breaches any bound is treated as a parse failure
    (Requirement 6.12) rather than being parsed partially.

    Attributes:
        max_bytes: Maximum accepted document size in bytes.
        max_pages: Maximum accepted page count.
        time_budget_seconds: Maximum wall-clock time allowed for text
            extraction plus line parsing.
    """

    max_bytes: int = 5 * 1024 * 1024  # 5 MiB — property-manager summaries are small.
    max_pages: int = 30
    time_budget_seconds: float = 10.0


#: The default bounds used when a caller does not supply their own.
DEFAULT_BOUNDS: Final[PdfParseBounds] = PdfParseBounds()


# An extractor turns PDF bytes into (full_text, page_count). It is injectable so
# tests can bypass the PDF library entirely.
ExtractFn = Callable[[bytes], "tuple[str, int]"]


class _ParseFailure(Exception):
    """Internal signal that a document must be treated as a parse failure.

    Carries a client-safe message; :func:`parse_expense_summary` converts it
    into a ``Result.failure``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# --- Line-item heuristics ---------------------------------------------------
#
# Property-manager summaries are semi-structured plain text once extracted: one
# line item per row, typically "<date> <description> <amount>" but with the date
# and/or amount sometimes absent. The heuristics below are deliberately tolerant
# — they pull out whatever they can and leave the rest unset.

# Dates: M/D/YYYY, MM/DD/YY, YYYY-MM-DD, or M-D-YYYY (slash or dash separators).
_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b("
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}"  # 2024-01-31 / 2024/1/5
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"  # 1/31/2024 / 01-05-24
    r")\b"
)

# Currency amounts: optional leading $, optional thousands separators, a decimal
# part, optionally parenthesized (accounting-style negatives). We match the
# amount conservatively (must have a decimal part or a currency marker) so we do
# not mistake a bare integer id/quantity for money.
_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"\(?\$?\s*"  # optional ( and $ 
    r"(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+\.\d{1,2})"  # 1,234.56 | 1234.56 | 12.5
    r"\s*\)?"
)


def _normalize_date(raw: str) -> str | None:
    """Normalize a matched date token to ISO ``YYYY-MM-DD``.

    Returns ``None`` if the token is not a plausible calendar date. Two-digit
    years are windowed into the 2000s (property-manager summaries are recent).
    """
    parts = re.split(r"[-/]", raw)
    if len(parts) != 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None

    if len(parts[0]) == 4:  # YYYY-MM-DD
        year, month, day = nums
    else:  # M/D/YY or M/D/YYYY
        month, day, year = nums
        if year < 100:
            year += 2000

    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _extract_amount(line: str) -> tuple[Money | None, tuple[int, int] | None]:
    """Extract the line's monetary amount and the span it occupied.

    Chooses the **last** currency-looking token on the line, which is where the
    amount sits in a typical ``date description amount`` row. Accounting-style
    parenthesized amounts are treated as negative. Returns ``(amount, span)`` or
    ``(None, None)`` when no amount is found or it cannot be coerced to money.
    """
    matches = list(_AMOUNT_RE.finditer(line))
    if not matches:
        return None, None

    match = matches[-1]
    token = match.group(0)
    digits = match.group(1).replace(",", "")
    try:
        amount = to_money(digits)
    except (ValueError, TypeError):
        return None, None

    # Parenthesized amount => negative (accounting convention).
    if "(" in token and ")" in token:
        amount = to_money(-amount)
    return amount, match.span()


def parse_line_items_from_text(text: str) -> list[ParsedLineItem]:
    """Parse already-extracted PDF text into line items (Requirement 6.3).

    This is the pure, dependency-free core of the adapter: it applies the
    date/amount/description heuristics to each non-blank line. A line is kept as
    a :class:`ParsedLineItem` only if it yields at least one meaningful field
    (a date, an amount, or a non-trivial description); pure separators/headers
    that carry nothing useful are skipped.

    Args:
        text: The full text extracted from the PDF.

    Returns:
        The parsed line items in document order (possibly empty — the caller
        decides that empty means parse failure per Requirement 6.12).
    """
    items: list[ParsedLineItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        remainder = line

        # Amount first so we can strip its span out of the description.
        amount, amount_span = _extract_amount(remainder)
        if amount_span is not None:
            remainder = (remainder[: amount_span[0]] + " " + remainder[amount_span[1] :])

        # Date next; strip it out of the description too.
        date: str | None = None
        date_match = _DATE_RE.search(remainder)
        if date_match is not None:
            date = _normalize_date(date_match.group(1))
            if date is not None:
                remainder = (
                    remainder[: date_match.start()] + " " + remainder[date_match.end() :]
                )

        # Whatever is left, tidied up, is the description.
        description = re.sub(r"\s{2,}", " ", remainder).strip(" \t:-|") or None

        # A description of only punctuation/separators is not meaningful.
        if description is not None and not re.search(r"[A-Za-z0-9]", description):
            description = None

        if date is None and amount is None and description is None:
            continue

        items.append(
            ParsedLineItem(
                date=date,
                amount=amount,
                description=description,
                raw=line,
            )
        )
    return items


def _default_extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract full text and page count using ``pdfplumber`` (fallback ``pypdf``).

    Imported lazily so the heavy PDF stack is only required when the real
    extractor runs; tests inject a stub instead. Raises :class:`_ParseFailure`
    if neither library can read the document.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:  # pragma: no cover - exercised only without pdfplumber
        pdfplumber = None  # type: ignore[assignment]

    if pdfplumber is not None:
        import io

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = pdf.pages
                page_count = len(pages)
                texts = [page.extract_text() or "" for page in pages]
            return "\n".join(texts), page_count
        except Exception as exc:  # noqa: BLE001 - any parser error is a parse failure
            raise _ParseFailure(f"could not read PDF: {exc}") from exc

    # Fallback: pypdf.
    try:
        import io

        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        texts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(texts), page_count
    except Exception as exc:  # noqa: BLE001
        raise _ParseFailure(f"could not read PDF: {exc}") from exc


def parse_expense_summary(
    pdf_bytes: bytes,
    *,
    bounds: PdfParseBounds = DEFAULT_BOUNDS,
    extract_text: ExtractFn | None = None,
    now: Callable[[], float] = time.monotonic,
) -> Result[list[ParsedLineItem]]:
    """Parse an expense-summary PDF into line items within bounded resources.

    Enforces the size/page/time bounds and treats a breach — or a document that
    yields zero line items — as a parse failure (Requirement 6.12). On success
    the result carries a non-empty list of :class:`ParsedLineItem` (Requirement
    6.3).

    Args:
        pdf_bytes: The raw PDF document bytes.
        bounds: Size/page/time limits; defaults to :data:`DEFAULT_BOUNDS`.
        extract_text: Injectable ``bytes -> (text, page_count)`` extractor;
            defaults to a ``pdfplumber``/``pypdf``-backed one. Tests pass a stub
            so no real PDF dependency is required.
        now: Monotonic clock used to measure the parse-time budget; injectable
            for deterministic tests.

    Returns:
        * ``Result.success(list[ParsedLineItem])`` with at least one item.
        * ``Result.failure("unavailable", ...)`` when the document is oversized,
          too many pages, too slow, unreadable, or yields no line items.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        return Result.failure(
            "unavailable",
            "No transactions could be extracted: the upload was not a readable document.",
        )

    if len(pdf_bytes) == 0:
        return Result.failure(
            "unavailable",
            "No transactions could be extracted: the document was empty.",
        )

    if len(pdf_bytes) > bounds.max_bytes:
        return Result.failure(
            "unavailable",
            "No transactions could be extracted: the document is too large to parse.",
        )

    extractor = extract_text or _default_extract_text
    start = now()

    try:
        text, page_count = extractor(bytes(pdf_bytes))
    except _ParseFailure as exc:
        return Result.failure(
            "unavailable",
            f"No transactions could be extracted: {exc.message}",
        )
    except Exception as exc:  # noqa: BLE001 - any extractor error is a parse failure
        return Result.failure(
            "unavailable",
            f"No transactions could be extracted: {exc}",
        )

    if page_count > bounds.max_pages:
        return Result.failure(
            "unavailable",
            "No transactions could be extracted: the document has too many pages to parse.",
        )

    items = parse_line_items_from_text(text)

    # Time check after the work: if extraction + parsing blew the budget, treat
    # the document as too slow to parse (Requirement 6.12).
    if now() - start > bounds.time_budget_seconds:
        return Result.failure(
            "unavailable",
            "No transactions could be extracted: the document took too long to parse.",
        )

    if not items:
        return Result.failure(
            "unavailable",
            "No transactions could be extracted from the document. You can enter transactions manually.",
        )

    return Result.success(items)
