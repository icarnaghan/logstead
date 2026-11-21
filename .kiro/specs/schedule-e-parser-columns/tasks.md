# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Header-letter column count and span-scoped amounts
  - **CRITICAL**: This test MUST FAIL on the unfixed parser - failure confirms the over-counting bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it validates the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug (phantom columns from a document-global wide table, wrong cells from the contiguous assumption, Schedule C false-match)
  - **Scoped PBT Approach**: The bug is deterministic for a fixed fixture, so scope the property to the concrete real-structure fixture (`real_return_scrubbed.json`)
  - Create a hand-built, SCRUBBED, minimized Textract block fixture under `backend/tests/services/fixtures/schedule_e_parser/real_return_scrubbed.json` (from Bug Details / Examples in design):
    - A Schedule E Part I page: title + "Rents received" + a "Properties:" header row; an 8-column TABLE whose header-letter row has A/B/C at NON-CONTIGUOUS columns 4/6/8; line labels in COLUMN 2; line numbers in columns 1 and 3; allow-set rows with amounts in the property spans (include the col-4-vs-col-5 offset for A); a Line 18 (Depreciation) row with a FAKE amount; FAKE/placeholder addresses
    - An unrelated wide (10- or 11-column) worksheet TABLE on a DIFFERENT page
    - A Schedule-C-looking page sharing generic expense labels (Advertising, Insurance, Supplies, Taxes, Utilities) but NO "rents received" and NO A/B/C header
  - **NO REAL PII**: all values FAKE; never copy any value from `/tmp/textract_blocks.json`
  - Add a test to `backend/tests/services/test_schedule_e_parser.py` asserting: exactly 3 property columns; amounts read from the A/B/C span columns (A at col 4/5, B at col 6/7, C at col 8); no Line 18 anywhere; the Schedule C page and the wide worksheet contribute no columns
  - Run on the UNFIXED parser: `cd backend && .venv/bin/python -m pytest -q tests/services/test_schedule_e_parser.py`
  - **EXPECTED OUTCOME**: Test FAILS (proves the over-counting / mis-read bug exists)
  - Document counterexamples found (observed column count and wrong cell reads)
  - Mark complete when the test is written, run, and the failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-buggy inputs unchanged
  - **IMPORTANT**: Follow observation-first methodology — the existing `test_schedule_e_parser.py` IS the preservation suite
  - Observe on the UNFIXED parser that the three existing fixtures behave as the current tests assert:
    - `clean_two_columns.json` → 2 columns; amounts 24000/18500 (line 3), addresses "12 Maple Street"/"90 Oak Avenue", tax year 2023
    - `no_schedule_e.json` → `no_schedule_e_found=True`, no columns
    - `low_confidence.json` → 1 column, values flagged `needs_verification`, year unset
  - Confirm these existing preservation tests PASS on the UNFIXED parser (baseline to preserve)
  - Do NOT weaken any existing assertion; if the tightened locator later needs a fixture to carry a richer header, update the fixture minimally and note it
  - Run: `cd backend && .venv/bin/python -m pytest -q tests/services/test_schedule_e_parser.py`
  - **EXPECTED OUTCOME**: Existing preservation tests PASS (confirms baseline behavior to preserve)
  - Mark complete when the baseline is confirmed green on the unfixed parser
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 3. Fix the Schedule E parser column over-counting

  - [ ] 3.1 Implement the fix
    - Tighten `_is_part_i_page`: require a Schedule E title marker AND Schedule-E-specific evidence ("rents received" and/or a "Properties:" A/B/C header), so Schedule C / worksheet pages are rejected (design Fix Implementation step 1)
    - Scope every TABLE / KEY_VALUE_SET / LINE read to the located Part I page(s); process each genuine Part I page independently and concatenate columns; never scan tables document-wide (step 2)
    - Replace `_column_count_from_tables` with header-letter detection: find the row of single-letter property labels (A, B, C, capped at 3), record each letter's ColumnIndex, and compute each property's column span (letter column up to the next letter's column); fall back to the legacy contiguous interpretation only when no header-letter row exists (step 3)
    - Read amounts by span and map lines by scanning ALL the row's text cells for a recognized line label (not column 1); skip Line 18 (steps 3-4)
    - Scope and cap the geometry fallback and address readers to the Part I page(s), capped at 3 columns (steps 5-6)
    - Preserve the raw-token + confidence + `needs_verification` contract; money stays in the service (step 7)
    - _Bug_Condition: isBugCondition(blocks) from design — Part I page with letter headers + any of the 4 root causes_
    - _Expected_Behavior: Property 1 — exactly N (≤3/page) span-scoped columns, no Line 18, non-Part-I pages contribute nothing_
    - _Preservation: Preservation Requirements from design_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Header-letter column count and span-scoped amounts
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - Run: `cd backend && .venv/bin/python -m pytest -q tests/services/test_schedule_e_parser.py`
    - **EXPECTED OUTCOME**: Test PASSES (confirms exactly 3 span-scoped columns, no Line 18, non-Part-I ignored)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-buggy inputs unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run the parser suite plus the service and router suites:
      - `cd backend && .venv/bin/python -m pytest -q tests/services/test_schedule_e_parser.py tests/services/test_schedule_e_extraction.py tests/router/test_schedule_e_extraction_routes.py`
      - plus the `tests/services/test_schedule_e_extraction_*_property.py` suites
    - **EXPECTED OUTCOME**: All PASS (no regressions). If a fixture needed a minimal header enrichment, note it; assertions unchanged
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Run the full Schedule E parser, extraction, property, and router suites; all green
  - Real-capture sanity check (throwaway `/tmp` script, NOT committed): run the fixed parser over `/tmp/textract_blocks.json`; confirm exactly 3 columns sourced from page 13 with the expected per-column line summary; confirm no non-Part-I page contributes columns; confirm NO real PII committed
  - Ensure all tests pass; ask the user if questions arise
