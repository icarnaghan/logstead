# Requirements Document

## Introduction

This feature makes three small, related corrections to the passive loss carryforward reconciliation and the per-property tax-year pickers, all driven by real filed-return data (`CarryforwardService` at `backend/src/logstead/services/carryforward.py`; `Carryforward_Page` at `frontend/src/pages/CarryforwardPage.tsx`; specs `.kiro/specs/carryforward-carry-in-semantics/`, `.kiro/specs/carryforward-chain-status/` and `.kiro/specs/carryforward-allowed-loss/`).

### The problems this solves

1. **Whole-dollar returns vs. cents.** Tax returns are filed in whole dollars, each line rounded individually, while the app keeps cents. A return that faithfully carried the prior year's figure (for example 10,057 against an app figure of 10,056.73, or 8,692 against 8,691.91) is flagged `mismatch` ("Needs review") today because `reconcile()` compares reported and expected values to the exact cent. Rounding noise should not look like an error.
2. **Misleading mismatch hint.** The hint under a `mismatch` row says "Does not match the {prior} return's carry-out. Review the {prior} return." That points at the wrong return when this year's own line is the error (a blank or 0 line on one return, or a return that omitted one property's carried loss).
3. **Year pickers start too late.** The Reports, Transactions and Property Detail year pickers start at the earliest depreciable asset's placed-in-service year, or a six-year window when there are no assets. A property with 2010-2018 transactions cannot select those years.

### What this feature does

- **Tolerance comparison (backend).** Status comparison uses a single documented constant, `STATUS_TOLERANCE = Decimal("2.00")`. The `ok` rule and the `carried` rule each hold when `abs(reported - other) <= STATUS_TOLERANCE`. The tolerance is exposed additively on `GET /carryforward` as `status_tolerance` so the page can explain it.
- **Hint rewording (frontend).** The `mismatch` hint names the line to check and shows both whole-dollar figures. The page copy mentions the whole-dollar tolerance using the new wire field.
- **Year range (backend and frontend).** A small additive route returns the property's earliest data year; one shared frontend helper uses it for all three pickers.

### What this feature is, and is not

- `expected_carry_in`, `expected_carryforward`, `drift`, the status precedence (unreported, ok, carried, mismatch), `carried_from_year` attribution, storage keys and write routes are **unchanged**. `drift` stays the exact signed cent difference and remains informational.
- A special-allowance-on-prior-losses field was considered and **dropped**; it is out of scope.
- The app still never computes the IRC §469 limitation and remains a reconciliation aid, not a tax engine.
- Backward compatibility: every exact-cent `ok` or `carried` year stays `ok` or `carried`. The only classification change is that some years that are `mismatch` (or `carried` that become `ok`) today become `ok` or `carried` because they sit within the tolerance.
- The existing `taxYearRange` helper keeps working for current callers until they migrate.

### Grounding (named seams)

- `backend/src/logstead/services/carryforward.py`: `ReconciledYear`, `ReconciliationSummary`, and the `reconcile()` status block (`reported_value == expected_in`, `reported_value == chain_in`).
- `backend/src/logstead/router/handler.py`: `_carryforward_reconcile` and `_to_jsonable` (generic dataclass serialization, so a new summary dataclass field reaches the wire without handler changes); `_transaction_service`, `_depreciation_service`, `_property_service` and the route table.
- `backend/src/logstead/repository/dynamo_repo.py` (`query(..., ascending=...)`) and `backend/src/logstead/repository/keys.py` (`transaction_sk`, `date_from_inverted`): transaction sort keys are inverted dates, so the earliest transaction is the last item in key order.
- `backend/src/logstead/services/dashboard.py`: `latest_tax_year()` and `derive_data_years()`.
- `frontend/src/api/carryforward.ts` (`ReconciliationSummary`), `frontend/src/pages/CarryforwardPage.tsx` (`mismatchHint`, `DisclaimerNotice`), `frontend/src/lib/taxYears.ts` (`taxYearRange`, `latestCompletedTaxYear`), `ReportsPage.tsx`, `TransactionsPage.tsx`, and `PropertyDetailPage.tsx` (which carries its own private copy of `taxYearRange`).
- The property detail response (`Property`) carries no date usable as a first-activity year, so a new field is required.

## Glossary

- **Carryforward_Service**: The backend `CarryforwardService` that derives the reconciliation series and classifies each year.
- **Carryforward_Router**: The `GET /carryforward` handler path (`_carryforward_reconcile`) that serializes the summary.
- **Carryforward_Page**: The frontend page `CarryforwardPage.tsx`.
- **Carryforward_API**: The frontend transport module `frontend/src/api/carryforward.ts`, including the `ReconciliationSummary` type.
- **Reconciled_Year**: One entry in the ascending reconciliation series, one per Data_Year.
- **Previous_Row**: The Reconciled_Year immediately before a given row in the displayed series.
- **Reported_Carry_In**: The user-entered Form 8582 "Prior years unallowed losses" figure for a year (`reported_carryforward`).
- **Expected_Carry_In**: The balance the app expects to enter the year (`expected_carry_in`).
- **Chain_In**: The year's Year_Step applied to the Previous_Row's Reported_Carry_In (the value a return would show if it faithfully carried the prior return's figure).
- **Status_Tolerance**: The constant `STATUS_TOLERANCE`, `Decimal("2.00")`, the largest absolute difference that still counts as a match.
- **Within_Tolerance**: Two amounts a and b are Within_Tolerance when `abs(a - b) <= Status_Tolerance`, computed with exact `Decimal` arithmetic.
- **Drift**: `Reported_Carry_In - Expected_Carry_In` as an exact signed two-decimal value; informational only.
- **Reconciliation_Status**: One of `unreported`, `ok`, `carried`, `mismatch`.
- **Money_String**: A monetary value serialized as a fixed two-decimal string, never a float.
- **Whole_Dollar_Formatter**: The existing `formatMoneyWholeDollars` function in `frontend/src/lib/money.ts`.
- **Property_Service**: The user-scoped backend access to a user's property records.
- **Earliest_Data_Year**: For one property, the smaller of (a) the year of its earliest transaction date and (b) the year of its earliest depreciable asset's placed-in-service date; absent when neither exists.
- **Earliest_Year_Route**: The new read-only route `GET /properties/{propertyId}/earliest-year` that returns the Earliest_Data_Year.
- **Latest_Completed_Year**: The prior calendar year, the cap for every tax-year picker (`latestCompletedTaxYear()`).
- **Fallback_Window**: The six most recent years ending at the Latest_Completed_Year, offered when a property has no data.
- **Year_Range_Helper**: The shared frontend function that builds the selectable tax-year list for Reports_Page, Transactions_Page and Property_Detail_Page.
- **Reports_Page**, **Transactions_Page**, **Property_Detail_Page**: The frontend pages `ReportsPage.tsx`, `TransactionsPage.tsx` and `PropertyDetailPage.tsx`.

## Requirements

### Requirement 1: Tolerant status comparison

**User Story:** As the single user, I want amounts that differ only by whole-dollar rounding to count as matching, so that a faithfully filed return is not flagged for review.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL define `STATUS_TOLERANCE` as the exact `Decimal` value `2.00` in one module-level constant with a documenting comment.
2. WHEN a Reconciled_Year has a Reported_Carry_In that is Within_Tolerance of its Expected_Carry_In, THE Carryforward_Service SHALL assign the status `ok`.
3. WHEN a Reconciled_Year has a Reported_Carry_In that is not Within_Tolerance of its Expected_Carry_In, a Chain_In exists, and the Reported_Carry_In is Within_Tolerance of the Chain_In, THE Carryforward_Service SHALL assign the status `carried`.
4. WHEN a Reconciled_Year has a Reported_Carry_In that is Within_Tolerance of neither the Expected_Carry_In nor the Chain_In, THE Carryforward_Service SHALL assign the status `mismatch`.
5. WHEN a Reconciled_Year has no Reported_Carry_In, THE Carryforward_Service SHALL assign the status `unreported`.
6. THE Carryforward_Service SHALL evaluate the rules in the order `unreported`, `ok`, `carried`, `mismatch` and SHALL assign exactly one status to each Reconciled_Year.
7. THE Carryforward_Service SHALL evaluate each Within_Tolerance comparison independently for each year, so that tolerance used in one year never accumulates into another year's comparison.
8. THE Carryforward_Service SHALL compute every Within_Tolerance comparison with exact `Decimal` arithmetic and no floating-point value.
9. WHEN the absolute difference equals exactly `Status_Tolerance`, THE Carryforward_Service SHALL treat the amounts as Within_Tolerance.
10. WHEN the absolute difference exceeds `Status_Tolerance` by `0.01`, THE Carryforward_Service SHALL treat the amounts as not Within_Tolerance.

### Requirement 2: Values and attribution unchanged by the tolerance

**User Story:** As the single user, I want balances, drift and root-cause attribution to stay exact, so that the tolerance only changes the label and never the numbers.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL produce the same `expected_carry_in` and `expected_carryforward` values for every Reconciled_Year as before this feature, for any Opening_Balance, nets, allowed data and reported data.
2. THE Carryforward_Service SHALL compute `drift` as the exact signed cent difference `reported_carryforward - expected_carry_in`, or null when the year is unreported.
3. WHEN a Reconciled_Year has a nonzero `drift` whose absolute value is within the Status_Tolerance, THE Carryforward_Service SHALL assign the status `ok` and SHALL still report the nonzero `drift`.
4. THE Carryforward_Service SHALL determine `status` without reading `drift`.
5. WHEN a Reconciled_Year has the status `carried`, THE Carryforward_Service SHALL set `carried_from_year` to the tax year of the most recent earlier Reconciled_Year whose status is `mismatch`, as before this feature.
6. WHEN a Reconciled_Year has a status other than `carried`, THE Carryforward_Service SHALL set `carried_from_year` to null.
7. WHEN a Reconciled_Year is the first in the series, THE Carryforward_Service SHALL classify the year using the `unreported`, `ok` and `mismatch` rules only.
8. IF the Previous_Row has no Reported_Carry_In, THEN THE Carryforward_Service SHALL classify the year using the `unreported`, `ok` and `mismatch` rules only.
9. WHEN a gain year floors the running balance at `0.00`, THE Carryforward_Service SHALL apply the tolerance to the floored Expected_Carry_In and Chain_In values.
10. THE Carryforward_Service SHALL leave the storage keys, stored attributes, write routes and the §469 stance unchanged.

### Requirement 3: Backward compatibility of classification

**User Story:** As the single user, I want every year that already matches exactly to keep its label, so that the tolerance only forgives rounding.

#### Acceptance Criteria

1. WHEN a Reported_Carry_In equals the Expected_Carry_In to the cent, THE Carryforward_Service SHALL assign the status `ok`.
2. WHEN a year was `carried` before this feature and its Reported_Carry_In is not Within_Tolerance of the Expected_Carry_In, THE Carryforward_Service SHALL assign the status `carried`.
3. THE Carryforward_Service SHALL assign `unreported` to exactly the same Reconciled_Years as before this feature.
4. WHEN Status_Tolerance is `0.00`, THE Carryforward_Service SHALL produce the same statuses as before this feature.

### Requirement 4: Tolerance on the wire

**User Story:** As a frontend developer, I want the tolerance in the reconciliation response, so that the page can state it without hard-coding it.

#### Acceptance Criteria

1. WHEN a client requests `GET /carryforward`, THE Carryforward_Router SHALL include `status_tolerance` in the summary.
2. THE Carryforward_Router SHALL serialize `status_tolerance` as a two-decimal Money_String, `"2.00"` for the default constant.
3. THE Carryforward_Router SHALL keep every existing summary and year field and its value unchanged.
4. WHEN the user has no Data_Years and no Opening_Balance, THE Carryforward_Router SHALL still include `status_tolerance`.
5. THE Carryforward_API SHALL declare `status_tolerance: string` on the `ReconciliationSummary` type.

### Requirement 5: Mismatch hint names the line to check

**User Story:** As the single user, I want the hint on a flagged row to say which line to check and show both figures, so that I look at the right return.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has the status `mismatch` and is the first row in the series, THE Carryforward_Page SHALL render the hint "Compared with your opening balance."
2. WHEN a Reconciled_Year has the status `mismatch`, a Previous_Row exists, and the Previous_Row has no Reported_Carry_In, THE Carryforward_Page SHALL render the hint "The {prior} return is not reported, so this was compared with the expected figure only." with the Previous_Row's tax year substituted.
3. WHEN a Reconciled_Year has the status `mismatch`, a Previous_Row exists, and the Previous_Row has a Reported_Carry_In, THE Carryforward_Page SHALL render the hint "The {prior} return carried out about {carry-out}, but this return's line shows {reported}. Check this year's Form 8582 line and the {prior} return's carry-out."
4. THE Carryforward_Page SHALL substitute {carry-out} with the Previous_Row's `expected_carryforward` and {reported} with the row's `reported_carryforward`, each formatted by the Whole_Dollar_Formatter.
5. WHEN a Reconciled_Year has a status other than `mismatch`, THE Carryforward_Page SHALL render no hint.
6. THE Carryforward_Page SHALL format the hint figures from the Money_String text and SHALL NOT use floating-point arithmetic.

### Requirement 6: Page copy explains the tolerance

**User Story:** As the single user, I want the page to say why small differences count as OK, so that an OK status next to a nonzero drift is not confusing.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL render a sentence stating that matches within the tolerance count as OK because returns are filed in whole dollars.
2. THE Carryforward_Page SHALL build the tolerance figure in that sentence from the `status_tolerance` wire field formatted by the Whole_Dollar_Formatter, so the displayed figure follows the backend constant.
3. THE Carryforward_Page SHALL render the tolerance sentence whenever the reconciliation table is shown.
4. THE Carryforward_Page SHALL keep the reported editor, the allowed-loss control, the opening balance control, the Drift column, the disclaimer and the empty state with their current behaviour.

### Requirement 7: Earliest data year route

**User Story:** As the single user, I want the app to know the earliest year a property has any activity, so that I can pick any year that has data.

#### Acceptance Criteria

1. WHEN a client requests `GET /properties/{propertyId}/earliest-year` for a property the user owns, THE Earliest_Year_Route SHALL respond 200 with a JSON object containing `earliest_year` as an integer.
2. THE Earliest_Year_Route SHALL compute `earliest_year` as the smaller of the earliest transaction year and the earliest depreciable asset placed-in-service year for the property.
3. WHEN the property has transactions but no assets, THE Earliest_Year_Route SHALL return the earliest transaction year.
4. WHEN the property has assets but no transactions, THE Earliest_Year_Route SHALL return the earliest placed-in-service year.
5. WHEN the property has neither transactions nor assets, THE Earliest_Year_Route SHALL return `earliest_year` as JSON null.
6. THE Earliest_Year_Route SHALL read only the requesting user's data and SHALL respond 404 for a property the user does not own, consistent with the other property sub-routes.
7. THE Earliest_Year_Route SHALL find the earliest transaction by reading one item at the end of the property's transaction key order, and SHALL NOT load every transaction.
8. THE Earliest_Year_Route SHALL NOT modify any stored data.
9. THE Earliest_Year_Route SHALL return the earliest transaction year even when that year is later than the Latest_Completed_Year or earlier than the earliest asset year.

### Requirement 8: Shared year-range helper

**User Story:** As the single user, I want the Reports, Transactions and Property Detail pickers to offer every year back to my first activity, so that I can view 2010-2018 data.

#### Acceptance Criteria

1. THE Year_Range_Helper SHALL return the selectable tax years newest first, from the Latest_Completed_Year down to the earliest year of known activity, inclusive.
2. THE Year_Range_Helper SHALL take the earliest year of known activity as the smallest of the Earliest_Data_Year, every asset's placed-in-service year, and the start of the Fallback_Window.
3. WHEN neither the Earliest_Data_Year nor any asset exists, THE Year_Range_Helper SHALL return the Fallback_Window of six years ending at the Latest_Completed_Year.
4. WHEN the earliest year of known activity is later than the Latest_Completed_Year, THE Year_Range_Helper SHALL clamp the range so it never starts after the Latest_Completed_Year and is never empty.
5. THE Year_Range_Helper SHALL ignore a year below 1900 or a non-numeric year.
6. THE Reports_Page, THE Transactions_Page and THE Property_Detail_Page SHALL each obtain the Earliest_Data_Year for the current property through one shared frontend API function and build their year list with the Year_Range_Helper.
7. WHEN the Earliest_Year_Route request fails, THE Reports_Page, THE Transactions_Page and THE Property_Detail_Page SHALL fall back to the range built from assets alone and SHALL keep the page usable.
8. THE Property_Detail_Page SHALL use the shared Year_Range_Helper and SHALL NOT keep a private copy of the range function.
9. THE Reports_Page, THE Transactions_Page and THE Property_Detail_Page SHALL keep the Latest_Completed_Year as the default selection and the top of the list.
10. THE Transactions_Page SHALL keep "All years" selectable.

### Requirement 9: Existing test and build compatibility

**User Story:** As a maintainer, I want the existing suites to keep passing, so that the change is safe to ship.

#### Acceptance Criteria

1. THE backend carryforward tests under `backend/tests/services/test_carryforward_*.py` and `backend/tests/router/test_carryforward_*.py` SHALL pass after the change.
2. WHEN an existing backend test asserts exact-cent status equality, THE test SHALL be updated to the tolerance rule while keeping its original intent, and exact-cent assertions SHALL remain only where the intent is `drift` or expected values.
3. WHEN an existing generator produces a "mismatch" by offsetting a reported value by a cent, THE test SHALL offset by more than `Status_Tolerance` instead.
4. THE frontend fixtures that build a `ReconciliationSummary` SHALL include `status_tolerance` so that `npm run build` (`tsc -b`) succeeds.
5. WHEN an existing frontend test asserts the old mismatch hint text, THE test SHALL be updated to the new wording.
6. WHEN an existing frontend test stubs the asset list for a year-picker page, THE test SHALL also stub the Earliest_Data_Year function so no network is attempted.

### Requirement 10: Numeric integrity and scope limits

**User Story:** As the single user, I want exact money arithmetic and no scope creep, so that the reconciliation stays trustworthy.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL use exact `Decimal` arithmetic for every tolerance comparison, drift and chain value, with no floating-point value.
2. THE Carryforward_Page SHALL derive every displayed figure from Money_String text or integer cents, with no floating-point arithmetic on money.
3. THE feature SHALL NOT add a special-allowance field or any other new stored attribute.
4. THE feature SHALL add no write route; the Earliest_Year_Route is read-only.
