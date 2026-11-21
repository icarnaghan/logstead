# Implementation Plan: Carryforward Tolerance and Year Range

## Overview

This plan makes three small corrections driven by real filed-return data. First, `CarryforwardService.reconcile()` compares reported figures with the expected and chain figures within a documented `STATUS_TOLERANCE` of `2.00` (exact `Decimal`) instead of to the cent, and exposes the tolerance as `status_tolerance` on `GET /carryforward`. Second, the page's mismatch hint is reworded to name the line to check, and the page explains the whole-dollar tolerance from the wire field. Third, a read-only route `GET /properties/{propertyId}/earliest-year` and one shared frontend hook make the Reports, Transactions and Property Detail year pickers start at the property's earliest activity year.

`expected_carry_in`, `expected_carryforward`, `drift`, status precedence, `carried_from_year`, storage keys and write routes are unchanged. A special-allowance-on-prior-losses field was considered and dropped; it is not part of this plan.

The language is **Python 3.12** (backend) and **React 19 + TypeScript** (frontend). Money stays exact `Decimal` in Python and fixed two-decimal strings or integer cents in the browser; no float arithmetic on money.

**Dependency shape.** Task 1.1 writes `backend/src/logstead/services/carryforward.py` and everything else in group 1 depends on it. Existing backend tests that assume exact-cent status equality, or generate a "mismatch" by offsetting a cent, would fail after 1.1, so tasks 1.2 to 1.6 are **required**. Task 2.1 (`dynamo_repo.py`), 2.2 (`transaction.py`), 2.3 (`dashboard.py`) and 2.4 (`handler.py`) each write a different file and chain through their imports. On the frontend, adding `status_tolerance` to the `ReconciliationSummary` type (4.1) breaks every fixture that builds a summary until 4.2 and 4.3 update them, because `npm run build` runs `tsc -b`. Tests that stub `../api/assets` must also stub the new earliest-year function (5.4 to 5.6).

Testing reuses the project stack: backend `pytest` + `Hypothesis` + `moto` with the real composed service stack (mirroring `test_carryforward_chain_status_property.py`); frontend `vitest` + `fast-check` + RTL. Each property test runs at least 100 iterations and is tagged `# Feature: carryforward-tolerance-and-year-range, Property N: ...` (`//` in TS).

Housekeeping: the backend venv may need recreating (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"` from `backend/`). iCloud duplicate files (`* 2.*`) may appear; delete them, never commit them. Never deploy and do not commit.

## Tasks

- [x] 1. Backend: tolerant status comparison
  - [x] 1.1 Add `STATUS_TOLERANCE`, `_within_tolerance` and the summary field in `backend/src/logstead/services/carryforward.py`
    - Add module-level `STATUS_TOLERANCE: Decimal = Decimal("2.00")` with a comment explaining whole-dollar returns versus cents and that it is the single place to change (also sent as `status_tolerance`); add `"STATUS_TOLERANCE"` to `__all__`
    - Add `_within_tolerance(a, b) -> bool` returning `abs(a - b) <= STATUS_TOLERANCE` (exact `Decimal`, no float)
    - In `reconcile()` replace `reported_value == expected_in` with `_within_tolerance(reported_value, expected_in)` and `reported_value == chain_in` with `_within_tolerance(reported_value, chain_in)`; keep the order unreported, ok, carried, mismatch; keep `drift = to_money(reported_value - expected_in)`, `expected_in`/`expected_out`, `chain_in` construction, `last_mismatch_year` and `carried_from` exactly as they are
    - Add `status_tolerance: Money = STATUS_TOLERANCE` (defaulted, last field) to `ReconciliationSummary`; pass `status_tolerance=to_money(STATUS_TOLERANCE)` from `reconcile()` including the empty-series case
    - Update the module docstring, `ReconciledYear.status` and `ReconciledYear.drift` docstrings to say "within the status tolerance" instead of "to the cent"; do not change setters, validators or storage
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 4.1, 4.4, 10.1, 10.3_
    - _Design: Components and Interfaces (Backend: tolerance); Edge cases_

  - [x] 1.2 Update the status and balance oracles in `backend/tests/services/test_carryforward_status_property.py` and `backend/tests/services/test_carryforward_allowed_balance_property.py`
    - In `_assert_statuses_total_and_correct` (near the oracle at lines 245-253) replace `reported == year.expected_carry_in` and `reported == chain` with `abs(...) <= Decimal("2.00")`; import `STATUS_TOLERANCE` from the service rather than repeating the literal
    - Where the strategy builds "mismatch" by `expected +/- a cent`, offset by more than the tolerance (for example `STATUS_TOLERANCE + 1 dollar`), and update the nearby comment and module docstring; keep the 2019 reported `0.00` example classified as `mismatch` only if its expected carry-in exceeds the tolerance, otherwise adjust the fixture value so the intent (a dropped carryover) holds
    - In `test_carryforward_allowed_balance_property.py` keep every `expected_carryforward` assertion exact; adapt any old-status oracle to the tolerance rule
    - _Requirements: 9.1, 9.2, 9.3_
    - _Design: Testing Strategy_

  - [x] 1.3 Update the oracles in `backend/tests/services/test_carryforward_chain_status_property.py` and `backend/tests/services/test_carryforward_chain_status_injection_property.py`
    - Replace the `reported == expected` and `reported == chain` oracle comparisons (around lines 289-295 of the first file) with the tolerance rule; adjust the "off-by-one-cent variants" strategies so a value meant to be a mismatch or non-chain value differs by more than the tolerance
    - Keep the `carried_from_year` attribution assertions (lines 472-481) unchanged
    - In the injection test, make the injected error and the "independent second error" differ from both expected and chain by more than the tolerance; keep the expectation of exactly one `mismatch` at the error year and `carried` afterwards
    - _Requirements: 9.1, 9.2, 9.3, 2.5, 2.6_
    - _Design: Testing Strategy_

  - [x] 1.4 Update `backend/tests/services/test_carryforward_chain_status_compat_property.py`, `backend/tests/services/test_carryforward_chain_status_drift_property.py` and `backend/tests/services/test_carryforward_chain_status_examples.py`
    - Compat: keep the `expected_carryforward` recurrence assertions exact; change `_status_vs_carry_in` to the tolerance rule; restate "backward compatible" as: exact-equal years are `ok`, `unreported` years are unchanged, and a year that was exact `carried` and is not within tolerance of expected is still `carried`; add a case that patches `STATUS_TOLERANCE` to `Decimal("0.00")` (monkeypatch the module attribute) and asserts the old exact classification
    - Drift: `_oracle_statuses` uses the tolerance rule; keep `drift == reported - expected` exact to the cent, including for `ok` years with nonzero drift
    - Examples: keep the worked example (its drifts are -5,000 so statuses hold); change any example that relied on a sub-$2 difference being `mismatch` or `carried`
    - _Requirements: 9.1, 9.2, 3.1, 3.2, 3.3, 3.4, 2.2, 2.3_
    - _Design: Testing Strategy_

  - [x] 1.5 Update the carry-in and remaining carryforward service tests
    - `backend/tests/services/test_carryforward_carry_in_property.py` and `backend/tests/services/test_carryforward_carry_in_examples.py`: Property 3 (all reported equal to expected gives `ok`, drift `0.00`) stays valid; adapt any status oracle or "differs by a cent" example to the tolerance rule
    - Run `.venv/bin/python -m pytest -q -p no:cacheprovider -n auto tests/services -k carryforward` from `backend/` and fix any remaining carryforward service test that assumes exact-cent status equality (candidates: `test_carryforward_running_balance_property.py`, `test_carryforward_balance_edges_property.py`, `test_carryforward_persistence_property.py`, `test_carryforward_fully_allowed_property.py`, `test_carryforward_allowed_examples.py`, `test_carryforward_net_reconciliation_property.py`), keeping each test's intent and keeping exact-cent assertions only for drift and expected values
    - _Requirements: 9.1, 9.2, 9.3_
    - _Design: Testing Strategy_

  - [x] 1.6 Update the router tests for the new summary field
    - In `backend/tests/router/test_carryforward_route.py` assert `body["status_tolerance"] == "2.00"` for a populated series and for the empty series; in `test_carryforward_chain_status_route.py`, `test_carryforward_money_property.py` and `test_carryforward_allowed_money_property.py` add `status_tolerance` to the summary fixed-format checks (string matching `^\d+\.\d{2}$`, never float) and fix any status expectation that assumed exact equality
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.1_
    - _Design: Data Models_

  - [x]* 1.7 Property tests: tolerance classification
    - **Property 1: Status follows the tolerant four-rule precedence**
    - **Property 2: Values within tolerance classify as ok or carried**
    - **Property 3: Values just outside tolerance classify as mismatch**
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.9, 1.10, 2.3, 2.7, 2.8**
    - New `backend/tests/services/test_carryforward_tolerance_property.py`; moto-backed composed stack like `test_carryforward_chain_status_property.py`; reconcile once to learn nets and expected values, set reported values as expected or chain plus signed offsets in cents (`|offset| <= 200`, exactly `200`, and `201`), reconcile again, compare to an independent `Decimal`-cents oracle

  - [x]* 1.8 Property tests: values unchanged, attribution, compatibility, real-data shape
    - **Property 4: Tolerance never changes values, drift or attribution inputs**
    - **Property 5: Root-cause attribution is unchanged**
    - **Property 6: Backward compatibility of exact matches**
    - **Property 7: Real-data shape yields carried**
    - **Validates: Requirements 1.3, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4**
    - Append to `backend/tests/services/test_carryforward_tolerance_property.py`; Property 7 builds a root-cause `mismatch` year followed by 2019/2020/2022-2025-style years whose reported values are the chain value plus a few dollars or cents (more than `2.00` from the expected value) and asserts every later year is `carried` from the root-cause year

  - [x]* 1.9 Unit examples: whole-dollar returns and boundaries
    - New `backend/tests/services/test_carryforward_tolerance_examples.py`; reported 10,057 against expected 10,056.73 is `ok` with drift `0.27`; 8,692 against 8,691.91 is `ok`; 11,831 against 11,830.xx is `ok`; a difference of exactly `2.00` is `ok` and `2.01` is `mismatch`; a blank/`0.00` line against a large expected value is `mismatch`; a return that omitted 902 of carried loss is `mismatch`; tolerance does not accumulate across years; the gain-year floor with a few dollars reported; first year and unreported-prior-year fallbacks
    - _Requirements: 1.2, 1.3, 1.4, 1.7, 1.9, 1.10, 2.3, 2.7, 2.8, 2.9_
    - _Design: Worked examples; Edge cases_

- [x] 2. Backend: earliest data year route
  - [x] 2.1 Add an optional `limit` to `DynamoRepository.query` in `backend/src/logstead/repository/dynamo_repo.py`
    - Add keyword `limit: int | None = None`; when set, pass `Limit` to the query call and stop paginating once `limit` items are collected; document it; default behaviour is unchanged
    - _Requirements: 7.7_
    - _Design: Components and Interfaces (Backend: earliest year)_

  - [x] 2.2 Add `TransactionService.earliest_year` in `backend/src/logstead/services/transaction.py`
    - Query `keys.property_scoped_pk(property_id)` with `keys.transaction_list_prefix()`, `ascending=False`, `limit=1`; return `None` when empty, otherwise `keys.date_from_inverted(sk.split("#")[1]).year`; reads nothing else and writes nothing
    - _Requirements: 7.2, 7.3, 7.7, 7.8_
    - _Design: Components and Interfaces (Backend: earliest year)_

  - [x] 2.3 Add `earliest_data_year` in `backend/src/logstead/services/dashboard.py`
    - Add `earliest_data_year(property_id, transactions, depreciation) -> int | None` returning the minimum of `transactions.earliest_year(property_id)` and `int(asset.placed_in_service_date[:4])` over `depreciation.list_assets(property_id)`, or `None` when neither exists; add to `__all__` if the module defines one
    - _Requirements: 7.2, 7.3, 7.4, 7.5, 7.9_
    - _Design: Components and Interfaces (Backend: earliest year)_

  - [x] 2.4 Add the route in `backend/src/logstead/router/handler.py`
    - Add `_earliest_year(wiring, user, params, body, query)`: call `_property_service(wiring, user).get(params["propertyId"])` first and return `_result_response(got)` on failure (404 for a property the user does not own); otherwise return `_response(200, {"earliest_year": year})` using `earliest_data_year` with `_transaction_service(wiring)` and `_depreciation_service(wiring)`
    - Register `("GET", "/properties/{propertyId}/earliest-year", _earliest_year, False)` with the other `/properties/{propertyId}/...` routes; confirm the literal segment does not collide with existing templates
    - _Requirements: 7.1, 7.5, 7.6, 7.8, 10.4_
    - _Design: Components and Interfaces (Backend: earliest year)_

  - [x]* 2.5 Tests: repository limit, service, route and property
    - **Property 10: Earliest data year is the minimum activity year**
    - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.6, 7.9**
    - New `backend/tests/router/test_earliest_year_route.py` over moto: transactions only (2010-2018 gives 2010), assets only, both (the smaller wins in each direction), neither (`earliest_year` null), another user's property gives 404; New `backend/tests/services/test_earliest_data_year_property.py`: Hypothesis over random transaction dates and in-service dates compared to `min` of the years, including receipts attached to the earliest transaction; add a `limit` example to the repository tests under `backend/tests/repository/`

- [x] 3. Checkpoint - backend
  - Ensure the backend compiles, `tests/services/test_carryforward_*.py` and `tests/router/test_carryforward_*.py` are green, and the route works; ask the user if questions arise.

- [x] 4. Frontend: tolerance field, hint and copy
  - [x] 4.1 Add `status_tolerance` to `ReconciliationSummary` in `frontend/src/api/carryforward.ts`
    - Add `readonly status_tolerance: string;` (fixed two-decimal string, for example `"2.00"`) with a doc comment: the largest difference still treated as a match because returns are filed in whole dollars; update the status doc comment from "to the cent" wording where present
    - _Requirements: 4.5_
    - _Design: Components and Interfaces (Frontend: carryforward API)_

  - [x] 4.2 Update fixtures in `frontend/src/api/carryforward.test.ts` and `frontend/src/pages/CarryforwardPage.test.tsx`
    - Add `status_tolerance: "2.00"` to every `ReconciliationSummary` literal (three in `carryforward.test.ts`; `POPULATED` and `EMPTY` in the page test) so `tsc -b` succeeds; add one assertion in `carryforward.test.ts` that `status_tolerance` round-trips through `getReconciliation`
    - In the page test replace the expectation at line 254 with the new hint wording computed from that fixture's 2020 `expected_carryforward` and the 2021 reported value, formatted by `formatMoneyWholeDollars`
    - _Requirements: 9.4, 9.5_
    - _Design: Testing Strategy_

  - [x] 4.3 Update the remaining summary fixtures and hint assertions
    - Add `status_tolerance: "2.00"` to the summary builders in `CarryforwardPage.carryIn.test.tsx`, `CarryforwardPage.carryIn.property.test.tsx`, `CarryforwardPage.driftCue.property.test.tsx`, `CarryforwardPage.labelHighlight.property.test.tsx` and `CarryforwardPage.chainStatus.test.tsx`
    - Replace the old hint text in `CarryforwardPage.carryIn.test.tsx` (line 206) and `CarryforwardPage.chainStatus.test.tsx` (line 232) with the new wording built from the fixture's Previous_Row `expected_carryforward` and the row's `reported_carryforward`; update the negative regex at `carryIn.test.tsx` line 215 (`/Compared with|Does not match|not reported, so/`) to `/Compared with|carried out about|not reported, so/`
    - _Requirements: 9.4, 9.5_
    - _Design: Testing Strategy_

  - [x] 4.4 Reword `mismatchHint` and add the tolerance sentence in `frontend/src/pages/CarryforwardPage.tsx`
    - Replace the last return of `mismatchHint` with: "The {prior} return carried out about {previous.expected_carryforward whole dollars}, but this return's line shows {year.reported_carryforward whole dollars}. Check this year's Form 8582 line and the {prior} return's carry-out." using `formatMoneyWholeDollars` on the Money_String text (no float); keep the first-row and unreported-previous wordings exactly; update the function's doc comment
    - Add a `ToleranceNote` paragraph rendered with the reconciliation table (not in the empty state) reading "Matches within {formatMoneyWholeDollars(summary.status_tolerance)} count as OK because returns are filed in whole dollars." and wire it where the table is rendered; keep the reported editor, allowed-loss control, opening balance control, Drift column, disclaimer and empty state unchanged
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 10.2_
    - _Design: Components and Interfaces (Frontend: page)_

  - [x]* 4.5 Tests: hint wording and tolerance sentence
    - **Property 9: Mismatch hint content**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
    - New `frontend/src/pages/CarryforwardPage.hint.property.test.tsx` (fast-check over integer cents for the previous carry-out and the reported value, `numRuns: 100`): hint appears only on `mismatch` rows, contains the previous year, the formatted carry-out and the formatted reported value; and `frontend/src/pages/CarryforwardPage.tolerance.test.tsx` (RTL): the sentence shows "$2" for `"2.00"` and "$10" for `"10.00"`, appears with the table, and is absent in the empty state; the first-row and unreported-previous hints keep their exact text

- [x] 5. Frontend: shared year range
  - [x] 5.1 Extend `taxYearRange` in `frontend/src/lib/taxYears.ts`
    - Add an optional fourth parameter `earliestDataYear: number | null = null`; the earliest year is the minimum of the fallback-window start, every valid asset year (>= 1900) and `earliestDataYear` when it is an integer of at least 1900; clamp to `latest`; keep two- and three-argument calls identical; update the module doc comment (earliest activity, not only assets)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
    - _Design: Components and Interfaces (Frontend: year range)_

  - [x] 5.2 Add `getEarliestDataYear` to `frontend/src/api/properties.ts`
    - `getEarliestDataYear(propertyId, signal?) -> Promise<number | null>` calling `GET /properties/{id}/earliest-year` through the shared client and returning `earliest_year`; add an `EarliestYearResponse` type
    - _Requirements: 8.6_
    - _Design: Components and Interfaces (Frontend: year range)_

  - [x] 5.3 Add the `usePropertyYearRange` hook in new `frontend/src/lib/usePropertyYearRange.ts`
    - Signature `(propertyId, assets, load = getEarliestDataYear) => number[]`; fetch once per `propertyId` with an abort/stale guard, treat any failure as `null`, return `useMemo(() => taxYearRange(assets, latestCompletedTaxYear(), 6, earliest), [assets, earliest])`
    - _Requirements: 8.6, 8.7, 8.9_
    - _Design: Components and Interfaces (Frontend: year range)_

  - [x] 5.4 Wire `frontend/src/pages/ReportsPage.tsx` and update its tests
    - Replace the `taxYearRange(assets, ...)` memo with `usePropertyYearRange(propertyId, assets)` (called unconditionally); keep the injected `years` prop as an override and `latestCompletedTaxYear()` as the default selection
    - In `ReportsPage.test.tsx` extend the `vi.mock("../api/properties", ...)` or add a mock so `getEarliestDataYear` resolves `null` (keep other exports via `importOriginal`); in `PageContainer.test.tsx` make the `ReportsPage` case not hit the network the same way
    - _Requirements: 8.6, 8.7, 8.9, 9.6_
    - _Design: Page wiring_

  - [x] 5.5 Wire `frontend/src/pages/TransactionsPage.tsx` and update its tests
    - Replace the `useMemo(() => taxYearRange(...))` with `usePropertyYearRange(propertyId, assets)`; keep "All years" and the `latestCompletedTaxYear()` default
    - In `TransactionsPage.test.tsx` stub `getEarliestDataYear` to resolve `null` alongside the existing `../api/assets` mock
    - _Requirements: 8.6, 8.7, 8.9, 8.10, 9.6_
    - _Design: Page wiring_

  - [x] 5.6 Wire `frontend/src/pages/PropertyDetailPage.tsx` and update its tests
    - Delete the private `taxYearRange` and its doc comment; add a `loadEarliestYear?: (propertyId: string, signal?: AbortSignal) => Promise<number | null>` test seam (default `getEarliestDataYear`) and use `usePropertyYearRange(propertyId, assets, loadEarliestYear)`; keep the `latestTaxYear` default selection
    - In `PropertyDetailPage.test.tsx` pass `loadEarliestYear` (default `async () => null`) from the render helper; in `PageContainer.test.tsx` pass `loadEarliestYear={noop(null)}` to the `PropertyDetailPage` case
    - _Requirements: 8.6, 8.7, 8.8, 8.9, 9.6_
    - _Design: Page wiring_

  - [x]* 5.7 Tests: range helper, hook and API
    - **Property 11: Year range spans the earliest known year to the latest completed year**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
    - New `frontend/src/lib/taxYears.test.ts` (fast-check, `numRuns: 100`: descending, starts at `latest`, never empty, ends at the expected minimum, contiguous; examples: 2010 earliest data year with no assets gives 2010 through the latest completed year; no data gives the six-year window; future earliest year clamps; below-1900 ignored); `frontend/src/lib/usePropertyYearRange.test.tsx` (RTL `renderHook`: success, rejected loader falls back to assets, property change refetches); an `api/properties.test.ts` case for `getEarliestDataYear`

- [x] 6. Checkpoint - frontend
  - Ensure `npm run build` and `npx vitest --run` compile and pass for the carryforward and year-picker pages; ask the user if questions arise.

- [x] 7. CHANGELOG entry
  - [x] 7.1 Add entries under `## [Unreleased]` in `CHANGELOG.md`
    - Under `### Changed`: carryforward status comparison now treats figures within $2 as matching (whole-dollar returns versus cents), the mismatch hint names the line to check, and the Reports, Transactions and Property Detail year pickers start at the property's earliest transaction or asset year
    - Add an `### Added` bullet (create the heading if absent) for `status_tolerance` on `GET /carryforward` and the `GET /properties/{propertyId}/earliest-year` route; match the existing entry style and wording
    - _Requirements: 4.1, 7.1_

- [x] 8. Final verification - suites green, no float, no deploy
  - Backend: from `backend/`, recreate the venv if missing or stale (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"`), then run `.venv/bin/python -m pytest -q -p no:cacheprovider -n auto`; the full suite must be green
  - Frontend: from `frontend/`, run `npm run build` (the real gate: `tsc -b && vite build`), then `npx vitest --run`; both must be green
  - Confirm `expected_carry_in`, `expected_carryforward` and `drift` math is unchanged, no floating-point arithmetic was introduced for money, no special-allowance field was added, and the §469 limitation is not computed
  - Delete any iCloud duplicate files (`* 2.*`); never commit them; do not commit anything
  - Do NOT run any deploy (`make deploy`); the user runs deploys. Ask the user if anything is unclear
  - _Requirements: 9.1, 9.4, 10.1, 10.2, 10.3, 10.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "4.1", "5.1", "5.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.4", "1.5", "2.2", "4.2", "4.3", "5.3"] },
    { "id": 2, "tasks": ["1.6", "2.3", "4.4", "5.4", "5.5"] },
    { "id": 3, "tasks": ["1.7", "1.9", "2.4", "4.5", "5.6", "5.7"] },
    { "id": 4, "tasks": ["1.8", "2.5", "7.1"] }
  ]
}
```

> Wave ordering note: tasks 1.7 and 1.8 both write `test_carryforward_tolerance_property.py` and sit in waves 3 and 4. 1.2 to 1.6 each touch distinct test files. 2.1 (`dynamo_repo.py`), 2.2 (`transaction.py`), 2.3 (`dashboard.py`) and 2.4 (`handler.py`) each write one file and are in increasing waves because each imports the previous. 4.2 and 4.3 write disjoint fixture files; 4.4 writes `CarryforwardPage.tsx` only. 5.4, 5.5 and 5.6 each write one page and its test; 5.4 and 5.6 both touch `PageContainer.test.tsx`, so 5.6 sits in a later wave than 5.4. Checkpoints (3, 6) and the final task (8) are stop-and-verify gates, not code tasks, so they are not in the wave graph.

## Notes

- **Spec only.** This spec describes the change; implementation happens when tasks are run. Tasks marked `[ ]*` are optional new tests and can be skipped for a faster MVP. Tasks 1.2 to 1.6, 4.2, 4.3 and 5.4 to 5.6 are **not** optional: they keep the existing suites and `tsc -b` green.
- **Backward compatibility.** `expected_carry_in`, `expected_carryforward`, `drift` and `carried_from_year` attribution are identical to today; every exact-cent `ok` stays `ok`. With the tolerance set to `0.00` the old statuses are reproduced.
- **Existing tests that assume exact-cent status equality** must adopt the tolerance rule, and generators that build a "mismatch" by a one-cent offset must offset by more than `STATUS_TOLERANCE`, otherwise they will classify `ok`.
- **No new stored data and no write routes.** The only new route, `GET /properties/{propertyId}/earliest-year`, is read-only and user-scoped.
- **No deploy.** Task 8 is the real gate and explicitly excludes `make deploy`.
