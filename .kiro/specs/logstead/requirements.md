# Requirements Document

## Introduction

Logstead is a property management application for a single-member LLC that owns and rents residential real estate. The initial version targets a small landlord (currently 2 rental properties) and prioritizes simplicity. The application focuses on two core outcomes:

1. **Schedule E preparation** — collecting income and expense data throughout the year, categorized to the exact line items on IRS Schedule E (Form 1040), so that year-end tax filing is straightforward.
2. **Depreciation tracking** — recording depreciable assets (buildings, capital improvements) and computing straight-line depreciation schedules that feed the Schedule E depreciation line.

The initial release is scoped **strictly to what is needed to prepare a federal tax return for the rental activity**. In practice this means the income and expenses reported on IRS Schedule E, the depreciation schedule that feeds Schedule E, and the supporting property data required to complete the form. Capabilities that are not directly required to produce the federal tax return are deferred to future releases and are documented in the "Out of Scope (Future Releases)" section below.

The application is single-user and single-LLC for the initial release, but the data model must allow adding more properties over time. The interface should be clean and modern, comparable in feel to consumer finance apps such as Monarch Money. This document defines the functional and quality requirements for the initial release; technical design decisions are deferred to the design phase.

## Glossary

- **Logstead**: The overall property management application described by this document. Used as the system name in ubiquitous requirements.
- **User**: The single authenticated person who owns and operates the LLC and uses Logstead.
- **Identity_Provider**: The external managed authentication service (Amazon Cognito) that authenticates the User and issues tokens to Logstead.
- **Hosted_Sign_In**: The Identity_Provider's hosted sign-in page, where the User enters credentials and is authenticated.
- **LLC**: The single legal entity (limited liability company) that owns the rental properties tracked in Logstead.
- **Property**: A single rental real estate unit or building tracked in Logstead, corresponding to one column of Schedule E Part I. Attributes include a name, physical address, and property type.
- **Property_Type**: The IRS-defined use classification for a Property (for example, residential rental, or land). Determines the applicable depreciation recovery period.
- **Transaction**: A single dated financial record associated with a Property, representing either income received or an expense paid.
- **Transaction_Category**: The classification assigned to a Transaction that maps it to a specific Schedule E line item.
- **Schedule_E_Line**: A specific numbered line on IRS Schedule E (Form 1040), Part I, such as Line 3 (Rents received) or Line 14 (Repairs).
- **Depreciable_Asset**: A capitalized item associated with a Property that is recovered over multiple tax years through depreciation (for example, the building itself, a roof replacement, or an appliance).
- **Depreciation_Schedule**: The year-by-year set of depreciation amounts computed for a Depreciable_Asset over its recovery period.
- **Cost_Basis**: The depreciable dollar amount of a Depreciable_Asset, excluding non-depreciable components such as land.
- **Recovery_Period**: The number of years over which a Depreciable_Asset is depreciated (for example, 27.5 years for residential rental buildings).
- **Placed_In_Service_Date**: The date a Depreciable_Asset began being used in the rental activity, which determines the first depreciation year and the applicable convention.
- **Mid_Month_Convention**: The IRS convention for real property under which an asset is treated as placed in service in the middle of the month, prorating the first and final year of depreciation.
- **Tax_Year**: A calendar year for which income, expenses, and depreciation are aggregated for reporting.
- **Schedule_E_Report**: A per-Property, per-Tax_Year summary that aggregates categorized Transactions and depreciation into Schedule E line-item totals.
- **Fair_Rental_Days**: The number of days in a Tax_Year that a Property was rented at fair rental value, reported in the Schedule E property header.
- **Personal_Use_Days**: The number of days in a Tax_Year that a Property was used for personal purposes, reported in the Schedule E property header.
- **RentCast**: The external property data provider (rentcast.io) whose API Logstead calls to retrieve a Property_Record for a selected address.
- **Property_Record**: The set of property data returned by RentCast for a given address, used to prefill Property_Details.
- **Property_Details**: The standard descriptive attributes of a Property sourced from a RentCast Property_Record where available (for example, formatted address, address components, geographic coordinates, property type, bedroom and bathroom counts, living area square footage, lot size, year built, and property features). Individual Property_Details fields are populated only when RentCast provides them.
- **Address_Suggestion**: A candidate address presented by Logstead as the User types a Property address, used to select the address for a RentCast lookup.
- **Property_Photo**: An image file uploaded by the User and associated with a Property to augment the RentCast-sourced Property_Details, since RentCast Property_Records do not include photos.
- **Expense_Summary**: A PDF document produced by a property manager that lists a Property's expense line items for a Tax_Year, uploaded by the User to prepopulate expense Transactions.
- **Draft_Transaction**: A provisional, uncommitted Transaction candidate parsed from an Expense_Summary and held for User review. A Draft_Transaction is not a Transaction until the User confirms it, at which point Logstead creates a corresponding Transaction.

## Requirements

### Requirement 1: User Authentication

**User Story:** As the LLC owner, I want to sign in to Logstead through a managed identity provider, so that my financial records are private and accessible only to me and my credentials are secured by the provider rather than stored by Logstead.

#### Acceptance Criteria

1. WHEN an unauthenticated User requests any page other than the sign-in entry point, THE Logstead SHALL redirect the User to the Identity_Provider's Hosted_Sign_In page.
2. WHEN the Identity_Provider authenticates the User and returns to Logstead with a valid authentication result, THE Logstead SHALL establish an authenticated session and display the dashboard.
3. IF authentication fails or is denied at the Identity_Provider, THEN THE Logstead SHALL not establish a session and SHALL return the User to the sign-in entry point with an authentication error message.
4. WHEN an authenticated User requests to sign out, THE Logstead SHALL terminate the local session, sign the User out of the Identity_Provider session, and return the User to the sign-in entry point.
5. THE Logstead SHALL delegate credential storage and verification to the Identity_Provider and SHALL NOT store User passwords.
6. THE Logstead SHALL authorize access to the Logstead API using the tokens issued by the Identity_Provider.

### Requirement 2: Property Management

**User Story:** As the LLC owner, I want to add and maintain my rental properties, so that I can track income, expenses, and depreciation separately for each one.

#### Acceptance Criteria

1. WHEN a User submits a new Property with a name, address, and Property_Type, THE Logstead SHALL create the Property and associate the Property with the LLC.
2. IF a User submits a new Property with an empty name or empty address, THEN THE Logstead SHALL reject the submission and display a validation message identifying the missing field.
3. WHEN a User requests the list of Properties, THE Logstead SHALL display all Properties belonging to the LLC.
4. WHEN a User edits an existing Property's name, address, or Property_Type, THE Logstead SHALL save the updated values.
5. THE Logstead SHALL support an unlimited number of Properties per LLC.
6. WHEN a User requests to delete a Property that has no associated Transactions and no associated Depreciable_Assets, THE Logstead SHALL delete the Property.
7. IF a User requests to delete a Property that has one or more associated Transactions or Depreciable_Assets, THEN THE Logstead SHALL reject the deletion and display a message stating that associated records must be removed first.
8. WHERE a User records Fair_Rental_Days and Personal_Use_Days for a Property and a Tax_Year, THE Logstead SHALL store the values and include the values in the Schedule_E_Report property header for that Tax_Year.
9. THE Logstead SHALL store the Property_Details associated with a Property, populating each Property_Details field only when a value is available.

### Requirement 3: Address Autocomplete and RentCast Property Enrichment

**User Story:** As the LLC owner, I want Logstead to look up a property's details automatically when I add it, so that I do not have to type the standard property information by hand.

#### Acceptance Criteria

1. WHILE a User is entering a Property address on the add-Property form, THE Logstead SHALL present Address_Suggestions matching the entered text.
2. WHEN a User selects an Address_Suggestion, THE Logstead SHALL call the RentCast API to retrieve the Property_Record for the selected address.
3. WHEN RentCast returns a Property_Record for the selected address, THE Logstead SHALL prefill the Property_Details from the Property_Record, populating each field only when RentCast provides a value.
4. WHEN the Property_Details are prefilled from a Property_Record, THE Logstead SHALL allow the User to review and edit the prefilled values before saving the Property.
5. IF RentCast returns no matching Property_Record for the selected address, THEN THE Logstead SHALL allow the User to enter the Property_Details manually and display a message that no property data was found.
6. IF the RentCast call fails, THEN THE Logstead SHALL allow the User to enter the Property_Details manually and display a message that property data could not be retrieved.
7. THE Logstead SHALL allow the User to create a Property regardless of RentCast availability.
8. THE Logstead SHALL capture from the Property_Record, where available, the formatted address, address line 1, address line 2, city, state, zip code, county, latitude, longitude, property type, number of bedrooms, number of bathrooms, living area square footage, lot size, year built, and property features including architecture type, heating, cooling, garage, pool, and roof type.

### Requirement 4: Property Photos

**User Story:** As the LLC owner, I want to upload photos of a property, so that I have visual records to augment the data RentCast provides, which does not include photos.

#### Acceptance Criteria

1. WHEN a User uploads one or more image files to a Property, THE Logstead SHALL store each Property_Photo and associate each Property_Photo with the Property.
2. IF a User uploads a file that is not an accepted image type, THEN THE Logstead SHALL reject the upload and display a validation message identifying the accepted image types.
3. WHEN a User requests the Property_Photos for a Property, THE Logstead SHALL display all Property_Photos associated with the Property.
4. WHEN a User requests to delete a Property_Photo, THE Logstead SHALL delete the Property_Photo and remove the association with the Property.

### Requirement 5: Income and Expense Transaction Tracking

**User Story:** As the LLC owner, I want to record income and expense transactions against each property, so that I can capture all financial activity needed for tax reporting.

#### Acceptance Criteria

1. WHEN a User submits a Transaction with a Property, a date, an amount, a type of income or expense, and a Transaction_Category, THE Logstead SHALL create the Transaction and associate the Transaction with the selected Property.
2. IF a User submits a Transaction with an amount less than or equal to zero, THEN THE Logstead SHALL reject the submission and display a validation message.
3. IF a User submits a Transaction without a Property, a date, an amount, or a Transaction_Category, THEN THE Logstead SHALL reject the submission and display a validation message identifying the missing field.
4. WHEN a User requests the Transactions for a Property, THE Logstead SHALL display all Transactions for that Property ordered by date descending.
5. WHERE a User applies a Tax_Year filter to a Transaction list, THE Logstead SHALL display only Transactions whose date falls within the selected Tax_Year.
6. WHEN a User edits an existing Transaction's date, amount, type, or Transaction_Category, THE Logstead SHALL save the updated values.
7. WHEN a User requests to delete a Transaction, THE Logstead SHALL delete the Transaction.
8. WHERE a User attaches a receipt document to a Transaction, THE Logstead SHALL store the document and associate the document with the Transaction.

### Requirement 6: Expense Summary Import

**User Story:** As the LLC owner, I want to import my property manager's yearly expense summary PDF, so that I can prepopulate my expense transactions instead of entering each one by hand.

#### Acceptance Criteria

1. WHEN a User uploads an Expense_Summary PDF and selects a Property and a Tax_Year, THE Logstead SHALL associate the import with the selected Property and Tax_Year.
2. IF the uploaded file is not a PDF, THEN THE Logstead SHALL reject the upload and display a validation message stating that a PDF file is required.
3. WHEN a User uploads a valid Expense_Summary PDF, THE Logstead SHALL parse the Expense_Summary into a set of Draft_Transactions, extracting the date, amount, and description for each line item where available.
4. WHEN Logstead creates a Draft_Transaction from an Expense_Summary line item, THE Logstead SHALL attempt to map the Draft_Transaction to a Schedule E expense Transaction_Category.
5. WHEN Logstead has parsed the Expense_Summary, THE Logstead SHALL present the Draft_Transactions to the User for review before saving.
6. WHILE the User is reviewing Draft_Transactions and has not confirmed them, THE Logstead SHALL NOT create any Transaction from the Draft_Transactions.
7. WHERE a Draft_Transaction is presented for review, THE Logstead SHALL allow the User to edit the Draft_Transaction's date, amount, type, Transaction_Category, and description before confirming.
8. WHERE one or more Draft_Transactions are presented for review, THE Logstead SHALL allow the User to remove one or more Draft_Transactions before confirming.
9. IF a Draft_Transaction is missing a date, an amount, or a Transaction_Category, THEN THE Logstead SHALL flag the Draft_Transaction so that the User completes the missing fields before confirming.
10. WHEN a User confirms the reviewed Draft_Transactions, THE Logstead SHALL create a Transaction for each confirmed Draft_Transaction and associate each Transaction with the selected Property.
11. IF a confirmed Draft_Transaction does not satisfy the Transaction validation rules of Requirement 5, THEN THE Logstead SHALL reject that Draft_Transaction and display a validation message identifying the failing field.
12. IF the Expense_Summary cannot be parsed or yields no line items, THEN THE Logstead SHALL display a message that no transactions could be extracted and allow the User to enter Transactions manually.

### Requirement 7: Schedule E Category Mapping

**User Story:** As the LLC owner, I want each transaction categorized to a Schedule E line, so that year-end totals map directly onto my tax form without manual reclassification.

#### Acceptance Criteria

1. THE Logstead SHALL provide a fixed set of income Transaction_Categories that map to Schedule E Part I income lines, including Rents received (Line 3) and Royalties received (Line 4).
2. THE Logstead SHALL provide a fixed set of expense Transaction_Categories that map to Schedule E Part I expense lines: Advertising (Line 5), Auto and travel (Line 6), Cleaning and maintenance (Line 7), Commissions (Line 8), Insurance (Line 9), Legal and other professional fees (Line 10), Management fees (Line 11), Mortgage interest paid to banks (Line 12), Other interest (Line 13), Repairs (Line 14), Supplies (Line 15), Taxes (Line 16), Utilities (Line 17), and Other (Line 19).
3. WHEN a User assigns a Transaction_Category to a Transaction, THE Logstead SHALL record the mapping between the Transaction and the corresponding Schedule_E_Line.
4. WHERE a User selects the Other expense category (Line 19), THE Logstead SHALL require the User to enter a free-text description of the expense.
5. THE Logstead SHALL exclude the Depreciation line (Line 18) from the user-assignable expense Transaction_Categories.

### Requirement 8: Depreciable Asset Management

**User Story:** As the LLC owner, I want to record depreciable assets for each property, so that I can track my depreciation deductions over time.

#### Acceptance Criteria

1. WHEN a User submits a Depreciable_Asset with a Property, a description, a Cost_Basis, a Placed_In_Service_Date, and a Recovery_Period, THE Logstead SHALL create the Depreciable_Asset and associate the Depreciable_Asset with the selected Property.
2. IF a User submits a Depreciable_Asset with a Cost_Basis less than or equal to zero, THEN THE Logstead SHALL reject the submission and display a validation message.
3. IF a User submits a Depreciable_Asset without a Property, a description, a Cost_Basis, a Placed_In_Service_Date, or a Recovery_Period, THEN THE Logstead SHALL reject the submission and display a validation message identifying the missing field.
4. THE Logstead SHALL offer a Recovery_Period of 27.5 years as the default selection for residential rental building assets.
5. WHEN a User edits an existing Depreciable_Asset's description, Cost_Basis, Placed_In_Service_Date, or Recovery_Period, THE Logstead SHALL save the updated values and recompute the associated Depreciation_Schedule.
6. WHEN a User requests to delete a Depreciable_Asset, THE Logstead SHALL delete the Depreciable_Asset and the associated Depreciation_Schedule.
7. WHEN a User requests the list of Depreciable_Assets for a Property, THE Logstead SHALL display all Depreciable_Assets for that Property.

### Requirement 9: Depreciation Schedule Computation

**User Story:** As the LLC owner, I want Logstead to calculate depreciation automatically, so that I get the correct annual deduction without doing the math by hand.

#### Acceptance Criteria

1. WHEN a Depreciable_Asset is created or updated, THE Logstead SHALL compute a Depreciation_Schedule using the straight-line method over the asset's Recovery_Period.
2. THE Logstead SHALL apply the Mid_Month_Convention when computing the first Tax_Year and final Tax_Year depreciation amounts for each Depreciable_Asset.
3. WHEN Logstead computes a Depreciation_Schedule, THE Logstead SHALL ensure the sum of all annual depreciation amounts equals the asset's Cost_Basis.
4. WHEN a User requests the Depreciation_Schedule for a Depreciable_Asset, THE Logstead SHALL display the depreciation amount and the remaining basis for each Tax_Year in the Recovery_Period.
5. WHEN a User requests the total depreciation for a Property for a given Tax_Year, THE Logstead SHALL return the sum of the annual depreciation amounts of all Depreciable_Assets of that Property for that Tax_Year.

### Requirement 10: Schedule E Report Generation

**User Story:** As the LLC owner, I want a year-end summary organized by Schedule E line, so that I can transfer the totals directly onto my tax return.

#### Acceptance Criteria

1. WHEN a User requests a Schedule_E_Report for a Property and a Tax_Year, THE Logstead SHALL aggregate all Transactions of that Property within that Tax_Year into totals by Schedule_E_Line.
2. WHEN Logstead generates a Schedule_E_Report, THE Logstead SHALL include the Property address, Property_Type, Fair_Rental_Days, and Personal_Use_Days in the report header for the Property and Tax_Year.
3. WHEN Logstead generates a Schedule_E_Report, THE Logstead SHALL populate the Depreciation line (Line 18) with the total Property depreciation for the Tax_Year computed from the Depreciation_Schedules.
4. WHEN Logstead generates a Schedule_E_Report, THE Logstead SHALL compute total income, total expenses, and net income or loss for the Property and Tax_Year.
5. WHERE the Schedule_E_Report includes Other expenses (Line 19), THE Logstead SHALL list each Other expense description with the corresponding amount.
6. WHEN a User requests a combined Schedule_E_Report across all Properties for a Tax_Year, THE Logstead SHALL display per-Property columns and a totals column consistent with the Schedule E form layout.
7. WHERE a User requests to export a Schedule_E_Report, THE Logstead SHALL produce the report as a downloadable file.

### Requirement 11: Dashboard and Financial Overview

**User Story:** As the LLC owner, I want an at-a-glance overview of my portfolio, so that I can quickly understand how my properties are performing.

#### Acceptance Criteria

1. WHEN an authenticated User opens the dashboard, THE Logstead SHALL display total income, total expenses, and net income or loss across all Properties for the current Tax_Year.
2. WHEN an authenticated User opens the dashboard, THE Logstead SHALL display a per-Property summary of income, expenses, and net income or loss for the current Tax_Year.
3. WHERE a User selects a different Tax_Year on the dashboard, THE Logstead SHALL update the displayed totals to reflect the selected Tax_Year.
4. WHILE the LLC has no Properties, THE Logstead SHALL display a prompt guiding the User to add the first Property.

### Requirement 12: Data Model and Schema Extensibility

**User Story:** As the LLC owner, I want the underlying data model to capture the full property and tax data set and to accommodate future record types, so that my current records are complete and future capabilities can be added without a disruptive redesign.

#### Acceptance Criteria

1. THE Logstead SHALL store the full set of Property_Details fields that a RentCast Property_Record can return, including the formatted address, address line 1, address line 2, city, state, zip code, county, latitude, longitude, property type, number of bedrooms, number of bathrooms, living area square footage, lot size, year built, and property features including architecture type, heating, cooling, garage, pool, and roof type.
2. WHEN Logstead stores a Property_Record in which some Property_Details fields are present and others are absent, THE Logstead SHALL persist each present field's value and leave each absent field unset without raising an error.
3. WHEN a User retrieves a Property whose Property_Details were stored from a Property_Record, THE Logstead SHALL return the previously stored present field values unchanged and report absent fields as unset.
4. THE Logstead SHALL store the data required to prepare a federal Schedule E return for the rental activity, comprising categorized income and expense Transactions mapped to their Schedule_E_Lines, Depreciable_Assets and their Depreciation_Schedules, and the per-Property and per-Tax_Year supporting data consisting of Property address, Property_Type, Fair_Rental_Days, and Personal_Use_Days.
5. THE Logstead SHALL retain sufficient stored Transaction, Depreciable_Asset, and Depreciation_Schedule data to reproduce a Schedule_E_Report for any Property and Tax_Year from persisted data alone.
6. THE Logstead SHALL structure the data model so that future record types, specifically repairs, granular day-to-day expenses, and a maintenance and service log, can be added as new record types associated with a Property without altering the stored representation of existing Properties, Transactions, or Depreciable_Assets.
7. THE Logstead SHALL limit the initial-release data model to the Property, Transaction, Depreciable_Asset, Depreciation_Schedule, Property_Details, Property_Photo, and supporting records defined in this document, excluding the future record types identified in the Out of Scope section from current-release functional behavior.

### Requirement 13: Data Persistence and Integrity

**User Story:** As the LLC owner, I want my records stored reliably, so that my financial history is preserved across sessions and over multiple years.

#### Acceptance Criteria

1. WHEN a User creates, updates, or deletes a Property, a Transaction, or a Depreciable_Asset, THE Logstead SHALL persist the change so that the change is present after the User signs out and signs back in.
2. THE Logstead SHALL retain Transactions and Depreciable_Assets for prior Tax_Years without expiration.
3. WHEN Logstead stores a monetary amount, THE Logstead SHALL retain the amount to two decimal places of precision.

### Requirement 14: User Interface Quality

**User Story:** As the LLC owner, I want a clean, modern interface, so that managing my properties feels effortless.

#### Acceptance Criteria

1. THE Logstead SHALL present a consistent navigation structure providing access to the dashboard, Properties, Transactions, Depreciable_Assets, and Schedule_E_Reports.
2. WHERE the viewport width is at least 768 pixels, THE Logstead SHALL present a multi-column layout, and WHERE the viewport width is less than 768 pixels, THE Logstead SHALL present a single-column layout.
3. WHEN a User submission fails validation, THE Logstead SHALL display the validation message adjacent to the field that caused the failure.
4. THE Logstead SHALL meet WCAG 2.1 Level AA success criteria for color contrast and keyboard navigation.

## Out of Scope (Future Releases)

The following capabilities are recognized as potentially valuable but are **explicitly excluded from the initial release**. The initial release is limited to what is needed to prepare the federal tax return for the rental activity. The items below do not drive any acceptance criteria in this document and are recorded here only to capture intent for future planning.

- **Granular ongoing activity logging beyond tax needs**: More frequent or detailed record-keeping (for example, day-to-day operational notes or event streams) that goes beyond the income, expense, and depreciation data required for the federal tax return.
- **Maintenance and service log as first-class records**: Tracking of repairs, appliance service, inspections, and similar maintenance or service events as distinct records with their own lifecycle, separate from tax-deductible expense Transactions. In the initial release, such activity is captured only to the extent that the associated cost is recorded as an expense Transaction categorized to the appropriate Schedule E line.
