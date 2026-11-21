# Requirements Document

## Introduction

The mortgage-amortization feature models a Loan from origination: original principal, rate, term, first payment date, and an optional payment override. That model assumes the user has made only the scheduled payments since day one. A user who has made extra principal payments in the past gets a generated schedule that does not match the lender's real balance.

This feature replaces the origination model with a balance-anchor model. A Loan is defined by its annual interest rate, its monthly principal-and-interest payment, and one known balance (the Anchor_Balance) on one date (the Anchor_Date). Logstead projects forward from that anchor. The remaining payments, the payoff date, and the final smaller payment are derived, not entered. The original principal becomes an optional, informational field that no calculation reads.

Because the schedule starts at the anchor, Logstead generates no interest for tax years before the Anchor_Date year, and generates interest for the Anchor_Date year only for payments after the Anchor_Date. The user already has Form 1098 figures for those periods, so the feature lets the user enter an Interest_Override for any tax year from 1900 through the Anchor_Date year, including years that have no generated payments. Those overrides feed Schedule E Line 12 through the existing precedence rule, so the manual Line 12 fallback still applies when the effective loan interest is 0.00.

The mortgage-amortization feature was never released, so no real loans exist in the origination shape and this change needs no data migration. A stored or backed-up Loan that lacks the anchor fields is invalid and is rejected by strict reads and by backup validation. Any Loan created locally with the origination fields must be re-entered. The backup `schema_version` stays "1".

This spec supersedes the loan input model of the `mortgage-amortization` spec. Requirements from that spec that are not restated here (Line 12 precedence, report display, carryforward integration, ownership scoping, atomic writes, Loan deletion, key layout) continue to apply and are listed in Requirement 14.

### Assumptions

- Payments are monthly. The Monthly_Payment covers principal and interest only. Escrow (taxes, insurance, PMI) is out of scope.
- The Anchor_Balance is the principal balance immediately after the payment made on the Anchor_Date. That payment is already applied and is not part of the generated schedule. The first projected payment falls one calendar month after the Anchor_Date.
- Later payments fall on the same day of each following month as the Anchor_Date, clamped to the last day of shorter months, always clamping from the original Anchor_Date day (Jan 31 gives Feb 28 or 29, then Mar 31).
- Interest for a payment is the balance before the payment multiplied by the annual rate divided by 12, rounded half-up to the cent. Each payment belongs to the tax year of its payment date (cash basis).
- A user who enters today's balance can set the Anchor_Date to today. The Loans_Page defaults the Anchor_Date to today and lets the user change it.
- Only one anchor per Loan is supported. Multiple balance checkpoints are recorded in `docs/future-improvements.md` and are out of scope.
- Interest-only periods, adjustable rates, balloon payments, and daily-accrual interest are out of scope. A refinance is modeled as ending one Loan and creating another.
- Loan data is scoped to the authenticated user and to one Property.

## Glossary

- **Logstead**: The rental-property Schedule E tracking application.
- **Loan_Service**: The backend service that owns Loan create, list, get, update, delete, the schedule projection, and Interest_Overrides.
- **Loan**: A mortgage or similar loan belonging to one Property, defined by an Annual_Interest_Rate, a Monthly_Payment, an Anchor_Balance, and an Anchor_Date.
- **Property**: A rental unit that is one column of Schedule E Part I.
- **Annual_Interest_Rate**: The nominal annual rate as a percentage Decimal with at most four decimal places (for example 6.875).
- **Monthly_Payment**: The principal-and-interest amount paid each month, as a positive two-decimal Decimal.
- **Anchor_Balance**: The principal balance immediately after the payment made on the Anchor_Date, as a positive two-decimal Decimal.
- **Anchor_Date**: The ISO-8601 date (YYYY-MM-DD) of the payment after which the Anchor_Balance is known.
- **Anchor_Year**: The calendar year of the Anchor_Date.
- **Next_Payment_Date**: The date one calendar month after the Anchor_Date, with the day clamped to the last day of that month. The Next_Payment_Date is the date of the first Payment_Row.
- **Extra_Principal**: An optional fixed two-decimal amount added to principal with every projected payment.
- **Payoff_Date**: An optional date on which the Loan ends early. No Payment_Row is generated after the Payoff_Date.
- **Original_Principal**: An optional, informational two-decimal amount that the Loan originally borrowed. No calculation reads the Original_Principal.
- **Closing_Date**: An optional, informational date on which the Loan originated. No calculation reads the Closing_Date.
- **Payment_Row**: One projected payment with its payment number, date, payment amount, interest portion, principal portion, and remaining balance.
- **Amortization_Schedule**: The ordered list of Payment_Rows for a Loan, projected forward from the anchor.
- **Remaining_Payments**: The number of Payment_Rows in the Amortization_Schedule, derived by the Loan_Service.
- **Projected_Payoff_Date**: The date of the final Payment_Row when the final balance is 0.00, derived by the Loan_Service.
- **Final_Payment**: The last Payment_Row of a Loan that fully amortizes, which sweeps the remaining balance and may be smaller than the Monthly_Payment.
- **Yearly_Rollup**: For one Loan and tax year, the sum of interest, principal, and payments, and the ending balance, of the Payment_Rows dated in that year.
- **Override_Only_Rollup**: A Yearly_Rollup row stored for a tax year that has an Interest_Override but no Payment_Row. It has 0 payments, an estimated interest of 0.00, principal of 0.00, total paid of 0.00, and no ending balance.
- **Interest_Override**: An optional user-supplied interest amount for one Loan and one tax year, entered to match Form 1098.
- **Effective_Interest**: For one Loan and tax year, the Interest_Override when one exists, otherwise the Yearly_Rollup interest.
- **Report_Inclusion**: A per-Loan flag, default on, that controls whether the Loan's Effective_Interest feeds Schedule E Line 12.
- **Manual_Mortgage_Interest**: The total of the user's expense transactions in the `mortgage-interest-banks` category (Schedule E Line 12) for a Property and tax year.
- **Reporting_Service**: The existing `ReportingService` that builds per-property and combined Schedule E reports.
- **Backup_Service**: The existing service that exports and restores the user's data as a backup document.
- **Loans_Page**: The frontend page for a Property that lists Loans and shows the Amortization_Schedule.
- **Loan_Preview**: The Loans_Page display of the Remaining_Payments and Projected_Payoff_Date computed in the browser from the form values.
- **Form_1098**: The IRS Mortgage Interest Statement that the lender issues each year.
- **Whole_Dollar_Format**: The existing `formatMoneyWholeDollars` display that renders money as whole dollars.

## Requirements

### Requirement 1: Define a Loan by its anchor

**User Story:** As a landlord, I want to record my loan from a balance I know today, so that the projection starts from reality even though I made extra principal payments in the past.

#### Acceptance Criteria

1. WHEN a valid Loan is submitted for a Property owned by the authenticated user, THE Loan_Service SHALL persist the Loan with a generated unique id and created and updated timestamps, generate the Amortization_Schedule and Yearly_Rollups, and return the persisted Loan.
2. THE Loan_Service SHALL require a description of 1 to 200 characters, an Annual_Interest_Rate, a Monthly_Payment, an Anchor_Balance, and an Anchor_Date for every Loan.
3. IF a required Loan field is missing or a description is empty or longer than 200 characters, THEN THE Loan_Service SHALL return a validation failure identifying each offending field and SHALL NOT persist or modify any Loan.
4. IF the Anchor_Balance is zero, negative, greater than 999,999,999.99, or has more than two decimal places, THEN THE Loan_Service SHALL return a validation failure on the anchor balance field and SHALL NOT persist or modify any Loan.
5. IF the Monthly_Payment is zero, negative, greater than 999,999,999.99, or has more than two decimal places, THEN THE Loan_Service SHALL return a validation failure on the monthly payment field and SHALL NOT persist or modify any Loan.
6. IF the Annual_Interest_Rate is negative, is greater than 100, or has more than four decimal places, THEN THE Loan_Service SHALL return a validation failure on the interest rate field and SHALL NOT persist or modify any Loan.
7. IF the Anchor_Date is not a valid ISO-8601 calendar date (YYYY-MM-DD) or is earlier than 1900-01-01, THEN THE Loan_Service SHALL return a validation failure on the anchor date field and SHALL NOT persist or modify any Loan.
8. IF the Monthly_Payment is less than or equal to one month of interest on the Anchor_Balance at the Annual_Interest_Rate, THEN THE Loan_Service SHALL return a validation failure on the monthly payment field stating that the payment must exceed the first month's interest, and SHALL NOT persist or modify any Loan.
9. WHEN the user updates an existing Loan with valid input, THE Loan_Service SHALL re-validate the input with the same rules as create, preserve the Loan id and created timestamp, set the updated timestamp to the time of the update, and regenerate the Amortization_Schedule and Yearly_Rollups.
10. WHEN the user deletes an existing Loan, THE Loan_Service SHALL delete the Loan, its Interest_Overrides, and all of its stored Yearly_Rollups in one atomic operation, such that either all are removed or none are.

### Requirement 2: Project the schedule forward from the anchor

**User Story:** As a landlord, I want the payment table to start after my known balance and derive the remaining payments, so that the payoff date and the final payment match what the lender will actually show.

#### Acceptance Criteria

1. WHEN the Amortization_Schedule is generated for a valid Loan, THE Loan_Service SHALL date the first Payment_Row on the Next_Payment_Date and date each later Payment_Row one calendar month after the previous one, clamping the day to the last day of the month from the original Anchor_Date day.
2. THE Loan_Service SHALL generate no Payment_Row dated on or before the Anchor_Date.
3. WHEN a Payment_Row is generated, THE Loan_Service SHALL compute the interest portion as the balance before the payment multiplied by the Annual_Interest_Rate divided by 100 and divided by 12, rounded half-up to 2 decimal places.
4. WHEN a Payment_Row is generated and the balance before the payment plus that interest is greater than the Monthly_Payment plus any Extra_Principal, THE Loan_Service SHALL set the principal portion to the Monthly_Payment plus any Extra_Principal minus the interest portion.
5. WHEN the balance before a payment plus that payment's interest is less than or equal to the Monthly_Payment plus any Extra_Principal, THE Loan_Service SHALL make that Payment_Row the Final_Payment, with a principal portion equal to the balance before the payment, a payment amount equal to that principal plus the interest, and an ending balance of 0.00, and SHALL generate no further Payment_Rows.
6. THE Loan_Service SHALL derive the Remaining_Payments as the number of Payment_Rows and SHALL NOT accept a remaining payment count as input.
7. WHERE the Amortization_Schedule ends with an ending balance of 0.00, THE Loan_Service SHALL report the date of the Final_Payment as the Projected_Payoff_Date.
8. FOR ALL valid Loans, THE Loan_Service SHALL produce Payment_Rows in which the interest portion plus the principal portion equals the payment amount.
9. FOR ALL valid Loans without a Payoff_Date, THE Loan_Service SHALL produce Payment_Rows whose principal portions sum exactly to the Anchor_Balance and whose final remaining balance equals 0.00.
10. FOR ALL valid Loans, THE Loan_Service SHALL produce Payment_Rows whose remaining balance is strictly decreasing from the Anchor_Balance and never less than 0.00.
11. FOR ALL valid Loans, THE Loan_Service SHALL produce an identical Amortization_Schedule when computed twice from identical inputs.
12. WHERE the Annual_Interest_Rate is 0, THE Loan_Service SHALL set the interest portion of every Payment_Row to 0.00.
13. THE Loan_Service SHALL perform all schedule arithmetic using Decimal values rounded half-up to 2 decimal places at each Payment_Row and SHALL NOT use floating-point arithmetic.
14. IF the Amortization_Schedule would need more than 600 Payment_Rows, THEN THE Loan_Service SHALL return a validation failure on the monthly payment field stating that the loan would take more than 600 payments to pay off, and SHALL NOT persist or modify any Loan.
15. IF the date of any Payment_Row would fall after December 31, 9999, THEN THE Loan_Service SHALL return a validation failure on the anchor date field and SHALL NOT persist or modify any Loan.
16. FOR ALL valid Loans and every Payment_Row k that is not the Final_Payment, a Loan with the same rate, Monthly_Payment, and Extra_Principal anchored on the date of Payment_Row k with the balance of Payment_Row k SHALL produce the same interest, principal, payment, and balance in every later Payment_Row, and the same dates when the Anchor_Date day is 28 or less.

### Requirement 3: Extra principal and early payoff

**User Story:** As a landlord, I want to model ongoing extra principal and an early payoff date from the anchor forward, so that the projection reflects what I plan to do.

#### Acceptance Criteria

1. WHERE an Extra_Principal is supplied, THE Loan_Service SHALL add the Extra_Principal to the principal portion of every projected Payment_Row until the balance reaches 0.00.
2. IF an Extra_Principal is negative, greater than 999,999,999.99, or has more than two decimal places, THEN THE Loan_Service SHALL return a validation failure on the extra principal field and SHALL NOT persist or modify any Loan.
3. WHERE a Payoff_Date is supplied, THE Loan_Service SHALL generate no Payment_Row dated after the Payoff_Date.
4. WHERE a Payoff_Date is supplied and the balance remains positive after the last Payment_Row on or before the Payoff_Date, THE Loan_Service SHALL report that balance, to the cent, as the payoff balance of the Loan.
5. IF the Payoff_Date is not a valid ISO-8601 calendar date or is earlier than the Next_Payment_Date, THEN THE Loan_Service SHALL return a validation failure on the payoff date field and SHALL NOT persist or modify any Loan.
6. FOR ALL valid Loans with a Payoff_Date, THE Loan_Service SHALL produce Payment_Rows whose principal portions plus the payoff balance equal the Anchor_Balance.
7. FOR ALL valid Loans and any Payoff_Date, THE Loan_Service SHALL produce Payment_Rows that are exactly the leading Payment_Rows of the same Loan without a Payoff_Date that are dated on or before the Payoff_Date.
8. FOR ALL valid Loans and any Extra_Principal greater than 0.00, THE Loan_Service SHALL produce no more Payment_Rows and no greater total interest than the same Loan with an Extra_Principal of 0.00.
9. WHEN the user sets or clears a Payoff_Date, THE Loan_Service SHALL regenerate the Amortization_Schedule and Yearly_Rollups, and clearing the Payoff_Date SHALL restore the Yearly_Rollups that the same Loan had without a Payoff_Date.

### Requirement 4: Original principal and closing date are informational

**User Story:** As a landlord, I want to keep the original loan amount and closing date on the record, so that I can see them without them changing my numbers.

#### Acceptance Criteria

1. WHERE an Original_Principal is supplied, THE Loan_Service SHALL store the Original_Principal as a two-decimal money string and return it in Loan responses.
2. IF a supplied Original_Principal is zero, negative, greater than 999,999,999.99, or has more than two decimal places, THEN THE Loan_Service SHALL return a validation failure on the original principal field and SHALL NOT persist or modify any Loan.
3. WHERE a Closing_Date is supplied, THE Loan_Service SHALL store the Closing_Date and return it in Loan responses.
4. IF a supplied Closing_Date is not a valid ISO-8601 calendar date, THEN THE Loan_Service SHALL return a validation failure on the closing date field and SHALL NOT persist or modify any Loan.
5. FOR ALL valid Loans, THE Loan_Service SHALL produce identical Payment_Rows, Yearly_Rollups, and Effective_Interest whether the Original_Principal and Closing_Date are absent, present, or changed.

### Requirement 5: Yearly rollups and the anchor year

**User Story:** As a landlord, I want yearly interest totals that cover only the payments Logstead actually projects, so that I know which years I must fill in from Form 1098.

#### Acceptance Criteria

1. WHEN a Loan's Payment_Rows are generated, THE Loan_Service SHALL compute exactly one Yearly_Rollup for each tax year in which the Loan has at least one Payment_Row.
2. THE Loan_Service SHALL generate no interest and no Yearly_Rollup from the Amortization_Schedule for any tax year before the Anchor_Year.
3. THE Loan_Service SHALL include in the Anchor_Year Yearly_Rollup only the Payment_Rows dated after the Anchor_Date, with no interest or principal prorated or added for payments on or before the Anchor_Date.
4. FOR ALL valid Loans, THE Loan_Service SHALL produce a Yearly_Rollup interest, principal, and total paid equal to the sums of the Payment_Row values dated in that year, and an ending balance equal to the remaining balance of the last Payment_Row dated in that year.
5. WHEN a tax year has no Payment_Row and no Interest_Override for a Loan, THE Loan_Service SHALL report 0.00 interest and 0.00 principal for that Loan and tax year.
6. WHEN a Loan is created or updated, THE Loan_Service SHALL store its Yearly_Rollups and Override_Only_Rollups so that the total Effective_Interest for a Property and a single tax year is readable with one tax-year query, and SHALL replace all previously stored rollup rows for that Loan so that no stale rollup remains.
7. IF storing the Yearly_Rollups fails when a Loan is created or updated, THEN THE Loan_Service SHALL return an error indicating that the rollups were not saved and SHALL retain the Loan's previously stored Loan item and rollup rows unchanged.

### Requirement 6: Interest overrides for years outside the generated schedule

**User Story:** As a landlord, I want to enter my Form 1098 interest for the anchor year and for earlier years, so that Schedule E uses the lender's figures for periods the projection does not cover.

#### Acceptance Criteria

1. WHERE the user supplies a valid Interest_Override for a Loan and a tax year that has a Payment_Row, THE Loan_Service SHALL use the Interest_Override as the Effective_Interest for that Loan and tax year.
2. WHERE the user supplies a valid Interest_Override for a Loan and a tax year that has no Payment_Row and is between 1900 and the Anchor_Year inclusive, THE Loan_Service SHALL store an Override_Only_Rollup for that tax year and use the Interest_Override as the Effective_Interest for that Loan and tax year.
3. IF an Interest_Override is supplied for a tax year that is earlier than 1900, or that is later than the Anchor_Year and has no Payment_Row, THEN THE Loan_Service SHALL return a validation failure on the field identifying that tax year and SHALL store no Interest_Override for that tax year.
4. IF an Interest_Override is negative, has more than two decimal places, or is not a numeric value, THEN THE Loan_Service SHALL return a validation failure on the field identifying that tax year and SHALL retain the previously stored Interest_Override for that tax year, if any.
5. WHEN an Interest_Override is created, changed, or removed, THE Loan_Service SHALL leave every Payment_Row, every balance, and every principal total for the Loan identical to its value before the change.
6. WHEN an Interest_Override exists for a Loan and tax year, THE Loan_Service SHALL expose the estimate variance for that tax year as the Interest_Override minus the Yearly_Rollup interest, as a signed two-decimal money string, using 0.00 as the Yearly_Rollup interest for an Override_Only_Rollup.
7. WHEN the user removes an Interest_Override for a tax year that has a Payment_Row, THE Loan_Service SHALL revert the Effective_Interest for that Loan and tax year to the Yearly_Rollup interest.
8. WHEN the user removes an Interest_Override for a tax year that has no Payment_Row, THE Loan_Service SHALL delete the Override_Only_Rollup for that tax year.
9. WHEN a Loan is updated, THE Loan_Service SHALL retain each Interest_Override whose tax year is between 1900 and the new Anchor_Year inclusive or has a Payment_Row in the new schedule, SHALL delete every other Interest_Override together with its rollup row, and SHALL write Override_Only_Rollups for retained Interest_Overrides that no longer have a Payment_Row.
10. THE Loan_Service SHALL store each Interest_Override as a money string with exactly two decimal places, including a value of zero stored as "0.00".

### Requirement 7: Line 12 and data years with override-only rollups

**User Story:** As a landlord, I want my Form 1098 figures for past years to fill Line 12 without being added to my hand-entered entries, so that earlier-year reports and the carryforward chain use the lender's numbers.

#### Acceptance Criteria

1. WHEN a Schedule_E_Report is built for a Property and a tax year in which an included Loan has an Override_Only_Rollup, THE Reporting_Service SHALL include that Override_Only_Rollup's Effective_Interest in the Loan interest that is evaluated by the existing Line 12 precedence rule.
2. WHEN every included Loan of a Property has an Effective_Interest of 0.00 in a tax year, THE Reporting_Service SHALL set the Line 12 total to the Manual_Mortgage_Interest, including when that Effective_Interest comes from an Interest_Override of 0.00 on an Override_Only_Rollup.
3. THE Reporting_Service SHALL keep the Line 12 source values, the superseded-manual-interest figure, the Line 12 impact notice data, the combined report sums, and the export fields defined by mortgage-amortization Requirement 6 unchanged.
4. WHEN the set of Data_Years is derived, THE Logstead SHALL include each tax year, up to the latest completed tax year, in which an included Loan has a Yearly_Rollup or an Override_Only_Rollup.
5. WHEN the earliest data year of a Property is derived, THE Logstead SHALL consider the Anchor_Year and the earliest tax year of any Interest_Override of each Loan of that Property.
6. WHEN the passive-loss carryforward is computed for a tax year, THE Reporting_Service SHALL supply the net that includes the Effective_Interest of Override_Only_Rollups to the carryforward calculation.

### Requirement 8: Loans API

**User Story:** As a frontend developer, I want the Loans API to carry the anchor model, so that the UI can manage loans and their past-year overrides.

#### Acceptance Criteria

1. THE Logstead SHALL accept and return Loans under the existing `/properties/{propertyId}/loans` routes, with the fields description, annual interest rate, monthly payment, anchor balance, anchor date, extra principal, payoff date, original principal, closing date, and Report_Inclusion.
2. THE Logstead SHALL return in every Loan response the derived fields remaining payments, next payment date, projected payoff date, payoff balance, and status, and SHALL NOT return term, first payment date, payment override, default payment, or scheduled payment fields.
3. THE Logstead SHALL serialize every money value in Loan API responses as a decimal string with exactly two digits after the decimal point and the Annual_Interest_Rate as a decimal string.
4. IF a Loan request sends the Annual_Interest_Rate, Monthly_Payment, Anchor_Balance, Extra_Principal, or Original_Principal as a JSON floating-point number, THEN THE Logstead SHALL return a validation failure on that field and SHALL NOT change any stored data.
5. WHEN an authenticated user requests the Amortization_Schedule for a Loan, THE Logstead SHALL return the Payment_Rows ordered by payment date ascending and the Yearly_Rollups, including Override_Only_Rollups, ordered by tax year ascending, with a null ending balance for each Override_Only_Rollup.
6. WHEN an authenticated user submits a set request for an Interest_Override for a Loan and a tax year, THE Logstead SHALL store the override under the rules of Requirement 6 and return the resulting yearly object.
7. IF a request references a Property that does not exist or does not belong to the authenticated user, THEN THE Logstead SHALL return a not-found response that is identical in status and body for both cases and SHALL NOT change any stored data.
8. IF a Loan request fails validation, THEN THE Logstead SHALL reject the request, return a validation error response that names each offending field using the existing error shape, and SHALL leave stored data unchanged.
9. WHEN a valid Loan is serialized by the API and parsed again, THE Logstead SHALL produce a Loan equal to the original in every field, including the exact Annual_Interest_Rate decimal value and every money value to two decimal places.

### Requirement 9: Backup and restore

**User Story:** As a landlord, I want backups to carry the anchor loan shape, so that a restore reproduces my mortgage data.

#### Acceptance Criteria

1. WHEN a backup is exported, THE Backup_Service SHALL include for each Loan the anchor-shape fields, the informational fields, the Report_Inclusion flag, the timestamps, and all Interest_Overrides including those on years without Payment_Rows, with every money value as a string with exactly two decimal places.
2. THE Backup_Service SHALL exclude stored Yearly_Rollup rows, Override_Only_Rollups, and Payment_Rows from the backup document.
3. WHEN a backup that contains anchor-shape Loans is restored, THE Backup_Service SHALL preserve each Loan's id, created timestamp, and updated timestamp and SHALL recompute the Yearly_Rollups and Override_Only_Rollups before the restore completes.
4. IF a Loan in a backup document fails the Loan validation rules, including a Loan that lacks a required anchor-shape field and an Interest_Override for a tax year that is not permitted by Requirement 6, THEN THE Backup_Service SHALL reject the entire restore, persist no data from the backup document, and return an error that names the Property, the Loan, and the rule violated.
5. WHEN a backup is exported, restored into an empty account, and exported again, THE Backup_Service SHALL produce a second export whose Loan content is identical to the first export's Loan content.
6. THE Backup_Service SHALL keep the backup `schema_version` equal to "1".
7. WHEN a backup document that contains no Loans is restored, THE Backup_Service SHALL create zero Loans and report a restored Loan count of 0.

### Requirement 10: Loan form and preview

**User Story:** As a landlord, I want a simple form that asks for my current balance and payment, so that I can set up a loan in a minute and see when it will be paid off.

#### Acceptance Criteria

1. THE Loans_Page SHALL provide a form to create and edit a Loan with fields for description, Annual_Interest_Rate, Monthly_Payment, Anchor_Balance, Anchor_Date, and the optional Extra_Principal, Payoff_Date, Original_Principal, Closing_Date, and Report_Inclusion.
2. WHEN the user opens the form to create a Loan, THE Loans_Page SHALL set the Anchor_Date to today's date and SHALL allow the user to change the Anchor_Date.
3. THE Loans_Page SHALL display help text that defines the Anchor_Balance as the balance after the payment made on the Anchor_Date and states that the first projected payment is one month later.
4. WHEN the user enters a valid Annual_Interest_Rate, Monthly_Payment, Anchor_Balance, and Anchor_Date, THE Loans_Page SHALL display the Loan_Preview with the Remaining_Payments and the Projected_Payoff_Date within 500 milliseconds and before the user submits.
5. IF the form values are missing or invalid, or the Monthly_Payment does not exceed the first month's interest, or the schedule would need more than 600 payments, THEN THE Loans_Page SHALL hide the Loan_Preview and SHALL NOT display a stale value.
6. THE Loans_Page SHALL compute the Loan_Preview in the browser using BigInt fixed-point arithmetic and SHALL produce the same Remaining_Payments and Projected_Payoff_Date as the Loan_Service for the shared golden vectors.
7. IF the API rejects a submitted Loan with a validation error that names a field, THEN THE Loans_Page SHALL show the validation message next to that field, SHALL retain all values the user entered, and SHALL NOT add the Loan to the list.
8. IF the API rejects a submitted Loan with an error that names no field or the request fails, THEN THE Loans_Page SHALL show an error message at the form level, SHALL retain all values the user entered, and SHALL NOT add or change the Loan in the list.

### Requirement 11: Loans page tables and guidance

**User Story:** As a landlord, I want the page to tell me which years I need to fill in from Form 1098, so that my Schedule E uses the right figures.

#### Acceptance Criteria

1. THE Loans_Page SHALL list the Loans of the Property with each Loan's description, Anchor_Balance and Anchor_Date, Annual_Interest_Rate, Monthly_Payment, Remaining_Payments with Projected_Payoff_Date, and status.
2. THE Loans_Page SHALL render the Yearly_Rollup table with columns for tax year, interest, principal, total paid, and ending balance in Whole_Dollar_Format, with one row per tax year that has a Payment_Row or an Interest_Override.
3. WHEN a Yearly_Rollup row is an Override_Only_Rollup, THE Loans_Page SHALL display a text dash in the principal, total paid, and ending balance cells of that row.
4. WHEN a Loan is selected, THE Loans_Page SHALL display a notice that states the Anchor_Year, states that generated interest for the Anchor_Year covers only payments after the Anchor_Date, and tells the user to enter the Form_1098 interest as an Interest_Override for the Anchor_Year and for earlier years.
5. WHEN a Loan is selected, THE Loans_Page SHALL provide a control to add an Interest_Override for a tax year between 1900 and the Anchor_Year inclusive that has no Payment_Row.
6. IF the user enters a tax year outside 1900 through the Anchor_Year, or an amount that is negative, not a number, or has more than two decimals, in the add-override control, THEN THE Loans_Page SHALL show a validation message next to the invalid field and SHALL NOT call the API.
7. WHEN the user removes an Interest_Override for a tax year with no Payment_Row, THE Loans_Page SHALL remove that tax year's row from the Yearly_Rollup table.
8. THE Loans_Page SHALL display a notice that the schedule is an estimate and that the user should reconcile the figures with Form_1098.
9. THE Loans_Page SHALL expose every form control, button, and table header with an accessible name, and SHALL allow every action on the page to be completed using only the keyboard.

### Requirement 12: Storage, sample data, and documentation

**User Story:** As a maintainer, I want the new shape stored and documented consistently, so that the code and the docs stay aligned.

#### Acceptance Criteria

1. THE Logstead SHALL store a Loan under its Property's partition with the existing Loan key prefix, persisting the Anchor_Balance, Monthly_Payment, Extra_Principal, and Original_Principal as two-decimal money strings, the Anchor_Date as an ISO date string, and the Annual_Interest_Rate as a plain decimal string.
2. THE Logstead SHALL store each rollup row with the existing rollup key prefix and the existing GSI2 tax-year key, and SHALL omit the ending balance attribute on an Override_Only_Rollup.
3. IF a stored Loan lacks a required anchor-shape field, or a stored Loan money value cannot be parsed as a two-decimal string, or the Annual_Interest_Rate cannot be parsed as a decimal string when read, THEN THE Logstead SHALL reject the read with an error indicating the invalid field and SHALL leave the stored data unchanged.
4. THE Logstead SHALL document in `docs/data-model.md` the anchor-shape Loan attributes, the Override_Only_Rollup row, and the Line 12 precedence rule, with each topic under its own heading.
5. THE Logstead SHALL document in `docs/api.md` the anchor-shape request and response fields and the extended Interest_Override tax-year range.
6. THE Logstead SHALL record the change in `CHANGELOG.md` under the Unreleased heading.
7. THE Logstead SHALL provide a sample backup document `frontend/src/data/sample-backup.json` whose Loan uses the anchor shape and includes an Interest_Override for a tax year before the Anchor_Year.

### Requirement 13: Retained behavior

**User Story:** As a maintainer, I want the unchanged parts of the loan feature to keep working, so that this change does not regress reports or ownership rules.

#### Acceptance Criteria

1. THE Logstead SHALL continue to satisfy mortgage-amortization Requirements 6 (Line 12 integration and double-counting prevention), 10 (report display of the Line 12 source), and 9.16 through 9.20 (superseded notice, delete, navigation, accessibility) for anchor-shape Loans.
2. THE Logstead SHALL continue to apply Property ownership scoping, atomic multi-item writes, strict stored-value readers, and the rejection of Property deletion while Loans exist, as defined by mortgage-amortization Requirements 1.10 through 1.15, 8.7, 8.8, and 12.
3. THE Logstead SHALL continue to compute all money with Decimal values and to transport money as two-decimal strings.
4. THE Logstead SHALL continue to support any number of Loans under one Property, each with its own anchor and schedule.
