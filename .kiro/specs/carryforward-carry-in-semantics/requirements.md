# Requirements Document

## Introduction

This feature corrects a semantic mismatch in the **passive loss carryforward reconciliation** (`CarryforwardService` at `backend/src/logstead/services/carryforward.py`; `Carryforward_Page` at `frontend/src/pages/CarryforwardPage.tsx`; sibling specs `.kiro/specs/passive-loss-carryforward/`, `.kiro/specs/carryforward-allowed-loss/` and `.kiro/specs/carryforward-chain-status/`).

### The problem this solves

For each year the user enters the Form 8582 line **"Prior years unallowed losses"**. That figure is the passive loss balance carried **into** that year from earlier years. The app currently treats the stored per-year value as the balance carried **out of** that year and compares it with the expected **end-of-year** balance. Every figure the user entered is therefore compared with the wrong year. Example: the 2015 form shows 837, which equals the expected end-2014 balance of 837, but the app compared 837 with the expected end-2015 balance of 2,452 and flagged a mismatch. In the user's real data, the entered figures minus the expected end-of-prior-year balance are a steady 2,645 for 2021 to 2025, which confirms that the real discrepancy is a single earlier error, not a per-year problem. The years 2016 to 2018 were left blank on the actual forms; a blank year is "unreported" and the app should help the user find and fix it.

### What this feature does

The app's semantics are changed to match the form. The stored per-year value (item `PLCF#<year>`, attribute `amount`, wire field `reported_carryforward`) is **reinterpreted as the carry-in** reported on that year's return. No data migration is needed because the user already entered these values as carry-in on the same year row.

- Each year exposes an **expected carry-in** (the balance expected to enter the year) and keeps its existing **expected carry-out** (the balance expected to leave the year, which is the next year's expected carry-in).
- Status for year Y compares the reported carry-in of Y with the expected carry-in of Y. The chain check is re-pointed: the chain value for Y is year Y-1's step applied to the **reported carry-in of Y-1**.
- A visible "expected to carry into next year" value is shown after the latest year, so the user can check the next return.
- UI labels, helper text, docstrings and docs use "Prior years' unallowed losses (Form 8582)" and carry-in wording.

### What this feature is, and is not

- The running-balance math is **unchanged**: a loss adds its unallowed portion, a gain is absorbed, the balance is floored at `0.00`, and the IRC §469 limitation is never applied. Only the year to which each reported figure is compared changes.
- The storage keys, stored attributes, write routes and the wire field names `reported_carryforward` and `expected_carryforward` are unchanged. New wire fields are additive.
- Allowed-loss controls stay on the loss row of the year that incurred the loss. They change that year's carry-out and therefore the next year's expected carry-in.
- The app remains a reconciliation aid, not a tax engine.

### Grounding (named seams)

- `backend/src/logstead/services/carryforward.py`: the `reconcile()` loop, `_apply_year_step`, `_effective_allowed`, `ReconciledYear`, `ReconciliationSummary`.
- `backend/src/logstead/router/handler.py`: `_carryforward_reconcile` and `_to_jsonable` (generic dataclass serialization, so new fields flow to the wire without handler changes).
- `frontend/src/api/carryforward.ts` (`ReconciledYear`, `ReconciliationSummary`), `frontend/src/pages/CarryforwardPage.tsx` (`ReconciliationTable`, `ReconciliationRow`, `ReportedEditor`, `StatusCell`, `DriftCell`, `DisclaimerNotice`), `frontend/src/lib/money.ts` (`formatMoneyWholeDollars`, `isLoss`).

## Glossary

- **Carryforward_Service**: The backend `CarryforwardService` that derives the reconciliation series and classifies each year.
- **Carryforward_Page**: The frontend page `CarryforwardPage.tsx` that renders the reconciliation table.
- **Carryforward_API**: The frontend transport module `frontend/src/api/carryforward.ts`, including the `ReconciledYear` and `ReconciliationSummary` wire types.
- **Reconciled_Year**: One entry in the ascending reconciliation series, one per Data_Year.
- **Data_Year**: A tax year for which the user has Schedule E data; the series spans exactly the Data_Years (unchanged, calendar gaps preserved).
- **Prior_Reconciled_Year**: The Reconciled_Year immediately before a given Reconciled_Year in the ascending series. The first Reconciled_Year has none.
- **Opening_Balance**: The user's non-negative starting suspended-loss balance entering the first Reconciled_Year (default `0.00`).
- **Schedule_E_Net**: The portfolio net for a year; negative denotes a loss (unchanged).
- **Loss_Year / Non_Loss_Year**: A year whose Schedule_E_Net is strictly less than `0.00` / any other year.
- **Effective_Allowed_Amount**: The allowed magnitude for a year from the existing `_effective_allowed` logic (unchanged).
- **Year_Step**: The existing balance step for a year. For a Loss_Year, `prior + max(Loss_Magnitude - Effective_Allowed_Amount, 0.00)`. For a Non_Loss_Year, `max(prior - Schedule_E_Net, 0.00)`.
- **Expected_Carry_Out**: The balance expected to leave a year: the Year_Step applied to the year's Expected_Carry_In. This is the existing running balance and the existing wire field `expected_carryforward`.
- **Expected_Carry_In**: The balance expected to enter a year. For the first Reconciled_Year it is the Opening_Balance; for every other year it is the Prior_Reconciled_Year's Expected_Carry_Out.
- **Reported_Carry_In**: The Form 8582 "Prior years unallowed losses" figure the user recorded for a year: a non-negative two-decimal magnitude, or absent. It is stored in the existing per-year attribute `amount` and exposed in the existing wire field `reported_carryforward`.
- **Chain_Carry_In**: For a Reconciled_Year whose Prior_Reconciled_Year has a Reported_Carry_In, the Year_Step of the **Prior_Reconciled_Year** (using its Schedule_E_Net and Effective_Allowed_Amount) applied to that prior Reported_Carry_In. It answers: "what should this return show if it faithfully carried the prior return's figure through the prior year's activity?"
- **Reconciliation_Status**: One of `unreported`, `ok`, `carried`, `mismatch`.
- **Mismatch_Year**: A Reconciled_Year with status `mismatch`. Its carry-in differs from both the Expected_Carry_In and the Chain_Carry_In (or no chain value exists), so the break occurred between the prior return's carry-out and this return's carry-in.
- **Carried_From_Year**: The `carried_from_year` field: for a `carried` year, the tax year of the most recent earlier Mismatch_Year, otherwise null. It names the year whose carry-in was the first to be wrong; the return to review is the one for the year before it (the return whose carry-out produced that wrong carry-in).
- **Drift**: `Reported_Carry_In - Expected_Carry_In` as a signed two-decimal value; positive means the return shows more than expected; null when the year is unreported.
- **Next_Year_Expected_Carry_In**: The Expected_Carry_Out of the latest Reconciled_Year, or the Opening_Balance when the series is empty. It is the figure the next return's "Prior years unallowed losses" line should show.
- **Money_String**: A monetary value serialized as a fixed two-decimal string (for example `"-2645.00"`), never a float.
- **Whole_Dollar_Formatter**: The existing `formatMoneyWholeDollars` function in `frontend/src/lib/money.ts`.

## Requirements

### Requirement 1: Expected carry-in and carry-out per year

**User Story:** As the single user, I want each year to show the balance expected to enter it and the balance expected to leave it, so that I can compare each form line with the right figure.

#### Acceptance Criteria

1. WHEN a Reconciled_Year is the first in the series, THE Carryforward_Service SHALL set its Expected_Carry_In to the Opening_Balance.
2. WHEN a Reconciled_Year is not the first in the series, THE Carryforward_Service SHALL set its Expected_Carry_In to the Prior_Reconciled_Year's Expected_Carry_Out.
3. THE Carryforward_Service SHALL set each year's Expected_Carry_Out to the Year_Step applied to that year's Expected_Carry_In, using the existing `_effective_allowed` and `_apply_year_step` logic.
4. THE Carryforward_Service SHALL produce the same `expected_carryforward` (Expected_Carry_Out) value for every Reconciled_Year as before this feature, for any Opening_Balance, nets, allowed data and reported data.
5. THE Carryforward_Service SHALL compute every Expected_Carry_In and Expected_Carry_Out as an exact two-decimal `Decimal` value.

### Requirement 2: Reported value is the carry-in

**User Story:** As the single user, I want the figure I enter for a year to mean the Form 8582 "Prior years unallowed losses" line of that year's return, so that what I type matches what is printed on the form.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL treat the stored per-year `amount` value as the Reported_Carry_In of that year.
2. THE Carryforward_Service SHALL leave the storage keys, stored attributes, validators, setters and write routes for the reported value unchanged.
3. THE Carryforward_Service SHALL require no data migration for existing stored values.
4. THE Carryforward_Service SHALL keep the wire field name `reported_carryforward` for the Reported_Carry_In.

### Requirement 3: Status classification against the carry-in

**User Story:** As the single user, I want each year's carry-in compared with the carry-in the app expects, so that real discrepancies are flagged against the correct year.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has no Reported_Carry_In, THE Carryforward_Service SHALL assign the status `unreported`.
2. WHEN a Reconciled_Year has a Reported_Carry_In equal to its Expected_Carry_In to the cent, THE Carryforward_Service SHALL assign the status `ok`.
3. WHEN a Reconciled_Year has a Reported_Carry_In that differs from its Expected_Carry_In, the Prior_Reconciled_Year has a Reported_Carry_In, and the Reported_Carry_In equals the Chain_Carry_In to the cent, THE Carryforward_Service SHALL assign the status `carried`.
4. WHEN a Reconciled_Year has a Reported_Carry_In that differs from its Expected_Carry_In and rule 3.3 does not apply, THE Carryforward_Service SHALL assign the status `mismatch`.
5. THE Carryforward_Service SHALL evaluate rules 3.1, 3.2, 3.3 and 3.4 in that order and SHALL assign exactly one status to each Reconciled_Year.
6. IF the Prior_Reconciled_Year has no Reported_Carry_In, THEN THE Carryforward_Service SHALL classify the year using rules 3.1, 3.2 and 3.4 only.
7. WHEN a Reconciled_Year is the first in the series, THE Carryforward_Service SHALL classify the year using rules 3.1, 3.2 and 3.4 only, comparing with the Opening_Balance.
8. WHEN every year has a Reported_Carry_In equal to the Prior_Reconciled_Year's Expected_Carry_Out (and the first year equals the Opening_Balance), THE Carryforward_Service SHALL assign the status `ok` to every year.

### Requirement 4: Chain value uses the prior year's step

**User Story:** As the single user, I want the chain check to reflect how a faithful return carries its prior figure forward, so that a year that merely inherited an earlier error is not blamed.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has a Prior_Reconciled_Year with a Reported_Carry_In, THE Carryforward_Service SHALL compute the Chain_Carry_In by applying the Year_Step of the Prior_Reconciled_Year to the Prior_Reconciled_Year's Reported_Carry_In.
2. THE Carryforward_Service SHALL use the Prior_Reconciled_Year's own Schedule_E_Net and Effective_Allowed_Amount when computing the Chain_Carry_In.
3. THE Carryforward_Service SHALL compute every Chain_Carry_In as an exact two-decimal `Decimal` value.
4. WHEN a later year contains an error independent of an earlier error, THE Carryforward_Service SHALL assign that later year the status `mismatch`.

### Requirement 5: Root-cause year attribution

**User Story:** As the single user, I want each inherited year to name the year whose carry-in was first wrong, so that I know which return to review.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has the status `carried`, THE Carryforward_Service SHALL set `carried_from_year` to the tax year of the most recent earlier Reconciled_Year whose status is `mismatch`.
2. IF a Reconciled_Year has the status `carried` and no earlier Reconciled_Year has the status `mismatch`, THEN THE Carryforward_Service SHALL set `carried_from_year` to null.
3. WHEN a Reconciled_Year has a status other than `carried`, THE Carryforward_Service SHALL set `carried_from_year` to null.
4. THE Carryforward_Service SHALL set `carried_from_year` to an integer tax year strictly less than the year's own `tax_year` or to null.

### Requirement 6: Drift value

**User Story:** As the single user, I want to see how far each reported carry-in is from the expected carry-in, so that I can judge the size of an error.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has a Reported_Carry_In, THE Carryforward_Service SHALL set `drift` to the Reported_Carry_In minus the Expected_Carry_In as an exact signed two-decimal value.
2. WHEN a Reconciled_Year has no Reported_Carry_In, THE Carryforward_Service SHALL set `drift` to null.
3. THE Carryforward_Service SHALL determine `status` independently of `drift`, so that `drift` alone never changes a status.

### Requirement 7: Wire contract

**User Story:** As a frontend developer, I want the existing reconciliation response to carry the carry-in figures additively, so that the page can render them without a new route.

#### Acceptance Criteria

1. WHEN a client requests `GET /carryforward`, THE Carryforward_Service router SHALL include `expected_carry_in` as a Money_String for every year in the response.
2. THE Carryforward_Service router SHALL keep the existing year fields `expected_carryforward`, `reported_carryforward`, `allowed_loss`, `fully_allowed`, `status`, `drift` and `carried_from_year`, with `expected_carryforward` carrying the Expected_Carry_Out.
3. WHEN a client requests `GET /carryforward`, THE Carryforward_Service router SHALL include `next_year` as a JSON integer or JSON null and `next_year_expected_carry_in` as a Money_String in the summary.
4. WHEN the series contains at least one year, THE Carryforward_Service SHALL set `next_year` to the latest Reconciled_Year's `tax_year` plus one and `next_year_expected_carry_in` to the latest year's Expected_Carry_Out.
5. WHEN the series is empty, THE Carryforward_Service SHALL set `next_year` to null and `next_year_expected_carry_in` to the Opening_Balance.
6. THE Carryforward_Service router SHALL serialize every new money value as a fixed two-decimal Money_String and SHALL NOT emit a float.
7. THE Carryforward_API SHALL declare `expected_carry_in: string` on `ReconciledYear` and `next_year: number | null` and `next_year_expected_carry_in: string` on `ReconciliationSummary`.

### Requirement 8: Table columns and copy

**User Story:** As the single user, I want the table headings and helper text to use the names on the tax form, so that I enter the right figure in the right place.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL render a column headed "Expected entering year" that shows each year's `expected_carry_in` using the Whole_Dollar_Formatter.
2. THE Carryforward_Page SHALL render the reported-value column headed "Prior years' unallowed losses (Form 8582)", containing the existing reported editor.
3. THE Carryforward_Page SHALL render a column headed "Expected to carry out" that shows each year's `expected_carryforward` using the Whole_Dollar_Formatter.
4. THE Carryforward_Page SHALL display helper text stating that the reported figure is the "Prior years unallowed losses" line on that year's Form 8582, that is, the balance carried into that year from earlier years.
5. THE Carryforward_Page SHALL name the reported editor's accessible label "Prior years' unallowed losses for {tax_year}".
6. THE Carryforward_Page SHALL render the same number of cells in every table row, including unreported rows.
7. THE Carryforward_Page SHALL keep the Drift column, the allowed-loss column and the Whole_Dollar_Formatter display of every money value.

### Requirement 9: Next-year expectation

**User Story:** As the single user, I want to see what the next return should show on the prior-years line, so that I can check it before I file.

#### Acceptance Criteria

1. WHEN the summary has `has_data` true, THE Carryforward_Page SHALL display a line "Expected to carry into {next_year}" with the `next_year_expected_carry_in` value formatted by the Whole_Dollar_Formatter.
2. WHEN `next_year` is null, THE Carryforward_Page SHALL display the line "Expected to carry into the next year" with the `next_year_expected_carry_in` value.
3. WHEN the user saves or clears a reported value, an allowed-loss value, a Fully_Allowed toggle or the opening balance, THE Carryforward_Page SHALL reload the series so that the next-year line, status and drift update together.

### Requirement 10: Status labels, hints and highlighting

**User Story:** As the single user, I want each status explained in terms of returns, so that I know which return to review.

#### Acceptance Criteria

1. WHEN a year has the status `mismatch`, THE Carryforward_Page SHALL render the label "Needs review" with the existing danger highlight on the row and status.
2. WHEN a year has the status `mismatch` and a Prior_Reconciled_Year with a Reported_Carry_In exists, THE Carryforward_Page SHALL render the hint "Does not match the {prior_year} return's carry-out. Review the {prior_year} return."
3. WHEN a year has the status `mismatch` and the Prior_Reconciled_Year has no Reported_Carry_In, THE Carryforward_Page SHALL render the hint "The {prior_year} return is not reported, so this was compared with the expected figure only."
4. WHEN a year has the status `mismatch` and is the first in the series, THE Carryforward_Page SHALL render the hint "Compared with your opening balance."
5. WHEN a year has the status `carried` and a non-null `carried_from_year`, THE Carryforward_Page SHALL render the label "Carried from {carried_from_year}" without the danger highlight.
6. WHEN a year has the status `carried` and a null `carried_from_year`, THE Carryforward_Page SHALL render the label "Carried from earlier year" without the danger highlight.
7. WHEN a year has the status `unreported`, THE Carryforward_Page SHALL render the label "Not reported" and SHALL still render that year's Expected_Carry_In so the user can fill in the blank form.
8. THE Carryforward_Page SHALL render the label "OK" for the status `ok`.
9. THE Carryforward_Page SHALL convey drift direction and status through text so meaning does not rest on colour alone.

### Requirement 11: Page copy and allowed-loss guidance

**User Story:** As the single user, I want the page introduction and disclaimer to describe carry-in semantics, so that the page does not mislead me.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL describe in its introduction that each year's expected figure is the loss balance expected to enter that year from earlier years, compared with the Form 8582 line the user reported.
2. THE Carryforward_Page SHALL update the disclaimer notice to refer to the expected carry-in and carry-out instead of the "expected carryforward" for a single end-of-year figure.
3. THE Carryforward_Page SHALL state next to the allowed-loss control that the allowed amount for a year changes the amount expected to carry into the next year.
4. THE Carryforward_Page SHALL keep the opening balance control, the allowed-loss control, the empty state and the reported editor behaviour, with the copy changes above.
5. THE Carryforward_Service docstrings and the Carryforward_API doc comments SHALL describe `reported_carryforward` as the carry-in and `expected_carryforward` as the carry-out.

### Requirement 12: Numeric integrity and scope limits

**User Story:** As the single user, I want exact money arithmetic and unchanged scope, so that the reconciliation stays trustworthy.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL compute Expected_Carry_In, Chain_Carry_In, drift and Next_Year_Expected_Carry_In using exact two-decimal `Decimal` arithmetic with no floating-point values.
2. THE Carryforward_Service SHALL derive all new values without applying the IRC §469 limitation.
3. THE Carryforward_Page SHALL derive the drift sign cue from the Money_String text and SHALL NOT use floating-point arithmetic on drift amounts.

### Requirement 13: Existing test and build compatibility

**User Story:** As a maintainer, I want every existing suite to keep passing after the semantics change, so that the change is safe to ship.

#### Acceptance Criteria

1. WHEN an existing backend test asserts the out-of-year comparison (status, drift or chain oracle based on `expected_carryforward`), THE test SHALL be updated to the carry-in rules in Requirements 3, 4 and 6 while keeping its original intent.
2. THE frontend fixtures that build `ReconciledYear` or `ReconciliationSummary` objects SHALL include `expected_carry_in`, `next_year` and `next_year_expected_carry_in` so that `npm run build` (`tsc -b`) succeeds.
3. WHEN an existing frontend test asserts a header, label or helper string changed by Requirements 8, 10 or 11, THE test SHALL be updated to the new copy.
4. THE backend carryforward tests under `tests/services/test_carryforward_*.py` and `tests/router/test_carryforward_*.py` SHALL pass after the change.
5. THE test suite SHALL include a worked example using the user's real 2014-2019 shape (loss years with allowed amounts, blanks in 2016-2018).
