# Requirements Document

## Introduction

Logstead currently derives Schedule E Line 12 (Mortgage interest paid to banks) only from expense transactions that the user enters by hand. Depreciation already shows a better pattern: the user enters a few inputs, the system generates a schedule, and the Schedule E report reads the yearly amount from that schedule.

This feature mirrors that pattern for mortgages. A user records a Loan under a Property (original principal, annual interest rate, term, first payment date, and optional extras). Logstead generates a monthly Amortization_Schedule, rolls the payments up into per-year interest and principal totals, and feeds the yearly interest into Schedule E Line 12 in the per-property and combined reports. Because the net figure feeds the passive-loss carryforward, the generated interest flows into carryforward through the existing report totals.

The generated figures are an estimate. Lenders report the authoritative interest figure on Form 1098, so the feature lets the user override the interest for a tax year to match Form 1098 and always labels the schedule as an estimate.

### Assumptions

- Payments are monthly. One payment is scheduled per month, starting on the first payment date.
- Each payment is attributed to the tax year of its payment date (cash basis). Interest for a payment is the balance before the payment multiplied by the annual rate divided by 12, rounded to the cent (half-up).
- The Loan's payment covers principal and interest only. Escrow (taxes, insurance, PMI) is out of scope and remains user-entered transactions.
- Interest-only periods, adjustable rates, balloon payments, and daily-accrual interest are out of scope. A refinance is modeled as ending one Loan and creating another.
- A property may have several Loans (for example a first mortgage and a HELOC). Each Loan has its own schedule.
- Loan data is scoped to the authenticated user and to one Property, like Depreciable_Assets.

## Glossary

- **Logstead**: The rental-property Schedule E tracking application.
- **Loan_Service**: The backend service that owns Loan create, list, get, update, and delete, and the schedule computation.
- **Loan**: A mortgage or similar loan belonging to one Property, with an original principal, annual interest rate, term in months, and first payment date.
- **Property**: A rental unit that is one column of Schedule E Part I.
- **Original_Principal**: The amount borrowed, as a positive two-decimal Decimal.
- **Annual_Interest_Rate**: The nominal annual rate as a percentage Decimal with at most four decimal places (for example 6.875).
- **Term_Months**: The number of monthly payments used to amortize the Loan, as a positive whole number.
- **First_Payment_Date**: The ISO-8601 date (YYYY-MM-DD) of the first scheduled payment. Later payments fall on the same day of each following month, clamped to the last day of shorter months.
- **Scheduled_Payment**: The principal-and-interest amount due each month. Defaults to the standard level payment computed from the Original_Principal, rate, and Term_Months, rounded half-up to the cent.
- **Payment_Override**: An optional user-supplied Scheduled_Payment that replaces the computed default.
- **Extra_Principal**: An optional fixed two-decimal amount added to principal with every payment.
- **Payoff_Date**: An optional date on which the Loan ends early (paid off or refinanced). No payment is generated after the Payoff_Date.
- **Closing_Date**: An optional informational date on which the Loan originated. The Closing_Date does not affect computation.
- **Payment_Row**: One scheduled payment with its payment number, date, payment amount, interest portion, principal portion, and remaining balance.
- **Amortization_Schedule**: The ordered list of Payment_Rows for a Loan.
- **Yearly_Rollup**: For one Loan and tax year, the sum of interest, the sum of principal, the sum of payments, and the ending balance of the Payment_Rows dated in that year.
- **Interest_Override**: An optional user-supplied interest amount for one Loan and one tax year, entered to match Form 1098.
- **Effective_Interest**: For one Loan and tax year, the Interest_Override when one exists, otherwise the Yearly_Rollup interest.
- **Report_Inclusion**: A per-Loan flag, default on, that controls whether the Loan's Effective_Interest feeds Schedule E Line 12.
- **Manual_Mortgage_Interest**: The total of the user's expense transactions in the `mortgage-interest-banks` category (Schedule E Line 12) for a Property and tax year.
- **Reporting_Service**: The existing `ReportingService` that builds per-property and combined Schedule E reports.
- **Schedule_E_Report**: The per-property report with Part I line totals, total income, total expenses, and net.
- **Combined_Report**: The portfolio report that sums per-property Schedule_E_Reports.
- **Form_1098**: The IRS Mortgage Interest Statement that the lender issues each year.
- **Backup_Service**: The existing service that exports and restores the user's data as a backup document.
- **Loans_Page**: The frontend page for a Property that lists Loans and shows the Amortization_Schedule.
- **Whole_Dollar_Format**: The existing `formatMoneyWholeDollars` display that renders money as whole dollars.

## Requirements

### Requirement 1: Create and manage Loans

**User Story:** As a landlord, I want to record the terms of a mortgage on a property, so that Logstead can generate its amortization schedule for me.

#### Acceptance Criteria

1. WHEN a valid Loan is submitted for a Property owned by the authenticated user, THE Loan_Service SHALL persist the Loan with a generated unique id and created and updated timestamps, generate the Amortization_Schedule, and return the persisted Loan.
2. THE Loan_Service SHALL require a description of 1 to 200 characters, an Original_Principal, an Annual_Interest_Rate, a Term_Months, and a First_Payment_Date for every Loan.
3. IF a required Loan field is missing or a description is empty or longer than 200 characters, THEN THE Loan_Service SHALL return a validation failure identifying each offending field and SHALL NOT persist or modify any Loan.
4. IF the Original_Principal is zero, negative, greater than 999,999,999.99, or has more than two decimal places, THEN THE Loan_Service SHALL return a validation failure on the original principal field and SHALL NOT persist or modify any Loan.
5. IF the Annual_Interest_Rate is negative, is greater than 100, or has more than four decimal places, THEN THE Loan_Service SHALL return a validation failure on the interest rate field and SHALL NOT persist or modify any Loan.
6. IF the Term_Months is not a whole number between 1 and 600 inclusive, THEN THE Loan_Service SHALL return a validation failure on the term field and SHALL NOT persist or modify any Loan.
7. IF the First_Payment_Date is not a valid ISO-8601 calendar date (YYYY-MM-DD), THEN THE Loan_Service SHALL return a validation failure on the first payment date field and SHALL NOT persist or modify any Loan.
8. IF a Payoff_Date is supplied and is earlier than the First_Payment_Date, THEN THE Loan_Service SHALL return a validation failure on the payoff date field and SHALL NOT persist or modify any Loan.
9. IF a Closing_Date is supplied and is later than the First_Payment_Date, THEN THE Loan_Service SHALL return a validation failure on the closing date field and SHALL NOT persist or modify any Loan.
10. THE Loan_Service SHALL allow any number of Loans under one Property.
11. WHEN the user lists Loans for a Property, THE Loan_Service SHALL return only the Loans of that Property that belong to the authenticated user, or an empty list if there are none.
12. WHEN the user updates an existing Loan with valid input, THE Loan_Service SHALL re-validate the input with the same rules as create, preserve the Loan id and created timestamp, set the updated timestamp to the time of the update, and regenerate the Amortization_Schedule.
13. WHEN the user deletes an existing Loan, THE Loan_Service SHALL delete the Loan, its Interest_Overrides, and its stored yearly schedule rows in one atomic operation, such that either all are removed or none are.
14. IF a Loan is requested for read, update, or delete by an id that does not exist under the given Property for the authenticated user, THEN THE Loan_Service SHALL return a not-found failure and SHALL NOT modify any data.
15. IF persisting, updating, or deleting a Loan fails for a reason other than validation or not-found, THEN THE Loan_Service SHALL return an error indicating the operation failed and SHALL leave previously stored Loan data unchanged.

### Requirement 2: Payment inputs and early payoff

**User Story:** As a landlord, I want to enter my actual monthly payment, extra principal, or payoff date, so that the schedule matches how I really pay the loan.

#### Acceptance Criteria

1. WHERE no Payment_Override is supplied, THE Loan_Service SHALL set the Scheduled_Payment to the standard level payment for the Original_Principal, Annual_Interest_Rate, and Term_Months, rounded half-up to the cent.
2. WHERE the Annual_Interest_Rate is zero and no Payment_Override is supplied, THE Loan_Service SHALL set the Scheduled_Payment to the Original_Principal divided by Term_Months, rounded half-up to the cent.
3. WHERE a Payment_Override is supplied, THE Loan_Service SHALL use the Payment_Override as the Scheduled_Payment without rounding or modification, provided it passes the validation in criterion 4.
4. IF a Payment_Override is zero, negative, or less than or equal to the interest due on the first payment, THEN THE Loan_Service SHALL reject the request, return a validation failure identifying the payment field, and leave any previously stored Loan and schedule unchanged.
5. WHERE an Extra_Principal is supplied, THE Loan_Service SHALL add the Extra_Principal to the principal portion of every Payment_Row until the balance reaches zero, and SHALL limit the final Payment_Row so that the total principal paid does not exceed the remaining balance.
6. IF an Extra_Principal is negative, THEN THE Loan_Service SHALL reject the request, return a validation failure identifying the extra principal field, and leave any previously stored Loan and schedule unchanged.
7. WHERE a Payoff_Date is supplied, THE Loan_Service SHALL generate no Payment_Row dated after the Payoff_Date, and SHALL include a Payment_Row dated exactly on the Payoff_Date.
8. WHERE a Payoff_Date is supplied and the balance remains positive after the last Payment_Row on or before the Payoff_Date, THE Loan_Service SHALL report that remaining balance, to the cent, as the payoff balance of the Loan.
9. THE Loan_Service SHALL treat Scheduled_Payment as principal and interest only and SHALL NOT include escrow amounts.
10. IF a Payoff_Date is earlier than the date of the first Payment_Row, THEN THE Loan_Service SHALL reject the request, return a validation failure identifying the payoff date field, and leave any previously stored Loan and schedule unchanged.

### Requirement 3: Amortization schedule generation

**User Story:** As a landlord, I want a correct month-by-month amortization table, so that I can see how much of each payment is interest and principal.

#### Acceptance Criteria

1. WHEN an Amortization_Schedule is requested for a valid Loan, THE Loan_Service SHALL generate one Payment_Row per calendar month starting on the First_Payment_Date, numbered from 1 in ascending date order, with a maximum of Term_Months Payment_Rows.
2. WHEN a Payment_Row is generated, THE Loan_Service SHALL compute the interest portion as the balance before the payment multiplied by the Annual_Interest_Rate divided by 100 and divided by 12, rounded half-up to 2 decimal places (the cent).
3. WHEN a Payment_Row is generated, THE Loan_Service SHALL compute the principal portion as the Scheduled_Payment plus any Extra_Principal for that row minus the interest portion, limited to a maximum equal to the balance before the payment and to a minimum of 0.00.
4. WHEN the balance before a payment plus that payment's interest is less than or equal to the Scheduled_Payment plus any Extra_Principal, THE Loan_Service SHALL set that Payment_Row as the final payment, with a principal portion equal to the balance before the payment, a payment amount equal to that principal plus the interest, an ending balance of 0.00, and SHALL generate no further Payment_Rows.
5. WHEN the Term_Months-th Payment_Row is generated and a balance remains because of rounding, THE Loan_Service SHALL set the principal portion of that row to the balance before the payment and the payment amount to that principal plus the interest, so that the ending balance equals 0.00.
6. THE Loan_Service SHALL perform all schedule arithmetic using Decimal values rounded half-up to 2 decimal places at each Payment_Row and SHALL NOT use floating-point arithmetic.
7. FOR ALL valid Loans, THE Loan_Service SHALL produce Payment_Rows in which the interest portion plus the principal portion equals the payment amount.
8. FOR ALL valid Loans without a Payoff_Date, THE Loan_Service SHALL produce Payment_Rows whose principal portions sum exactly to the Original_Principal and whose final remaining balance equals 0.00.
9. FOR ALL valid Loans with a Payoff_Date, THE Loan_Service SHALL produce Payment_Rows whose principal portions plus the payoff balance equal the Original_Principal.
10. FOR ALL valid Loans, THE Loan_Service SHALL produce Payment_Rows whose remaining balance is non-increasing from one row to the next and is never less than 0.00.
11. FOR ALL valid Loans, THE Loan_Service SHALL produce an identical Amortization_Schedule (same row count and identical values in every field of every row) when computed twice from identical inputs.
12. WHERE the Annual_Interest_Rate is 0, THE Loan_Service SHALL set the interest portion of every Payment_Row to 0.00.
13. IF the Loan inputs are invalid (for example, Term_Months less than 1, Original_Principal less than or equal to 0.00, or Annual_Interest_Rate below 0), THEN THE Loan_Service SHALL reject the request with an error indicating which input is invalid and SHALL NOT produce an Amortization_Schedule.

### Requirement 4: Yearly rollups and partial years

**User Story:** As a landlord, I want yearly interest and principal totals, so that I can match them to the tax year and to my Form 1098.

#### Acceptance Criteria

1. WHEN a Loan's Payment_Rows are generated, THE Loan_Service SHALL compute exactly one Yearly_Rollup for each tax year in which the Loan has at least one Payment_Row, and SHALL compute no Yearly_Rollup for any tax year in which the Loan has zero Payment_Rows.
2. THE Loan_Service SHALL attribute each Payment_Row to the calendar tax year (January 1 through December 31) of its payment date, such that each Payment_Row belongs to exactly one Yearly_Rollup.
3. FOR ALL valid Loans, THE Loan_Service SHALL produce a Yearly_Rollup interest equal to the sum of the interest portions of the Payment_Rows dated in that year, rounded to 2 decimal places, with a tolerance of 0.00.
4. FOR ALL valid Loans, THE Loan_Service SHALL produce Yearly_Rollups whose principal sums, added across all years, equal the sum of all Payment_Row principal portions, rounded to 2 decimal places, with a tolerance of 0.00.
5. THE Loan_Service SHALL set the ending balance of each Yearly_Rollup to the remaining balance of the last Payment_Row dated in that year, expressed to 2 decimal places.
6. WHEN the First_Payment_Date falls after January 31, THE Loan_Service SHALL produce a first-year Yearly_Rollup that contains only the Payment_Rows dated in that year, with no interest or principal prorated or added for months before the First_Payment_Date.
7. WHEN the final Payment_Row is dated before December 1, THE Loan_Service SHALL produce a last-year Yearly_Rollup that contains only the Payment_Rows dated in that year, with an ending balance of 0.00.
8. WHEN a tax year has no Payment_Row for a Loan, THE Loan_Service SHALL report 0.00 interest and 0.00 principal for that Loan and tax year, including for tax years between the first and last Payment_Row years and for tax years outside the Loan's payment span.
9. WHEN a Loan is created or updated, THE Loan_Service SHALL store its Yearly_Rollups so that the total Effective_Interest for a Property and a single tax year is readable with one tax-year query, and SHALL replace all previously stored Yearly_Rollups for that Loan so that no stale rollups remain.
10. IF storing the Yearly_Rollups fails when a Loan is created or updated, THEN THE Loan_Service SHALL return an error indicating that the rollups were not saved and SHALL retain the Loan's previously stored Yearly_Rollups unchanged.

### Requirement 5: Interest override to match Form 1098

**User Story:** As a landlord, I want to enter the interest my lender reported for a year, so that my Schedule E uses the authoritative figure instead of the estimate.

#### Acceptance Criteria

1. WHERE the user supplies a valid Interest_Override for a Loan and tax year, THE Loan_Service SHALL use the Interest_Override as the Effective_Interest for that Loan and tax year.
2. WHEN an Interest_Override is created, changed, or removed, THE Loan_Service SHALL leave every Payment_Row, every balance, and every principal total for the Loan identical to its value before the change.
3. IF an Interest_Override is negative, has more than two decimal places, or is not a numeric value, THEN THE Loan_Service SHALL reject the request with a validation failure on the field identifying that tax year, and SHALL retain the previously stored Interest_Override for that tax year, if any.
4. IF an Interest_Override is supplied for a tax year in which the Loan has no Payment_Row, THEN THE Loan_Service SHALL reject the request with a validation failure on the field identifying that tax year, and SHALL store no Interest_Override for that tax year.
5. WHEN the user removes an Interest_Override, THE Loan_Service SHALL revert the Effective_Interest for that Loan and tax year to the Yearly_Rollup interest.
6. WHEN an Interest_Override exists for a Loan and tax year, THE Loan_Service SHALL expose the estimate variance for that tax year as the Interest_Override minus the Yearly_Rollup interest, as a signed two-decimal money string (negative when the Interest_Override is lower than the Yearly_Rollup interest).
7. WHEN the Loan is updated so that a tax year no longer has a Payment_Row, THE Loan_Service SHALL delete the Interest_Override for that tax year and SHALL retain the Interest_Overrides for all other tax years.
8. THE Loan_Service SHALL store each Interest_Override as a money string with exactly two decimal places, including a value of zero stored as "0.00".

### Requirement 6: Schedule E Line 12 integration and double-counting prevention

**User Story:** As a landlord, I want generated mortgage interest to fill Line 12 without being added on top of interest I already entered by hand, so that my deduction is not double counted.

#### Acceptance Criteria

1. WHEN a Schedule_E_Report is built for a Property and tax year, and at least one Loan of that Property with Report_Inclusion on has Effective_Interest greater than 0.00 in that year, THE Reporting_Service SHALL set the Line 12 total to the sum of the Effective_Interest of every Loan of that Property with Report_Inclusion on, rounded to 2 decimal places.
2. WHEN a Property and tax year has at least one Loan with Report_Inclusion on and Effective_Interest greater than 0.00, THE Reporting_Service SHALL exclude Manual_Mortgage_Interest from the Line 12 total.
3. WHEN Manual_Mortgage_Interest is excluded from Line 12, THE Reporting_Service SHALL include in the Schedule_E_Report a superseded-manual-interest figure containing the excluded amount (2 decimal places) and the count of excluded transactions (integer, 0 or greater).
4. WHEN a Property and tax year has no Loan with Report_Inclusion on and Effective_Interest greater than 0.00, THE Reporting_Service SHALL set the Line 12 total to Manual_Mortgage_Interest, identical to the behavior before this feature, and SHALL report the superseded-manual-interest amount as 0.00 and the count as 0.
5. THE Reporting_Service SHALL identify the source of the Line 12 total in the Schedule_E_Report as exactly one of two values: loan-generated or transaction-entered.
6. WHERE a Loan has Report_Inclusion off, THE Reporting_Service SHALL exclude that Loan from the Line 12 total and from the precedence decision in this requirement, regardless of that Loan's Effective_Interest.
7. THE Reporting_Service SHALL include Line 12 in total expenses, so that net equals total income minus total expenses with loan-generated interest included.
8. THE Reporting_Service SHALL leave the Line 13 (Other interest) total unaffected by Loans.
9. WHEN a Combined_Report is built, THE Reporting_Service SHALL set each per-property Line 12 column by the rules in this requirement and SHALL set the portfolio Line 12 total to the sum of the per-property Line 12 totals, with the same equality holding for the superseded-manual-interest amount and count.
10. WHEN a Schedule_E_Report or a Combined_Report is exported to CSV or JSON, THE Reporting_Service SHALL output the same Line 12 total, Line 12 source, and superseded-manual-interest figure as shown in the on-screen report, with no difference in value at 2 decimal places.
11. WHEN the passive-loss carryforward is computed for a tax year, THE Reporting_Service SHALL supply the net that includes loan-generated Line 12 interest to the carryforward calculation.
12. FOR ALL Properties and tax years, THE Reporting_Service SHALL produce a Line 12 total that equals either the sum of Effective_Interest over included Loans or Manual_Mortgage_Interest, and never the sum of both.
13. FOR ALL Properties and tax years, THE Reporting_Service SHALL produce a Schedule_E_Report that is identical when built twice from the same stored data.

### Requirement 7: Payoff and refinance

**User Story:** As a landlord, I want to end a loan when I pay it off or refinance, so that my reports stay accurate across the change.

#### Acceptance Criteria

1. WHEN the user sets a Payoff_Date on a Loan, THE Loan_Service SHALL regenerate the Amortization_Schedule and Yearly_Rollups for that Loan so that no Payment_Row is dated after the Payoff_Date and the Payment_Row dated on the Payoff_Date, if any, is retained.
2. WHEN a Payoff_Date shortens a Loan, THE Loan_Service SHALL remove stored Yearly_Rollups for tax years after the Payoff_Date year and SHALL drop Interest_Overrides for those years.
3. WHEN the user clears a Payoff_Date, THE Loan_Service SHALL regenerate the full Amortization_Schedule and Yearly_Rollups from the Loan inputs, through the original final payment date.
4. WHEN the user creates a new Loan under a Property that has an earlier Loan with a Payoff_Date, THE Loan_Service SHALL generate the new Loan's Amortization_Schedule independently of the earlier Loan, so that the earlier Loan's Payment_Rows, Yearly_Rollups and Interest_Overrides remain unchanged.
5. WHEN two Loans of one Property have Payment_Rows in the same tax year, THE Reporting_Service SHALL sum their Effective_Interest into the Line 12 total for that year, so that the Line 12 total equals the sum of each Loan's Effective_Interest for that year.
6. IF the user sets a Payoff_Date that is earlier than the Loan's first payment date, THEN THE Loan_Service SHALL reject the change, display an error message indicating the Payoff_Date precedes the first payment date, and SHALL leave the existing Amortization_Schedule, Yearly_Rollups and Interest_Overrides unchanged.
7. IF regeneration of the Amortization_Schedule or Yearly_Rollups fails after the user sets or clears a Payoff_Date, THEN THE Loan_Service SHALL display an error message indicating the regeneration failed and SHALL restore the Payoff_Date, Amortization_Schedule, Yearly_Rollups and Interest_Overrides to their values before the change.

### Requirement 8: Loans API

**User Story:** As a frontend developer, I want a consistent API for Loans, so that the UI can manage them like other property resources.

#### Acceptance Criteria

1. WHEN an authenticated user submits a create, list, get, update, or delete request for a Loan under `/properties/{propertyId}/loans` for a Property the user owns, THE Logstead SHALL perform the requested operation and return a success response containing the resulting Loan, the list of Loans for that Property, or an empty confirmation for delete.
2. WHEN an authenticated user requests the Amortization_Schedule for a Loan under the Loan's resource path, THE Logstead SHALL return the Payment_Rows ordered by payment date ascending and the Yearly_Rollups ordered by tax year ascending.
3. WHEN an authenticated user submits a set request for an Interest_Override for a Loan and a tax year under the Loan's resource path, THE Logstead SHALL store the override, and the next Amortization_Schedule response for that Loan SHALL reflect it in the Yearly_Rollup for that tax year.
4. WHEN an authenticated user submits a remove request for an Interest_Override for a Loan and a tax year under the Loan's resource path, THE Logstead SHALL delete the override, and the next Amortization_Schedule response for that Loan SHALL reflect the calculated interest for that tax year.
5. THE Logstead SHALL serialize every money value in Loan API responses as a decimal string with exactly two digits after the decimal point.
6. THE Logstead SHALL serialize the Annual_Interest_Rate as a decimal string and SHALL NOT convert the Annual_Interest_Rate to a floating-point number at any point between request parsing and response serialization.
7. IF a request references a Property that does not exist or does not belong to the authenticated user, THEN THE Logstead SHALL return a not-found response that is identical in status and body for both cases, and SHALL NOT change any stored data.
8. IF a request references a Loan that does not exist under the specified Property, THEN THE Logstead SHALL return a not-found response and SHALL NOT change any stored data.
9. IF a Loan request fails validation, THEN THE Logstead SHALL reject the request, return a validation error response that names each offending field using the existing error shape, and SHALL leave stored data unchanged.
10. WHEN a valid Loan payload is serialized by the API and parsed again, THE Logstead SHALL produce a Loan equal to the original in every field, including the exact Annual_Interest_Rate decimal value and every money value to two decimal places (round-trip property).

### Requirement 9: Loans page and amortization table

**User Story:** As a landlord, I want to enter a loan and see its amortization, so that I can understand and verify the interest on my Schedule E.

#### Acceptance Criteria

1. THE Loans_Page SHALL provide a form to create and edit a Loan with fields for description (1 to 200 characters), Original_Principal, Annual_Interest_Rate, Term_Months, First_Payment_Date, and the optional Payment_Override, Extra_Principal, Closing_Date, Payoff_Date, and Report_Inclusion.
2. WHEN the user enters a valid Original_Principal, Annual_Interest_Rate, and Term_Months, THE Loans_Page SHALL display the computed default Scheduled_Payment within 500 milliseconds and before the user submits.
3. IF the user enters an Original_Principal, Annual_Interest_Rate, or Term_Months that is missing or invalid, THEN THE Loans_Page SHALL hide the computed default Scheduled_Payment and SHALL NOT display a stale value.
4. IF the API rejects a submitted Loan with a validation error that names a field, THEN THE Loans_Page SHALL show the validation message next to that field, SHALL retain all values the user entered, and SHALL NOT add the Loan to the list.
5. IF the API rejects a submitted Loan with an error that names no field or the request fails, THEN THE Loans_Page SHALL show an error message at the form level, SHALL retain all values the user entered, and SHALL NOT add or change the Loan in the list.
6. THE Loans_Page SHALL list the Loans of the Property with each Loan's description, Original_Principal, rate, term, and current status (active or ended).
7. WHILE a Property has no Loans, THE Loans_Page SHALL display an empty-state message and the control to create a Loan.
8. WHEN the user selects a Loan, THE Loans_Page SHALL display a Yearly_Rollup table with columns for tax year, interest, principal, total paid, and ending balance, with one row per tax year in which the Loan has at least one payment.
9. THE Loans_Page SHALL render Yearly_Rollup money values in Whole_Dollar_Format.
10. WHEN the user expands a tax year in the Yearly_Rollup table, THE Loans_Page SHALL display that year's Payment_Rows with payment number, date, payment, interest, principal, and balance.
11. THE Loans_Page SHALL render Payment_Row money values to the cent.
12. WHEN the user sets an Interest_Override for a tax year of a Loan, THE Loans_Page SHALL save it, SHALL display the estimate variance (override minus estimated interest) next to that year, and SHALL update the Yearly_Rollup row.
13. WHEN the user removes an Interest_Override for a tax year, THE Loans_Page SHALL restore the estimated interest for that year and SHALL remove the estimate variance display for it.
14. IF the user enters an Interest_Override that is negative or not a number, THEN THE Loans_Page SHALL show a validation message next to the override field and SHALL NOT save the override.
15. THE Loans_Page SHALL display a notice that the schedule is an estimate and that the user should reconcile the figures with Form_1098.
16. WHEN a Property has Manual_Mortgage_Interest superseded by Loan-generated interest in a tax year, THE Loans_Page SHALL display a notice that states the tax year, states the superseded amount in Whole_Dollar_Format, and tells the user to turn Report_Inclusion off to restore the manual figures.
17. WHEN the user confirms deletion of a Loan, THE Loans_Page SHALL call the delete operation and, on success, remove the Loan from the list and clear its Yearly_Rollup display.
18. IF the delete operation fails, THEN THE Loans_Page SHALL keep the Loan in the list and show an error message indicating the deletion failed.
19. THE Loans_Page SHALL be reachable from the Property navigation using the same pattern as the depreciable assets page.
20. THE Loans_Page SHALL expose every form control, button, and table header with an accessible name, and SHALL allow every action on the page to be completed using only the keyboard.

### Requirement 10: Report display of Line 12 source

**User Story:** As a landlord, I want the report to show where Line 12 came from, so that I trust the number and can spot a mismatch with my manual entries.

#### Acceptance Criteria

1. WHEN the Schedule_E_Report view is rendered for a Property and tax year whose Line 12 total is loan-generated, THE Schedule_E_Report view SHALL display a text label adjacent to the Line 12 amount identifying the amount as loan-generated.
2. WHEN the Schedule_E_Report view is rendered for a Property and tax year in which Manual_Mortgage_Interest is superseded, THE Schedule_E_Report view SHALL display the superseded Manual_Mortgage_Interest total, in US dollars with two decimal places, on the same row as Line 12, distinguishable from the Line 12 amount by a text label identifying it as superseded.
3. WHEN the Schedule_E_Report view is rendered for a Property and tax year whose Line 12 total is transaction-entered, THE Schedule_E_Report view SHALL display the Line 12 amount with no loan-generated label and no superseded amount, identical to the behavior before this feature.
4. WHEN the Schedule_E_Report view is rendered for a Property and tax year with no loan-generated amount and no Manual_Mortgage_Interest, THE Schedule_E_Report view SHALL display Line 12 as 0.00 with no loan-generated label and no superseded amount.
5. IF the Line 12 source or superseded amount cannot be determined when the Schedule_E_Report view is rendered, THEN THE Schedule_E_Report view SHALL display the Line 12 amount without a source label or superseded amount and SHALL display an error indication that the Line 12 source is unavailable.

### Requirement 11: Backup and restore

**User Story:** As a landlord, I want my loans included in backups, so that a restore reproduces my mortgage data and reports.

#### Acceptance Criteria

1. WHEN a backup is exported, THE Backup_Service SHALL include, for each Property, every Loan belonging to that Property, each Loan's inputs, and each Loan's Interest_Overrides in the backup document, with every money value represented as a string with exactly two decimal places.
2. THE Backup_Service SHALL exclude stored Yearly_Rollup rows and Payment_Rows from the backup document.
3. WHEN a backup that contains Loans is restored, THE Backup_Service SHALL preserve each Loan's original id, created timestamp, and updated timestamp, and SHALL recompute the Amortization_Schedule and Yearly_Rollups for each restored Loan before the restore completes.
4. WHEN a backup document that contains no Loans is restored, THE Backup_Service SHALL restore all remaining data in the document, create zero Loans, and report a restored Loan count of 0 in the restore summary.
5. WHEN a backup is exported, restored into an empty account, and exported again, THE Backup_Service SHALL produce a second export whose Loan content (ids, timestamps, inputs, and Interest_Overrides) is identical to the first export's Loan content.
6. IF a Loan in a backup document fails the Loan validation rules, THEN THE Backup_Service SHALL reject the entire restore, persist no data from the backup document (leaving the account state unchanged), and return an error indicating the Property and the Loan that failed and the validation rule violated.
7. WHEN a restore completes successfully, THE Backup_Service SHALL include in the restore summary the total number of Loans restored, equal to the number of Loans in the backup document.

### Requirement 12: Storage and documentation

**User Story:** As a maintainer, I want Loan storage to follow the existing single-table conventions, so that the code stays consistent and the model is documented.

#### Acceptance Criteria

1. WHEN a Loan is created, updated, read, or deleted, THE Logstead SHALL store and address the Loan under its Property's partition using only key builders defined in `repository/keys.py`, and no service module SHALL construct a partition key or sort key string directly.
2. WHEN a Loan's Yearly_Rollup is generated, THE Logstead SHALL store one row per tax year under the Loan's key prefix, each with a GSI2 tax-year key, following the depreciation schedule row pattern.
3. WHEN a Loan is stored, THE Logstead SHALL persist every Loan money value as a decimal string with exactly two digits after the decimal point, and SHALL persist the Annual_Interest_Rate as a decimal string.
4. WHEN a Property's Loans are listed, THE Logstead SHALL return only Loan rows and zero Yearly_Rollup rows.
5. WHEN a Property's depreciable assets are listed, THE Logstead SHALL return only depreciable asset rows and zero Loan rows or Loan Yearly_Rollup rows.
6. IF a stored Loan money value cannot be parsed as a two-decimal string or the Annual_Interest_Rate cannot be parsed as a decimal string when read, THEN THE Logstead SHALL reject the read with an error indicating the invalid field and SHALL leave the stored data unchanged.
7. THE Logstead SHALL document in `docs/data-model.md` the Loan entity, its key prefixes, the Line 12 precedence rule, and the backup treatment, with each of these four topics under its own heading.
