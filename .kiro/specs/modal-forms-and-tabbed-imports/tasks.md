# Implementation Plan: Modal Forms and Tabbed Imports

## Overview

Frontend-only change in two independent halves that share a few small pieces. First, the Loans and Depreciable Assets pages move their add/edit forms into a shared `RecordModal`, driven by a small pure reducer (`useRecordModal`) and a server-error dismissal helper. Second, the two Schedule E import pages become route-based tabs under one `Import` primary-nav entry, with a layout route, an `IMPORT_NAV` config, and tab styles shared with `PropertySectionTabs`. No backend, API, or dependency change.

Tasks are ordered so shared units land first, then the consumers (forms, pages, routes). Each task cites the requirement(s) it satisfies. Test sub-tasks are marked optional with `*`; core implementation tasks are never optional. The design includes Correctness Properties for the modal reducer and the error dismissal helper only, so those get property-based tests with `fast-check` (already installed, 100 runs minimum). Everything else uses example-based tests with Vitest, React Testing Library, and `vitest-axe`.

## Tasks

- [x] 1. Update the navigation model and shared tab styles
  - [x] 1.1 Add `IMPORT_NAV`, collapse the import entries, and extract tab styles
    - In `frontend/src/components/navConfig.ts`, replace the "Import Schedule E" and "Import from PDF" entries of `PRIMARY_NAV` with one `{ to: "/imports/schedule-e", label: "Import" }` entry (no `end`, so it stays active on the PDF route).
    - Add `export const IMPORT_NAV: readonly NavItem[]` with `{ to: "/imports/schedule-e", label: "Enter manually", end: true }` then `{ to: "/imports/schedule-e/extract", label: "Upload PDF" }`.
    - Create `frontend/src/components/sectionTabStyles.ts` exporting `sectionTabClassName(isActive: boolean): string` that returns exactly the class string `PropertySectionTabs` builds today.
    - Change `frontend/src/components/PropertySectionTabs.tsx` to call `sectionTabClassName` with no visual change.
    - _Requirements: 10.2, 10.5, 10.6, 11.1, 11.2, 11.3, 11.4_

  - [x] 1.2 Update `navConfig.test.ts`
    - Replace the two-entry expectation with the single `["/imports/schedule-e", "Import"]` entry and assert the old labels are absent.
    - Assert `IMPORT_NAV` lists "Enter manually" (with `end: true`) then "Upload PDF" in order.
    - Re-run `PropertySectionTabs.test.tsx` to confirm the extracted styles changed nothing.
    - _Requirements: 10.2, 10.5, 11.1, 11.2_

- [x] 2. Build the Imports section
  - [x] 2.1 Create `ImportSectionTabs` and `ImportsLayout`
    - Create `frontend/src/components/ImportSectionTabs.tsx`: `nav[aria-label="Import methods"]` with a `ul` of `NavLink`s built from `IMPORT_NAV`, using `end={item.end}` and `sectionTabClassName`, mirroring `PropertySectionTabs` structure (`mt-4`, `flex flex-wrap gap-2`).
    - Create `frontend/src/pages/ImportsLayout.tsx`: `<section aria-labelledby="page-heading">` with `<h1 id="page-heading">Import Schedule E</h1>`, `<ImportSectionTabs />`, and `<div className="mt-6"><Outlet /></div>`.
    - _Requirements: 9.1, 9.2, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 2.2 Wire the routes and trim the two import pages
    - In `frontend/src/App.tsx`, replace the two flat import routes with a layout route `imports` (element `ImportsLayout`) containing an index route `<Navigate to="/imports/schedule-e" replace />`, `schedule-e` (`ScheduleEImportPage`), and `schedule-e/extract` (`ScheduleEExtractionPage`). Update the route-table doc comment to describe the Imports section and add the `/imports` redirect.
    - In `ScheduleEImportPage.tsx` and `ScheduleEExtractionPage.tsx`, replace the root `<section aria-labelledby>` with a `<div>` and remove each page's `<h1>`. Keep the intro text, notes, form slot, and the `aria-live` slot unchanged. Update the file-header comments to say each page is a tab of the Imports section.
    - Leave `ExtractionStatus` links to `/imports/schedule-e` as they are.
    - _Requirements: 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 11.5, 12.1, 12.2, 12.3, 12.4, 12.5, 13.4_

  - [x] 2.3 Write tests for `ImportSectionTabs`
    - New `ImportSectionTabs.test.tsx`: landmark name "Import methods"; two links in order; `aria-current="page"` on the active tab only at each route (PDF route does not mark Manual); Tab and Enter navigate; classes equal `sectionTabClassName` output; `vitest-axe` has no violations.
    - _Requirements: 9.2, 10.1, 10.2, 10.3, 10.4, 10.6_

  - [x] 2.4 Write routing tests for the Imports section
    - New test using `MemoryRouter` with the real route table: `/imports` redirects to `/imports/schedule-e`; both deep links show the matching tab and content; heading sits above the tabs; switching tabs shows the destination in its initial state and discards typed entries; history back returns to the previous tab; the "enter your Schedule E manually" link from an extraction failure lands on the Manual tab; `/imports/foo` shows NotFound.
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 11.5_

  - [x] 2.5 Update existing tests for the new layout
    - `ScheduleEExtractionPage.test.tsx` and any test that queries the removed per-page `<h1>`: drop or move those assertions to the layout heading.
    - `AppLayout.test.tsx`: assert one "Import" link in the desktop and mobile navs, marked active on both import routes, and no "Import Schedule E" or "Import from PDF" links.
    - Confirm `ExtractionStatus.test.tsx`, `ScheduleEImportForm` tests, and extraction flow tests stay green unchanged.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 12.1, 12.2, 13.2, 13.3_

- [x] 3. Checkpoint - Imports section
  - Run `cd frontend && npm test -- --run` and `npm run build`. Ensure all tests pass, ask the user if questions arise.

- [x] 4. Build the shared modal pieces
  - [x] 4.1 Add `useDismissibleErrors`
    - Create `frontend/src/lib/useDismissibleErrors.ts` exporting the pure `omitDismissed(errors, dismissed)` and the hook `useDismissibleErrors(serverErrors)` returning `{ errors, dismiss }`. The dismissed set resets whenever the `serverErrors` object identity changes (store-previous-prop pattern, no effect).
    - _Requirements: 5.5_

  - [x] 4.2 Write property test for `omitDismissed`
    - **Property 4: Editing a field dismisses exactly that field's server error**
    - New `lib/useDismissibleErrors.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: modal-forms-and-tabbed-imports, Property 4: Editing a field dismisses exactly that field's server error`.
    - **Validates: Requirements 5.5**

  - [x] 4.3 Add `RecordModal`
    - Create `frontend/src/components/ui/RecordModal.tsx` wrapping `@radix-ui/react-dialog` with the props in the design (`open`, `onOpenChange`, `title`, `description`, `children`, `dismissible`, `onCloseAutoFocus`). Use the existing overlay and panel tokens plus `max-h-[90vh] overflow-y-auto`.
    - When `dismissible` is false, prevent default on `onEscapeKeyDown` and `onInteractOutside`. Also prevent default in `onInteractOutside` when the target is inside `[role="region"][aria-label^="Notifications"]` (the toast viewport).
    - Export it from `components/ui/index.ts`.
    - _Requirements: 4.2, 4.3, 4.6, 6.1, 6.2, 6.3, 6.6, 6.7, 6.8, 8.1, 8.3, 8.4_

  - [x] 4.4 Add `recordModalReducer` and `useRecordModal`
    - Create `frontend/src/components/ui/useRecordModal.ts` with the `RecordModalState` / `RecordModalAction` types, the pure `recordModalReducer`, and `useRecordModal(records, { fallbackFocusRef })` returning `state`, `open`, `editing` (derived by id), `openAdd`, `openEdit`, `close`, `onRecordDeleted`, and `handleCloseAutoFocus`.
    - `openAdd` / `openEdit` capture `document.activeElement`. `handleCloseAutoFocus` prevents default, focuses the trigger when `isConnected`, otherwise focuses `fallbackFocusRef.current`. `open` is false in edit mode when the record is not in the list.
    - Export it from `components/ui/index.ts`.
    - _Requirements: 2.1, 2.2, 3.1, 3.7, 3.8, 4.1, 6.4, 6.5, 8.1_

  - [x] 4.5 Write property test for opening the modal
    - **Property 1: Opening the modal is independent of prior state**
    - New `components/ui/useRecordModal.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: modal-forms-and-tabbed-imports, Property 1: Opening the modal is independent of prior state`.
    - **Validates: Requirements 2.1, 3.1, 3.7**

  - [x] 4.6 Write property test for close
    - **Property 2: Close always ends closed and is idempotent**
    - Add to `useRecordModal.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 2.4, 3.4, 4.1, 4.2, 4.3**

  - [x] 4.7 Write property test for record deletion
    - **Property 3: Deleting a record closes the modal only when that record is being edited**
    - Add to `useRecordModal.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 3.8**

  - [x] 4.8 Write component tests for `RecordModal` and `useRecordModal`
    - `RecordModal.test.tsx`: `role="dialog"` with name and description; focus moves inside on open and Tab stays inside; background hidden from role queries; Escape and outside click close when dismissible and are ignored when not; a click inside the toast viewport does not close it; `max-h-[90vh]` and `overflow-y-auto` classes present; imported from `components/ui`; `vitest-axe` clean.
    - `useRecordModal.test.tsx`: `editing` derives from the list; missing edit target reports `open` false; `handleCloseAutoFocus` focuses a connected trigger and falls back to the heading when the trigger is detached.
    - _Requirements: 3.8, 4.2, 4.3, 4.6, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 8.1, 8.4_

- [x] 5. Update the forms for modal use
  - [x] 5.1 Update `LoanForm` for dismissible server errors
    - In `frontend/src/components/loans/LoanForm.tsx`, route `serverErrors` through `useDismissibleErrors` and call `dismiss(field)` from `setField`. Keep client-error merging, the preview, anchor help, labels, defaults, and the form-level alert unchanged.
    - _Requirements: 2.7, 5.1, 5.2, 5.5, 5.6, 7.1, 7.2, 7.3_

  - [x] 5.2 Update `AssetForm` and `AssetList`
    - In `frontend/src/components/assets/AssetForm.tsx`, add the optional `formError` prop rendered as a `role="alert"` paragraph above the first field, route `fieldErrors` through `useDismissibleErrors`, and call `dismiss(field)` from each field's change handler.
    - In `frontend/src/components/assets/AssetList.tsx`, change the empty-list message so it no longer refers to a form above.
    - _Requirements: 1.6, 5.1, 5.2, 5.5_

  - [x] 5.3 Write form tests
    - `LoanForm.test.tsx` and `AssetForm.test.tsx`: editing a field with a server error removes that message and leaves others; a new `serverErrors` / `fieldErrors` object re-shows it; `AssetForm` shows `formError` in `role="alert"`; existing validation, preview, and default tests stay green.
    - `AssetList.test.tsx` (create if absent): empty message does not mention "form above".
    - _Requirements: 1.6, 5.2, 5.5, 5.6, 7.1, 7.2_

- [x] 6. Convert the Loans and Assets pages to modals
  - [x] 6.1 Rework `LoansPage`
    - Remove the inline "Add loan / Edit loan" section, `editing` state, `formHeadingRef`, and the `"form"` focus target. Use `useRecordModal(loans, { fallbackFocusRef: listHeadingRef })`.
    - Add an "Add loan" `Button` beside the "All loans" heading, shown only when not loading, no load error, and at least one loan. Wire `LoanList.onCreate` to `openAdd` and `onEdit` to `clearErrors` then `openEdit`.
    - Render `RecordModal` with titles "Add loan" / "Edit loan", `dismissible={!submitting}`, `onCloseAutoFocus={modal.handleCloseAutoFocus}`, and `LoanForm` (keyed by record id, `onCancel` always set). `closeModal()` clears errors then closes.
    - On save success call `modal.close()`, refresh impact and the selected schedule, and toast "Loan added" / "Loan updated". Add an effect (notify read through a ref) that toasts "Could not save the loan" when `errors.form` is the only error key. `confirmDelete` calls `modal.onRecordDeleted` and keeps focusing the "All loans" heading.
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.6, 6.4, 6.5, 7.1, 7.3, 7.4, 7.5, 8.2_

  - [x] 6.2 Rework `AssetsPage`
    - Remove the inline "Add asset / Edit asset" section and `editing` state. Add `listHeadingRef` (`tabIndex={-1}`) on the "Assets" heading and use `useRecordModal(assets, { fallbackFocusRef: listHeadingRef })`.
    - Add an "Add asset" `Button` beside the heading (same visibility rule). Empty state `StateBlock` gets new copy and `action={{ label: "Add asset", onClick: modal.openAdd }}`.
    - Render `RecordModal` ("Add asset" / "Edit asset", `dismissible={!submitting}`) around `AssetForm` with `fieldErrors`, `formError` (set only for no-field failures), and `onCancel` always set. `closeModal()` clears `fieldErrors` and `formError` then closes.
    - Add a separate `deleteError` state shown as a `role="alert"` under the list heading for delete failures. `confirmDelete` calls `modal.onRecordDeleted`.
    - Change `reload` so `loading` is set only until the first successful load for the current `propertyId`; later refreshes update `assets` in place so the row Edit button stays mounted. Keep the toasts "Asset added", "Asset updated", and "Could not save the asset", and keep the expanded-schedule refresh after an update.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 6.4, 6.5, 8.2_

  - [x] 6.3 Update and extend `LoansPage.test.tsx`
    - Update helpers that assume an always-visible form (for example `submitButton()`).
    - Cover: empty state action; table plus Add button; no form while closed; loading and load-error hide Add; Add opens an empty modal with today's anchor date; Edit opens a prefilled modal; create and update success close, reload, and toast; field error and form-level error keep the modal open with values retained; non-field failure toasts; Cancel, Escape, and backdrop close without a save call; errors cleared after close and reopen; pending save disables inputs and ignores Escape; focus returns to the Add and Edit triggers and falls back to the "All loans" heading when the empty-state trigger is gone; preview and anchor help inside the modal; notices and schedule outside the modal; update refreshes schedule and Line 12 impact; delete still returns focus to "All loans".
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.4, 3.5, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.6, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 13.1, 13.3_

  - [x] 6.4 Update and extend `AssetsPage.test.tsx`
    - Update tests that assume an inline form. Cover the same scenarios as the Loans page for Assets: empty state copy (no "form above") and action; table plus Add button; Add and Edit modals with correct names; success paths and toasts; field error, form-level error, and non-field toast; retained values; Cancel, Escape, backdrop; errors cleared on close; pending save; focus return and heading fallback; expanded schedule refreshes after an update; delete failure shows the `deleteError` alert; refresh after save keeps the table mounted.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.4, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 6.4, 6.5, 13.1, 13.3_

- [x] 7. Update documentation
  - [x] 7.1 Describe the consolidated Imports section in the docs
    - `docs/developer-guide.md`: mention the Imports section (`ImportsLayout`, `ImportSectionTabs`, `IMPORT_NAV`) and the `RecordModal` pattern in the frontend notes, and fix the "Year-end Schedule E model" bullet so it says only the legacy expense-import (`ImportReview`) is unrouted while Schedule E import is reachable from the Import nav entry.
    - `docs/api.md` and `docs/architecture.md`: clarify that the "no import screen" notes refer to the expense-import routes, not the Schedule E import.
    - _Requirements: 12.5, 13.4_

- [x] 8. Final checkpoint - Ensure all tests pass
  - Run `cd frontend && npm test -- --run` and `npm run build` (type-check and build must both pass). Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster path. Core implementation tasks and checkpoints are not optional.
- Each task references the specific requirement clauses it satisfies for traceability.
- Property tests cover only the modal reducer and the error dismissal helper. All other behavior uses example-based tests, because it is UI wiring, routing, or focus behavior.
- Non-goals respected: no backend or API change, no new dependency, no change to the Transactions, Properties, or Businesses dialogs, and the legacy expense-import stays unrouted.
- Tab switching in the Imports section discards unsaved entries by design (confirmed assumption).
- Safari and Firefox on macOS may not focus a button on click, so focus return can fall back to the list heading there. Radix has the same limitation for existing dialogs.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "4.3"] },
    { "id": 1, "tasks": ["1.2", "2.1", "4.2", "4.4", "5.1", "5.2"] },
    { "id": 2, "tasks": ["2.2", "2.3", "4.5", "4.8", "5.3", "6.1", "6.2"] },
    { "id": 3, "tasks": ["2.4", "2.5", "4.6", "6.3", "6.4", "7.1"] },
    { "id": 4, "tasks": ["4.7"] }
  ]
}
```
