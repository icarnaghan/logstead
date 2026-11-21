# Feature: schedule-e-pdf-extraction, Property 3: Extracted amounts normalize to two-decimal money with no drift, and unreadable values are flagged, not dropped
"""Property-based test for Schedule E extraction money normalization (task 8.3).

Validates: Requirements 5.1, 5.2, 5.3, 4.6

This test drives a Hypothesis generator that BUILDS a Schedule E Part I
Textract-shaped block fixture from a randomly generated layout (random
property-column count 1-3, random per-line amount tokens drawn from clean
two-decimal money, ``$``/comma-formatted money, blanks, and garbled non-numeric
tokens, a random tax year, random addresses, and optionally a Line 18
depreciation row). The generated blocks are fed through the **real** extraction
path:

    parse_schedule_e(blocks)  ->  ExtractionService._build_review_draft(parsed)

so the service's money normalization (``util/money.to_money`` /
``money_to_str`` via ``ExtractionService._normalize_amount``) is exercised
exactly as it runs in production. No live AWS, S3, DynamoDB, or Textract is
touched — the parser is pure and the review-draft assembly is driven against an
in-memory stub property source.

The property asserts, for the generated layout:

* every CLEAN / normalizable generated amount token recovers in the draft as
  ``money_to_str(to_money(token))`` **exactly** — no precision drift (Req 5.1,
  5.3);
* every un-normalizable / garbled / blank token recovers as ``"0.00"`` with
  ``needs_verification=True`` **and** the column/line is still PRESENT, not
  dropped (Req 4.6, 5.2);
* every draft line amount is a fixed two-decimal string.

The generator doubles as a parser+normalizer round-trip over the amounts it
builds in (Req 4.1-4.4, 6.1 folded in: Part I is located, one column per
property column is produced, the allow-set lines and addresses are read, the
year is detected).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.schedule_e_extraction import (
    DEFAULT_MIN_CONFIDENCE,
    ExtractionService,
)
from logstead.services.schedule_e_parser import ALLOWED_LINES, parse_schedule_e
from logstead.util.money import money_to_str, to_money

# The subset of allow-set lines the generator lays out as table rows. Keeping a
# fixed, label-recognizable subset (each maps cleanly through the parser's
# _LABEL_TO_LINE) makes the round-trip deterministic while still covering income
# (3,4), expense (5,7,9,14,17), and Other (19). Line 18 is laid out separately
# (optionally) and must never recover.
_LINE_LABELS: dict[int, str] = {
    3: "Rents received",
    4: "Royalties received",
    5: "Advertising",
    7: "Cleaning and maintenance",
    9: "Insurance",
    14: "Repairs",
    17: "Utilities",
    19: "Other",
}

_TWO_DECIMAL_RE = re.compile(r"^-?\d+\.\d{2}$")


# --- A stub property source so _build_review_draft needs no AWS ----------------


class _NoProperties:
    """Minimal stand-in for PropertyService used by _build_review_draft.

    ``_build_review_draft`` only calls ``.list()`` on the property source (as the
    fuzzy-match candidate set). Returning an empty list keeps the test focused on
    money normalization while still exercising the real address → best_match path
    (which simply yields no suggestion against zero candidates).
    """

    def list(self) -> list[Any]:
        return []


def _service() -> ExtractionService:
    """Build an ExtractionService without AWS collaborators.

    The money-normalization path (``_build_review_draft`` → ``_normalize_amount``
    → ``to_money`` / ``money_to_str``) touches only ``self._properties.list()``,
    so the instance is constructed bypassing ``__init__`` with just that one
    collaborator stubbed. No S3/DynamoDB/Textract client is created.
    """
    svc = ExtractionService.__new__(ExtractionService)
    svc._properties = _NoProperties()  # type: ignore[attr-defined]
    return svc


# --- Amount-token generators (categorized by expected normalization outcome) ---


def _is_normalizable(token: str) -> bool:
    """True when the extraction path will normalize ``token`` to real money.

    Mirrors ``ExtractionService._normalize_amount`` + ``_clean_money_token``:
    strip ``$``/commas, convert ``(x)`` to ``-x``, then require ``to_money`` to
    accept it. Used by the test oracle (not the production code) to classify each
    generated token.
    """
    text = token.strip()
    if not text:
        return False
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = text.replace("$", "").replace(",", "").strip()
    if negative and text and not text.startswith("-"):
        text = f"-{text}"
    try:
        to_money(text)
    except (ValueError, TypeError):
        return False
    return True


def _expected_amount(token: str) -> str:
    """The exact two-decimal string the draft should carry for ``token``.

    Recomputes the production normalization independently so the assertion is a
    true round-trip oracle rather than a tautology.
    """
    text = token.strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = text.replace("$", "").replace(",", "").strip()
    if negative and text and not text.startswith("-"):
        text = f"-{text}"
    return money_to_str(to_money(text))


# Clean two-decimal money, e.g. "0.00", "1234.56" (from a quantized Decimal).
_clean_money = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("99999999"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")

# Whole-dollar integers, e.g. "24000", "0" (OCR often drops trailing ".00").
_whole_dollar = st.integers(min_value=0, max_value=99_999_999).map(str)

# Money with a leading "$" and grouping commas, e.g. "$24,000.00", "$1,875.50".
_formatted_money = st.integers(min_value=0, max_value=99_999_999).map(
    lambda n: f"${n:,}.{n % 100:02d}"
)

# Blank / whitespace tokens — the "unreadable" (absent) case.
_blank = st.sampled_from(["", "   ", "\t"])

# Garbled, non-numeric OCR tokens — the "unreadable" (un-normalizable) case.
_garbled = st.sampled_from(
    ["l2O", "n/a", "N/A", "--", "???", "O.OO", "abc", "$--", "(bad)", "12.3.4"]
)

# A per-cell amount token: a random mix across all categories.
_amount_token = st.one_of(
    _clean_money, _whole_dollar, _formatted_money, _blank, _garbled
)

# A per-cell token that is never blank (used for Line 3 Rents).
_non_blank_amount_token = st.one_of(
    _clean_money, _whole_dollar, _formatted_money, _garbled
)

# A random US-ish street address per column.
_address = st.builds(
    lambda num, street, kind: f"{num} {street} {kind}",
    st.integers(min_value=1, max_value=9999),
    st.sampled_from(["Maple", "Oak", "Elm", "Pine", "Cedar", "Birch"]),
    st.sampled_from(["Street", "Avenue", "Road", "Lane", "Drive"]),
)

_year = st.integers(min_value=2000, max_value=2099)

# Column count 1-3.
_column_count = st.integers(min_value=1, max_value=3)


@st.composite
def _layouts(draw: st.DrawFn) -> dict[str, Any]:
    """Draw a full Schedule E Part I layout to render as Textract blocks.

    Returns a dict carrying the chosen column count, year, per-column addresses,
    per-(column, line) amount tokens for the laid-out allow-set subset, and an
    optional Line 18 (Depreciation) row with its own tokens.
    """
    num_columns = draw(_column_count)
    year = draw(_year)
    addresses = [draw(_address) for _ in range(num_columns)]

    # Per-(column, line) tokens for the laid-out subset of allow-set lines.
    amounts: dict[int, list[str]] = {}
    for line in _LINE_LABELS:
        # Line 3 (Rents) always carries a token. The parser prunes a column with
        # no Rents and fewer than two expense lines as the form's phantom totals
        # column (_prune_phantom_columns), so a blank Rents cell could drop a
        # generated property and break the one-column-per-property check.
        token = _non_blank_amount_token if line == 3 else _amount_token
        amounts[line] = [draw(token) for _ in range(num_columns)]

    include_line_18 = draw(st.booleans())
    line_18_tokens = (
        [draw(_amount_token) for _ in range(num_columns)]
        if include_line_18
        else []
    )

    return {
        "num_columns": num_columns,
        "year": year,
        "addresses": addresses,
        "amounts": amounts,
        "include_line_18": include_line_18,
        "line_18_tokens": line_18_tokens,
    }


# --- Textract-shaped block fixture builder -------------------------------------


def _word(wid: str, text: str, conf: float) -> dict[str, Any]:
    return {"Id": wid, "BlockType": "WORD", "Text": text, "Confidence": conf}


def _cell(
    cid: str, row: int, col: int, child_id: str, conf: float
) -> dict[str, Any]:
    return {
        "Id": cid,
        "BlockType": "CELL",
        "RowIndex": row,
        "ColumnIndex": col,
        "Confidence": conf,
        "Relationships": [{"Type": "CHILD", "Ids": [child_id]}],
    }


def _build_blocks(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Render a drawn layout into a Textract GetDocumentAnalysis-shaped block list.

    Mirrors the hand-built ``clean_two_columns.json`` fixture structure: a PAGE
    with LINE children (title, "For calendar year YYYY", the address label +
    per-column address LINEs, and the line-label LINEs), a FORMS address
    KEY_VALUE_SET with one VALUE per column, and a TABLE whose column 1 carries
    the recognizable line labels and columns 2..(n+1) carry each property
    column's amount token. High confidence (98-99) is used throughout so
    needs_verification is driven only by (un)readability, isolating the money
    normalization behavior under test.
    """
    num_columns = layout["num_columns"]
    year = layout["year"]
    addresses = layout["addresses"]
    amounts = layout["amounts"]

    conf = 99.0
    blocks: list[dict[str, Any]] = []

    # --- PAGE + header/label LINEs --------------------------------------------
    line_child_ids: list[str] = ["ttl", "cal", "parti", "addr-lbl"]

    blocks.append(
        {
            "Id": "ttl",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "SCHEDULE E (Form 1040) Supplemental Income and Loss",
            "Confidence": conf,
            "Geometry": {
                "BoundingBox": {"Left": 0.05, "Top": 0.02, "Width": 0.5, "Height": 0.02}
            },
        }
    )
    blocks.append(
        {
            "Id": "cal",
            "BlockType": "LINE",
            "Page": 1,
            "Text": f"For calendar year {year}",
            "Confidence": conf,
            "Geometry": {
                "BoundingBox": {"Left": 0.70, "Top": 0.02, "Width": 0.2, "Height": 0.02}
            },
        }
    )
    blocks.append(
        {
            "Id": "parti",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "Part I Income or Loss From Rental Real Estate and Royalties",
            "Confidence": conf,
            "Geometry": {
                "BoundingBox": {"Left": 0.05, "Top": 0.08, "Width": 0.6, "Height": 0.02}
            },
        }
    )
    blocks.append(
        {
            "Id": "addr-lbl",
            "BlockType": "LINE",
            "Page": 1,
            "Text": "1a Physical address of each property",
            "Confidence": conf,
            "Geometry": {
                "BoundingBox": {"Left": 0.05, "Top": 0.14, "Width": 0.3, "Height": 0.02}
            },
        }
    )

    # Per-column address LINEs (geometry fallback source) + FORMS values.
    addr_value_ids: list[str] = []
    for idx in range(num_columns):
        left = 0.45 + idx * 0.18
        addr_line_id = f"addr-line-{idx}"
        blocks.append(
            {
                "Id": addr_line_id,
                "BlockType": "LINE",
                "Page": 1,
                "Text": addresses[idx],
                "Confidence": conf,
                "Geometry": {
                    "BoundingBox": {
                        "Left": left,
                        "Top": 0.14,
                        "Width": 0.15,
                        "Height": 0.02,
                    }
                },
            }
        )
        line_child_ids.append(addr_line_id)

        # FORMS VALUE block for this column's address (preferred address path).
        val_id = f"addr-val-{idx}"
        word_ids: list[str] = []
        for w_i, word in enumerate(addresses[idx].split()):
            wid = f"{val_id}-w{w_i}"
            blocks.append(_word(wid, word, conf))
            word_ids.append(wid)
        blocks.append(
            {
                "Id": val_id,
                "BlockType": "KEY_VALUE_SET",
                "EntityTypes": ["VALUE"],
                "Page": 1,
                "Confidence": conf,
                "Geometry": {
                    "BoundingBox": {
                        "Left": left,
                        "Top": 0.14,
                        "Width": 0.15,
                        "Height": 0.02,
                    }
                },
                "Relationships": [{"Type": "CHILD", "Ids": word_ids}],
            }
        )
        addr_value_ids.append(val_id)

    # FORMS address KEY block pairing all per-column VALUE blocks.
    blocks.append(_word("addr-key-w1", "Physical", conf))
    blocks.append(_word("addr-key-w2", "address", conf))
    blocks.append(
        {
            "Id": "addr-key",
            "BlockType": "KEY_VALUE_SET",
            "EntityTypes": ["KEY"],
            "Page": 1,
            "Confidence": conf,
            "Relationships": [
                {"Type": "CHILD", "Ids": ["addr-key-w1", "addr-key-w2"]},
                {"Type": "VALUE", "Ids": addr_value_ids},
            ],
        }
    )

    # Line-label LINEs (so the page passes the Part I marker + label test).
    laid_out_lines = list(_LINE_LABELS)
    if layout["include_line_18"]:
        laid_out_lines = laid_out_lines + [18]

    top = 0.30
    for line in laid_out_lines:
        label = _LINE_LABELS.get(line, "Depreciation expense or depletion")
        lbl_id = f"lbl-{line}"
        blocks.append(
            {
                "Id": lbl_id,
                "BlockType": "LINE",
                "Page": 1,
                "Text": f"{line} {label}",
                "Confidence": conf,
                "Geometry": {
                    "BoundingBox": {
                        "Left": 0.05,
                        "Top": top,
                        "Width": 0.3,
                        "Height": 0.02,
                    }
                },
            }
        )
        line_child_ids.append(lbl_id)
        top += 0.03

    blocks.insert(
        0,
        {
            "Id": "page-1",
            "BlockType": "PAGE",
            "Page": 1,
            "Relationships": [{"Type": "CHILD", "Ids": line_child_ids}],
        },
    )

    # --- TABLE: col 1 = labels, cols 2..(n+1) = per-column amount tokens -------
    table_child_ids: list[str] = []
    row_index = 0
    for line in laid_out_lines:
        row_index += 1
        label = _LINE_LABELS.get(line, "Depreciation expense or depletion")

        label_word_id = f"tw-{line}-l"
        label_cell_id = f"tc-{line}-l"
        blocks.append(_word(label_word_id, label, conf))
        blocks.append(_cell(label_cell_id, row_index, 1, label_word_id, conf))
        table_child_ids.append(label_cell_id)

        tokens = (
            layout["line_18_tokens"]
            if line == 18
            else amounts[line]
        )
        for col_idx in range(num_columns):
            token = tokens[col_idx]
            word_id = f"tw-{line}-c{col_idx}"
            cell_id = f"tc-{line}-c{col_idx}"
            # An empty/whitespace token → a cell with no WORD child (absent read).
            if token.strip():
                blocks.append(_word(word_id, token, conf))
                child_ids = [word_id]
            else:
                child_ids = []
            blocks.append(
                {
                    "Id": cell_id,
                    "BlockType": "CELL",
                    "RowIndex": row_index,
                    "ColumnIndex": col_idx + 2,
                    "Confidence": conf,
                    "Relationships": [{"Type": "CHILD", "Ids": child_ids}],
                }
            )
            table_child_ids.append(cell_id)

    blocks.append(
        {
            "Id": "table-1",
            "BlockType": "TABLE",
            "Page": 1,
            "Confidence": conf,
            "Relationships": [{"Type": "CHILD", "Ids": table_child_ids}],
        }
    )

    return blocks


# --- The property --------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(layout=_layouts())
def test_amounts_normalize_to_two_decimal_money_without_drift(
    layout: dict[str, Any],
) -> None:
    """Property 3: amounts normalize with no drift; unreadable → "0.00" + flagged, kept.

    Validates: Requirements 5.1, 5.2, 5.3, 4.6
    """
    blocks = _build_blocks(layout)

    parsed = parse_schedule_e(blocks, min_confidence=DEFAULT_MIN_CONFIDENCE)
    assert parsed.no_schedule_e_found is False

    draft = _service()._build_review_draft(parsed)

    # One column per generated property column — nothing dropped (Req 5.2).
    assert len(draft.columns) == layout["num_columns"]

    for col_idx, column in enumerate(draft.columns):
        by_line = {ln.schedule_e_line: ln for ln in column.lines}

        # Every column covers exactly the allow-set — Line 18 never appears.
        assert set(by_line) == set(ALLOWED_LINES)
        assert 18 not in by_line

        for line, label in _LINE_LABELS.items():
            draft_line = by_line[line]
            token = layout["amounts"][line][col_idx]

            # Every draft amount is a fixed two-decimal string (Req 5.3).
            assert _TWO_DECIMAL_RE.match(draft_line.amount), (
                f"line {line} amount {draft_line.amount!r} is not two-decimal"
            )

            if _is_normalizable(token):
                # Clean/formatted token round-trips with no precision drift
                # (Req 5.1): the draft equals money_to_str(to_money(token)).
                assert draft_line.amount == _expected_amount(token), (
                    f"drift: token {token!r} -> {draft_line.amount!r}, "
                    f"expected {_expected_amount(token)!r}"
                )
            else:
                # Blank/garbled token: "0.00" + flagged, column still present
                # (Req 4.6, 5.2).
                assert draft_line.amount == "0.00", (
                    f"unreadable token {token!r} did not become 0.00: "
                    f"{draft_line.amount!r}"
                )
                assert draft_line.needs_verification is True

        # Lines the generator did not lay out are still present as "0.00"
        # placeholders (absent allowed line → kept, flagged) — never dropped.
        for line in ALLOWED_LINES - set(_LINE_LABELS):
            placeholder = by_line[line]
            assert placeholder.amount == "0.00"
            assert placeholder.needs_verification is True
