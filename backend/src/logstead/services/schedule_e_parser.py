"""Pure Schedule E Part I parser (Requirements 4.1-4.6, 5.2, 6.1-6.3, 8.3, 12.2).

A standard-library-only, AWS-free, deterministic module that turns a raw
Amazon Textract blocks list (the ``Block`` dicts returned by
``GetDocumentAnalysis``) into a structured :class:`ParsedExtraction`. It has no
S3, DynamoDB, or boto3 dependency, so tests feed it canned Textract-response
JSON fixtures and never touch live AWS.

Entry point::

    parse_schedule_e(blocks, *, min_confidence) -> ParsedExtraction

Design "The parser (pure — services/schedule_e_parser.py)", steps (a)-(f):

* **(a) Locate Schedule E Part I.** Scan ``LINE`` text for the characteristic
  markers of the form: a Schedule E title marker ("Schedule E" / "Part I" / the
  "Income or Loss From Rental Real Estate" title) *plus* at least one piece of
  Schedule-E-specific evidence ("Rents received", "Royalties received", the
  "Properties:" A/B/C header, or the full rental-real-estate title). The
  specificity requirement rejects Schedule C and generic expense worksheets that
  merely share labels like Advertising or Insurance. Each matching page is
  processed independently and its columns concatenated. When no page matches,
  :attr:`ParsedExtraction.no_schedule_e_found` is ``True`` and no columns are
  produced (Req 4.1, 12.2).
* **(b) Property columns + line amounts.** For each located Part I page, produce
  one :class:`ParsedColumn` per *genuine* property column (A, B, C — capped at
  three per page). Within the page's property table the parser locates the A/B/C
  header-letter row and derives each property's column *span* (letter column up
  to the next letter's column), then reads each amount from the numeric cell in
  that span. Each row's line is anchored to the Schedule E line number the form
  prints in the row's leftmost column (``_line_in_row`` / ``_line_number_token``),
  **not** to its label text — the dense totals rows (lines 20-26) carry free-text
  labels mentioning other lines, which label matching would mis-map and overwrite.
  Column count is **not** taken from raw table width (an earlier ``max_col - 1``
  heuristic over-counted an unrelated wide worksheet as ~10 phantom columns).
  Because the blank IRS form always prints three A/B/C headers even when fewer
  properties are used, a detected column is pruned unless it looks like a real
  property — it has a Rents (line 3) amount or at least two populated expense
  lines — so the form's totals/summary column (no rents, no per-property
  expenses) is dropped while a genuine rental or expense-bearing royalty survives
  (``_prune_phantom_columns``; all columns kept if the rule would reject every
  one). A clean grid with no letter header falls back to the legacy contiguous
  reading (label in column 1, line read by label, properties in columns 2..N); a
  weak TABLES result falls back to geometry (numeric tokens on the same
  horizontal band bucketed left-to-right by ``Left``), scoped to the page and
  capped at three columns. Only the allow-set
  ``{3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,19}`` is read — **never** Line 18, and
  rows numbered outside the allow-set (18, or the 20-26 totals) are skipped, so a
  depreciation amount can never be read or carried (Req 4.2, 4.3, 4.5). An
  absent/unreadable allowed line yields an empty raw token with
  ``needs_verification=True`` (Req 4.6).
* **(c) Per-column physical-address box.** Read each column's "Physical address
  of each property" area via the FORMS ``KEY_VALUE_SET`` pairs (locate the
  address key, read the paired value per column), with a geometry fallback
  bucketed into the same column positions as the amounts (Req 4.4).
* **(d) Tax year.** Scan header ``LINE``s for a four-digit year / the
  "For calendar year 20YY" phrasing; set the single detected year or leave it
  ``None`` and flagged (Req 6.1, 6.2, 6.3).
* **(e) Per-value confidence.** Attach each contributing block's ``Confidence``
  (0-100) to each produced line/address/year value and set
  ``needs_verification=True`` when confidence is below ``min_confidence`` or the
  value could not be read (Req 5.2, 8.3).

**Purity / money boundary.** This parser is pure and emits amounts as the **raw
read tokens** (``ParsedLine.raw_amount``) exactly as OCR'd — it does *not*
normalize money. The ``ExtractionService`` is responsible for normalizing each
raw token to a two-decimal money string through ``util/money`` (``to_money`` /
``money_to_str``) when it builds the service-layer ``ReviewDraft``. Keeping
money normalization out of the parser keeps this module trivially testable and
free of the money convention's error handling.

**Honesty about heuristics.** Exact box/line geography on a scanned government
form is inherently heuristic. Every value carries a confidence and a
``needs_verification`` flag; nothing here is ground truth — the parser's job is
a good *pre-fill*, surfaced for human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "ALLOWED_LINES",
    "ParsedLine",
    "ParsedColumn",
    "ParsedExtraction",
    "parse_schedule_e",
]

#: The explicit Schedule E Part I line allow-set the parser will ever read:
#: income lines 3-4, expense lines 5-17, and Line 19 (Other). Line 18
#: (Depreciation) is deliberately absent, so a depreciation amount can never be
#: read or carried into the result (Req 4.5).
ALLOWED_LINES: Final[frozenset[int]] = frozenset(
    {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19}
)

# --- Form markers used to recognize a Schedule E Part I page (step a) --------

#: Title / section markers. Any one of these counts as the "title" signal.
_TITLE_MARKERS: Final[tuple[str, ...]] = (
    "schedule e",
    "part i",
    "income or loss from rental real estate",
)

#: Schedule-E-specific evidence that is ABSENT from a Schedule C / generic
#: expense worksheet. A page needs the title marker PLUS at least one of these
#: to be treated as Part I, so pages that merely share generic expense labels
#: (Advertising, Insurance, Supplies, Taxes, Utilities) are rejected. "rents
#: received" is Schedule E line 3; "properties:" is the A/B/C header marker.
_SCHEDULE_E_EVIDENCE: Final[tuple[str, ...]] = (
    "rents received",
    "royalties received",
    "properties:",
    "income or loss from rental real estate",
)

#: The structural maximum number of property columns on one Schedule E Part I
#: page (columns A, B, C). The width/geometry heuristics are capped at this.
_MAX_PROPERTY_COLUMNS: Final[int] = 3

#: The highest table column index that may carry a printed Schedule E line
#: number. On the real grid the line number sits in columns 1 and 3, flanking
#: the label in column 2; property amount columns begin at 4. Scoping the
#: line-number scan to this zone keeps a bare 1-2 digit amount from being read
#: as a line number (see _line_in_row).
_LINE_NUMBER_MAX_COLUMN: Final[int] = 3

#: The single-letter property-column header labels, in order (A, B, C). The
#: header-letter row of a Part I property table carries these.
_PROPERTY_LETTERS: Final[tuple[str, ...]] = ("A", "B", "C")

#: A Schedule E Part I property grid always prints three column headers (A, B,
#: C) even when the taxpayer used fewer; the unused header's column then only
#: carries the form's totals/summary roll-ups (lines 23a-26), which Textract
#: places under that header letter and the reader mistakes for a real property.
#: A detected column is kept only when it looks like a genuine property: it has
#: a readable Rents (line 3) amount, OR at least this many populated expense
#: lines. The totals column has no rents and no real per-property expenses, so
#: it is pruned; a genuine rental (rents) or an expense-bearing royalty property
#: survives. See _is_real_property_column / _prune_phantom_columns.
_MIN_EXPENSE_LINES_FOR_PROPERTY: Final[int] = 2

#: The Schedule E Part I expense lines (allow-set, excluding income lines 3-4
#: and always excluding Line 18 Depreciation) used by the phantom-column test.
_EXPENSE_LINES: Final[frozenset[int]] = frozenset(
    {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19}
)

#: Maps a recognized line-label substring to its Schedule E line number. Used
#: by the amount reader to associate a label row with its allowed line. Only
#: allow-set lines appear here; Line 18 (Depreciation) is intentionally omitted.
_LABEL_TO_LINE: Final[tuple[tuple[str, int], ...]] = (
    ("rents received", 3),
    ("royalties received", 4),
    ("royalties", 4),
    ("advertising", 5),
    ("auto and travel", 6),
    ("cleaning and maintenance", 7),
    ("commissions", 8),
    ("insurance", 9),
    ("legal and other professional", 10),
    ("legal and other", 10),
    ("management fees", 11),
    ("mortgage interest paid to banks", 12),
    ("mortgage interest", 12),
    ("other interest", 13),
    ("repairs", 14),
    ("supplies", 15),
    ("taxes", 16),
    ("utilities", 17),
    # NOTE: Line 18 (Depreciation) is deliberately NOT mapped here.
    ("other", 19),
)

#: Phrases that mark the physical-address key in the FORMS result (step c).
_ADDRESS_KEY_MARKERS: Final[tuple[str, ...]] = (
    "physical address of each property",
    "physical address",
)

#: A plausible tax year range for a prior-year return (step d). Bounds keep an
#: OCR'd stray four-digit number (a ZIP, an amount) from being mistaken for a
#: year.
_MIN_YEAR: Final[int] = 1900
_MAX_YEAR: Final[int] = 2100

# A four-digit year, optionally after "20" placeholder phrasing.
_YEAR_RE: Final[re.Pattern[str]] = re.compile(r"\b(19|20)\d{2}\b")
# "For calendar year 2023" / "calendar year 20 23" style phrasing.
_CALENDAR_YEAR_RE: Final[re.Pattern[str]] = re.compile(
    r"calendar\s+year\s+((?:19|20)\d{2})"
)

# A numeric money-ish token: optional $, digits with optional grouping commas
# and optional cents, optionally parenthesized (negative) — captured as a raw
# token (NOT normalized here). The cents group is optional and may be a bare
# trailing dot ("21,000." / "686."), which is how scanned IRS forms commonly
# render whole-dollar amounts; the service normalizes the raw token downstream.
_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\(?\$?-?\d{1,3}(?:,\d{3})*(?:\.\d*)?\)?$|^\(?\$?-?\d+(?:\.\d*)?\)?$"
)


@dataclass
class ParsedLine:
    """One raw Schedule E line reading within a :class:`ParsedColumn`.

    The parser emits the raw OCR token here; the service normalizes it to a
    two-decimal money string. Never carries Line 18.

    Attributes:
        schedule_e_line: The IRS Schedule E Part I line number, always a member
            of :data:`ALLOWED_LINES` (never 18).
        raw_amount: The raw amount token as read ("" when absent/unreadable).
        confidence: The contributing Textract block confidence (0-100), or
            ``None`` when the value could not be read.
        needs_verification: ``True`` when confidence is below ``min_confidence``
            or the value could not be read (Req 4.6, 5.2, 8.3).
    """

    schedule_e_line: int
    raw_amount: str
    confidence: float | None
    needs_verification: bool


@dataclass
class ParsedColumn:
    """One Schedule E Part I property column (A, B, C, ...).

    Attributes:
        address_text: The raw physical-address text, or ``None`` when not read.
        address_confidence: The address block confidence (0-100), or ``None``.
        address_needs_verification: ``True`` when the address was absent or
            low-confidence.
        lines: The per-line raw readings for this column (allow-set only).
    """

    address_text: str | None
    address_confidence: float | None
    address_needs_verification: bool
    lines: list[ParsedLine] = field(default_factory=list)


@dataclass
class ParsedExtraction:
    """The pure parser's structured result.

    The service maps this to the service-layer ``ReviewDraft`` (normalizing
    money and attaching fuzzy property suggestions).

    Attributes:
        no_schedule_e_found: ``True`` when no Schedule E Part I page was located;
            ``columns`` is then empty (Req 12.2).
        tax_year: The single detected tax year, or ``None`` when not confidently
            found (Req 6.2).
        tax_year_confidence: The confidence of the detected year, or ``None``.
        tax_year_needs_verification: ``True`` when the year was absent or
            low-confidence (Req 6.2).
        columns: One :class:`ParsedColumn` per detected property column; empty
            when ``no_schedule_e_found`` is ``True``.
    """

    no_schedule_e_found: bool
    tax_year: int | None = None
    tax_year_confidence: float | None = None
    tax_year_needs_verification: bool = True
    columns: list[ParsedColumn] = field(default_factory=list)


# --- Block-graph helpers -----------------------------------------------------


def _block_text(block: dict[str, Any]) -> str:
    """Return a block's ``Text`` (empty string when absent)."""
    text = block.get("Text")
    return text if isinstance(text, str) else ""


def _block_conf(block: dict[str, Any]) -> float | None:
    """Return a block's ``Confidence`` as a float, or ``None`` when absent."""
    conf = block.get("Confidence")
    if isinstance(conf, (int, float)):
        return float(conf)
    return None


def _bbox(block: dict[str, Any]) -> dict[str, float]:
    """Return a block's ``Geometry.BoundingBox`` (empty dict when absent)."""
    geom = block.get("Geometry")
    if isinstance(geom, dict):
        box = geom.get("BoundingBox")
        if isinstance(box, dict):
            return box
    return {}


def _index_by_id(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index blocks by their ``Id`` for relationship traversal."""
    return {b["Id"]: b for b in blocks if isinstance(b.get("Id"), str)}


def _related_ids(block: dict[str, Any], rel_type: str) -> list[str]:
    """Return the ``Ids`` of a block's relationship of ``rel_type``."""
    out: list[str] = []
    for rel in block.get("Relationships", []) or []:
        if isinstance(rel, dict) and rel.get("Type") == rel_type:
            ids = rel.get("Ids")
            if isinstance(ids, list):
                out.extend(i for i in ids if isinstance(i, str))
    return out


def _cell_text(
    cell: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> tuple[str, float | None]:
    """Join the WORD children of a CELL into text + min child confidence."""
    words: list[str] = []
    confs: list[float] = []
    for child_id in _related_ids(cell, "CHILD"):
        child = by_id.get(child_id)
        if child is None:
            continue
        if child.get("BlockType") in ("WORD", "SELECTION_ELEMENT"):
            txt = _block_text(child)
            if txt:
                words.append(txt)
            c = _block_conf(child)
            if c is not None:
                confs.append(c)
    text = " ".join(words).strip()
    conf = min(confs) if confs else _block_conf(cell)
    return text, conf


def _key_value_text(
    kv_block: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> tuple[str, float | None]:
    """Join the WORD children referenced by a KEY/VALUE block into text."""
    words: list[str] = []
    confs: list[float] = []
    for child_id in _related_ids(kv_block, "CHILD"):
        child = by_id.get(child_id)
        if child is None:
            continue
        txt = _block_text(child)
        if txt:
            words.append(txt)
        c = _block_conf(child)
        if c is not None:
            confs.append(c)
    text = " ".join(words).strip()
    conf = min(confs) if confs else _block_conf(kv_block)
    return text, conf


# --- Amount token helpers ----------------------------------------------------


#: A bare Schedule E Part I line number as printed on the form (1-2 digits).
#: The real grid prints the line number in BOTH the leftmost column and a second
#: narrow column flanking the label; a row whose two line-number columns agree on
#: an allow-set integer is a genuine data row (NOT a totals/summary row such as
#: "23a" or line 20-26). Used to anchor rows to lines by the form's own numbering
#: rather than fuzzy label text — the label of a totals row ("Subtract line 20
#: from line 3 ... or 4 (royalties)") would otherwise false-match a real line.
_LINE_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"^\d{1,2}$")


def _line_number_token(token: str) -> int | None:
    """Return a bare 1-2 digit line number as an int, or None."""
    stripped = token.strip()
    if _LINE_NUMBER_RE.match(stripped):
        return int(stripped)
    return None


def _looks_like_amount(token: str) -> bool:
    """True when a token looks like a numeric money amount."""
    stripped = token.strip()
    if not stripped:
        return False
    return bool(_AMOUNT_RE.match(stripped))


def _line_for_label(label_text: str) -> int | None:
    """Map a line-label LINE's text to its Schedule E line number, or None.

    Only allow-set lines are mappable; a label that resolves to Line 18
    (Depreciation) is impossible because 18 is never in :data:`_LABEL_TO_LINE`.
    """
    lowered = label_text.lower()
    for marker, line in _LABEL_TO_LINE:
        if marker in lowered:
            if line in ALLOWED_LINES:
                return line
            return None  # pragma: no cover - defensive; 18 never mapped
    return None


# --- Page location (step a) --------------------------------------------------


def _page_lines(
    blocks: list[dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> dict[str | None, list[dict[str, Any]]]:
    """Group LINE blocks by their owning PAGE block's id.

    Textract blocks carry a ``Page`` number; when PAGE blocks list CHILD LINE
    ids we honor those, else we fall back to the ``Page`` attribute. LINEs with
    no page association are grouped under ``None``.
    """
    groups: dict[int | None, list[dict[str, Any]]] = {}

    # Prefer explicit PAGE → CHILD relationships, keyed by the PAGE's number so
    # the located page can later scope TABLE/FORMS reads by their ``Page``.
    page_blocks = [b for b in blocks if b.get("BlockType") == "PAGE"]
    assigned: set[str] = set()
    if page_blocks:
        for page in page_blocks:
            page_num = page.get("Page")
            child_lines: list[dict[str, Any]] = []
            for cid in _related_ids(page, "CHILD"):
                child = by_id.get(cid)
                if child is not None and child.get("BlockType") == "LINE":
                    child_lines.append(child)
                    assigned.add(cid)
                    if page_num is None:
                        page_num = child.get("Page")
            groups.setdefault(page_num, []).extend(child_lines)

    # Fall back to the ``Page`` number for any LINE not already assigned.
    for b in blocks:
        if b.get("BlockType") != "LINE":
            continue
        if b.get("Id") in assigned:
            continue
        groups.setdefault(b.get("Page"), []).append(b)

    return groups


def _is_part_i_page(lines: list[dict[str, Any]]) -> bool:
    """True when a page is a genuine Schedule E Part I page.

    A page must carry a Schedule E title marker AND at least one piece of
    Schedule-E-specific evidence (:data:`_SCHEDULE_E_EVIDENCE`) that a Schedule C
    / generic expense worksheet would not have. The specificity requirement
    rejects pages that merely share generic expense labels (Advertising,
    Insurance, Supplies, Taxes, Utilities), which previously false-matched as
    Part I (Req 2.3).
    """
    joined = " \n ".join(_block_text(ln).lower() for ln in lines)
    has_title = any(marker in joined for marker in _TITLE_MARKERS)
    if not has_title:
        return False
    # Schedule-E-specific evidence is REQUIRED: a Schedule C / generic expense
    # worksheet may share the generic line labels but never carries "rents
    # received" / "royalties received" / a "Properties:" A/B/C header / the full
    # "income or loss from rental real estate" title (Req 2.3). This single
    # requirement rejects the previously false-matching pages without depending
    # on how many generic labels Textract happened to emit as standalone LINEs
    # (table-cell labels are not LINE blocks).
    return any(ev in joined for ev in _SCHEDULE_E_EVIDENCE)


# --- Tax year (step d) -------------------------------------------------------


def _detect_tax_year(
    lines: list[dict[str, Any]], min_confidence: float
) -> tuple[int | None, float | None, bool]:
    """Detect a single tax year from header LINEs.

    Returns ``(year, confidence, needs_verification)``. Prefers an explicit
    "calendar year 20YY" phrasing; otherwise takes the first in-range four-digit
    year. Leaves the year ``None`` and flagged when none is confidently found.
    """
    for ln in lines:
        text = _block_text(ln)
        m = _CALENDAR_YEAR_RE.search(text.lower())
        if m:
            year = int(m.group(1))
            if _MIN_YEAR <= year <= _MAX_YEAR:
                conf = _block_conf(ln)
                needs = conf is None or conf < min_confidence
                return year, conf, needs

    for ln in lines:
        text = _block_text(ln)
        m = _YEAR_RE.search(text)
        if m:
            year = int(m.group(0))
            if _MIN_YEAR <= year <= _MAX_YEAR:
                conf = _block_conf(ln)
                needs = conf is None or conf < min_confidence
                return year, conf, needs

    return None, None, True


# --- Property-column detection + amounts (step b) ----------------------------


def _vertical_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    """True when two bounding boxes share a horizontal band (Top overlap)."""
    a_top = a.get("Top")
    a_h = a.get("Height")
    b_top = b.get("Top")
    b_h = b.get("Height")
    if None in (a_top, a_h, b_top, b_h):
        return False
    a_bottom = a_top + a_h
    b_bottom = b_top + b_h
    # Overlap when the mid-line of one sits within the other's band (loose).
    a_mid = a_top + a_h / 2
    b_mid = b_top + b_h / 2
    return (b_top <= a_mid <= b_bottom) or (a_top <= b_mid <= a_bottom)


def _table_rows(
    table: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> dict[int, dict[int, dict[str, Any]]]:
    """Group a TABLE's CELL children by RowIndex → {ColumnIndex: cell}."""
    rows: dict[int, dict[int, dict[str, Any]]] = {}
    for cid in _related_ids(table, "CHILD"):
        cell = by_id.get(cid)
        if cell is None or cell.get("BlockType") != "CELL":
            continue
        r = cell.get("RowIndex")
        c = cell.get("ColumnIndex")
        if isinstance(r, int) and isinstance(c, int):
            rows.setdefault(r, {})[c] = cell
    return rows


def _header_letter_columns(
    rows: dict[int, dict[int, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
) -> list[int]:
    """Find the property-letter header columns (the A/B/C ColumnIndexes).

    Scans each row for cells whose text is exactly a single property letter
    (A, B, C). The row with the most such letters is the header-letter row; its
    letters' ColumnIndexes (in order) are the property-amount column anchors,
    capped at :data:`_MAX_PROPERTY_COLUMNS`. Returns an empty list when no such
    row exists (the caller then falls back to the legacy contiguous layout).
    """
    best_cols: list[int] = []
    for _r, cells in sorted(rows.items()):
        letter_cols: list[int] = []
        for col_index in sorted(cells):
            text, _ = _cell_text(cells[col_index], by_id)
            if text.strip().upper() in _PROPERTY_LETTERS:
                letter_cols.append(col_index)
        if len(letter_cols) > len(best_cols):
            best_cols = letter_cols
    return best_cols[:_MAX_PROPERTY_COLUMNS]


def _column_spans(
    letter_cols: list[int], max_col: int
) -> list[tuple[int, int]]:
    """Compute each property's (start_col, end_col) span from the letter anchors.

    Property *i* owns columns from its header letter up to (but not including)
    the next letter's column; the last property's span runs to ``max_col``.
    """
    spans: list[tuple[int, int]] = []
    for i, start in enumerate(letter_cols):
        end = letter_cols[i + 1] - 1 if i + 1 < len(letter_cols) else max_col
        spans.append((start, end))
    return spans


def _amounts_from_table_page(
    tables: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> tuple[int, dict[int, dict[int, tuple[str, float | None]]]]:
    """Read property columns + amounts from one Part I page's tables.

    Returns ``(num_columns, {prop_idx: {schedule_e_line: (raw, conf)}})``.

    Prefers HEADER-LETTER detection: within the page's property table, locate
    the A/B/C header row and derive each property's column span; map each row's
    line by scanning its text cells for a recognized line label (NOT assuming
    column 1); read each property's amount from the numeric cell in that
    property's span. Line 18 is never mapped, so its row is skipped (Req 2.2,
    2.4). When no header-letter row exists, falls back to the legacy contiguous
    layout (label in column 1, properties in columns 2..N) so the clean
    ``clean_two_columns.json`` path is preserved (Req 3.1).
    """
    best: tuple[int, dict[int, dict[int, tuple[str, float | None]]]] = (0, {})

    for table in tables:
        rows = _table_rows(table, by_id)
        if not rows:
            continue
        max_col = max((max(cells) for cells in rows.values()), default=0)
        letter_cols = _header_letter_columns(rows, by_id)

        if letter_cols:
            spans = _column_spans(letter_cols, max_col)
            amounts = _read_amounts_by_span(rows, by_id, spans)
            num_columns = len(spans)
        else:
            num_columns, amounts = _read_amounts_contiguous(rows, by_id, max_col)

        # Prefer the table that actually carries the most Schedule E amounts,
        # then (as a tiebreak) the most property columns. Ranking populated
        # amount cells FIRST is essential: a Part I page also carries wider but
        # data-free sibling tables (the Yes/No questionnaire, the property-type
        # mini-tables), and a column-count-first rank let such an empty table —
        # read via the contiguous ``max_col - 1`` path — shadow the real grid,
        # yielding phantom columns with all-zero values. The real grid always
        # wins on populated-cell count.
        populated = sum(len(v) for v in amounts.values())
        best_populated = sum(len(v) for v in best[1].values())
        if (populated, num_columns) > (best_populated, best[0]):
            best = (num_columns, amounts)

    return best


def _read_amounts_by_span(
    rows: dict[int, dict[int, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
    spans: list[tuple[int, int]],
) -> dict[int, dict[int, tuple[str, float | None]]]:
    """Read amounts using header-letter column spans.

    For each row, map the line by scanning all the row's text cells for a
    recognized label; then for each property pick the numeric cell whose
    ColumnIndex falls in that property's span (preferring the letter column).
    """
    out: dict[int, dict[int, tuple[str, float | None]]] = {
        i: {} for i in range(len(spans))
    }
    for _r, cells in sorted(rows.items()):
        line = _line_in_row(cells, by_id)
        if line is None:
            continue
        for prop_idx, (start, end) in enumerate(spans):
            reading = _numeric_cell_in_span(cells, by_id, start, end)
            if reading is not None:
                out[prop_idx][line] = reading
    return out


def _read_amounts_contiguous(
    rows: dict[int, dict[int, dict[str, Any]]],
    by_id: dict[str, dict[str, Any]],
    max_col: int,
) -> tuple[int, dict[int, dict[int, tuple[str, float | None]]]]:
    """Legacy contiguous reader: label in column 1, properties in columns 2..N.

    Preserves the behavior for clean two-column grids that lack an A/B/C header
    row (Req 3.1). Returns ``(num_columns, amounts)``.
    """
    num_columns = max(max_col - 1, 0)
    out: dict[int, dict[int, tuple[str, float | None]]] = {
        i: {} for i in range(num_columns)
    }
    for _r, cells in sorted(rows.items()):
        label_cell = cells.get(1)
        if label_cell is None:
            continue
        label_text, _ = _cell_text(label_cell, by_id)
        line = _line_for_label(label_text)
        if line is None:
            continue
        for prop_idx in range(num_columns):
            cell = cells.get(prop_idx + 2)
            if cell is None:
                continue
            raw, conf = _cell_text(cell, by_id)
            out[prop_idx][line] = (raw.strip(), conf)
    return num_columns, out


def _line_in_row(
    cells: dict[int, dict[str, Any]], by_id: dict[str, dict[str, Any]]
) -> int | None:
    """Map a table row to its Schedule E line by scanning all its text cells.

    Does NOT assume the label is in column 1 — the real grid places line labels
    in column 2 (line numbers in columns 1 and 3). Returns the first recognized
    allow-set line, or None (Line 18 is never mappable).
    """
    # PREFERRED: the form's own line number. The real grid prints the line
    # number in two narrow columns flanking the label (e.g. columns 1 and 3).
    # When those columns agree on an allow-set integer, that is the line — this
    # anchors each row to the correct line by the form's numbering and rejects
    # the dense totals/summary rows (lines 20-26, "23a"-"e") whose labels would
    # otherwise fuzzy-match a real line. A number NOT in the allow-set (e.g. 18
    # Depreciation, 20-26 totals) means "skip this row", so we return None
    # rather than falling through to a misleading label match.
    # PREFERRED: the form's own line number in the leftmost column. Every row
    # of the real Part I grid prints its Schedule E line number in column 1
    # (confirmed in a flanking column on data rows). When column 1 holds a bare
    # line number, it is authoritative: return it if it is an allow-set line, or
    # None to SKIP the row when it is not (e.g. 18 Depreciation, or 20-26 totals
    # rows). This anchors each amount to the correct line by the form's own
    # numbering and stops the dense totals/summary rows — whose free-text labels
    # mention other lines ("...income or (loss)", "Subtract line 20 from line 3
    # ... or 4 (royalties)") — from fuzzy-matching and overwriting a real line.
    # Scan ALL the narrow left-hand columns (1.._LINE_NUMBER_MAX_COLUMN) for a
    # bare line-number token, not just the leftmost. The real grid may print the
    # label in column 1 and the bare number in column 3 (or vice-versa); a
    # totals row like "21 Subtract line 20 from line 3 (rents) and/or 4
    # (royalties)" carries its label in column 1 and the bare "21" in column 3.
    # The FIRST bare number found in these columns is authoritative: return it
    # when it is an allow-set line, or None to SKIP the row when it is not (18
    # Depreciation, or the 20-26 totals/summary rows). Finding a bare number but
    # skipping it is deliberate — it stops the label fallback below from
    # fuzzy-matching a totals row's cross-referencing label ("...3 (rents) and/or
    # 4 (royalties)") onto a real line and overwriting its amount.
    for col_index in sorted(c for c in cells if c <= _LINE_NUMBER_MAX_COLUMN):
        n = _line_number_token(_cell_text(cells[col_index], by_id)[0])
        if n is not None:
            return n if n in ALLOWED_LINES else None

    # FALLBACK: label text. Preserves the clean single-table layout, which has
    # no printed line-number column (label in column 1, amounts in 2..N).
    for col_index in sorted(cells):
        text, _ = _cell_text(cells[col_index], by_id)
        line = _line_for_label(text)
        if line is not None:
            return line
    return None


def _numeric_cell_in_span(
    cells: dict[int, dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    start: int,
    end: int,
) -> tuple[str, float | None] | None:
    """Return the (raw, conf) of the numeric cell in [start, end], or None.

    Prefers the cell at the span's start column (the header-letter column), then
    the first numeric-looking cell scanning left-to-right across the span.
    """
    start_cell = cells.get(start)
    if start_cell is not None:
        raw, conf = _cell_text(start_cell, by_id)
        if _looks_like_amount(raw):
            return raw.strip(), conf
    for col_index in range(start, end + 1):
        cell = cells.get(col_index)
        if cell is None:
            continue
        raw, conf = _cell_text(cell, by_id)
        if _looks_like_amount(raw):
            return raw.strip(), conf
    return None


def _amounts_from_geometry(
    part_lines: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    num_columns: int,
) -> dict[int, dict[int, tuple[str, float | None]]]:
    """Geometry fallback: bucket numeric tokens on a label's band into columns.

    For each recognized line-label LINE, collect numeric LINE tokens that share
    its horizontal band and bucket them left-to-right by ``Left`` into
    ``num_columns`` property columns.
    """
    out: dict[int, dict[int, tuple[str, float | None]]] = {
        i: {} for i in range(num_columns)
    }
    if num_columns <= 0:
        return out

    numeric_lines = [
        ln
        for ln in part_lines
        if _looks_like_amount(_block_text(ln)) and _bbox(ln)
    ]

    for ln in part_lines:
        line = _line_for_label(_block_text(ln))
        if line is None:
            continue
        label_box = _bbox(ln)
        if not label_box:
            continue
        band = [
            n for n in numeric_lines if _vertical_overlap(label_box, _bbox(n))
        ]
        band.sort(key=lambda b: _bbox(b).get("Left", 0.0))
        # Bucket left-to-right into num_columns slots by order.
        for idx, n in enumerate(band[:num_columns]):
            out[idx][line] = (_block_text(n).strip(), _block_conf(n))
    return out


# --- Physical address box (step c) -------------------------------------------


def _addresses_from_forms(
    blocks: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    num_columns: int,
    allowed_pages: set[int | None],
) -> dict[int, tuple[str, float | None]]:
    """Read per-column address text from the FORMS KEY_VALUE_SET pairs.

    Locates KEY blocks whose text contains an address marker, reads the paired
    VALUE text, and buckets the located address values left-to-right by ``Left``
    into ``num_columns`` columns. Scoped to ``allowed_pages`` so address boxes on
    non-Part-I pages never contribute (Req 2.1).
    """
    out: dict[int, tuple[str, float | None]] = {}
    if num_columns <= 0:
        return out

    found: list[tuple[float, str, float | None]] = []  # (left, text, conf)
    for b in blocks:
        if b.get("BlockType") != "KEY_VALUE_SET":
            continue
        if b.get("Page") not in allowed_pages:
            continue
        entity_types = b.get("EntityTypes") or []
        if "KEY" not in entity_types:
            continue
        key_text, _ = _key_value_text(b, by_id)
        if not any(m in key_text.lower() for m in _ADDRESS_KEY_MARKERS):
            continue
        for value_id in _related_ids(b, "VALUE"):
            value_block = by_id.get(value_id)
            if value_block is None:
                continue
            val_text, val_conf = _key_value_text(value_block, by_id)
            if not val_text:
                continue
            left = _bbox(value_block).get("Left", 0.0)
            found.append((left, val_text, val_conf))

    found.sort(key=lambda t: t[0])
    for idx, (_left, text, conf) in enumerate(found[:num_columns]):
        out[idx] = (text, conf)
    return out


def _addresses_from_geometry(
    part_lines: list[dict[str, Any]],
    num_columns: int,
) -> dict[int, tuple[str, float | None]]:
    """Geometry fallback for addresses: bucket address-row LINEs by ``Left``.

    Finds the address-label LINE, then buckets the non-numeric LINEs that share
    its band left-to-right into the same column positions as the amounts.
    """
    out: dict[int, tuple[str, float | None]] = {}
    if num_columns <= 0:
        return out

    label_line = None
    for ln in part_lines:
        if any(m in _block_text(ln).lower() for m in _ADDRESS_KEY_MARKERS):
            label_line = ln
            break
    if label_line is None:
        return out

    label_box = _bbox(label_line)
    if not label_box:
        return out

    band = [
        ln
        for ln in part_lines
        if ln is not label_line
        and _bbox(ln)
        and _vertical_overlap(label_box, _bbox(ln))
        and not _looks_like_amount(_block_text(ln))
        # Only keep address-like tokens: on some layouts a bare form-field
        # number (e.g. "1a") sits on the label's band and must not be read as
        # an address — the letter-row fallback supplies the real one instead.
        and _looks_like_address(_block_text(ln))
    ]
    band.sort(key=lambda b: _bbox(b).get("Left", 0.0))
    for idx, ln in enumerate(band[:num_columns]):
        out[idx] = (_block_text(ln).strip(), _block_conf(ln))
    return out


#: A LINE "looks like" a property address when it is reasonably long and mixes
#: letters with digits (a street number + name + city/state/ZIP). Used by the
#: letter-anchored fallback to tell a real address from a stray field label or
#: form number (e.g. "1a") sharing the same row band.
def _looks_like_address(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 8:
        return False
    if any(m in stripped.lower() for m in _ADDRESS_KEY_MARKERS):
        return False
    has_digit = any(ch.isdigit() for ch in stripped)
    has_alpha = sum(ch.isalpha() for ch in stripped) >= 2
    return has_digit and has_alpha


def _addresses_from_letter_rows(
    part_lines: list[dict[str, Any]],
    num_columns: int,
) -> dict[int, tuple[str, float | None]]:
    """Fallback for forms that stack addresses vertically by A/B/C row.

    Some preparers (e.g. H&R Block) emit no FORMS address key/value and lay the
    "Physical address of each property" box out as one row PER property: a
    left-margin property letter (A/B/C) with the address text on the same
    horizontal band to its right, stacked top-to-bottom — not spread across
    columns. The horizontal-band ``_addresses_from_geometry`` reader, which
    buckets tokens on the *label's* own band left-to-right, mis-reads this (it
    grabs a form number like "1a" that happens to sit beside the label).

    This reader instead anchors on the property letters: it finds the address
    label, then for each A/B/C letter appearing at/below the label in the left
    margin (in order) it pairs the single address-like LINE on that letter's own
    row band. Column *i* maps to the *i*-th letter. A letter with no address-like
    line on its band (an unused property) contributes nothing.
    """
    out: dict[int, tuple[str, float | None]] = {}
    if num_columns <= 0:
        return out

    label_line = None
    for ln in part_lines:
        if any(m in _block_text(ln).lower() for m in _ADDRESS_KEY_MARKERS):
            label_line = ln
            break
    if label_line is None:
        return out
    label_box = _bbox(label_line)
    if not label_box:
        return out
    label_top = label_box.get("Top", 0.0)
    label_left = label_box.get("Left", 0.0)

    # Left-margin property letters at/below the label, first occurrence of each,
    # in A/B/C order (keyed to column index by position).
    letters: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ln in sorted(part_lines, key=lambda b: _bbox(b).get("Top", 0.0)):
        text = _block_text(ln).strip().upper()
        box = _bbox(ln)
        if (
            text in _PROPERTY_LETTERS
            and box
            and box.get("Left", 1.0) < label_left
            and box.get("Top", 0.0) >= label_top - 0.005
            and text not in seen
        ):
            seen.add(text)
            letters.append(ln)

    def _center(box: dict[str, float]) -> float:
        return box.get("Top", 0.0) + box.get("Height", 0.0) / 2

    address_lines = [
        ln for ln in part_lines if _looks_like_address(_block_text(ln)) and _bbox(ln)
    ]

    for idx, letter in enumerate(letters[:num_columns]):
        letter_center = _center(_bbox(letter))
        best = None
        best_dist = 1e9
        for cand in address_lines:
            dist = abs(_center(_bbox(cand)) - letter_center)
            # Same printed row: a tight vertical band keeps the A address off the
            # B row (letter rows are ~0.015 apart on this form).
            if dist <= 0.012 and dist < best_dist:
                best, best_dist = cand, dist
        if best is not None:
            out[idx] = (_block_text(best).strip(), _block_conf(best))
    return out



# --- Assembly ----------------------------------------------------------------


def _build_line(
    line_no: int,
    reading: tuple[str, float | None] | None,
    min_confidence: float,
) -> ParsedLine:
    """Build a ParsedLine from a raw (text, conf) reading (None → unreadable)."""
    if reading is None:
        return ParsedLine(
            schedule_e_line=line_no,
            raw_amount="",
            confidence=None,
            needs_verification=True,
        )
    raw, conf = reading
    raw = raw.strip()
    unreadable = not raw or not _looks_like_amount(raw)
    low_conf = conf is None or conf < min_confidence
    return ParsedLine(
        schedule_e_line=line_no,
        raw_amount=raw,
        confidence=conf,
        needs_verification=unreadable or low_conf,
    )


def parse_schedule_e(
    blocks: list[dict[str, Any]], *, min_confidence: float
) -> ParsedExtraction:
    """Parse a Textract blocks list into a :class:`ParsedExtraction`.

    Args:
        blocks: The raw Textract ``Block`` dicts from ``GetDocumentAnalysis``
            (all pages already aggregated by the adapter).
        min_confidence: The confidence floor (0-100). A line/address/year with a
            contributing-block confidence below this — or that could not be
            read — is flagged ``needs_verification`` (Req 5.2, 8.3).

    Returns:
        A :class:`ParsedExtraction`. When no Schedule E Part I page is located,
        ``no_schedule_e_found`` is ``True`` and ``columns`` is empty (Req 12.2).
        Amounts are the raw read tokens; the service normalizes them to money.
    """
    if not blocks:
        return ParsedExtraction(no_schedule_e_found=True)

    by_id = _index_by_id(blocks)

    # (a) Locate Schedule E Part I page(s); ignore non-matching pages. Keep the
    # per-page grouping so every TABLE/FORMS/geometry read can be scoped to a
    # located Part I page and never scan the document globally (Req 2.1).
    grouped = _page_lines(blocks, by_id)
    part_i_pages = [
        (page_num, lines)
        for page_num, lines in grouped.items()
        if _is_part_i_page(lines)
    ]
    if not part_i_pages:
        return ParsedExtraction(no_schedule_e_found=True)

    part_lines: list[dict[str, Any]] = []
    for _page_num, lines in part_i_pages:
        part_lines.extend(lines)

    # (d) Tax year from the located page(s)' header lines.
    tax_year, year_conf, year_needs = _detect_tax_year(part_lines, min_confidence)

    # (b)+(c) Process each genuine Part I page independently and concatenate the
    # resulting columns, so the per-page A/B/C header governs the count/layout
    # and no non-Part-I page can contribute columns (Req 2.2, 2.4).
    columns: list[ParsedColumn] = []
    for page_num, lines in part_i_pages:
        columns.extend(
            _columns_for_page(blocks, by_id, page_num, lines, min_confidence)
        )

    return ParsedExtraction(
        no_schedule_e_found=False,
        tax_year=tax_year,
        tax_year_confidence=year_conf,
        tax_year_needs_verification=year_needs,
        columns=columns,
    )


def _columns_for_page(
    blocks: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    page_num: int | None,
    page_lines: list[dict[str, Any]],
    min_confidence: float,
) -> list[ParsedColumn]:
    """Build the property columns for a single located Part I page.

    Prefers the HEADER-LETTER table reader; falls back to the (page-scoped,
    capped) geometry reader when the TABLES result is weak. Addresses prefer the
    page-scoped FORMS pairs, then the geometry fallback.
    """
    # Property columns + amounts from this page's tables (header-letter aware).
    page_tables = [
        b
        for b in blocks
        if b.get("BlockType") == "TABLE" and b.get("Page") == page_num
    ]
    num_columns, table_amounts = _amounts_from_table_page(page_tables, by_id)

    # The geometry reader is a FALLBACK for a weak TABLES result, not a gap-filler
    # for a solid one. When the table reader already produced columns, an absent
    # amount is a genuine blank (flagged needs_verification) — guessing it from
    # loose LINE geometry would pull in line-number tokens and cross-column
    # bleed. So geometry only runs when TABLES gave no columns (Req 3.5).
    if num_columns > 0:
        geometry_amounts: dict[int, dict[int, tuple[str, float | None]]] = {}
    else:
        # Derive the column count from geometry — scoped to this page's lines and
        # capped at the structural maximum (Req 2.4, 3.5).
        num_columns = min(
            _infer_columns_from_geometry(page_lines), _MAX_PROPERTY_COLUMNS
        )
        geometry_amounts = _amounts_from_geometry(page_lines, by_id, num_columns)

    forms_addresses = _addresses_from_forms(
        blocks, by_id, num_columns, allowed_pages={page_num}
    )
    geometry_addresses = _addresses_from_geometry(page_lines, num_columns)
    # Vertical A/B/C-row layout fallback (e.g. H&R Block), used only where the
    # FORMS and horizontal-band readers found nothing for a column.
    letter_row_addresses = _addresses_from_letter_rows(page_lines, num_columns)

    columns: list[ParsedColumn] = []
    for col_idx in range(num_columns):
        per_line = dict(table_amounts.get(col_idx, {}))
        for line_no, reading in geometry_amounts.get(col_idx, {}).items():
            per_line.setdefault(line_no, reading)

        lines = [
            _build_line(line_no, per_line.get(line_no), min_confidence)
            for line_no in sorted(ALLOWED_LINES)
        ]

        addr_reading = (
            forms_addresses.get(col_idx)
            or geometry_addresses.get(col_idx)
            or letter_row_addresses.get(col_idx)
        )
        if addr_reading is not None:
            addr_text, addr_conf = addr_reading
            addr_text = addr_text.strip() or None
        else:
            addr_text, addr_conf = None, None
        addr_needs = (
            addr_text is None
            or addr_conf is None
            or addr_conf < min_confidence
        )

        columns.append(
            ParsedColumn(
                address_text=addr_text,
                address_confidence=addr_conf,
                address_needs_verification=addr_needs,
                lines=lines,
            )
        )
    return _prune_phantom_columns(columns)


def _is_real_property_column(column: "ParsedColumn") -> bool:
    """Return True when a detected column looks like a genuine property.

    A Schedule E Part I grid always prints three column headers (A/B/C); an
    unused header's column carries only the form's totals/summary roll-ups,
    which Textract files under that letter. Such a column has no Rents (line 3)
    and no real per-property expenses, so it is NOT a property.

    A column qualifies as real when it has a readable Rents (line 3) amount, OR
    at least :data:`_MIN_EXPENSE_LINES_FOR_PROPERTY` populated expense lines.
    Royalties (line 4) alone do NOT qualify, because the totals column's only
    populated value is the royalty roll-up; an expense-bearing royalty property
    still survives on its expense count.
    """
    populated = {
        ln.schedule_e_line
        for ln in column.lines
        if ln.raw_amount and ln.raw_amount.strip()
    }
    if 3 in populated:
        return True
    expense_hits = len(populated & _EXPENSE_LINES)
    return expense_hits >= _MIN_EXPENSE_LINES_FOR_PROPERTY


def _prune_phantom_columns(
    columns: list["ParsedColumn"],
) -> list["ParsedColumn"]:
    """Drop phantom property columns produced by the form's totals column.

    Keeps every column that :func:`_is_real_property_column` accepts. As a
    safety net, if the test would reject *every* column (e.g. an unusual grid
    where no column shows rents or enough expenses), the columns are returned
    unchanged so a sparse-but-genuine return is never emptied — the service
    still surfaces the values for human review.
    """
    kept = [c for c in columns if _is_real_property_column(c)]
    return kept if kept else columns


def _infer_columns_from_geometry(part_lines: list[dict[str, Any]]) -> int:
    """Infer the property-column count from the widest label band's numerics.

    Used only when the TABLES result gives no column count. Finds the recognized
    line-label LINE whose horizontal band carries the most numeric tokens and
    uses that count as the number of property columns (at least 1 when any
    amounts exist on the page).
    """
    numeric_lines = [
        ln
        for ln in part_lines
        if _looks_like_amount(_block_text(ln)) and _bbox(ln)
    ]
    if not numeric_lines:
        return 0

    best = 0
    for ln in part_lines:
        if _line_for_label(_block_text(ln)) is None:
            continue
        label_box = _bbox(ln)
        if not label_box:
            continue
        band = [n for n in numeric_lines if _vertical_overlap(label_box, _bbox(n))]
        best = max(best, len(band))
    return best if best > 0 else 1
