"""Unit tests for the pure Schedule E Part I parser (task 3.5).

Driven entirely by CANNED Textract-response JSON fixtures under
``tests/services/fixtures/schedule_e_parser/`` — live Amazon Textract is never
called. The fixtures are hand-built, minimal approximations of real
``GetDocumentAnalysis`` output; real Textract blocks carry far more structure.
Because the governing principle is *extraction proposes, the human confirms,
layer 1 persists*, an approximate pre-fill is acceptable: every value is
surfaced for review.

Coverage (requirement clauses in parentheses):

* Part I located and non-Schedule-E pages ignored (4.1).
* One :class:`ParsedColumn` per property column (4.2).
* Income lines 3-4, expense lines 5-17, and Line 19 read, plus the per-column
  address box (4.3, 4.4).
* Line 18 (Depreciation) is **never** present in any column (4.5).
* An absent/unreadable allowed line → empty raw token + ``needs_verification``
  (the service renders this as ``"0.00"``) (4.6).
* Tax year detected when present, unset + flagged when absent (6.1, 6.2).
* The no-Schedule-E fixture → ``no_schedule_e_found`` with no columns (12.2).
* Low-confidence values flagged ``needs_verification`` (5.2, 8.3).
"""

from __future__ import annotations

import json
from pathlib import Path

from logstead.services.schedule_e_parser import (
    ALLOWED_LINES,
    ParsedColumn,
    ParsedExtraction,
    ParsedLine,
    _is_real_property_column,
    parse_schedule_e,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "schedule_e_parser"


def _load(name: str) -> list[dict]:
    """Load a canned Textract blocks list from a fixture JSON file."""
    data = json.loads((_FIXTURES / name).read_text())
    return data["blocks"]


def _parse(name: str, *, min_confidence: float = 80.0) -> ParsedExtraction:
    return parse_schedule_e(_load(name), min_confidence=min_confidence)


def _lines_by_number(column) -> dict[int, object]:
    return {ln.schedule_e_line: ln for ln in column.lines}


# --- Clean, two-column Schedule E Part I (TABLES + FORMS paths) --------------


def test_clean_locates_part_i_and_detects_year():
    """Part I is located and the calendar year is detected (4.1, 6.1)."""
    result = _parse("clean_two_columns.json")

    assert result.no_schedule_e_found is False
    assert result.tax_year == 2023
    assert result.tax_year_needs_verification is False


def test_clean_one_column_per_property_column():
    """Exactly one column per property column A/B is produced (4.2)."""
    result = _parse("clean_two_columns.json")
    assert len(result.columns) == 2


def test_clean_reads_income_expense_and_other_lines():
    """Lines 3-4 (income), 5-17 (expense), and 19 (Other) are read (4.3)."""
    result = _parse("clean_two_columns.json")
    col_a = _lines_by_number(result.columns[0])

    assert col_a[3].raw_amount == "24000"
    assert col_a[4].raw_amount == "0"
    assert col_a[5].raw_amount == "350.00"
    assert col_a[14].raw_amount == "1875.50"
    assert col_a[19].raw_amount == "120.00"

    col_b = _lines_by_number(result.columns[1])
    assert col_b[3].raw_amount == "18500"
    assert col_b[14].raw_amount == "640.00"
    assert col_b[19].raw_amount == "60.00"


def test_clean_reads_address_box_per_column():
    """Each column's physical-address box is read via FORMS (4.4)."""
    result = _parse("clean_two_columns.json")

    assert result.columns[0].address_text == "12 Maple Street"
    assert result.columns[1].address_text == "90 Oak Avenue"
    assert result.columns[0].address_needs_verification is False


def test_clean_every_column_covers_the_full_allow_set():
    """Each column carries exactly the allow-set lines — never Line 18 (4.5)."""
    result = _parse("clean_two_columns.json")
    for column in result.columns:
        numbers = {ln.schedule_e_line for ln in column.lines}
        assert numbers == set(ALLOWED_LINES)


def test_line_18_never_present_despite_depreciation_in_document():
    """A Line 18 amount in the document is never carried into any column (4.5).

    The clean fixture deliberately includes a Line 18 (Depreciation) table row
    with amounts 9999.99 / 8888.88; those must appear nowhere in the result.
    """
    result = _parse("clean_two_columns.json")
    for column in result.columns:
        assert all(ln.schedule_e_line != 18 for ln in column.lines)
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "9999.99" not in raw_values
        assert "8888.88" not in raw_values


def test_unreadable_allowed_line_is_empty_and_flagged():
    """An allowed line with no reading → empty token + needs_verification (4.6).

    Line 6 (Auto and travel) has no cell/token in the clean fixture, so it must
    still be present (allow-set coverage) with an empty raw amount flagged for
    verification. The service renders this as "0.00".
    """
    result = _parse("clean_two_columns.json")
    col_a = _lines_by_number(result.columns[0])

    assert col_a[6].raw_amount == ""
    assert col_a[6].needs_verification is True


def test_clean_amounts_carry_confidence():
    """Each read line carries its contributing block confidence (6.3, 8.3)."""
    result = _parse("clean_two_columns.json")
    col_a = _lines_by_number(result.columns[0])

    assert col_a[3].confidence == 98.3
    assert col_a[3].needs_verification is False


# --- No Schedule E in the document ------------------------------------------


def test_no_schedule_e_fixture_yields_no_columns():
    """A non-Schedule-E page → no_schedule_e_found with no columns (12.2)."""
    result = _parse("no_schedule_e.json")

    assert result.no_schedule_e_found is True
    assert result.columns == []


def test_empty_blocks_yields_no_schedule_e():
    """An empty blocks list is treated as no Schedule E found (12.2)."""
    result = parse_schedule_e([], min_confidence=80.0)
    assert result.no_schedule_e_found is True
    assert result.columns == []


# --- Low-confidence / garbled Schedule E Part I (geometry fallback) ---------


def test_low_confidence_still_locates_part_i():
    """A low-confidence page still matches the Part I markers (4.1)."""
    result = _parse("low_confidence.json")
    assert result.no_schedule_e_found is False
    assert len(result.columns) == 1


def test_low_confidence_values_flagged_needs_verification():
    """Below-min_confidence readings are flagged needs_verification (5.2, 8.3)."""
    result = _parse("low_confidence.json")
    col = _lines_by_number(result.columns[0])

    # Rents read via the geometry fallback, but at confidence 42 < 80.
    assert col[3].raw_amount == "12000"
    assert col[3].needs_verification is True

    # Insurance read at confidence 48 < 80.
    assert col[9].raw_amount == "800.00"
    assert col[9].needs_verification is True


def test_low_confidence_garbled_amount_is_flagged():
    """A garbled, non-numeric token for Line 5 is flagged for verification."""
    result = _parse("low_confidence.json")
    col = _lines_by_number(result.columns[0])

    # "l2O" is not a readable amount → flagged (the service maps it to "0.00").
    assert col[5].needs_verification is True


def test_low_confidence_absent_year_is_unset_and_flagged():
    """No detectable year → tax_year unset and flagged (6.2)."""
    result = _parse("low_confidence.json")
    assert result.tax_year is None
    assert result.tax_year_needs_verification is True


def test_low_confidence_still_covers_full_allow_set_without_line_18():
    """Even on a garbled page every column spans the allow-set, never 18 (4.5)."""
    result = _parse("low_confidence.json")
    numbers = {ln.schedule_e_line for ln in result.columns[0].lines}
    assert numbers == set(ALLOWED_LINES)
    assert 18 not in numbers


# --- Bug regression: real-return structure (header letters, non-contiguous) --
#
# Property 1: Bug Condition - Header-letter column count and span-scoped amounts.
#
# The ``real_return_scrubbed.json`` fixture is a hand-built, SCRUBBED, minimized
# approximation of the real 30-page capture that triggered the over-counting
# bug. ALL VALUES ARE FAKE — no real PII. It reproduces the structure that
# broke the parser:
#   * page 13: the genuine Schedule E Part I grid — a "Properties:" header row,
#     A/B/C column letters at NON-CONTIGUOUS table columns 4/6/8, line labels in
#     COLUMN 2 (not 1), line numbers in columns 1 and 3, allow-set rows whose
#     amounts land in each property's span (A at col 4 OR col 5), a Line 18
#     (Depreciation) row that must be excluded, and fake addresses;
#   * page 16: an unrelated WIDE 11-column worksheet TABLE (the globally widest);
#   * page 12: a Schedule C page sharing generic expense labels but with neither
#     "rents received" nor an A/B/C header, so it must NOT be treated as Part I.
#
# On the UNFIXED parser this test FAILS: the document-global width heuristic
# reports ~10 phantom columns from page 16, the contiguous 2..N assumption reads
# the wrong cells, and the loose locator false-matches the Schedule C page.


def test_real_return_detects_two_properties_pruning_phantom_totals_column():
    """Two real properties, not three: the totals column is pruned (2.1-2.4).

    The IRS form prints three column headers (A/B/C at cols 4/6/8), so header
    detection finds three letters. But C is the form's totals/summary column:
    it has no Rents (line 3) and no real per-property expenses, only a royalty
    roll-up and a stray line-19 echo. It must be pruned, leaving A and B.

    Must FAIL on the unfixed parser, which reported the globally widest table's
    width (the 11-column worksheet on page 16), and would still over-count by
    emitting the phantom C before pruning was added.
    """
    result = _parse("real_return_scrubbed.json")
    assert result.no_schedule_e_found is False
    assert len(result.columns) == 2


def test_real_return_amounts_read_from_ab_spans():
    """Amounts read from each real property's span (2.2).

    Property A owns cols 4-5, B owns cols 6-7. Rents (line 3) has A at col 4 and
    B at col 6; Insurance (line 9) has A at col 5 and B at col 7; Repairs (line
    14) has A at col 5; Other (line 19) has A at col 4. The phantom C column
    (col 8) is pruned, so only two columns remain.
    """
    result = _parse("real_return_scrubbed.json")
    assert len(result.columns) == 2
    col_a = _lines_by_number(result.columns[0])
    col_b = _lines_by_number(result.columns[1])

    assert col_a[3].raw_amount == "11000"
    assert col_b[3].raw_amount == "12000"

    assert col_a[9].raw_amount == "686"
    assert col_b[9].raw_amount == "253"

    assert col_a[14].raw_amount == "60"
    assert col_a[19].raw_amount == "1496"


def test_real_return_rows_anchored_to_printed_line_number():
    """Each amount lands on the line printed in the row, not a fuzzy label match.

    The totals row (form line 21, "Subtract line 20 from line 3 (rents) and/or 4
    (royalties)") carries fake amounts 9999 (A span) and 8888 (B span). A reader
    that mapped rows by label text would match "rents"/"royalties" and overwrite
    line 3 or 4. The fixed reader anchors on the printed line number in column 1
    ("21", not an allow-set line) and skips the row, so neither value appears and
    the real line 3 rents survive.
    """
    result = _parse("real_return_scrubbed.json")
    assert len(result.columns) == 2
    for column in result.columns:
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "9999" not in raw_values
        assert "8888" not in raw_values
    col_a = _lines_by_number(result.columns[0])
    col_b = _lines_by_number(result.columns[1])
    assert col_a[3].raw_amount == "11000"
    assert col_b[3].raw_amount == "12000"
    # Line 4 (Royalties) was never a real per-property value here; the totals
    # row did not leak into it.
    assert col_a[4].raw_amount == ""
    assert col_b[4].raw_amount == ""


def test_real_return_phantom_totals_column_value_excluded():
    """The totals column's roll-up values never appear as a property (2.4).

    The pruned C column carried a royalty total ("500") and a stray line-19
    echo ("976"); neither should surface in any kept property column.
    """
    result = _parse("real_return_scrubbed.json")
    for column in result.columns:
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "500" not in raw_values
        assert "976" not in raw_values


def test_real_return_excludes_line_18_depreciation():
    """The Line 18 (Depreciation) row's fake amounts appear in no column (2.4)."""
    result = _parse("real_return_scrubbed.json")
    for column in result.columns:
        assert all(ln.schedule_e_line != 18 for ln in column.lines)
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "7777" not in raw_values
        assert "6666" not in raw_values


def test_real_return_ignores_schedule_c_and_wide_worksheet():
    """Only page 13 contributes; Schedule C (12) and the worksheet (16) do not.

    If the Schedule C page or the wide worksheet contributed, the column count
    or the per-column amounts would be wrong. The 2-column assertion plus the
    span-scoped amount assertions above together prove no non-Part-I page leaks
    in; here we additionally confirm the detected year comes from page 13.
    """
    result = _parse("real_return_scrubbed.json")
    assert len(result.columns) == 2
    assert result.tax_year == 2023
    # No worksheet header text ("Cost", "Method", ...) ever becomes an address.
    for column in result.columns:
        assert column.address_text != "Depreciation and Amortization Worksheet"



# --- Phantom-column pruning rule (unit-level) -------------------------------


def _column(**raw_by_line: str) -> ParsedColumn:
    """Build a ParsedColumn whose given lines carry a raw amount (rest blank)."""
    lines = [
        ParsedLine(
            schedule_e_line=n,
            raw_amount=raw_by_line.get(str(n), ""),
            confidence=99.0 if str(n) in raw_by_line else None,
            needs_verification=str(n) not in raw_by_line,
        )
        for n in sorted(ALLOWED_LINES)
    ]
    return ParsedColumn(
        address_text=None,
        address_confidence=None,
        address_needs_verification=True,
        lines=lines,
    )


def test_real_property_kept_when_it_has_rents():
    """A column with Rents (line 3) is a real property, even with no expenses."""
    assert _is_real_property_column(_column(**{"3": "21000"})) is True


def test_royalty_only_property_with_expenses_is_kept():
    """A royalty-only property survives on its expense lines (no false prune).

    This is the edge case the pruning rule must NOT drop: a property with no
    rents but genuine per-property expenses is real.
    """
    col = _column(**{"4": "674", "9": "250", "16": "80"})
    assert _is_real_property_column(col) is True


def test_totals_column_is_pruned():
    """A column with no rents and only a royalty roll-up is a phantom (dropped).

    This mirrors the IRS form's totals column: a single line-4 royalty total
    and nothing else qualifying — fewer than two expense lines, no rents.
    """
    col = _column(**{"4": "674", "19": "976"})
    assert _is_real_property_column(col) is False


# --- Staggered multi-table layout (H&R Block) regression --------------------
#
# ``hrblock_staggered_scrubbed.json`` is a minimal, hand-built, SCRUBBED
# approximation (all amounts/addresses FAKE) of the layout a real H&R Block
# 2019 return produced via Textract. It reproduces the structural signature
# that broke extraction:
#
#   * the Part I page carries a WIDE but data-free sibling table (the Yes/No
#     questionnaire) alongside the real Schedule E grid, and
#   * the real grid prints its line number in column 3 (not column 1), with the
#     A/B/C property headers at non-adjacent columns (4/6/8) and the amounts
#     staggered across spacer columns.
#
# Before the fix, the table selector ranked candidate tables by column count
# first, so the wider questionnaire table (read via the contiguous
# ``max_col - 1`` path, ncols=4, zero amounts) shadowed the real grid — the
# draft showed phantom columns with all-zero values. The selector now ranks by
# populated amount cells first, so the real grid always wins.


def test_hrblock_staggered_selects_real_grid_not_wide_sibling():
    """The data-bearing grid wins over a wider, empty sibling table."""
    result = _parse("hrblock_staggered_scrubbed.json")

    assert result.no_schedule_e_found is False
    assert result.tax_year == 2019
    # Exactly the two genuine property columns (A, B); the empty C and the
    # questionnaire table contribute nothing.
    assert len(result.columns) == 2


def test_hrblock_staggered_reads_amounts_not_zeros():
    """Each property column carries its real staggered amounts (not all 0.00)."""
    result = _parse("hrblock_staggered_scrubbed.json")

    col_a = _lines_by_number(result.columns[0])
    col_b = _lines_by_number(result.columns[1])
    # Rents (line 3) and a spread of expenses are read from the staggered cells.
    assert col_a[3].raw_amount == "12000."
    assert col_b[3].raw_amount == "9000."
    assert col_a[12].raw_amount == "4000."
    assert col_b[12].raw_amount == "3000."
    # At least the populated lines carry a real amount — not every line is blank.
    populated_a = [ln for ln in result.columns[0].lines if ln.raw_amount.strip()]
    assert len(populated_a) >= 8


def test_hrblock_staggered_excludes_line_18_depreciation():
    """The Line 18 (Depreciation) row's fake amounts appear in no column."""
    result = _parse("hrblock_staggered_scrubbed.json")

    for column in result.columns:
        assert all(ln.schedule_e_line != 18 for ln in column.lines)
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "9999." not in raw_values
        assert "8888." not in raw_values


def test_hrblock_staggered_reads_vertical_abc_addresses():
    """Addresses laid out as vertical A/B/C rows (no FORMS key) are read.

    This layout has no FORMS address key/value; the "Physical address of each
    property" box is one row per property (a left-margin letter with the address
    text on the same band). The horizontal-band reader must not grab the stray
    form number ("1a") beside the label, and the letter-row fallback supplies
    the real address for each column.
    """
    result = _parse("hrblock_staggered_scrubbed.json")

    assert len(result.columns) == 2
    assert result.columns[0].address_text == "123 FAKE STREET SPRINGFIELD IL 62704"
    assert (
        result.columns[1].address_text
        == "456 SAMPLE AVENUE APT 2 SHELBYVILLE IL 62565"
    )
    # The stray field number on the label band is never read as an address.
    for column in result.columns:
        assert column.address_text != "1a"


def test_hrblock_staggered_totals_row_not_mapped_to_royalties():
    """A cross-referencing totals row (line 21) must not land on line 4.

    Line 21's label — "Subtract line 20 from line 3 (rents) and/or 4
    (royalties)" — mentions "royalties", which the label fallback would map to
    line 4, overwriting the real (0.00) royalties with the line-21 amount. The
    bare line number "21" in the row's narrow column is authoritative and out of
    the allow-set, so the whole row is skipped and royalties stays as read.
    """
    result = _parse("hrblock_staggered_scrubbed.json")

    for column in result.columns:
        by_line = _lines_by_number(column)
        # Royalties keeps its real "0." — not the line-21 total (3800./1750.).
        assert by_line[4].raw_amount == "0."
        # The totals rows (20, 21, 22) never appear as read lines.
        for totals_line in (20, 21, 22):
            assert all(ln.schedule_e_line != totals_line for ln in column.lines)
        # And the line-21 amounts never surface anywhere in the column.
        raw_values = {ln.raw_amount for ln in column.lines}
        assert "3800." not in raw_values
        assert "1750." not in raw_values
