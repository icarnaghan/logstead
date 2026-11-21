# Requirements Document

## Introduction

Logstead is a single-user Schedule E rental tax app (React/Vite/Tailwind SPA; Python 3.12 Lambda over a single-table DynamoDB design; SAM infrastructure). Today a user records expenses as year-end totals: one transaction per Schedule E line per tax year, optionally with a supporting document. The Schedule E report sums the transactions of each category onto the category's line. Schedule E Import writes one summary transaction per non-zero line, marked `imported`.

This feature lets the user keep **itemized detail** behind a year's total for an expense line, starting with **Repairs (Schedule E line 14)**. The user opens a new **Repairs** tab under a property, picks a tax year, and logs individual repair entries (date, amount, description/vendor, optional notes), each with attached receipts. The existing ability to enter or import a single repairs total is unchanged and remains the right choice for years without granular detail.

The two sources are combined by an explicit, non-automatic rule:

- If the year has a repairs **total** (entered or imported), the total is authoritative for line 14 and the itemized entries are supporting detail.
- If the year has no total, line 14 is the sum of the itemized entries.
- The two are never added together.

The Repairs page shows the total, the itemized sum, the unitemized remainder (total minus itemized, possibly negative and then flagged), and which source line 14 uses. When the total and the itemized sum differ, the page offers a button to set the total to the itemized sum, behind a confirm dialog that names the exact line 14 change and warns about completed tax years, with an Undo toast.

The feature is built around a small per-category configuration so other expense lines (for example Supplies, line 15, or Cleaning and maintenance, line 7) can adopt the same pattern later by enabling a category. Repairs is the only enabled category in this release.

The precedence rule relies on telling imported totals apart from user-entered ones, so this release also fixes two existing defects that lose the `imported` marker: a generic transaction update that drops it (an edited imported total would be duplicated by the next re-import), and backups that do not carry it (a restore would turn imported rows into user rows). See Requirements 19 and 20.

### Out of scope and future work

- Enabling any category other than Repairs.
- Mobile layout of the property tabs (future work, tracked in `docs/future-improvements.md`; see Requirement 17).
- Converting existing repairs transactions into itemized entries (future work, tracked in `docs/future-improvements.md`; see Requirement 17). Existing transactions stay Entered_Total_Rows.
- Any change to depreciation, Schedule E import parsing, loans, or the carryforward algorithm.
- Whole-dollar rounding of the Repairs page. The page reconciles raw entry amounts, so it shows cents.

### Decisions recorded

- Several Entered_Total_Rows in one category and year are still summed into the Entered_Total. The Repairs_Page disables set, edit, remove, and sync for that state and links to the Transactions page (Requirements 7.7, 8.6, 9.8).
- A total of zero is never stored. Removing the total makes line 14 follow the itemized entries, and a year with neither a total nor entries reports line 14 as 0.00 with no user action (Requirements 5.3, 5.9, 7.11, 8.7).
- An Itemized_Entry date must fall within the selected tax year (Requirements 2.6, 2.7).

### Grounding in the existing code

- `services/category.py` defines the category catalog (`repairs` is Schedule E line 14, an expense).
- `services/report.py` (`ReportingService._build_report`) is the only place that turns transactions into Schedule E line totals. The dashboard, the year-over-year trends, the carryforward reconciliation and the CSV/JSON exports all read those totals through `ReportingService.report_for`.
- `services/transaction.py` stores transactions under `PROPERTY#<id>` with an inverted-date sort key and GSI2 tax-year keys, and stores receipts as `#DOC#` rows under the transaction. Receipt uploads use presigned S3 PUT URLs (600 second expiry, content-type allowlist of images and PDF, sanitized filenames, oversized objects purged on read).
- `services/schedule_e_import.py` writes `imported=True` summary transactions and, on re-import, replaces only the imported rows for a (property, tax year).
- `router/handler.py` guards every `/properties/{propertyId}/...` route with `_property_scoped`, validates path ids with `_check_path_ids`, and validates request strings with helpers such as `_opt_str`.
- `services/backup.py` exports and restores transactions with `schema_version` `"1"`; unknown categories and malformed money are rejected on restore.
- Frontend: `TransactionsPage`, `RecordModal` + `useRecordModal`, `useUndoableDelete`, `useAsyncResource`, `PropertySection` + `PropertySectionTabs` (driven by `PROPERTY_NAV` in `navConfig.ts`), `ResponsiveTable`, `StateBlock`, `PageHeader`, `ConfirmDialog`, toasts, `ReceiptList`.

## Glossary

- **Logstead_API**: The Python Lambda backend reached through the router in `router/handler.py`.
- **Logstead_UI**: The React single-page frontend.
- **Itemized_Category**: A Schedule E expense category enabled for itemized entries in the central configuration. In this release the only Itemized_Category is `repairs` (line 14).
- **Itemized_Config**: The single backend configuration listing the Itemized_Categories. The frontend reads the enabled list from the Logstead_API summary response and does not duplicate it.
- **Itemized_Entry**: A transaction that carries the itemized marker (`itemized = true`), belongs to an Itemized_Category, has type `expense`, and records one repair (date, amount, description/vendor, optional notes).
- **Entered_Total_Row**: A transaction in an Itemized_Category that does not carry the itemized marker. Rows created before this feature, rows created on the Transactions page, rows created by Schedule E Import, and rows created by the Repairs page "set total" action are all Entered_Total_Rows.
- **Entered_Total**: For one (property, tax year, Itemized_Category), the sum of the amounts of its Entered_Total_Rows. The Entered_Total is **present** when at least one Entered_Total_Row exists and **absent** otherwise.
- **Itemized_Sum**: For one (property, tax year, Itemized_Category), the sum of the amounts of its Itemized_Entries (`0.00` when there are none).
- **Unitemized_Remainder**: Entered_Total minus Itemized_Sum. It is defined only when the Entered_Total is present, and it may be negative.
- **Line_Total**: The amount the Schedule E report shows for the category's line for the (property, tax year): the Entered_Total when present, otherwise the Itemized_Sum.
- **Line_Source**: Which input produced the Line_Total: `entered_total`, `itemized`, or `none` (neither exists).
- **Precedence_Rule**: The rule that computes Line_Total and Line_Source from the Entered_Total and the Itemized_Sum.
- **Line_Resolver**: The single backend function that implements the Precedence_Rule. Every consumer of Schedule E line totals obtains its figure through the Line_Resolver.
- **Repairs_Page**: The new per-property page at `/properties/:propertyId/repairs`, reached from the Repairs tab.
- **Itemized_Summary**: The Logstead_API response describing one (property, tax year, Itemized_Category): Entered_Total, Itemized_Sum, Unitemized_Remainder, Line_Total, Line_Source, the Entered_Total_Rows, and the Itemized_Entries.
- **Sync_Action**: The Repairs_Page button labelled "Update total to $X (itemized)" that sets the Entered_Total to the Itemized_Sum.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string such as `"1250.00"`; never a float and never a DynamoDB `Number`.
- **Completed_Tax_Year**: A tax year earlier than the current calendar year.
- **Receipt**: A supporting document attached to a transaction through the existing receipt mechanism (the UI labels it "Document").
- **Property_Tabs**: The per-property sub-navigation rendered by `PropertySectionTabs` from `PROPERTY_NAV`.

## Requirements

### Requirement 1: Repairs tab and page

**User Story:** As the property owner, I want a Repairs tab on each property, so that I can reach itemized repair detail alongside Transactions and Assets.

#### Acceptance Criteria

1. THE Logstead_UI SHALL add a "Repairs" entry to the Property_Tabs between "Transactions" and "Depreciable Assets".
2. WHEN the user selects the Repairs tab, THE Logstead_UI SHALL render the Repairs_Page at `/properties/:propertyId/repairs` inside the existing property layout.
3. THE Repairs_Page SHALL render a `PageHeader` through `PropertySection` with a breadcrumb, one `h1`, and the Property_Tabs, and SHALL set the document title to "Repairs - {property name}".
4. THE Repairs_Page SHALL provide a tax-year selector that defaults to the latest Completed_Tax_Year and offers the same year range as the Transactions page.
5. WHERE the URL carries a `year` search parameter holding an offered tax year, THE Repairs_Page SHALL select that year on load.
6. WHEN the user switches property with the property switcher while on the Repairs_Page, THE Logstead_UI SHALL stay on the Repairs section and carry over the `year` search parameter.
7. WHILE the Itemized_Summary is loading for the first time, THE Repairs_Page SHALL show a skeleton, and WHILE it reloads afterwards THE Repairs_Page SHALL keep the previous content mounted and show the refreshing indicator.
8. IF the Itemized_Summary fails to load, THEN THE Repairs_Page SHALL show an error `StateBlock` with a retry action.
9. THE Repairs_Page SHALL show a note stating that capital improvements such as a roof or HVAC belong in Assets because they are depreciated, with a link to the property's Assets page at `/properties/:propertyId/assets`.

### Requirement 2: Itemized repair entries

**User Story:** As the property owner, I want to log individual repairs for a tax year, so that I keep a record of what the year's repairs consisted of.

#### Acceptance Criteria

1. WHEN the user submits the add-entry form with a valid date, amount, and description, THE Logstead_API SHALL create an Itemized_Entry with category `repairs`, type `expense`, and the itemized marker set, and THE Logstead_UI SHALL show it in the selected year's entry list.
2. THE Logstead_API SHALL accept an optional notes field on an Itemized_Entry of at most 1000 characters.
3. THE Logstead_API SHALL require the description/vendor field of an Itemized_Entry to be non-blank and at most 200 characters after trimming.
4. THE Logstead_API SHALL require the amount of an Itemized_Entry to be greater than zero with at most two decimal places and not above the existing amount ceiling.
5. THE Logstead_API SHALL require the date of an Itemized_Entry to be a valid ISO `YYYY-MM-DD` date.
6. WHERE the request carries a `tax_year`, THE Logstead_API SHALL reject an entry whose date falls outside that tax year with a validation error identifying the `date` field.
7. THE Repairs_Page add-entry form SHALL send the selected tax year and SHALL default the date to today when today falls in the selected year, and otherwise to December 31 of the selected year.
8. WHEN the user edits an Itemized_Entry, THE Logstead_API SHALL apply the same validation as creation and SHALL keep the entry's id, itemized marker, and attached Receipts.
9. WHEN the user deletes an Itemized_Entry, THE Logstead_API SHALL delete the entry and its Receipts, including their S3 objects.
10. THE Repairs_Page SHALL list the selected year's Itemized_Entries newest first with date, description/vendor, notes, and amount columns, using `ResponsiveTable`.
11. IF the Logstead_API rejects an add or edit with a field-identifying validation error, THEN THE Logstead_UI SHALL show the message next to that field in the `RecordModal` form and keep the modal open.
12. THE Logstead_API SHALL reject creation of an Itemized_Entry for a category that is not an Itemized_Category with a validation error identifying the `category_id` field.

### Requirement 3: Receipts on entries and totals

**User Story:** As the property owner, I want to attach receipts to each repair entry, so that I can back each expense with evidence.

#### Acceptance Criteria

1. THE Repairs_Page SHALL provide a "Documents" control on each Itemized_Entry that attaches, lists, and deletes Receipts through the existing receipt component.
2. THE Logstead_API SHALL store Receipts of an Itemized_Entry through the existing transaction receipt routes and SHALL apply the existing receipt limits: the image and PDF content-type allowlist, filename sanitization, 600 second upload URL expiry, and oversized-object purge.
3. WHERE the Entered_Total consists of exactly one Entered_Total_Row, THE Repairs_Page SHALL provide the same "Documents" control for that row.
4. THE Logstead_UI SHALL label Receipts as "Documents" and "Supporting documents", consistent with the Transactions page.

### Requirement 4: Entered totals keep working

**User Story:** As the property owner, I want to keep entering or importing a single repairs total for years where I have no detail, so that the existing workflow is unchanged.

#### Acceptance Criteria

1. THE Logstead_API SHALL treat every transaction that exists before this feature is deployed as an Entered_Total_Row of its category, without any data migration.
2. WHEN the user creates a repairs transaction on the Transactions page, THE Logstead_API SHALL store it as an Entered_Total_Row.
3. WHEN Schedule E Import writes a repairs summary transaction, THE Logstead_API SHALL store it as an Entered_Total_Row with `imported = true`.
4. WHEN Schedule E Import re-imports a (property, tax year), THE Logstead_API SHALL replace only the imported rows and SHALL leave every Itemized_Entry unchanged.
5. WHEN a (property, tax year) has an Entered_Total and no Itemized_Entries, THE Schedule E report SHALL show the Entered_Total on line 14, identical to the report before this feature.
6. THE Logstead_API SHALL NOT allow the generic transaction create route to set the itemized marker.

### Requirement 5: Line total precedence

**User Story:** As the property owner, I want line 14 to use my total when I have one and my itemized entries otherwise, so that the two are never double counted.

#### Acceptance Criteria

1. WHEN the Entered_Total is present for a (property, tax year, Itemized_Category), THE Line_Resolver SHALL return the Entered_Total as the Line_Total and `entered_total` as the Line_Source, regardless of the Itemized_Sum.
2. WHEN the Entered_Total is absent and at least one Itemized_Entry exists, THE Line_Resolver SHALL return the Itemized_Sum as the Line_Total and `itemized` as the Line_Source.
3. WHEN the Entered_Total is absent and no Itemized_Entry exists, THE Line_Resolver SHALL return `0.00` as the Line_Total and `none` as the Line_Source.
4. THE Line_Resolver SHALL NOT add the Itemized_Sum to the Entered_Total in any case.
5. THE Line_Resolver SHALL compute every amount with `Decimal` arithmetic and return Line_Total, Itemized_Sum, and Unitemized_Remainder quantized to two decimal places.
6. THE Line_Resolver SHALL define Unitemized_Remainder as Entered_Total minus Itemized_Sum when the Entered_Total is present, and as undefined otherwise.
7. WHEN an Itemized_Entry is created, edited, or deleted, THE Logstead_API SHALL NOT change any Entered_Total_Row.
8. WHEN an Entered_Total_Row is created, edited, or deleted, THE Logstead_API SHALL NOT change any Itemized_Entry.
9. WHEN a (property, tax year) has no Entered_Total_Row and no Itemized_Entry, THE Schedule E report SHALL show `0.00` on line 14, and THE Logstead_API SHALL require no stored zero total and no user action to produce that figure.

### Requirement 6: One source of truth across reports

**User Story:** As the property owner, I want the report, dashboard, carryforward and exports to agree on line 14, so that I never see conflicting numbers.

#### Acceptance Criteria

1. THE Schedule E report builder SHALL obtain the line total of every Itemized_Category line from the Line_Resolver and SHALL NOT sum Itemized_Entries onto that line by any other path.
2. THE Logstead_API SHALL compute the Itemized_Summary Line_Total with the same Line_Resolver the report builder uses.
3. FOR ALL (property, tax year) states, THE dashboard per-property summary, the dashboard year-over-year trends, the carryforward Schedule E net, the combined report, and the CSV and JSON exports SHALL equal the figures derived from the report builder's line totals.
4. FOR ALL (property, tax year) states, THE Itemized_Summary Line_Total SHALL equal the line 14 total on the Schedule E report for the same (property, tax year).
5. WHEN the Line_Source of a line is `entered_total`, THE report line's `includes_imported` marker SHALL reflect only the Entered_Total_Rows.
6. THE Line_Resolver SHALL apply only to categories listed in the Itemized_Config, and the report builder SHALL sum every transaction of any other category exactly as before.
7. THE Logstead_API SHALL leave the depreciation line 18, the Line 12 loan precedence, and the Line 19 itemization unchanged.

### Requirement 7: Summary display and source label

**User Story:** As the property owner, I want to see the total, the itemized sum, the remainder and which source line 14 uses, so that I understand how the year's number is built.

#### Acceptance Criteria

1. THE Repairs_Page SHALL show the Entered_Total, or the text "No total entered" when absent.
2. THE Repairs_Page SHALL show the Itemized_Sum and the number of Itemized_Entries.
3. WHEN the Entered_Total is present, THE Repairs_Page SHALL show the Unitemized_Remainder.
4. IF the Unitemized_Remainder is negative, THEN THE Repairs_Page SHALL flag it with a visible text label stating that itemized entries exceed the entered total, in addition to any color.
5. THE Repairs_Page SHALL show the Line_Total and a label of the Line_Source reading "Line 14 uses: entered total" when the Line_Source is `entered_total`, "Line 14 uses: itemized entries" when `itemized`, and "Line 14 has no amount for this year" when `none`.
6. THE Repairs_Page SHALL render the summary figures in a way that screen readers announce each label with its value.
7. WHEN the Entered_Total consists of more than one Entered_Total_Row, THE Repairs_Page SHALL list those rows with a link to the Transactions page filtered to the year and explain that they are combined into the Entered_Total.
8. WHERE an Entered_Total_Row has `imported = true`, THE Repairs_Page SHALL show an "Imported" badge on it.
9. THE Repairs_Page SHALL format summary and entry amounts with cent precision using `formatMoney`.
10. WHERE an Entered_Total_Row has `imported = true`, THE Repairs_Page SHALL state next to the "Imported" badge that re-importing a Schedule E for that tax year replaces the imported total.
11. WHEN the Line_Source is `none`, THE Repairs_Page SHALL show the Line_Total as `$0.00` and SHALL offer "Set total" and "Add entry" without requiring a total to exist.

### Requirement 8: Manage the total manually

**User Story:** As the property owner, I want to set, edit and remove the year's repairs total on the Repairs page, so that I do not need to switch to the Transactions page.

#### Acceptance Criteria

1. WHEN the Entered_Total is absent, THE Repairs_Page SHALL offer a "Set total" action.
2. WHEN the user submits a valid amount through "Set total", THE Logstead_API SHALL create one Entered_Total_Row for the tax year dated December 31, with type `expense`, the category, `imported = false`, and no itemized marker.
3. WHEN the Entered_Total consists of exactly one Entered_Total_Row, THE Repairs_Page SHALL offer "Edit total" and "Remove total" actions.
4. WHEN the user submits a valid amount through "Edit total", THE Logstead_API SHALL update that row's amount in place and SHALL preserve its id, date, description, `imported` marker, and Receipts.
5. WHEN the user confirms "Remove total", THE Logstead_API SHALL delete the Entered_Total_Row and its Receipts, and THE Line_Source SHALL become `itemized` when Itemized_Entries exist.
6. IF the Entered_Total consists of more than one Entered_Total_Row, THEN THE Logstead_API SHALL reject set, edit, and remove total requests with a `conflict` error, and THE Repairs_Page SHALL disable those actions with an explanation and the link from Requirement 7.7.
7. THE Logstead_API SHALL require a set or edit total amount to be greater than zero with at most two decimal places, and THE Repairs_Page SHALL explain that removing the total is how to make line 14 follow the itemized entries.
8. WHEN a total is removed and the row is not imported and has no Receipts, THE Repairs_Page SHALL show an Undo toast that re-creates the row; otherwise THE Repairs_Page SHALL use a confirm dialog and no Undo.
9. WHEN a total is set or edited, THE Repairs_Page SHALL show a success toast with an Undo action that restores the previous state (deleting the new row, or restoring the previous amount in place).

### Requirement 9: Update total to the itemized sum

**User Story:** As the property owner, I want one action that makes my total match my itemized entries, so that I can reconcile the year deliberately.

#### Acceptance Criteria

1. WHILE the Entered_Total is present, at least one Itemized_Entry exists, and the Itemized_Sum differs from the Entered_Total, THE Repairs_Page SHALL show the Sync_Action labelled "Update total to $X (itemized)", where X is the Itemized_Sum formatted with `formatMoney`.
2. WHILE the Entered_Total is absent or equals the Itemized_Sum or no Itemized_Entry exists, THE Repairs_Page SHALL NOT show the Sync_Action.
3. WHEN the user activates the Sync_Action, THE Repairs_Page SHALL open a confirm dialog naming the exact change: the line number, the tax year, the current Entered_Total, the new Entered_Total, and the signed difference.
4. WHERE the tax year is a Completed_Tax_Year, THE confirm dialog SHALL add a warning that records will no longer match a filed return for that year.
5. WHEN the user confirms, THE Logstead_API SHALL set the Entered_Total to the Itemized_Sum through the set-total operation of Requirement 8, preserving the single row's id, `imported` marker, and Receipts.
6. WHEN the Sync_Action succeeds, THE Repairs_Page SHALL show a toast containing an Undo action that restores the previous Entered_Total amount.
7. IF the Sync_Action fails, THEN THE Repairs_Page SHALL show an error toast, keep the dialog's data unchanged, and leave the Entered_Total unchanged.
8. IF the Entered_Total consists of more than one Entered_Total_Row, THEN THE Repairs_Page SHALL disable the Sync_Action with the explanation from Requirement 8.6.
9. WHEN the user cancels the confirm dialog, THE Logstead_API SHALL make no change.

### Requirement 10: Itemized entries on the Transactions page

**User Story:** As the property owner, I want the Transactions page to stay accurate and not mislead me about itemized entries, so that I do not accidentally double count or edit them in the wrong place.

#### Acceptance Criteria

1. THE Transactions page SHALL continue to list Itemized_Entries so that the list matches the data behind the report.
2. THE Transactions page SHALL mark each Itemized_Entry with an "Itemized" badge and SHALL replace its Edit and Delete actions with a "Manage on Repairs page" link to the Repairs_Page for the entry's tax year.
3. WHILE the loaded list contains at least one Itemized_Entry, THE Transactions page SHALL show a note explaining that itemized entries are supporting detail and that line 14 uses the entered total when one exists.
4. WHEN the user opens the add-transaction form with category Repairs and the loaded list holds Itemized_Entries dated in the form's tax year, THE Logstead_UI SHALL show a hint that the new transaction becomes the entered total and replaces the itemized sum on line 14.
5. THE Logstead_API SHALL reject a generic transaction update that would change an existing transaction's itemized marker, in either direction, with a validation error identifying the `itemized` field.
6. THE Logstead_API SHALL keep the generic transaction delete route working for Itemized_Entries.
7. THE Logstead_UI SHALL treat an Itemized_Entry as not Undo-safe in `isTransactionSafeDelete`.

### Requirement 11: Generic category configuration

**User Story:** As the maintainer, I want the itemized-with-total pattern to be configuration-driven, so that other expense lines can adopt it later without new rules or pages.

#### Acceptance Criteria

1. THE Itemized_Config SHALL list each Itemized_Category by category id and SHALL be the only place that names `repairs` as enabled.
2. THE Logstead_API SHALL expose the Itemized_Summary, entry, and total routes parameterized by `{categoryId}` and SHALL accept only Itemized_Categories.
3. IF a request names a category id that is not in the catalog, THEN THE Logstead_API SHALL return the same `not_found` response used for unknown categories elsewhere.
4. IF a request names a catalog category that is not an Itemized_Category, THEN THE Logstead_API SHALL return a validation error identifying the `category_id` field.
5. THE Repairs_Page SHALL take the category id, the line label, and the page text from a single frontend definition for the Repairs tab, so a later category reuses the same page component with a different definition.
6. THE Itemized_Config SHALL contain only `repairs` in this release, and THE Logstead_UI SHALL expose no page or tab for any other category.
7. THE Line_Resolver SHALL treat an itemized-marked transaction of a category not in the Itemized_Config as an Entered_Total_Row, so a mis-flagged row never disappears from a total.

### Requirement 12: Data model compatibility

**User Story:** As the property owner, I want my existing data and backups to keep working, so that the feature needs no migration.

#### Acceptance Criteria

1. THE Logstead_API SHALL store the itemized marker as an optional boolean attribute `itemized` and the notes as an optional string attribute `notes` on the existing transaction item, with no new key, sort key, GSI, route namespace for storage, or table.
2. WHEN the Logstead_API reads a transaction item without an `itemized` attribute, THE Logstead_API SHALL read it as `itemized = false`.
3. THE Logstead_API SHALL omit the `itemized` and `notes` attributes from the stored item when they hold their default values, so existing items keep their stored shape.
4. THE Logstead_API SHALL export `itemized` and `notes` in the backup document for each transaction while keeping `schema_version` equal to `"1"`.
5. WHEN a backup document lacks `itemized` on a transaction, THE Logstead_API SHALL restore it with `itemized = false`.
6. IF a backup transaction has `itemized = true` and its category is not an Itemized_Category or its type is not `expense`, THEN THE Logstead_API SHALL reject the restore with a validation error identifying the `itemized` field and SHALL write nothing.
7. IF a backup transaction carries `itemized` that is not a boolean or `notes` that is not a string of at most 1000 characters, THEN THE Logstead_API SHALL reject the restore with a validation error and SHALL write nothing.
8. FOR ALL valid states, exporting a backup and restoring it SHALL reproduce the same Itemized_Entries and Entered_Total_Rows, and the same Line_Total for every (property, tax year) (round-trip property).
9. THE bundled sample backup fixture and the frontend backup types SHALL remain valid with the added optional fields (`itemized`, `notes`, and `imported` from Requirement 20).

### Requirement 13: Authorization and input validation

**User Story:** As the property owner, I want my data to be reachable only by me and malformed input rejected, so that the new routes are as safe as the existing ones.

#### Acceptance Criteria

1. THE Logstead_API SHALL guard every new `/properties/{propertyId}/itemized/...` route with the existing `_property_scoped` ownership check before the service runs.
2. WHEN a user requests a new route with another user's property id, THE Logstead_API SHALL return a `404` response byte-identical to the response for a property id that does not exist, and SHALL read and write no data.
3. WHEN a user requests an entry route with an entry id that belongs to a different property or that is not an Itemized_Entry of the named category, THE Logstead_API SHALL return the same `not_found` response as for a missing entry.
4. THE Logstead_API SHALL validate path ids with the existing `_check_path_ids` and the tax year with the existing `_int_param` bounds.
5. THE Logstead_API SHALL validate request body strings with `_opt_str` and amounts with the existing amount parser, and SHALL return `400` with a `field` for each failure.
6. THE Logstead_API SHALL ignore any `user_id`, `property_id`, `itemized`, `imported`, or `type` supplied in a request body of the new routes and SHALL take them from the path and the service.
7. THE Logstead_API SHALL return identical `404` responses on the existing receipt routes for an Itemized_Entry that belongs to another user.

### Requirement 14: Money handling

**User Story:** As the property owner, I want exact amounts everywhere, so that totals reconcile to the cent.

#### Acceptance Criteria

1. THE Logstead_API SHALL carry every monetary value of the feature as a `Decimal` in code and a two-decimal Money_String on the wire and in storage.
2. THE Logstead_UI SHALL compute the Sync_Action amount, the remainder display, and the confirm dialog difference in integer cents through `lib/money.ts`, with no floating-point arithmetic.
3. FOR ALL generated entry amounts and totals, THE Itemized_Sum, the Unitemized_Remainder, and the Line_Total SHALL have exactly two decimal places and the Itemized_Sum SHALL equal the exact sum of the entry amounts.

### Requirement 15: Undo semantics

**User Story:** As the property owner, I want clear, safe Undo behavior, so that I can recover from mistakes without losing evidence.

#### Acceptance Criteria

1. WHEN the user deletes an Itemized_Entry that has no Receipts, THE Repairs_Page SHALL delete it and show an Undo toast that re-creates the entry from the retained fields.
2. WHEN the user deletes an Itemized_Entry whose Receipt count is unknown or above zero, THE Repairs_Page SHALL use a confirm dialog and SHALL NOT offer Undo.
3. WHEN Undo re-creates an entry or a total row, THE Logstead_API SHALL assign a new id and fresh `created_at` and `updated_at`, and THE developer guide's "Undo and record IDs" table SHALL document this.
4. WHEN Undo restores a previous total amount by editing in place, THE Logstead_API SHALL keep the row's id.
5. IF an Undo action fails, THEN THE Logstead_UI SHALL show an error toast and refresh the summary.

### Requirement 16: Accessibility and UI conventions

**User Story:** As a keyboard and screen-reader user, I want the Repairs page to follow the app's accessibility conventions, so that it is usable.

#### Acceptance Criteria

1. THE Repairs_Page SHALL use only the shared primitives (`PageHeader`, `PropertySection`, `RecordModal`, `FormField`, `MoneyInput`, `DateInput`, `ConfirmDialog`, `ResponsiveTable`, `StateBlock`, `Button`, `Badge`, toasts) and semantic color and type tokens.
2. THE Repairs_Page SHALL pass the axe route suite in light and dark themes with exactly one `h1`, and the route SHALL be added to the Playwright accessibility spec.
3. THE Repairs_Page forms SHALL wire label, hint, error, and `aria-invalid` through `FormField`, move focus to the first invalid field after a failed submit, and use the discard guard for dirty forms.
4. THE Repairs_Page SHALL announce summary changes after a save, sync, or undo through the toast live region.
5. THE Repairs_Page SHALL not rely on color alone for the negative remainder, the source label, or the Itemized badge.
6. THE Repairs_Page SHALL give every icon-only or ambiguous action an accessible name that includes the entry date and description.
7. THE Repairs_Page SHALL keep touch targets at 44px on narrow viewports through the shared `Button` and form controls.

### Requirement 17: Documentation

**User Story:** As the maintainer, I want the docs to reflect the feature and the deferred mobile work, so that future work has context.

#### Acceptance Criteria

1. THE repository SHALL add two short items to `docs/future-improvements.md`: revisiting the property tabs layout on mobile now that the tab count has grown, and converting existing repairs transactions into itemized entries.
2. THE developer guide SHALL document the Repairs page, the Precedence_Rule and its single location, the itemized marker, and the Undo behavior of Itemized_Entries in the "Undo and record IDs" table.
3. THE developer guide's year-end Schedule E model section SHALL state that the one-entry-per-line convention still applies to totals and that itemized detail is optional supporting detail.

### Requirement 18: Verification

**User Story:** As the maintainer, I want strong tests around the precedence rule and the new routes, so that double counting cannot slip in.

#### Acceptance Criteria

1. THE test suite SHALL include Hypothesis property tests for the Line_Resolver proving: the Line_Total equals the Entered_Total when present and the Itemized_Sum when absent; the Itemized_Sum is never added to a present Entered_Total; every output has two decimal places; and the Itemized_Sum equals the exact decimal sum of the entry amounts.
2. THE test suite SHALL include a Hypothesis property test, run through the real report builder over moto, proving the report line total equals the Line_Resolver result and equals the Itemized_Summary Line_Total for arbitrary mixes of Entered_Total_Rows and Itemized_Entries, and that the dashboard summary and carryforward net use that same figure.
3. THE test suite SHALL include a property test proving that rows of categories outside the Itemized_Config sum exactly as before the feature.
4. THE test suite SHALL include a backup round-trip property test covering Itemized_Entries and notes, and example tests for the restore validation of Requirement 12.
5. THE test suite SHALL include router tests for every new route covering success, validation errors with `field`, and the cross-user `404` byte-identity of Requirement 13, added to `test_cross_user_authorization.py`.
6. THE test suite SHALL include a Schedule E Import test proving a re-import leaves Itemized_Entries unchanged.
7. THE frontend test suite SHALL include tests for the Repairs page states (loading, error, empty, total only, itemized only, both with a positive and a negative remainder), the Sync_Action visibility rule, the confirm dialog text with and without the Completed_Tax_Year warning, the Undo flows, the Transactions page badge and link, the nav entry, and the route in the axe suite.
8. THE frontend test suite SHALL include a fast-check property test proving that, for arbitrary amount lists, the displayed Itemized_Sum, remainder, and Sync_Action label amount equal the integer-cents oracle.
9. THE test suite SHALL include tests proving that a generic transaction update preserves the stored `imported` and `itemized` markers, including a regression test that edits an imported total through the generic update and then re-imports the same (property, tax year) and finds exactly one Entered_Total_Row and the re-imported line total.
10. THE test suite SHALL include a backup round-trip property test covering the `imported` marker and an example test that an older backup without `imported` restores with `imported = false`.
11. AFTER the feature is implemented, THE existing backend and frontend test suites, the frontend build, and the type check SHALL remain green.

### Requirement 19: Imported and itemized markers survive generic updates

**User Story:** As the property owner, I want editing an imported total on the Transactions page to keep it recognized as imported, so that re-importing the Schedule E replaces it instead of adding a second total.

#### Acceptance Criteria

1. WHEN a transaction is updated through the generic transaction update route, THE Logstead_API SHALL keep the stored row's `imported` marker unchanged.
2. THE Logstead_API SHALL ignore any `imported` or `itemized` value in the body of a generic transaction create or update request, so that a client can neither set nor clear either marker through those routes.
3. THE Logstead_API SHALL NOT change a stored transaction's `itemized` marker through any update path.
4. WHEN the user edits an imported total through the generic update route and Schedule E Import then re-imports the same (property, tax year), THE Logstead_API SHALL replace that row so that exactly one Entered_Total_Row remains for each imported line.
5. WHEN Schedule E Import creates a transaction, THE Logstead_API SHALL set `imported = true` through the service create path, which remains available only to internal callers.
6. WHEN the Repairs_Page edits or syncs the Entered_Total, THE Logstead_API SHALL preserve the row's `imported` marker as stated in Requirements 8.4 and 9.5.

### Requirement 20: Backups carry the imported marker

**User Story:** As the property owner, I want a restored backup to keep imported rows marked as imported, so that a later re-import replaces them and totals are not double counted.

#### Acceptance Criteria

1. THE Logstead_API SHALL export `imported` for each transaction in the backup document while keeping `schema_version` equal to `"1"`.
2. WHEN a backup document lacks `imported` on a transaction, THE Logstead_API SHALL restore it with `imported = false`.
3. IF a backup transaction carries `imported` that is not a boolean, THEN THE Logstead_API SHALL reject the restore with a validation error identifying the `imported` field and SHALL write nothing.
4. IF a backup transaction has both `imported = true` and `itemized = true`, THEN THE Logstead_API SHALL reject the restore with a validation error identifying the `itemized` field and SHALL write nothing.
5. FOR ALL valid states, exporting a backup and restoring it SHALL reproduce the same `imported` marker on every transaction (round-trip property).
6. WHEN a backup that contains imported rows has been restored and Schedule E Import re-imports the same (property, tax year), THE Logstead_API SHALL replace the restored imported rows without leaving a duplicate Entered_Total_Row.
