# Implementation Plan: Carryforward Chain Break Summary

## Overview

This plan adds a frontend-only reading of the carryforward series: a pure derivation in `frontend/src/lib/carryforwardChain.ts`, a chain summary block above the reconciliation table (shown only when a year is `mismatch`), and a hint on `carried` rows. Money stays in Money_Strings, arithmetic is exact integer cents via `toCents`/`centsToMoney`, and display uses `formatMoneyWholeDollars`. No backend change, no new wire field, and no change to expected values, `drift`, `status` or the tolerance.

The language is **TypeScript** (React 19, vitest, React Testing Library, fast-check), matching the workspace. Property tests run at least 100 iterations and are tagged `// Feature: carryforward-chain-break-summary, Property N: ...`.

**Dependency shape.** Task 1.1 creates the library file; everything else depends on it. Task 2.1 is the only task that edits `CarryforwardPage.tsx`. Task 2.2 is **required**: the summary block repeats the phrase "carried out about" from the existing hint, so a negative regex in `CarryforwardPage.carryIn.test.tsx` and possibly other queries can match more than one element and must be scoped to the table. Test files are separate per task so they can run in parallel.

Housekeeping: iCloud duplicate files (`* 2.*`) may appear; delete them, never commit them. Never deploy and do not commit.

## Tasks

- [x] 1. Pure derivation in `frontend/src/lib/`
  - [x] 1.1 Create `frontend/src/lib/carryforwardChain.ts`
    - Export `ChainBreak`, `ChainSummary`, `CarriedBreakInfo`, `summarizeChainBreaks(years)` and `carriedBreakInfo(year, summary)` exactly as in the design (import `ReconciledYear` from `../api/carryforward`, `toCents` and `centsToMoney` from `./money`)
    - `summarizeChainBreaks`: walk the ascending series; track the last non-null drift in cents (start `0`); group consecutive `mismatch` rows into runs; per run record `startYear`, `endYear`, `startAmount` and `endAmount` as `centsToMoney(toCents(drift) - baselineCents)`, the start row's `reported_carryforward` and `expected_carry_in`, and `priorYear`/`priorCarryOut` only when the previous array row has a non-null `reported_carryforward`; treat a null drift on a mismatch row as `0.00`; return `null` when there is no run; `totalGap` is the latest row with a non-null drift
    - `carriedBreakInfo`: return `null` unless `status === "carried"` with non-null `carried_from_year` and `drift`; otherwise `{ breakYear, drift, firstBreakYear }` with `firstBreakYear` set to `summary.firstBreak.startYear` only when it differs from `breakYear`
    - No React, DOM or network imports; no floating-point arithmetic on money; do not mutate the input; add doc comments explaining the run grouping and baseline rule
    - _Requirements: 1.1, 1.2, 2.1, 2.3, 3.4, 4.1, 4.4, 5.1, 5.2, 5.3_
    - _Design: Components and Interfaces (carryforwardChain.ts)_

  - [x] 1.2 Write unit tests in `frontend/src/lib/carryforwardChain.test.ts`
    - Real-data shape: 2016 to 2018 mismatch (reported `0.00`, drifts `-2452.00`, `-2710.00`, `-3422.00`), 2019 to 2020 carried from 2018, 2021 mismatch (about `-902.00` incremental), 2022 to 2025 carried from 2021, total gap 2025 `-4323.00`; assert first break years, `startAmount` `-2452.00`, `endAmount` `-3422.00`, `priorYear` 2015 and `priorCarryOut` `2452.00`, one further break at 2021, and `carriedBreakInfo` for 2019 (`breakYear` 2018, `firstBreakYear` 2016) and 2023 (`breakYear` 2021, `firstBreakYear` 2016)
    - Edge cases: empty series and no-mismatch series return `null`; first-row mismatch has null `priorYear`/`priorCarryOut`; mismatch after an unreported row has null prior fields; a mismatch with positive drift gives a positive amount; two mismatch runs separated by an unreported row stay two runs; a later run's baseline is the last carried drift; `carriedBreakInfo` returns `null` for `ok`, `mismatch`, `unreported`, carried with null `carried_from_year`, and carried with null `drift`; the input array is not mutated
    - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.4, 3.4, 4.1, 4.3, 4.4, 5.3, 8.1, 8.3_

  - [x]* 1.3 Write property tests for break detection in `frontend/src/lib/carryforwardChain.breaks.property.test.ts`
    - **Property 1: A summary exists exactly when a mismatch row exists**
    - **Property 2: Breaks are the maximal runs of consecutive mismatch rows**
    - **Validates: Requirements 1.1, 1.2, 1.5, 2.1, 2.2, 2.4**
    - fast-check `seriesArb` as in the design (1 to 12 ascending years, random statuses, integer-cent money), `numRuns: 100` or more; oracle recomputes the runs with plain loops

  - [x]* 1.4 Write property tests for amounts and totals in `frontend/src/lib/carryforwardChain.amounts.property.test.ts`
    - **Property 3: Break amounts are exact drift differences**
    - **Property 4: Total gap is the latest non-null drift**
    - **Property 5: Break amounts account for the total gap**
    - **Validates: Requirements 2.3, 3.1, 3.4, 5.2**
    - Oracle uses `BigInt` cents (including large magnitudes and negatives) and asserts two-decimal Money_String shape; Property 5 uses a generator that holds `drift` constant across non-mismatch reported rows; `numRuns: 100` or more

  - [x]* 1.5 Write property tests for carried info and purity in `frontend/src/lib/carryforwardChain.carried.property.test.ts`
    - **Property 6: Carried-row info reflects the row and the first break**
    - **Property 7: The derivation does not modify its input**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 5.3**
    - Property 7 compares the input with a deep copy taken before the calls and checks repeated calls return equal results; `numRuns: 100` or more

- [x] 2. Page: summary block and carried hint
  - [x] 2.1 Add the summary block and carried hint to `frontend/src/pages/CarryforwardPage.tsx`
    - Import `summarizeChainBreaks` and `carriedBreakInfo` from `../lib/carryforwardChain`, and `centsToMoney`/`toCents` from `../lib/money`
    - Add `ChainSummaryBlock({ summary, tolerance })`: a `<section aria-labelledby>` with a visible `<h2>` "Where the chain breaks", neutral styling (`border-border bg-surface-muted`), then the first-break sentence (prior-row variant or first-row/unreported-prior variant), the continuation line only when `endYear > startYear`, a "Further breaks:" paragraph and `<ul>` of `<li>` items only when `furtherBreaks` is non-empty, the total gap sentence (under/over beyond the tolerance, "within {tolerance}" otherwise, comparing `abs(toCents(drift))` with `toCents(tolerance)`), and the closing line; wording exactly as in the design, every amount through `formatMoneyWholeDollars` of an absolute Money_String, "dropped" for negative and "extra" for positive amounts
    - In `ReconciliationTable` compute `const chain = summarizeChainBreaks(years)` once and pass each row a `carriedHint` string built from `carriedBreakInfo(year, chain)` ("Inherits the {breakYear} break: this line is about {abs drift} under|over the expected carry-in." plus " The chain first broke in {firstBreakYear}." when set); thread it through `ReconciliationRow` to `StatusCell`, which renders it beneath the label in the same `text-xs text-fg-muted` style as the existing hint
    - Render `ChainSummaryBlock` in the populated branch of `CarryforwardPage` between `ToleranceNote` and `ReconciliationTable` (compute the summary in the page and pass it to both, or compute inside each from the same `summary.years`), passing `summary.status_tolerance`; render nothing when the derivation returns `null`
    - Keep the existing "Carried from {year}" label, the `mismatchHint` text, the disclaimer, the empty state and all editors unchanged; do not add an API call
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 5.4, 5.5, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3_
    - _Design: Components and Interfaces (CarryforwardPage.tsx); Wording; Carried hint wording_

  - [x] 2.2 Keep the existing page tests passing
    - Run `npx vitest --run src/pages/CarryforwardPage` from `frontend/` and fix any assertion that now matches more than one element
    - Scope the negative regex in `CarryforwardPage.carryIn.test.tsx` (the one containing `carried out about`) to the table, for example with `within(screen.getByRole("table"))`, and scope any other colliding query the same way; do not weaken or delete assertions, and do not change fixtures unless a collision requires it
    - _Requirements: 8.4_
    - _Design: Testing Strategy (Existing tests)_

  - [x] 2.3 Write RTL tests in `frontend/src/pages/CarryforwardPage.chainSummary.test.tsx`
    - Use the injectable `api` prop with the real-data fixture (2015 ok; 2016 to 2018 mismatch with reported `0.00`; 2019 to 2020 carried from 2018; 2021 mismatch; 2022 to 2025 carried from 2021; `status_tolerance` `"2.00"`), with money formatted by `formatMoneyWholeDollars` in expectations
    - Assert: region found by role `region` and name "Where the chain breaks"; first-break sentence ("The chain first breaks in 2016: the 2015 return carried out about $2,452, but the 2016 line shows $0."); continuation ("through 2018" and "$3,422"); a `listitem` for the 2021 break with "$902" and "dropped"; total gap sentence for 2025 with "$4,323" and "under"; the carried hint on the 2019 row (break 2018, first broke 2016) and on the 2022 row (break 2021); the "Carried from 2018" label and the disclaimer still present; the existing mismatch hint still on the 2016 row
    - Also assert: no region for an all-ok series, a carried-only series and the empty state; the first-row and unreported-prior variants of the first-break sentence; the gap sentence at exactly the tolerance ("within $2") and one cent above ("under"); a positive-drift break uses "extra" and "over"; a single run renders no list; the api mock is called once (no extra requests)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.4, 3.1, 3.2, 3.3, 4.1, 4.5, 5.4, 6.1, 6.3, 7.1, 7.2, 8.2, 8.3_

  - [x]* 2.4 Write property tests in `frontend/src/pages/CarryforwardPage.chainSummary.property.test.tsx`
    - **Property 8: The summary block states the derived facts**
    - **Property 9: Carried rows show the inherited-break hint**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5**
    - fast-check over small generated series (integer cents, a random tolerance of `0.00` to `10.00`), rendered with the injectable `api` prop and `cleanup` between runs, `numRuns: 100` or more; expectations are built from `formatMoneyWholeDollars` and the derived data from `summarizeChainBreaks`, scoped to the region or the row so the table's own cells do not interfere

- [x] 3. Checkpoint - tests green
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Documentation
  - [x] 4.1 Add a `CHANGELOG.md` entry under `## [Unreleased]`
    - Under the existing `### Added` heading, add a bullet in the existing style: **Carryforward chain break summary.** The page shows a summary above the table when a year is a mismatch, naming the year the chain first breaks, the amount that appears dropped there, any further separate breaks and the total gap; `carried` rows now hint at the break they inherited. Derived from existing fields in the browser; no API change
    - _Requirements: 8.5_

  - [x] 4.2 Mark the idea as addressed in `docs/future-improvements.md`
    - In the section "Summarize where a carryforward chain first broke", add directly under the heading a status line in the style of the first section: `**Status: addressed.** Implemented as a chain summary block above the table plus a hint on carried rows (spec: carryforward-chain-break-summary).`
    - Replace the "Deferred until the real-data gap has been checked..." note with a short addressed note: consecutive mismatch years are grouped as one break, later breaks are listed with their incremental amount (the change in drift), and the total gap is the latest reported year's drift; keep the original context and idea text for history
    - _Requirements: 8.6_

- [x] 5. Final verification
  - From `frontend/`, run `npm run build` (the real gate: `tsc -b && vite build`), then `npx vitest --run`; both must be green
  - Confirm no backend file changed, `expected_carry_in`, `expected_carryforward`, `drift`, `status` and `carried_from_year` are used as received, no floating-point arithmetic on money was introduced, the disclaimer is unchanged and the §469 limitation is not computed
  - Delete any iCloud duplicate files (`* 2.*`); never commit them; do not commit anything
  - Do NOT run any deploy (`make deploy`); the user runs deploys. Ask the user if anything is unclear
  - _Requirements: 5.4, 5.5, 7.1, 7.3, 8.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "2.1", "4.1", "4.2"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] }
  ]
}
```

> Wave ordering note: 1.2 to 1.5 and 2.1 each write a different file and depend only on 1.1. 4.1 (`CHANGELOG.md`) and 4.2 (`docs/future-improvements.md`) are independent files. 2.2, 2.3 and 2.4 depend on 2.1; 2.2 edits existing test files, while 2.3 and 2.4 create new ones. Checkpoint 3 and final task 5 are stop-and-verify gates, not code tasks, so they are not in the graph.

## Notes

- **Spec only.** This spec describes the change; implementation happens when tasks are run. Tasks marked `[ ]*` are optional property tests and can be skipped for a faster MVP. Task 2.2 is required because it keeps the existing suite green.
- **Rounding.** Carried rows may differ from each other by up to the status tolerance, so the sum of whole-dollar break figures can differ from the total gap by a dollar (for example about $3,422 + $902 against $4,323). The wording says "about" and the total is stated separately; Property 5 covers the exact case.
- **Grouping.** Consecutive mismatch years are one break. A mismatch separated from an earlier one by any non-mismatch row (including an unreported row) is a further break reported with its incremental amount.
- **No deploy, no commit.**
