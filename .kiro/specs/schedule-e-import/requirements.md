# Requirements Document

## Introduction

Logstead is a single-user (per-authenticated-Cognito-user) serverless application for preparing an IRS Schedule E rental tax return. Logstead does **not** store Schedule E reports: a report is **derived on demand** by the reporting service from stored data — transactions (income lines 3-4, expense lines 5-17 and 19), depreciation schedules (Line 18), and per-year usage days.

This feature, **Schedule E Import**, lets a user backfill prior-year Schedule E data (for example, up to ten years of prior tax returns) so that their historical year-end reports populate. Because reports are derived rather than stored, "importing a Schedule E" means **synthesizing the backing transactions** for a given (property, tax year) that reproduce the Schedule E line totals the user enters.

A real IRS Schedule E Part I has **multiple property columns (A, B, C) on a single page**, so one tax year commonly covers more than one rental property. To mirror that, the v1 input format is a **guided per-tax-year form** that supports **multiple properties in a single import pass**: the user selects a Tax_Year once, then adds one or more property entries. Each property entry has its own set of Schedule E line fields (income lines 3-4, expense lines 5-17, and Line 19 Other) and its own mapping to a Logstead Property — either an existing owned property or one created inline. This single multi-property submission is the **Import_Submission**; each property column within it is a **Property_Entry**. This structure also sets up the deferred "layer 2" extraction feature, whose output will pre-fill this same multi-property form.

The import then writes **one summary transaction per non-zero line, per property entry**, each carrying an **imported marker** so the synthesized entries are always visibly distinct from transactions the user tracks going forward. Re-importing a tax year cleanly **replaces** only the previously-imported summary set for each (property, tax year) **included in the current submission**, and never touches user-tracked transactions.

Line 18 (Depreciation) is **never imported** and the import **never writes any depreciation data** for any property in the submission. Depreciation on the report continues to come only from depreciation schedules, so an imported year shows $0 depreciation for a property until the user creates a depreciation schedule for that property/year.

Every operation in this feature is scoped to the authenticated user's Cognito `sub`, exactly as all existing Logstead domain data is. This feature introduces no change to authentication, identity, tenancy, or how reports are computed beyond consuming the synthesized transactions and surfacing the imported marker.

### Non-Goals (Out of Scope)

The following are explicitly out of scope for this feature and MUST NOT be implemented:

- **Full tax-return PDF upload and automatic extraction** (OCR / document-understanding such as Textract or Bedrock). This is a separate, planned "layer 2" feature whose output will pre-fill THIS feature's multi-property guided form. It is noted only to confirm the form is the stable v1 input surface; no extraction is built here.
- **Importing or synthesizing depreciation, or any Line 18 value.** The import never writes depreciation data for any property.
- **Itemizing imported line amounts into multiple transactions.** The import creates exactly one summary transaction per non-zero line per property entry.
- **CSV or any structured-file upload.** The only v1 input is the guided form.
- **Any change to how reports are computed** beyond consuming the synthesized transactions and surfacing the imported marker.
- **Multi-user / multi-tenant changes.** Data stays per-authenticated-user, like all existing Logstead data.

## Glossary

- **Logstead**: The single-user serverless application for preparing an IRS Schedule E rental tax return.
- **Authenticated_User**: The person identified by a Cognito `sub`. All data in this feature is scoped to this user.
- **Schedule_E_Import**: The capability that synthesizes the backing transactions for one or more (Property, Tax_Year) pairs from user-entered Schedule E line amounts.
- **Import_Service**: The backend service component (to be created) that validates import input, synthesizes imported summary transactions, applies replace-on-reimport, and scopes all work to the Authenticated_User.
- **Import_Submission**: The whole multi-property, single-year submission the Authenticated_User submits in one pass. It carries one Tax_Year and one or more Property_Entries.
- **Property_Entry**: One property's mapping plus its set of Schedule E line amounts within a single Import_Submission (the analog of one Schedule E Part I property column A/B/C). Each Property_Entry maps to exactly one Property and carries income lines 3-4, expense lines 5-17, and Line_19_Other for that property.
- **Property**: An existing Logstead rental property record owned by the Authenticated_User, carrying an address and optional details.
- **Tax_Year**: The calendar year a Schedule E covers; transactions are keyed per-property per-tax-year. A single Import_Submission has exactly one Tax_Year shared by all its Property_Entries.
- **Schedule_E_Line**: An IRS Schedule E Part I line number. The modeled lines are income lines 3 (Rents) and 4 (Royalties), expense lines 5-17, Line 18 (Depreciation), and Line 19 (Other).
- **Category_Catalog**: The fixed reference set of assignable Schedule E categories, keyed to Schedule E Part I lines. Line 18 (Depreciation) is intentionally **not** an assignable category.
- **Line_18_Depreciation**: Schedule E Line 18. Derived only from depreciation schedules; never fed by a transaction and never imported.
- **Line_19_Other**: Schedule E Line 19 (Other expenses). Its category requires a free-text description on every transaction assigned to it.
- **Summary_Transaction**: A single synthesized transaction created by the import to represent the entire entered amount for one non-zero Schedule E line of one Property_Entry (that is, for one (Property, Tax_Year)).
- **Imported_Marker**: A persisted attribute on a Summary_Transaction identifying it as import-synthesized (as opposed to a user-tracked transaction), so listings and reports can distinguish it.
- **Imported_Set**: All Summary_Transactions carrying the Imported_Marker for one (Property, Tax_Year).
- **User_Tracked_Transaction**: Any transaction that does not carry the Imported_Marker (an ordinary transaction the user records going forward).
- **Money_Value**: A monetary amount handled as a `Decimal` in code and persisted as a fixed two-decimal string, per Logstead's money convention (never a float, never a DynamoDB number).
- **Reporting_Service**: The existing service that derives a Schedule E report on demand from stored transactions, depreciation schedules, and usage days.

## Requirements

### Requirement 1: Import entry point and multi-property flow

**User Story:** As a Logstead user, I want a guided way to enter a prior year's Schedule E for one or more properties at once, so that my historical reports populate without re-creating individual transactions.

#### Acceptance Criteria

1. THE Schedule_E_Import SHALL provide a guided per-tax-year form as the only v1 input surface for importing a Schedule E.
2. WHEN the Authenticated_User starts an import, THE Schedule_E_Import SHALL require the Authenticated_User to select one Tax_Year for the Import_Submission before entering line amounts.
3. THE Schedule_E_Import SHALL allow the Authenticated_User to add one or more Property_Entries to a single Import_Submission, each with its own Property mapping and its own set of Schedule E line amounts.
4. THE Schedule_E_Import SHALL present, for each Property_Entry, entry fields for income lines 3-4, expense lines 5-17, and Line_19_Other, and SHALL NOT present an entry field for Line_18_Depreciation.
5. WHEN the Authenticated_User submits a completed Import_Submission, THE Import_Service SHALL synthesize the Imported_Set for each Property_Entry's (Property, Tax_Year) and report the per-Property_Entry outcome to the Authenticated_User.
6. IF the Authenticated_User submits an Import_Submission with no Property_Entry, THEN THE Import_Service SHALL reject the request with a validation error indicating that at least one Property_Entry is required.
7. IF the Authenticated_User submits an Import_Submission without a selected Tax_Year, THEN THE Import_Service SHALL reject the request with a validation error identifying the Tax_Year field.

### Requirement 2: Property mapping and inline creation per entry

**User Story:** As a Logstead user, I want to map each property column to an existing property or create one on the spot, so that each column's imported data lands on the right property.

#### Acceptance Criteria

1. WHEN the Authenticated_User maps a Property_Entry, THE Schedule_E_Import SHALL offer the Authenticated_User's existing Properties for selection.
2. WHERE the Authenticated_User chooses to create a new Property for a Property_Entry, THE Schedule_E_Import SHALL create the Property using the existing property-creation capability and use the newly created Property as that Property_Entry's mapping.
3. IF a Property_Entry maps to a Property that does not exist or is not owned by the Authenticated_User, THEN THE Import_Service SHALL reject the Import_Submission with a not-found error identifying the offending Property_Entry.
4. WHEN an inline Property creation for a Property_Entry is submitted with a missing required Property field, THEN THE Schedule_E_Import SHALL reject the Import_Submission with a validation error identifying the offending Property_Entry and field.
5. IF two Property_Entries in the same Import_Submission map to the same Property, THEN THE Import_Service SHALL reject the Import_Submission with a validation error indicating that each Property_Entry must map to a distinct Property for the Tax_Year.

### Requirement 3: Tax-year selection

**User Story:** As a Logstead user, I want to choose which tax year the Schedule E belongs to, so that the synthesized transactions appear in the correct year's report for every property.

#### Acceptance Criteria

1. WHEN the Authenticated_User selects a Tax_Year for an Import_Submission, THE Import_Service SHALL associate every synthesized Summary_Transaction across all Property_Entries with that Tax_Year so each (Property, Tax_Year) report includes them.
2. IF the Authenticated_User provides a Tax_Year that is not a valid four-digit calendar year, THEN THE Import_Service SHALL reject the Import_Submission with a validation error identifying the Tax_Year field.
3. THE Import_Service SHALL date each synthesized Summary_Transaction within the selected Tax_Year so that the existing per-property per-tax-year transaction query returns the Imported_Set for that Property and year.

### Requirement 4: Entering Schedule E line amounts per property entry

**User Story:** As a Logstead user, I want to type each Schedule E line amount for each property column from my prior return, so that the import reproduces my reported totals for every property.

#### Acceptance Criteria

1. THE Schedule_E_Import SHALL accept, per Property_Entry, a Money_Value for each of income lines 3-4, expense lines 5-17, and Line_19_Other.
2. WHERE a Schedule_E_Line entry within a Property_Entry is left blank, THE Import_Service SHALL treat that line's amount as zero for that Property_Entry.
3. WHEN the Authenticated_User enters line amounts for a Property_Entry, THE Import_Service SHALL map each entered line to the corresponding Category_Catalog category for that Schedule_E_Line.

### Requirement 5: Depreciation is never imported

**User Story:** As a Logstead user, I want to understand that depreciation is not imported for any property, so that I know to add a depreciation schedule to get Line 18 on each property's report.

#### Acceptance Criteria

1. THE Schedule_E_Import SHALL NOT accept, synthesize, or persist any Line_18_Depreciation amount or depreciation data for any Property_Entry during an import.
2. THE Schedule_E_Import SHALL display a notice to the Authenticated_User stating that depreciation is not imported for any property in the Import_Submission and that a depreciation schedule must be created for each Property and the Tax_Year to populate Line 18.
3. WHEN an import completes for a (Property, Tax_Year) that has no depreciation schedule, THE Reporting_Service SHALL report Line_18_Depreciation as the zero Money_Value for that report.

### Requirement 6: Synthesize one summary transaction per non-zero line per property entry

**User Story:** As a Logstead user, I want each entered line of each property column to become a single summary entry, so that my imported data is compact rather than fabricated line items.

#### Acceptance Criteria

1. WHEN an Import_Submission is submitted, THE Import_Service SHALL create, for each Property_Entry, exactly one Summary_Transaction for each Schedule_E_Line of that Property_Entry whose entered amount is greater than the zero Money_Value.
2. WHERE a Schedule_E_Line's entered amount within a Property_Entry equals the zero Money_Value, THE Import_Service SHALL NOT create a Summary_Transaction for that line of that Property_Entry.
3. WHEN the Import_Service creates a Summary_Transaction for an income line of a Property_Entry, THE Import_Service SHALL record the transaction as income for that Property_Entry's Property with the Schedule_E_Line of the mapped Category_Catalog category.
4. WHEN the Import_Service creates a Summary_Transaction for an expense line of a Property_Entry, THE Import_Service SHALL record the transaction as an expense for that Property_Entry's Property with the Schedule_E_Line of the mapped Category_Catalog category.
5. WHEN the Import_Service creates a Summary_Transaction for Line_19_Other of a Property_Entry, THE Import_Service SHALL set a non-blank description so the existing Line_19_Other description rule is satisfied.
6. WHERE no explicit description is provided for a Line_19_Other amount of a Property_Entry, THE Import_Service SHALL apply the default description "Imported Schedule E Other".
7. THE Import_Service SHALL record each Summary_Transaction amount as a Money_Value equal to the entered amount for that Schedule_E_Line of that Property_Entry.

### Requirement 7: Imported marker and its visibility

**User Story:** As a Logstead user, I want imported entries to be clearly marked, so that I never confuse backfilled data with transactions I track going forward.

#### Acceptance Criteria

1. WHEN the Import_Service creates a Summary_Transaction, THE Import_Service SHALL persist an Imported_Marker on that transaction identifying it as import-synthesized.
2. THE Import_Service SHALL NOT persist an Imported_Marker on any User_Tracked_Transaction.
3. WHEN a transaction listing includes a Summary_Transaction, THE Schedule_E_Import SHALL render the Summary_Transaction as identifiable as imported.
4. WHEN a Schedule E report includes amounts contributed by Summary_Transactions, THE Reporting_Service SHALL surface the Imported_Marker so the Authenticated_User can identify imported contributions.
5. THE Import_Service SHALL preserve the Imported_Marker through the existing transaction read path so a stored Summary_Transaction remains identifiable after retrieval.

### Requirement 8: Replace-on-reimport scoped per (Property, Tax_Year) in the submission

**User Story:** As a Logstead user, I want re-importing a year to replace my earlier import only for the properties I include this time, so that corrections do not pile up duplicates, do not disturb my real transactions, and do not silently wipe a property I left out.

#### Acceptance Criteria

1. WHEN the Authenticated_User submits an Import_Submission that includes a (Property, Tax_Year) that already has an Imported_Set, THE Import_Service SHALL delete the existing Imported_Set for that (Property, Tax_Year) before persisting the new Imported_Set for that Property_Entry.
2. THE Import_Service SHALL restrict replace-on-reimport deletion to transactions carrying the Imported_Marker for a (Property, Tax_Year) that is present in the current Import_Submission.
3. THE Import_Service SHALL NOT delete or modify any Imported_Set for a (Property, Tax_Year) that is NOT present in the current Import_Submission, even if that Property was included in a prior import of the same Tax_Year.
4. THE Import_Service SHALL NOT delete or modify any User_Tracked_Transaction during an import or re-import.
5. WHEN a re-import completes, THE Reporting_Service SHALL derive each affected (Property, Tax_Year) report from the new Imported_Set plus any User_Tracked_Transactions, with no residual amounts from the replaced Imported_Set.
6. WHERE a re-import leaves a Schedule_E_Line with the zero Money_Value for a Property_Entry, THE Import_Service SHALL ensure no Summary_Transaction for that line remains for that (Property, Tax_Year).

### Requirement 9: All-or-nothing input validation

**User Story:** As a Logstead user, I want the import to reject the whole submission if any property column is bad, so that my synthesized data is trustworthy and I am never left with a partially applied import.

#### Acceptance Criteria

1. WHEN the Authenticated_User submits a line amount for a Property_Entry, THE Import_Service SHALL accept it only as a Money_Value expressible to two decimal places.
2. IF a submitted line amount for any Property_Entry is negative, THEN THE Import_Service SHALL reject the entire Import_Submission with a validation error identifying the offending Property_Entry and Schedule_E_Line.
3. IF a submitted line amount for any Property_Entry is not a valid monetary value, THEN THE Import_Service SHALL reject the entire Import_Submission with a validation error identifying the offending Property_Entry and Schedule_E_Line.
4. IF every entered line amount within any single Property_Entry equals the zero Money_Value, THEN THE Import_Service SHALL reject the entire Import_Submission with a validation error indicating that the offending Property_Entry requires at least one non-zero line amount.
5. IF any Property_Entry fails any validation rule (invalid, negative, or non-two-decimal amount; missing or not-found Property; duplicate Property mapping; all-zero entry; or invalid Tax_Year), THEN THE Import_Service SHALL reject the entire Import_Submission and SHALL NOT create, delete, or modify any transaction for any Property_Entry.
6. WHEN the Import_Service rejects an Import_Submission for any validation reason, THE Import_Service SHALL report each offending Property_Entry and field so the Authenticated_User knows which entry and line is wrong.

### Requirement 10: Per-user scoping

**User Story:** As a Logstead user, I want my imported data isolated to my account, so that it behaves like every other record in the app.

#### Acceptance Criteria

1. THE Import_Service SHALL scope every import operation to the Authenticated_User identified by the Cognito `sub`.
2. WHEN the Import_Service synthesizes a Summary_Transaction for a Property_Entry, THE Import_Service SHALL store it under the Authenticated_User's data scope using the existing per-property per-tax-year transaction storage.
3. IF any Property_Entry maps to a Property not owned by the Authenticated_User, THEN THE Import_Service SHALL reject the entire Import_Submission with a not-found error and SHALL NOT create any transaction for any Property_Entry.

### Requirement 11: Money precision and consistency

**User Story:** As a Logstead user, I want imported amounts to carry the same precision as the rest of Logstead, so that reports reconcile exactly.

#### Acceptance Criteria

1. THE Import_Service SHALL represent every imported line amount, across all Property_Entries, as a Money_Value with exactly two decimal places.
2. THE Import_Service SHALL persist every Summary_Transaction amount as a fixed two-decimal string, consistent with Logstead's money persistence convention.
3. WHEN the Reporting_Service aggregates Summary_Transactions into a Schedule_E_Line total for a (Property, Tax_Year), THE Schedule_E_Line total SHALL equal the sum of the entered amounts for that line of that Property_Entry as a two-decimal Money_Value with no precision drift.
