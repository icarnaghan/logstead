# Implementation Plan: Mortgage Amortization

## Overview

This plan adds a **Loan** entity under a Property. Logstead generates a monthly amortization schedule with a pure `Decimal` engine, stores one yearly rollup row per tax year (GSI2-indexed), and feeds the yearly Effective_Interest into Schedule E Line 12 in the per-property and combined reports. Generated interest takes precedence over hand-entered Line 12 transactions (never both), the superseded manual amount is reported, and the passive-loss carryforward sees the interest through the existing report totals. Users can override interest per year to match Form 1098 through dedicated override routes only.

The approved design decisions this plan follows:

- The payment preview in the form is computed client-side in `frontend/src/lib/amortization.ts` with `BigInt` fixed-point math. A shared golden-vector file, `frontend/src/data/loan-payment-vectors.json`, is asserted by both pytest and vitest so the two implementations cannot drift.
- Interest overrides are managed only through `PUT` and `DELETE /properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}`. The loan create and update bodies carry no overrides; an update preserves overrides whose tax year still has a rollup.
- Loan routes accept `original_principal`, `annual_interest_rate`, `payment_override` and `extra_principal` only as JSON **strings**. A JSON float is a 400 validation error on that field. Money and the rate are never floats anywhere.
- `Error` gains an additive `errors` tuple of `(field, message)` pairs so one failure can name every offending field. Existing clients and tests keep working.

The language is **Python 3.12** (backend: pytest, Hypothesis, moto) and **React 19 + TypeScript** (frontend: vitest, React Testing Library, fast-check). Money stays exact `Decimal` in Python and fixed two-decimal strings or `BigInt` or integer cents in the browser.

**Dependency shape.** `backend/src/logstead/services/loan.py` is written by tasks 2.1, 2.2, 2.3, 3.1, 3.2 and 3.3 in strictly increasing waves. `backend/src/logstead/router/handler.py` is written by 1.2, 5.1, 5.2, 7.3 and 5.3 in increasing waves (5.3 registers the line-12-impact route, so it must follow 6.3 and 7.3). `backend/src/logstead/services/report.py` is written by 6.1, 6.2 and 6.3 in increasing waves. `backend/src/logstead/services/backup.py` is written by 9.2, 9.3, 9.4 and 9.5 in increasing waves. Every addition to an existing constructor or dataclass is a trailing optional argument with a default, so existing positional constructions keep compiling.

**Existing tests the changes force.** Three changes break existing tests and their fixes are **REQUIRED, not optional**:

- The backend report serializers always add the Line 12 rows to CSV and the `line12` object to JSON (task 6.4).
- A report without a `line12` object now renders a "Line 12 source unavailable" indication (Requirement 10.5), so existing frontend report fixtures need a `line12` value (task 13.5).
- `PROPERTY_NAV` gains a "Loans" entry, so `navConfig.test.ts` (which asserts order and labels) must change (task 13.1). Adding a Loan to `sample-backup.json` forces the summary assertions in two sample-fixture tests to change (task 9.6).

Tasks marked `*` are new tests (optional). Each property test runs at least 100 iterations and carries a tag comment `# Feature: mortgage-amortization, Property N: <text>` (`//` in TypeScript).

Housekeeping: the backend venv may need recreating (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"` from `backend/`). iCloud duplicate files (`* 2.*`) may appear; delete them, never commit them. Never deploy and do not commit.

## Tasks

- [x] 1. Keys, models and the additive Error `errors` list
  - [x] 1.1 Add Loan key builders in `backend/src/logstead/repository/keys.py`
    - Add `LOAN_PREFIX = "LOAN#"`, `LOAN_YEAR_MARKER = "#YEAR#"` and `GSI2_LOAN_YEAR_PREFIX = "LOANYR#"`
    - Add `loan_sk(loan_id)`, `loan_list_prefix()`, `loan_year_sk(loan_id, tax_year)`, `loan_year_list_prefix(loan_id)`, `is_loan_year_sk(sk)`, `gsi2_loan_year_sk(loan_id)` and `gsi2_loan_year_prefix()` exactly as in the design
    - Extend the module docstring entity table with `Loan` and `LoanYearRollup` and the GSI2 list with `GSI2PK=PROPERTY#<id>#YEAR#<taxYear>  GSI2SK=LOANYR#<loanId>`; add the new names to `__all__` if the module defines one
    - Confirm `asset_list_prefix()` (`ASSET#`), `SCHED#` and `TXN#` prefixes never match Loan keys
    - _Requirements: 12.1, 12.2, 12.4, 12.5_
    - _Design: Components and Interfaces (Backend: keys.py additions)_

  - [x] 1.2 Add `errors` to `Error` in `backend/src/logstead/models/result.py` and emit it from `_error_body` in `backend/src/logstead/router/handler.py`
    - Add `errors: tuple[tuple[str, str], ...] = ()` as the last field of the frozen `Error` dataclass, and an optional `errors` argument to `Result.failure` (default empty), keeping every existing call valid; document that `field` and `message` still carry the first error
    - In `_error_body`, when `error.errors` is non-empty add `"errors": [{"field": f, "message": m}, ...]`; keep `field` and `message` exactly as today and add nothing when `errors` is empty
    - _Requirements: 1.3, 8.9_
    - _Design: Findings F6; Error Handling_

  - [x] 1.3 Create `backend/src/logstead/models/loan.py` and export it from `backend/src/logstead/models/__init__.py`
    - Define `MAX_MONEY = Decimal("999999999.99")`, `LoanInput`, `Loan`, `PaymentRow`, `YearlyRollup` (with an `effective_interest` property: override if not `None`, else `interest`), `LoanView`, `YearlyRollupView` and `LoanSchedule` exactly as in the design; frozen dataclasses except `LoanInput`
    - `LoanView.status` is `Literal["active", "ended"]`; `LoanSchedule.estimate` is always `True`
    - No `float` fields; money is `Decimal`, the rate is a canonical `Decimal`
    - _Requirements: 1.1, 1.2, 2.1, 3.1, 4.1, 5.1, 5.6, 8.5, 8.6_
    - _Design: Components and Interfaces (Backend: models/loan.py)_

- [x] 2. Pure engine, validation and item builders in `backend/src/logstead/services/loan.py`
  - [x] 2.1 Create the engine: interest, default payment, payment dates, rows and rollups
    - Create `backend/src/logstead/services/loan.py`; implement `monthly_interest`, `default_payment`, `payment_date` (clamp from the original day: Jan 31 to Feb 28 or 29 to Mar 31), `compute_payment_rows(loan) -> (rows, payoff_balance)` and `build_yearly_rollups(loan, rows)` as in the design
    - All arithmetic is `Decimal` inside `decimal.localcontext()` with `prec = 60`, rounded half-up to cents via the existing `to_money`; no `float` anywhere
    - The `k == term` branch sweeps the rounding remainder; a Payoff_Date stops the loop so the truncated schedule is a prefix of the full one; `payoff_balance` is set only when a Payoff_Date leaves a positive balance
    - Rollups group rows by `int(row.date[0:4])`, only for years with rows, with no proration and ending balance taken from the last row of the year
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 2.7, 2.8, 2.9, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 7.1_
    - _Design: Components and Interfaces (services/loan.py pure engine); Findings F4, F5_

  - [x] 2.2 Add `validate_loan_fields` to `backend/src/logstead/services/loan.py`
    - Collect every offending field: `description` (strip, 1 to 200), `original_principal` (present, finite, at most 2 dp rejected not rounded, `> 0` and `<= MAX_MONEY`), `annual_interest_rate` (0 to 100, at most 4 dp), `term_months` (int and not bool, 1 to 600), `first_payment_date` (strict `^\d{4}-\d{2}-\d{2}$` then a real date, not before 1900-01-01, last payment year not past 9999), `payment_override` (at most 2 dp, `> 0`, greater than the first payment's interest, only checked once principal, rate, term and first date are valid), `extra_principal` (at most 2 dp, `0 <= v <= MAX_MONEY`), `closing_date` (valid, not after the first payment date), `payoff_date` (valid, not before the first payment date)
    - On failure return `Result.failure("validation", first.message, field=first.field, errors=<every error>)`; on success canonicalize the rate (`format(rate.normalize(), "f")`, never scientific notation)
    - The function takes plain values and is reusable by backup restore without any store access
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.4, 2.6, 2.10, 3.13, 7.6, 8.6_
    - _Design: Components and Interfaces (validation); Findings F8, F9, F17_

  - [x] 2.3 Add item builders and strict readers to `backend/src/logstead/services/loan.py`
    - Add `loan_to_item(loan)` and `rollup_to_item(rollup)` (importable by backup restore) using only `keys.py` helpers; define `_LOAN_MONEY`, `_ROLLUP_MONEY` and `_WRITE_MONEY` exactly as in the design; `annualInterestRate` is a plain decimal string and not a money attribute; `interestOverrides` is a map of `str(year)` to a two-decimal string and is omitted when empty; unset optional attributes are omitted
    - Add strict parsers: a stored money value must match `^-?\d+\.\d{2}$` and the rate must parse as a finite `Decimal`; a bad value raises an internal `StoredLoanError(field)`; add `_loan_from_item` and `_rollup_from_item`, read with `money_attrs=set()` so values arrive as raw strings
    - _Requirements: 12.1, 12.2, 12.3, 12.6, 5.8, 8.10_
    - _Design: Components and Interfaces (item builders; strict reads); Data Models (Table items)_

- [x] 3. `LoanService` in `backend/src/logstead/services/loan.py`
  - [x] 3.1 Implement create, list, get, update and delete with one atomic `transact_write`
    - `LoanService(repo, today=_utc_today)`; `create_loan` validates, builds a `Loan` with a fresh uuid hex and equal timestamps, then writes through `_write_loan`
    - `_write_loan` computes rows and rollups, builds actions = put Loan + put every rollup + delete rollup rows for years in the previous set but not the new set, and refuses a plan over 100 actions with a `validation` failure on `first_payment_date` suggesting delete and re-add; it calls `repo.transact_write(actions, money_attrs=_WRITE_MONEY)` and maps `ClientError` and `BotoCoreError` to `unavailable` ("No changes were made.")
    - `update_loan`: `get_loan` first (not found wins), validate, keep `id` and `created_at`, set a new `updated_at`, preserve `interest_overrides` filtered to years that still have a rollup, `previous_years` = years of the stored rollup rows; the input carries no overrides
    - `delete_loan`: query `loan_year_list_prefix`, then one `transact_write` deleting the Loan item and every rollup row; `list_loans` queries `loan_list_prefix()` and drops rows where `keys.is_loan_year_sk(sk)`; `get_loan` and a missing id return `not_found` with message "Loan not found." and `field="loan_id"`
    - Build `LoanView` (`default_payment`, `scheduled_payment`, `payoff_balance`, `status` using the injected `today`); a corrupt stored value returns `conflict` naming the field and writes nothing
    - _Requirements: 1.1, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 2.1, 2.8, 4.9, 4.10, 7.1, 7.2, 7.3, 7.4, 7.7, 12.1, 12.2, 12.6_
    - _Design: Components and Interfaces (LoanService); Transaction size guard; Findings F3_

  - [x] 3.2 Implement `schedule_for`, `set_interest_override` and `clear_interest_override`
    - `schedule_for` recomputes rows from the Loan and merges stored rollup rows into `YearlyRollupView` (`interest` = Effective_Interest, `estimated_interest`, `interest_override`, `variance = override - estimated` as a signed two-decimal value, `None` without an override); `estimate=True`
    - `set_interest_override(property_id, loan_id, tax_year, amount)`: load the Loan, require the year to be a stored rollup year (else `validation` on `interest_overrides.<year>`), accept only a `str` or `Decimal` that is non-negative with at most two decimals (else the same field error, nothing written), then one `transact_write` of [put Loan with updated map and new `updatedAt`, put that year's rollup row with `interestOverride` and `effectiveInterest`]; payment rows and balances are untouched
    - `clear_interest_override` removes the key and restores `effectiveInterest` to the estimate; clearing an absent override succeeds; an unknown year returns `None`
    - _Requirements: 4.8, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 8.2, 8.3, 8.4_
    - _Design: Components and Interfaces (LoanService, set and clear override)_

  - [x] 3.3 Implement the read seams used by reports, dashboard and carryforward
    - `property_effective_interest_for_year(property_id, tax_year) -> Money`: one GSI2 query (`GSI2PK=PROPERTY#<id>#YEAR#<year>`, `begins_with(keys.gsi2_loan_year_prefix())`), keep rows with `includeInReport == true`, sum `effectiveInterest` as `Decimal`
    - `report_years(property_id) -> set[int]` (years with a rollup from an included Loan) and `earliest_year(property_id) -> int | None` (first payment year across the property's Loans)
    - _Requirements: 4.9, 6.1, 6.6, 7.5_
    - _Design: Components and Interfaces (LoanService read seams); Carryforward and Data_Year changes_

- [x] 4. Checkpoint - backend core
  - Ensure `.venv/bin/python -m compileall -q src` succeeds and the existing backend suite is still green with the new modules in place; fix any existing test the changes force; ask the user if questions arise.

- [x] 5. Router: ownership helper, routes and string-only money
  - [x] 5.1 Add Loan helpers in `backend/src/logstead/router/handler.py`
    - Add `_loan_service(wiring)` (builds `LoanService(wiring.repo)`), `_require_owned_property(wiring, user, property_id)` (wraps `_property_service(wiring, user).get`, returns `_result_response(got)` on failure so a missing and a foreign property give an identical 404 `"Property not found."`)
    - Add `_FieldError`, `_loan_decimal(value, field)` (empty or `None` becomes `None`; `bool` or `float` raises `_FieldError(field, "must be sent as a decimal string")`; otherwise `Decimal(str(value))`, a bad literal is a field error) and `_loan_input(body, property_id)` accepting snake_case and camelCase keys, `term_months` as an int only; a `_FieldError` is returned as `Result.failure("validation", msg, field=field)`; the body carries no interest overrides
    - _Requirements: 1.3, 8.6, 8.7, 8.9_
    - _Design: Components and Interfaces (Router); Findings F2, F8_

  - [x] 5.2 Register the Loan routes and handlers in `backend/src/logstead/router/handler.py`
    - Add `_create_loan` (201), `_list_loans`, `_get_loan`, `_update_loan`, `_delete_loan` (200 with a `null` body), `_loan_schedule`, `_set_interest_override` (body `{"interest": "<string>"}`, `taxYear` via `_int_param`) and `_clear_interest_override`; every handler starts with `_require_owned_property` and returns it when set
    - Serialize `LoanView`, `LoanSchedule` and `YearlyRollupView` to the JSON shapes in the design (money as two-decimal strings, the rate as a plain decimal string, `interest_overrides` as `{"2024": "7010.12"}`, signed variance)
    - Add the nine `_ROUTES` entries with `public=False`, listing the literal `/loans/line-12-impact` template before `/loans/{loanId}`; the `line-12-impact` entry itself is registered in task 5.3; confirm the 6-segment override templates do not collide with `/transactions/{t}/receipts/{d}`
    - _Requirements: 1.1, 1.11, 1.12, 1.13, 1.14, 5.1, 5.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10_
    - _Design: Components and Interfaces (Router; JSON shapes)_

  - [x] 5.3 Register `GET /properties/{propertyId}/loans/line-12-impact` in `backend/src/logstead/router/handler.py`
    - Add `_loan_line12_impact`: `_require_owned_property` first, then `ReportingService.line12_impact(property_id)` (task 6.3); return the list of `{tax_year, loan_interest, superseded_manual_interest: {amount, count}}` with two-decimal money strings
    - Register the template before `/loans/{loanId}`
    - _Requirements: 6.3, 8.2, 9.16_
    - _Design: Findings F16; JSON shapes_

- [x] 6. ReportingService: Line 12 precedence, combined report and backend export serializers
  - [x] 6.1 Add Line 12 data shapes and precedence in `backend/src/logstead/services/report.py`
    - Add `Line12Source`, `SupersededManualInterest`, `Line12Detail` and `Line12Portfolio`; `ScheduleEReport` gains `line12: Line12Detail` (default `transaction-entered`, `0.00`, `0`) and `CombinedScheduleEReport` gains `line12: Line12Portfolio` (zero default), both as the last field
    - Add a trailing optional `loans: "LoanService | None" = None` to `ReportingService.__init__`
    - In `_build_report` count Line 12 transactions (`manual_12_count`); when `loans.property_effective_interest_for_year(...) > 0.00` set `line_totals[12]` to the loan total, `line_imported[12]` to `False`, and `line12` to `loan-generated` with the manual amount and count; otherwise keep the manual total with `transaction-entered`, `0.00`, `0`; Line 13 and `_totals_from_lines` are untouched
    - In `combined_report` build the portfolio `Line12Portfolio` as the sum of the per-property totals, superseded amounts and counts; no portfolio-level source
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.11, 6.12, 6.13, 7.5_
    - _Design: Components and Interfaces (ReportingService changes); Line 12 precedence diagram; Findings F15_

  - [x] 6.2 Extend the backend export serializers in `backend/src/logstead/services/report.py`
    - `_report_dict` adds `"line12": {"source", "superseded_manual_interest": {"amount": "<2dp>", "count": n}}`; `_combined_to_json` adds a top-level `"line12": {"total", "superseded_manual_interest": {...}}`
    - CSV: per-property block adds `Line 12 Source`, `Line 12 Superseded Manual Interest`, `Line 12 Superseded Transaction Count` directly after the line table; combined CSV adds `Line 12 Total`, `Line 12 Superseded Manual Interest`, `Line 12 Superseded Transaction Count` to the portfolio block; money via `money_to_str`
    - _Requirements: 6.10_
    - _Design: Components and Interfaces (Serialization); Findings F13_

  - [x] 6.3 Add `ReportingService.line12_impact` in `backend/src/logstead/services/report.py`
    - `line12_impact(property_id) -> Result[list[Line12ImpactYear]]` with `Line12ImpactYear(tax_year, loan_interest, superseded_manual_interest)`; list the property's transactions once (all years), group Line 12 transactions by year, read included-loan Effective_Interest per rollup year from `LoanService`, and return only years where loan interest is greater than `0.00` and at least one manual Line 12 transaction exists, ascending by year
    - _Requirements: 6.3, 9.16_
    - _Design: Findings F14, F16_

  - [x] 6.4 REQUIRED: fix existing export and report tests forced by the serializer change
    - Run `tests/services/test_report.py`, `tests/integration/test_report_export.py` and `tests/services/test_combined_report_property.py`; update any assertion that compares exact CSV text, exact JSON keys or row counts so it tolerates (or asserts) the new Line 12 rows and `line12` object, keeping each test's intent
    - Do not weaken value assertions: Line 12 totals, `net` and Line 19 itemization must remain exact
    - _Requirements: 6.10, 6.13_
    - _Design: Testing Strategy (existing tests)_

- [x] 7. Data years, earliest year, Dashboard and Carryforward loan wiring
  - [x] 7.1 Add the optional `loans` collaborator in `backend/src/logstead/services/dashboard.py`
    - `derive_data_years(properties, transactions, depreciation, loans=None)` unions `loans.report_years(prop.id)` into the Data_Year set and keeps the existing `latest_tax_year()` cap; `earliest_data_year(property_id, transactions, depreciation, loans=None)` adds `loans.earliest_year(property_id)` as a candidate; `DashboardService.__init__` gets a trailing `loans=None` and forwards it
    - With `loans=None` behavior is exactly as today
    - _Requirements: 6.11_
    - _Design: Carryforward and Data_Year changes; Findings F1_

  - [x] 7.2 Add the optional `loans` collaborator in `backend/src/logstead/services/carryforward.py`
    - `CarryforwardService.__init__` gets a trailing `loans=None` and passes it to `derive_data_years`; `_schedule_e_net_for_year` is unchanged (it already sums `report_for(...).totals.net`)
    - _Requirements: 6.11_
    - _Design: Carryforward and Data_Year changes_

  - [x] 7.3 Wire the loan service in `backend/src/logstead/router/handler.py`
    - `_reporting_service` passes `loans=_loan_service(wiring)`; `_dashboard_service_or_503`, `_carryforward_service_or_503` and `_earliest_year` pass the loan service for data-year derivation
    - _Requirements: 6.1, 6.9, 6.11_
    - _Design: Router (wiring changes)_

- [x] 8. PropertyService delete guard
  - [x] 8.1 Guard property deletion when Loans exist in `backend/src/logstead/services/property.py`
    - In `delete`, also query `keys.loan_list_prefix()` for the property; when any Loan row exists return the existing `conflict` result with a message that also names loans ("remove its loans first"); transactions and assets behavior is unchanged
    - _Requirements: 1.13, 12.1_
    - _Design: PropertyService.delete change; Findings F7_

- [x] 9. BackupService: export, restore, validate and summary
  - [x] 9.1 Extend `backend/src/logstead/models/backup.py`
    - Add `BackupLoan` (all fields in the design, `interest_overrides: dict[int, Decimal]`), `BackupProperty.loans: list[BackupLoan] = field(default_factory=list)`, `RestoreSummary.loans: int = 0` and `ClearSummary.loans: int = 0`; `schema_version` stays `"1"`
    - _Requirements: 11.1, 11.4, 11.7_
    - _Design: Backup and restore_

  - [x] 9.2 Validate Loans inside `validate_document` in `backend/src/logstead/services/backup.py`
    - For each raw loan require `id`, `property_id`, `description`, `original_principal`, `annual_interest_rate`, `term_months`, `first_payment_date`; `property_id` must reference a property in the document; parse money with `_parse_money` and the rate with `_parse_plain_decimal`; run `validate_loan_fields`; recompute rollup years from the validated loan and require every `interest_overrides` key to be one of them
    - On failure return `Result.failure("validation", f"property {pid!r}, loan {lid!r}: {message}", field=<loan field>)`; a document without `loans` yields zero loans; this phase is pure and runs before the clear
    - _Requirements: 11.4, 11.6_
    - _Design: Backup and restore (validation); Findings F10_

  - [x] 9.3 Export Loans in `backend/src/logstead/services/backup.py`
    - `BackupService.__init__` receives (or builds) a `LoanService`; `_export_property` adds `loans = [BackupLoan(...) for view in list_loans(pid).value]` including `interest_overrides`; never reads rollup rows or payment rows; `_to_jsonable` renders Decimals as strings (`"300000.00"`, rate `"6.875"`) and int override keys as strings
    - _Requirements: 11.1, 11.2_
    - _Design: Backup and restore (Export)_

  - [x] 9.4 Restore Loans in `backend/src/logstead/services/backup.py`
    - For each loan build a `Loan` keeping the document's id, `created_at` and `updated_at`, recompute with `compute_payment_rows` and `build_yearly_rollups`, and emit `loan_to_item` and `rollup_to_item` rows into two new write groups using `_LOAN_MONEY` and `_ROLLUP_MONEY` (batches of at most 100, as for the other groups); rollups are never read from the document; set `RestoreSummary.loans` to the number of Loans, including the empty-document summary
    - _Requirements: 11.3, 11.4, 11.5, 11.7_
    - _Design: Backup and restore (Restore write path)_

  - [x] 9.5 Count Loans in `BackupService.clear` in `backend/src/logstead/services/backup.py`
    - Count rows where `sk.startswith(keys.loan_list_prefix()) and not keys.is_loan_year_sk(sk)` into `ClearSummary.loans`; the generic child delete already removes Loan and rollup rows
    - _Requirements: 11.7, 12.1_
    - _Design: Backup and restore (clear)_

  - [x] 9.6 REQUIRED: add a Loan to the sample backup and update the two sample-fixture tests
    - Add one Loan with a 2024 interest override to `frontend/src/data/sample-backup.json` (shape as in the design's backup fragment)
    - Update the summary and count assertions in `backend/tests/router/test_backup_sample_fixture.py` and `frontend/src/data/sample-backup.test.ts` (loan count `1`, plus a Loan-content round trip); run both
    - _Requirements: 11.1, 11.3, 11.7_
    - _Design: Testing Strategy (sample fixture)_

- [x] 10. Checkpoint - backend complete
  - Run `.venv/bin/python -m pytest -q -p no:cacheprovider -n auto` from `backend/`; fix every existing test the changes force; ask the user if questions arise.

- [x] 11. Frontend: API modules and the client-side payment preview
  - [x] 11.1 Create `frontend/src/api/loans.ts`
    - Export `Loan`, `LoanInput`, `PaymentRow`, `YearlyRollup`, `LoanSchedule`, `Line12ImpactYear` and the helpers `listLoans`, `createLoan`, `getLoan`, `updateLoan`, `deleteLoan`, `getLoanSchedule`, `setInterestOverride`, `clearInterestOverride`, `getLine12Impact`, each taking an injectable `client = apiClient`, in the style of `api/assets.ts`
    - Money and the rate stay strings end to end; ids and years are URL-encoded; `setInterestOverride` sends `{ interest }`
    - _Requirements: 8.1, 8.5, 8.6, 9.1_
    - _Design: Frontend (API module)_

  - [x] 11.2 Add Line 12 types and CSV rows in `frontend/src/api/reports.ts`
    - Add `Line12Source`, `Line12Detail`, optional `line12?: Line12Detail` on `ScheduleEReport` and optional `line12?: { total: string; superseded_manual_interest: { amount: string; count: number } }` on `CombinedScheduleEReport`
    - `reportToCsv` writes `Line 12 Source`, `Line 12 Superseded Manual Interest` and `Line 12 Superseded Transaction Count` rows when `line12` is present and omits them when it is absent; `reportToJson` is the report verbatim
    - _Requirements: 6.10, 10.5_
    - _Design: Frontend (API module; Findings F13)_

  - [x] 11.3 Add Loan types in `frontend/src/api/backup.ts`
    - Add `BackupLoan`, `loans?: BackupLoan[]` on `BackupProperty`, and `loans?: number` on `RestoreSummary` and `ClearSummary`
    - _Requirements: 11.1, 11.7_
    - _Design: Frontend (API module)_

  - [x] 11.4 Create `frontend/src/lib/amortization.ts`
    - Export `defaultMonthlyPayment(principal, ratePct, termMonths): string | null` using `BigInt` fixed-point math scaled to `10^40`, `(1+r)^n` by repeated multiplication with truncation, rounded half-up to cents; rate `0` returns `principal / term` rounded half-up
    - Parse inputs with the backend grammar (principal positive, at most 2 dp and at most 999,999,999.99; rate 0 to 100 with at most 4 dp; term a whole number 1 to 600) and return `null` for any missing or invalid input; no `number` arithmetic on money
    - _Requirements: 2.1, 2.2, 9.2, 9.3_
    - _Design: Client-side default payment preview_

  - [x] 11.5 Generate the shared golden vectors in `frontend/src/data/loan-payment-vectors.json`
    - Use a throwaway script (not committed, delete after use) to run the backend `default_payment` over about 60 `{principal, rate, term, payment}` vectors covering rate 0, term 1, term 600, maximum principal, high rates, four-decimal rates and round values; store all values as strings except `term`; spot-check a few rows by hand against an independent calculator
    - _Requirements: 2.1, 2.2, 9.2_
    - _Design: Cross-language fixture_

- [x] 12. Frontend: Loans page, form, tables, override controls and notices
  - [x] 12.1 Create `frontend/src/components/loans/loanForm.ts`
    - Form value types (all strings), `validateLoanForm` mirroring the backend rules (description 1 to 200, principal, rate, term, strict `YYYY-MM-DD`, payoff not before first payment, closing not after it, positive payment override, non-negative extra principal) returning per-field messages, and `toLoanInput` producing a `LoanInput` with money and rate as strings; modeled on `businessForm.ts`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 9.1_
    - _Design: Pages, components, hooks_

  - [x] 12.2 Create `frontend/src/components/loans/LoanForm.tsx`
    - Create and edit form with labeled controls for description, original principal, annual rate, term months, first payment date, payment override, extra principal, closing date, payoff date and Report_Inclusion; keeps all values as strings; field errors via `aria-describedby`; a form-level `role="alert"` message
    - `defaultMonthlyPayment` runs in a `useMemo` over principal, rate and term so the preview updates synchronously and is removed (never stale) as soon as any of the three is invalid
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.20_
    - _Design: Pages, components, hooks (LoanForm)_

  - [x] 12.3 Create `frontend/src/components/loans/LoanList.tsx`
    - Lists description, principal, rate, term and status (active or ended) with Select, Edit and Delete buttons that have accessible names; renders an empty-state message and the create control when there are no Loans
    - _Requirements: 9.6, 9.7, 9.20_
    - _Design: Pages, components, hooks (LoanList)_

  - [x] 12.4 Create `frontend/src/components/loans/YearlyRollupTable.tsx` and `frontend/src/components/loans/PaymentRowsTable.tsx`
    - Yearly table columns: tax year, interest, principal, total paid, ending balance, rendered with `formatMoneyWholeDollars`; one row per yearly object in ascending year order; a button per year with `aria-expanded` and `aria-controls` reveals that year's `PaymentRowsTable` (group `schedule.payments` by `date.slice(0, 4)`; number, date, payment, interest, principal, balance via `formatMoney`)
    - Show a text "Filed value" marker when an override exists (never color alone), the `InterestOverrideControl` per year, and the variance in words; `<caption class="sr-only">` and `scope` on headers, as `ScheduleTable` does
    - _Requirements: 9.8, 9.9, 9.10, 9.11, 9.12, 9.13, 9.20_
    - _Design: Pages, components, hooks (YearlyRollupTable, PaymentRowsTable)_

  - [x] 12.5 Create `frontend/src/components/loans/InterestOverrideControl.tsx`
    - Per-year input with an explicit Save button and Enter-to-submit (no save-on-blur) and a Clear button; reject a negative, non-numeric or more-than-two-decimal value inline and do not call the API; show server `interest_overrides.<year>` errors next to that year; variance text states direction in words (for example "$120 lower than the estimate")
    - _Requirements: 9.12, 9.13, 9.14, 9.20_
    - _Design: Pages, components, hooks (InterestOverrideControl)_

  - [x] 12.6 Create `frontend/src/components/loans/EstimateNotice.tsx` and `frontend/src/components/loans/SupersededInterestNotice.tsx`
    - `EstimateNotice`: states the schedule is an estimate and to reconcile with Form 1098
    - `SupersededInterestNotice`: takes `Line12ImpactYear[]` and renders one notice per year with the tax year, the superseded amount via `formatMoneyWholeDollars`, and the instruction to turn Report_Inclusion off to restore the manual figures
    - _Requirements: 9.15, 9.16_
    - _Design: Pages, components, hooks (notices)_

  - [x] 12.7 Create the hooks `useLoans.ts`, `useLoanSchedule.ts` and `useLine12Impact.ts` in `frontend/src/components/loans/`
    - `useLoans`: list plus create, update and delete state, mapping a 400 body with `errors` (or a single `field`) to per-field messages and anything else to a form-level message, keeping entered values; `useLoanSchedule`: load and refresh the schedule, set and clear override, per-year errors; `useLine12Impact`: loads once per property and after Loan changes, and a failed load hides the notice area without blocking the page
    - _Requirements: 9.4, 9.5, 9.12, 9.13, 9.17, 9.18, 7.7_
    - _Design: Pages, components, hooks; Error Handling (frontend)_

  - [x] 12.8 Create `frontend/src/pages/LoansPage.tsx`
    - Route `/properties/:propertyId/loans`, injectable `api` prop like `AssetsPage`; renders `PropertySection title="Loans"`, `EstimateNotice`, `SupersededInterestNotice`s, the form, the list, and the yearly table for the selected Loan; uses `StateBlock`, `ConfirmDialog` and `useToast`; on delete success remove the Loan and clear its rollup display, on failure keep it and show an error
    - _Requirements: 9.1, 9.4, 9.5, 9.6, 9.7, 9.8, 9.15, 9.16, 9.17, 9.18, 9.20_
    - _Design: Pages, components, hooks (LoansPage)_

- [x] 13. Frontend: navigation, route and report view Line 12 label and superseded amount
  - [x] 13.1 REQUIRED: add "Loans" to `PROPERTY_NAV` in `frontend/src/components/navConfig.ts` and fix `navConfig.test.ts`
    - Add `{ segment: "loans", label: "Loans" }` after "Depreciable Assets"; update the order and label assertions in `frontend/src/components/navConfig.test.ts`; run `PropertySectionTabs.test.tsx` and `PropertyLayout.test.tsx` and fix any tab-count assumption
    - _Requirements: 9.19_
    - _Design: Pages, components, hooks (Navigation)_

  - [x] 13.2 Add the route in `frontend/src/App.tsx`
    - Import `LoansPage` and add `<Route path="loans" element={<LoansPage />} />` under the `properties/:propertyId` layout route; update the route comment
    - _Requirements: 9.19_
    - _Design: Pages, components, hooks (Navigation)_

  - [x] 13.3 Render the Line 12 label and superseded amount in `frontend/src/components/reports/ScheduleELineTable.tsx`
    - Add optional `line12?: Line12Detail | null`; for the Line 12 row only: `loan-generated` shows a `Badge` "Loan-generated" and, when `count > 0` or `amount > 0`, "Superseded manual interest: $X,XXX.XX (N transactions)" via `formatMoney`; `transaction-entered` renders exactly as today; a missing or unrecognized `source` renders the amount with no label plus the text "Line 12 source unavailable"
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_
    - _Design: Report view changes_

  - [x] 13.4 Pass `line12` through `frontend/src/components/reports/ReportView.tsx` and `frontend/src/components/reports/CombinedReportView.tsx`
    - `ReportView` passes `report.line12` to `ScheduleELineTable`; `CombinedReportView` composes `ReportView` per column and adds a "Line 12 total" row under the portfolio totals when the combined `line12` is present
    - _Requirements: 6.9, 10.1, 10.2, 10.5_
    - _Design: Report view changes_

  - [x] 13.5 REQUIRED: give existing frontend report fixtures a `line12` value
    - In `ReportView.test.tsx`, `ScheduleELineTable.test.tsx`, `markerSurfacing.test.tsx`, `pages/ReportsPage.test.tsx`, `pages/CombinedReportsPage.test.tsx` and `api/reports.test.ts` (its `makeReport`) add `line12: { source: "transaction-entered", superseded_manual_interest: { amount: "0.00", count: 0 } }` (and a combined `line12` where a combined fixture exists) so these tests do not render the "source unavailable" indication; fix any CSV assertion that compares exact text
    - Keep each test's intent; do not delete assertions
    - _Requirements: 10.3, 10.5_
    - _Design: Testing Strategy (existing tests)_

- [x] 14. Checkpoint - frontend complete
  - Run `npm run build` (`tsc -b && vite build`) and `npx vitest --run` from `frontend/`; fix every existing test the changes force; ask the user if questions arise.

- [x] 15. Backend tests
  - [x] 15.1 Key helper tests in `backend/tests/repository/test_keys.py`
    - Loan key helper outputs, `is_loan_year_sk` true only for rollup SKs, no collision with `ASSET#`, `SCHED#`, `TXN#` prefixes
    - _Requirements: 12.1, 12.2, 12.4, 12.5_

  - [x] 15.2 Error `errors` tests in new `backend/tests/models/test_error_errors.py`
    - `Result.failure` with and without `errors`; `_error_body` emits `errors` only when present and always keeps `field` and `message` as the first error
    - _Requirements: 1.3, 8.9_

  - [x] 15.3 Property tests: engine in new `backend/tests/services/test_loan_engine_property.py`
    - **Property 1: Payment row arithmetic and balance recurrence**
    - **Property 2: Schedule shape, dates, and termination**
    - **Property 3: Principal conservation**
    - **Property 4: Schedule determinism**
    - **Property 6: Extra principal never makes a loan slower or costlier**
    - **Property 7: Payoff date truncates the schedule to a prefix**
    - **Property 8: Yearly rollup consistency**
    - **Validates: Requirements 2.3, 2.5, 2.7, 2.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 4.1, 4.2, 4.3, 4.4, 4.5, 4.8, 7.1**
    - Pure tests against `compute_payment_rows` and `build_yearly_rollups`; oracle uses `fractions.Fraction` and `calendar`, never the code under test; generators per the design (month-end days biased)

  - [x] 15.4 Property test: default payment oracle in new `backend/tests/services/test_loan_default_payment_property.py`
    - **Property 5: Default payment matches an exact oracle**
    - **Validates: Requirements 2.1, 2.2, 3.12**
    - Also asserts every vector in `frontend/src/data/loan-payment-vectors.json` equals `default_payment`

  - [x] 15.5 Property test: validation in new `backend/tests/services/test_loan_validation_property.py`
    - **Property 9: Validation rejects every invalid field and writes nothing**
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.4, 2.6, 2.10, 3.13, 7.6, 8.9**
    - moto-backed `LoanService`; per-field invalid strategies combined by random non-empty subset; the table is byte-for-byte unchanged afterwards

  - [x] 15.6 Property test: serialization round trip in new `backend/tests/services/test_loan_roundtrip_property.py`
    - **Property 10: Loan serialization round trips**
    - **Validates: Requirements 8.5, 8.6, 8.10, 12.3**
    - Includes the router JSON shape, the item builder round trip, and a JSON float rate rejected on `annual_interest_rate`

  - [x] 15.7 Examples and failure injection in new `backend/tests/services/test_loan_service.py`
    - CRUD examples, `not_found` cases, atomic failure injection (fake repo raising `ClientError` leaves everything unchanged), the 100-action guard, strict-read corruption returning `conflict` with the field (12.6), corrupt value never written back
    - _Requirements: 1.10, 1.14, 1.15, 4.10, 7.7, 12.6_

  - [x] 15.8 Property tests: storage in new `backend/tests/services/test_loan_storage_property.py`
    - **Property 11: Stored rollups always equal the engine output, with none stale**
    - **Property 12: Payoff set and clear is a round trip, and later years disappear**
    - **Property 13: Delete removes exactly one Loan and leaves the rest alone**
    - **Property 14: Listing is scoped and typed**
    - **Validates: Requirements 1.1, 1.11, 1.12, 1.13, 4.9, 7.1, 7.2, 7.3, 7.4, 12.2, 12.4, 12.5**

  - [x] 15.9 Property tests: overrides in new `backend/tests/services/test_loan_override_property.py`
    - **Property 16: An override replaces estimated interest and nothing else**
    - **Property 17: Override set then clear is a round trip with a correct variance**
    - **Property 18: Invalid overrides are rejected and storage format is fixed**
    - **Property 19: Updates prune only the overrides whose year disappears**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 7.2**

  - [x] 15.10 Router tests in new `backend/tests/router/test_loan_routes.py`
    - **Property 15: Missing and foreign properties are indistinguishable**
    - **Validates: Requirements 8.7**
    - Route examples (create, list, get, update, delete, schedule, override set and clear, line-12 impact; 8.1 to 8.4, 8.8), JSON float rejection, `errors` list shape, 404 body identical for a missing and a foreign property on every Loan route

  - [x] 15.11 Property tests: Line 12 in new `backend/tests/services/test_report_line12_property.py`
    - **Property 20: Line 12 uses loan interest or manual interest, never both**
    - **Property 21: Totals include Line 12 and Line 13 is untouched**
    - **Property 22: Combined report columns follow the same rules and the portfolio sums them**
    - **Property 23: Reports are reproducible**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.12, 6.13, 7.5**
    - Generators per the design (1 to 3 properties, 0 to 3 Loans each, inclusion flags, overrides including `0.00`, 0 to 5 Line 12 transactions per year)

  - [x] 15.12 Property test: exports in new `backend/tests/services/test_report_line12_export_property.py`
    - **Property 24: Exports match the report**
    - **Validates: Requirements 6.10**
    - Parses the backend CSV and JSON and compares Line 12 total, source and superseded amount and count at two decimals

  - [x] 15.13 Property test: carryforward in new `backend/tests/services/test_carryforward_loan_property.py`
    - **Property 25: Carryforward sees loan interest**
    - **Validates: Requirements 6.11**
    - Includes loan-only years (no transactions or depreciation) appearing among the Data_Years up to the latest completed tax year

  - [x] 15.14 Property tests: backup in new `backend/tests/services/test_backup_loan_roundtrip_property.py`
    - **Property 26: Backup round trip preserves Loans**
    - **Property 27: An invalid Loan in a backup rejects the whole restore**
    - **Validates: Requirements 11.1, 11.3, 11.5, 11.6, 11.7**
    - Plus the no-loans document example (11.4, loan count `0`) and the export containing no rollup or payment rows (11.2)

  - [x] 15.15 Property deletion guard test in new `backend/tests/services/test_property_delete_loans.py`
    - A property with a Loan returns `conflict` and stays intact; deleting the Loan first allows the property delete
    - _Requirements: 1.13, 12.1_

  - [x] 15.16 Data-year tests in `backend/tests/services/test_dashboard.py`
    - `derive_data_years` and `earliest_data_year` include loan years and the first payment year; behavior with `loans=None` is unchanged; future years stay capped
    - _Requirements: 6.11_

  - [x] 15.17 Documentation and key-discipline tests in new `backend/tests/infra/test_loan_docs.py`
    - `docs/data-model.md` contains the four required headings (Loan entity, Loan key prefixes, Line 12 precedence rule, Loan backup treatment); a source scan confirms `services/loan.py` builds no `PK` or `SK` string directly
    - _Requirements: 12.1, 12.7_

- [x] 16. Frontend tests
  - [x] 16.1 Golden vector and edge tests in new `frontend/src/lib/amortization.test.ts`
    - Every vector in `frontend/src/data/loan-payment-vectors.json`; rate 0, term 1, maximum principal, `null` for each invalid input
    - _Requirements: 2.1, 2.2, 9.2, 9.3_

  - [x] 16.2 Property test: preview in new `frontend/src/lib/amortization.property.test.ts`
    - **Property 28: The default payment preview matches the backend and is never stale**
    - **Validates: Requirements 9.2, 9.3**
    - fast-check vs a `BigInt` rational oracle; `null` on any invalid input; money strings from integer cents, never floats

  - [x] 16.3 API tests in new `frontend/src/api/loans.test.ts`
    - URLs, encoding, request bodies, money and rate stay strings, fake-fetch client like `api/assets`
    - _Requirements: 8.1, 8.5, 8.6_

  - [x] 16.4 Form validation tests in new `frontend/src/components/loans/loanForm.test.ts`
    - Client validation mirrors the backend rules; `toLoanInput` keeps strings
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [x] 16.5 Component tests in new `frontend/src/components/loans/LoanForm.test.tsx`
    - Fields and labels (9.1), preview shown for valid input and hidden as soon as any of principal, rate or term becomes invalid (9.2, 9.3)
    - _Requirements: 9.1, 9.2, 9.3_

  - [x] 16.6 Component tests in new `frontend/src/components/loans/LoanList.test.tsx`
    - Description, principal, rate, term, status; empty state with the create control
    - _Requirements: 9.6, 9.7_

  - [x] 16.7 Tests: yearly table in new `frontend/src/components/loans/YearlyRollupTable.property.test.tsx` and `YearlyRollupTable.test.tsx`
    - **Property 29: Loans page money formatting**
    - **Validates: Requirements 9.8, 9.9, 9.11**
    - Example test: expand and collapse, `aria-expanded`, keyboard operation, variance text (9.10, 9.20)

  - [x] 16.8 Tests: override control in new `frontend/src/components/loans/InterestOverrideControl.property.test.tsx` and `InterestOverrideControl.test.tsx`
    - **Property 30: Client override validation never sends a bad value**
    - **Validates: Requirements 9.14**
    - Example test: save, variance text, clear (9.12, 9.13)

  - [x] 16.9 Property test: notice in new `frontend/src/components/loans/SupersededInterestNotice.property.test.tsx`
    - **Property 31: Superseded-interest notice content**
    - **Validates: Requirements 9.16**

  - [x] 16.10 Page tests in new `frontend/src/pages/LoansPage.test.tsx`
    - Field errors shown with entered values kept (9.4), form-level error (9.5), estimate notice (9.15), delete success and failure (9.17, 9.18), failed line-12-impact load does not block the page, `vitest-axe` passes (9.20)
    - _Requirements: 9.4, 9.5, 9.15, 9.17, 9.18, 9.20_

  - [x] 16.11 Property test: report row in new `frontend/src/components/reports/ScheduleELineTable.line12.property.test.tsx`
    - **Property 32: Line 12 report rendering follows the source**
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.5**

  - [x] 16.12 Line 12 cases in `frontend/src/components/reports/ReportView.test.tsx`
    - Loan-generated with superseded amount to two decimals on the Line 12 row (10.1, 10.2), transaction-entered unchanged (10.3), zero with no label (10.4), missing `line12` shows the unavailable indication (10.5)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 16.13 Export tests in `frontend/src/api/reports.test.ts`
    - `reportToCsv` writes the three Line 12 rows and omits them without `line12`; parity check for **Property 24** against the backend CSV layout
    - **Validates: Requirements 6.10**

  - [x] 16.14 Route test in `frontend/src/App.test.tsx`
    - `/properties/:id/loans` renders `LoansPage`
    - _Requirements: 9.19_

  - [x] 16.15 Backup type tests in `frontend/src/api/backup.test.ts`
    - Loans in the document and restore summary types round trip as strings
    - _Requirements: 11.1, 11.7_

- [x] 17. Documentation and CHANGELOG
  - [x] 17.1 Update `docs/data-model.md`
    - Add four separate headings: **Loan entity**, **Loan key prefixes** (item tables, `LOAN#` and `LOAN#..#YEAR#` rows in the prefix table, the GSI2 `LOANYR#` note), **Line 12 precedence rule** (loan-generated wins when included Effective_Interest is above `0.00`, never both, superseded figure, source), **Loan backup treatment** (loans and overrides exported, rollups and payment rows derived, `schema_version` stays `"1"`, older builds drop `loans` on restore)
    - _Requirements: 12.7_
    - _Design: Documentation updates_

  - [x] 17.2 Update `docs/api.md`
    - Add a "Loans" route table (nine routes) and the `line12` report fields
    - _Requirements: 8.1, 6.10_
    - _Design: Documentation updates_

  - [x] 17.3 Add entries under `## [Unreleased]` in `CHANGELOG.md`
    - Under `### Added`: loans with generated monthly amortization schedules, per-year Form 1098 interest override, generated interest feeding Schedule E Line 12 (per-property and combined) and carryforward, Loans page and navigation entry, Loans in backup and restore, the Loan routes, `line12` on report responses and exports, and `errors` on validation failures; under `### Changed`: Line 12 uses loan interest instead of (not added to) hand-entered mortgage interest when a loan produces interest, a property with Loans cannot be deleted until they are removed; match the existing entry style
    - _Requirements: 6.1, 6.2, 12.7_

- [x] 18. Final verification - suites green, no deploy
  - Backend: from `backend/`, recreate the venv if missing or stale (`python3 -m venv .venv && .venv/bin/python -m pip install -q -e ".[dev]"`), then run `.venv/bin/python -m pytest -q -p no:cacheprovider -n auto`; the full suite must be green
  - Frontend: from `frontend/`, run `npm run build` (the real gate: `tsc -b && vite build`), then `npx vitest --run`; both must be green
  - Confirm no floating-point arithmetic was introduced for money or the rate, no service builds a `PK` or `SK` string directly, and asset listing still returns zero Loan rows
  - Delete any iCloud duplicate files (`* 2.*`) and the throwaway vector-generation script; never commit them; do not commit anything
  - Do NOT run any deploy (`make deploy`); the user runs deploys. Ask the user if anything is unclear
  - _Requirements: 3.6, 6.7, 6.13, 8.6, 12.1, 12.5_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "11.1", "11.2", "11.3", "11.4", "13.1", "17.1", "17.2", "17.3"] },
    { "id": 1, "tasks": ["2.1", "8.1", "9.1", "12.1", "12.3", "12.4", "12.5", "12.6", "12.7", "13.3", "15.1", "15.2", "16.2", "16.3", "16.15"] },
    { "id": 2, "tasks": ["2.2", "11.5", "12.2", "13.4", "15.3", "16.4", "16.6", "16.7", "16.8", "16.9", "16.11"] },
    { "id": 3, "tasks": ["2.3", "12.8", "13.5", "15.4", "16.1", "16.5"] },
    { "id": 4, "tasks": ["3.1", "9.2", "13.2", "16.10", "16.12", "16.13"] },
    { "id": 5, "tasks": ["3.2", "5.1", "9.3", "15.5", "15.15", "16.14"] },
    { "id": 6, "tasks": ["3.3", "5.2", "9.4", "15.9"] },
    { "id": 7, "tasks": ["6.1", "7.1", "9.5", "15.6", "15.7", "15.8", "15.17"] },
    { "id": 8, "tasks": ["6.2", "7.2", "9.6", "15.11", "15.14", "15.16"] },
    { "id": 9, "tasks": ["6.3", "6.4", "7.3", "15.12"] },
    { "id": 10, "tasks": ["5.3", "15.13"] },
    { "id": 11, "tasks": ["15.10"] }
  ]
}
```

> Wave ordering note: `services/loan.py` is written by 2.1, 2.2, 2.3, 3.1, 3.2 and 3.3 in waves 1, 2, 3, 4, 5 and 6. `router/handler.py` is written by 1.2 (wave 0), 5.1 (5), 5.2 (6), 7.3 (9) and 5.3 (10); 5.3 follows 6.3 (wave 9) because it calls `line12_impact`, and 7.3 follows 7.2 (wave 8) because the carryforward constructor must accept `loans` first. `services/report.py` is written by 6.1, 6.2 and 6.3 in waves 7, 8 and 9. `services/backup.py` is written by 9.2, 9.3, 9.4 and 9.5 in waves 4, 5, 6 and 7. `services/dashboard.py` (7.1, wave 7) precedes `services/carryforward.py` (7.2, wave 8). Frontend: 13.3 (wave 1) precedes 13.4 (wave 2); 13.5 (wave 3) edits report fixtures and `reports.test.ts` before the optional 16.12 and 16.13 (wave 4) add cases to the same files. 11.5 (wave 2) needs the backend `default_payment` from 2.1 (wave 1), and the optional vector tests 15.4 and 16.1 follow it. Checkpoints (4, 10, 14) and the final task (18) are stop-and-verify gates, not code tasks, so they are not in the wave graph.

## Notes

- **Spec only.** This spec describes the change; implementation happens when tasks are run. Tasks marked `[ ]` are optional new tests and can be skipped for a faster MVP. Tasks 6.4, 9.6, 13.1 and 13.5 are **not** optional: they keep the existing suites and `tsc -b` green.
- **Backward compatibility.** Every addition to `Error`, `ScheduleEReport`, `CombinedScheduleEReport`, `RestoreSummary`, `ClearSummary`, `ReportingService`, `DashboardService`, `CarryforwardService`, `derive_data_years` and `earliest_data_year` is a trailing optional argument or defaulted field, so existing constructions still work. With no Loans, every report equals today's output apart from the added `line12` fields.
- **Money discipline.** Money and the annual rate are `Decimal` or strings everywhere; the router rejects a JSON float for them; the rate attribute is stored as a plain decimal string and is not money-quantized.
- **Overrides** are managed only through the dedicated override routes. Loan update bodies carry none, and an update keeps the overrides whose tax year still has a rollup.
- **Out of scope** (design follow-ups): ownership checks on the existing asset routes (F2), and carrying `depreciation_overrides` in the backup document (F11).
- **No deploy and no commit.** Task 18 is the real gate and explicitly excludes `make deploy`.
