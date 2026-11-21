# Implementation Plan: Carryforward Carry-In Semantics

## Overview

This plan re-points the passive-loss carryforward reconciliation from "reported value = balance carried **out** of the year" to "reported value = Form 8582 **Prior years unallowed losses** = balance carried **into** the year". The stored `PLCF#<year>` `amount` and the wire field `reported_carryforward` are reinterpreted as the carry-in; there is no data migration. `reconcile()` exposes a new per-year `expected_carry_in` (the balance before the step), keeps `expected_carryforward` as the carry-out (value unchanged), compares reported with expected carry-in, and re-points the chain check to the **previous** year's step applied to the previous year's **reported** carry-in. The summary gains `next_year` and `next_year_expected_carry_in`. The page gets new columns, hints, helper text and copy.

The languages are **Python 3.12** (backend) and **React 19 + TypeScript** (frontend). The router needs no code change because `_to_jsonable` serializes dataclass fields; route tests verify it. Money stays an exact two-decimal `Decimal` in Python and a fixed two-decimal string over the wire.

**Dependency shape.** Tasks 1.1 and 1.2 both write `backend/src/logstead/services/carryforward.py`, so they sit in distinct waves. Existing tests that encode the out-of-year comparison (task 2) **must** be updated or the suites fail. Frontend fixtures (4.2, 5.2 to 5.5) **must** gain `expected_carry_in` and the summary fields because `npm run build` (`tsc -b`) otherwise fails. Tests that only assert the running balance (`expected_carryforward`) stay valid unchanged.

Testing reuses the project stack: backend `pytest` + `Hypothesis` + `moto` with the real composed service stack (mirroring `test_carryforward_chain_status_property.py`); frontend `vitest` + `fast-check` + RTL. Every property test runs at least 100 iterations and is tagged `# Feature: carryforward-carry-in-semantics, Property N: ...` (`//` in TS).

Housekeeping: the backend venv may need recreating (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"` from `backend/`). iCloud duplicate files (`* 2.*`) must be deleted, never committed.

## Tasks

- [x] 1. Backend: carry-in semantics in `CarryforwardService`
  - [x] 1.1 Extend `ReconciledYear` and `ReconciliationSummary` in `backend/src/logstead/services/carryforward.py`
    - Add `expected_carry_in: Money = Decimal("0.00")` as the last field of `ReconciledYear`
    - Add `next_year: int | None = None` and `next_year_expected_carry_in: Money = Decimal("0.00")` as the last fields of `ReconciliationSummary`
    - Rewrite the module docstring and the `ReconciledYear` / `ReconciliationSummary` docstrings: `reported_carryforward` is the Form 8582 "Prior years unallowed losses" carry-in, `expected_carryforward` is the expected carry-out, `expected_carry_in` is what the reported value is compared with, `drift` is `reported - expected_carry_in`, and `carried_from_year` is the year whose carry-in was first wrong (review the return for the year before it)
    - _Requirements: 1.1, 1.2, 2.4, 7.1, 7.3, 11.5_
    - _Design: Components and Interfaces (Backend)_

  - [x] 1.2 Re-point `reconcile()` in `backend/src/logstead/services/carryforward.py`
    - Capture `expected_in = balance` before the step and `expected_out = _apply_year_step(...)` after it; keep `expected_carryforward = expected_out` (value unchanged) and set `expected_carry_in = expected_in`
    - Compute `drift = reported - expected_in` (null when unreported)
    - Track `prev_reported`, `prev_net` and `prev_allowed`; for every year after the first with a non-null `prev_reported`, compute `chain_in = _apply_year_step(prev_reported, prev_net, prev_allowed)`
    - Status block in order: `unreported`; `ok` when reported equals `expected_in`; `carried` (with `carried_from_year = last_mismatch_year`) when `chain_in` is present and equals reported; else `mismatch` and set `last_mismatch_year = year`
    - Set `next_year = years[-1] + 1` and `next_year_expected_carry_in = balance` after the loop (`None` and the opening balance when there are no years)
    - Update the `reconcile()` docstring and inline comments for carry-in semantics; do not change setters, validators, storage keys or `_apply_year_step`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 7.4, 7.5, 12.1, 12.2_
    - _Design: Classification algorithm; Edge cases_

  - [x]* 1.3 Property tests: carry-in relation, faithful entry, next-year summary
    - **Property 1: Carry-in follows the previous carry-out and carry-out is unchanged**
    - **Property 3: Faithful entry is all ok**
    - **Property 8: Next-year expectation**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 3.8, 6.1, 7.3, 7.4, 7.5**
    - New `backend/tests/services/test_carryforward_carry_in_property.py`; moto-backed composed stack; generate opening, nets (some years with allowed amounts and fully-allowed flags); assert the carry-in/carry-out recurrence against an independent `Decimal` oracle; set every year's reported value to its `expected_carry_in` and assert all years are `ok` with drift `0.00` (the user's real scenario: figures equal to the previous year's expected balance); assert `next_year` and `next_year_expected_carry_in` including the empty-series case

  - [x]* 1.4 Example test: the user's real 2014 to 2020 shape
    - New `backend/tests/services/test_carryforward_carry_in_examples.py`; the design's worked example (2014 `ok`, 2015 837 is `ok` where the old semantics flagged it, 2016 to 2018 blank with `expected_carry_in` 2,452 / 2,452 / 2,152 and `unreported`, 2019 `mismatch` drift -2,645 after the blank gap, 2020 `carried` from 2019 drift -2,645, `next_year` 2021 and `next_year_expected_carry_in` 3,252); first year compares with the opening balance; unreported previous year falls back then chains one year later; gain-year floor; second independent error names the later year; fully allowed and partly allowed loss years are not misread
    - _Requirements: 3.2, 3.3, 3.4, 3.6, 3.7, 4.4, 5.1, 6.1, 7.4, 13.5_
    - _Design: Worked example; Edge cases_

- [x] 2. Backend: update existing tests that encode the out-of-year comparison
  - [x] 2.1 Update the status oracle in `backend/tests/services/test_carryforward_status_property.py`
    - Compare reported with `expected_carry_in`; rebuild the chain oracle from the previous row's reported value, `schedule_e_net`, `allowed_loss` and `fully_allowed`; update the module docstring; keep the test's intent and strategies
    - _Requirements: 13.1, 3.1, 3.2, 3.3, 3.4_
    - _Design: Existing test impact_

  - [x] 2.2 Update Properties 1, 4, 5 in `backend/tests/services/test_carryforward_chain_status_property.py`
    - Re-point the oracle to carry-in (reported vs `expected_carry_in`, chain = previous year's step on the previous reported value); update the `carried` relation and `carried_from_year` assertions; update the docstrings
    - _Requirements: 13.1, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4_

  - [x] 2.3 Update `backend/tests/services/test_carryforward_chain_status_compat_property.py`
    - Keep the property that `expected_carryforward` equals the pre-feature running-balance recurrence; replace the claims that `unreported` / `ok` / `mismatch` equal the old out-of-year rule with the re-pointed relations (`unreported` iff no reported value; `status in {mismatch, carried}` exactly when reported differs from `expected_carry_in`); keep a non-adjacent-years generator where every status is `ok` or `mismatch`
    - _Requirements: 13.1, 1.4, 3.1, 3.2, 3.6_

  - [x] 2.4 Update `backend/tests/services/test_carryforward_chain_status_injection_property.py`
    - Build the correct reported series from `expected_carry_in`; chain later years with the previous year's step on the previous reported value; assert exactly one `mismatch` at the injected year, `carried` / `ok` afterwards, a second injected error naming the later year, and the fallback after an unreported gap
    - _Requirements: 13.1, 3.6, 4.4, 5.1_

  - [x] 2.5 Update `backend/tests/services/test_carryforward_chain_status_drift_property.py`
    - Assert `drift == reported_carryforward - expected_carry_in` as an exact two-decimal `Decimal`, null iff unreported, and that status equals the carry-in oracle
    - _Requirements: 13.1, 6.1, 6.2, 6.3_

  - [x] 2.6 Update `backend/tests/services/test_carryforward_chain_status_examples.py`
    - Re-derive every example (worked example, first year, unreported prior, gain-year floor, second error, allowed-loss years) under carry-in semantics with the previous-year chain step; keep the original scenarios' intent
    - _Requirements: 13.1, 3.2, 3.3, 3.4, 3.6, 3.7, 4.4, 5.1_

  - [x] 2.7 Update status expectations in `test_carryforward_allowed_balance_property.py` and `test_carryforward_fully_allowed_property.py` (under `backend/tests/services/`)
    - Keep every `expected_carryforward` assertion; change status or drift expectations that compared reported with the carry-out to compare with `expected_carry_in` (accept `mismatch` or `carried` where the oracle says reported differs from expected carry-in)
    - _Requirements: 13.1, 1.4_

  - [x] 2.8 Update `test_carryforward_allowed_examples.py` and audit `test_carryforward_persistence_property.py` and `test_carryforward_running_balance_property.py` (under `backend/tests/services/`)
    - Re-derive status / drift expectations in the examples for carry-in semantics (set reported values to the carry-in the scenario implies); in the two audited files change only assertions that compare reported with the carry-out
    - _Requirements: 13.1, 2.2, 2.3_

  - [x] 2.9 Update the router tests under `backend/tests/router/`
    - `test_carryforward_route.py`, `test_carryforward_money_property.py`, `test_carryforward_allowed_money_property.py`, `test_carryforward_chain_status_route.py`: re-derive status / drift examples for carry-in, assert `expected_carry_in` (two-decimal string on every year), `next_year` (int or null) and `next_year_expected_carry_in` (two-decimal string) are present, and that the existing fields keep their names and types
    - **Property 9: Wire figures are fixed-format and never float**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.6, 12.1**
    - _Requirements: 13.1, 2.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 3. Checkpoint - backend carry-in semantics
  - Ensure the backend compiles and all `tests/services/test_carryforward_*.py` and `tests/router/test_carryforward_*.py` suites are green (including the oracles updated in task 2); ask the user if questions arise.

- [x] 4. Frontend: API types
  - [x] 4.1 Extend the types in `frontend/src/api/carryforward.ts`
    - Add `readonly expected_carry_in: string` to `ReconciledYear`; add `readonly next_year: number | null` and `readonly next_year_expected_carry_in: string` to `ReconciliationSummary`
    - Rewrite the doc comments: `reported_carryforward` is the Form 8582 "Prior years unallowed losses" carry-in, `expected_carryforward` is the expected carry-out, `expected_carry_in` is what reported is compared with, `drift` is reported minus expected carry-in; no request signature changes
    - _Requirements: 7.7, 11.5_
    - _Design: Components and Interfaces (Frontend)_

  - [x] 4.2 Update fixtures in `frontend/src/api/carryforward.test.ts`
    - Add `expected_carry_in` to every `ReconciledYear` fixture and `next_year` / `next_year_expected_carry_in` to every `ReconciliationSummary` fixture so `tsc -b` succeeds; add one assertion that the new fields round-trip through `getReconciliation`
    - _Requirements: 13.2, 7.7_

- [x] 5. Frontend: page columns, hints and copy
  - [x] 5.1 Rework `frontend/src/pages/CarryforwardPage.tsx`
    - Table headers in order: Year, Schedule E net, "Expected entering year" (`formatMoneyWholeDollars(expected_carry_in)`), "Prior years' unallowed losses (Form 8582)" (the reported editor), Drift, Allowed loss, "Expected to carry out" (`formatMoneyWholeDollars(expected_carryforward)`), Status; every row renders eight cells
    - Helper paragraph above the table telling the user to enter the "Prior years unallowed losses" line from each year's Form 8582 (the balance carried into that year)
    - `ReportedEditor` aria-label "Prior years' unallowed losses for {tax_year}" and matching error strings
    - `StatusCell` hint for `mismatch` rows computed from the previous row in the table: previous reported gives "Does not match the {prior_year} return's carry-out. Review the {prior_year} return."; previous unreported gives "The {prior_year} return is not reported, so this was compared with the expected figure only."; first row gives "Compared with your opening balance."; unreported rows still show their expected carry-in
    - Allowed-loss control helper text: the allowed amount changes the amount expected to carry into the next year
    - Summary line below the table: "Expected to carry into {next_year}" (or "the next year" when null) with the whole-dollar `next_year_expected_carry_in`
    - Rewrite the page introduction and `DisclaimerNotice` copy for carry-in / carry-out; update component doc comments; keep the mismatch-only highlight, `DriftCell`, opening balance control, empty state and reload-after-write flow
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.1, 11.2, 11.3, 11.4, 12.3_
    - _Design: Components and Interfaces (Frontend)_

  - [x] 5.2 Update `frontend/src/pages/CarryforwardPage.test.tsx`
    - Add `expected_carry_in`, `next_year` and `next_year_expected_carry_in` to the row builder and every literal so `tsc -b` succeeds; update header-count, cell-count, aria-label ("Prior years' unallowed losses for {year}"), heading and intro / disclaimer text assertions to the new copy
    - _Requirements: 13.2, 13.3, 8.2, 8.5, 8.6_

  - [x] 5.3 Update `frontend/src/pages/CarryforwardPage.chainStatus.test.tsx`
    - Add the new fixture fields; update header, label and reload-after-save assertions to the new columns and copy; keep the "Carried from {year}" and highlight assertions
    - _Requirements: 13.2, 13.3, 10.1, 10.5, 10.6_

  - [x] 5.4 Update `frontend/src/pages/CarryforwardPage.driftCue.property.test.tsx`
    - Add the new fixture fields to `makeApi`; keep Property 10 (drift cell direction cue) and its tag; adjust any header lookup that depended on the old column order
    - **Property 10: Drift cell shows direction in text**
    - **Validates: Requirements 10.9, 12.3**
    - _Requirements: 13.2, 13.3_

  - [x] 5.5 Update `frontend/src/pages/CarryforwardPage.labelHighlight.property.test.tsx`
    - Add the new fixture fields; keep Property 11 (label and highlight depend only on status and root-cause year); adjust cell lookups for the eight-column layout
    - **Property 11: Status label and highlight depend only on status and root-cause year**
    - **Validates: Requirements 10.1, 10.5, 10.6, 10.7, 10.8**
    - _Requirements: 13.2, 13.3_

  - [x]* 5.6 RTL examples for the new columns, hints and next-year line
    - New `frontend/src/pages/CarryforwardPage.carryIn.test.tsx`; the "Expected entering year", "Prior years' unallowed losses (Form 8582)" and "Expected to carry out" headers; helper text naming the Form 8582 line; the three mismatch hints (first year, unreported previous year, reported previous year); an unreported row still shows its expected carry-in; "Expected to carry into 2021" with the formatted value and the null-year wording; allowed-loss helper text; a reload after a save updates the next-year line
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 9.2, 9.3, 10.2, 10.3, 10.4, 10.7, 11.3_
    - _Design: Testing Strategy_

  - [x]* 5.7 Property test: carry-in and carry-out cells and constant cell count
    - **Property 12: Rows show carry-in and carry-out and have a constant cell count**
    - **Validates: Requirements 8.1, 8.3, 8.6, 8.7**
    - New `frontend/src/pages/CarryforwardPage.carryIn.property.test.tsx`; fast-check over generated rows (status, drift, expected, reported, null reported); assert every row has as many cells as the header, the entering cell contains the formatted `expected_carry_in` and the carry-out cell contains the formatted `expected_carryforward`; `numRuns: 100`

- [x] 6. Docs
  - [x] 6.1 Add a CHANGELOG entry in `CHANGELOG.md`
    - Match the file's existing format; describe the carry-in re-pointing, the new `expected_carry_in`, `next_year` and `next_year_expected_carry_in` wire fields, and that no data migration is needed; `README.md` and `docs/` contain no reported-carryforward wording (confirmed by search), so no other doc edit is expected
    - _Requirements: 2.3, 11.5_

- [x] 7. Final verification - suites green, no float, no deploy
  - Backend: if the venv is missing or stale, recreate it (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"` from `backend/`), then run `.venv/bin/python -m pytest -q -p no:cacheprovider -n auto` from `backend/`; the full suite must be green
  - Frontend: from `frontend/`, run `npm run build` (the real gate: `tsc -b && vite build`) and then `npx vitest --run`; both must be green
  - Confirm `expected_carryforward` values are unchanged, no floating-point arithmetic was introduced, and the §469 limitation is not computed
  - Delete any iCloud duplicate files (`* 2.*`); never commit them
  - Do NOT run any deploy (`make deploy`); the user runs deploys. Do NOT commit. Ask the user if anything is unclear.
  - _Requirements: 1.4, 12.1, 12.2, 13.1, 13.2, 13.3, 13.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4", "4.1"] },
    { "id": 3, "tasks": ["2.5", "2.6", "2.7", "2.8", "5.1"] },
    { "id": 4, "tasks": ["2.9", "1.3", "1.4", "4.2", "5.2"] },
    { "id": 5, "tasks": ["5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 6, "tasks": ["6.1"] }
  ]
}
```

> Wave ordering note: tasks 1.1 and 1.2 both write `carryforward.py` and occupy distinct waves. Every other task writes its own file(s), and no two tasks in the same wave share a file. 5.1 writes `CarryforwardPage.tsx` after 4.1 settles the types; the page tests (5.2 to 5.5) follow the page rework so their copy and column assertions match. Checkpoint 3 and final task 7 are stop-and-verify gates, not code tasks, so they are not in the wave graph.

## Notes

- **Spec only.** This spec describes the change; implementation happens when tasks are run. Tasks marked `[ ]*` are optional new tests and can be skipped for a faster MVP. Task 2 (updating existing backend tests), 4.2 and 5.2 to 5.5 (frontend fixtures and copy) are **not** optional: they keep the existing suites and `tsc -b` green.
- **Naming asymmetry is deliberate.** `reported_carryforward` is a carry-in and `expected_carryforward` stays the carry-out so existing running-balance consumers and tests are unaffected; the new `expected_carry_in` is what the page compares. A later spec may rename the wire fields.
- **No data migration, no new routes, no storage-key changes.**
- **No deploy and no commit.** Task 7 is the real gate and explicitly excludes `make deploy` and `git commit`.
