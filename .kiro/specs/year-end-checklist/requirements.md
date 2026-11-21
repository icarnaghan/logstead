# Requirements Document

## Introduction

Logstead is a single-user Schedule E rental tax app (React/Vite/Tailwind SPA; Python 3.12 Lambda over a single-table DynamoDB design; SAM infrastructure). The user's records for a tax year live in several places: transactions, itemized Repairs entries, depreciation schedules, loans, Schedule E imports, and the portfolio carryforward reconciliation. Today the user has to visit each page to judge whether a year is ready to file.

This feature adds a per-property, per-tax-year **Year-end checklist** that answers "am I ready to file?". It is **read-only**: it reads data the app already holds, writes nothing, and adds no stored data. Each checklist item has a status (`done`, `needs_attention`, or `not_applicable`), a one-line reason, and a link to the page where the user can fix it. A per-year **summary** (counts of items by status) appears on the property page and on the dashboard.

The checklist is a **reminder aid**. It checks completeness and consistency of the records in Logstead. It does not compute tax, does not say what the user should report, and uses no AI. The thresholds it applies (what counts as a large entry or a large swing) are configuration values, not prompts for tax decisions.

### Out of scope

- Any write, repair, or "fix it for me" action. Items link to the existing page that fixes the problem.
- Persisting checklist results, dismissing items, or marking items "reviewed".
- Per-user editing of thresholds in the UI (the configuration is a backend module in this release).
- The accountant package and PDF report, and the UI polish work (command palette, global search, activity history, mobile layout, onboarding). These are separate specs.
- Any change to the precedence rules, the carryforward algorithm, the loan schedule engine, or the Schedule E import parser.

### Grounding in the existing code

- `services/report.py` (`ReportingService.report_for`) is the single place that turns transactions into Schedule E line totals. It already exposes each line total, the `includes_imported` marker, and the Line 12 source with the superseded manual interest (`Line12Detail`).
- `services/itemized.py` holds `LineAccumulator` and `ITEMIZED_CATEGORIES`, which implement the entered-total-versus-itemized-sum rule. `LineResolution` already carries the entered total, itemized sum, itemized count, and the (possibly negative) remainder.
- `services/carryforward.py` (`CarryforwardService.reconcile`) classifies each year `ok`, `mismatch`, `carried`, or `unreported` using `STATUS_TOLERANCE` (`2.00`). The reconciliation is portfolio-level, not per property.
- `services/loan.py` (`LoanService`) provides per-year effective interest, per-year interest overrides (the user's confirmed figure), the balance anchor date and balance, and `include_in_report`.
- `services/depreciation.py` provides per-property schedules and `property_depreciation_for_year`.
- `services/transaction.py` lists transactions and stores receipts as `#DOC#` rows under the transaction. Transactions carry `imported`, `itemized`, `created_at`, and `updated_at`. The `imported` marker survives generic edits, so an edited imported row stays marked `imported` and has an `updated_at` later than its `created_at`.
- `router/handler.py` guards every `/properties/{propertyId}/...` route with `_property_scoped`, validates path ids with `_check_path_ids` and the year with `_int_param`, and maps service results to the error model in `docs/api.md`.
- Frontend: `PropertySection` + `PropertySectionTabs` (driven by `PROPERTY_NAV`), `PageHeader`, `StateBlock`, `Badge`, `ResponsiveTable`, `useAsyncResource`, the dashboard page, and the carryforward `DisclaimerNotice` wording ("reconciliation aid, not tax advice").

### Decisions recorded

- **Portfolio carryforward item.** The carryforward reconciliation is per user, not per property. The carryforward item therefore shows the same result on every property's checklist for a year (Requirement 9).
- **"Balance checkpoint" means the loan balance anchor.** Loan interest is treated as confirmed when the user entered an interest override for the year, or when a recent balance anchor exists (Requirement 8).
- **Edited-after-import is detected from timestamps.** An imported transaction counts as edited when its `updated_at` is later than its `created_at` (Requirement 14).
- **Threshold defaults are proposals.** The defaults in the Checklist_Config (Requirement 3) are starting values for review. They are configuration, so changing one needs no UI change.
- **Mortgage-interest item counts only loans that apply to the year.** The `line12_source` item flags a zero Line 12 only for an Applicable_Loan, so a loan anchored after the tax year or excluded from the report does not mark earlier years.
- **The checklist never blocks.** A `needs_attention` item is information. Nothing in the app is disabled by it.
- **Query parameter name.** `taxYear` is used on every route (Requirements 15.1, 15.3, 15.4, and 16.4).
- **Dashboard year.** The dashboard card uses the latest Data_Year from the trends headline. No year selector is added to the dashboard.
- **Loan rule for item 4.** The item counts only Applicable_Loans (Requirement 7).
- **Year-aware links need `?year=` support, added conditionally.** `TransactionsPage` and `ReportsPage` do not read `?year=` today. The shared `parseYearParam` helper in `lib/taxYears.ts` and the `?year=` initializers on those two pages are added by whichever of this spec or the `ui-polish` spec lands first: the task adds them if they are absent and reuses them if they are present. The two specs do not conflict, and neither duplicates the helper (Requirement 5.2).
- **The carryforward read cost is accepted.** `reconcile()` computes a report per property per Data_Year, and every Checklist request pays that cost once because item 6 is portfolio-level. This is acceptable for a single-user portfolio. A longer-lived cache is a later change if it becomes slow.
- **Edited-after-import is timestamp-based and only a re-import clears it.** Setting an edited imported amount back to the filed figure does not clear item 11 because the filed figure is not stored (Requirement 14).
- **The accountant package hook is part of this feature.** `logstead.services.checklist.provider_for(wiring, user)` lets the `accountant-package` spec include a checklist file without importing router internals (Requirement 24).

## Glossary

- **Logstead_API**: The Python Lambda backend reached through the router in `router/handler.py`.
- **Logstead_UI**: The React single-page frontend.
- **Checklist_Service**: The backend service that computes a Checklist for a (property, tax year). It reads `ReportingService`, `LineAccumulator`, `CarryforwardService`, `LoanService`, `DepreciationService`, and `TransactionService` outputs and holds no precedence rules of its own.
- **Checklist**: The ordered list of Checklist_Items for one (property, tax year), with its Checklist_Counts.
- **Checklist_Item**: One check, with an `id`, a `title`, a Status, a Reason, a Link, and optional `details`.
- **Item_Id**: The stable identifier of a Checklist_Item. The ids are `income_entered`, `expenses_entered`, `depreciation_present`, `line12_source`, `loan_interest_confirmed`, `carryforward_reconciled`, `repairs_exceed_total`, `repairs_capital_candidates`, `receipts_missing`, `yoy_swings`, and `imported_values_edited`.
- **Status**: One of `done`, `needs_attention`, or `not_applicable`.
- **Reason**: A single-sentence plain-language explanation of the Status, produced by the Logstead_API.
- **Link**: An app-relative path to the existing page where the user can fix or review the item, such as `/properties/{propertyId}/repairs?year=2024`.
- **Checklist_Counts**: The number of Checklist_Items per Status for one Checklist, plus the total.
- **Checklist_Summary**: The Checklist_Counts for one (property, tax year), without the items.
- **Checklist_Config**: The single backend configuration holding every threshold the checklist applies (Requirement 3).
- **Large_Entry_Amount**: The configured amount at or above which a transaction is "large" for the missing-receipt check.
- **Capital_Candidate_Amount**: The configured amount at or above which a single itemized Repairs entry is listed as a possible capital improvement.
- **Swing_Percent**: The configured percentage change between a line's total and the prior year's total at or above which the change is a swing.
- **Swing_Minimum_Amount**: The configured absolute dollar change that a swing must also reach.
- **Anchor_Max_Age_Months**: The configured maximum age, in months before the end of the tax year, of a loan balance anchor that still counts as a recent balance checkpoint.
- **Summary_Year_Count**: The configured number of most recent Data_Years shown in the property page summary.
- **Data_Year**: A tax year for which a property has data, as derived by the existing shared `derive_data_years` helper.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string such as `"1250.00"`; never a float and never a DynamoDB `Number`.
- **Completed_Tax_Year**: A tax year earlier than the current calendar year.
- **Applicable_Loan**: A loan of the property that is included in the report and whose balance anchor date is on or before December 31 of the tax year. A loan anchored after the tax year, and a loan excluded from the report, are not Applicable_Loans.
- **Receipt**: A supporting document attached to a transaction through the existing receipt mechanism (the UI labels it "Document").
- **Checklist_Provider**: The object returned by `provider_for(wiring, user)`. It exposes `checklist_for(property_id, tax_year)` and returns the same `Result[Checklist]` as `ChecklistService.checklist_for`.
- **Checklist_Disclaimer**: The notice stating that the checklist is a reminder aid and not tax advice.

## Requirements

### Requirement 1: Checklist for a property and tax year

**User Story:** As the property owner, I want one list that tells me what is done and what needs attention for a property and tax year, so that I know whether I am ready to file.

#### Acceptance Criteria

1. WHEN the user requests the Checklist for a property and a tax year, THE Logstead_API SHALL return one Checklist_Item for each Item_Id, in the fixed order listed in the Glossary.
2. THE Logstead_API SHALL give each Checklist_Item an `id`, `title`, `status`, `reason`, and `link`, and SHALL include `details` where Requirements 5 through 14 define them.
3. THE Logstead_API SHALL set each Status to exactly one of `done`, `needs_attention`, or `not_applicable`.
4. THE Logstead_API SHALL return Checklist_Counts for `done`, `needs_attention`, `not_applicable`, and the total, where the three status counts add up to the total.
5. THE Logstead_API SHALL return the same Checklist for identical stored data and an identical Checklist_Config (deterministic output).
6. THE Logstead_API SHALL return a Checklist for a tax year in which the property has no data, with each item's Status derived by the same rules.
7. THE Logstead_API SHALL echo the property id, the tax year, and the thresholds that were applied in the Checklist response.

### Requirement 2: Read-only behavior

**User Story:** As the property owner, I want the checklist to look but never change anything, so that opening it is always safe.

#### Acceptance Criteria

1. THE Checklist_Service SHALL perform no repository write, no S3 write, and no delete for any checklist or summary request.
2. THE Logstead_API SHALL expose the checklist and summary routes only through `GET`.
3. THE Checklist_Service SHALL introduce no new stored item, key, sort key, GSI, or table.
4. THE Checklist_Service SHALL NOT generate presigned URLs or load file contents when it determines whether a Receipt exists.
5. WHEN the user opens a Link, THE Logstead_UI SHALL navigate to the existing page without changing any data.

### Requirement 3: Thresholds are configuration

**User Story:** As the maintainer, I want every threshold in one configuration, so that changing a threshold needs no UI change and no search for hard-coded numbers.

#### Acceptance Criteria

1. THE Checklist_Config SHALL define Large_Entry_Amount, Capital_Candidate_Amount, Swing_Percent, Swing_Minimum_Amount, Anchor_Max_Age_Months, and Summary_Year_Count, and SHALL be the only place that holds those values.
2. THE Checklist_Config SHALL propose these defaults: Large_Entry_Amount `250.00`, Capital_Candidate_Amount `2500.00`, Swing_Percent `50`, Swing_Minimum_Amount `500.00`, Anchor_Max_Age_Months `12`, and Summary_Year_Count `5`.
3. THE Checklist_Config SHALL hold every money threshold as a `Decimal` and Swing_Percent as a `Decimal`, and SHALL serialize money thresholds as Money_Strings.
4. THE Logstead_API SHALL interpolate the applied threshold values into each Reason that depends on a threshold, so the text always matches the configured value.
5. THE Logstead_UI SHALL contain no threshold number and SHALL display only the Reason text and `details` values returned by the Logstead_API.
6. IF the Checklist_Config holds a money threshold below zero, a Swing_Percent at or below zero, or an Anchor_Max_Age_Months or Summary_Year_Count below one, THEN THE Checklist_Config SHALL raise a configuration error when it is loaded.
7. WHEN an amount equals a threshold exactly, THE Checklist_Service SHALL treat the amount as reaching the threshold (inclusive comparison).

### Requirement 4: Reuse of existing computations

**User Story:** As the maintainer, I want the checklist to reuse the report and service outputs, so that it can never disagree with the report or restate a precedence rule.

#### Acceptance Criteria

1. THE Checklist_Service SHALL obtain every Schedule E line total, the Line 12 source, and the superseded manual interest from `ReportingService.report_for` for the requested tax year.
2. THE Checklist_Service SHALL obtain the entered total, the itemized sum, and the remainder for an Itemized_Category from `LineAccumulator` and `LineResolution`.
3. THE Checklist_Service SHALL obtain the carryforward status and the carry-in figures from `CarryforwardService.reconcile`, and SHALL NOT compare reported and expected carry-in amounts itself.
4. THE Checklist_Service SHALL obtain loan interest, interest overrides, and anchor data from `LoanService`.
5. THE Checklist_Service SHALL obtain depreciation schedule data from `DepreciationService`.
6. THE Checklist_Service SHALL NOT implement the Line 12 precedence rule, the itemized precedence rule, or the carryforward tolerance rule.
7. FOR ALL (property, tax year) states, each line total that appears in a Checklist_Item `details` SHALL equal the corresponding `ReportingService.report_for` line total.
8. WHEN a Checklist or Checklist_Summary request needs the same upstream result more than once, THE Checklist_Service SHALL read it once per request. For the carryforward reconciliation, that read SHALL occur once per request across all properties in a dashboard summary.

### Requirement 5: Income and expenses entered

**User Story:** As the property owner, I want to know whether I entered income and expenses for the year, so that an empty year does not slip through.

#### Acceptance Criteria

1. WHEN the sum of the income line totals (Schedule E lines 3 and 4) for the year is greater than `0.00`, THE Checklist_Service SHALL set `income_entered` to `done`.
2. IF the sum of the income line totals for the year is `0.00`, THEN THE Checklist_Service SHALL set `income_entered` to `needs_attention`, with a Link to the property's Transactions page for the year.
3. WHEN at least one expense line other than Line 18 has a total greater than `0.00` for the year, THE Checklist_Service SHALL set `expenses_entered` to `done`.
4. IF every expense line other than Line 18 has a total of `0.00` for the year, THEN THE Checklist_Service SHALL set `expenses_entered` to `needs_attention`, with a Link to the property's Transactions page for the year.
5. THE Checklist_Service SHALL include the income total and the expense total (excluding Line 18) in the `details` of the respective item as Money_Strings.

### Requirement 6: Depreciation present for assets in service

**User Story:** As the property owner, I want to know whether depreciation is reflected for my assets, so that I do not forget Line 18.

#### Acceptance Criteria

1. WHEN no depreciable asset of the property has a schedule row for the tax year, THE Checklist_Service SHALL set `depreciation_present` to `not_applicable` with a Reason stating that no asset has depreciation scheduled for the year.
2. WHEN at least one asset has a schedule row for the tax year and the Line 18 total from the report is greater than `0.00`, THE Checklist_Service SHALL set `depreciation_present` to `done`.
3. IF at least one asset has a schedule row for the tax year and the Line 18 total from the report is `0.00`, THEN THE Checklist_Service SHALL set `depreciation_present` to `needs_attention`.
4. THE Checklist_Service SHALL give `depreciation_present` a Link to the property's Assets page.
5. THE Checklist_Service SHALL include the number of assets with a schedule row for the year and the Line 18 total in `details`.

### Requirement 7: Line 12 mortgage interest source

**User Story:** As the property owner, I want to see where my Line 12 mortgage interest came from and whether hand-entered interest was replaced, so that I do not double count or miss interest.

#### Acceptance Criteria

1. WHEN the report's Line 12 source is `loan-generated` and the superseded manual interest count is `0`, THE Checklist_Service SHALL set `line12_source` to `done` and state in the Reason that Line 12 comes from the loan schedule.
2. IF the report's Line 12 source is `loan-generated` and the superseded manual interest count is greater than `0`, THEN THE Checklist_Service SHALL set `line12_source` to `needs_attention`, and the Reason SHALL state the count and the total of the superseded manual entries and that the report does not use them.
3. WHEN the report's Line 12 source is `transaction-entered` and the Line 12 total is greater than `0.00`, THE Checklist_Service SHALL set `line12_source` to `done` and state in the Reason that Line 12 comes from entered transactions.
4. WHEN the report's Line 12 source is `transaction-entered`, the Line 12 total is `0.00`, and the property has no Applicable_Loan, THE Checklist_Service SHALL set `line12_source` to `not_applicable`.
5. IF the report's Line 12 source is `transaction-entered`, the Line 12 total is `0.00`, and the property has at least one Applicable_Loan, THEN THE Checklist_Service SHALL set `line12_source` to `needs_attention` and the Reason SHALL state that a loan applies to the year but produced no Line 12 interest.
6. THE Checklist_Service SHALL give `line12_source` a Link to the property's Loans page when the source is `loan-generated` or an Applicable_Loan exists, and otherwise a Link to the Transactions page for the year.
7. THE Checklist_Service SHALL include the source, the Line 12 total, and the superseded count and amount in `details`.

### Requirement 8: Loan interest confirmed or balance checkpoint present

**User Story:** As the property owner, I want to know whether the loan interest on my report is confirmed or backed by a recent balance, so that I know whether it is only an estimate.

#### Acceptance Criteria

1. WHEN the report's Line 12 source is not `loan-generated`, THE Checklist_Service SHALL set `loan_interest_confirmed` to `not_applicable`.
2. WHEN the report's Line 12 source is `loan-generated`, THE Checklist_Service SHALL evaluate each loan that is included in the report and has interest for the tax year.
3. WHEN a loan has an interest override for the tax year, THE Checklist_Service SHALL treat that loan as confirmed.
4. WHEN a loan has no interest override for the tax year and its balance anchor date falls within Anchor_Max_Age_Months before the end of the tax year or within the tax year, THE Checklist_Service SHALL treat that loan as having a recent balance checkpoint.
5. WHEN every evaluated loan is confirmed or has a recent balance checkpoint, THE Checklist_Service SHALL set `loan_interest_confirmed` to `done`.
6. IF at least one evaluated loan is neither confirmed nor has a recent balance checkpoint, THEN THE Checklist_Service SHALL set `loan_interest_confirmed` to `needs_attention`, and the Reason SHALL name the number of such loans and state that their interest is estimated from the schedule.
7. THE Checklist_Service SHALL give `loan_interest_confirmed` a Link to the property's Loans page.
8. THE Checklist_Service SHALL list, in `details`, each evaluated loan's id, display name, whether it is confirmed, its anchor date, and the interest used for the year as a Money_String.

### Requirement 9: Carryforward reconciled for the year

**User Story:** As the property owner, I want to know whether my reported carry-in for the year matches the expected carry-in, so that a break in the chain is not missed.

#### Acceptance Criteria

1. WHEN the carryforward reconciliation has no row for the tax year, THE Checklist_Service SHALL set `carryforward_reconciled` to `not_applicable`.
2. WHEN the reconciliation status for the year is `ok`, THE Checklist_Service SHALL set `carryforward_reconciled` to `done`.
3. WHEN the reconciliation status for the year is `unreported` and the year's expected carry-in is `0.00`, THE Checklist_Service SHALL set `carryforward_reconciled` to `not_applicable` with a Reason stating that no carry-in is expected.
4. IF the reconciliation status for the year is `unreported` and the year's expected carry-in is greater than `0.00`, THEN THE Checklist_Service SHALL set `carryforward_reconciled` to `needs_attention`, and the Reason SHALL state the expected carry-in.
5. IF the reconciliation status for the year is `mismatch`, THEN THE Checklist_Service SHALL set `carryforward_reconciled` to `needs_attention`, and the Reason SHALL state the reported carry-in, the expected carry-in, and the drift.
6. IF the reconciliation status for the year is `carried`, THEN THE Checklist_Service SHALL set `carryforward_reconciled` to `needs_attention`, and the Reason SHALL name the `carried_from_year`.
7. THE Reason of `carryforward_reconciled` SHALL state that the item is portfolio-level and the same on every property's checklist.
8. THE Reason of `carryforward_reconciled` SHALL state the existing status tolerance, taken from the reconciliation response and not restated in the Checklist_Config.
9. THE Checklist_Service SHALL give `carryforward_reconciled` a Link to the Carryforward page.
10. THE Checklist_Service SHALL include the status, the reported carry-in, the expected carry-in, and the drift as Money_Strings (or null) in `details`.

### Requirement 10: Itemized Repairs exceed the entered total

**User Story:** As the property owner, I want to know when my itemized repairs add up to more than the repairs total on the report, so that I can reconcile the two.

#### Acceptance Criteria

1. WHEN the Repairs line has an entered total and the remainder from `LineResolution` is less than `0.00`, THE Checklist_Service SHALL set `repairs_exceed_total` to `needs_attention`, and the Reason SHALL state the entered total, the itemized sum, and the amount by which the itemized sum exceeds the total.
2. WHEN the Repairs line has an entered total and at least one itemized entry and the remainder is `0.00` or greater, THE Checklist_Service SHALL set `repairs_exceed_total` to `done`.
3. WHEN the Repairs line has no itemized entry or no entered total, THE Checklist_Service SHALL set `repairs_exceed_total` to `not_applicable`.
4. THE Checklist_Service SHALL give `repairs_exceed_total` a Link to the property's Repairs page for the tax year.
5. THE Checklist_Service SHALL include the entered total, the itemized sum, the remainder, and the line source as Money_Strings or strings in `details`.

### Requirement 11: Large Repairs entries that may be capital improvements

**User Story:** As the property owner, I want to be pointed at large repair entries that I may want to review as improvements, so that I can decide whether they belong in Assets.

#### Acceptance Criteria

1. THE Checklist_Service SHALL evaluate every itemized entry of the Repairs category dated in the tax year against the Capital_Candidate_Amount.
2. WHEN at least one such entry has an amount at or above the Capital_Candidate_Amount, THE Checklist_Service SHALL set `repairs_capital_candidates` to `needs_attention`, and the Reason SHALL state the number of entries and the Capital_Candidate_Amount.
3. WHEN the property has at least one itemized Repairs entry for the year and none reaches the Capital_Candidate_Amount, THE Checklist_Service SHALL set `repairs_capital_candidates` to `done`.
4. WHEN the property has no itemized Repairs entry for the year, THE Checklist_Service SHALL set `repairs_capital_candidates` to `not_applicable`.
5. THE Checklist_Service SHALL word the Reason as a prompt to review, stating that the user decides whether an entry is a repair or an improvement, and SHALL NOT state that an entry is or is not a capital improvement.
6. THE Checklist_Service SHALL give `repairs_capital_candidates` a Link to the property's Assets page, and SHALL list in `details` each flagged entry's id, date, description, and amount, with a Link to the Repairs page for the year.

### Requirement 12: Receipts missing on large entries

**User Story:** As the property owner, I want to know which large entries have no receipt, so that I can attach documents before I need them.

#### Acceptance Criteria

1. THE Checklist_Service SHALL evaluate each expense transaction dated in the tax year that does not carry the `imported` marker and whose amount is at or above the Large_Entry_Amount.
2. WHEN at least one evaluated transaction has no Receipt, THE Checklist_Service SHALL set `receipts_missing` to `needs_attention`, and the Reason SHALL state the number of such transactions, the number evaluated, and the Large_Entry_Amount.
3. WHEN at least one transaction is evaluated and every evaluated transaction has at least one Receipt, THE Checklist_Service SHALL set `receipts_missing` to `done`.
4. WHEN no transaction is evaluated, THE Checklist_Service SHALL set `receipts_missing` to `not_applicable`.
5. THE Checklist_Service SHALL exclude imported summary rows from evaluation, because a Schedule E import produces year totals rather than individual purchases.
6. THE Checklist_Service SHALL give `receipts_missing` a Link to the property's Transactions page for the year, and SHALL list in `details` each transaction without a Receipt with its id, date, category, description, and amount, up to 25 entries, along with the total count.
7. THE Checklist_Service SHALL determine Receipt presence for all evaluated transactions of the year with no more than one receipt-metadata query per evaluated transaction, and SHALL NOT call S3.

### Requirement 13: Year-over-year swings by Schedule E line

**User Story:** As the property owner, I want to see which Schedule E lines changed a lot from last year, so that I can check for a typo or a missing entry.

#### Acceptance Criteria

1. THE Checklist_Service SHALL compare each Schedule E line total for the tax year with the same line total for the prior tax year, both obtained from `ReportingService.report_for`.
2. WHEN every line total of the prior year is `0.00`, THE Checklist_Service SHALL set `yoy_swings` to `not_applicable`, with a Reason stating that there is no prior-year data to compare.
3. THE Checklist_Service SHALL treat a line as a swing WHEN the absolute change is at or above the Swing_Minimum_Amount and either the prior-year total is `0.00` or the absolute change as a percentage of the prior-year total is at or above the Swing_Percent.
4. WHEN prior-year data exists and no line is a swing, THE Checklist_Service SHALL set `yoy_swings` to `done`.
5. IF at least one line is a swing, THEN THE Checklist_Service SHALL set `yoy_swings` to `needs_attention`, and the Reason SHALL state the number of lines and the Swing_Percent and Swing_Minimum_Amount that were applied.
6. THE Checklist_Service SHALL compute the absolute change and the percentage with `Decimal` arithmetic, with the percentage quantized to one decimal place.
7. THE Checklist_Service SHALL list in `details` each swing line's number, label, prior-year total, current-year total, signed change, and percentage (null when the prior-year total is `0.00`).
8. THE Checklist_Service SHALL give `yoy_swings` a Link to the property's Reports page for the year.
9. THE Checklist_Service SHALL word the Reason as a change to review and SHALL NOT say that a change is wrong.

### Requirement 14: Imported values later edited

**User Story:** As the property owner, I want to know when a value that came from an imported Schedule E has since been edited, so that I remember the line no longer matches the imported return.

#### Acceptance Criteria

1. THE Checklist_Service SHALL evaluate each transaction dated in the tax year that carries the `imported` marker.
2. WHEN no transaction carries the `imported` marker for the year, THE Checklist_Service SHALL set `imported_values_edited` to `not_applicable`.
3. WHEN at least one imported transaction exists and none has an `updated_at` later than its `created_at`, THE Checklist_Service SHALL set `imported_values_edited` to `done`.
4. IF at least one imported transaction has an `updated_at` later than its `created_at`, THEN THE Checklist_Service SHALL set `imported_values_edited` to `needs_attention`, and the Reason SHALL state the number of edited imported lines.
5. THE Checklist_Service SHALL list in `details` each edited imported transaction's id, Schedule E line, current amount, and `updated_at`.
6. THE Checklist_Service SHALL give `imported_values_edited` a Link to the property's Transactions page for the year.
7. THE Reason SHALL state that re-importing a Schedule E for the year replaces imported values.

### Requirement 15: Checklist and summary routes

**User Story:** As the property owner, I want the checklist and the summaries available through the API, so that the property page, the checklist page, and the dashboard can show them.

#### Acceptance Criteria

1. THE Logstead_API SHALL expose `GET /properties/{propertyId}/checklist?taxYear={year}` returning the Checklist.
2. THE Logstead_API SHALL expose `GET /properties/{propertyId}/checklist/summary` returning, for each of the most recent Summary_Year_Count Data_Years of the property (descending), the Checklist_Summary of that year.
3. THE Logstead_API SHALL expose `GET /checklist/summary?taxYear={year}` returning, for each property of the authenticated user, the Checklist_Summary for that year.
4. WHERE `taxYear` is omitted on a route that accepts it, THE Logstead_API SHALL use the latest Completed_Tax_Year.
5. THE Logstead_API SHALL return the same counts for a (property, tax year) from the Checklist route and both summary routes.
6. WHEN the property has no Data_Year, THE Logstead_API SHALL return an empty year list from the property summary route.
7. WHEN the user owns no property, THE Logstead_API SHALL return an empty property list from the dashboard summary route.
8. IF a collaborator reports a failure such as a corrupt stored loan, THEN THE Logstead_API SHALL return that failure through the existing error model and SHALL NOT return a partial Checklist.
9. THE Logstead_API SHALL serialize every money value of the Checklist as a Money_String.

### Requirement 16: Authorization and input validation

**User Story:** As the property owner, I want my checklist reachable only by me and bad input rejected, so that the new routes are as safe as the existing ones.

#### Acceptance Criteria

1. THE Logstead_API SHALL guard every route under `/properties/{propertyId}/checklist` with the existing `_property_scoped` ownership check before the service runs.
2. WHEN a user requests a checklist route with another user's property id, THE Logstead_API SHALL return a `404` response byte-identical to the response for a property id that does not exist, and SHALL read no data.
3. THE Logstead_API SHALL scope the dashboard summary route to the authenticated user's properties and SHALL NOT include another user's property in any count.
4. THE Logstead_API SHALL validate path ids with the existing `_check_path_ids` and `taxYear` with the existing `_int_param` bounds, and SHALL return `400` with `field: "taxYear"` for an out-of-range or non-numeric year.
5. THE Logstead_API SHALL embed in each Link only the property id taken from the validated path and the tax year taken from the validated parameter.
6. THE Logstead_API SHALL return errors in the existing error model of `docs/api.md`.

### Requirement 17: Property page summary

**User Story:** As the property owner, I want to see on the property page how many items need attention for each recent year, so that I can spot unfinished years at a glance.

#### Acceptance Criteria

1. THE Logstead_UI SHALL show a "Year-end checklist" summary section on the property page, listing each year returned by the property summary route with its needs-attention count, done count, and not-applicable count.
2. THE Logstead_UI SHALL show the needs-attention count as text such as "3 need attention" and SHALL show "All clear" when the count is `0` and at least one item is `done`.
3. THE Logstead_UI SHALL link each year in the section to the checklist page for that year.
4. WHILE the summary loads for the first time, THE Logstead_UI SHALL show a skeleton, and WHILE it reloads afterwards THE Logstead_UI SHALL keep the previous content mounted.
5. IF the summary fails to load, THEN THE Logstead_UI SHALL show an error `StateBlock` with a retry action and SHALL leave the rest of the property page usable.
6. WHEN the property has no Data_Year, THE Logstead_UI SHALL show an empty state that links to the Transactions page.

### Requirement 18: Dashboard summary

**User Story:** As the property owner, I want the dashboard to show how many items need attention per property for the selected year, so that I see which property to open first.

#### Acceptance Criteria

1. THE Logstead_UI SHALL show a "Year-end checklist" card on the dashboard listing each property with its needs-attention count for the dashboard's selected tax year.
2. THE Logstead_UI SHALL link each property row to that property's checklist page for the selected year.
3. WHEN the dashboard's selected tax year changes, THE Logstead_UI SHALL reload the card for the new year.
4. WHEN the user owns no property, THE Logstead_UI SHALL omit the card.
5. IF the summary fails to load, THEN THE Logstead_UI SHALL show an error state inside the card with a retry action and SHALL leave the rest of the dashboard unchanged.
6. THE Logstead_UI SHALL load the card independently of the other dashboard data, so a slow or failed summary does not delay the existing dashboard content.

### Requirement 19: Checklist page

**User Story:** As the property owner, I want a page that lists every item with its status, reason, and a link to fix it, so that I can work through the year.

#### Acceptance Criteria

1. THE Logstead_UI SHALL add a "Checklist" entry to the Property_Tabs and render the Checklist page at `/properties/:propertyId/checklist` inside the existing property layout, through `PropertySection` and `PageHeader`, with one `h1` and a document title of "Year-end checklist - {property name}".
2. THE Checklist page SHALL provide a tax-year selector that defaults to the latest Completed_Tax_Year, honors a `year` search parameter holding an offered year, and offers the same year range as the Transactions page.
3. THE Checklist page SHALL show, for each Checklist_Item, its title, a Status badge, the Reason, and a link labelled with the destination page and containing the item title in its accessible name.
4. THE Checklist page SHALL show the Checklist_Counts at the top as text, such as "3 need attention, 6 done, 2 not applicable".
5. THE Checklist page SHALL list items that need attention before the other items, and SHALL keep the fixed item order within each group.
6. WHERE a Checklist_Item has `details`, THE Checklist page SHALL show them in a disclosure that is collapsed by default, rendered with `ResponsiveTable` for tabular details and formatted with `formatMoney`.
7. WHILE the Checklist loads for the first time, THE Checklist page SHALL show a skeleton, and WHILE it reloads afterwards THE Checklist page SHALL keep the previous content mounted and show the refreshing indicator.
8. IF the Checklist fails to load, THEN THE Checklist page SHALL show an error `StateBlock` with a retry action.
9. THE Checklist page SHALL show the Checklist_Disclaimer near the top in every state, with wording consistent with the existing carryforward disclaimer: the checklist is a reminder aid, not tax advice, and it does not tell the user what to report.
10. THE Checklist page SHALL offer no button that changes data.
11. WHEN the user switches property with the property switcher while on the Checklist page, THE Logstead_UI SHALL stay on the Checklist section and carry over the `year` search parameter.

### Requirement 20: Accessibility and UI conventions

**User Story:** As a keyboard and screen-reader user, I want the checklist to follow the app's accessibility conventions, so that it is usable.

#### Acceptance Criteria

1. THE Logstead_UI SHALL build the Checklist page and both summary sections only from the shared primitives (`PageHeader`, `PropertySection`, `StateBlock`, `Badge`, `ResponsiveTable`, `Button`, `Card` or the existing dashboard card component) and semantic color and type tokens.
2. THE Logstead_UI SHALL express each Status through text and an icon in addition to color, with the Status text exposed to screen readers.
3. THE Checklist page SHALL pass the axe route suite in light and dark themes with exactly one `h1`, and the route SHALL be added to the Playwright accessibility spec.
4. THE Logstead_UI SHALL render the items as a list, so that screen readers announce the number of items.
5. WHEN the tax year changes, THE Checklist page SHALL announce the new counts through a polite live region.
6. THE Logstead_UI SHALL give each item link an accessible name that includes the item title.
7. THE Logstead_UI SHALL keep touch targets at 44px on narrow viewports through the shared `Button` and link styles.
8. THE Logstead_UI SHALL contain no AI-generated text and no tax advice; every Reason SHALL come from the Logstead_API.

### Requirement 21: Money handling

**User Story:** As the property owner, I want exact amounts everywhere, so that figures on the checklist match the report to the cent.

#### Acceptance Criteria

1. THE Logstead_API SHALL carry every monetary value of the feature as a `Decimal` in code and a two-decimal Money_String on the wire.
2. THE Logstead_UI SHALL display money through `formatMoney` and SHALL perform no floating-point arithmetic on money.
3. FOR ALL generated amounts, THE Checklist_Service SHALL compute sums, differences, absolute changes, and threshold comparisons exactly with `Decimal`.
4. THE Logstead_API SHALL include in each Reason money amounts formatted with two decimals.

### Requirement 22: Verification

**User Story:** As the maintainer, I want strong tests around the status rules and the read-only guarantee, so that the checklist cannot disagree with the report or change data.

#### Acceptance Criteria

1. THE test suite SHALL include a Hypothesis property test proving that, for arbitrary data, the Checklist has one item per Item_Id in the fixed order, each Status is one of the three values, and the status counts add up to the total.
2. THE test suite SHALL include a Hypothesis property test, run through the real `ReportingService` over moto, proving that every line total in the Checklist `details` equals the `report_for` line total.
3. THE test suite SHALL include a Hypothesis property test proving the threshold boundary: for arbitrary amounts and thresholds, an amount equal to a threshold reaches it and an amount one cent lower does not, for the Large_Entry_Amount, the Capital_Candidate_Amount, and the Swing_Minimum_Amount.
4. THE test suite SHALL include a Hypothesis property test of the year-over-year rule proving that a line is a swing exactly when the Requirement 13.3 condition holds, with arbitrary prior and current totals.
5. THE test suite SHALL include a read-only test proving that building a Checklist and both summaries performs no repository or S3 write, using a recording repository.
6. THE test suite SHALL include example tests for each Requirement 5 through 14 status rule, covering every `done`, `needs_attention`, and `not_applicable` branch.
7. THE test suite SHALL include a test proving that the checklist counts for a (property, tax year) are equal across the Checklist route and both summary routes.
8. THE test suite SHALL include a test proving that the carryforward reconciliation is read once for a dashboard summary that spans several properties.
9. THE test suite SHALL include router tests for every new route covering success, validation errors with `field`, and the cross-user `404` byte-identity of Requirement 16, added to `test_cross_user_authorization.py`.
10. THE test suite SHALL include a configuration test proving that an invalid Checklist_Config raises a configuration error, and that every threshold in a Reason matches the configuration.
11. THE frontend test suite SHALL include tests for the Checklist page states (loading, error, all clear, mixed statuses, empty year), the needs-attention-first ordering, the disclaimer in every state, the property page summary, the dashboard card, the nav entry, and the route in the axe suite.
12. THE frontend test suite SHALL include a test proving that no threshold number is defined in the frontend sources outside the values returned by the Logstead_API.
13. AFTER the feature is implemented, THE existing backend and frontend test suites, the frontend build, and the type check SHALL remain green.
14. THE test suite SHALL include a contract test for the Checklist_Provider as specified in Requirement 24.5 and 24.6.

### Requirement 23: Documentation

**User Story:** As the maintainer, I want the docs to describe the checklist, so that future work has context.

#### Acceptance Criteria

1. THE `docs/api.md` file SHALL document the three checklist routes, their parameters, and the response shape.
2. THE `docs/data-model.md` file SHALL state that the checklist stores no data and list the existing data each item reads.
3. THE `docs/developer-guide.md` file SHALL document the Item_Ids, the Checklist_Config and how to change a threshold, and how to add an item.
4. THE `CHANGELOG.md` file SHALL record the feature, including the Checklist_Provider hook used by the accountant package.
5. THE `docs/developer-guide.md` file SHALL also document `provider_for(wiring, user)`, its return type, and that the `accountant-package` feature imports it at run time.

### Requirement 24: Accountant package hook

**User Story:** As the maintainer of the accountant package, I want a stable entry point that returns a checklist generator, so that the package can include the checklist without importing router internals.

#### Acceptance Criteria

1. THE Checklist_Service module `logstead.services.checklist` SHALL expose a function `provider_for(wiring, user)` that accepts the router wiring object and a `UserContext` or a user id string.
2. THE function `provider_for` SHALL return a Checklist_Provider whose method `checklist_for(property_id, tax_year)` returns the same `Result[Checklist]` as `ChecklistService.checklist_for` for the same user, property, and year.
3. THE function `provider_for` SHALL perform no repository read and no S3 call until `checklist_for` is called, and the Checklist_Provider SHALL perform no write.
4. IF a collaborator of the Checklist_Service cannot be built from the wiring, THEN THE function `provider_for` SHALL raise an exception and SHALL NOT return a partial Checklist_Provider.
5. THE function `provider_for` SHALL keep the exact name and the parameters `(wiring, user)` used by `.kiro/specs/accountant-package/design.md`, and the accountant package SHALL treat a missing module, a missing `provider_for`, or a raised exception as an absent checklist.
6. THE test suite SHALL include a contract test proving that `provider_for(wiring, user)` returns an object with `checklist_for(property_id, tax_year)`, that the object returns a Checklist equal to the one the Checklist route returns, and that the accountant package's optional import contract holds: the package builder obtains the provider through `importlib.import_module("logstead.services.checklist")` and completes both when the module is present and when it is absent.
