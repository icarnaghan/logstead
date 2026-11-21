# Requirements Document

## Introduction

This feature extends the existing **passive loss carryforward reconciliation** (`CarryforwardService` at `backend/src/logstead/services/carryforward.py`; `Carryforward_Page` at `frontend/src/pages/CarryforwardPage.tsx`; specs `.kiro/specs/passive-loss-carryforward/` and `.kiro/specs/carryforward-allowed-loss/`) so the one year whose filed return actually mishandled a carryover stands out from the years that merely inherited its error.

### The problem this solves

The app's `Expected_Carryforward` is a running balance built from the app's own Schedule E nets (and any recorded allowed loss). Each later filed return, however, correctly carried forward its **own** prior-year figure. When one year's return contains a mistake (for example a dropped carryover), that wrong figure is carried into every following return. The app keeps comparing those later returns to its own, correct running balance, so **every** year after the mistake reads "Needs review". The single year that needs amending is buried among years that are internally consistent with the return before them.

### What this feature does

It adds a **chain check** to status classification. For a year with a reported value, the service applies **this year's** step to the **prior year's reported** figure (instead of the prior year's expected figure). If the reported value matches that chain result, the return is consistent with the prior return and the difference from the economic balance is inherited from an earlier mistake. Such a year gets a new status `carried` and names the earlier root-cause year. A year whose reported value fails both the economic check and the chain check keeps the status `mismatch`: this year's own return mishandled the carryover.

It also adds a per-year **drift**: the signed difference `reported - expected`, informational only, so the user can see how far each filed return sits from the economic balance.

### What this feature is, and is not

- `Expected_Carryforward` is **unchanged**: same running-balance math, same allowed-loss handling.
- The chain check is a classification aid. The app still never computes the IRC §469 limitation and remains a reconciliation aid, not a tax engine.
- The existing `GET /carryforward` response gains `drift`, `carried_from_year` and the `carried` status value. There are **no new routes, no storage-key changes and no write-route changes**.
- Backward compatibility is a hard constraint: the `ok` and `unreported` classifications and every `expected_carryforward` value are identical to today for any input. The only classification change is that some years that are `mismatch` today become `carried`.

### Grounding (named seams)

- `backend/src/logstead/services/carryforward.py`: the `reconcile()` running-balance loop and status block, `_effective_allowed`, `_schedule_e_net_for`, and the `ReconciledYear` dataclass with `status: Literal["ok", "mismatch", "unreported"]`.
- `backend/src/logstead/router/handler.py`: `_carryforward_reconcile` and `_to_jsonable` (generic dataclass serialization, so new dataclass fields flow to the wire without handler changes).
- `frontend/src/api/carryforward.ts` (`ReconciledYear` type and status union), `frontend/src/pages/CarryforwardPage.tsx` (`STATUS_LABEL`, `StatusCell`, `ReconciliationTable`, `ReconciliationRow`), `frontend/src/lib/money.ts` (`formatMoneyWholeDollars`, `isLoss`).

## Glossary

- **Carryforward_Service**: The backend `CarryforwardService` that derives the reconciliation series and classifies each year.
- **Carryforward_Page**: The frontend page `CarryforwardPage.tsx` that renders the reconciliation table.
- **Carryforward_API**: The frontend transport module `frontend/src/api/carryforward.ts`, including the `ReconciledYear` wire type.
- **Reconciled_Year**: One entry in the ascending reconciliation series, one per Data_Year.
- **Data_Year**: A tax year for which the user has Schedule E data; the series spans exactly the Data_Years (unchanged).
- **Prior_Reconciled_Year**: The Reconciled_Year immediately before a given Reconciled_Year in the ascending series (calendar gaps between Data_Years are preserved as today). The first Reconciled_Year has none.
- **Opening_Balance**: The user's non-negative starting suspended-loss balance carried into the first Reconciled_Year (default `0.00`).
- **Schedule_E_Net**: The portfolio net for a year; negative denotes a loss (unchanged).
- **Loss_Year**: A year whose Schedule_E_Net is strictly less than `0.00`. **Non_Loss_Year**: any other year.
- **Loss_Magnitude**: For a Loss_Year, `-Schedule_E_Net`.
- **Effective_Allowed_Amount**: The allowed magnitude for a year, computed by the existing `_effective_allowed` logic (explicit allowed amount, dynamic Fully_Allowed flag, `0.00` for a Non_Loss_Year).
- **Expected_Carryforward**: The existing economic running balance after applying a year's step to the prior year's **expected** balance (unchanged).
- **Reported_Carryforward**: The carryforward the user recorded for a year, a non-negative two-decimal magnitude, or absent.
- **Year_Step**: The existing balance step for a year. For a Loss_Year, `prior + max(Loss_Magnitude - Effective_Allowed_Amount, 0.00)`. For a Non_Loss_Year, `max(prior - Schedule_E_Net, 0.00)`. Applied to the prior Expected_Carryforward it yields the Expected_Carryforward; applied to the Prior_Reconciled_Year's Reported_Carryforward it yields the Chain_Expected.
- **Chain_Expected**: For a Reconciled_Year whose Prior_Reconciled_Year has a Reported_Carryforward, the Year_Step applied to that prior Reported_Carryforward. It answers: "what should this return say if it correctly carried forward the prior return's figure?"
- **Reconciliation_Status**: One of `unreported`, `ok`, `carried`, `mismatch` (the first three semantics as described below; `carried` is new).
- **Mismatch_Year**: A Reconciled_Year with status `mismatch`; it is the root-cause year of an error.
- **Carried_Year**: A Reconciled_Year with status `carried`.
- **Carried_From_Year**: The `carried_from_year` field, the tax year of the most recent earlier Mismatch_Year for a Carried_Year, otherwise null.
- **Drift**: `Reported_Carryforward - Expected_Carryforward` as a signed two-decimal value; positive means the return carries more than the economic balance, negative means less; null when the year is unreported.
- **Money_String**: A monetary value serialized as a fixed two-decimal string (for example `"-5000.00"`), never a float.
- **Whole_Dollar_Formatter**: The existing `formatMoneyWholeDollars` function in `frontend/src/lib/money.ts`.

## Requirements

### Requirement 1: Chain_Expected derivation

**User Story:** As the single user, I want the app to compute what each return should say if it correctly carried forward the previous return's figure, so that inherited errors can be told apart from new ones.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has a Prior_Reconciled_Year with a Reported_Carryforward, THE Carryforward_Service SHALL compute the Chain_Expected by applying the Year_Step of that year to the Prior_Reconciled_Year's Reported_Carryforward.
2. WHEN the Year_Step is applied to a Loss_Year, THE Carryforward_Service SHALL add `max(Loss_Magnitude - Effective_Allowed_Amount, 0.00)` to the prior value.
3. WHEN the Year_Step is applied to a Non_Loss_Year, THE Carryforward_Service SHALL subtract the Schedule_E_Net from the prior value and floor the result at `0.00`.
4. THE Carryforward_Service SHALL compute the Effective_Allowed_Amount for the Chain_Expected with the same `_effective_allowed` logic used for the Expected_Carryforward, using the year's explicit allowed amount and Fully_Allowed flag.
5. WHEN a Reconciled_Year is the first in the series, THE Carryforward_Service SHALL use the Opening_Balance as the prior value for the Year_Step.
6. THE Carryforward_Service SHALL compute every Chain_Expected as an exact two-decimal `Decimal` value.

### Requirement 2: Status classification with the chain check

**User Story:** As the single user, I want a year that inherited an earlier error to be labelled differently from the year that caused it, so that I know which return to amend.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has no Reported_Carryforward, THE Carryforward_Service SHALL assign the status `unreported`.
2. WHEN a Reconciled_Year has a Reported_Carryforward equal to its Expected_Carryforward to the cent, THE Carryforward_Service SHALL assign the status `ok`.
3. WHEN a Reconciled_Year has a Reported_Carryforward that differs from its Expected_Carryforward, the Prior_Reconciled_Year has a Reported_Carryforward, and the Reported_Carryforward equals the Chain_Expected to the cent, THE Carryforward_Service SHALL assign the status `carried`.
4. WHEN a Reconciled_Year has a Reported_Carryforward that differs from its Expected_Carryforward and rule 2.3 does not apply, THE Carryforward_Service SHALL assign the status `mismatch`.
5. THE Carryforward_Service SHALL evaluate rules 2.1, 2.2, 2.3 and 2.4 in that order and SHALL assign exactly one status to each Reconciled_Year.
6. IF the Prior_Reconciled_Year has no Reported_Carryforward, THEN THE Carryforward_Service SHALL classify the year using rules 2.1, 2.2 and 2.4 only.
7. WHEN a Reconciled_Year is the first in the series, THE Carryforward_Service SHALL classify the year using rules 2.1, 2.2 and 2.4 only.
8. WHEN a later year contains an error independent of an earlier error, THE Carryforward_Service SHALL assign that later year the status `mismatch`.

### Requirement 3: Root-cause year attribution

**User Story:** As the single user, I want each inherited year to name the year that caused it, so that I can go straight to the return that needs amending.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has the status `carried`, THE Carryforward_Service SHALL set `carried_from_year` to the tax year of the most recent earlier Reconciled_Year whose status is `mismatch`.
2. IF a Reconciled_Year has the status `carried` and no earlier Reconciled_Year has the status `mismatch`, THEN THE Carryforward_Service SHALL set `carried_from_year` to null.
3. WHEN a Reconciled_Year has a status other than `carried`, THE Carryforward_Service SHALL set `carried_from_year` to null.
4. THE Carryforward_Service SHALL set `carried_from_year` to an integer tax year strictly less than the year's own `tax_year` or to null.

### Requirement 4: Drift value

**User Story:** As the single user, I want to see how far each filed return is from the economic balance, so that I can judge the size of an error.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has a Reported_Carryforward, THE Carryforward_Service SHALL set `drift` to the Reported_Carryforward minus the Expected_Carryforward as an exact signed two-decimal value.
2. WHEN a Reconciled_Year has no Reported_Carryforward, THE Carryforward_Service SHALL set `drift` to null.
3. THE Carryforward_Service SHALL determine `status` independently of `drift`, so that `drift` alone never changes a status.

### Requirement 5: Backward compatibility

**User Story:** As the single user, I want existing balances and OK/unreported years to stay exactly as they are, so that this change only improves how errors are labelled.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL produce the same `expected_carryforward` value for every Reconciled_Year as before this feature, for any Opening_Balance, nets, allowed data and reported data.
2. THE Carryforward_Service SHALL assign `unreported` and `ok` to exactly the same Reconciled_Years as before this feature.
3. THE Carryforward_Service SHALL assign `mismatch` or `carried` to exactly the Reconciled_Years that were `mismatch` before this feature.
4. WHEN no Reconciled_Year has a Prior_Reconciled_Year with a Reported_Carryforward, THE Carryforward_Service SHALL produce the same statuses as before this feature.

### Requirement 6: Wire contract

**User Story:** As a frontend developer, I want the existing reconciliation response to carry the new fields, so that the page can render them without a new route.

#### Acceptance Criteria

1. WHEN a client requests `GET /carryforward`, THE Carryforward_Service router SHALL include `drift` and `carried_from_year` for every year in the response.
2. THE Carryforward_Service router SHALL serialize a non-null `drift` as a signed two-decimal Money_String and a null `drift` as JSON null.
3. THE Carryforward_Service router SHALL serialize `carried_from_year` as a JSON integer or JSON null.
4. THE Carryforward_Service router SHALL serialize `status` as one of `ok`, `mismatch`, `carried` or `unreported`.
5. THE Carryforward_Service router SHALL keep the existing response fields and their values unchanged.
6. THE Carryforward_API SHALL declare `drift: string | null`, `carried_from_year: number | null` and the status union `"ok" | "mismatch" | "carried" | "unreported"` on the `ReconciledYear` type.

### Requirement 7: Drift column

**User Story:** As the single user, I want a Drift column in the reconciliation table, so that I can read the size and direction of each difference at a glance.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL render a column headed "Drift" in the reconciliation table.
2. WHEN a year has a non-null `drift` that is greater than zero, THE Carryforward_Page SHALL render a leading "+" sign, the Whole_Dollar_Formatter output, and the text "over".
3. WHEN a year has a non-null `drift` that is less than zero, THE Carryforward_Page SHALL render the Whole_Dollar_Formatter output with its minus sign and the text "under".
4. WHEN a year has a non-null `drift` equal to `0.00`, THE Carryforward_Page SHALL render the Whole_Dollar_Formatter output with no over or under text.
5. WHEN a year has a null `drift`, THE Carryforward_Page SHALL render an em dash in the Drift cell.
6. THE Carryforward_Page SHALL convey the direction of drift through text so that meaning does not rest on colour alone.
7. THE Carryforward_Page SHALL render the same number of cells in every table row, including rows with a null `drift`.

### Requirement 8: Status label and highlighting

**User Story:** As the single user, I want carried years labelled with their root cause and only the root-cause year highlighted, so that the year to amend is the one that stands out.

#### Acceptance Criteria

1. WHEN a year has the status `carried` and a non-null `carried_from_year`, THE Carryforward_Page SHALL render the status label "Carried from {carried_from_year}" with the year substituted.
2. WHEN a year has the status `carried` and a null `carried_from_year`, THE Carryforward_Page SHALL render the status label "Carried from earlier year".
3. WHEN a year has the status `mismatch`, THE Carryforward_Page SHALL render the existing "Needs review" label and the existing danger highlight on the row and status.
4. WHEN a year has the status `carried`, THE Carryforward_Page SHALL render the row and the status without the danger highlight.
5. THE Carryforward_Page SHALL render the existing labels "OK" for `ok` and "Not reported" for `unreported`.

### Requirement 9: Existing page behaviour preserved

**User Story:** As the single user, I want the controls I already use to keep working, so that this change does not disrupt my workflow.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL keep the reported editor, the allowed-loss control, the opening balance control, the disclaimer and the empty state with their current behaviour.
2. WHEN the user saves or clears a reported value, an allowed-loss value, a Fully_Allowed toggle or the opening balance, THE Carryforward_Page SHALL reload the series so that status, drift and root-cause labels update together.

### Requirement 10: Numeric integrity and scope limits

**User Story:** As the single user, I want exact money arithmetic and unchanged scope, so that the reconciliation stays trustworthy.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL compute Chain_Expected and drift using exact two-decimal `Decimal` arithmetic with no floating-point values.
2. THE Carryforward_Service SHALL derive status, drift and `carried_from_year` without applying the IRC §469 limitation.
3. THE Carryforward_Service SHALL leave the storage keys, stored attributes and write routes unchanged.
4. THE Carryforward_Page SHALL derive the drift sign cue from the Money_String text and SHALL NOT use floating-point arithmetic on drift amounts.

### Requirement 11: Existing test and build compatibility

**User Story:** As a maintainer, I want the existing suites to keep passing, so that the change is safe to ship.

#### Acceptance Criteria

1. THE frontend fixtures that build `ReconciledYear` objects in `frontend/src/api/carryforward.test.ts` and `frontend/src/pages/CarryforwardPage.test.tsx` SHALL include the `drift` and `carried_from_year` fields so that `npm run build` (`tsc -b`) succeeds.
2. THE backend carryforward tests under `tests/services/test_carryforward_*.py` and `tests/router/test_carryforward_*.py` SHALL pass after the change.
3. WHEN an existing backend test asserts the pre-feature status rule or the three-value status set, THE test SHALL be updated to the four-value rule defined in Requirement 2 while keeping its original intent.
