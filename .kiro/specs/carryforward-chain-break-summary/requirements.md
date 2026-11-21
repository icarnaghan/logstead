# Requirements Document

## Introduction

The passive loss carryforward page already marks `mismatch` and `carried` years and gives each `mismatch` row a hint. A reader still has to trace the chain by hand to learn where it first broke, how much was dropped, whether a later year added a separate cause, and how large the gap is now. On real data, the 2016 to 2018 lines were reported as `0.00` against expected carry-ins of $2,452, $2,710 and $3,422, and a separate $902 break appeared in 2021 after several `carried` years.

This feature adds two read-only presentations built from fields the page already receives:

1. A **chain summary block** above the reconciliation table, shown only when at least one year is `mismatch`. It names the year the chain first breaks and the amount that appears dropped there, lists each later, separate break with its incremental amount, and states the total gap.
2. A **per-year hint** on `carried` rows that points back to the break year and the drift the row inherited.

The derivation is a small pure function in `frontend/src/lib/`. No backend change, no new wire field, and no change to expected values, `drift`, `status`, `carried_from_year` or the tolerance. The existing disclaimer stays: the page is a reconciliation aid, not tax advice, and the IRC §469 limitation is not computed.

## Glossary

- **Carryforward_Page**: The page component in `frontend/src/pages/CarryforwardPage.tsx` that shows the passive loss carryforward reconciliation.
- **Reconciled_Year**: One row of the series (`ReconciledYear`), with `tax_year`, `status`, `drift`, `expected_carry_in`, `expected_carryforward`, `reported_carryforward` and `carried_from_year`.
- **Money_String**: A fixed two-decimal string such as `"-4323.00"`. Negative `drift` means the reported line is under the expected carry-in.
- **Chain_Analyzer**: The pure functions in `frontend/src/lib/carryforwardChain.ts` that derive the break data from the series.
- **Break_Run**: A maximal sequence of consecutive Reconciled_Years in the series whose `status` is `mismatch`.
- **Break**: The data for one Break_Run: its first year (start year), its last year (end year), and the drift change it caused.
- **First_Break**: The Break whose start year is the earliest of all Breaks.
- **Further_Break**: Any Break other than the First_Break.
- **Baseline_Drift**: The `drift` of the nearest Reconciled_Year before the Break_Run whose `drift` is not null, or `0.00` when there is none.
- **Break_Amount**: The exact difference between a Reconciled_Year's `drift` and the Baseline_Drift of its Break_Run, as a signed Money_String. Negative means amount dropped; positive means extra amount reported.
- **Total_Gap**: The `drift` of the latest Reconciled_Year whose `drift` is not null, with its year.
- **Chain_Summary_Block**: The region rendered above the reconciliation table that presents the First_Break, the Further_Breaks and the Total_Gap.
- **Carried_Row_Hint**: The hint line rendered in the Status_Cell of a `carried` row.
- **Status_Cell**: The status column cell of a table row, which already shows the "Carried from {year}" label.
- **Status_Tolerance**: The `status_tolerance` Money_String on the reconciliation summary.

## Requirements

### Requirement 1

**User Story:** As a user reconciling my carryforward, I want to see where the chain first broke and how much was dropped there, so that I do not have to compare rows by hand.

#### Acceptance Criteria

1. WHEN at least one Reconciled_Year has `status` `mismatch`, THE Carryforward_Page SHALL render the Chain_Summary_Block above the reconciliation table.
2. IF no Reconciled_Year has `status` `mismatch`, THEN THE Carryforward_Page SHALL render no Chain_Summary_Block.
3. WHEN the Chain_Summary_Block is rendered AND the First_Break start year has a preceding Reconciled_Year with a non-null `reported_carryforward`, THE Chain_Summary_Block SHALL state the First_Break start year, the preceding year's `expected_carryforward`, and the start year's `reported_carryforward`, each amount formatted with `formatMoneyWholeDollars`.
4. WHEN the Chain_Summary_Block is rendered AND the First_Break start year is the first Reconciled_Year or has a preceding Reconciled_Year whose `reported_carryforward` is null, THE Chain_Summary_Block SHALL state the First_Break start year, the start year's `reported_carryforward`, and the start year's `expected_carry_in`, each formatted with `formatMoneyWholeDollars`.
5. WHEN the First_Break end year is later than its start year, THE Chain_Summary_Block SHALL state the end year and the Break_Amount at the end year formatted with `formatMoneyWholeDollars`.
6. WHEN a Break_Amount is negative, THE Chain_Summary_Block SHALL describe it with the word "dropped", and WHEN a Break_Amount is positive, THE Chain_Summary_Block SHALL describe it with the word "extra".

### Requirement 2

**User Story:** As a user, I want later, separate breaks listed on their own, so that one root cause is not mistaken for the whole gap.

#### Acceptance Criteria

1. WHEN the series contains more than one Break_Run, THE Chain_Summary_Block SHALL list each Further_Break in ascending year order as a list item.
2. THE Chain_Summary_Block SHALL show for each Further_Break its start year, its end year when later than the start year, and its Break_Amount at the end year formatted with `formatMoneyWholeDollars`.
3. THE Chain_Analyzer SHALL compute the Break_Amount of each Break_Run as the difference between the `drift` of its end year and its Baseline_Drift, so that a Further_Break reports only the change it caused.
4. IF the series contains exactly one Break_Run, THEN THE Chain_Summary_Block SHALL render no Further_Break list.

### Requirement 3

**User Story:** As a user, I want the total gap stated, so that I know how far the latest return is from the expected carry-in.

#### Acceptance Criteria

1. WHEN the Chain_Summary_Block is rendered, THE Chain_Summary_Block SHALL state the year and the absolute value of the Total_Gap formatted with `formatMoneyWholeDollars`.
2. WHEN the Total_Gap is negative and its absolute value exceeds the Status_Tolerance, THE Chain_Summary_Block SHALL describe the gap as "under" the expected carry-in, and WHEN it is positive and exceeds the Status_Tolerance, THE Chain_Summary_Block SHALL describe the gap as "over" the expected carry-in.
3. WHEN the absolute value of the Total_Gap is less than or equal to the Status_Tolerance, THE Chain_Summary_Block SHALL state that the latest reported line is within the Status_Tolerance of the expected carry-in, with the tolerance formatted with `formatMoneyWholeDollars`.
4. THE Chain_Analyzer SHALL take the Total_Gap from the `drift` of the latest Reconciled_Year whose `drift` is not null.

### Requirement 4

**User Story:** As a user, I want each carried year to point back to the break it inherited, so that I can see why the row is flagged without reading the whole table.

#### Acceptance Criteria

1. WHEN a Reconciled_Year has `status` `carried`, a non-null `carried_from_year` and a non-null `drift`, THE Status_Cell SHALL render a Carried_Row_Hint below the existing "Carried from {year}" label.
2. THE Carried_Row_Hint SHALL state the `carried_from_year` and the absolute value of the row's own `drift` formatted with `formatMoneyWholeDollars`, followed by "under" when `drift` is negative or "over" when `drift` is positive.
3. WHEN the First_Break start year differs from the row's `carried_from_year`, THE Carried_Row_Hint SHALL also state the First_Break start year.
4. IF a Reconciled_Year has `status` other than `carried`, or has a null `carried_from_year`, or has a null `drift`, THEN THE Status_Cell SHALL render no Carried_Row_Hint.
5. THE Carryforward_Page SHALL keep the existing "Carried from {year}" label and the existing `mismatch` hint text unchanged.

### Requirement 5

**User Story:** As a maintainer, I want the derivation exact and isolated, so that money is never subject to floating-point error and the logic is testable on its own.

#### Acceptance Criteria

1. THE Chain_Analyzer SHALL reside in `frontend/src/lib/carryforwardChain.ts` as pure functions with no React, network or DOM dependency.
2. THE Chain_Analyzer SHALL compute every Break_Amount and the Total_Gap in exact integer cents using `toCents` and `centsToMoney`, and SHALL return them as Money_Strings.
3. THE Chain_Analyzer SHALL leave its input series unmodified.
4. THE Carryforward_Page SHALL derive all Chain_Summary_Block and Carried_Row_Hint content from the existing `ReconciledYear` fields and the Status_Tolerance, with no new backend field or request.
5. THE Carryforward_Page SHALL keep the values of `expected_carry_in`, `expected_carryforward`, `drift`, `status` and `carried_from_year` as received from the backend.

### Requirement 6

**User Story:** As a user relying on assistive technology, I want the summary and hints readable without color, so that the information reaches me regardless of how I read the page.

#### Acceptance Criteria

1. THE Chain_Summary_Block SHALL be a labelled region with a visible heading, exposed through `aria-labelledby`.
2. THE Chain_Summary_Block SHALL convey every break, amount and direction in text, with no meaning carried by color alone.
3. WHEN Further_Breaks are listed, THE Chain_Summary_Block SHALL render them as a semantic list.

### Requirement 7

**User Story:** As a user, I want the existing framing kept, so that the summary is not mistaken for tax advice.

#### Acceptance Criteria

1. THE Carryforward_Page SHALL keep rendering the existing disclaimer in every state, unchanged.
2. THE Chain_Summary_Block SHALL describe figures as "about" amounts in whole dollars and SHALL name the return line to review, without stating a required correction or tax amount.
3. THE Carryforward_Page SHALL compute no IRC §469 limitation as part of this feature.

### Requirement 8

**User Story:** As a maintainer, I want the change verified by tests and recorded in the project docs, so that behavior and history stay reliable.

#### Acceptance Criteria

1. THE project SHALL include unit tests for the Chain_Analyzer, and property-based tests for it that run at least 100 iterations each.
2. THE project SHALL include React Testing Library tests for the Chain_Summary_Block and the Carried_Row_Hint, including a property-based test that runs at least 100 iterations.
3. THE project SHALL include a test of the real-data shape: mismatch years 2016 to 2018, carried years 2019 to 2020, a mismatch in 2021, then carried years through 2025.
4. THE existing Carryforward_Page tests SHALL continue to pass, with only assertions that collide with the new summary text adjusted.
5. THE `CHANGELOG.md` SHALL record the change under `[Unreleased]`.
6. THE `docs/future-improvements.md` entry "Summarize where a carryforward chain first broke" SHALL be marked as addressed.
