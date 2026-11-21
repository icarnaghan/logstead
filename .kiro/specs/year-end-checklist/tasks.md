# Implementation Plan: Year-end Checklist

## Overview

This plan adds a read-only, per-property, per-tax-year Year-end checklist: eleven fixed checks, each `done`, `needs_attention` or `not_applicable` with a Reason and a Link, plus per-year counts on the property page and per-property counts on the dashboard. The design is a thin snapshot gatherer (`ChecklistService`) over existing services, eleven pure rule functions in `services/checklist.py`, one configuration module (`services/checklist_config.py`), three small read seams on existing services (`resolve_category_rows`, `LoanService.year_facts`, `TransactionService.has_receipt`), and three `GET` routes that take the `taxYear` query parameter. Nothing is stored.

Languages: Python 3.12 (backend) and TypeScript/React (frontend), as in the design. Backend tests use pytest, Hypothesis and moto. Frontend tests use vitest, fast-check and React Testing Library. Every property-based test runs at least 100 iterations and is tagged `# Feature: year-end-checklist, Property N: ...` (`//` in TypeScript).

Ordering: configuration and the read seams come first, then the pure rule layer and its property tests, then the gatherer service, the routes and authorization. The frontend starts from the API module and pure text helpers, builds the components and pages, wires the nav entry and route once the page exists, and ends with accessibility coverage. Documentation closes the plan. This is a spec-only deliverable; implementation happens task by task later. Nothing here deploys or commits.

## Tasks

- [x] 1. Backend: configuration and read seams
  - [x] 1.1 Create `backend/src/logstead/services/checklist_config.py`
    - Define `ChecklistConfigError`, the frozen `ChecklistConfig` (Large_Entry_Amount `250.00`, Capital_Candidate_Amount `2500.00`, Swing_Percent `50`, Swing_Minimum_Amount `500.00`, Anchor_Max_Age_Months `12`, Summary_Year_Count `5`) and `CHECKLIST_CONFIG = ChecklistConfig()`
    - `__post_init__` rejects non-`Decimal` money or percent values (including `float`), a money threshold below `0.00`, a `swing_percent` of `0` or less, and a month or year count below `1`; money thresholds are quantized to two places
    - Add `applied()` returning the echo object for the response (money as two-decimal `Decimal`, `swing_percent` as given)
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 1.7_
  - [x] 1.2 Extract `resolve_category_rows` in `backend/src/logstead/services/itemized.py`
    - Add the frozen `CategoryRows` (resolution, entries, total rows) and `resolve_category_rows(transactions, category_id)` holding the loop now inside `ItemizedExpenseService.summary` (filter by category, classify with `_is_entry`, feed `LineAccumulator`)
    - Make `summary` call it and keep its response shape and behavior unchanged
    - _Requirements: 4.2_
  - [x] 1.3 Add `LoanService.year_facts` in `backend/src/logstead/services/loan.py`
    - Add the frozen `LoanYearFact` (loan id, description, anchor date, include flag, interest as `Money`, has-override flag) and `year_facts(property_id, tax_year)`
    - Read the loan items and the year's rollups (all rollups, not only included ones), join on loan id, return every loan, project no schedule, write nothing, and raise `StoredLoanError` through the existing strict parsers
    - _Requirements: 4.4, 8.2, 8.3, 8.4_
  - [x] 1.4 Add `TransactionService.has_receipt` in `backend/src/logstead/services/transaction.py`
    - `has_receipt(property_id, transaction)` builds the same `#DOC#` prefix as `_receipt_items` and runs one `Limit=1` query; no S3 call, no presigned URL
    - _Requirements: 2.4, 12.7_
  - [x] 1.5 Write the config property test
    - **Property 3: Config validation**
    - **Validates: Requirements 3.3, 3.6**
    - New `backend/tests/services/test_checklist_config_property.py`; add examples in `backend/tests/services/test_checklist_config.py`: defaults equal the six proposed values, each invalid value raises `ChecklistConfigError`, and a source scan finds none of the six default numbers as literals in `services/*.py` other than `checklist_config.py`
  - [x] 1.6 Write tests for the read seams
    - New `backend/tests/services/test_checklist_seams.py` over moto: `year_facts` with stored loans, overrides, an excluded loan, an anchor after the tax year and a corrupt loan item (raises `StoredLoanError`); `has_receipt` with and without a `#DOC#` row and with a receipt on a different transaction; `resolve_category_rows` equals the pre-change `summary` output for the same rows
    - _Requirements: 2.4, 4.2, 4.4, 12.7_

- [x] 2. Backend: pure rule layer
  - [x] 2.1 Create `backend/src/logstead/services/checklist.py` with models and pure helpers
    - Define `ItemId`, `ITEM_IDS` (fixed order), `Status`, frozen `ChecklistItem`, `ChecklistCounts`, `Checklist`, `ChecklistSummary`, `PropertyChecklistSummary`, `PropertyChecklistRow`, `PortfolioChecklistSummary`, `LoanFact`, `YearSnapshot`, and `MAX_RECEIPT_DETAILS = 25`
    - Add `receipt_candidates`, `is_large_entry`, `is_capital_candidate`, `swing_for` (one-decimal half-up percentage, compared after quantizing), `anchor_is_recent` (closed window with month-end clamping), `applicable_loan_count` (included in the report and anchored on or before December 31 of the tax year), `recent_years`, `is_edited` (both timestamps parse and `updated_at > created_at`), `build_counts`, a money and percent formatter for Reasons, and the link builder (`/properties/{id}/{segment}` with `?year=` for `transactions`, `repairs` and `reports`; `/carryforward`)
    - Use `Decimal` only; no I/O
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.7, 4.6, 8.4, 11.2, 12.1, 13.3, 13.6, 14.3, 15.2, 16.5, 21.1, 21.3, 21.4_
  - [x] 2.2 Implement rules for items 1 to 5 in `checklist.py`
    - `income_entered`, `expenses_entered` (excluding line 18), `depreciation_present`, `line12_source` (flags a zero entered Line 12 only for an Applicable_Loan; Loans link when loan-generated or an Applicable_Loan exists), and `loan_interest_confirmed` (evaluated loans are included with interest above `0.00`)
    - Each rule reads only the snapshot and the config, writes its `details` per the design, and states the count and superseded amount where required
    - _Requirements: 4.1, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8_
  - [x] 2.3 Implement rules for items 6 to 8 in `checklist.py`
    - `carryforward_reconciled` (status mapping, portfolio-level sentence, tolerance taken from the reconciliation, no comparison of amounts), `repairs_exceed_total` and `repairs_capital_candidates` (review-prompt wording that never calls an entry a capital improvement)
    - _Requirements: 4.2, 4.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
  - [x] 2.4 Implement rules for items 9 to 11 and `build_checklist` in `checklist.py`
    - `receipts_missing` (not imported, expense, at or above Large_Entry_Amount, at most 25 detail rows with the full count), `yoy_swings` (review wording, never says a change is wrong), `imported_values_edited` (Reason states that re-import replaces imported values)
    - `build_checklist(snapshot, config)` calls the eleven rules in `ITEM_IDS` order, builds the counts, and echoes the applied thresholds
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 3.4, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.9, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7_
  - [x] 2.5 Write the shape property test
    - **Property 1: Checklist shape, counts, and determinism**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    - New `backend/tests/services/test_checklist_shape_property.py` with strategies that build `YearSnapshot`s from generated reports, transactions, `LoanFact`s and `ReconciledYear`s, including empty snapshots
  - [x] 2.6 Write the threshold interpolation property test
    - **Property 2: Applied thresholds are echoed and interpolated**
    - **Validates: Requirements 1.7, 3.4**
    - In `backend/tests/services/test_checklist_shape_property.py`
  - [x] 2.7 Write the inclusive comparison property test
    - **Property 4: Threshold comparison is inclusive**
    - **Validates: Requirements 3.7, 11.2, 12.1, 13.3**
    - New `backend/tests/services/test_checklist_thresholds_property.py` with boundary values `T`, `T - 0.01` and `T + 0.01` for `is_large_entry`, `is_capital_candidate` and the Swing_Minimum_Amount test
  - [x] 2.8 Write the income and expenses property test
    - **Property 5: Income and expenses entered**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
    - New `backend/tests/services/test_checklist_report_rules_property.py`; include a report whose only non-zero expense is line 18
  - [x] 2.9 Write the depreciation property test
    - **Property 6: Depreciation present**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.5**
    - In `backend/tests/services/test_checklist_report_rules_property.py`
  - [x] 2.10 Write the Line 12 source property test
    - **Property 7: Line 12 source**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7**
    - In `backend/tests/services/test_checklist_report_rules_property.py`; generate loans with arbitrary include flags and anchor dates so a loan anchored after the tax year or excluded from the report never changes the status
  - [x] 2.11 Write the loan interest property test
    - **Property 8: Loan interest confirmed**
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8**
    - New `backend/tests/services/test_checklist_loan_rule_property.py` with an independent date oracle for the anchor window, including month-end clamping and leap years
  - [x] 2.12 Write the carryforward mapping property test
    - **Property 9: Carryforward mapping**
    - **Validates: Requirements 4.3, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.10**
    - New `backend/tests/services/test_checklist_rules_property.py`
  - [x] 2.13 Write the itemized repairs property test
    - **Property 10: Itemized repairs versus the entered total**
    - **Validates: Requirements 4.2, 10.1, 10.2, 10.3, 10.5**
    - In `backend/tests/services/test_checklist_rules_property.py`; Repairs rows go through the real `resolve_category_rows`
  - [x] 2.14 Write the capital candidates property test
    - **Property 11: Large Repairs entries to review**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.6**
    - In `backend/tests/services/test_checklist_rules_property.py`
  - [x] 2.15 Write the receipts property test
    - **Property 12: Receipts on large expenses**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.6**
    - New `backend/tests/services/test_checklist_receipts_swings_property.py`
  - [x] 2.16 Write the year-over-year swing property test
    - **Property 13: Year-over-year swings**
    - **Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 21.3**
    - In `backend/tests/services/test_checklist_receipts_swings_property.py` with an independent `Decimal` oracle
  - [x] 2.17 Write the edited imported values property test
    - **Property 14: Imported values later edited**
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5**
    - New `backend/tests/services/test_checklist_edited_import_property.py` with equal, reversed, missing, unparseable, naive and aware timestamps
  - [x] 2.18 Write the recent-year selection property test
    - **Property 21: Recent-year selection**
    - **Validates: Requirements 15.2, 15.6**
    - New `backend/tests/services/test_checklist_helpers_property.py`
  - [x] 2.19 Write the link construction property test
    - **Property 22: Links embed only validated ids and the year**
    - **Validates: Requirements 10.4, 13.8, 14.6, 16.5**
    - In `backend/tests/services/test_checklist_helpers_property.py` with ids from the `_ID_RE` alphabet
  - [x] 2.20 Write example tests for every rule branch
    - New `backend/tests/services/test_checklist_rules.py`: each `done`, `needs_attention` and `not_applicable` branch of items 1 to 11 with concrete amounts and the exact Reason text; for item 4 a loan anchored after the tax year and a loan excluded from the report each leave a zero Line 12 `not_applicable`, and an included loan anchored on December 31 of the tax year flags it; the review-prompt wording of items 8 and 10; the fixed carryforward and edited-import sentences; the 25-entry cap with 30 missing receipts
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.1, 10.2, 10.3, 11.2, 11.3, 11.4, 11.5, 12.2, 12.3, 12.4, 13.2, 13.4, 13.5, 13.9, 14.2, 14.3, 14.4, 14.7_

- [x] 3. Checkpoint - pure rule layer
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 4. Backend: gatherer service
  - [x] 4.1 Add `ChecklistService` and the request cache to `backend/src/logstead/services/checklist.py`
    - Implement `_RequestCache` (one `reconcile`, one `report_for` per `(property_id, year)`), `checklist_for`, `property_summary` (via `derive_data_years` and `recent_years`) and `portfolio_summary` (default year `latest_tax_year()`, one property listing, one reconciliation)
    - Gather per design: reports and prior-year report, one `list_for_property`, `resolve_category_rows(..., "repairs")`, asset schedule rows, `year_facts` (`StoredLoanError` becomes the same `conflict` as `report_for`), the year's `ReconciledYear`, and `has_receipt` for candidates only
    - Return any failed `Result` unchanged and never a partial Checklist
    - _Requirements: 2.1, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.8, 12.7, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.8_
  - [x] 4.2 Write the report agreement property test
    - **Property 16: Details line totals equal the report**
    - **Validates: Requirements 4.1, 4.7**
    - New `backend/tests/services/test_checklist_agreement_property.py` through the real `ReportingService` over moto with small generated state
  - [x] 4.3 Write the route agreement property test
    - **Property 17: Counts agree across the three routes**
    - **Validates: Requirements 15.5**
    - In `backend/tests/services/test_checklist_agreement_property.py`
  - [x] 4.4 Write the shared reads property test
    - **Property 18: Upstream reads are shared within a request**
    - **Validates: Requirements 4.8, 12.7**
    - New `backend/tests/services/test_checklist_read_sharing_property.py` with wrapper objects that count `reconcile`, `report_for` and `has_receipt` calls
  - [x] 4.5 Write the read-only property test
    - **Property 19: The checklist is read-only**
    - **Validates: Requirements 2.1, 2.4**
    - New `backend/tests/services/test_checklist_read_only_property.py` with a recording repository and S3 stub; stored items compared before and after
  - [x] 4.6 Write the money form property test
    - **Property 20: Money values have the wire form**
    - **Validates: Requirements 15.9, 21.1, 21.4**
    - New `backend/tests/services/test_checklist_money_property.py` serializing through `_to_jsonable`
  - [x] 4.7 Write the backup classification property test
    - **Property 15: Edited classification survives backup and restore**
    - **Validates: Requirements 14.3, 14.4**
    - New `backend/tests/services/test_checklist_backup_property.py` extending the existing backup round-trip strategies with imported rows and timestamp pairs
  - [x] 4.8 Write service example tests
    - New `backend/tests/services/test_checklist_service.py`: a year with no data, a corrupt loan item returns `conflict` and no items, `reconcile` called once for a dashboard summary over three properties, default year equals `latest_tax_year()` with a frozen clock, a source scan finding no `STATUS_TOLERANCE` comparison and no sum over `schedule_e_line` in `checklist.py`
    - New `backend/tests/services/test_checklist_edited_import.py`: import a Schedule E and expect `done`; edit the imported total through `TransactionService.update` and through `ItemizedExpenseService.set_total` and expect `needs_attention`; set the amount back and expect it to stay; re-import and expect `done`; attach a receipt and expect no change; backup and restore keeps the classification; a restored row without timestamps counts as not edited; a row re-created through the generic create route has `imported == False`
    - _Requirements: 2.1, 4.3, 4.6, 4.8, 14.3, 14.4, 15.4, 15.6, 15.7, 15.8_

- [x] 5. Backend: routes and authorization
  - [x] 5.1 Add the checklist handlers and routes in `backend/src/logstead/router/handler.py`
    - Add `_checklist_service(wiring, user)` built from the same collaborators the report and carryforward routes use, `_year_param(query)` returning `_int_param(query["taxYear"], "taxYear")` or `None`, and the handlers `_property_checklist` and `_property_checklist_summary` (both `@_property_scoped`) and `_portfolio_checklist_summary`
    - Register `GET /properties/{propertyId}/checklist`, `GET /properties/{propertyId}/checklist/summary` and `GET /checklist/summary` in `_ROUTES`; register no other method; leave existing route matching unchanged
    - _Requirements: 2.2, 15.1, 15.2, 15.3, 15.4, 15.8, 16.1, 16.3, 16.4, 16.5, 16.6_
  - [x] 5.2 Write router tests
    - New `backend/tests/router/test_checklist_routes.py`: success for the three routes; `400` with `field == "taxYear"` for `abc`, `1899` and `2201`; `PUT`, `POST` and `DELETE` on the three paths resolve to no route; the property summary returns the most recent Data_Years descending; an empty property returns an empty year list; a user with no property returns an empty list; the Checklist, property summary and dashboard summary agree on counts; existing `/properties/{propertyId}/...` route resolution is unchanged
    - _Requirements: 2.2, 15.1, 15.2, 15.3, 15.5, 15.6, 15.7, 16.4, 16.6, 22.7, 22.9_
  - [x] 5.3 Extend the cross-user authorization tests
    - In `backend/tests/router/test_cross_user_authorization.py`: user B requests user A's `/properties/{id}/checklist` and `/checklist/summary` and gets a body byte-identical to a missing id with no repository reads after the ownership check; user B's dashboard summary omits user A's property
    - _Requirements: 16.1, 16.2, 16.3_
  - [x] 5.4 Add the accountant package hook `provider_for`
    - In `backend/src/logstead/router/handler.py` add the public alias `build_checklist_service = _checklist_service` (if the accountant-package work already added public wiring aliases, add this one next to them; do not duplicate)
    - In `backend/src/logstead/services/checklist.py` add the `ChecklistProvider` protocol and `provider_for(wiring, user)`, which imports `build_checklist_service` lazily inside the function and returns the built `ChecklistService`; the function reads nothing and raises when a collaborator cannot be built; keep the exact name and parameters used in `.kiro/specs/accountant-package/design.md`
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5_
  - [x] 5.5 Write the provider contract test
    - New `backend/tests/services/test_checklist_provider_contract.py`: `provider_for` accepts `(wiring, user)` with a `UserContext` and with a user id string; `checklist_for(property_id, tax_year)` equals `ChecklistService.checklist_for` for the same data and records no write; a wiring that cannot build a collaborator makes `provider_for` raise
    - Optional import contract: when `logstead.services.accountant_package` is importable, assert that `default_checklist_provider(wiring, user)` returns the provider and a built package contains `checklist/year-end-checklist-<year>.json`; with the checklist module hidden through `sys.modules` and an import hook, assert the builder still completes and records the reason; when the accountant package is not present, assert only the `importlib.import_module("logstead.services.checklist")` and `provider_for` shape and skip the package assertions
    - This is an example-based test; no property number is added
    - _Requirements: 24.2, 24.5, 24.6, 22.14_

- [x] 6. Checkpoint - backend
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 7. Frontend: API module and pure helpers
  - [x] 7.1 Add `frontend/src/api/yearEndChecklist.ts`
    - `YearEndChecklistApi` with an injectable `ApiClient` and the shared `yearEndChecklistApi`: `getChecklist(propertyId, taxYear, signal?)`, `getPropertySummary(propertyId, signal?)`, `getPortfolioSummary(taxYear, signal?)`; query parameter `taxYear`
    - Export the wire types (`ChecklistStatus`, `ChecklistCounts`, `ChecklistItem`, `YearEndChecklist`, `PropertyChecklistSummary`, `PortfolioChecklistSummary`)
    - Add `frontend/src/api/yearEndChecklist.test.ts` for paths, query strings and the omitted-year case
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 21.1_
  - [x] 7.2 Add `parseYearParam` and honor `?year=` on Transactions and Reports (conditional: add if absent, reuse if present)
    - Before editing, check whether the `ui-polish` work already added `parseYearParam` to `frontend/src/lib/taxYears.ts` and the `?year=` initializers to the two pages. Add only what is missing and reuse what is present; never define a second helper or a second initializer
    - `parseYearParam(value)` in `frontend/src/lib/taxYears.ts` returns the integer for a canonical decimal string from 1900 through 2200, else `null` (the same contract as the `ui-polish` spec)
    - Initialize `taxYear` from a valid `?year=` in `frontend/src/pages/TransactionsPage.tsx` and `frontend/src/pages/ReportsPage.tsx`, falling back to `latestCompletedTaxYear()`; do not write the parameter back
    - Extend `frontend/src/lib/taxYears.test.ts` and the two page tests for a valid, invalid and absent value only where those cases are not already covered
    - _Requirements: 5.2, 13.8, 14.6_
  - [x] 7.3 Create `frontend/src/components/year-end-checklist/yearEndText.ts`
    - `orderItems` (stable partition, needs attention first), `countsText`, `summaryHeadline` ("All clear" only when `needs_attention == 0` and `done >= 1`), `statusLabel`, `linkLabel` (destination name from `PROPERTY_NAV` or "Carryforward")
    - _Requirements: 17.2, 19.3, 19.4, 19.5, 20.2_
  - [x] 7.4 Write the ordering property test
    - **Property 23: Needs-attention items come first**
    - **Validates: Requirements 19.5**
    - New `frontend/src/components/year-end-checklist/yearEndText.property.test.ts`
  - [x] 7.5 Write the counts text property test
    - **Property 24: Counts text and headline**
    - **Validates: Requirements 17.2, 19.4**
    - In `frontend/src/components/year-end-checklist/yearEndText.property.test.ts`

- [x] 8. Frontend: components, pages, navigation and accessibility
  - [x] 8.1 Build the presentational components in `frontend/src/components/year-end-checklist/`
    - `YearEndStatusBadge` (icon plus status text, semantic tokens), `YearEndDisclaimer` (`role="note"`, reminder aid and not tax advice, no instruction on what to report), `YearEndItemDetails` (type guards per `item.id`, `ResponsiveTable` for row lists, `dl` for scalars, `formatMoney`, renders nothing for an unknown shape), `YearEndItemRow` (title, badge, Reason, destination link with `aria-label` `"{linkLabel}: {title}"`, `<details>` collapsed by default)
    - Build only from shared primitives; no threshold number and no money arithmetic
    - _Requirements: 3.5, 19.3, 19.6, 19.9, 20.1, 20.2, 20.6, 20.8, 21.2_
  - [x] 8.2 Build `frontend/src/pages/YearEndChecklistPage.tsx`
    - `PropertySection` titled "Year-end checklist" (one `h1`, document title "Year-end checklist - {property name}"), the disclaimer in every state, a year `Select` (`id="year-end-year"`) from `usePropertyYearRange` defaulting to `parseYearParam(...)` or `latestCompletedTaxYear()` and written back to `year` on change, the counts text in a `role="status"` `aria-live="polite"` region, a `<ul>` of `YearEndItemRow`s ordered by `orderItems`
    - `useAsyncResource` with `useFirstLoad` (property id as reset key): skeleton on first load, previous content kept with the refreshing indicator on reload, error `StateBlock` with retry; no control that changes data
    - _Requirements: 2.5, 19.1, 19.2, 19.3, 19.4, 19.5, 19.7, 19.8, 19.9, 19.10, 20.4, 20.5_
  - [x] 8.3 Build `YearEndSummarySection` and add it to the property page
    - `frontend/src/components/year-end-checklist/YearEndSummarySection.tsx` loads `getPropertySummary`, one row per year with `summaryHeadline`, done and not-applicable counts, and a link to `/properties/{id}/checklist?year={year}`; skeleton first, previous content kept on reload, error `StateBlock` with retry, empty state linking to Transactions
    - Render it below the tile grid in `frontend/src/pages/PropertyDetailPage.tsx`; a failure inside it leaves the tiles usable
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 20.1, 20.2_
  - [x] 8.4 Build `YearEndDashboardCard` and add it to the dashboard
    - `frontend/src/components/year-end-checklist/YearEndDashboardCard.tsx` with prop `taxYear: number | null`, its own `useAsyncResource` for `getPortfolioSummary(taxYear)`, a row per property with its needs-attention count linking to that property's checklist for the year, omitted when the user owns no property, error state with retry inside the card, own skeleton while `taxYear` is `null`
    - In `frontend/src/pages/DashboardPage.tsx` pass `latestYear?.tax_year` from the trends headline once loaded, `latestCompletedTaxYear()` when trends failed, and `null` while loading; add no year selector and make the card independent of the other dashboard requests
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 20.1_
  - [x] 8.5 Add the Checklist tab and route
    - Append `{ segment: "checklist", label: "Checklist" }` to `PROPERTY_NAV` in `frontend/src/components/navConfig.ts`; add `{ path: "checklist", element: <YearEndChecklistPage /> }` and update the route comment in `frontend/src/routes.tsx`
    - Update `navConfig.test.ts`, `PropertySectionTabs.test.tsx` and the property switcher tests where they list the tabs, and confirm the switcher keeps the section and the `year` parameter
    - _Requirements: 19.1, 19.11_
  - [x] 8.6 Write page and component tests
    - New tests for `YearEndChecklistPage` (loading, error with retry, all clear, mixed statuses, empty year, needs-attention-first order, disclaimer in every state, no mutating button, year default and `year` parameter, list role, live region, link accessible names), `YearEndSummarySection` (skeleton then retained content, error, empty state, year links), `YearEndDashboardCard` (rows and links, reload on `taxYear` change, omitted without a property, error inside the card, renders while trends are pending or failed), and `YearEndItemDetails` (unknown shape renders nothing); confirm `pageConformance.test.ts` needs no allowlist entry
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8, 19.9, 19.10, 20.4, 20.5, 20.6, 22.11_
  - [x] 8.7 Write the no-hard-coded-threshold source scan
    - New test under `frontend/src/components/year-end-checklist/` asserting that no numeric literal other than `0`, `1` and `-1` appears in non-string code of the new feature files
    - _Requirements: 3.5, 22.12_
  - [x] 8.8 Add accessibility and browser coverage
    - Add canned checklist and summary responses to `frontend/src/test/apiStub.ts` and `frontend/src/test/fixtures.ts`, add `["checklist", `${P}/checklist`]` to `ROUTES` in `frontend/e2e/a11y.spec.ts`, and add the three API stubs to `frontend/e2e/fixtures.ts`; the page passes axe in light and dark themes with one `h1`
    - _Requirements: 20.3, 22.11_

- [x] 9. Documentation
  - [x] 9.1 Update `docs/api.md`
    - Document the three routes, the `taxYear` parameter and its default, the response shapes, the `details` keys per item, and the `400` and `404` cases
    - _Requirements: 23.1_
  - [x] 9.2 Update `docs/data-model.md`
    - State that the checklist stores no data and list the existing data each item reads
    - _Requirements: 23.2_
  - [x] 9.3 Update `docs/developer-guide.md`
    - Document the Item_Ids, the Checklist_Config and how to change a threshold, the Applicable_Loan rule, how to add an item (one rule function plus one `ITEM_IDS` entry), the `YearEnd` file prefix, and the `provider_for(wiring, user)` hook with its `ChecklistProvider` return type and the note that the accountant package imports it at run time
    - _Requirements: 23.3, 23.5, 24.5_
  - [x] 9.4 Update `docs/testing.md`
    - Describe the new backend and frontend property tests, the read-only and read-sharing tests, the provider contract test, and the source-scan tests
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.8, 22.12, 22.14_
  - [x] 9.5 Update `CHANGELOG.md`
    - Record the Year-end checklist: three routes, the Checklist tab, the property page section, the dashboard card, and the `?year=` support on Transactions and Reports (if this work added it), and the `provider_for` hook used by the accountant package
    - _Requirements: 23.4_
  - [x] 9.6 Update `README.md`
    - Add the Year-end checklist to the feature list with a line that it is a read-only reminder aid and not tax advice
    - _Requirements: 23.4_

- [x] 10. Final checkpoint - full verification
  - Ensure backend `pytest`, frontend `vitest`, `npm run lint`, `npm run build` and the type check pass, ask the user if questions arise.

## Notes

- Every leaf task is required. There are no optional sub-tasks in this plan.
- The pure rule layer (tasks 1 and 2) is the core. The gatherer and routes (tasks 4 and 5) add no rules of their own.
- Tasks that write the same file sit in different waves: `services/checklist.py` (2.1, 2.2, 2.3, 2.4, 4.1, 5.4), `router/handler.py` (5.1, 5.4), `TransactionsPage.tsx` and `ReportsPage.tsx` (7.2), `PropertyDetailPage.tsx` (8.3), `DashboardPage.tsx` (8.4).
- The nav entry and route (8.5) come after the page exists so no tab ever points at a missing page.
- Query parameter is `taxYear` everywhere; response bodies keep `tax_year`.
- Task 7.2 is conditional: it adds `parseYearParam` and the `?year=` initializers only if the `ui-polish` work has not already added them, and reuses them otherwise. Task 5.4 is the hook the `accountant-package` spec imports at run time.
- No deploy and no commit are part of this plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "7.1", "7.3"] },
    { "id": 1, "tasks": ["1.5", "1.6", "2.1", "7.2", "7.4", "7.5", "8.1"] },
    { "id": 2, "tasks": ["2.2", "2.7", "2.18", "2.19", "8.2", "8.3", "8.4"] },
    { "id": 3, "tasks": ["2.3", "2.8", "2.9", "2.10", "2.11", "8.5", "8.6", "8.7"] },
    { "id": 4, "tasks": ["2.4", "2.12", "2.13", "2.14", "8.8"] },
    { "id": 5, "tasks": ["2.5", "2.6", "2.15", "2.16", "2.17", "2.20", "4.1"] },
    { "id": 6, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "5.1", "9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["5.2", "5.3", "5.4", "9.1", "9.5", "9.6"] },
    { "id": 8, "tasks": ["5.5"] }
  ]
}
```
