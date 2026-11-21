# Schedule E Parser Columns Bugfix Design

## Overview

The pure Schedule E Part I parser (`backend/src/logstead/services/schedule_e_parser.py`)
turns an Amazon Textract blocks list into a `ParsedExtraction` of property columns and
per-line amounts. On a real 30-page return (20,473 blocks) it reported **10 property
columns** for a Schedule E that has **3** (A, B, C on page 13).

The fix retargets column detection from a document-global table-width heuristic to a
**header-letter detection** scoped to the located Schedule E Part I page(s), and tightens
the page locator so Schedule C / worksheet pages that merely share generic expense labels
are rejected. The parser stays pure (standard-library only, AWS-free) and keeps emitting
raw OCR tokens — money normalization remains the service's job.

The fix is targeted and minimal: it rewrites the column-counting and amount-reading
internals and the page-location predicate, and scopes every table/forms/geometry read to
the Part I page(s). The public surface (`parse_schedule_e`, `ParsedExtraction`,
`ParsedColumn`, `ParsedLine`, `ALLOWED_LINES`) and the money/confidence/`needs_verification`
contract are unchanged.

## Glossary

- **Bug_Condition (C)**: The document contains a genuine Schedule E Part I page whose
  property columns must be derived from A/B/C header letters, AND at least one of the four
  root-cause triggers holds (a wider table on a non-Part-I page, non-contiguous Part I
  headers, a shared-label page false-match, or a located column count > 3).
- **Property (P)**: For every buggy input the fixed parser yields exactly as many columns
  as A/B/C header letters present on the genuine Part I page(s), reads each amount from the
  property's own header-letter column span, carries no Line 18, and lets no non-Part-I page
  contribute columns.
- **Preservation**: The clean contiguous `clean_two_columns.json` path, the Line 18
  exclusion / allow-set `{3,4,5-17,19}`, the no-Schedule-E outcome, the raw-token +
  confidence + `needs_verification` behavior (money normalized by the service), the geometry
  fallback, and tax-year + address reading all behave as before for non-buggy inputs.
- **`parse_schedule_e` / F / F'**: The parser entry point. F is the original (unfixed)
  function; F' is the fixed function.
- **Part I page**: A page whose LINE text carries a Schedule E title marker **and**
  Schedule-E-specific evidence ("rents received"), distinguishing it from Schedule C.
- **Header-letter row**: The table row (under the "Properties:" header) whose cells contain
  the single-letter property labels A, B, C.
- **Property column span**: The contiguous range of table ColumnIndexes a property owns —
  from its header-letter column up to (but excluding) the next header letter's column.
- **Allow-set**: `{3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 19}` — never 18.

## Bug Details

### Bug Condition

The bug manifests when a multi-page return's Schedule E Part I page uses the real IRS layout
(property-letter headers at non-contiguous table columns) and the document also contains
wider unrelated tables and/or a Schedule C page that shares generic expense labels. The
parser's column source (`_column_count_from_tables`) scans **every** TABLE in the document
and takes `max_col - 1` of the globally widest one; its amount reader
(`_amounts_from_table`) assumes labels live in column 1 and property amounts occupy
contiguous columns `2..N`; and its page locator (`_is_part_i_page`) accepts any page with a
title marker plus any two generic line labels.

**Formal Specification:**
```
FUNCTION isBugCondition(blocks)
  INPUT: blocks of type list of Textract Block
  OUTPUT: boolean

  RETURN existsPartIPageWithLetterHeaders(blocks)
         AND (
              widestTableIsOnNonPartIPage(blocks)   // Root cause 1: global width
           OR partIHeadersAreNonContiguous(blocks)   // Root cause 2: cols 4/6/8
           OR aSharedLabelPageFalseMatches(blocks)    // Root cause 3: Schedule C / worksheet
           OR locatedColumnCount(blocks) > 3          // Root cause 4: no structural cap
         )
END FUNCTION
```

### Examples

Observed on the real capture (`/tmp/textract_blocks.json`, read-only, real PII — never
committed):

- Loose locator falsely matched pages 5, 7, 12 (page 12 is a Schedule C) in addition to the
  genuine page 13 — expected: only page 13 is Part I.
- Globally widest TABLE is page 16 (11 columns); `max_col - 1 = 10` phantom property columns
  — expected: 3 columns (A, B, C from page 13).
- Page 13's Part I grid is 31 rows × 8 columns. The header-letter row (row 2) holds A at
  col 4, B at col 6, C at col 8 (empty gap cols 3/5/7). Line labels are in **column 2**, not
  column 1 (line numbers sit in cols 1 and 3) — expected: labels read from any text cell in
  the row, amounts read from each property's span.
- Amounts are NOT fixed to cols 4/6/8: Rents (row 3) → A at col 4, B at col 6; Insurance
  (row 10) → A at col 5, B at col 7; Repairs (row 15) → A at col 5. Each property owns a
  **span** (A = cols 4–5, B = cols 6–7, C = col 8), matching Textract's own MERGED_CELL
  grouping — expected: an amount in a line row belongs to the property whose span contains
  its ColumnIndex.
- Row 19 of the grid is Line 18 (Depreciation), amounts 5,091. / 4,091. — expected: excluded
  entirely, never read into any column.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The clean contiguous layout (`clean_two_columns.json`: labels in column 1, amounts in
  contiguous columns 2..N) continues to produce one column per property with the same
  per-line amounts, addresses, and tax year.
- Line 18 (Depreciation) continues to be excluded; only the allow-set `{3,4,5-17,19}` is
  read; a depreciation amount is never carried.
- A document with no Schedule E Part I page continues to return `no_schedule_e_found=True`
  with no columns.
- Each value continues to carry the raw read token (empty when absent) + its contributing
  confidence + a `needs_verification` flag; money normalization stays in the service layer.
- The geometry fallback continues to run when the TABLES result is weak — now scoped to the
  Part I page and capped at a sane property-column maximum.
- The single tax year and per-column physical-address text continue to be read as before.

**Scope:**
All inputs where `isBugCondition` is false must be completely unaffected by this fix. This
includes the three existing fixtures (`clean_two_columns.json`, `low_confidence.json`,
`no_schedule_e.json`) and any document whose Part I page already uses a clean contiguous
`label | A | B` table.

## Hypothesized Root Cause

Confirmed by inspecting the real capture; the four root causes are:

1. **Document-global table-width heuristic**: `_column_count_from_tables` iterates **all**
   TABLE blocks and takes `max(max_col - 1)`. The widest table (page 16 = 11 cols; page 3 =
   10 cols) wins even though it is on a non-Schedule-E page → 10 phantom columns.

2. **Contiguity + column-1 label assumption**: `_amounts_from_table` reads the line label
   from cell column 1 and property amounts from contiguous columns `2..(N+1)`. The real grid
   has line labels in column 2, line numbers in columns 1 and 3, and property amounts in the
   non-contiguous spans anchored at header letters A/B/C (cols 4/6/8). Both the label lookup
   and the amount columns are wrong.

3. **Loose page locator**: `_is_part_i_page` accepts a title marker ("schedule e" / "part i"
   / "income or loss from rental real estate") plus any two of a generic label set
   (advertising, insurance, supplies, taxes, utilities, commissions…). Schedule C and
   worksheet pages share those labels, so pages 5/7/12 false-match.

4. **No structural cap**: a Schedule E Part I page has at most 3 property columns (A, B, C),
   but nothing caps the width-derived count.

## Correctness Properties

Property 1: Bug Condition - Header-letter column count and span-scoped amounts

_For any_ input where the bug condition holds (`isBugCondition` returns true), the fixed
`parse_schedule_e` SHALL produce exactly one `ParsedColumn` per A/B/C header letter present
on the located Schedule E Part I page(s) (capped at 3 per page), read each line amount from
the property column span anchored at that letter (handling non-contiguous layouts such as
cols 4/6/8 with amounts in spans 4–5 / 6–7 / 8), map each row's line by scanning the row's
text cells for a recognized Schedule E line label rather than assuming column 1, exclude
Line 18, and let no page lacking Schedule-E-specific evidence contribute any column.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Non-buggy inputs unchanged

_For any_ input where the bug condition does NOT hold (`isBugCondition` returns false), the
fixed `parse_schedule_e` SHALL produce the same `ParsedExtraction` as the original function,
preserving the clean contiguous column path, the Line 18 exclusion and allow-set, the
no-Schedule-E outcome, the raw-token + confidence + `needs_verification` contract (money
left to the service), the geometry fallback, and tax-year + address reading.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

**File**: `backend/src/logstead/services/schedule_e_parser.py`

**Functions**: `_is_part_i_page`, `_column_count_from_tables` (replaced), `_amounts_from_table`,
`_amounts_from_geometry`, `_addresses_from_forms`, `_addresses_from_geometry`,
`_infer_columns_from_geometry`, and the `parse_schedule_e` orchestration.

**Specific Changes**:

1. **Tighten the page locator (`_is_part_i_page`)** — Root cause 3.
   Require a Schedule E title marker AND Schedule-E-specific evidence that is absent from
   Schedule C: the phrase "rents received" (Schedule E line 3) and/or a "Properties:" header
   with A/B/C column letters. Keep the generic-label hit count as a secondary signal but no
   longer sufficient on its own. Pages 5/7/12 of the real capture must be rejected; page 13
   must be accepted. The clean/low-confidence fixtures both carry "rents received", so they
   still match.

2. **Scope every read to the located Part I page(s)** — Root cause 1.
   Thread the set of Part I page keys through the orchestration. Collect only the TABLE,
   KEY_VALUE_SET, and LINE blocks that belong to a located Part I page (by PAGE→CHILD
   relationship or `Page` attribute), and never scan tables document-wide. Process each
   genuine Part I page independently and concatenate the resulting columns.

3. **Replace width counting with header-letter detection** (`_property_columns_from_table`
   replaces `_column_count_from_tables`) — Root causes 2 and 4.
   Within a located Part I page's property table, find the **header-letter row**: the row
   whose cells each contain a single property letter (A, B, C, …, up to 3). Record each
   letter's `ColumnIndex`. Compute each property's **column span**: from its letter's column
   up to (but excluding) the next letter's column (the last property's span runs to the
   table's max column). The number of properties for the page is the number of letters found
   (capped at 3). If no header-letter row is found, fall back to the legacy contiguous
   interpretation for that page (preserves `clean_two_columns.json`).

4. **Read amounts by span, map lines by scanning text cells** (`_amounts_from_table`).
   For each table row, determine the line by scanning **all** the row's cells for a
   recognized line label (`_line_for_label`), not just column 1 — so a label in column 2 is
   found. For each property, pick the amount cell as the numeric-looking cell whose
   ColumnIndex falls within that property's span (prefer the one at the letter's column, else
   the first numeric cell in the span). Only allow-set lines are read; Line 18 is never
   mapped, so its row is skipped.

5. **Scope and cap the geometry fallback** (`_amounts_from_geometry`,
   `_infer_columns_from_geometry`) — Root cause 4.
   Keep the band-bucketing fallback for pages with a weak TABLES result, but restrict it to
   the Part I page's lines and cap the inferred column count at 3. When the header-letter
   path yields the column spans, the geometry fallback uses that count.

6. **Scope the address readers** (`_addresses_from_forms`, `_addresses_from_geometry`).
   Restrict the FORMS KEY_VALUE_SET scan and the geometry address fallback to the Part I
   page(s) and bucket into the detected property columns (capped). Behavior for the clean
   fixture (2 contiguous address boxes) is unchanged.

7. **Preserve the money/confidence/`needs_verification` contract** (`_build_line`,
   `ParsedColumn`/`ParsedExtraction` assembly) — unchanged. Raw tokens only; the service
   normalizes money.

### Tax-year reading

Unchanged, still scoped to the located Part I page(s)' header lines (step d).

## Testing Strategy

### Validation Approach

Two phases: first surface a counterexample that demonstrates the over-counting on the
UNFIXED parser, then verify the fix produces exactly 3 span-scoped columns and preserves all
non-buggy behavior. A real-capture sanity check (not committed) confirms the fix on the
actual 30-page document.

### Exploratory Bug Condition Checking

**Goal**: Surface a counterexample that demonstrates the bug BEFORE implementing the fix,
and confirm the root-cause analysis (global width + contiguity + loose locator + no cap).

**Test Plan**: Build a hand-crafted, SCRUBBED, minimized Textract fixture
(`real_return_scrubbed.json`) that reproduces the real structure with FAKE values:
- A Schedule E Part I page (title + "rents received" + a "Properties:" row) with an 8-column
  TABLE whose header-letter row has A/B/C at non-contiguous columns 4/6/8, line labels in
  column 2, line numbers in columns 1 and 3, a few allow-set rows with amounts in the span
  columns (including the 4-vs-5 offset), plus a Line 18 (Depreciation) row that must be
  excluded, and FAKE/placeholder addresses.
- An unrelated wide (10- or 11-column) worksheet TABLE on a different page.
- A Schedule-C-looking page that shares generic expense labels (Advertising, Insurance,
  Supplies, Taxes, Utilities) but has neither "rents received" nor an A/B/C header.

Run on the UNFIXED parser and assert exactly 3 span-scoped columns, no Line 18, and no
non-Part-I contribution. The test MUST FAIL on the unfixed parser (it reports ~10 columns
from the wide worksheet and reads the wrong cells).

**Test Cases**:
1. **Column count**: exactly 3 property columns (A, B, C) — will fail on unfixed code
   (reports the wide worksheet's width).
2. **Span-scoped amounts**: each amount read from the correct property's span (A at col 4/5,
   B at col 6/7, C at col 8) — will fail on unfixed code (contiguous 2..N assumption).
3. **Line 18 excluded**: the Depreciation row's fake amount appears in no column — passes on
   unfixed code too (allow-set already excludes it) but asserted for regression safety.
4. **Non-Part-I ignored**: the Schedule C page and the wide worksheet contribute no columns —
   will fail on unfixed code.

**Expected Counterexamples**:
- Unfixed parser returns `len(columns) == 10` (or similar) instead of 3.
- Amounts pulled from contiguous columns 2..N instead of the A/B/C spans.

### Fix Checking

**Goal**: For all inputs where the bug condition holds, the fixed function produces the
expected span-scoped behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := parse_schedule_e_fixed(input)
  ASSERT length(result.columns) = countOfLetterHeadersOnPartIPages(input)   // capped at 3/page
  ASSERT forEachColumn amountsReadFrom(propertySpanAnchoredAtHeaderLetter)
  ASSERT noColumnContains(scheduleELine = 18)
  ASSERT nonPartIPagesContributeNoColumns(result)
END FOR
```

### Preservation Checking

**Goal**: For all inputs where the bug condition does NOT hold, the fixed function produces
the same result as the original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT parse_schedule_e_original(input) = parse_schedule_e_fixed(input)
END FOR
```

**Testing Approach**: The existing parser tests (`test_schedule_e_parser.py`) are the
preservation suite — they encode the clean two-column path, the Line 18 exclusion, the
no-Schedule-E outcome, the geometry fallback, and confidence/`needs_verification`. They must
stay green. If the tightened locator or header-letter logic requires the existing fixtures
to carry a slightly richer header (e.g. an A/B column-letter row) to still parse, the
fixtures are updated minimally without weakening any assertion, and the change is noted. The
service and router suites (`test_schedule_e_extraction.py`, the
`test_schedule_e_extraction_*_property.py` suites, `test_schedule_e_extraction_routes.py`)
exercise the same fixtures end-to-end and must also stay green.

**Test Plan**: Observe behavior on the UNFIXED parser for the three existing fixtures first,
then confirm identical behavior after the fix.

**Test Cases**:
1. **Clean two-column preservation**: `clean_two_columns.json` → 2 columns, same amounts,
   addresses, tax year.
2. **Line 18 / allow-set preservation**: every column spans exactly the allow-set, never 18.
3. **No-Schedule-E preservation**: `no_schedule_e.json` → `no_schedule_e_found=True`.
4. **Geometry-fallback preservation**: `low_confidence.json` → 1 column, flagged values.

### Unit Tests

- Header-letter detection on a non-contiguous (4/6/8) grid → 3 property spans.
- Line mapping by scanning text cells (label in column 2) → correct line numbers.
- Span-scoped amount reading (A at col 4 and col 5) → correct per-property amounts.
- Line 18 row present in the grid → excluded from every column.
- Non-Part-I wide worksheet table and Schedule C page → no columns contributed.
- Each existing fixture → unchanged result (preservation).

### Property-Based Tests

- The existing `test_schedule_e_extraction_*_property.py` suites (no-Line-18 invariant,
  money normalization, scoping, write isolation) continue to hold across generated inputs.

### Integration Tests

- `test_schedule_e_extraction.py`: the service parse-and-cache path over the fixtures.
- `test_schedule_e_extraction_routes.py`: the router end-to-end over the fixtures.
- Real-capture sanity check (throwaway `/tmp` script, NOT committed, NO PII committed):
  run the fixed parser over `/tmp/textract_blocks.json` and confirm exactly 3 columns sourced
  from page 13 with the expected per-column line summary.
