# Requirements Document

## Introduction

This feature adds a **passive loss carryforward reconciliation** view to the Logstead single-user Schedule E rental tax app (React 19 + Vite + TypeScript SPA, Monarch-style theming; Python 3.12 Lambda over single-table DynamoDB, S3, Cognito JWT auth). Rental real estate is a passive activity under IRC §469: when a tax year's deductible rental expenses exceed its income, the resulting loss is generally suspended and carried forward to later years until absorbed by passive income or released on a fully taxable disposition. The user has, in prior years, forgotten to carry a suspended loss forward onto the next return, and needs a way to spot those years to prepare an amended return.

The feature presents a **year-by-year reconciliation table/timeline** at the portfolio level. For every year that has Schedule E data, it shows:

- the **Schedule E net** for that year (derived from existing data — the same figure the reports and trends already compute);
- a running **Expected_Carryforward** — what the suspended-loss balance *should* be if losses rolled forward correctly year to year, computed from the derived nets plus an optional user-set opening balance;
- a **Reported_Carryforward** the user enters per year, read off their actually-filed return;
- a **Status** that highlights years where Reported_Carryforward diverges from Expected_Carryforward — the signature of a forgotten carryover.

### What this feature is, and is not

This is a **reconciliation aid**, not a tax engine. The Expected_Carryforward is the *economic* carryforward derived from Schedule E net alone. It deliberately does **not** apply the IRC §469 passive-loss limitation — the $25,000 special allowance for active participation, its $100k–$150k MAGI phase-out, or real-estate-professional status — because the app collects none of the inputs those rules require (MAGI, participation facts, passive income from non-rental activities, or disposition events). The feature's job is to surface *where* a carryforward looks wrong so the user and their tax professional can investigate; it is not a substitute for Form 8582 and must not present itself as authoritative tax advice.

Scope decisions already confirmed with the user and carried into these requirements:

- **Portfolio-level** aggregation: one running suspended-loss balance across all properties per year (matching how §469 aggregates rental real estate), not a separate balance per property.
- **Reported_Carryforward is user-entered** per year — the reliable comparison point. Inferring it automatically from uploaded Schedule E PDFs is explicitly out of scope for this first cut.
- **Profitable years absorb prior suspended losses**: a year whose Schedule E net is a gain reduces the running Expected_Carryforward, floored at zero; a loss year increases it.

Explicitly **out of scope**: computing the §469 limitation or any Form 8582 line; collecting MAGI, participation status, or non-rental passive income; modeling property dispositions; per-property carryforward balances; auto-reading the reported figure from PDFs; and amending or generating any tax form. These may be revisited later but are not part of this feature.

Money is an exact two-decimal `Decimal` in backend code and is serialized as fixed two-decimal **strings** over the wire (never floats, never a DynamoDB `Number`). A negative net denotes a loss; the suspended-loss balance is carried as a non-negative magnitude with an explicit sign convention defined in the design.

This feature reuses the existing per-(property, year) Schedule E derivations (`ReportingService.report_for`) looped across the user's Data_Years — the same path the dashboard trends already use — so the derived nets always reconcile with the per-property Schedule E reports. It introduces exactly one small piece of durable cross-year state: the user-entered Reported_Carryforward (and optional opening balance) per Tax_Year.

## Glossary

- **Carryforward_Page**: The new page this feature adds that renders the portfolio-level passive-loss carryforward reconciliation table/timeline for the authenticated user.
- **Carryforward_API**: The new frontend transport wrapper that calls this feature's backend routes (read the reconciliation series; save a Reported_Carryforward entry).
- **Carryforward_Service**: The new backend service that derives the Expected_Carryforward series from Schedule E nets and merges in the user-entered Reported_Carryforward entries to produce the Reconciliation_Series.
- **Reporting_Service**: The existing backend `ReportingService`, whose `report_for(property_id, year)` yields a property's Schedule E report totals (income, expenses, net) for a tax year.
- **Property_Service**: The existing backend `PropertyService`, whose `list()` returns the authenticated user's properties.
- **Tax_Year**: A calendar year for which Schedule E data may exist. Rental data is tracked as one entry per Schedule E line per Tax_Year.
- **Data_Year**: A Tax_Year for which the authenticated user has any Schedule E data. The reconciliation spans exactly the set of Data_Years (optionally preceded by an Opening_Balance_Year; see Requirement 7).
- **Schedule_E_Net**: For a Tax_Year, the portfolio sum of every property's net (`total_income - total_expenses`) from that property's Schedule E report; negative denotes a passive loss for that year. Derived, never stored.
- **Suspended_Loss_Balance**: The running, non-negative magnitude of cumulative passive loss carried into a Tax_Year that has not yet been absorbed. Carried as a non-negative `Decimal` (0.00 means no suspended loss).
- **Expected_Carryforward**: The Suspended_Loss_Balance after applying a Tax_Year's Schedule_E_Net to the balance carried in from the prior year — a loss year increases it, a gain year reduces it (floored at zero). Derived from Schedule_E_Net and the Opening_Balance alone; it does NOT apply the §469 limitation.
- **Reported_Carryforward**: The suspended-loss carryforward the user actually reported on their filed return for a Tax_Year, entered by the user. A non-negative Money_String magnitude, or absent when the user has not entered it for that year.
- **Opening_Balance**: An optional user-set Suspended_Loss_Balance carried into the earliest reconciled year, representing suspended losses that accrued before the app's data begins. Defaults to 0.00 when unset.
- **Reconciliation_Series**: The year-indexed result the Carryforward_Service produces: for each reconciled Tax_Year, the Schedule_E_Net, the Expected_Carryforward, the Reported_Carryforward (when entered), and a Reconciliation_Status.
- **Reconciliation_Status**: A per-year classification: `ok` when the Reported_Carryforward matches the Expected_Carryforward to the cent; `mismatch` when they differ; `unreported` when no Reported_Carryforward has been entered for that year.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string (e.g. `"1500.00"`, `"-125.00"`), never a float and never a DynamoDB `Number`.
- **Disclaimer_Notice**: The persistent, visible notice on the Carryforward_Page stating that the Expected_Carryforward is an economic reconciliation aid derived from Schedule E net only, does not apply the §469 limitation (Form 8582, the $25,000 allowance, MAGI phase-outs, real-estate-professional status), and is not tax advice.
- **Empty_State**: The guidance shown on the Carryforward_Page when the authenticated user has no Data_Years (and no Opening_Balance), so there is nothing to reconcile yet.

## Requirements

### Requirement 1: Derive the per-year Schedule E net series

**User Story:** As the single user, I want each year's rental net computed from my existing data, so that the carryforward reconciliation is grounded in the same numbers as my Schedule E reports.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL derive the Schedule_E_Net for each Data_Year as the portfolio sum, across the authenticated user's properties, of each property's net from `Reporting_Service.report_for(property_id, year)` for that year.
2. THE Carryforward_Service SHALL derive the Schedule_E_Net from persisted Schedule E data alone, producing the same portfolio net as the existing reports and dashboard trends for the same Tax_Year, with no separately stored or cached net.
3. THE Carryforward_Service SHALL scope every derivation to the authenticated user's own properties and SHALL NOT include any other user's data.
4. THE Carryforward_Service SHALL represent each Schedule_E_Net as a Money_String, negative when the year is a net loss.

### Requirement 2: Compute the expected carryforward as a running balance

**User Story:** As the single user, I want the app to compute what my suspended-loss carryforward should be each year, so that I have a correct baseline to compare my filed returns against.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL compute the Expected_Carryforward for the reconciled years as a running Suspended_Loss_Balance, processing Data_Years in ascending chronological order.
2. THE Carryforward_Service SHALL carry the Opening_Balance (Requirement 7), defaulting to 0.00, into the earliest reconciled year as the balance brought forward.
3. WHERE a Tax_Year's Schedule_E_Net is a loss (less than zero), THE Carryforward_Service SHALL increase the Suspended_Loss_Balance carried into that year by the magnitude of that loss to produce that year's Expected_Carryforward.
4. WHERE a Tax_Year's Schedule_E_Net is a gain (greater than or equal to zero), THE Carryforward_Service SHALL reduce the Suspended_Loss_Balance carried into that year by the magnitude of that gain to produce that year's Expected_Carryforward, flooring the result at 0.00 and never producing a negative Suspended_Loss_Balance.
5. THE Carryforward_Service SHALL carry each year's Expected_Carryforward forward as the balance brought into the next reconciled year.
6. THE Carryforward_Service SHALL compute every Expected_Carryforward using exact two-decimal `Decimal` arithmetic with no floating-point drift, and SHALL represent each as a non-negative Money_String.
7. THE Carryforward_Service SHALL compute the Expected_Carryforward from Schedule_E_Net and the Opening_Balance alone and SHALL NOT apply the IRC §469 passive-loss limitation (the $25,000 allowance, MAGI phase-out, or real-estate-professional rules) in the derivation.

### Requirement 3: Record the reported carryforward per year

**User Story:** As the single user, I want to enter what I actually reported as my carryforward each year, so that the app can compare it against the expected value.

#### Acceptance Criteria

1. WHEN the user submits a Reported_Carryforward for a Tax_Year, THE Carryforward_Service SHALL persist it as a non-negative two-decimal amount associated with that Tax_Year for the authenticated user.
2. WHEN the user submits a Reported_Carryforward for a Tax_Year that already has one, THE Carryforward_Service SHALL replace the prior value with the submitted value.
3. IF a submitted Reported_Carryforward is negative or not a valid two-decimal money amount, THEN THE Carryforward_Service SHALL reject it with a validation error identifying the offending field and SHALL NOT persist any change.
4. WHEN the user clears a Reported_Carryforward for a Tax_Year, THE Carryforward_Service SHALL remove the stored entry so that year returns to the `unreported` status.
5. THE Carryforward_Service SHALL scope every Reported_Carryforward read and write to the authenticated user, so that one user can never read or modify another user's entries.
6. THE Carryforward_Service SHALL serialize every stored Reported_Carryforward over the wire as a Money_String.

### Requirement 4: Reconcile expected against reported and flag problem years

**User Story:** As the single user, I want the app to highlight years where my reported carryforward does not match the expected one, so that I can find the returns I need to amend.

#### Acceptance Criteria

1. THE Carryforward_Service SHALL assign each reconciled Tax_Year a Reconciliation_Status of `ok`, `mismatch`, or `unreported`.
2. WHERE a Tax_Year has a Reported_Carryforward equal to that year's Expected_Carryforward to the cent, THE Carryforward_Service SHALL assign that year the `ok` status.
3. WHERE a Tax_Year has a Reported_Carryforward that differs from that year's Expected_Carryforward by any non-zero amount, THE Carryforward_Service SHALL assign that year the `mismatch` status.
4. WHERE a Tax_Year has no Reported_Carryforward entered, THE Carryforward_Service SHALL assign that year the `unreported` status.
5. WHEN the Carryforward_Page renders the Reconciliation_Series, THE Carryforward_Page SHALL visually highlight every `mismatch` year distinctly from `ok` and `unreported` years, using a textual status indication so the distinction never rests on color alone.
6. WHEN the Carryforward_Page displays a `mismatch` year, THE Carryforward_Page SHALL show both that year's Expected_Carryforward and its Reported_Carryforward so the user can see the discrepancy.

### Requirement 5: Present the reconciliation table/timeline

**User Story:** As the single user, I want a clear year-by-year view of my carryforward reconciliation, so that I can read my complete history and the problem years at a glance.

#### Acceptance Criteria

1. WHEN the Carryforward_Page renders for a user with at least one reconciled year, THE Carryforward_Page SHALL display one row per reconciled Tax_Year in ascending chronological order.
2. THE Carryforward_Page SHALL display, for each reconciled Tax_Year, that year as a four-digit calendar year, its Schedule_E_Net, its Expected_Carryforward, its Reported_Carryforward (or an explicit not-entered indication), and its Reconciliation_Status.
3. THE Carryforward_Page SHALL render every monetary value in the app's existing display money format (two-decimal, with the app's currency and loss conventions), derived from the Money_String without re-deriving it from a float.
4. WHERE a Tax_Year's Schedule_E_Net is a loss, THE Carryforward_Page SHALL present that net with the app's existing loss indication, distinguishable from a non-negative net.
5. THE Carryforward_Page SHALL provide a control to enter or edit the Reported_Carryforward for each reconciled Tax_Year, surfacing any validation error from Requirement 3 next to that control.
6. THE Carryforward_Page SHALL reflect a saved or cleared Reported_Carryforward in the displayed Reconciliation_Series and statuses without requiring a full page reload.

### Requirement 6: Empty state

**User Story:** As the single user, I want a sensible message when there is nothing to reconcile yet, so that an empty history is not confusing.

#### Acceptance Criteria

1. WHEN the Carryforward_Page renders for a user who has no Data_Years and no Opening_Balance set, THE Carryforward_Page SHALL display the Empty_State guidance rather than an empty or error state.
2. WHILE the Empty_State is shown, THE Carryforward_Page SHALL NOT display a reconciliation table with zero rows and SHALL NOT present an error.

### Requirement 7: Opening balance for pre-data suspended losses

**User Story:** As the single user, I want to seed a starting carryforward from before the app had my data, so that my earliest reconciled years build on the right balance.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL provide a control to set the Opening_Balance as a non-negative two-decimal amount.
2. WHEN the user sets an Opening_Balance, THE Carryforward_Service SHALL persist it for the authenticated user and SHALL carry it into the earliest reconciled year as the balance brought forward (Requirement 2.2).
3. IF a submitted Opening_Balance is negative or not a valid two-decimal money amount, THEN THE Carryforward_Service SHALL reject it with a validation error and SHALL NOT persist any change.
4. WHERE no Opening_Balance has been set, THE Carryforward_Service SHALL treat the Opening_Balance as 0.00.
5. THE Carryforward_Service SHALL scope the Opening_Balance to the authenticated user.

### Requirement 8: Non-advice disclaimer

**User Story:** As the single user, I want the app to be clear that this is a reconciliation aid and not tax advice, so that I do not mistake the expected figure for an authoritative §469 result.

#### Acceptance Criteria

1. WHEN the Carryforward_Page renders, THE Carryforward_Page SHALL display the Disclaimer_Notice in a persistently visible location.
2. THE Disclaimer_Notice SHALL state, in plain language, that the Expected_Carryforward is a reconciliation aid derived from Schedule E net only, that it does not apply the IRC §469 passive-loss limitation (the $25,000 special allowance, its income phase-out, or real-estate-professional status — the parts Form 8582 handles), and that it is not tax advice.
3. THE Carryforward_Page SHALL provide an expandable explanation (collapsed by default) that describes, in plain language, what a suspended passive loss carryforward is, why the app does not compute the §469 limitation (it does not collect the whole-return income and participation facts those rules require), and that the figure is intended to help the user and their tax professional spot years to review.
4. THE Carryforward_Page SHALL NOT present the Expected_Carryforward or any Reconciliation_Status as a definitive tax figure or as a filing instruction.
