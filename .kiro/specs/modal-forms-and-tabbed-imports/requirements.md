# Requirements Document

## Introduction

This feature makes two frontend layout changes that reclaim screen space and remove duplicate navigation.

1. **Modal add/edit forms.** The per-property Loans page and the per-property Depreciable Assets page render their add/edit form inline, above the table. The form occupies the top of the page even when the user only wants to review existing records. After this change each page shows only its table when records exist (or an empty state with an Add button when none exist). An Add button opens a modal dialog that contains the form, and the row Edit action opens the same modal prefilled.

2. **Tabbed import section.** The app has two separate primary-nav entries for importing a prior year's Schedule E: "Import Schedule E" (manual guided form, `/imports/schedule-e`) and "Import from PDF" (upload and auto-extract, `/imports/schedule-e/extract`). After this change one "Import" nav entry leads to a single Imports section with two tabs, mirroring the route-based tab pattern of the per-property section tabs (`PropertySectionTabs`).

### Findings from the existing code

- **Loans** (`pages/LoansPage.tsx`, `components/loans/LoanForm.tsx`, `LoanList.tsx`): the form is always visible in an "Add loan" / "Edit loan" section above the "All loans" table. The form shows a live Loan_Preview, shows server field errors passed from `useLoans`, and `LoanList` already renders an empty state with an "Add loan" action.
- **Depreciable assets** (`pages/AssetsPage.tsx`, `components/assets/AssetForm.tsx`, `AssetList.tsx`): same layout. The empty state tells the user to use "the form above", and `AssetList` has its own plain-text empty message that also refers to the form above. Server field errors and a form-level error are held in page state.
- **Transactions** (`pages/TransactionsPage.tsx`) already uses a Radix dialog with an "Add transaction" button. It is the closest existing precedent for this feature and needs no change.
- **Properties and Businesses** already use dialogs (`AddPropertyDialog`, `EditPropertyDialog`, `AddBusinessDialog`, `EditBusinessDialog`). They need no change.
- **Shared primitives**: `components/ui` has `ConfirmDialog` (a Radix Dialog wrapper that supplies focus trap, Escape to close, and focus return) and `StateBlock` (empty state with an action). There is no generic form dialog primitive; each existing add/edit dialog hand-rolls the `@radix-ui/react-dialog` markup.
- **Usage**: no always-visible usage form exists in `frontend/src`. Usage days appear only as read-only values in the report header. Usage is therefore not a candidate.
- **Remaining inline forms** are inline cell editors (`ScheduleTable` override editor, `InterestOverrideControl`, `PastYearOverrideForm`). These edit a single value in context and are not candidates.
- **Imports**: `App.tsx` registers `imports/schedule-e` (`ScheduleEImportPage`) and `imports/schedule-e/extract` (`ScheduleEExtractionPage`). `PRIMARY_NAV` lists both as separate entries. `ExtractionStatus` links back to `/imports/schedule-e` for the failure outcomes.
- **Tab pattern**: `PropertySectionTabs` is a `nav[aria-label="Property sections"]` containing a list of `NavLink`s. Each tab is a distinct route; the active link gets `aria-current="page"`. It is not an ARIA `tablist`.

### Flag: the `/imports` expense-import routes

`docs/api.md` and `docs/developer-guide.md` note that the backend `/imports` routes (`POST /imports`, `GET /imports/{sessionId}`, drafts, confirm) are not surfaced in the UI. Investigation confirms this. `ImportReviewPage` and `components/imports/ImportReview` exist but are **not registered in `App.tsx`**, and no nav entry reaches them. They are the legacy expense-summary PDF import, not Schedule E. The user's phrase "import from pdf" matches the Schedule E PDF extraction page (the nav entry labelled "Import from PDF"), not this legacy flow. This spec therefore merges only the two Schedule E import pages and leaves the legacy expense import unrouted (see Requirement 12).

### Assumptions

- The two modal pages are Loans and Depreciable Assets. Transactions, Properties, and Businesses already use dialogs.
- The tab pattern to mirror is the route-based `PropertySectionTabs` pattern, so each tab keeps its own URL and the browser Back button and deep links work.
- Existing import URLs stay valid: `/imports/schedule-e` is the manual tab and `/imports/schedule-e/extract` is the PDF tab.
- Backend APIs are unchanged.

### Open questions for confirmation

1. **Scope of "things like loans and depreciable assets".** No other page with an always-visible inline add form was found. Confirm that Loans and Depreciable Assets are the full scope.
2. **Default tab.** Requirement 9 makes the manual form the default tab (the `/imports` redirect target) because it is the existing `/imports/schedule-e` destination. Confirm, or choose the PDF tab as the default.
3. **Unsaved data on tab switch.** Because each tab is a route, switching tabs unmounts the other tab. Requirement 9 states that in-progress entries are not preserved. Confirm, or ask for preservation.
4. **Legacy expense import.** Confirm that it stays out of scope.

## Glossary

- **Logstead**: The rental-property Schedule E tracking application.
- **Loans_Page**: The per-property page at `/properties/:propertyId/loans` that lists Loans and shows the yearly schedule of the selected Loan.
- **Assets_Page**: The per-property page at `/properties/:propertyId/assets` that lists Depreciable_Assets and shows the depreciation schedule of the expanded asset.
- **Record_Page**: Either the Loans_Page or the Assets_Page.
- **Loan**: A mortgage loan record belonging to one property.
- **Depreciable_Asset**: A depreciable asset record belonging to one property.
- **Record**: A Loan or a Depreciable_Asset.
- **Record_Table**: The table of Records on a Record_Page (`LoanList` or `AssetList`).
- **Record_Form**: The add/edit form for a Record (`LoanForm` or `AssetForm`).
- **Record_Modal**: A modal dialog built on `@radix-ui/react-dialog` that contains a Record_Form.
- **Add_Button**: The button on a Record_Page that opens the Record_Modal in add mode.
- **Edit_Action**: The per-row Edit button in the Record_Table that opens the Record_Modal in edit mode.
- **Empty_State**: The `StateBlock` of kind `empty` shown when a property has no Records.
- **Server_Field_Error**: A field-level validation message returned by the backend for a rejected save (HTTP 400 with a `field` and `message`).
- **Loan_Preview**: The live display of remaining payments and projected payoff date inside the Loan form (`data-testid="loan-preview"`).
- **Trigger_Element**: The element that had focus when the Record_Modal opened (the Add_Button or the row Edit_Action).
- **Imports_Section**: The consolidated import area that contains the Import_Tabs.
- **Import_Tabs**: The navigation of two tabs inside the Imports_Section, one for each import method.
- **Manual_Tab**: The tab that hosts the guided manual Schedule E form (`ScheduleEImportPage` content).
- **PDF_Tab**: The tab that hosts the Schedule E PDF upload and extraction flow (`ScheduleEExtractionPage` content).
- **Primary_Nav**: The app-level navigation built from `PRIMARY_NAV` and rendered by `MainNav` in the desktop sidebar and the mobile navigation dialog.
- **Property_Section_Tabs**: The existing `PropertySectionTabs` component, a `nav[aria-label="Property sections"]` of `NavLink` items that serves as the reference pattern.

## Requirements

### Requirement 1: Record pages show the table without an inline form

**User Story:** As a landlord, I want the Loans and Depreciable Assets pages to show my records without a form taking up the top of the page, so that I can review my data without scrolling past a form.

#### Acceptance Criteria

1. THE Loans_Page SHALL render no Record_Form in the page body while the Record_Modal is closed.
2. THE Assets_Page SHALL render no Record_Form in the page body while the Record_Modal is closed.
3. WHILE a property has at least one Record, THE Record_Page SHALL display the Record_Table as the primary content of the page.
4. WHILE a property has at least one Record, THE Record_Page SHALL display an Add_Button.
5. WHILE a property has no Records and the Records have loaded, THE Record_Page SHALL display the Empty_State with an action that opens the Record_Modal in add mode.
6. THE Empty_State of the Assets_Page SHALL describe adding an asset with the Add action and SHALL NOT refer to "the form above".
7. WHILE the Records are loading, THE Record_Page SHALL display the loading state and SHALL NOT display the Add_Button.
8. IF loading the Records fails, THEN THE Record_Page SHALL display the load error message and SHALL NOT display the Add_Button.

### Requirement 2: Add Records through a modal

**User Story:** As a landlord, I want an Add button that opens a form in a modal, so that I can add a loan or asset without the form taking up page space.

#### Acceptance Criteria

1. WHEN the user activates the Add_Button, THE Record_Page SHALL open the Record_Modal in add mode with an empty Record_Form.
2. WHEN the user activates the Empty_State action, THE Record_Page SHALL open the Record_Modal in add mode with an empty Record_Form.
3. THE Record_Modal in add mode SHALL have the accessible name "Add loan" on the Loans_Page and "Add asset" on the Assets_Page.
4. WHEN a create request succeeds, THE Record_Page SHALL close the Record_Modal.
5. WHEN a create request succeeds, THE Record_Page SHALL reload the Records and display the new Record in the Record_Table.
6. WHEN a create request succeeds, THE Record_Page SHALL display a success toast with the title "Loan added" on the Loans_Page and "Asset added" on the Assets_Page.
7. WHEN the Record_Modal opens in add mode, THE Record_Form SHALL show the same default values as the current inline form (for example the anchor date defaulting to today on the Loans_Page).

### Requirement 3: Edit Records through the same modal

**User Story:** As a landlord, I want Edit to open the same modal prefilled with the record, so that adding and editing feel the same.

#### Acceptance Criteria

1. WHEN the user activates the Edit_Action for a Record, THE Record_Page SHALL open the Record_Modal in edit mode with the Record_Form prefilled from that Record.
2. THE Record_Modal in edit mode SHALL have the accessible name "Edit loan" on the Loans_Page and "Edit asset" on the Assets_Page.
3. THE Edit_Action accessible name SHALL continue to include the Record description.
4. WHEN an update request succeeds, THE Record_Page SHALL close the Record_Modal, reload the Records, and display a success toast with the title "Loan updated" on the Loans_Page and "Asset updated" on the Assets_Page.
5. WHEN an update request succeeds for the Loan whose schedule is selected, THE Loans_Page SHALL refresh the displayed yearly schedule and the Line 12 impact.
6. WHEN an update request succeeds for the Depreciable_Asset whose schedule is expanded, THE Assets_Page SHALL refresh the displayed depreciation schedule.
7. WHEN the user opens the Record_Modal in add mode after editing a Record, THE Record_Form SHALL show empty default values and SHALL NOT retain the edited Record's values.
8. IF the Record being edited is deleted while the Record_Modal is open, THEN THE Record_Page SHALL close the Record_Modal.

### Requirement 4: Cancel and dismiss behavior

**User Story:** As a landlord, I want to back out of the modal without saving, so that I can abandon a form safely.

#### Acceptance Criteria

1. WHEN the user activates the Cancel button in the Record_Form, THE Record_Page SHALL close the Record_Modal without sending a save request.
2. WHEN the user presses Escape while the Record_Modal is open, THE Record_Page SHALL close the Record_Modal without sending a save request.
3. WHEN the user activates the modal backdrop, THE Record_Page SHALL close the Record_Modal without sending a save request.
4. WHEN the Record_Modal closes without a successful save, THE Record_Page SHALL clear the Server_Field_Errors and the form-level error.
5. WHILE a save request is in flight, THE Record_Form SHALL disable its inputs and its submit button.
6. WHILE a save request is in flight, THE Record_Modal SHALL remain open.

### Requirement 5: Error handling inside the modal

**User Story:** As a landlord, I want validation errors to appear next to my entries inside the modal, so that I can fix them without losing what I typed.

#### Acceptance Criteria

1. IF the backend rejects a save with a Server_Field_Error, THEN THE Record_Modal SHALL remain open and THE Record_Form SHALL display the message next to the named field.
2. IF the backend rejects a save with a form-level error, THEN THE Record_Modal SHALL remain open and THE Record_Form SHALL display the message in an element with `role="alert"` inside the Record_Modal.
3. IF a save fails with an error that has no field, THEN THE Record_Page SHALL display an error toast with the title "Could not save the loan" on the Loans_Page and "Could not save the asset" on the Assets_Page.
4. IF a save is rejected, THEN THE Record_Form SHALL retain every value the user entered.
5. WHEN the user edits a field that shows an error, THE Record_Form SHALL clear the message for that field.
6. THE Record_Form SHALL run the same client-side validation as the current inline form, and a failed validation SHALL keep the Record_Modal open.

### Requirement 6: Modal accessibility

**User Story:** As a keyboard or screen-reader user, I want the modal to behave like other dialogs in Logstead, so that I can use it without a mouse.

#### Acceptance Criteria

1. THE Record_Modal SHALL have `role="dialog"` with an accessible name from its title and an accessible description.
2. WHILE the Record_Modal is open, THE Record_Modal SHALL trap keyboard focus inside the dialog.
3. WHEN the Record_Modal opens, THE Record_Modal SHALL move focus to an element inside the dialog.
4. WHEN the Record_Modal closes, THE Record_Page SHALL return focus to the Trigger_Element.
5. IF the Trigger_Element is no longer in the document when the Record_Modal closes (for example after a Record is deleted), THEN THE Record_Page SHALL move focus to the Record_Page list heading.
6. WHILE the Record_Modal is open, THE Record_Page SHALL render the content behind the dialog as inert to assistive technology.
7. THE Record_Modal SHALL scroll its own content when the viewport height is smaller than the form, with a maximum height of 90vh, so that the submit and Cancel buttons remain reachable.
8. THE Record_Modal SHALL use the same overlay, panel, border, and shadow styling as the existing dialogs in `components/ui` and `components/properties`.

### Requirement 7: Loan-specific behavior in the modal

**User Story:** As a landlord, I want the live loan preview to keep working in the modal, so that I can check the payoff projection before saving.

#### Acceptance Criteria

1. WHILE the Record_Modal is open on the Loans_Page, THE Loan form SHALL display the Loan_Preview and SHALL update it on every change to a field the projection reads.
2. WHEN the required fields for a projection are incomplete or invalid, THE Loan form SHALL display no Loan_Preview.
3. THE Loan form SHALL display the anchor-balance help text inside the Record_Modal.
4. WHEN the Loans_Page deletes a Loan, THE Loans_Page SHALL continue to use the existing confirmation dialog and SHALL return focus to the "All loans" heading.
5. THE Loans_Page SHALL continue to display the estimate notice, the superseded-interest notice, and the yearly schedule of the selected Loan outside the Record_Modal.

### Requirement 8: Shared modal primitive

**User Story:** As a developer, I want one reusable form-modal component, so that both pages share behavior instead of duplicating Radix markup.

#### Acceptance Criteria

1. THE Logstead frontend SHALL provide a shared Record_Modal component in `components/ui` that wraps `@radix-ui/react-dialog` and accepts a title, a description, an open flag, an open-change handler, and the form as content.
2. THE Loans_Page and the Assets_Page SHALL both render the shared Record_Modal component.
3. THE shared Record_Modal component SHALL reuse the existing `Button`, focus-ring, and token classes and SHALL introduce no new dependency.
4. THE shared Record_Modal component SHALL be exported from `components/ui/index.ts`.

### Requirement 9: Combined Imports section with tabs

**User Story:** As a landlord, I want one Import section with a tab for each import method, so that I can find both without two separate menu items.

#### Acceptance Criteria

1. THE Imports_Section SHALL display a page heading "Import Schedule E" and the Import_Tabs above the active tab's content.
2. THE Import_Tabs SHALL contain exactly two tabs: "Enter manually" (Manual_Tab) and "Upload PDF" (PDF_Tab).
3. WHEN the user activates a tab, THE Imports_Section SHALL navigate to that tab's route and display that tab's content.
4. THE Imports_Section SHALL serve the Manual_Tab at `/imports/schedule-e`.
5. THE Imports_Section SHALL serve the PDF_Tab at `/imports/schedule-e/extract`.
6. WHEN a user opens `/imports/schedule-e` or `/imports/schedule-e/extract` directly, THE Imports_Section SHALL display the matching tab as active.
7. WHEN a user opens `/imports`, THE Imports_Section SHALL redirect to `/imports/schedule-e`.
8. WHEN the user switches tabs, THE Imports_Section SHALL display the destination tab in its initial state, and THE Imports_Section SHALL NOT preserve unsaved entries from the previous tab.
9. WHEN the user presses the browser Back button after switching tabs, THE Imports_Section SHALL display the previous tab.
10. THE Imports_Section SHALL render the page heading, intro text, and notes that the current pages render, with the intro text and notes belonging to the tab they describe.

### Requirement 10: Import tab accessibility and pattern parity

**User Story:** As a keyboard user, I want the import tabs to behave like the property tabs, so that navigation is predictable.

#### Acceptance Criteria

1. THE Import_Tabs SHALL render as a `nav` landmark with `aria-label="Import methods"` containing a list of `NavLink` items.
2. THE Import_Tabs SHALL use the same classes for active, inactive, hover, and focus-visible states as the Property_Section_Tabs.
3. THE Import_Tabs SHALL apply `aria-current="page"` to the active tab only.
4. THE Import_Tabs SHALL be reachable and operable by keyboard using Tab and Enter.
5. THE Import_Tabs SHALL derive its tab list from a single configuration constant in `navConfig.ts`, in the same way `PROPERTY_NAV` feeds the Property_Section_Tabs.
6. WHEN the PDF_Tab route is active, THE Import_Tabs SHALL mark only the PDF_Tab as active and SHALL NOT mark the Manual_Tab as active.

### Requirement 11: Primary navigation consolidation

**User Story:** As a landlord, I want a single Import entry in the main menu, so that the menu is shorter and clearer.

#### Acceptance Criteria

1. THE Primary_Nav SHALL contain one "Import" entry that links to `/imports/schedule-e`.
2. THE Primary_Nav SHALL NOT contain the "Import Schedule E" or "Import from PDF" entries.
3. WHILE the current route is `/imports/schedule-e` or `/imports/schedule-e/extract`, THE Primary_Nav SHALL mark the "Import" entry as active.
4. THE Primary_Nav SHALL render the same "Import" entry in the desktop sidebar and the mobile navigation dialog.
5. WHEN the user follows the manual-form link from the extraction failure or no-Schedule-E status messages, THE PDF_Tab SHALL navigate to `/imports/schedule-e` and THE Imports_Section SHALL display the Manual_Tab as active.

### Requirement 12: Import behavior is preserved

**User Story:** As a landlord, I want the import flows to work exactly as before inside the tabs, so that consolidation does not change what gets saved.

#### Acceptance Criteria

1. THE Manual_Tab SHALL render the existing `ScheduleEImportForm` and the depreciation-not-imported note without change to its validation, submission, or error routing.
2. THE PDF_Tab SHALL render the existing upload control, status poller, and review screen without change to the presign, upload, begin, poll, and confirm sequence.
3. THE Imports_Section SHALL NOT change any backend request or response.
4. THE PDF_Tab SHALL continue to pass the confirmed draft to the unchanged `importScheduleE` write path.
5. THE legacy expense-import components (`ImportReviewPage`, `components/imports/ImportReview`) SHALL remain unrouted and unchanged by this feature.

### Requirement 13: Regression coverage and documentation

**User Story:** As a maintainer, I want tests and docs to match the new layout, so that future changes do not regress it.

#### Acceptance Criteria

1. THE Logstead frontend test suite SHALL include tests for the Loans_Page and the Assets_Page that cover the empty state, opening the Record_Modal from the Add_Button and from the Edit_Action, closing after success, retaining the modal on a Server_Field_Error, and returning focus to the Trigger_Element.
2. THE Logstead frontend test suite SHALL include tests for the Imports_Section that cover tab rendering, active-tab marking, deep links to both routes, the `/imports` redirect, and the Primary_Nav entry.
3. THE existing tests that assert the inline form or the two nav entries SHALL be updated to the new behavior.
4. THE route table comment in `App.tsx` and the import references in `docs` SHALL describe the consolidated Imports_Section.
