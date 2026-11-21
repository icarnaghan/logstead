# Requirements Document

## Introduction

This feature bundles two related, user-approved changes to how Logstead handles and displays depreciation on the single-user Schedule E rental tax app (React 19 + Vite + TypeScript SPA, Monarch-style theming; Python 3.12 Lambda over single-table DynamoDB, S3, Cognito JWT auth).

The two changes share a motivation: making the app reproduce the depreciation figures a user actually filed on historical tax returns, while keeping the app's internal math exact.

- **Feature A — Per-year depreciation override.** Today the depreciation engine (`compute_schedule_rows` in `backend/src/logstead/services/depreciation.py`) computes a straight-line + mid-month (MACRS) schedule as a pure function of the asset, and materializes the per-year rows in DynamoDB. It guarantees two correctness invariants, enforced by Hypothesis property tests: (1) the per-year `amount` values sum **exactly** to `cost_basis`; and (2) each year's `remaining_basis` is non-increasing and ends at exactly `0.00`. There is currently no way to pin a single year to a value that differs from the computed one. A concrete need: a June-2010, $140,000, 27.5-year residential-rental asset whose correct mid-month first-year value is ~$2,758, but whose filed 2010 Form 4562 (prepared by H&R Block) reported $1,952. The user wants to make the app agree with the filed return without abandoning the engine's exactness guarantees. The approved approach ("Option 1") adds an optional per-year override map to the asset, applied after the normal computation, with the delta rolled into the final (tail) year so both invariants still hold exactly.

- **Feature B — Whole-dollar display rounding.** Tax returns report whole-dollar line amounts. The user wants the tax-oriented display surfaces to show amounts rounded to the nearest whole dollar (IRS standard: 0.50 and above rounds up, below rounds down — explicitly **not** ceiling/round-up). This is a **display-only** change: stored and computed values stay exact two-decimal, and rounding happens only at the UI formatting boundary, reusing the integer-cents approach in `frontend/src/lib/money.ts` with no floating-point arithmetic.

### What these features are, and are not

- The override is a **deliberate reproduction of a known filed value**, not a general-purpose manual depreciation editor or a basis-adjustment tool. The engine's two invariants are preserved by construction: an override that would make an invariant impossible is rejected with a field-identifying validation error rather than silently breaking the sum-to-basis guarantee.
- Whole-dollar rounding is a **presentation concern only**. The schedule engine, API payloads, passive-loss-carryforward reconciliation math, and the sum-to-basis invariant are unchanged. No stored or transported value is rounded. There is no float math anywhere in the money pipeline, and this feature does not introduce any.

### Grounding: concrete seams this feature builds on

These are named so the design can be precise; the requirements stay implementation-agnostic where possible.

- **Engine:** `compute_schedule_rows(asset) -> list[DepreciationScheduleRow]` — pure, computes straight-line + mid-month; first (placed-in-service) year prorated by `(12.5 - month)/12`; recovery spans `ceil(recovery)+1` tax years; the tail year is pinned to exact cost basis to absorb rounding.
- **Persistence:** `create_asset`/`update_asset` call `_materialize_schedule`, recomputing rows and writing them under SK `ASSET#<assetId>#SCHED#<taxYear>` in one transaction (with a GSI2 tax-year partition); `delete_asset` cascades. `property_depreciation_for_year` reads rows via a GSI2 query for the Schedule E report.
- **Asset model:** `DepreciableAsset` (`backend/src/logstead/models/depreciation.py`): `id`, `property_id`, `description`, `cost_basis: Decimal`, `placed_in_service_date: 'YYYY-MM-DD'`, `recovery_period_years: Decimal = 27.5`, `created_at`, `updated_at`; `AssetInput` mirrors the editable fields.
- **Validation pattern:** `Result`-based validation in `depreciation.py` (`Result.failure("validation", message, field=...)`).
- **Backend money util:** `backend/src/logstead/util/money.py` (`to_money` / two-decimal `Decimal` quantization).
- **Frontend assets API:** `frontend/src/api/assets.ts` (`DepreciableAsset`, `CreateAssetInput`, `UpdateAssetInput`, `ScheduleRow { tax_year, amount, remaining_basis, method, convention }`, `listAssets`/`createAsset`/`updateAsset`/`getSchedule`).
- **Frontend money helpers:** `frontend/src/lib/money.ts` — the single canonical `formatMoney(string)` plus `toCents`/`centsToMoney`/`sumMoney`/`isLoss`. Money is a fixed two-decimal string across the API; the UI never does float math (integer-cents only). Call sites include ReportView, ScheduleELineTable, OtherItemsList, AssetList, DashboardPage (depreciation + net tiles), PortfolioSummary, CarryforwardPage, PropertyDetailPage, and TransactionsPage.

### Open question for requirements review

Feature B scope — the user said "all numbers in the UI round up as they would in the tax returns." Tax returns round reported **line** amounts, not raw data entry. These requirements **propose** that whole-dollar rounding applies to the **tax-oriented display surfaces that mirror a return** (the Schedule E report / ReportView and its line tables, the depreciation schedule display, the dashboard depreciation + net figures, and the carryforward table), while **raw transaction-entry amounts** (TransactionsPage amounts, asset cost-basis input echoes) remain at cent precision. This is the one open assumption to confirm during review; see Requirement 11. If the user intends literally every money value to round, Requirement 11 changes to cover all `formatMoney` call sites.

## Glossary

- **Depreciation_Engine**: The pure backend function `compute_schedule_rows(asset)` that computes an asset's straight-line + mid-month depreciation schedule and guarantees the two engine invariants.
- **Depreciation_Service**: The existing backend `DepreciationService`, which validates asset input and materializes/reads schedule rows via `create_asset`, `update_asset`, `delete_asset`, `_materialize_schedule`, and `property_depreciation_for_year`.
- **Depreciable_Asset**: A persisted asset (`DepreciableAsset`) with a cost basis, placed-in-service date, and recovery period, under an owning property.
- **Override_Map**: An optional map on a Depreciable_Asset from Tax_Year to a two-decimal override Amount, persisted as a single DynamoDB attribute on the asset item (a map/JSON value), not as separate schedule-row items, keys, or routes.
- **Override_Amount**: A single two-decimal money value in the Override_Map that pins a specific Tax_Year's depreciation `amount` to a user-supplied value.
- **Tax_Year**: A four-digit calendar year appearing in an asset's computed schedule (from the placed-in-service year through the tail year).
- **Computed_Schedule**: The list of per-year schedule rows the Depreciation_Engine produces before any overrides are applied.
- **Effective_Schedule**: The schedule after overrides are applied — the Computed_Schedule with each overridden year's `amount` replaced by its Override_Amount and the resulting delta absorbed into the tail year.
- **Tail_Year**: The last (chronologically final) Tax_Year of an asset's schedule, which the engine pins so per-year amounts sum exactly to cost basis.
- **Invariant_Sum**: Engine invariant 1 — the per-year `amount` values of a schedule sum exactly to the asset's `cost_basis`.
- **Invariant_Monotonic**: Engine invariant 2 — each year's `remaining_basis` is non-increasing across the schedule and ends at exactly `0.00`.
- **Schedule_Row**: One tax-year row of a schedule (`DepreciationScheduleRow`): `tax_year`, `amount`, `remaining_basis`, `method`, `convention`.
- **Asset_Schedule_UI**: The per-property frontend surface that displays an asset's depreciation schedule and (with this feature) lets the user enter or clear a per-year Override_Amount.
- **Override_Marker**: A visual indication in the Asset_Schedule_UI that a given Tax_Year's amount is an override rather than a computed value, accompanied by a short explanatory note.
- **Money_String**: A monetary value serialized over the wire and stored as a fixed two-decimal string (e.g. `"2758.00"`, `"-125.00"`), never a float and never a DynamoDB `Number`.
- **Whole_Dollar_Formatter**: The frontend display helper that renders a Money_String rounded to the nearest whole dollar for tax-oriented surfaces, computed in integer cents with no floating-point arithmetic.
- **Nearest_Whole_Dollar**: Rounding to the nearest integer dollar using the IRS convention — a cents remainder of 50 or more rounds the dollar amount away from zero in magnitude; below 50 truncates toward zero in magnitude (e.g. `5090.91` → `5091`, `5090.10` → `5090`, `5090.50` → `5091`).
- **Tax_Oriented_Surface**: A display surface that mirrors a filed tax return — the Schedule E report / ReportView and its line tables, the depreciation schedule display, the dashboard depreciation and net figures, and the carryforward table.
- **Raw_Entry_Surface**: A display surface showing raw data-entry amounts rather than return-style line totals — transaction amounts on TransactionsPage and asset cost-basis input echoes — which retain cent precision.

## Requirements

### Requirement 1: Per-year override map on the asset

**User Story:** As the single user, I want to attach optional per-year depreciation overrides to an asset, so that the app can reproduce a value I actually filed on a historical return.

#### Acceptance Criteria

1. THE Depreciable_Asset SHALL support an optional Override_Map from Tax_Year to a two-decimal Override_Amount.
2. THE Depreciation_Service SHALL persist the Override_Map as a single attribute on the asset DynamoDB item, and SHALL NOT create additional schedule-row items, sort keys, routes, or tables to store overrides.
3. WHERE a Depreciable_Asset has no Override_Map attribute, THE Depreciation_Service SHALL treat the asset as having no overrides.
4. THE Depreciation_Service SHALL serialize every Override_Amount in the Override_Map over the wire as a Money_String.
5. WHERE an asset has an Override_Map, THE Depreciation_Service SHALL scope every read and write of that Override_Map to the authenticated user's own property, so that one user can never read or modify another user's overrides.

### Requirement 2: Apply overrides after computing the normal schedule

**User Story:** As the single user, I want each overridden year to show my filed value while the rest of the schedule stays correct, so that the schedule matches my return without my recomputing anything.

#### Acceptance Criteria

1. THE Depreciation_Engine SHALL compute the Computed_Schedule first, then apply the Override_Map to produce the Effective_Schedule.
2. WHERE a Tax_Year has an Override_Amount in the Override_Map, THE Depreciation_Engine SHALL set that Tax_Year's Schedule_Row `amount` to the Override_Amount in the Effective_Schedule.
3. THE Depreciation_Engine SHALL absorb the total delta introduced by all applied overrides into the Tail_Year's `amount`, so that the Effective_Schedule's per-year amounts sum exactly to the asset's `cost_basis`.
4. THE Depreciation_Engine SHALL recompute each Schedule_Row's `remaining_basis` in the Effective_Schedule from the Effective_Schedule's amounts, so that `remaining_basis` equals `cost_basis` minus the cumulative amount through that year.
5. WHERE the Tail_Year itself has an Override_Amount, THE Depreciation_Engine SHALL apply the validation rules of Requirement 3 rather than overwriting the Tail_Year with an absorbed delta that would contradict the user's override.
6. THE Depreciation_Engine SHALL compute the Effective_Schedule using exact two-decimal `Decimal` arithmetic with no floating-point drift.

### Requirement 3: Validate overrides so the invariants remain satisfiable

**User Story:** As the single user, I want the app to reject overrides that cannot be reconciled with the asset's cost basis, so that the schedule never silently becomes wrong.

#### Acceptance Criteria

1. IF any Override_Amount is negative or is not a valid two-decimal money amount, THEN THE Depreciation_Service SHALL reject the asset input with a validation error identifying the offending Tax_Year and SHALL NOT persist any change.
2. IF an Override_Amount is specified for a Tax_Year that does not appear in the asset's Computed_Schedule, THEN THE Depreciation_Service SHALL reject the asset input with a validation error identifying that Tax_Year and SHALL NOT persist any change.
3. IF the sum of all Override_Amounts exceeds the asset's `cost_basis`, THEN THE Depreciation_Service SHALL reject the asset input with a validation error and SHALL NOT persist any change.
4. IF applying the overrides would require the Tail_Year's `amount` to be negative in order to preserve Invariant_Sum, THEN THE Depreciation_Service SHALL reject the asset input with a validation error and SHALL NOT persist any change.
5. IF applying the overrides would require the Tail_Year's `amount` to be negative AND the Tail_Year itself is overridden (so no absorbing year remains), THEN THE Depreciation_Service SHALL reject the asset input with a validation error and SHALL NOT persist any change.
6. WHEN the Depreciation_Service rejects an override, THE Depreciation_Service SHALL follow the existing `Result`-based validation pattern, returning a `validation` failure whose field identifies the offending input.

### Requirement 4: Materialize and re-materialize overridden schedules through existing paths

**User Story:** As the single user, I want editing an override to update the stored schedule the same way editing any other asset field does, so that reports and the dashboard reflect my override immediately.

#### Acceptance Criteria

1. WHEN the user creates an asset with an Override_Map, THE Depreciation_Service SHALL apply the overrides and materialize the Effective_Schedule rows through the existing `create_asset` / `_materialize_schedule` path in a single transaction.
2. WHEN the user updates an asset's Override_Map, THE Depreciation_Service SHALL recompute the Effective_Schedule and rewrite the materialized rows through the existing `update_asset` / `_materialize_schedule` path in a single transaction.
3. WHEN the user clears a Tax_Year's Override_Amount, THE Depreciation_Service SHALL recompute and re-materialize the schedule so that Tax_Year returns to its computed value.
4. THE property-level per-year depreciation read by `property_depreciation_for_year` SHALL reflect the Effective_Schedule for any asset that has overrides, so the Schedule E report consumes the overridden amounts.
5. WHEN an asset with overrides is deleted, THE Depreciation_Service SHALL cascade-delete its materialized schedule rows exactly as for an asset without overrides.

### Requirement 5: Backward compatibility for assets without overrides

**User Story:** As the single user, I want every existing asset to behave exactly as it does today, so that adding the override feature changes nothing for assets I never override.

#### Acceptance Criteria

1. WHERE a Depreciable_Asset has no Override_Map, THE Depreciation_Engine SHALL produce a schedule identical, row for row and value for value, to the schedule it produces today.
2. THE Depreciation_Service SHALL read and write an asset that has no Override_Map attribute without error, treating the absent attribute as "no overrides".
3. THE Depreciation_Service SHALL preserve the existing item shape for the cost basis, recovery period, and all other existing asset attributes when the Override_Map is absent.

### Requirement 6: Enter and clear overrides in the schedule UI

**User Story:** As the single user, I want to enter or clear a per-year override in the per-property asset schedule, so that I can pin a year to my filed value from the interface.

#### Acceptance Criteria

1. WHEN the Asset_Schedule_UI renders an asset's schedule, THE Asset_Schedule_UI SHALL provide a control to enter or edit an Override_Amount for each Tax_Year in the schedule.
2. WHEN the user submits an Override_Amount for a Tax_Year, THE Asset_Schedule_UI SHALL send the updated Override_Map through the existing asset update path and reflect the re-materialized schedule without requiring a full page reload.
3. WHEN the user clears a Tax_Year's Override_Amount, THE Asset_Schedule_UI SHALL send the updated Override_Map so that Tax_Year reverts to its computed value in the displayed schedule.
4. IF the Depreciation_Service rejects an override per Requirement 3, THEN THE Asset_Schedule_UI SHALL surface the validation error next to the offending Tax_Year's control and SHALL NOT leave the schedule in a state that implies the override was saved.
5. THE Asset_Schedule_UI SHALL perform no floating-point arithmetic on Override_Amounts, handling them as Money_Strings through the existing integer-cents helpers.

### Requirement 7: Mark overridden years in the schedule UI

**User Story:** As the single user, I want overridden years to be visually marked and explained, so that a future reader understands why a year is pinned.

#### Acceptance Criteria

1. WHERE a Tax_Year's displayed amount comes from an Override_Amount, THE Asset_Schedule_UI SHALL display an Override_Marker distinguishing that year from computed years, using a textual indication so the distinction never rests on color alone.
2. WHEN the Asset_Schedule_UI shows an Override_Marker, THE Asset_Schedule_UI SHALL show a short note explaining that the year's amount is pinned to reproduce a value from a filed return rather than the app's computed value.
3. WHERE no Tax_Year is overridden, THE Asset_Schedule_UI SHALL display no Override_Marker and SHALL present the schedule as it does today.

### Requirement 8: Nearest-whole-dollar display formatter

**User Story:** As the single user, I want a display helper that rounds a money value to the nearest whole dollar the way a tax return does, so that tax-oriented figures read as whole dollars.

#### Acceptance Criteria

1. THE Whole_Dollar_Formatter SHALL round a Money_String to the Nearest_Whole_Dollar, where a cents remainder of 50 or more rounds the magnitude up and a remainder below 50 rounds the magnitude down.
2. THE Whole_Dollar_Formatter SHALL NOT use ceiling (always-round-up) rounding.
3. THE Whole_Dollar_Formatter SHALL compute the rounded value in exact integer cents and SHALL perform no floating-point arithmetic.
4. WHERE the Money_String is empty, `null`, or `undefined`, THE Whole_Dollar_Formatter SHALL pass through the same empty result as the existing `formatMoney` helper.
5. WHERE the Money_String represents a loss (a negative amount), THE Whole_Dollar_Formatter SHALL round the magnitude to the Nearest_Whole_Dollar and preserve the negative sign.
6. THE Whole_Dollar_Formatter SHALL render the rounded value in the app's existing US-currency display format with no cents shown.

### Requirement 9: Display-only rounding leaves stored and computed values exact

**User Story:** As the single user, I want whole-dollar rounding to affect only what I see, so that my data, reports, and reconciliation math stay exact.

#### Acceptance Criteria

1. THE Whole_Dollar_Formatter SHALL round only at the display boundary and SHALL NOT alter any stored value, API payload, or computed value.
2. THE Depreciation_Engine, the Depreciation_Service, the passive-loss-carryforward reconciliation math, and the Invariant_Sum SHALL be unchanged by the introduction of whole-dollar display rounding.
3. THE API SHALL continue to serialize every monetary value as a two-decimal Money_String regardless of whole-dollar display rounding.

### Requirement 10: Preserve alignment and accessibility cues under rounding

**User Story:** As the single user, I want rounded figures to stay aligned and keep their loss cues, so that the tables remain readable and accessible.

#### Acceptance Criteria

1. WHEN a Tax_Oriented_Surface renders Whole_Dollar_Formatter values in a column, THE Tax_Oriented_Surface SHALL preserve the existing tabular-numeric alignment used for money columns.
2. WHERE a rounded value represents a loss, THE Tax_Oriented_Surface SHALL preserve the existing textual loss indication (the `isLoss` cue) so the loss distinction never rests on color alone.

### Requirement 11: Scope whole-dollar rounding to tax-oriented surfaces (confirmed)

> **Scope resolved (review):** Whole-dollar rounding applies **only** to the tax-oriented surfaces listed below (Schedule E report / ReportView and its line tables, the depreciation schedule display, the dashboard depreciation and net figures, and the carryforward table). Raw transaction-entry amounts (TransactionsPage amounts) and asset cost-basis input echoes (AssetList) stay at two-decimal cent precision. The broader "every `formatMoney` site" interpretation in 11.6 was **not** chosen.

**User Story:** As the single user, I want whole-dollar rounding where my app mirrors a tax return, so that return-style figures read as whole dollars while raw data entry keeps its cents.

#### Acceptance Criteria

1. THE Schedule E report / ReportView and its line tables SHALL display monetary line figures through the Whole_Dollar_Formatter.
2. THE depreciation schedule display SHALL show per-year amounts and remaining basis through the Whole_Dollar_Formatter.
3. THE dashboard depreciation figure and the dashboard net figure SHALL display through the Whole_Dollar_Formatter.
4. THE carryforward reconciliation table SHALL display its monetary figures through the Whole_Dollar_Formatter.
5. THE Raw_Entry_Surface (TransactionsPage transaction amounts and asset cost-basis input echoes) SHALL continue to display at two-decimal cent precision through the existing `formatMoney` helper, unless the user confirms during review that literally every money value in the UI should round to whole dollars.
6. WHEN the user confirms the broader scope during review, THE feature SHALL apply the Whole_Dollar_Formatter to all money display sites currently using `formatMoney`, and this requirement SHALL be updated to record that decision.

### Requirement 12: Non-functional — suites green, invariants preserved, no new float math

**User Story:** As the single user, I want the existing guarantees to hold after these changes, so that I can trust the schedule and the display.

#### Acceptance Criteria

1. AFTER the override feature is implemented, THE existing backend test suite SHALL remain green, including the Hypothesis property tests that enforce Invariant_Sum and Invariant_Monotonic.
2. THE override feature SHALL add Hypothesis property tests proving that, for arbitrary valid Override_Maps, the Effective_Schedule still satisfies Invariant_Sum and Invariant_Monotonic.
3. THE override feature SHALL add a Hypothesis property test proving that an asset with no Override_Map produces a schedule identical to the schedule produced with overrides disabled (backward compatibility, Requirement 5.1).
4. AFTER the whole-dollar display feature is implemented, THE frontend build and frontend test suite SHALL remain green.
5. THE whole-dollar display feature SHALL introduce no floating-point arithmetic into the money pipeline, performing all rounding in exact integer cents.
