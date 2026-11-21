# Implementation Plan: Loan Balance Anchor

## Overview

This plan changes the already-implemented mortgage-amortization feature in place. It replaces the origination input model (original principal, term, first payment date, payment override) with the balance-anchor model (rate, monthly payment, anchor balance, anchor date), adds override-only rollups for years before and including the anchor year, and updates the Loans page and preview.

The mortgage-amortization feature was never merged or deployed, so there are no real old-shape loans. This plan has no legacy conversion and no migration. A stored or backed-up loan without the anchor fields is simply invalid: the strict reader raises `StoredLoanError` naming the missing field and backup validation rejects it with the usual property, loan, and field message. Implementation continues on the existing branch `feat/mortgage-amortization` (same merge request), so every task modifies the existing code in place.

Existing seams stay: key layout, `LoanService` method names, atomic rollup writes, strict readers, Line 12 precedence, `line-12-impact`, dashboard and carryforward hooks, and backup flow. Backend is Python (pytest, Hypothesis, moto). Frontend is TypeScript (vitest, React Testing Library, fast-check).

Property tests replace or extend the existing test files named in each task. If an optional property task is skipped, the old test module it would replace still exercises removed fields and fails; delete that module in task 3.15.

## Tasks

- [x] 1. Backend models and pure engine
  - [x] 1.1 Update `backend/src/logstead/models/loan.py` to the anchor shape
    - Replace `LoanInput` and `Loan` fields: remove `term_months`, `first_payment_date`, `payment_override`; add `monthly_payment`, `anchor_balance`, `anchor_date`; make `original_principal` optional (`Decimal | None`)
    - Make `YearlyRollup.ending_balance` and `YearlyRollupView.ending_balance` `Decimal | None`
    - Replace `LoanView` derived fields `default_payment` and `scheduled_payment` with `remaining_payments`, `next_payment_date`, `projected_payoff_date`; keep `payoff_balance` and `status`
    - Add constants `MAX_PAYMENTS = 600` and `MIN_ANCHOR_YEAR = 1900`
    - _Requirements: 1.2, 2.6, 4.1, 4.3, 5.1, 8.2_

  - [x] 1.2 Rewrite the projection engine in `backend/src/logstead/services/loan.py`
    - Add `ScheduleError(field, message)`; make `payment_date(anchor, index)` (index >= 1) raise `ScheduleError("anchor_date", ...)` past year 9999
    - Rewrite `compute_payment_rows` to start at the anchor: first row at anchor plus 1 month, clamp from the anchor day, final sweep row when `balance + interest <= payment + extra`, payoff-date stop, `ScheduleError("monthly_payment", ...)` before a 601st row; remove the `term` branch and the principal clamp
    - Delete `default_payment` and remove it from `__all__` and the module docstring (its only callers were the old engine and `LoanService._view`, both rewritten)
    - Add `override_year_allowed(tax_year, anchor_year, generated_years)`
    - Extend `build_yearly_rollups` to add Override_Only_Rollups (payments 0, zeros, `ending_balance=None`) for override years without rows, sorted by year
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.12, 2.13, 2.14, 2.15, 3.1, 3.3, 3.4, 5.1, 5.2, 5.3, 5.4, 6.2_

  - [x] 1.3 Rewrite `validate_loan_fields` and `ValidatedLoan` for the anchor shape
    - Validate description, rate, `monthly_payment`, `anchor_balance`, strict `anchor_date` (>= 1900-01-01), payment greater than first-month interest, `extra_principal`, `payoff_date` (>= next payment date), optional `original_principal`, optional `closing_date` (format only, no relation check)
    - After all field checks pass, run `compute_payment_rows` on a draft and map `ScheduleError` to a validation error on its field; keep collecting every error and the `errors` tuple
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.14, 2.15, 3.2, 3.5, 4.2, 4.4_

  - [x] 1.4 Update item builders and strict readers in `services/loan.py`
    - `loan_to_item`: emit `monthlyPayment`, `anchorBalance`, `anchorDate`, optional `originalPrincipal`; drop `termMonths`, `firstPaymentDate`, `paymentOverride`; update `_LOAN_MONEY` to `monthlyPayment, anchorBalance, extraPrincipal, originalPrincipal`
    - `rollup_to_item`: omit `endingBalance` when `None`; `_rollup_from_item`: read it with `_stored_opt_money`
    - `_loan_from_item`: parse only the anchor shape; a missing required attribute (`monthlyPayment`, `anchorBalance`, `anchorDate`) or any unparseable value raises `StoredLoanError(field)` naming the field; remove the origination-attribute parsing and add no fallback
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 1.5 Generate the shared projection vectors
    - Using a one-off script run against the new engine, write about 60 vectors to `frontend/src/data/loan-projection-vectors.json` with the fields listed in the design (inputs plus remaining payments, next payment date, projected payoff date, payoff balance, final payment, total interest); include rate 0, payoff-date truncation, month-end anchors, leap day, exactly 600 rows
    - Spot-check a few vectors against an independent calculator
    - Delete `backend/tests/services/test_loan_default_payment_property.py` (it tests the deleted `default_payment`)
    - _Requirements: 2.3, 2.4, 2.5, 10.6_

  - [x] 1.6 Write property test for row arithmetic and balance recurrence
    - **Property 1: Row arithmetic and balance recurrence**
    - Rewrite `backend/tests/services/test_loan_engine_property.py` with a `Fraction` oracle
    - **Validates: Requirements 2.3, 2.4, 2.8, 2.10, 2.13, 3.1**

  - [x] 1.7 Write property test for schedule shape, dates, termination, and determinism
    - **Property 2: Schedule shape, dates, termination, and determinism**
    - New file `backend/tests/services/test_loan_engine_shape_property.py` using `calendar` as the date oracle
    - **Validates: Requirements 2.1, 2.2, 2.5, 2.6, 2.7, 2.11, 2.12**

  - [x] 1.8 Write property test for principal conservation
    - **Property 3: Principal conservation**
    - New file `backend/tests/services/test_loan_engine_conservation_property.py`
    - **Validates: Requirements 2.9, 3.4, 3.6**

  - [x] 1.9 Write property test for extra principal monotonicity
    - **Property 5: Extra principal never makes a loan slower or costlier**
    - New file `backend/tests/services/test_loan_engine_extra_property.py`
    - **Validates: Requirements 3.8**

  - [x] 1.10 Write property test for payoff-date prefix truncation
    - **Property 6: Payoff date truncates the schedule to a prefix**
    - New file `backend/tests/services/test_loan_engine_payoff_property.py`
    - **Validates: Requirements 3.3, 3.7**

  - [x] 1.11 Write property test for re-anchoring consistency
    - **Property 7: Re-anchoring consistency**
    - New file `backend/tests/services/test_loan_engine_reanchor_property.py`; compare dates only when the anchor day is 28 or less
    - **Validates: Requirements 2.1, 2.16**

  - [x] 1.12 Write property test for yearly rollups, anchor year, and override-only rows
    - **Property 8: Yearly rollup consistency, anchor year, and override-only rows**
    - New file `backend/tests/services/test_loan_rollup_property.py`
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 6.2**

  - [x] 1.14 Write golden-vector test for the engine
    - New file `backend/tests/services/test_loan_golden_vectors.py` asserting the engine against `frontend/src/data/loan-projection-vectors.json`
    - _Requirements: 10.6_

- [x] 2. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. LoanService, router, and loan tests
  - [x] 3.1 Update `LoanService` create, update, delete, list, get, and `_write_loan`
    - `_write_loan` builds generated plus override-only rollups and deletes stale rows in one `transact_write`; update the 100-action guard message and field (`interest_overrides`)
    - `update_loan` retains an override only when `override_year_allowed` holds for the new schedule
    - `_view` fills `remaining_payments`, `next_payment_date`, `projected_payoff_date`, `payoff_balance`, `status`; map `ScheduleError` and `StoredLoanError` (including a stored loan missing an anchor field) to `conflict`
    - `earliest_year` returns the minimum of each loan's anchor year and override years
    - _Requirements: 1.1, 1.9, 1.10, 2.6, 2.7, 5.6, 5.7, 6.9, 7.5, 12.3_

  - [x] 3.2 Update `schedule_for`, `set_interest_override`, and `clear_interest_override`
    - `schedule_for` builds yearly views from the Loan plus engine output only (no stored rollup read), including override-only views with `ending_balance=None`
    - Set and clear validate the year with `override_year_allowed`, validate the amount, then rewrite through `_write_loan` (D9); clearing an override-only year removes its row; clearing a year with no override succeeds without a write
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.10, 8.5, 8.6_

  - [x] 3.3 Update the router in `backend/src/logstead/router/handler.py`
    - `_loan_input` maps `monthly_payment`, `anchor_balance`, `anchor_date`, `original_principal`, `closing_date` and the other fields (snake_case and camelCase) through `_loan_decimal`; ignore removed legacy keys
    - Route table, ownership checks, and `_set_interest_override` stay; update the route comment block
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.6, 8.7, 8.8_

  - [x] 3.4 Write property test for serialization round trips
    - **Property 10: Loan serialization round trips**
    - Update `backend/tests/services/test_loan_roundtrip_property.py`
    - **Validates: Requirements 4.1, 4.3, 8.3, 8.4, 8.9, 12.1**

  - [x] 3.5 Write property test for stored rollups equal engine output
    - **Property 11: Stored rollups always equal the engine output, with none stale**
    - Update `backend/tests/services/test_loan_storage_property.py` (sequence of create, update, override set, override clear)
    - **Validates: Requirements 1.1, 1.9, 5.6, 12.2**

  - [x] 3.6 Write property test for payoff set and clear round trip
    - **Property 12: Payoff set and clear is a round trip**
    - New file `backend/tests/services/test_loan_payoff_roundtrip_property.py`
    - **Validates: Requirements 3.9**

  - [x] 3.7 Write property test for exact, scoped delete and list
    - **Property 13: Delete and list are exact and scoped**
    - Update `backend/tests/services/test_loan_storage_property.py` (runs after 3.5)
    - **Validates: Requirements 1.10, 13.4**

  - [x] 3.8 Write property test for override scope
    - **Property 14: An override replaces estimated interest for one year and nothing else**
    - Update `backend/tests/services/test_loan_override_property.py`; include years before the anchor year
    - **Validates: Requirements 6.1, 6.2, 6.5**

  - [x] 3.9 Write property test for override retention on update
    - **Property 17: Updates retain exactly the overrides whose year is still permitted**
    - Update `backend/tests/services/test_loan_override_property.py` (runs after 3.8)
    - **Validates: Requirements 6.9**

  - [x] 3.10 Write property test for override set then clear
    - **Property 15: Override set then clear is a round trip with a correct variance**
    - New file `backend/tests/services/test_loan_override_roundtrip_property.py`
    - **Validates: Requirements 6.6, 6.7, 6.8**

  - [x] 3.11 Write property test for invalid overrides
    - **Property 16: Invalid overrides are rejected and storage format is fixed**
    - Add to `backend/tests/services/test_loan_override_roundtrip_property.py` (runs after 3.10)
    - **Validates: Requirements 6.3, 6.4, 6.10**

  - [x] 3.13 Write property test for informational fields
    - **Property 4: Informational fields never affect results**
    - New file `backend/tests/services/test_loan_informational_property.py`
    - **Validates: Requirements 4.1, 4.3, 4.5**

  - [x] 3.14 Write property test for validation
    - **Property 9: Validation rejects every invalid field and writes nothing**
    - Rewrite `backend/tests/services/test_loan_validation_property.py`; include service and router layers, the 600-row cap, and year 9999
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.14, 2.15, 3.2, 3.5, 4.2, 4.4, 8.8**

  - [x] 3.15 Update `backend/tests/services/test_loan_service.py` to the anchor shape
    - CRUD examples, atomic failure injection with a fake repo raising `ClientError`, 100-action guard, strict-read corruption of anchor attributes, a stored item missing `anchorBalance` (raises `StoredLoanError` naming the field and maps to `conflict`), `ScheduleError` mapping, anchor-year and override-only examples
    - Delete any other backend test module that still imports removed fields because its replacing property task was skipped
    - _Requirements: 1.1, 1.9, 1.10, 5.7, 12.3_

  - [x] 3.16 Update router tests to the anchor shape
    - `backend/tests/router/test_loan_routes.py`: new request and response fields, float rejection, override years 1900 to anchor year, `ending_balance: null`, and remove `default_payment` and `scheduled_payment`, identical 404 for missing and foreign property on every Loan route
    - `backend/tests/router/test_loan_line12_impact_route.py`: new loan fixtures
    - _Requirements: 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8_

- [x] 4. Reports, dashboard, and carryforward
  - [x] 4.1 Write property test for Line 12 with override-only years
    - **Property 18: Line 12 uses loan interest or manual interest, never both, including override-only years**
    - Update generators in `backend/tests/services/test_report_line12_property.py` for anchor-shape loans and pre-anchor overrides (including 0.00)
    - **Validates: Requirements 7.1, 7.2**

  - [x] 4.2 Write property test for data years and carryforward
    - **Property 19: Data years and carryforward net include override-only years**
    - Update `backend/tests/services/test_carryforward_loan_property.py`
    - **Validates: Requirements 7.4, 7.5, 7.6**

  - [x] 4.3 Update remaining report-side test fixtures
    - Port loan fixtures in `backend/tests/services/test_report_line12_impact.py` and `backend/tests/services/test_property_delete_loans.py` to the anchor shape; add an example for the anchor-year partial interest superseding manual Line 12 and a pre-anchor override-only year
    - Confirm no source change is needed in `ReportingService`, `dashboard.py`, or `carryforward.py`
    - _Requirements: 7.1, 7.2, 7.3, 13.1, 13.2_

- [x] 5. Backup and restore
  - [x] 5.1 Update `backend/src/logstead/models/backup.py` `BackupLoan`
    - Fields per the design: remove `term_months`, `first_payment_date`, `payment_override`; add `monthly_payment`, `anchor_balance`, `anchor_date`; optional `original_principal`
    - _Requirements: 9.1_

  - [x] 5.2 Update `backend/src/logstead/services/backup.py` export, validation, and restore
    - `_list_loans` maps the strict-read `Loan` to `BackupLoan`
    - `_validate_loan` requires `monthly_payment`, `anchor_balance`, and `anchor_date` (a loan lacking one is rejected with the usual property, loan, and field message), then runs `validate_loan_fields` and `override_year_allowed` against the recomputed schedule; failures name property, loan, and rule; all inside the pre-clear validation phase
    - Restore keeps recomputing generated and override-only rollups; `schema_version` stays `"1"`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.6, 9.7_

  - [x] 5.3 Write property test for backup round trip
    - **Property 20: Backup round trip preserves anchor-shape Loans and overrides**
    - Update `backend/tests/services/test_backup_loan_roundtrip_property.py`
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.5**

  - [x] 5.4 Write property test for invalid Loan rejection
    - **Property 21: An invalid Loan in a backup rejects the whole restore** (include a loan missing `monthly_payment`, `anchor_balance`, or `anchor_date`)
    - Update `backend/tests/services/test_backup_loan_roundtrip_property.py` (runs after 5.3)
    - **Validates: Requirements 9.4**

  - [x] 5.6 Update the sample backup and backup test fixtures
    - Convert the Loan in `frontend/src/data/sample-backup.json` to the anchor shape and add an `interest_overrides` entry for a year before the anchor year
    - Update `backend/tests/router/test_backup_sample_fixture.py`, `backend/tests/services/test_backup_restore.py`, `backend/tests/services/test_backup_clear.py`, and `frontend/src/data/sample-backup.test.ts`; add an example rejecting a loan document whose loan lacks the anchor fields and an example restoring a no-loans document
    - _Requirements: 9.4, 9.7, 12.7_

- [x] 6. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Frontend projection, API types, and form model
  - [x] 7.1 Replace `defaultMonthlyPayment` with `projectLoan` in `frontend/src/lib/amortization.ts`
    - BigInt integer arithmetic: interest cents `(2n*balance*rateScaled + 12_000_000n) / (24_000_000n)`, `paymentDate` with clamp from the anchor day and leap years, final sweep row, payoff-date stop; return `null` for invalid inputs, payment not above first-month interest, more than 600 rows, year over 9999, payoff before the next payment date
    - Rewrite `frontend/src/lib/amortization.test.ts` with hand-written cases; delete `frontend/src/lib/amortization.property.test.ts` (recreated in 7.3)
    - _Requirements: 10.4, 10.5, 10.6_

  - [x] 7.2 Add golden-vector assertions and remove the old vectors
    - Assert `projectLoan` against `frontend/src/data/loan-projection-vectors.json` in `amortization.test.ts`
    - Delete `frontend/src/data/loan-payment-vectors.json`
    - _Requirements: 10.6_

  - [x] 7.3 Write property test for the preview
    - **Property 22: The preview matches the backend and is never stale**
    - New `frontend/src/lib/amortization.property.test.ts` using fast-check against a BigInt oracle
    - **Validates: Requirements 10.4, 10.5, 10.6**

  - [x] 7.4 Update `frontend/src/api/loans.ts` and `frontend/src/api/backup.ts` types
    - `Loan` and `LoanInput` per the design (remove `term_months`, `first_payment_date`, `payment_override`, `default_payment`, `scheduled_payment`); `YearlyRollup.ending_balance: string | null`; `BackupLoan` in the anchor shape
    - Update `frontend/src/api/loans.test.ts` and `frontend/src/api/backup.test.ts`
    - _Requirements: 8.1, 8.2, 8.5, 9.1_

  - [x] 7.5 Update `frontend/src/components/loans/loanFormModel.ts`
    - New `LoanFormValues`, `EMPTY_LOAN_FORM` with an injectable `todayIso()` for the anchor date, `LOAN_FIELD_BY_API_NAME`, `validateLoanForm` mirroring backend rules and using `projectLoan` for the payment-vs-interest, 600-row, and year 9999 messages, and `toLoanInput`
    - Update `loanFormModel.test.ts`
    - _Requirements: 1.2, 1.4, 1.5, 1.6, 1.7, 1.8, 2.14, 2.15, 3.2, 3.5, 4.2, 4.4, 10.1, 10.2_

- [x] 8. Frontend components and page
  - [x] 8.1 Update `LoanForm.tsx` and `LoanForm.test.tsx`
    - New field set with labels, anchor help text linked by `aria-describedby`, anchor date defaulting to today, Loan_Preview from `projectLoan` in a `useMemo` (remaining payments and projected payoff date, or payoff balance when a payoff date truncates), hidden when `null`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 11.9_

  - [x] 8.2 Update `LoanList.tsx` and `LoanList.test.tsx`
    - Columns: description, anchor balance with anchor date, rate, monthly payment, remaining payments with projected payoff date, status
    - _Requirements: 11.1_

  - [x] 8.3 Update `YearlyRollupTable.tsx` and `YearlyRollupTable.test.tsx`
    - Override-only rows (zero payments) show whole-dollar interest and text dashes for principal, total paid, ending balance, no expand control, and an "Override only" text marker; the anchor-year row shows "payments after <anchor date> only" as text; keep expand and collapse with `aria-expanded`
    - _Requirements: 11.2, 11.3, 11.9_

  - [x] 8.4 Write property test for yearly table formatting
    - **Property 23: Yearly table formatting including override-only rows**
    - Update `frontend/src/components/loans/YearlyRollupTable.property.test.tsx`
    - **Validates: Requirements 11.2, 11.3**

  - [x] 8.5 Add `PastYearOverrideForm.tsx` and `AnchorYearNotice.tsx`; update `EstimateNotice.tsx`
    - `PastYearOverrideForm`: year and amount inputs, client rules (integer year 1900 to anchor year, non-negative amount with at most two decimals), points to the row control when the year has payments, shows server `interest_overrides.<year>` errors next to the year field
    - `AnchorYearNotice`: states the anchor year, that generated interest for it covers only payments after the anchor date, and to enter the Form 1098 interest as an override for the anchor year and earlier years
    - `EstimateNotice` copy mentions the anchor; add unit tests for the new components
    - _Requirements: 11.4, 11.5, 11.6, 11.8, 11.9_

  - [x] 8.6 Write property test for the add-override form
    - **Property 24: The add-override form never sends an invalid value**
    - New `frontend/src/components/loans/PastYearOverrideForm.property.test.tsx`
    - **Validates: Requirements 11.5, 11.6**

  - [x] 8.7 Wire hooks and `LoansPage`
    - Update `useLoans.ts`, `useLoanSchedule.ts`, and `frontend/src/pages/LoansPage.tsx` to the new fields; render `AnchorYearNotice` and `PastYearOverrideForm` for the selected Loan; refresh the schedule after override set or clear so an override-only row appears or disappears; keep the superseded-interest notice, delete flow, and navigation
    - Update `frontend/src/pages/LoansPage.test.tsx` (field errors retained, form-level errors, notices, override-only add and remove, delete, axe)
    - _Requirements: 10.7, 10.8, 11.4, 11.5, 11.7, 11.8, 11.9, 13.1_

- [x] 9. Documentation and changelog
  - [x] 9.1 Update `docs/data-model.md` and `backend/tests/infra/test_loan_docs.py`
    - Headings: anchor-shape Loan attributes, Override_Only_Rollup row, Line 12 precedence rule; update backup treatment (anchor shape only; a loan without the anchor fields is rejected on restore); add a short note that the loan input model changed before release, so no migration is needed and any locally created loans must be re-entered
    - Update the heading assertions in `test_loan_docs.py`
    - _Requirements: 12.4_

  - [x] 9.2 Update `docs/api.md`, `CHANGELOG.md`, and `README.md`
    - `docs/api.md`: request and response fields, derived fields, override tax-year range 1900 to anchor year, `ending_balance: null`, and remove `default_payment` and `scheduled_payment`
    - `CHANGELOG.md` Unreleased: describe the anchor model and past-year overrides, replacing wording that describes term-based loans, and note that the loan input model changed before release (no migration needed; any locally created loans must be re-entered); update any README text that lists loan inputs
    - _Requirements: 12.5, 12.6_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Run the backend and frontend suites and the type checks. Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP; skipped property tasks leave obsolete old test modules that task 3.15 deletes.
- Each task references specific requirements for traceability.
- Waves in the dependency graph keep tasks that edit the same file in different waves.
- Property tests validate universal correctness properties; unit tests cover examples, edge cases, and failure injection.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "7.1", "7.4"] },
    { "id": 1, "tasks": ["1.2", "5.1", "7.3", "7.5", "8.2", "8.3", "8.5", "9.1", "9.2"] },
    { "id": 2, "tasks": ["1.3", "1.6", "1.7", "1.8", "1.9", "1.10", "1.11", "1.12", "8.1", "8.4", "8.6"] },
    { "id": 3, "tasks": ["1.4", "8.7"] },
    { "id": 4, "tasks": ["1.5", "3.1", "3.3", "5.2"] },
    { "id": 5, "tasks": ["1.14", "3.2", "5.3", "5.6", "7.2"] },
    { "id": 6, "tasks": ["3.4", "3.5", "3.6", "3.8", "3.10", "3.13", "3.14", "3.15", "3.16", "4.1", "4.2", "4.3", "5.4"] },
    { "id": 7, "tasks": ["3.7", "3.9", "3.11"] }
  ]
}
```
