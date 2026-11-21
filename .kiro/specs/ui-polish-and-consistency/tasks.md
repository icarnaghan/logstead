# Implementation Plan: UI Polish and Consistency

## Overview

Frontend-only change delivered in three phases. Each phase ends with a checkpoint and is independently shippable. Phase 1 lays foundations (type, spacing, and motion tokens, Button and Spinner, PageHeader, document title and route focus, FormField, StateBlock error variant, Skeletons, and the route table with the Axe_Suite). Phase 2 moves the five Legacy_Dialogs onto RecordModal and adds dirty-state protection, Error_Summary, Money_Input and Date_Input, first-load-only loading, Load_Error_Alert, toast improvements, and Undo for safe deletes. Phase 3 adds teal tokens and contrast fixes, branding, grouped navigation, the Property_Switcher, table upgrades, Transactions search, the progressive Dashboard with a checklist, an accessibility sweep, and documentation. No backend or API change.

Tasks follow the cross-phase dependency diagram in the design: Phase 1 tokens, Button, StateBlock, PageHeader, document title, FormField, and the route table come first. Phase 2 builds on Button `loading`, FormField, StateBlock error, and Skeleton. Phase 3 builds on `useFirstLoad`, the migrated dialogs, `Button` ghost and icon sizes, `Skeleton`, and `PageHeader`. Phases 1 and 2 use Semantic_Tokens only, so the Phase 3 teal change recolors them with no edits.

Each task cites the requirement clauses it satisfies. All tasks, including test sub-tasks, are required, as in the prior `modal-forms-and-tabbed-imports` spec (no `*` markers). Each of the design's 25 correctness properties is one `fast-check` property test (`numRuns: 100` minimum) placed right after the implementation it validates, tagged `// Feature: ui-polish-and-consistency, Property {n}: {title}`. All other behavior uses example-based tests with Vitest, React Testing Library, and `vitest-axe`.

## Tasks

- [x] 1. Phase 1 - Tokens, type scale, spacing, and motion
  - [x] 1.1 Add type scale, spacing, motion tokens, Reduced_Motion_Rule, and Toast keyframes
    - In `frontend/tailwind.config.js` add the type scale entries (`text-page-title`, `text-section-title`, `text-card-title`, `text-body`, `text-small`, `text-caption`) and spacing entries (`page-x`, `page-y`, `section`, `card`, `card-lg`), with the documentation comment block next to them.
    - Add `transitionDuration`, `transitionTimingFunction`, the `toast-in`, `toast-out`, `toast-swipe-out`, and `fade-in` keyframes, and the matching `animation` entries, all from the Motion_Tokens. Do not add `tailwindcss-animate`.
    - In `frontend/src/index.css` add `--motion-fast`, `--motion-base`, `--motion-slow`, `--motion-ease` on `:root` and the `prefers-reduced-motion: reduce` rule (1ms durations, one iteration, `scroll-behavior: auto`).
    - In `ToastProvider.tsx` replace `animate-in` and `animate-out` classes with the new `animate-toast-*` classes and the swipe classes.
    - Apply `text-page-title`, `text-section-title`, and the spacing names in `PageContainer` and `Card` only; page-level migration happens in task 5.
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.3, 2.5, 2.6_

  - [x] 1.2 Write the Tailwind-output configuration test
    - New test that runs PostCSS and Tailwind with the real config over the `ToastProvider` source and `index.css`, and asserts `.animate-toast-in`, `.animate-toast-out`, their `@keyframes`, and the `prefers-reduced-motion` rule with `1ms` are present.
    - Assert the type scale and spacing entries exist in the resolved config.
    - _Requirements: 1.1, 1.2, 1.3, 2.2, 2.3, 2.4_

- [x] 2. Phase 1 - Spinner and Button
  - [x] 2.1 Add `Spinner` and extend `Button`
    - Create `components/ui/Spinner.tsx` (`aria-hidden`, `focusable="false"`, `animate-spin`) and export it from `components/ui/index.ts`.
    - In `Button.tsx` add the `loading` prop (spinner centered over invisible-by-opacity children to keep width, `aria-busy="true"`, click and submit suppressed without `disabled`), the `ghost` variant, and the `icon` size (`h-9 w-9 p-0 max-md:h-11 max-md:w-11`). Add `max-md:min-h-11` to `sm` and `md`.
    - Add the development-only `console.warn` for an icon button without `aria-label`, `aria-labelledby`, or `title`, and a development warning for `loading` with `asChild`.
    - Keep existing variants, sizes, and call sites unchanged.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 2.2 Write tests for `Spinner` and `Button`
    - Cover loading (`aria-busy`, ignored click, form submit blocked, label still readable, same width class contract), ghost, icon size classes, the warning (fires once, silent with an accessible name), and unchanged existing variants. Update `Button.test.tsx` only by addition.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [x] 3. Phase 1 - PageHeader
  - [x] 3.1 Create `PageHeader` and rebuild `PropertySection` on it
    - Create `components/ui/PageHeader.tsx` with `title`, `description`, `meta`, `actions`, `breadcrumb`, `children`, and `headingId` (default `page-heading`). Render a `div` (not `header`), an `h1` with `id`, `tabIndex={-1}`, `text-page-title`, and `focus:outline-none`, the breadcrumb above, and actions end-aligned from `sm` up and below the title on narrow viewports.
    - Make `PropertySection` a thin wrapper around `PageHeader` (breadcrumb, title, `meta` for the property name, tabs as children).
    - Export from `components/ui/index.ts`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7, 1.4_

  - [x] 3.2 Write tests for `PageHeader` and `PropertySection`
    - Cover `h1` with `tabIndex=-1`, description in the muted token, actions and breadcrumb slots, the default `page-heading` id, and that existing `PropertySection` tests stay green. Run `vitest-axe`.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7_

- [x] 4. Phase 1 - Document title, route focus, and route announcement
  - [x] 4.1 Add `useDocumentTitle`
    - Create `lib/useDocumentTitle.ts` with `formatDocumentTitle` ("{page} - Logstead", or "Logstead" when empty) and the hook with two effects: one stores and restores the previous title on unmount, one sets the title whenever it changes.
    - _Requirements: 5.1, 5.2_

  - [x] 4.2 Add `RouteAnnouncer` and mount it in `AppLayout`
    - Create `components/RouteAnnouncer.tsx` exporting the pure `shouldHandleRouteChange(prevPath, nextPath, isInitial)` and the component. On a handled change, focus `main h1`, falling back to `#main-content`, and set the polite live region text (cleared, then set on the next animation frame) to the page title, falling back to "Logstead". Never move focus on the first run.
    - Render it once in `AppLayout` (`role="status"`, `aria-live="polite"`, `aria-atomic="true"`, `sr-only`).
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 4.3 Write property test for route-change handling
    - **Property 3: Route changes are handled only for pathname changes after the first render**
    - New `components/RouteAnnouncer.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 3: Route changes are handled only for pathname changes after the first render`.
    - **Validates: Requirements 5.5, 5.7**

  - [x] 4.4 Write tests for `useDocumentTitle` and `RouteAnnouncer`
    - Hook: format, restore on unmount, change while mounted. Announcer: focuses the `h1` after a path change, falls back to the main landmark, does not move focus on first render or on hash-only and search-only changes, announces the title, announces two identical titles in a row.
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

- [x] 5. Phase 1 - Migrate pages to PageHeader and document titles
  - [x] 5.1 Migrate Dashboard, Properties, Businesses, and detail pages
    - In `DashboardPage`, `PropertiesPage`, `PropertyDetailPage`, `BusinessesPage`, and `BusinessDetailPage` replace hand-built `h1` and section header markup with `PageHeader` and call `useDocumentTitle` using the titles in the design's migration table. PropertiesPage and BusinessesPage show the header action only when the list is non-empty; keep the current add dialogs mounted exactly as today until Phase 2.
    - Keep `<section aria-labelledby="page-heading">` wrappers so existing landmark queries still resolve.
    - _Requirements: 4.5, 4.6, 5.8, 1.4_

  - [x] 5.2 Migrate remaining pages
    - Do the same for `TransactionsPage`, `AssetsPage`, `LoansPage`, `ReportsPage` (via `PropertySection`), `CombinedReportsPage`, `CarryforwardPage`, `ProfilePage`, `ImportsLayout`, `ImportReviewPage`, and `NotFoundPage`. `ScheduleEImportPage` and `ScheduleEExtractionPage` keep no `h1`.
    - Replace `text-2xl` and other literal title sizes on pages with the Type_Scale names.
    - _Requirements: 4.5, 4.6, 5.8, 1.4_

  - [x] 5.3 Write the page conformance source-scan test
    - New test that reads every file in `frontend/src/pages/` and asserts: no `<h1` and no `text-2xl`; every page except `ScheduleEImportPage` and `ScheduleEExtractionPage` imports `PageHeader` (or `PropertySection`) and calls `useDocumentTitle` (directly or through `PropertySection`).
    - _Requirements: 4.5, 4.6, 5.8_

  - [x] 5.4 Update existing page tests for the new header markup
    - Fix `h1` and heading queries in page tests that relied on the old markup. Assert exactly one `h1` per rendered page where practical. Do not weaken existing assertions.
    - _Requirements: 4.5, 4.6_

- [x] 6. Phase 1 - FormField and Textarea
  - [x] 6.1 Create `FormField`
    - Create `components/ui/FormField.tsx` with the render-prop `children(control)`, `label`, `hint`, `error`, `required`, and optional ids generated with `useId`. Wire `htmlFor`, `aria-describedby` (hint and error ids that are present), `aria-required`, and `aria-invalid` (set only while an error exists); render the error with `role="alert"` and the required marker with `aria-hidden`.
    - Export `FieldControlProps` and `FormField` from `components/ui/index.ts`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 6.2 Create `Textarea` and make form controls accept `invalid`
    - Create `components/ui/Textarea.tsx` mirroring `Input` (same classes, `invalid`, `FOCUS_RING`, `max-md:min-h-11`). Ensure `Input` and `Select` accept `invalid` and add `max-md:min-h-11`. Export from `components/ui/index.ts`.
    - _Requirements: 6.1, 6.4, 6.7_

  - [x] 6.3 Adopt `FormField` in `LoanForm`, `AssetForm`, `TransactionForm`, and `ProfilePage`
    - Replace hand-built label, hint, and error markup with `FormField` (and `Textarea` for the transaction notes). Keep radio groups as `fieldset` and `legend`. Wrap the `ProfilePage` backup file input in `FormField` with a hint naming the accepted file type. Keep validation logic, defaults, previews, and form-level alerts unchanged.
    - _Requirements: 6.7_

  - [x] 6.4 Write tests for `FormField`, `Textarea`, and the adopted forms
    - `FormField`: label association, hint linking, required marker hidden from assistive technology plus `aria-required`, error with `role="alert"` plus `aria-invalid` plus describedby, no `aria-invalid` without an error, unique generated ids across two instances. `Textarea` parity with `Input`. Update `LoanForm`, `AssetForm`, `TransactionForm`, and `ProfilePage` tests only for changed markup. Run `vitest-axe`.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

- [x] 7. Phase 1 - StateBlock error variant and Skeleton set
  - [x] 7.1 Add the `error` variant to `StateBlock`
    - Add `kind="error"` with `role="alert"`, a danger icon, title, message (`description`), `onRetry`, `retrying`, and `compact`. Use `border-danger bg-danger-subtle`, `text-fg`, and `text-fg-muted`. The Retry `Button` is `loading` while `retrying` is true or while the promise returned by `onRetry` is unresolved. Loading shows `Spinner` plus the title and keeps `role="status"`; empty actions use `Button`. Keep existing loading and empty call sites unchanged.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 7.2 Create the Skeleton set and `ResponsiveTable` first-load rendering
    - Create `components/ui/Skeleton.tsx` with `Skeleton` (`aria-hidden`, `bg-surface-muted animate-pulse motion-reduce:animate-none`), `LoadingRegion` (`role="status"`, `aria-busy="true"`, `aria-label`), `TableSkeleton` (`rows` default 5, `columns`), `TileSkeleton`, and `ChartSkeleton`. Export from `components/ui/index.ts`.
    - Add a `loading` prop to `ResponsiveTable` that renders `TableSkeleton` in place of rows. No other `ResponsiveTable` change in this phase.
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 7.3 Write tests for `StateBlock` error and the Skeleton set
    - StateBlock: error markup and `role="alert"`, Retry calls `onRetry`, Retry shows loading while the promise is pending and when `retrying` is set, compact layout, loading and empty unchanged. Skeleton: `aria-hidden`, `motion-reduce:animate-none` class, `LoadingRegion` attributes, configured row and column counts, `ResponsiveTable` `loading` renders the skeleton. Run `vitest-axe`.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 8. Phase 1 - Route table and Axe_Suite
  - [x] 8.1 Extract `APP_ROUTES` and render with `useRoutes`
    - Create `frontend/src/routes.tsx` exporting `APP_ROUTES` (same routes as `App.tsx` today) and `leafPaths(routes, base?)`. Mark redirect-only routes with `handle: { redirect: true }` so `leafPaths` skips them. `App.tsx` becomes `useRoutes(APP_ROUTES)`. Behavior is unchanged; keep the route-table doc comment.
    - _Requirements: 25.7_

  - [x] 8.2 Create the Axe_Suite
    - Create `src/test/apiStub.ts` (fetch stub from path patterns to canned JSON, unmatched paths return an empty array) and `src/test/fixtures.ts` (one property, one business, one transaction with categories, one asset, one loan with a schedule, dashboard summary, trends series, reports, carryforward reconciliation).
    - Create `src/test/axeRoutes.test.tsx`: derive paths with `leafPaths(APP_ROUTES)`, fill parameters from a `SAMPLE_PARAMS` table (fail with the route name when a parameter has no sample), render the `*` route at `/no-such-page`, and for each route and each theme (toggle the `dark` class on `document.documentElement`) wait for the page `h1`, assert exactly one `h1`, and run `axe` with `color-contrast` disabled.
    - _Requirements: 25.6, 25.7, 4.6_

  - [x] 8.3 Write tests for `leafPaths`
    - Cover nested routes, index routes, skipped redirects, parameterized paths, and the catch-all route.
    - _Requirements: 25.7_

- [x] 9. Checkpoint - Phase 1 shippable
  - Run `cd frontend && npm test -- --run` and `npm run build`. Confirm the Axe_Suite passes for all routes in both themes and the Tailwind configuration test passes. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Phase 2 - Dirty state and discard confirmation
  - [x] 10.1 Add the dirty helper
    - Create `lib/dirty.ts` with `FormValues`, `isDirty(initial, current)` (strict equality, same key set, no trimming), and `useDirtyReporter(initial, current, onDirtyChange)` which reports changes of the derived value and reports false on unmount.
    - _Requirements: 10.1, 10.7_

  - [x] 10.2 Write property test for `isDirty`
    - **Property 1: Dirty state is exactly "values differ"**
    - New `lib/dirty.property.test.tsx` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 1: Dirty state is exactly "values differ"`.
    - **Validates: Requirements 10.1**

  - [x] 10.3 Write property test for edit and restore
    - **Property 2: Editing and then restoring returns to clean**
    - Add to `lib/dirty.property.test.tsx`, rendering a tiny harness for `useDirtyReporter`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 10.7**

  - [x] 10.4 Add `useDiscardGuard`
    - Create `components/ui/useDiscardGuard.ts` returning `requestClose()` (closes immediately when clean, otherwise opens the confirmation) and `discard: { open, onConfirm, onCancel }`. Export from `components/ui/index.ts`.
    - _Requirements: 10.2, 10.3, 10.4, 10.5_

  - [x] 10.5 Extend `useRecordModal` and `RecordModal` with the discard guard
    - Add `dirty`, `setDirty`, `requestClose`, and `discard` to `useRecordModal`. `close()` stays a force close and resets `dirty`; `openAdd` and `openEdit` reset `dirty`. Existing members are unchanged.
    - Add the optional `discard` prop to `RecordModal`, rendering a sibling `ConfirmDialog` titled "Discard changes?" with the description, "Discard" (destructive) and "Keep editing" labels from the design. `dismissible={false}` still blocks Escape and outside clicks.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 10.6 Write tests for the discard flow
    - In `RecordModal.test.tsx` and `useRecordModal.test.tsx` (additions only): all four close paths (Escape, backdrop, close icon, Cancel) with a dirty form show the confirmation and keep the modal open; confirm closes and discards; Keep editing retains edits and returns focus; clean close shows no confirmation; successful save closes without confirmation; the toast-viewport outside-click guard still works with the stacked dialog.
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 11. Phase 2 - Wire form dirty reporting on Loans and Assets
  - [x] 11.1 Add `onDirtyChange` to `LoanForm` and `AssetForm` and wire the pages
    - Give `LoanForm` and `AssetForm` an `onDirtyChange?: (dirty: boolean) => void` prop that uses `useDirtyReporter` on their string values. In `LoansPage` and `AssetsPage` pass `modal.setDirty`, set `onOpenChange={(next) => { if (!next) modal.requestClose(); }}`, `discard={modal.discard}`, and `onCancel={modal.requestClose}`.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 11.2 Write tests for Loans and Assets discard behavior
    - For each page: edit a field then close by each path shows "Discard changes?"; restoring the original value then closing does not; saving closes without the prompt; existing page tests stay green.
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

- [x] 12. Phase 2 - Imports tab guard and beforeunload
  - [x] 12.1 Add the Imports dirty context, tab guard, and `beforeunload`
    - In `ImportsLayout` provide `ImportsDirtyContext` (`{ dirty, setDirty }`, default no-op). `ScheduleEImportForm` reports dirty against a snapshot of `{ taxYear, entries }` taken at mount through `useDirtyReporter`.
    - In `ImportSectionTabs`, the `NavLink` `onClick` calls `preventDefault()` and opens the Discard_Confirmation when `dirty` is true and the target differs from the current route; confirming clears `dirty` and navigates; clean switches are unchanged.
    - Add `useBeforeUnloadWhen(dirty)` that adds a `beforeunload` listener (`preventDefault()` and `returnValue`) while dirty and removes it when clean or on unmount.
    - _Requirements: 10.8, 10.9, 10.10_

  - [x] 12.2 Write tests for the Imports guard
    - Dirty form: tab click shows the confirmation and stays on the tab until confirmed; Keep editing retains entries; clean form switches without confirmation; extraction-seeded form is clean until edited; listener added while dirty and removed when clean or unmounted. Existing `ImportSectionTabs` and routing tests stay green.
    - _Requirements: 10.8, 10.9, 10.10_

- [x] 13. Phase 2 - Error_Summary and focus first invalid field
  - [x] 13.1 Create `formErrors.ts`, `ErrorSummary`, and `useFocusFirstInvalid`
    - Create `lib/formErrors.ts` with `ErrorSummaryItem`, `orderedErrors`, and `firstInvalidField`. Create `components/ui/ErrorSummary.tsx` (renders nothing when empty; otherwise `role="alert"`, an `h2` with the singular or plural count, field items as link-styled buttons that focus `idFor(field)`, field-less items as plain text). Add `useFocusFirstInvalid({ errors, order, idFor, attempt })`. Export from `components/ui/index.ts`.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.7_

  - [x] 13.2 Write property test for error ordering
    - **Property 4: Error ordering and first invalid field**
    - New `lib/formErrors.property.test.tsx` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 4: Error ordering and first invalid field`.
    - **Validates: Requirements 11.1, 11.2**

  - [x] 13.3 Write property test for the summary heading
    - **Property 5: Error summary heading states the count**
    - Add to `lib/formErrors.property.test.tsx`, rendering `ErrorSummary`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 11.4, 11.5**

  - [x] 13.4 Wire `ErrorSummary` into `LoanForm`, `AssetForm`, and `TransactionForm`
    - Build `items` from `orderedErrors(fieldErrors, ORDER)` plus the form-level message, render `ErrorSummary` at the top of each form, and call `useFocusFirstInvalid` with an `attempt` counter incremented on failed client validation and on new server field errors. Form-level-only errors do not move focus. Inline `FormField` errors stay.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [x] 13.5 Write tests for `ErrorSummary` wiring
    - Summary lists all errors and links focus the right field; focus moves to the first invalid field in document order; fixing all errors removes the summary; a server error with no field shows in the summary without moving focus; inline errors still show. Run `vitest-axe`.
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

- [x] 14. Phase 2 - Money_Input and Date_Input
  - [x] 14.1 Add `moneyInput.ts` and `MoneyInput`
    - Create `lib/moneyInput.ts` with `sanitizeMoneyInput(raw, { allowNegative })`, `formatMoneyDisplay`, and `parseMoneyDisplay`. Create `components/ui/MoneyInput.tsx` (`$` prefix `aria-hidden`, `type="text"`, `inputMode="decimal"`, canonical text while focused, formatted on blur with two decimals, `value` and `onValueChange` with sanitized canonical text, `border-border-strong`-ready via the shared `Input`). Export from `components/ui/index.ts`.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [x] 14.2 Write property test for sanitized money text
    - **Property 6: Sanitized money text always fits the grammar**
    - New `lib/moneyInput.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 6: Sanitized money text always fits the grammar`.
    - **Validates: Requirements 12.3, 12.5**

  - [x] 14.3 Write property test for pasted decorated amounts
    - **Property 7: Pasted decorated amounts keep their numeric value**
    - Add to `lib/moneyInput.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 12.4**

  - [x] 14.4 Write property test for the money round trip
    - **Property 8: Money format and parse round trip**
    - Add to `lib/moneyInput.property.test.ts`, generating integer cents through `centsToMoney`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 12.6, 12.7**

  - [x] 14.5 Add `dateInput.ts` and `DateInput`
    - Create `lib/dateInput.ts` with `todayLocal(now?)` built from local date parts (never `toISOString`). Create `components/ui/DateInput.tsx`: `Input type="date"` plus a ghost `Button size="sm"` "Today" that calls `onValueChange(todayLocal())` and focuses the input. Export from `components/ui/index.ts`.
    - _Requirements: 12.8, 12.9_

  - [x] 14.6 Write property test for `todayLocal`
    - **Property 9: Today is the local calendar date**
    - New `lib/dateInput.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 9: Today is the local calendar date`.
    - **Validates: Requirements 12.9**

  - [x] 14.7 Adopt `MoneyInput` and `DateInput` in Loan, Asset, and Transaction forms
    - Use `MoneyInput` for the transaction amount, loan monthly payment, anchor balance, extra principal, original principal, and asset cost basis. Use `DateInput` for loan anchor, payoff, and closing dates and the asset in-service date. Leave the interest rate, inline override inputs, and import line amounts unchanged. Existing validators keep consuming canonical strings.
    - _Requirements: 12.6, 12.10_

  - [x] 14.8 Write tests for `MoneyInput`, `DateInput`, and the adopted forms
    - MoneyInput: prefix, `inputMode`, rejects letters, strips a pasted `$1,250.00`, limits decimals to two, negative only when allowed, formatted on blur, canonical on focus. DateInput: Today button sets the local date and focuses the input. Existing form tests updated only for changed markup.
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.8, 12.9, 12.10_

- [x] 15. Phase 2 - Migrate the Transactions dialog
  - [x] 15.1 Move the Transactions dialog onto `RecordModal`
    - In `TransactionsPage.tsx` replace the inline `Dialog.Root` with `RecordModal` driven by `useRecordModal(transactions, ...)`, titles "Add transaction" and "Edit transaction", and the discard guard wiring. Remove the hand-built close (x) button. Add `onDirtyChange` to `TransactionForm`. Success closes and refreshes; failure keeps the dialog open with the error inside and values retained. Focus returns to the opener through `handleCloseAutoFocus`.
    - _Requirements: 9.1, 9.2, 9.6, 9.7, 9.9, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 15.2 Write tests for the Transactions dialog
    - Opens as `dialog`, no second close button, first field focused, success closes and refreshes, failure retains values, dirty close shows the confirmation, focus returns to the opener. Existing `TransactionsPage` tests updated only for changed markup. Run `vitest-axe` on the open dialog.
    - _Requirements: 9.1, 9.2, 9.6, 9.7, 9.8, 9.9, 10.2_

- [x] 16. Phase 2 - Migrate AddPropertyDialog
  - [x] 16.1 Move `AddPropertyDialog` onto `RecordModal` with controlled props (D9)
    - Replace `Dialog.Root/Content` with `RecordModal` and `useDiscardGuard`. Add optional `open` and `onOpenChange` props; when `open` is undefined keep the built-in trigger exactly as today. Do not touch `handleSelectAddress`, `runEnrich`, `handleSelectUnit`, the `EnrichPhase` state machine, or the seams `enrich`, `create`, `fetchSuggestions`, `fetchUnits`.
    - Use `FormField`, `MoneyInput` for currency fields, `DateInput` for single dates, `ErrorSummary`, and the dirty reporter.
    - In `PropertiesPage` hold the open state and render the dialog in controlled mode; the header action shows only when properties exist and the empty state carries the single "Add property" action.
    - _Requirements: 9.1, 9.3, 9.4, 9.5, 9.6, 9.7, 9.9, 10.2, 11.1, 11.6, 12.10, 14.13_

  - [x] 16.2 Write tests for `AddPropertyDialog` and the Properties empty state
    - Regression: suggestion selection populates the same fields and values, enrichment found, not found, and thrown (form stays open, values retained, manual entry allowed). Create success closes and refreshes, failure keeps values, built-in trigger mode still works, discard prompt on a dirty close. PropertiesPage empty state shows exactly one "Add property" button. Existing dialog tests stay green.
    - _Requirements: 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 14.13_

- [x] 17. Phase 2 - Migrate EditPropertyDialog
  - [x] 17.1 Move `EditPropertyDialog` onto `RecordModal`
    - Replace the controlled `Dialog.Root` with `RecordModal`, keeping its props. Add `FormField`, `ErrorSummary`, `MoneyInput`, `DateInput`, and the discard guard with dirty reporting.
    - _Requirements: 9.1, 9.6, 9.7, 9.9, 10.2, 11.1, 11.6, 12.10_

  - [x] 17.2 Write tests for `EditPropertyDialog`
    - Opens as `dialog` with prefilled values, save closes and refreshes, failure shows the error inside and retains values, dirty close prompts, restore-to-original does not, focus returns to the opener. Existing tests updated only for markup.
    - _Requirements: 9.1, 9.6, 9.7, 9.8, 9.9, 10.2, 10.7_

- [x] 18. Phase 2 - Migrate AddBusinessDialog
  - [x] 18.1 Move `AddBusinessDialog` onto `RecordModal` with controlled props (D9)
    - Replace `Dialog.Root/Content` with `RecordModal`; add optional `open` and `onOpenChange` (built-in trigger kept when `open` is undefined). Update `BusinessFormFields` to use `FormField`, `Textarea`, and `DateInput` (formation date), and add `ErrorSummary` and dirty reporting.
    - In `BusinessesPage` hold the open state and render the dialog in controlled mode; header action only when businesses exist, and a single "Add business" action in the empty state.
    - _Requirements: 9.1, 9.6, 9.7, 9.9, 10.2, 11.1, 11.6, 12.10, 14.13_

  - [x] 18.2 Write tests for `AddBusinessDialog`
    - Opens as `dialog`, create success closes and refreshes, failure retains values, built-in trigger mode, dirty close prompts, empty state shows exactly one "Add business" button. Existing tests updated only for markup.
    - _Requirements: 9.1, 9.6, 9.7, 9.8, 9.9, 10.2_

- [x] 19. Phase 2 - Migrate EditBusinessDialog
  - [x] 19.1 Move `EditBusinessDialog` onto `RecordModal`
    - Replace the controlled `Dialog.Root` with `RecordModal`, keeping its props, reusing the updated `BusinessFormFields`, and adding the discard guard and dirty reporting.
    - _Requirements: 9.1, 9.6, 9.7, 9.9, 10.2, 11.1, 11.6_

  - [x] 19.2 Write tests for `EditBusinessDialog`
    - Opens as `dialog` with prefilled values, save closes and refreshes, failure retains values, dirty close prompts, focus returns to the opener. Existing tests updated only for markup.
    - _Requirements: 9.1, 9.6, 9.7, 9.8, 9.9, 10.2_

- [x] 20. Phase 2 - First-load helper
  - [x] 20.1 Add `useFirstLoad` and the refreshing indicator
    - Create `components/ui/useFirstLoad.ts` with the pure `deriveLoadView({ hasLoaded, loading, error })` and the hook (sticky `hasLoaded` via set-state-during-render, reset when `resetKey` changes). Add a small `RefreshingIndicator` (`Spinner` plus "Refreshing" text in a `role="status"`) in `components/ui/`. Export from `components/ui/index.ts`.
    - _Requirements: 14.1, 14.2, 14.3, 14.5_

  - [x] 20.2 Write property test for load-state derivation
    - **Property 12: Content stays mounted once loaded**
    - New `components/ui/useFirstLoad.property.test.tsx` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 12: Content stays mounted once loaded`.
    - **Validates: Requirements 14.1, 14.2, 14.8, 23.5**

  - [x] 20.3 Write example tests for `useFirstLoad`
    - Initial skeleton, content after first success, refresh keeps content and sets `refreshing`, refresh error keeps content with `errorIsStale`, first-load error shows the error only, `resetKey` change returns to the skeleton.
    - _Requirements: 14.1, 14.2, 14.3, 14.5, 14.8_

- [x] 21. Phase 2 - First-load and Load_Error_Alert rollout
  - [x] 21.1 Roll out to `PropertiesPage` and `BusinessesPage`
    - Use `useFirstLoad`, a table skeleton on first load, content kept mounted on refresh (stop setting `{ status: "loading" }` after the first load), the `RefreshingIndicator` beside the header actions, and `StateBlock kind="error"` (full on first load, compact over stale content) with Retry calling `refresh()`. Remove the hand-rolled banner-style errors. After create, update, and delete, the lists refresh as today.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.6, 14.7, 14.8_

  - [x] 21.2 Roll out to `BusinessDetailPage`, `PropertyDetailPage`, and `PropertyLayout`
    - Per-tile skeletons on first load and `StateBlock` error with Retry for each existing loader. Add `reload` to `PropertyContext` (default no-op for standalone renders) and show the `PropertyLayout` error with Retry. Remove hand-rolled red alert lines.
    - _Requirements: 14.1, 14.2, 14.4, 14.6, 14.7, 14.8_

  - [x] 21.3 Roll out to `TransactionsPage` and `AssetsPage`
    - Table skeleton on first load, content kept mounted (dimmed with `aria-busy`) on refresh, and `StateBlock` errors with Retry calling `loadTransactions()` and the asset and schedule loaders. A tax-year change on Transactions does not reset the hook. Remove hand-rolled red alert lines.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.6, 14.7, 14.8_

  - [x] 21.4 Roll out to `LoansPage`
    - Use `useFirstLoad` for `useLoans` and `useLoanSchedule` with `resetKey` set to the property id, table skeletons, kept content on refresh, and `StateBlock` errors with Retry calling each hook's `refresh`. Remove hand-rolled red alert lines.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.6, 14.7, 14.8_

  - [x] 21.5 Roll out to `ReportsPage`, `CombinedReportsPage`, and `CarryforwardPage`
    - `LoadingRegion` on first load, kept content on refresh, `StateBlock` errors with Retry re-running the report and reconciliation loaders. Remove hand-rolled red alert lines.
    - _Requirements: 14.1, 14.2, 14.4, 14.6, 14.7, 14.8_

  - [x] 21.6 Write rollout tests and extend the conformance scan
    - One test per rolled-out page (or per loader) for: skeleton on first load, content stays mounted during refresh, stale content plus compact error when a refresh fails, full error with Retry on first-load failure and Retry re-runs the failed request.
    - Extend the page conformance scan: no hand-rolled `role="alert"` load line with `text-danger`, with `DashboardPage` temporarily allowlisted (the allowlist entry is removed in task 34.5).
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.6, 14.7, 14.8_

- [x] 22. Phase 2 - Toast improvements
  - [x] 22.1 Add durations, close button, action, and info variant
    - In `ToastProvider.tsx` add `info` to `ToastVariant`, `action` and `duration` to `ToastMessage`, and the pure `toastDurationMs` (`duration ?? (action ? 10000 : variant === "error" ? 10000 : 5000)`). Pass it to each `Toast.Root`.
    - Add `<Toast.Close aria-label="Dismiss notification">` wrapping a ghost icon `Button` with `XIcon`-equivalent inline markup (the shared `icons.tsx` arrives in Phase 3, so use a small local close glyph now), and a `Toast.Action` button with a derived `altText`. Style `info` with `border-accent bg-accent-subtle text-fg`. Position full width above the bottom edge below 640px.
    - _Requirements: 14.9, 14.10, 14.11, 14.12, 13.5, 13.6_

  - [x] 22.2 Write tests for toast behavior
    - `toastDurationMs` table (success 5s, info 5s, error 10s, action 10s, override), close button name and dismissal, action closes the toast, pause on hover and on focus with fake timers, info variant classes. Update `ToastProvider.test.tsx` for the new animation classes by addition.
    - _Requirements: 14.9, 14.10, 14.11, 14.12, 13.5, 13.6_

- [x] 23. Phase 2 - Undo for safe deletes
  - [x] 23.1 Add `undoMappers.ts`
    - Create `lib/undoMappers.ts` with `isTransactionSafeDelete(t, receiptCount)` (not imported and zero receipts), `isLoanSafeDelete(l)` (no interest overrides), `transactionToInput`, `assetToInput`, and `loanToInput` (create-input keys only, ignoring `id` and timestamps).
    - _Requirements: 13.1, 13.3, 13.7_

  - [x] 23.2 Write property test for Safe_Delete classification
    - **Property 10: Safe_Delete classification**
    - New `lib/undoMappers.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 10: Safe_Delete classification`.
    - **Validates: Requirements 13.1, 13.7**

  - [x] 23.3 Write property test for undo mappers
    - **Property 11: Undo mappers reproduce the retained fields**
    - Add to `lib/undoMappers.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 13.3**

  - [x] 23.4 Add `useUndoableDelete`
    - Create `components/ui/toast/useUndoableDelete.ts` per the design: `remove`, then `refresh`, then a success toast with an Undo action; Undo calls `restore`, then `refresh`, then a "restored" toast; a failed `restore` shows an error toast and still refreshes; a failed `remove` shows an error toast and no Undo. Capture the item and `propertyId` at delete time so Undo works after navigation.
    - _Requirements: 13.2, 13.3, 13.4, 13.5_

  - [x] 23.5 Wire Undo into asset deletes
    - In `AssetsPage`, deleting an asset is always a Safe_Delete: use `useUndoableDelete` with `deleteAsset` and `createAsset(assetToInput(asset))`, clear selection keyed to the old id on restore, and drop the ConfirmDialog for assets.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.8_

  - [x] 23.6 Wire conditional Undo into transaction deletes
    - In `TransactionsPage`, on Delete call `listReceipts`; use `useUndoableDelete` only when `isTransactionSafeDelete(t, count)` is true. Imported rows, rows with receipts, and `listReceipts` failures (treated as having receipts) open the existing ConfirmDialog, whose text mentions receipts when any exist.
    - _Requirements: 13.1, 13.2, 13.3, 13.7, 13.8_

  - [x] 23.7 Wire conditional Undo into loan deletes
    - In `LoansPage`, use `useUndoableDelete` with `deleteLoan` and `createLoan(loanToInput(loan))` only when `isLoanSafeDelete(loan)`. Loans with interest overrides keep the ConfirmDialog. Clear the selected loan if it was the restored record's old id.
    - _Requirements: 13.1, 13.2, 13.3, 13.7, 13.8_

  - [x] 23.8 Write tests for `useUndoableDelete` and the per-delete classification
    - Hook: success shows an Undo toast, Undo restores and refreshes, restore failure shows an error and refreshes, remove failure shows no Undo. Pages: asset delete always offers Undo; transaction delete offers Undo only when not imported with zero receipts, and imported, with-receipts, and `listReceipts`-failure cases open the ConfirmDialog; loan delete offers Undo only without overrides. Receipts, properties, businesses, documents, and photos keep their existing confirm flows.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8_

- [x] 24. Checkpoint - Phase 2 shippable
  - Run `cd frontend && npm test -- --run` and `npm run build`. Confirm the Axe_Suite still passes, each migrated dialog test passes, and the delete classification tests pass. Ensure all tests pass, ask the user if questions arise.

- [x] 25. Phase 3 - Teal tokens and contrast
  - [x] 25.1 Add `lib/contrast.ts`
    - Create `lib/contrast.ts` with `parseRgbChannels`, `relativeLuminance`, `contrastRatio`, `readTokens(css)` (parses the `:root` and `.dark` blocks), and `TOKEN_PAIRS` (the Requirement 25.1 pairs plus the extra rows in the design's contrast table, including `border-strong` on `canvas` and `surface`).
    - _Requirements: 17.7, 25.1, 25.2_

  - [x] 25.2 Write property test for contrast ratio
    - **Property 13: Contrast ratio is a well-formed metric**
    - New `lib/contrast.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 13: Contrast ratio is a well-formed metric`.
    - **Validates: Requirements 17.7**

  - [x] 25.3 Apply the token values (teal accent, fg-subtle, fg-muted, border-strong, brand tokens)
    - In `frontend/src/index.css` set the teal `accent`, `accent-hover`, `accent-fg`, `accent-subtle` values and the raised `fg-muted` (dark) and `fg-subtle` (light and dark) values, and add `border-strong`, `brand-tagline`, and `brand-orange` in both themes, per the design's color table. Leave no indigo values.
    - In `frontend/tailwind.config.js` add `colors["border-strong"]`, `colors["brand-orange"]`, and `fill["brand-tagline"]`.
    - Switch `Input`, `Select`, `Textarea`, `MoneyInput`, and `DateInput` to `border-border-strong`, and change the skip link's `focus-visible:outline-white` to `focus-visible:outline-accent-fg`. Do not use `fg-subtle` on `accent-subtle`.
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 25.3_

  - [x] 25.4 Write the token contrast test
    - New `lib/contrast.test.ts` that reads `src/index.css`, parses both themes with `readTokens`, and asserts every row of `TOKEN_PAIRS` against its 4.5:1 or 3:1 minimum (including `border-strong`). Add a second assertion that fails when `index.css` contains indigo values.
    - _Requirements: 17.2, 17.5, 17.6, 17.7, 25.1, 25.2, 25.3, 25.9_

- [x] 26. Phase 3 - Brand assets, Logo, and shell wiring
  - [x] 26.1 Move the source logo and produce the outlined paths
    - `git mv logo.svg docs/brand/logo-source.svg`. Convert the wordmark and tagline text to outlined paths using Inter Bold (700) and Inter SemiBold (600) at the artwork's sizes and letter spacing (SIL OFL), with a small script using `opentype.js` or an Inkscape export documented in `docs/brand/`.
    - Write `frontend/src/assets/brand/brand-paths.ts` (`LOCKUP_VIEWBOX`, `MARK_VIEWBOX` "25 21 140 140", house, chimney, bars with gradients, `WORDMARK_PATH`, `TAGLINE_PATH`) and `frontend/src/assets/brand/logo.svg` and `logo-mark.svg`.
    - _Requirements: 15.1, 15.6, 15.7_

  - [x] 26.2 Create the icon generation script and public assets
    - Create `frontend/scripts/generate-brand-icons.mjs` (dev only, pinned rasterizer, not part of `npm run build`) that rasterizes `public/favicon.svg` to `public/favicon-32.png` and `public/apple-touch-icon.png` (180 by 180, white background, mark about 64% of the width). Commit `public/logo.svg`, `public/logo-mark.svg` (colors baked in), `public/favicon.svg` (square mark), the two PNGs, and `public/favicon-monogram.svg` (letter "L" in teal on a rounded square).
    - _Requirements: 15.2, 16.4_

  - [x] 26.3 Get the user's visual approval of the generated assets
    - Render a preview of the outlined lockup, the square mark, the favicon PNGs, and the dark-theme appearance, show it to the user, and wait for approval of the Inter Bold wordmark before wiring the assets into the shell. Apply any requested adjustments to the paths and regenerate.
    - _Requirements: 15.1, 15.2, 15.5_

  - [x] 26.4 Create `Logo`, `WordmarkFallback`, `BrandLogo`, and `BrandSplash`
    - Create `components/brand/Logo.tsx` (inline SVG with `aspect-ratio`, `role="img"` and `aria-label="Logstead"` unless `decorative`, `useId`-prefixed gradient ids, wordmark `currentColor`, tagline `className="fill-brand-tagline"` only when `tagline` is true), `WordmarkFallback.tsx` (text "logstead" in `text-fg`, `aria-label="Logstead"`, no amber or gold), `BrandLogo.tsx` (single switch with a small error boundary that renders the fallback if `Logo` throws), and `BrandSplash.tsx` (tagline logo at `h-40` from 640px, no tagline at `h-20` below).
    - _Requirements: 15.4, 15.5, 15.6, 15.7, 16.1, 16.2, 16.3, 16.5, 16.6_

  - [x] 26.5 Wire the header, splash screens, and `index.html`
    - In `AppLayout` render `<Link to="/" aria-label="Logstead home">` containing `<BrandLogo decorative className="h-8 sm:h-10 w-auto" />` with no tagline. Use `BrandSplash` in `RequireAuth` and `AuthCallback` above the existing status text, roles, and retry button, which stay unchanged.
    - In `frontend/index.html` set `<title>Logstead</title>` and add the SVG icon link, the 32px PNG icon link, and the `apple-touch-icon` link.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.7, 16.1_

  - [x] 26.6 Write tests for branding
    - `Logo`: accessible name, decorative mode, tagline only when requested, unique gradient ids across two instances, `aspect-ratio` reserved. `BrandLogo` renders the fallback when `Logo` throws. Header: link name "Logstead home", no tagline in the header. `BrandSplash`: tagline class contract at wide widths only. Smoke tests: `index.html` has the title and icon links; `public/` contains the icon files and the PNG headers report 32 by 32 and 180 by 180.
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6, 15.7, 16.1, 16.3, 16.4, 16.5, 16.6_

- [x] 27. Phase 3 - Icons
  - [x] 27.1 Create `icons.tsx`
    - Create `components/ui/icons.tsx` exporting `DashboardIcon`, `BuildingIcon`, `BriefcaseIcon`, `ReportIcon`, `CarryforwardIcon`, `UploadIcon`, `MenuIcon`, `XIcon`, `CheckIcon`, `ChevronUpIcon`, `ChevronDownIcon`, `SortIcon`, `AlertIcon`, `SearchIcon`, and `PlusIcon` on a shared base (24px viewBox, 1.75 stroke, `currentColor`, `aria-hidden="true"`, `focusable="false"`). Replace the Phase 2 local close glyph in `ToastProvider` with `XIcon`.
    - _Requirements: 18.3_

  - [x] 27.2 Write tests for the icons
    - Every exported icon renders `aria-hidden="true"` and `focusable="false"`, uses `currentColor`, and accepts `className`.
    - _Requirements: 18.3_

- [x] 28. Phase 3 - Grouped navigation
  - [x] 28.1 Add `NAV_GROUPS` and rebuild `MainNav`
    - In `navConfig.ts` add `NavIconName`, `icon` on `NavItem`, `NavGroup`, and `NAV_GROUPS` (Portfolio: Dashboard, Properties, Businesses; Tax: Reports, Carryforward; Tools: Import). Derive `PRIMARY_NAV` with `flatMap` in the same order as today.
    - Rebuild `MainNav` with a `div role="group" aria-labelledby` and a labelled `ul` per group, an `aria-hidden` icon per link, and `max-md:min-h-11`. Active links get `bg-accent-subtle text-accent font-medium` plus the accent bar, with `aria-current="page"`; never a solid accent block. Desktop sidebar and mobile drawer render the same `MainNav`.
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

  - [x] 28.2 Write tests for grouped navigation
    - `NAV_GROUPS` data and `PRIMARY_NAV` order; `MainNav` renders three labelled groups, hidden icons, `aria-current` and active classes on the active item only, no solid accent block, and the same groups in the desktop nav and the drawer. Update `navConfig.test.ts` and `AppLayout.test.tsx` only for changed markup.
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7_

- [x] 29. Phase 3 - Mobile drawer
  - [x] 29.1 Update the drawer controls and focus rule
    - In `AppLayout` make the open control `Button variant="ghost" size="icon"` with `MenuIcon` (keep `aria-label="Open navigation menu"`, `aria-controls`, `aria-expanded`) and the close control `Button variant="ghost" size="icon"` with `XIcon` and `aria-label="Close menu"` (44px below `md`).
    - Escape closes the drawer and Radix returns focus to the menu button. Selecting a destination closes the drawer and prevents the default close auto-focus for that case, so the route change moves focus to the new page `h1`.
    - _Requirements: 18.8, 18.9, 5.3_

  - [x] 29.2 Write tests for the drawer
    - Close button name "Close menu" and icon-button size classes, Escape returns focus to the menu button, choosing a destination closes the drawer and focus lands on the new page `h1`, open and close controls keep their ARIA attributes. Update `AppLayout.test.tsx` for the new close name.
    - _Requirements: 18.8, 18.9, 5.3_

- [x] 30. Phase 3 - Property_Switcher
  - [x] 30.1 Add `propertySwitch.ts`
    - Create `components/propertySwitch.ts` with `sectionFromPath`, `propertyIdFromPath`, and `switchPropertyPath(pathname, search, nextPropertyId)` built on `propertyPath` from `navConfig.ts`, carrying over only the `year` search parameter.
    - _Requirements: 19.3, 19.4, 19.5, 19.7_

  - [x] 30.2 Write property test for switching keeps the section
    - **Property 14: Switching property keeps the section**
    - New `components/propertySwitch.property.test.ts` with `fast-check` (`numRuns: 100`, ids from `fc.uuid()`), tagged `Feature: ui-polish-and-consistency, Property 14: Switching property keeps the section`.
    - **Validates: Requirements 19.3, 19.6**

  - [x] 30.3 Write property test for non-property routes
    - **Property 15: Switching from a non-property route goes to the overview**
    - Add to `components/propertySwitch.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 19.4**

  - [x] 30.4 Write property test for the year parameter
    - **Property 16: Only the year parameter is carried over**
    - Add to `components/propertySwitch.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 19.7**

  - [x] 30.5 Add `PropertySwitcher` and the shell properties context
    - Create `components/PropertySwitcher.tsx`: a native `Select` with `<label className="sr-only">Switch property</label>`, options from property names, the current property selected (placeholder option on non-property routes), `navigate(switchPropertyPath(...))` on change.
    - In `AppLayout` provide `ShellPropertiesContext` (`{ status, properties, refresh }`, default no-op), loaded once with `listProperties`. Show `Skeleton` while loading; render nothing on error or with zero properties. Hide the control below `sm` in the header and show it in the drawer. `PropertiesPage` calls `refresh()` after create, update, and delete.
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.8, 19.9_

  - [x] 30.6 Write tests for `PropertySwitcher`
    - Loading skeleton, error and empty hide the control without blocking the shell, current property selected, selecting navigates to the same section and keeps `year`, non-property route goes to the overview, accessible name "Switch property", keyboard operable, list refreshes after property changes. Run `vitest-axe`.
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.7, 19.8, 19.9_

- [x] 31. Phase 3 - ResponsiveTable sorting, sticky header, hover, numeric alignment
  - [x] 31.1 Add `tableSort.ts`
    - Create `components/ui/tableSort.ts` with `SortDirection`, `SortState`, `SortType`, `nextSortState` (other key to asc, asc to desc, desc to none), and `sortRows` (index-decorated stable sort; numbers numerically, dates as ISO strings with `Date.parse` fallback, text with `localeCompare(undefined, { numeric: true, sensitivity: "base" })`; missing values last in both directions; `null` state returns the input order as a new array).
    - _Requirements: 20.1, 20.3, 20.4, 20.5_

  - [x] 31.2 Write property test for sort state cycling
    - **Property 17: Sort state cycles through three states**
    - New `components/ui/tableSort.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 17: Sort state cycles through three states`.
    - **Validates: Requirements 20.1**

  - [x] 31.3 Write property test for sort ordering and preservation
    - **Property 18: Sorting orders rows and preserves them**
    - Add to `components/ui/tableSort.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 20.3, 20.4, 20.6**

  - [x] 31.4 Write property test for stable sorting
    - **Property 19: Sorting is stable**
    - Add to `components/ui/tableSort.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 20.5**

  - [x] 31.5 Write property test for descending reversing ascending
    - **Property 20: Descending reverses ascending when keys are distinct**
    - Add to `components/ui/tableSort.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 20.6**

  - [x] 31.6 Upgrade `ResponsiveTable`
    - Add column options `numeric`, `sortable`, `sortType`, `rowHeader`, `align`, row options `sortValues`, `detail`, `detailId`, `detailOpen`, and table props `stickyHeader`, `maxHeightClass` (default `max-h-[70vh]`), `defaultSort`, `sort`, `onSortChange`. Sortable headers render `<th scope="col">` with a button, `aria-sort` on the sorted column only, and `SortIcon` or chevron icons (`aria-hidden`, `max-md:min-h-11`).
    - Sticky header cells use `sticky top-0 z-10 bg-surface` with an inset bottom shadow; rows get `hover:bg-surface-muted focus-within:bg-surface-muted`; numeric columns are right-aligned with `tabular-nums` in header and body; detail rows render after their row (`colSpan`, `hidden` when closed) and under the card in the card layout; row-header cells render `<th scope="row">`.
    - With no sortable columns the markup stays as before, and the `hidden sm:block` table and `ul.sm:hidden` card list stay. No sort control below `sm`.
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.7, 20.8, 20.9, 20.10, 20.11, 25.4_

  - [x] 31.7 Write tests for `ResponsiveTable` upgrades
    - Sort header cycle (asc, desc, none) and `aria-sort`, numeric and date and text ordering, sticky and hover class contracts, numeric alignment in header and body, detail row show and hide, row header cells, no-sort rendering identical to before, mobile card list order follows the sort. Existing `ResponsiveTable` tests stay green. Run `vitest-axe`.
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.7, 20.8, 20.9, 20.10, 20.11_

- [x] 32. Phase 3 - Transactions search and filters
  - [x] 32.1 Add `transactionFilter.ts`
    - Create `lib/transactionFilter.ts` with `TransactionFilter` and `filterTransactions(transactions, categories, filter)`: a transaction matches when the trimmed, lower-cased query is a substring of its description, category label, or amount text (raw two-decimal amount and `formatMoney` text), and it matches the category selection when `categoryId` is null or equal. Order is preserved.
    - _Requirements: 21.2, 21.4, 21.5, 21.6, 21.10_

  - [x] 32.2 Write property test for filter correctness
    - **Property 21: Filter results are exactly the matching transactions**
    - New `lib/transactionFilter.property.test.ts` with `fast-check` (`numRuns: 100`; plant the query inside a randomly chosen field of a randomly chosen transaction), tagged `Feature: ui-polish-and-consistency, Property 21: Filter results are exactly the matching transactions`.
    - **Validates: Requirements 21.2, 21.4, 21.7**

  - [x] 32.3 Write property test for filter composition
    - **Property 22: Filters compose and never reorder**
    - Add to `lib/transactionFilter.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 21.5, 21.6**

  - [x] 32.4 Add search and filters to `TransactionsPage`
    - Next to `TaxYearFilter` add an `Input` with `aria-label="Search transactions"` and `SearchIcon`, and a category `Select` listing only categories present in the loaded transactions. Show "Showing {n} of {total} transactions" in a polite `role="status"` live region while a filter is active. With no match show a `StateBlock` empty state "No transactions match your filters" with a "Clear filters" action. Filtering is client-side only with no new API parameters; filter state is local to the page.
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.8, 21.9, 21.10_

  - [x] 32.5 Write tests for Transactions search and filters
    - Search name, typing filters by description, category, and amount text, category filter lists only present categories, combined filters, empty query shows all, count text and live region, no-match empty state and Clear filters, no extra API call when filtering.
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.8, 21.9, 21.10_

- [x] 33. Phase 3 - Migrate high-traffic tables
  - [x] 33.1 Migrate `PaymentRowsTable`
    - Render with `ResponsiveTable`: Payment number (`rowHeader`), Date, Payment, Interest, Principal, Balance (last four `numeric`), `stickyHeader`, `maxHeightClass="max-h-96"`, not sortable, empty state paragraph unchanged. Same columns, values, and formatting as before.
    - _Requirements: 22.1, 22.3, 22.4, 22.5_

  - [x] 33.2 Migrate `YearlyRollupTable`
    - Render with `ResponsiveTable`: Tax year (`rowHeader`, keeps the "Override only" badge and anchor-year note), Interest, Principal, Total paid, Ending balance (`numeric`), a Payments toggle button, and the interest override column only with `renderOverrideControl`. The nested `PaymentRowsTable` is the row `detail` with `detailId` `loan-{id}-year-{year}-payments` and `detailOpen` bound to the existing `expanded` set so `aria-controls` and `aria-expanded` keep working.
    - _Requirements: 22.1, 22.3, 22.4_

  - [x] 33.3 Migrate the asset `ScheduleTable`
    - Render with `ResponsiveTable`: Tax year (`rowHeader`), Depreciation amount, Remaining basis (`numeric`), Override (only when `editable`). `OverrideControl` replaces the fixed ids `override-${year}` and `override-error-${year}` with `useId()`-based ids (cells render twice in the table and the card list) and swaps the dead `bg-bg` class for the shared `Input`.
    - _Requirements: 22.2, 22.3, 22.4_

  - [x] 33.4 Update and extend tests for the migrated tables
    - Keep the existing `PaymentRowsTable`, `YearlyRollupTable`, and `ScheduleTable` tests, scoping queries with `within(screen.getByRole("table"))` where the card list repeats text. Add assertions for same columns and values, right-aligned numeric columns, sticky header on `PaymentRowsTable`, expand and collapse with correct ARIA, and no duplicate ids. Confirm Dense_Report_Tables and chart data tables are untouched.
    - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6, 22.7_

- [x] 34. Phase 3 - Progressive Dashboard and Checklist_Card
  - [x] 34.1 Add `checklist.ts` and `checklistStorage.ts`
    - Create `components/dashboard/checklist.ts` with `computeChecklist(flags, dismissed)` (`completed` is the count of true flags, `total` is 4, `visible` is `!dismissed && completed < 4`) and `hasTransactionData(trends)` (any year with a non-zero `total_income` or `total_expenses` via `toCents`).
    - Create `lib/checklistStorage.ts` with `checklistKeys(userId?)` (`logstead.checklist.visitedReport[.{sub}]` and `logstead.checklist.dismissed[.{sub}]`), `readFlag` and `writeFlag` (both wrapped in `try/catch`, safe when storage is unavailable), and `useMarkReportVisited()`.
    - _Requirements: 24.2, 24.5, 24.7, 24.8, 24.10, 24.11_

  - [x] 34.2 Write property test for checklist count and visibility
    - **Property 23: Checklist count and visibility**
    - New `components/dashboard/checklist.property.test.ts` with `fast-check` (`numRuns: 100`), tagged `Feature: ui-polish-and-consistency, Property 23: Checklist count and visibility`.
    - **Validates: Requirements 24.5, 24.10, 24.11**

  - [x] 34.3 Write property test for transaction data detection
    - **Property 24: Transaction data is detected from the trends series**
    - Add to `components/dashboard/checklist.property.test.ts` (series from small arrays of years with cent-based amount strings), `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 24.2**

  - [x] 34.4 Write property test for per-user storage keys
    - **Property 25: Checklist storage keys are per user**
    - Add to `components/dashboard/checklist.property.test.ts`, `numRuns: 100`, tagged with the property text.
    - **Validates: Requirements 24.7**

  - [x] 34.5 Make the Dashboard progressive with `DataTile`
    - Create `components/dashboard/DataTile.tsx` (`{ status, error, onRetry, skeleton, children }` picks skeleton, error, or content). In `DashboardPage` use two `useFirstLoad` instances (summary and trends) with their own retries, render the header and Quick actions immediately, show `TileSkeleton` or `ChartSkeleton` per tile, and show one `StateBlock` error with Retry per failed data source (a failed summary in the content area, a failed trends request across the trends region). Remove `DashboardLoading` and use `Spinner` for its inline spinner. Keep `ChartErrorBoundary` and `LazyChart` behavior unchanged.
    - Remove the `DashboardPage` allowlist entry from the conformance scan added in task 21.6.
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 14.6_

  - [x] 34.6 Add `ChecklistCard` and wire its data
    - Create `components/dashboard/ChecklistCard.tsx`: `Card` with `aria-labelledby`, heading "Get set up", progress "{completed} of {total} done", an ordered list of four steps (property, transactions, loan or asset, report). Incomplete steps are links (property to `/properties`; transactions to `/properties/{firstId}/transactions`; loan or asset to `/properties/{firstId}/assets`; report to `/reports`; fall back to `/properties` with no property). Complete steps show `CheckIcon` (`aria-hidden`) and `<span className="sr-only">Completed</span>`. A ghost icon `Button` with `aria-label="Dismiss setup checklist"` writes the dismissed flag. Render nothing when not visible; `TileSkeleton` while loading; hidden on error.
    - Flags: `hasProperty` from `summary.has_properties`; `hasTransactions` from `hasTransactionData(trends)`; `hasLoanOrAsset` from non-zero depreciation in trends, otherwise (card still visible and a property exists) `listLoans` and `listAssets` for at most the first 5 properties; `visitedReport` from the local flag. User id comes from `getUserProfile()?.sub`; no backend call for either flag.
    - Call `useMarkReportVisited()` in `ReportsPage` and `CombinedReportsPage`. Render the card in `DashboardPage`.
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7, 24.8, 24.9, 24.10_

  - [x] 34.7 Write tests for the Dashboard and `ChecklistCard`
    - Dashboard with staggered promises: header and Quick actions render at once, each tile replaces its skeleton independently, one error with Retry per failed source leaves other regions unaffected, Retry re-runs only that source, refresh keeps tiles mounted, chart error boundary behavior unchanged.
    - ChecklistCard: step order and links, "Completed" text, "{n} of 4 done", hidden when all steps complete, dismissal persisted, dismissal and visited flag keyed by user id, storage failure treated as unset without errors, skeleton while loading, hidden on error, report pages set the visited flag, no backend call for the flags.
    - _Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7, 24.8, 24.9, 24.10_

- [x] 35. Phase 3 - Accessibility sweep
  - [x] 35.1 Enforce touch targets below 768px
    - Confirm the shared primitives carry `max-md:min-h-11` (Button, Input, Select, Textarea, MoneyInput, DateInput, nav links, sort header buttons) and icon buttons carry `max-md:h-11 max-md:w-11`; add it to tab links through `sectionTabClassName`. For small text controls (Edit, Delete, Documents, and similar table buttons) extend the hit area with `relative before:absolute before:-inset-2 before:content-['']` instead of growing the control. Keep `FOCUS_RING` on every interactive control.
    - _Requirements: 25.4, 25.5, 25.9_

  - [x] 35.2 Write class-contract tests for touch targets and focus rings
    - Assert the class contracts above for the shared primitives, tab links, sort headers, nav links, drawer buttons, and the small text-button hit-area extension, and that interactive primitives keep `FOCUS_RING`. Note in the test header that pixel sizes need a manual check on a 375px viewport because jsdom has no layout.
    - _Requirements: 25.4, 25.5, 25.9_

  - [x] 35.3 Add dialog-state coverage to the Axe_Suite
    - In `src/test/axeRoutes.test.tsx` open each migrated Legacy_Dialog (Transactions, Add property, Edit property, Add business, Edit business) in both themes and run `axe` on `document.body` (with `color-contrast` disabled). Confirm the suite still fails when a route lacks a sample parameter.
    - _Requirements: 25.6, 25.7, 25.8_

  - [x] 35.4 Write source-scan tests for palette rules
    - Assert: no component contains a hard-coded palette color (hex or non-semantic Tailwind palette class) or `text-brand-orange`; `fg-subtle` is not used together with `accent-subtle` on the same element; amber and gold classes are never used for text; the skip link uses `outline-accent-fg`.
    - _Requirements: 17.1, 17.3, 17.4, 25.3_

- [x] 36. Phase 3 - Documentation
  - [x] 36.1 Update `docs/developer-guide.md`
    - Document the new primitives and conventions: Type_Scale and Spacing_Convention names, Motion_Tokens and the Reduced_Motion_Rule, `Button` `loading` and icon sizes, `PageHeader` and `useDocumentTitle`, `FormField`, `MoneyInput`, `DateInput`, `ErrorSummary`, `StateBlock` error and `useFirstLoad`, `Skeleton`, the RecordModal discard guard, `useUndoableDelete` and the delete classification, `ResponsiveTable` sorting, `APP_ROUTES` and the Axe_Suite, the token contrast test, and the semantic color tokens including `border-strong`.
    - Document the brand assets: `docs/brand/logo-source.svg`, the outlined Inter Bold paths and how they were produced, `frontend/scripts/generate-brand-icons.mjs`, the single-switch fallback in `BrandLogo`, and the rule that the tagline shows only on the sign-in splash at 640px and wider.
    - _Requirements: 1.5, 2.1, 15.1, 15.2, 15.4, 16.5, 17.1_

- [x] 37. Checkpoint - Phase 3 shippable
  - Run `cd frontend && npm test -- --run` and `npm run build`. Confirm the Axe_Suite (now including dialog states) and the token contrast test pass. Remind the user of the manual pass the automated suite cannot cover: 375px and 1440px viewports in both themes, touch-target sizes, sticky header scrolling, logo legibility at 32px and 40px, the 640px tagline breakpoint, and a screen reader run. Ensure all tests pass, ask the user if questions arise.

- [x] 38. Final checkpoint - Ensure all tests pass
  - Run `cd frontend && npm test -- --run` and `npm run build` (type-check and build must both pass). Confirm the page conformance scan, Tailwind configuration test, token contrast test, and Axe_Suite all pass. Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks, including test sub-tasks, are required, following the convention of the prior `modal-forms-and-tabbed-imports` spec. Checkpoints are not optional.
- Each phase ends with a checkpoint (tasks 9, 24, and 37) and is independently shippable. Task 38 is the final checkpoint.
- Ordering follows the design's cross-phase dependency diagram: Phase 1 tokens, Button, StateBlock, PageHeader, document title, FormField, and the route table precede Phase 2; Phase 2 `useFirstLoad` and the migrated dialogs precede the Phase 3 Dashboard and dialog Axe states.
- The 25 correctness properties map one to one to property-based tests: Properties 1 and 2 (tasks 10.2, 10.3), 3 (4.3), 4 and 5 (13.2, 13.3), 6 to 8 (14.2 to 14.4), 9 (14.6), 10 and 11 (23.2, 23.3), 12 (20.2), 13 (25.2), 14 to 16 (30.2 to 30.4), 17 to 20 (31.2 to 31.5), 21 and 22 (32.2, 32.3), 23 to 25 (34.2 to 34.4).
- Decisions applied: Requirement 18.9 was amended (Escape returns focus to the menu button; choosing a destination lets the route change focus the page `h1`); the outlined wordmark uses Inter Bold with a user visual approval task (26.3); `border-strong` is in Requirement 17.2 and covered by tasks 25.3 and 25.4; Dashboard errors are per data source (34.5); the tagline shows on the sign-in splash at 640px and wider only, never in the header.
- Safe_Delete classification: assets always; transactions only when not imported with zero receipts; loans only without interest overrides. All other deletes keep their current confirm flows.
- Task 26.3 pauses for the user to approve the generated brand assets before they are wired into the shell.
- Real layout, touch-target pixel sizes, screen reader output, and rendered-pixel contrast cannot be verified in jsdom; they are covered by class-contract tests, the token contrast test, and the manual pass listed in task 37.
- No backend, API, or new runtime dependency change. `tailwindcss-animate` is not added. The icon rasterizer for task 26.2 is a pinned dev-only dependency.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "8.1"] },
    { "id": 1, "tasks": ["1.2", "2.1", "3.1", "4.2", "6.1"] },
    { "id": 2, "tasks": ["2.2", "3.2", "4.3", "4.4", "5.1", "6.2", "7.1", "8.3"] },
    { "id": 3, "tasks": ["5.2", "7.2"] },
    { "id": 4, "tasks": ["5.3", "5.4", "6.3", "7.3", "8.2"] },
    { "id": 5, "tasks": ["6.4"] },
    { "id": 6, "tasks": ["10.1", "10.4", "13.1", "14.1", "14.5", "20.1", "22.1", "23.1"] },
    { "id": 7, "tasks": ["10.2", "10.3", "10.5", "12.1", "13.2", "13.3", "14.2", "14.3", "14.4", "14.6", "20.2", "22.2", "23.2", "23.3", "23.4"] },
    { "id": 8, "tasks": ["10.6", "11.1", "12.2", "16.1", "17.1", "18.1", "20.3"] },
    { "id": 9, "tasks": ["11.2", "13.4", "16.2", "17.2", "18.2", "19.1", "21.1", "23.5"] },
    { "id": 10, "tasks": ["13.5", "14.7", "19.2", "21.2", "21.4", "21.5"] },
    { "id": 11, "tasks": ["14.8", "15.1", "23.7"] },
    { "id": 12, "tasks": ["15.2", "21.3"] },
    { "id": 13, "tasks": ["21.6", "23.6"] },
    { "id": 14, "tasks": ["23.8"] },
    { "id": 15, "tasks": ["25.1", "26.1", "27.1", "30.1", "31.1", "32.1", "34.1"] },
    { "id": 16, "tasks": ["25.2", "25.3", "26.2", "28.1", "30.2", "30.3", "30.4", "31.2", "31.3", "31.4", "31.5", "31.6", "32.2", "32.3", "34.2", "34.3", "34.4", "34.5"] },
    { "id": 17, "tasks": ["25.4", "26.3", "26.4", "27.2", "28.2", "29.1", "31.7", "32.4", "33.1", "33.3", "34.6"] },
    { "id": 18, "tasks": ["26.5", "29.2", "32.5", "33.2", "34.7"] },
    { "id": 19, "tasks": ["26.6", "30.5", "33.4", "35.1"] },
    { "id": 20, "tasks": ["30.6", "35.2", "35.3", "35.4", "36.1"] }
  ]
}
```
