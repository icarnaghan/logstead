# Implementation Plan: Itemized Expenses

## Overview

This plan adds optional itemized detail behind a year's repairs total (Schedule E line 14), a new Repairs tab and page, and the explicit precedence rule that keeps itemized entries from double counting an entered total. The design is an additive `itemized` marker on transactions, one pure precedence function (`LineAccumulator` in `services/itemized.py`) used by the report builder and the new summary, configuration-driven categories (`repairs` only), and new `/properties/{propertyId}/itemized/{categoryId}/...` routes. Receipts reuse the existing transaction receipt routes.

Languages: Python 3.12 (backend) and TypeScript/React (frontend), as in the design. Backend tests use pytest, Hypothesis and moto. Frontend tests use vitest, fast-check and React Testing Library. Every property-based test runs at least 100 iterations and is tagged `# Feature: itemized-expenses, Property N: ...` (`//` in TypeScript).

Ordering: the backend data model and the pure resolver come first, then validation, report integration, the service, the routes, and backup. Frontend work starts from the API types and pure helpers, builds the page components, wires the route and nav entry once the page exists, then updates the Transactions page and the docs. This is a spec-only deliverable; implementation happens task by task later. Nothing here deploys or commits.

## Tasks

- [x] 1. Backend: data model and precedence core
  - [x] 1.1 Add the itemized marker and notes to the transaction model and storage mapping
    - In `backend/src/logstead/models/transaction.py` add `itemized: bool = False` and `notes: str | None = None` to `Transaction` and `TransactionInput`
    - In `backend/src/logstead/services/transaction.py` update `transaction_to_item` to write `itemized` only when true and `notes` only when set (a `None` value is dropped by the repository), and `_from_item` to read `bool(item.get("itemized", False))` and `notes`
    - Pass `itemized` and `notes` from `TransactionInput` into the `Transaction` built by `create` and `update` without adding validation yet
    - Keep every existing construction site compiling with the defaults
    - _Requirements: 4.1, 12.1, 12.2, 12.3_
  - [x] 1.2 Create `backend/src/logstead/services/itemized.py` with the configuration and the pure resolver
    - Define `ItemizedCategory`, `ITEMIZED_CATEGORIES = {"repairs": ...}`, and `is_itemized_category`
    - Define `LineSource`, the frozen `LineResolution` (line total, source, entered total, entered total row count, itemized sum, itemized count, remainder, total imported flag), and `LineAccumulator` with `add(amount, *, itemized, imported=False)` and `resolve()`
    - Use `Decimal` and `to_money` only; present means at least one unmarked row; never add the itemized sum to a present total
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.1, 11.6, 14.1_
  - [x] 1.3 Write property tests for the resolver
    - **Property 1: Precedence of total over itemized detail**
    - **Property 2: Itemized detail never changes a present total**
    - **Property 3: Amounts stay exact and two-decimal**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.9, 14.1, 14.3**
    - New `backend/tests/services/test_itemized_line_resolver_property.py`
  - [x] 1.4 Write the storage round-trip property test
    - **Property 13: Entry fields round-trip through storage**
    - **Validates: Requirements 12.1, 12.2, 12.3**
    - New `backend/tests/services/test_itemized_storage_roundtrip_property.py`; include legacy items without the attributes and defaults producing the pre-feature item shape

- [x] 2. Backend: transaction validation and marker preservation
  - [x] 2.1 Validate itemized entries and protect the marker in `TransactionService`
    - In `create` and `update` (`_validate`): when `itemized` is true require a category in `ITEMIZED_CATEGORIES` (error on `category_id`), type `expense`, a non-blank description of 1 to 200 characters after trimming, and allow `notes` of at most 1000 characters (blank becomes absent); when `itemized` is false reject `notes` with a validation error on `notes`
    - In `update` reject `data.itemized != existing.itemized` with a validation error on `itemized` and leave the stored row unchanged
    - Leave `delete` and the receipt methods unchanged
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.8, 2.12, 10.5, 10.6, 11.4_
  - [x] 2.2 Write property tests for validation
    - **Property 10: The itemized marker is immutable through updates**
    - **Property 11: Only configured categories accept itemized entries**
    - **Property 12: Entry date must fall in the stated tax year**
    - **Validates: Requirements 2.6, 2.12, 10.5, 11.2, 11.4**
    - New `backend/tests/services/test_itemized_validation_property.py`; Property 12 is exercised through `ItemizedExpenseService.create_entry` once task 4.1 exists, so build that case against the service and mark it skipped until then if needed
  - [x] 2.3 Preserve the `imported` and `itemized` markers on generic updates
    - In `TransactionService.update` build the updated `Transaction` with `imported=existing.imported` and `itemized=existing.itemized`, ignoring `data.imported`; keep `create` honoring `data.imported` for Schedule E Import
    - Confirm `_transaction_input` in `router/handler.py` does not read `imported`, `itemized` or `notes`; do not change create or update body handling otherwise
    - Land this before the report precedence work is relied on, since the rule depends on telling imported totals apart
    - _Requirements: 19.1, 19.2, 19.3, 19.5, 19.6_
  - [x] 2.4 Write tests for marker preservation and the re-import-after-edit regression
    - **Property 19: Updates preserve the stored markers and re-import never duplicates a total**
    - **Validates: Requirements 19.1, 19.2, 19.3, 19.4**
    - New `backend/tests/services/test_imported_marker_update_property.py` over moto; add the regression example (import a repairs total, edit it through the generic update, re-import, assert one total row and the re-imported line total) and a router test that the generic create and update bodies cannot set or clear `imported` or `itemized`

- [x] 3. Backend: report integration
  - [x] 3.1 Resolve line totals through `LineAccumulator` in `ReportingService._build_report`
    - Replace the per-line running sums with one `LineAccumulator` per line fed `itemized = txn.itemized and is_itemized_category(txn.category_id)` and the imported marker
    - Set `line_totals[line]` and `line_imported[line]` from `resolve()` before the Line 12 loan precedence block; keep line 18, line 12 and line 19 itemization behavior unchanged
    - _Requirements: 4.5, 5.9, 6.1, 6.5, 6.6, 6.7_
  - [x] 3.2 Write the unchanged-sum property test
    - **Property 4: Rows outside the itemized rule sum as before**
    - **Validates: Requirements 4.1, 4.5, 6.6, 11.7, 12.2**
    - New `backend/tests/services/test_itemized_non_itemized_sum_property.py` using the real `ReportingService` over moto against a plain-sum model

- [x] 4. Backend: itemized expense service
  - [x] 4.1 Add `ItemizedExpenseService` to `backend/src/logstead/services/itemized.py`
    - Implement `summary`, `create_entry`, `update_entry`, `delete_entry`, `set_total`, `remove_total` as described in the design, delegating to `TransactionService` and using `LineAccumulator` for the summary (including `total_differs_from_itemized`)
    - Category checks: unknown id is `not_found`, known but not enabled is a validation error on `category_id`
    - Entry operations first confirm the row is an itemized entry of the named category, else `not_found`
    - `set_total` creates one `{year}-12-31` expense row when none exists, updates a single row in place preserving id, date, description, `imported` and receipts, and returns `conflict` on field `total` for several rows; `remove_total` follows the same rules and returns `not_found` for none
    - Define the frozen `ItemizedSummary` and `EntryInput` dataclasses; reject an entry whose date year differs from a supplied `tax_year` with a validation error on `date`
    - _Requirements: 2.1, 2.6, 2.8, 2.9, 5.7, 5.8, 8.2, 8.4, 8.5, 8.6, 8.7, 9.5, 11.2, 11.3, 11.4, 13.3_
  - [x] 4.2 Write property tests for service operations
    - **Property 6: Entry operations and total operations are independent**
    - **Property 7: Total operations behave as specified**
    - **Property 8: Sync sets the total to the itemized sum and Undo restores it**
    - **Property 9: Several total rows block total operations**
    - **Validates: Requirements 2.8, 5.7, 5.8, 8.2, 8.4, 8.5, 8.6, 9.5, 9.6, 15.4**
    - New `backend/tests/services/test_itemized_service_property.py` over moto
  - [x] 4.3 Write the agreement property test and the source-scan test
    - **Property 5: Report, summary and downstream consumers agree**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    - New `backend/tests/services/test_itemized_report_agreement_property.py` comparing the report, the summary, `DashboardService`, `CarryforwardService`, the combined report, and the CSV and JSON exports
    - Add a source-scan example asserting `dashboard.py` and `carryforward.py` reference neither `schedule_e_line` nor `itemized`

- [x] 5. Backend: routes and authorization
  - [x] 5.1 Add the itemized handlers and routes in `backend/src/logstead/router/handler.py`
    - Add `_itemized_service(wiring)`, `_entry_input(body, property_id)` (using `_opt_str`, `_decimal_or_none`, `_int_param`), and six `@_property_scoped` handlers: summary, create entry (201), update entry, delete entry, set total, remove total
    - Register the routes from the design in `_ROUTES`; ignore `itemized`, `imported`, `type` and `property_id` in bodies
    - Confirm the generic `_transaction_input` still does not read `itemized` or `notes`
    - _Requirements: 4.6, 11.2, 13.1, 13.4, 13.5, 13.6_
  - [x] 5.2 Write router and cross-user tests
    - New `backend/tests/router/test_itemized_routes.py`: success and field-identifying validation per route, body extras ignored, generic create cannot set the marker, existing route matching still works
    - Extend `backend/tests/router/test_cross_user_authorization.py`: user A creates an entry and a total, user B gets a 404 byte-identical to a missing id on every new route and on the entry's receipt routes, and A's data is untouched
    - _Requirements: 4.6, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7_

- [x] 6. Backend: backup and import
  - [x] 6.1 Carry `itemized` and `notes` through backup export, validation and restore
    - In `backend/src/logstead/models/backup.py` add `itemized: bool = False` and `notes: str | None = None` to `BackupTransaction`; keep `SCHEMA_VERSION = "1"`
    - In `backend/src/logstead/services/backup.py` export both fields, parse them with defaults, validate type (boolean, string of at most 1000 characters) and that `itemized` true requires an Itemized_Category and type `expense`, and pass them into the restored `Transaction`
    - Reject invalid documents before any write with a validation error on `itemized` or `notes`
    - _Requirements: 12.4, 12.5, 12.6, 12.7, 12.9_
  - [x] 6.2 Write backup property tests and examples
    - **Property 14: Backup round trip preserves itemized data**
    - **Property 15: Restore rejects invalid itemized fields and writes nothing**
    - **Validates: Requirements 12.4, 12.6, 12.7, 12.8**
    - New `backend/tests/services/test_itemized_backup_property.py`; add examples for a legacy document without the fields and the unchanged sample fixture
  - [x] 6.4 Carry `imported` through backup export, validation and restore
    - In `backend/src/logstead/models/backup.py` add `imported: bool = False` to `BackupTransaction`; keep `SCHEMA_VERSION = "1"`
    - In `backend/src/logstead/services/backup.py` export `imported`, parse it with default false, reject a non-boolean value with a validation error on `imported`, reject `imported` and `itemized` both true with a validation error on `itemized`, and pass it into the restored `Transaction`; all checks run before any write
    - Add the optional `imported` field to the frontend backup types and confirm the sample fixture stays valid
    - Land this before the report precedence work is relied on, since the rule depends on telling imported totals apart
    - _Requirements: 12.9, 20.1, 20.2, 20.3, 20.4_
  - [x] 6.5 Write backup tests for the imported marker
    - **Property 20: Backup round trip preserves the imported marker**
    - **Validates: Requirements 20.1, 20.2, 20.3, 20.4, 20.5**
    - New `backend/tests/services/test_backup_imported_property.py`; add examples for an older backup without `imported` restoring with `imported = false`, and restore followed by Schedule E re-import leaving one total row (Requirement 20.6)
  - [x] 6.3 Write the re-import property test
    - **Property 16: Schedule E re-import leaves itemized entries unchanged**
    - **Validates: Requirements 4.3, 4.4**
    - New `backend/tests/services/test_itemized_reimport_property.py`; also assert imported summary rows have `itemized` false

- [x] 7. Checkpoint - backend
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 8. Frontend: API module, types and undo helpers
  - [x] 8.1 Add `frontend/src/api/itemized.ts` and extend the transaction type
    - `ItemizedApi` class with injectable client and the shared `itemizedApi`: `getSummary`, `createEntry`, `updateEntry`, `deleteEntry`, `setTotal`, `removeTotal`, plus the `ItemizedSummary` and entry input types
    - Add optional `itemized` and `notes` to `Transaction` in `frontend/src/api/transactions.ts`
    - Add API unit tests in `frontend/src/api/itemized.test.ts` for paths, query strings and bodies
    - _Requirements: 2.1, 8.2, 9.5, 11.2, 14.1_
  - [x] 8.2 Extend `frontend/src/lib/undoMappers.ts`
    - `isTransactionSafeDelete` returns false for itemized transactions; add `isItemizedEntrySafeDelete(entry, receiptCount)` (true only for a known zero count) and `itemizedEntryToInput(entry)`
    - _Requirements: 10.7, 15.1, 15.2_
  - [x] 8.3 Write the classification property test
    - **Property 18: Undo safety classification for itemized entries and totals**
    - **Validates: Requirements 10.7, 15.2**
    - Extend `frontend/src/lib/undoClassification.property.test.ts`; add an entry and total case to `frontend/src/lib/undoIds.test.tsx` for new ids after Undo

- [x] 9. Frontend: pure helpers and page definition
  - [x] 9.1 Create `frontend/src/lib/itemizedMath.ts` and `frontend/src/lib/itemizedPages.ts`
    - `itemizedMath`: integer-cents helpers `syncVisible`, `syncLabel`, `deltaCents`, `describeChange` built on `toCents`, `centsToMoney` and `formatMoney`
    - `itemizedPages`: `ItemizedPageDefinition` and `ITEMIZED_PAGES` with the `repairs` definition (category id, tab label, line 14, noun, intro text, capital improvement note flag)
    - _Requirements: 9.1, 9.2, 9.3, 11.5, 11.6, 14.2_

- [x] 10. Frontend: Repairs page
  - [x] 10.1 Build the presentational components in `frontend/src/components/itemized/`
    - `ItemizedSummaryPanel` (description list of total, itemized sum and count, remainder with text flag and "Over total" badge, line total, source label), `EnteredTotalCard` (set, edit, remove, Imported badge and re-import hint, Documents toggle for a single row, multi-row explanation with Transactions link), `ItemizedEntryList` (`ResponsiveTable`, Documents, Edit, Delete with accessible names including date and description), `ItemizedEntryForm` and `TotalForm` (`FormField`, `DateInput`, `MoneyInput`, `Input`, `Textarea`, `ErrorSummary`, `useFocusFirstInvalid`, `useDirtyReporter`)
    - Reuse `ReceiptList` unchanged
    - _Requirements: 2.7, 2.10, 2.11, 3.1, 3.3, 3.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9, 7.10, 8.1, 8.3, 8.6, 8.7, 16.1, 16.3, 16.5, 16.6_
  - [x] 10.2 Build `SyncTotalDialog` in `frontend/src/components/itemized/SyncTotalDialog.tsx`
    - `ConfirmDialog` naming the line, tax year, current total, new total and signed difference in cents; add the filed-return warning when the tax year is a completed tax year
    - _Requirements: 9.3, 9.4, 9.9, 16.1_
  - [x] 10.3 Assemble `ItemizedExpensesPage` and `RepairsPage`
    - `frontend/src/pages/ItemizedExpensesPage.tsx` (definition prop, injectable `api`) with `PropertySection`, year selector defaulting to the latest completed tax year and honoring the `year` search parameter, `useAsyncResource`, `useFirstLoad`, `StateBlock` error and retry, add-entry `RecordModal`, the Assets note with a link built by `propertyPath(propertyId, "assets")`, and `useDocumentTitle`
    - Flows: entry create, edit, delete with `useUndoableDelete` (receipt count lookup; confirm dialog otherwise); total set, edit and remove; sync with the dialog, success toast and Undo action that sets the previous amount; error toasts and summary refresh on failures
    - `frontend/src/pages/RepairsPage.tsx` default export using `ITEMIZED_PAGES.repairs`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.7, 1.8, 1.9, 2.1, 2.7, 7.11, 8.2, 8.4, 8.5, 8.8, 8.9, 9.5, 9.6, 9.7, 9.8, 15.1, 15.2, 15.3, 15.5, 16.4_
  - [x] 10.4 Write the frontend oracle property test
    - **Property 17: The page's displayed amounts match the integer-cents oracle**
    - **Validates: Requirements 7.2, 7.3, 9.1, 9.2, 9.3, 14.2**
    - New `frontend/src/lib/itemizedMath.property.test.ts` plus an RTL property test rendering `ItemizedSummaryPanel` and `SyncTotalDialog` with generated amounts
  - [x] 10.5 Write page and component tests
    - New `frontend/src/pages/ItemizedExpensesPage.test.tsx` and component tests: loading, error, empty, total only, itemized only, both with positive and negative remainder, source labels, sync visibility, dialog text with and without the completed-year warning, sync success, failure and cancel, Undo flows, multi-row state, Imported badge and hint, year search parameter, and a render with a second fake definition
    - _Requirements: 1.4, 1.5, 1.7, 1.8, 7.1, 7.4, 7.11, 7.5, 7.7, 7.8, 7.10, 8.1, 8.3, 8.6, 8.8, 8.9, 9.4, 9.7, 9.8, 9.9, 11.5, 15.1, 15.2, 15.5_

- [x] 11. Frontend: navigation, routing and accessibility coverage
  - [x] 11.1 Add the Repairs tab and route
    - Insert `{ segment: "repairs", label: "Repairs" }` after Transactions in `PROPERTY_NAV` (`frontend/src/components/navConfig.ts`); add `{ path: "repairs", element: <RepairsPage /> }` and update the comment in `frontend/src/routes.tsx`
    - Update `navConfig.test.ts`, `PropertySection.test.tsx`, `PropertySectionTabs.test.tsx`, `propertySwitch.property.test.ts` and `PropertyDetailPage.test.tsx` where they list the tabs
    - _Requirements: 1.1, 1.2, 1.6_
  - [x] 11.2 Add accessibility and browser coverage
    - Add canned summary responses to `frontend/src/test/apiStub.ts` and `frontend/src/test/fixtures.ts` so the axe route suite renders the page, add `repairs` to `ROUTES` in `frontend/e2e/a11y.spec.ts` and the new API route to `frontend/e2e/fixtures.ts`
    - _Requirements: 16.2_

- [x] 12. Frontend: Transactions page changes
  - [x] 12.1 Mark itemized rows in `TransactionList`
    - Show an "Itemized" `Badge` in the date cell and replace Edit and Delete with a "Manage on Repairs page" link (with the `year` search parameter and an `sr-only` suffix naming the date); keep the Documents button
    - _Requirements: 10.1, 10.2, 16.5_
  - [x] 12.2 Add the note and the form hint
    - In `frontend/src/pages/TransactionsPage.tsx` render the informational line when any listed row is itemized and pass an `itemizedYears` set to `TransactionForm`
    - In `frontend/src/components/transactions/TransactionForm.tsx` show the hint from Requirement 10.4 for category Repairs in a year with itemized entries; do not block saving
    - _Requirements: 10.3, 10.4_
  - [x] 12.3 Write Transactions page tests
    - Extend `TransactionList.test.tsx`, `TransactionForm.test.tsx` and `TransactionsPage.test.tsx` for the badge, link, hidden Edit and Delete, the note, and the hint
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 13. Documentation
  - [x] 13.1 Add the mobile property tabs and itemized conversion items to `docs/future-improvements.md`
    - A short section stating the property tabs now number six, that their mobile layout needs revisiting, and that this feature did not change it
    - A short section stating that converting existing repairs transactions into itemized entries is not part of this feature and that existing transactions remain entered totals
    - _Requirements: 17.1_
  - [x] 13.2 Update `docs/developer-guide.md`
    - Add rows for itemized entries and re-created totals to the "Undo and record IDs" table; describe the Repairs page, the itemized marker, the single location of the precedence rule, and that a backup made with this feature should be restored with it; add the optional-detail note to the year-end Schedule E model section
    - _Requirements: 15.3, 17.2, 17.3_

- [x] 14. Final checkpoint - full verification
  - Ensure backend `pytest`, frontend `vitest`, `npm run lint` and `npm run build` pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks; skip them for a faster MVP, but the properties are what protect the no-double-counting rule.
- The marker, the resolver, and the report change (tasks 1 to 3) are the core. The page is useful only once tasks 4 and 5 exist.
- Tasks 2.3 and 6.4 fix two existing defects (generic updates dropping `imported`, backups not carrying `imported`) and sit in the same wave as the report precedence work (3.1) so imported totals are distinguishable when the rule lands.
- Waves keep tasks that write the same file apart: `services/transaction.py` (1.1, 2.3, 2.1), `services/backup.py` and `models/backup.py` (6.4, 6.1), `services/itemized.py` (1.2, 4.1), `router/handler.py` (5.1), `TransactionsPage.tsx` (12.2).
- The nav entry and route (11.1) come after the page exists so no tab ever points at a missing page.
- No deploy and no commit are part of this plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "8.1", "9.1", "13.1"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.3", "3.1", "6.4", "8.2", "10.1", "10.2"] },
    { "id": 2, "tasks": ["2.1", "2.4", "3.2", "6.1", "6.5", "8.3", "10.3", "12.1"] },
    { "id": 3, "tasks": ["2.2", "4.1", "6.2", "6.3", "10.4", "10.5", "11.1", "12.2"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.1", "11.2", "12.3", "13.2"] },
    { "id": 5, "tasks": ["5.2"] }
  ]
}
```
