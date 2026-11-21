# Requirements Document

## Introduction

This feature extends the existing **passive loss carryforward reconciliation** (spec at `.kiro/specs/passive-loss-carryforward/`; `Carryforward_Service` at `backend/src/logstead/services/carryforward.py`; `Carryforward_Page` at `frontend/src/pages/CarryforwardPage.tsx`) so that the portion of a year's rental loss that was actually **allowed** (deducted) on the filed return no longer inflates the running suspended-loss balance.

The existing reconciliation derives each year's Schedule E net, rolls a running non-negative `Suspended_Loss_Balance` forward from an optional opening balance to produce an `Expected_Carryforward`, and compares that against a user-entered reported carryforward, flagging each year `ok` / `mismatch` / `unreported`. It is explicitly a **reconciliation aid, not a tax engine**: it computes the pure economic running suspended-loss balance and DELIBERATELY does NOT apply the IRC §469 limitation — the $25,000 special allowance, its MAGI phase-out, or real-estate-professional status — because the app collects none of the inputs those rules require.

### The problem this solves

Today the engine treats **every** loss year as fully suspended. But in years where a rental loss was actually **allowed** under the §25,000 special allowance (rather than suspended), the true end-of-year carryforward is lower than the app's `Expected_Carryforward` — producing a systematic, correct-but-permanent false `mismatch`.

Concrete example carried into these requirements as an acceptance scenario: the **2010** tax year had a Schedule E net of **-$758.00**; the taxpayer's MAGI (~$115k) left enough allowance that Form 8582 Part II line 10 (allowed special allowance) equalled **$758.00** — the ENTIRE loss was allowed, so the true end-of-year carryforward is **$0.00**. The app's `Expected_Carryforward` instead shows `$758.00` because it suspends the whole loss. The user must currently report `0.00` and live with a permanent `mismatch`.

### What this feature does

It adds a **per-year, optional `Allowed_Loss` amount** — the allowed portion of that year's loss, transcribed by the user from Form 8582 Part II line 10 — to the reconciliation. In the running-balance loop, a loss year now carries only the **unallowed** portion of its loss onto the balance; the allowed portion is excluded. Because the balance rolls forward, reducing one year's contribution automatically recalculates the `Expected_Carryforward` for every subsequent year, with no separate recalculation mechanism. With a correct `Allowed_Loss`, `Expected_Carryforward` becomes the true carryforward, so a correct reported value reconciles to `ok` (the 2010 case: allowed `758.00` → expected `0.00` → reported `0.00` → `ok`).

It also adds a per-year **`Fully_Allowed`** convenience toggle meaning "the whole loss for this year was allowed", tracked dynamically: when on, the effective allowed amount always equals that year's CURRENT Schedule E loss magnitude, even if the year's net later changes (e.g. from depreciation or transaction edits). The explicit `Allowed_Loss` amount is for partial-allowance years.

### What this feature is, and is not

This feature **preserves the "reconciliation aid, not a tax engine" boundary**. The app NEVER computes the §469 allowance: there is no MAGI collection, no active-participation determination, and no phase-out math. It only records the user's transcribed allowed amount from their already-filed Form 8582 and subtracts it from the year's suspended loss. The allowed amount is an input the user supplies, never a figure the app derives.

Scope decisions already confirmed with the user and carried into these requirements:

- The `Allowed_Loss` amount and `Fully_Allowed` toggle are **per-year** and **optional**. Default / absent means "none allowed", which reproduces today's behavior exactly.
- Persistence reuses the **existing** per-year reported-entry item (the `PLCF#<year>` item that today stores the reported carryforward `amount` plus `taxYear`) as an additional attribute. No new keys, items, or routes are introduced beyond what the existing reported-entry endpoints need.
- A per-year item may now exist to carry an allowed amount or a fully-allowed flag **independently of** a reported value, and vice versa; the item carries each of its figures as optional.
- `Fully_Allowed` is a stored flag/sentinel, NOT a snapshot of the loss into the amount field, so it tracks the current loss magnitude dynamically.
- The allowed control appears in the UI only on rows that are a loss year; gain and break-even rows have no loss to allow.
- All money stays an exact two-decimal `Decimal` in Python and a fixed two-decimal string over the wire; no float math is introduced.

Explicitly **out of scope** (unchanged from the base feature, and reaffirmed here): computing the §469 limitation or any Form 8582 line; collecting MAGI, participation status, or non-rental passive income; modeling property dispositions; per-property carryforward balances; auto-reading the allowed figure from PDFs; and amending or generating any tax form.

### Grounding (named seams, for the design phase)

These requirements stay implementation-agnostic but reference the seams the design phase will work within:

- `backend/src/logstead/services/carryforward.py`: the running-balance loop (the loss branch `balance = balance + (-net)`), the `ReconciledYear` / `ReconciliationSummary` dataclasses (`tax_year`, `schedule_e_net`, `expected_carryforward`, `reported_carryforward`, `status`), `set_reported` / `clear_reported` / `set_opening_balance`, `_validate_amount`, the per-year item `{PK: user_pk, SK: plcf_year_sk(year), amount, taxYear}`, `keys.plcf_year_sk` / `keys.plcf_opening_sk`, and derivation of `schedule_e_net` via `ReportingService.report_for` summed across properties.
- `frontend/src/pages/CarryforwardPage.tsx` (`ReconciliationRow`, `ScheduleENetCell`, `ReportedEditor`, `OpeningBalanceControl`) and `frontend/src/api/carryforward.ts`.
- Money: `backend/src/logstead/util/money.py` (`to_money` / `money_to_str`); `frontend/src/lib/money.ts`.

## Glossary

- **Carryforward_Service**: The existing backend service (`CarryforwardService`) that derives the `Expected_Carryforward` series and reconciles it against reported values. This feature extends its running-balance loop, its per-year persistence, and its validation.
- **Carryforward_Page**: The existing frontend page (`CarryforwardPage.tsx`) that renders the reconciliation table. This feature adds the `Allowed_Loss` control per loss row.
- **Carryforward_API**: The existing frontend transport wrapper (`frontend/src/api/carryforward.ts`) that calls the reconciliation backend routes.
- **Reporting_Service**: The existing backend `ReportingService`, whose `report_for(property_id, year)` yields a property's Schedule E report totals (income, expenses, net) for a tax year.
- **Tax_Year**: A four-digit calendar year for which Schedule E data may exist.
- **Data_Year**: A Tax_Year for which the authenticated user has any Schedule E data; the reconciliation spans exactly the set of Data_Years (optionally preceded by an opening-balance year).
- **Schedule_E_Net**: For a Tax_Year, the portfolio sum, across the user's properties, of each property's net from its Schedule E report; negative denotes a net loss. Derived, never stored.
- **Loss_Year**: A Tax_Year whose `Schedule_E_Net` is strictly less than `0.00` (a net rental loss). A Tax_Year whose net is `0.00` or positive is NOT a Loss_Year (it is a gain or break-even year, collectively a **Non_Loss_Year**).
- **Loss_Magnitude**: For a Loss_Year, the non-negative magnitude of that year's `Schedule_E_Net` (i.e. `-Schedule_E_Net`). For a Non_Loss_Year, `0.00`.
- **Allowed_Loss**: An optional, user-entered, non-negative two-decimal money magnitude for a Tax_Year, transcribed from Form 8582 Part II line 10, representing the portion of that year's rental loss that was ALLOWED (deducted) on the filed return rather than suspended. Absent / unset is treated as `0.00`. Never computed by the app.
- **Fully_Allowed**: An optional per-year boolean flag meaning "the entire loss for this Tax_Year was allowed". When set, the year's effective allowed amount dynamically equals the year's current `Loss_Magnitude`, regardless of any explicit `Allowed_Loss` value. Stored as a flag, not as a snapshot of the loss.
- **Effective_Allowed_Amount**: The allowed magnitude actually applied to a Tax_Year in the running-balance loop: the year's current `Loss_Magnitude` when `Fully_Allowed` is set; otherwise the year's `Allowed_Loss` (defaulting to `0.00` when absent); and `0.00` for any Non_Loss_Year.
- **Suspended_Loss**: For a Loss_Year, the portion of that year's loss that is NOT allowed and therefore carries onto the balance: `max(Loss_Magnitude - Effective_Allowed_Amount, 0.00)`.
- **Suspended_Loss_Balance**: The running, non-negative magnitude of cumulative passive loss carried into a Tax_Year that has not yet been absorbed.
- **Expected_Carryforward**: The `Suspended_Loss_Balance` after applying a Tax_Year's net (and its `Effective_Allowed_Amount`) to the balance carried in from the prior year — a non-negative magnitude. Derived from `Schedule_E_Net`, the opening balance, and the per-year allowed amounts alone; it does NOT apply the §469 limitation.
- **Reported_Carryforward**: The suspended-loss carryforward the user actually reported on their filed return for a Tax_Year, entered by the user; a non-negative two-decimal magnitude, or absent. (Unchanged from the base feature.)
- **Reconciliation_Status**: A per-year classification: `ok` when `Reported_Carryforward` matches `Expected_Carryforward` to the cent; `mismatch` when they differ; `unreported` when no `Reported_Carryforward` is entered. (Unchanged from the base feature.)
- **Per_Year_Item**: The existing single-table DynamoDB item keyed `{PK: USER#<userId>, SK: PLCF#<year>}` that today stores the `Reported_Carryforward` (`amount`) and `taxYear`. This feature adds optional attributes to it for the `Allowed_Loss` amount and the `Fully_Allowed` flag.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string (e.g. `"758.00"`, `"0.00"`), never a float and never a DynamoDB `Number`.

## Requirements

### Requirement 1: Record an optional per-year allowed-loss amount

**User Story:** As the single user, I want to record the portion of a year's rental loss that was actually allowed on my filed return, so that the expected carryforward reflects my real suspended loss instead of treating the whole loss as suspended.

#### Acceptance Criteria

1. WHEN the user submits an `Allowed_Loss` amount for a Tax_Year, THE Carryforward_Service SHALL persist that amount as a non-negative two-decimal magnitude associated with that Tax_Year for the authenticated user.
2. THE Carryforward_Service SHALL persist the `Allowed_Loss` amount as a distinct attribute on the Per_Year_Item, separate from the attribute that stores the `Reported_Carryforward`.
3. WHEN the user submits an `Allowed_Loss` amount for a Tax_Year that already has one, THE Carryforward_Service SHALL replace the prior `Allowed_Loss` amount with the submitted amount.
4. WHEN the user clears the `Allowed_Loss` amount for a Tax_Year, THE Carryforward_Service SHALL remove the stored `Allowed_Loss` amount so that the year is treated as having `0.00` allowed.
5. WHERE no `Allowed_Loss` amount is stored for a Tax_Year, THE Carryforward_Service SHALL treat that year's `Allowed_Loss` as `0.00`.
6. THE Carryforward_Service SHALL serialize every stored `Allowed_Loss` amount over the wire as a Money_String.

### Requirement 2: Persist allowed-loss data on the existing per-year item, independently of the reported value

**User Story:** As the single user, I want to set an allowed amount for a year whether or not I have entered a reported carryforward for that year, so that recording one does not force me to record the other.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL store the `Allowed_Loss` amount and the `Fully_Allowed` flag on the existing Per_Year_Item (keyed `PLCF#<year>` under the authenticated user) and SHALL NOT introduce any new item key, item type, or backend route beyond those the existing per-year reported-entry endpoints require.
2. WHEN the user sets an `Allowed_Loss` amount or `Fully_Allowed` flag for a Tax_Year that has no `Reported_Carryforward`, THE Carryforward_Service SHALL persist the allowed data and SHALL leave the `Reported_Carryforward` absent for that year.
3. WHEN the user sets a `Reported_Carryforward` for a Tax_Year that has an `Allowed_Loss` amount or `Fully_Allowed` flag, THE Carryforward_Service SHALL persist the reported value and SHALL preserve the existing allowed data for that year.
4. WHEN the user clears the `Reported_Carryforward` for a Tax_Year that still has an `Allowed_Loss` amount or `Fully_Allowed` flag, THE Carryforward_Service SHALL preserve the allowed data for that year.
5. WHERE the Per_Year_Item carries neither a `Reported_Carryforward`, an `Allowed_Loss` amount, nor a `Fully_Allowed` flag, THE Carryforward_Service SHALL treat the item as carrying no per-year state for that year.
6. THE Carryforward_Service SHALL scope every read and write of per-year allowed data to the authenticated user's `USER#<userId>` partition, so that one user can never read or modify another user's allowed data.

### Requirement 3: Exclude the allowed portion of a loss from the running balance

**User Story:** As the single user, I want only the unallowed portion of each year's loss to carry forward, so that the expected carryforward equals my true remaining suspended loss.

#### Acceptance Criteria

1. WHERE a Tax_Year is a Loss_Year, THE Carryforward_Service SHALL compute that year's `Suspended_Loss` as `max(Loss_Magnitude - Effective_Allowed_Amount, 0.00)` and SHALL increase the `Suspended_Loss_Balance` carried into that year by that `Suspended_Loss` to produce the year's `Expected_Carryforward`.
2. WHERE a Tax_Year is a Non_Loss_Year, THE Carryforward_Service SHALL reduce the `Suspended_Loss_Balance` carried into that year by the magnitude of that year's gain, floored at `0.00`, exactly as today and without applying any allowed amount.
3. THE Carryforward_Service SHALL carry each year's `Expected_Carryforward` forward as the balance brought into the next reconciled year, so that reducing one year's `Suspended_Loss` automatically lowers the `Expected_Carryforward` of every subsequent reconciled year with no separate recalculation step.
4. THE Carryforward_Service SHALL never allow the `Suspended_Loss_Balance` or any `Expected_Carryforward` to become negative.
5. THE Carryforward_Service SHALL compute every `Suspended_Loss` and `Expected_Carryforward` using exact two-decimal `Decimal` arithmetic with no floating-point drift, and SHALL represent each `Expected_Carryforward` as a non-negative Money_String.
6. THE Carryforward_Service SHALL derive the `Effective_Allowed_Amount` and `Suspended_Loss` from the user-entered allowed data and the derived `Schedule_E_Net` alone, and SHALL NOT compute the IRC §469 limitation (the $25,000 allowance, MAGI phase-out, or real-estate-professional rules).
7. WHEN a loss year is fully allowed to the cent, THE Carryforward_Service SHALL contribute `0.00` from that year to the `Suspended_Loss_Balance`.
8. THE Carryforward_Service SHALL classify every reconciled Tax_Year as exactly one of a Loss_Year (`Schedule_E_Net` strictly less than `0.00`) or a Non_Loss_Year (`Schedule_E_Net` equal to or greater than `0.00`), so that a break-even zero-net year is handled as a Non_Loss_Year and no reconciled year is left unclassified.

### Requirement 4: Fully-allowed toggle tracks the current loss magnitude dynamically

**User Story:** As the single user, I want a "fully allowed" toggle for a year, so that I can mark the whole loss as allowed without re-typing the amount, and have it stay correct if the year's net later changes.

#### Acceptance Criteria

1. WHEN the user turns on `Fully_Allowed` for a Loss_Year, THE Carryforward_Service SHALL persist the `Fully_Allowed` flag on that year's Per_Year_Item as a stored flag, and SHALL NOT snapshot the current `Loss_Magnitude` into the `Allowed_Loss` amount attribute.
2. WHILE `Fully_Allowed` is on for a Tax_Year, THE Carryforward_Service SHALL set that year's `Effective_Allowed_Amount` equal to the year's current `Loss_Magnitude`, so that the entire current loss is excluded from the `Suspended_Loss_Balance`.
3. WHILE `Fully_Allowed` is on for a Tax_Year, THE Carryforward_Service SHALL use the current `Loss_Magnitude` as the `Effective_Allowed_Amount` even when that `Loss_Magnitude` has changed since the flag was set (for example after a depreciation or transaction edit), without requiring the user to re-set the flag.
4. WHILE `Fully_Allowed` is on for a Tax_Year, THE Carryforward_Service SHALL treat that year's `Effective_Allowed_Amount` as the full current `Loss_Magnitude` regardless of any stored `Allowed_Loss` amount, so that the `Fully_Allowed` flag takes precedence over the explicit amount while it is on.
5. WHEN the user turns off `Fully_Allowed` for a Tax_Year, THE Carryforward_Service SHALL revert that year's `Effective_Allowed_Amount` to the year's stored `Allowed_Loss` amount, defaulting to `0.00` when none is stored.
6. WHERE no `Fully_Allowed` flag is stored for a Tax_Year, THE Carryforward_Service SHALL treat the year as not fully allowed.

### Requirement 5: Validate the allowed-loss amount against the year's loss

**User Story:** As the single user, I want the app to reject an allowed amount that cannot be right for a year, so that I do not record more allowed loss than the year actually had.

#### Acceptance Criteria

1. IF a submitted `Allowed_Loss` amount is negative or not a valid two-decimal money magnitude, THEN THE Carryforward_Service SHALL reject it with a validation error identifying the offending field and SHALL NOT persist any change.
2. WHEN validating a submitted `Allowed_Loss` amount for a Tax_Year, THE Carryforward_Service SHALL derive that year's `Schedule_E_Net` so that the submitted amount can be checked against the year's `Loss_Magnitude`.
3. IF a submitted `Allowed_Loss` amount exceeds the Tax_Year's `Loss_Magnitude`, THEN THE Carryforward_Service SHALL reject it with a validation error identifying the offending field and SHALL NOT persist any change.
4. IF the user submits an `Allowed_Loss` amount greater than `0.00`, or turns on `Fully_Allowed`, for a Non_Loss_Year, THEN THE Carryforward_Service SHALL reject the submission with a validation error identifying the offending field and SHALL NOT persist any change.
5. WHERE a submitted `Allowed_Loss` amount is between `0.00` and the Tax_Year's `Loss_Magnitude` inclusive, THE Carryforward_Service SHALL accept and persist it.
6. THE Carryforward_Service SHALL report every allowed-data validation failure using the existing `Result.failure("validation", message, field=...)` pattern, consistent with the existing reported-carryforward and opening-balance validation.

### Requirement 6: Present the allowed-loss control only on loss rows

**User Story:** As the single user, I want to enter the allowed amount directly in the reconciliation table, only where a year actually had a loss, so that the control appears where it makes sense and the expected and status update to reflect it.

#### Acceptance Criteria

1. WHERE a reconciled Tax_Year is a Loss_Year, THE Carryforward_Page SHALL present, on that year's row, a control to enter or edit the `Allowed_Loss` amount and a control to turn `Fully_Allowed` on or off.
2. WHERE a reconciled Tax_Year is a Non_Loss_Year, THE Carryforward_Page SHALL hide or disable the `Allowed_Loss` and `Fully_Allowed` controls for that row, so that no allowed input is offered where there is no loss to allow.
3. WHILE `Fully_Allowed` is on for a row, THE Carryforward_Page SHALL indicate that the full loss is allowed for that year and SHALL make the explicit `Allowed_Loss` amount input moot (hidden, disabled, or otherwise not applied) for that row.
4. WHEN the user saves or clears an `Allowed_Loss` amount or toggles `Fully_Allowed`, THE Carryforward_Page SHALL reflect the updated `Expected_Carryforward` and `Reconciliation_Status` for that year and every subsequent reconciled year without requiring a full page reload.
5. WHEN a submitted `Allowed_Loss` amount or `Fully_Allowed` toggle is rejected by validation (Requirement 5), THE Carryforward_Page SHALL surface the validation error next to the offending control and SHALL NOT alter the displayed reconciliation.
6. THE Carryforward_Page SHALL continue to display each reconciled year's `Schedule_E_Net`, `Expected_Carryforward`, `Reported_Carryforward`, and `Reconciliation_Status`, and SHALL continue to provide the existing reported-carryforward control and `ok` / `mismatch` / `unreported` behavior.
7. THE Carryforward_Page SHALL render every monetary value from its Money_String in the app's existing display money format, without re-deriving it from a float.

### Requirement 7: Backward compatibility with the existing reconciliation

**User Story:** As the single user, I want years where I set no allowed amount to behave exactly as they do today, so that adding this feature changes nothing for the years I do not touch.

#### Acceptance Criteria

1. WHERE a Tax_Year has no stored `Allowed_Loss` amount and does not have `Fully_Allowed` on, THE Carryforward_Service SHALL produce the identical `Expected_Carryforward` and `Reconciliation_Status` for that year that the existing feature produces today.
2. THE Carryforward_Service SHALL treat an absent `Allowed_Loss` attribute as `0.00` allowed and an absent `Fully_Allowed` flag as not fully allowed, so that existing Per_Year_Items written before this feature reconcile exactly as before.
3. WHERE no Tax_Year has any `Allowed_Loss` amount or `Fully_Allowed` flag set, THE Carryforward_Service SHALL produce the byte-for-byte identical `Expected_Carryforward` series it produces today for the same underlying Schedule E data and opening balance.
4. THE Carryforward_Service SHALL preserve the existing `ReconciledYear` / `ReconciliationSummary` fields (`tax_year`, `schedule_e_net`, `expected_carryforward`, `reported_carryforward`, `status`) and SHALL continue to classify each year `ok` / `mismatch` / `unreported` by the existing rules.

### Requirement 8: Acceptance scenario — a fully allowed loss reconciles to ok

**User Story:** As the single user, I want a year whose entire loss was allowed to reconcile cleanly, so that I no longer carry a permanent false mismatch for it.

#### Acceptance Criteria

1. WHERE a Tax_Year's `Schedule_E_Net` is `-758.00` and the user records an `Allowed_Loss` amount of `758.00` for that year (and the balance carried into the year is `0.00`), THE Carryforward_Service SHALL produce an `Expected_Carryforward` of `0.00` for that year.
2. WHEN the user then records a `Reported_Carryforward` of `0.00` for that same year, THE Carryforward_Service SHALL assign that year the `ok` Reconciliation_Status.
3. WHERE a Tax_Year's `Schedule_E_Net` is `-758.00` and the user turns on `Fully_Allowed` for that year (and the balance carried into the year is `0.00`), THE Carryforward_Service SHALL produce an `Expected_Carryforward` of `0.00` for that year, matching the explicit `758.00` allowed case.

### Requirement 9: Non-functional guarantees

**User Story:** As the single user, I want this change to keep the app correct, precise, and within its "not a tax engine" boundary, so that I can trust the existing behavior continues to hold.

#### Acceptance Criteria

1. THE Carryforward_Service and Carryforward_Page SHALL keep the existing backend and frontend test suites green.
2. THE Carryforward_Service SHALL maintain the running-balance invariant that the `Suspended_Loss_Balance` and every `Expected_Carryforward` are non-negative magnitudes for all inputs.
3. THE Carryforward_Service SHALL maintain the invariant that a Tax_Year with no `Allowed_Loss` amount and `Fully_Allowed` off contributes to the `Suspended_Loss_Balance` identically to the existing feature.
4. THE Carryforward_Service and Carryforward_Page SHALL represent and transmit every monetary value as an exact two-decimal `Decimal` in Python and as a fixed two-decimal Money_String over the wire, introducing no floating-point arithmetic.
5. THE Carryforward_Service SHALL NOT compute the IRC §469 passive-loss limitation and SHALL only consume the user-entered allowed amount, preserving the existing "reconciliation aid, not a tax engine" boundary and its disclaimer.
6. THE Carryforward_Service SHALL confine every read and write for this feature to the authenticated user's `USER#<userId>` partition, exactly like the existing reported entries and opening balance.
