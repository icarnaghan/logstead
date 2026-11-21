# Implementation Plan: UI Polish

## Overview

This plan delivers five areas as independently shippable groups: responsive layout (D), command palette and shortcuts (A), onboarding (E), global search (B), and activity history (C), followed by a cross-cutting accessibility, dependency and documentation pass. Each group has its own code, tests, e2e coverage and documentation tasks, ends with a checkpoint, and can be merged and released without the groups after it.

Languages: Python 3.12 (backend) and TypeScript/React (frontend), as in the design. Backend tests use pytest, Hypothesis and moto. Frontend tests use vitest, fast-check, React Testing Library and `vitest-axe`. Browser checks use Playwright with the existing `e2e/fixtures.ts` stubs. Every property-based test runs at least 100 iterations and is tagged `# Feature: ui-polish, Property N: ...` (`//` in TypeScript). No runtime dependency is added to either side.

### Recommended order

1. **Group D, responsive layout (tasks 1 to 2).** No backend, no new routes, and it fixes shared components (`RecordModal`, inputs, tabs) that the palette dialog and the new pages reuse. Ships the "Property tabs on mobile" item and closes it out of `docs/future-improvements.md`.
2. **Group A, command palette and shortcuts (tasks 3 to 4).** Frontend only. Introduces the navigation guard, the `new=1` and `year` parameters, the header Search button and the shortcuts registry. Search results and the Activity page plug in later.
3. **Group E, onboarding (tasks 5 to 6).** Frontend only. Adds the "Show setup guide" action to the palette from group A, so it follows A. It can ship before A if the palette action wiring (5.6) is deferred.
4. **Group B, global search (tasks 7 to 8).** First backend route. Integrates with the palette from group A and adds `/search`.
5. **Group C, activity history (tasks 9 to 10).** The largest group and the only one with new storage. Last because it has the most risk and nothing else depends on it. It adds the Activity nav entry, the `g a` shortcut and the property Overview panel.
6. **Cross-cutting pass (tasks 11 to 12).** Consolidated accessibility and end-to-end coverage, dependency and route-table guards, README and final documentation.

The wave graph at the end schedules the work so that tasks writing the same file are in different waves. A wave may start tasks from several groups, but nothing is user-visible until its group's wiring tasks run, and the order above is the order to release.

Cross-group notes: `parseYearParam` and the `?year=` initializers are shared with the year-end-checklist spec and are conditional in both specs: whichever lands first adds them, the other reuses them (tasks 3.8, 3.14 and 3.18 read "add if absent, reuse if present" and never define a second helper). The sidebar guard (3.17) is the one deliberate change to existing behavior in this plan and is recorded in the changelog. The `g a` shortcut and the Activity navigation entry are added in group C (9.12), not group A, so group A never links to a missing page. The `focus=backup` Profile behavior is added in 3.14 and reused by group E.

This is a spec-only deliverable; implementation happens task by task later. Nothing here deploys or commits.

## Tasks

- [x] 1. Group D: Responsive layout (ship first)
  - [x] 1.1 Create `frontend/src/lib/propertySections.ts`
    - Export `currentSection(pathname, propertyId): PropertyNavItem | null` built on `PROPERTY_NAV` and `propertyPath`: strip a trailing slash, prefer the longest match, treat the empty segment as an exact match only, return `null` outside the property
    - _Requirements: 21.8, 21.9_
  - [x] 1.2 Write the section resolver property test
    - **Property 27: Section resolver round trip**
    - **Validates: Requirements 21.8, 21.9**
    - New `frontend/src/lib/propertySections.property.test.ts`
  - [x] 1.3 Rewrite `frontend/src/components/PropertySectionTabs.tsx` as a disclosure on narrow viewports
    - Keep the single `nav[aria-label="Property sections"]` and one `ul` of `NavLink`s at every width; add the `md:hidden` button "Property sections: {current}" with `aria-expanded` and `aria-controls`; the list is `hidden md:flex md:flex-wrap` when closed and a column when open
    - Close on link click, on Escape (return focus to the button) and when focus leaves the nav; no horizontal scroll; use `sectionTabClassName`, the 44px target classes and no added transitions
    - Update `PropertySectionTabs.test.tsx` and any test that queries the tabs (`PropertySection.test.tsx`, `PropertySwitcher.test.tsx`) so existing queries still pass, and add tests for open, Escape, focus leave, link choice, the current label and the one-landmark rule
    - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.10, 21.12, 29.1_
  - [x] 1.4 Raise form control font size on narrow viewports
    - Add `max-md:text-base` to the base classes of `Input.tsx`, `Select.tsx`, `Textarea.tsx`, `MoneyInput.tsx` and `DateInput.tsx`; keep `text-sm` at `md` and wider
    - Extend `touchTargets.test.tsx` (or the primitives tests) with a class assertion for each control
    - _Requirements: 22.4, 22.6_
  - [x] 1.5 Make `RecordModal` and the table scroll area viewport-safe
    - In `RecordModal.tsx` use `max-h-[90dvh]`, `p-4 sm:p-6`, `w-[calc(100vw-1.5rem)] sm:w-[92vw]` and add an optional `footer` slot rendered in a sticky bottom bar inside the scrolling panel; forms without the slot render unchanged
    - In `ResponsiveTable.tsx` change the default sticky scroll area from `max-h-[70vh]` to `max-h-[70dvh]`
    - Update `RecordModal.test.tsx` and `ResponsiveTable.test.tsx` for the new classes and the footer slot
    - _Requirements: 22.2, 22.3, 22.9_
  - [x] 1.6 Audit and fix form grids and toolbars for 320px
    - Read each form (`TransactionForm`, `ItemizedEntryForm`, `TotalForm`, and the asset, loan, property and import forms) and each page toolbar (tax-year select groups, report toolbars, dashboard tiles, property Overview tiles); switch multi-column grids to `grid-cols-1 sm:grid-cols-2`, add `flex-wrap gap-2` to toolbars, and move the footer buttons of the modal forms into the `RecordModal` footer slot from 1.5
    - Record any finding too large for this task in `docs/future-improvements.md`
    - Update the touched component tests
    - _Requirements: 22.1, 22.4, 22.5, 22.7, 22.10_
  - [x] 1.7 Add `frontend/e2e/responsive.spec.ts`
    - Viewports 320x640, 375x800, 768x1024, 1024x768: no horizontal page scroll on the primary routes and no axe violation in both Themes
    - Tab disclosure at 375 and 768: open by keyboard, choose a section, Escape, `aria-current`; the tab area is at most two rows at 768 and 1023 with the seven-tab set (the test clones one `li` in the list with `page.evaluate` to simulate the year-end-checklist tab)
    - Keep this check for the life of the feature: if it shows more than two rows at 768, apply the documented fallback (change `md:` to `lg:` in `PropertySectionTabs`, update the Narrow_Viewport and Tablet_Viewport wording and the viewport tests, and record it in `docs/developer-guide.md`) and re-run the check at 768 and 1023
    - At 320: the add-transaction modal keeps Save inside the viewport; the palette dialog is not part of this task
    - _Requirements: 21.11, 21.13, 22.1, 22.3, 23.1, 23.2, 23.3_
  - [x] 1.8 Group D documentation
    - `docs/developer-guide.md`: the tab disclosure pattern and breakpoint, the `RecordModal` footer slot, `dvh` and the 16px input rule, in the Navigation, RecordModal and ResponsiveTable sections
    - `docs/future-improvements.md`: remove the "Property tabs on mobile" section
    - `docs/testing.md`: the viewport checks and `e2e/responsive.spec.ts`
    - `CHANGELOG.md`: "Responsive property tabs and small-screen form fixes"
    - _Requirements: 29.4_

- [x] 2. Checkpoint - Group D
  - Ensure all tests pass (`npm test`, `npm run lint`, `npm run build`, `npm run e2e`), ask the user if questions arise.

- [x] 3. Group A: Command palette and shortcuts
  - [x] 3.1 Create `frontend/src/lib/shortcuts/eligibility.ts`
    - `classifyTarget`, `KeyEventInfo`, `isEligiblePlainKey` and `isPaletteChord` as in the design; `hasBlockingDialog(doc)` using `[role="dialog"][data-state="open"]:not([data-palette])` and the `alertdialog` equivalent; no Shift restriction
    - _Requirements: 1.7, 1.8, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.10_
  - [x] 3.2 Create `frontend/src/lib/shortcuts/registry.ts` and `sequence.ts`
    - `SHORTCUTS` with Cmd/Ctrl+K, `/`, `?`, and the `g` sequences `d`, `p`, `r`, `c`, `i` (the `g a` entry is added with the Activity page in 9.12); `formatKeys`, `findDuplicates`; `stepSequence` and `SEQUENCE_TIMEOUT_MS = 1000`
    - _Requirements: 6.1, 6.3, 6.4, 6.8_
  - [x] 3.3 Write the eligibility property tests
    - **Property 1: Plain-key shortcut eligibility**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.10**
    - **Property 2: Palette chord eligibility**
    - **Validates: Requirements 1.1, 1.7, 1.8**
    - New `frontend/src/lib/shortcuts/eligibility.property.test.ts` with an independent oracle
  - [x] 3.4 Write the sequence property test and registry examples
    - **Property 3: Sequence matcher**
    - **Validates: Requirements 6.3, 6.4**
    - New `frontend/src/lib/shortcuts/sequence.property.test.ts`; add `registry.test.ts` asserting `findDuplicates(SHORTCUTS)` is empty and that every entry has a label and a group
  - [x] 3.5 Create the navigation guard
    - New `frontend/src/lib/navigationGuard.tsx`: `NavigationGuardProvider` (holds dirty flags, renders a `ConfirmDialog` "Discard changes?"), `useRegisterDirty(key, dirty)`, `useGuardedNavigate()`
    - In `pages/ImportsLayout.tsx` call `useRegisterDirty("imports", dirty)`; leave the existing context and the `ImportSectionTabs` behavior unchanged (`MainNav` is guarded in task 3.17)
    - New `navigationGuard.test.tsx`: dirty flag triggers the confirm, Keep editing stays, Discard navigates, clean navigates directly
    - _Requirements: 7.8_
  - [x] 3.6 Create `frontend/src/components/palette/paletteRank.ts`
    - `normalize`, `tokenize`, `rankLocal(items, query, limit)` and `moveHighlight(index, length, direction)` (pure, deterministic)
    - _Requirements: 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5_
  - [x] 3.7 Write the ranking property tests
    - **Property 4: Palette ranking and filtering**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
    - **Property 5: Highlight index wraps**
    - **Validates: Requirements 4.4, 4.5**
    - New `frontend/src/components/palette/paletteRank.property.test.ts`
  - [x] 3.8 Create `paletteItems.ts` and add `parseYearParam`
    - `frontend/src/components/palette/paletteItems.ts`: the `PaletteItem` types, `buildLocalItems({ properties, years, currentPropertyId, platform, hasProperty })` and `resolveActionTarget`
    - Conditional: add if absent, reuse if present. Add `parseYearParam(value)` to `frontend/src/lib/taxYears.ts` (a canonical decimal integer from 1900 through 2200, else `null`) only if the year-end-checklist work has not already added it; extend `taxYears.test.ts` only for cases not already covered
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.9_
  - [x] 3.9 Write the destination and action property tests
    - **Property 6: Year parameter parsing**
    - **Validates: Requirements 2.5, 2.6**
    - **Property 7: Action targets**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5**
    - New `frontend/src/components/palette/paletteItems.property.test.ts`
  - [x] 3.10 Build the shortcuts provider and help dialog
    - New `components/palette/paletteContext.ts` (context and `usePalette`), `components/shortcuts/ShortcutsProvider.tsx` (one `document` `keydown` listener removed on unmount; chord, plain keys, sequences, navigation through `useGuardedNavigate`) and `ShortcutsHelp.tsx` (Radix `Dialog`, `data-palette`, `dl` by group, `kbd`, Cmd or Ctrl by platform, focus return)
    - Tests: one listener and cleanup, ignored in inputs and with a `RecordModal` open, `/` and `?` open the right dialog, `g` then `d` navigates, timeout resets, help lists every shortcut and closes with Escape
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.8, 7.9_
  - [x] 3.11 Build the command palette
    - New `components/palette/PaletteProvider.tsx`, `CommandPalette.tsx` and `PaletteList.tsx`: Radix `Dialog` named "Command palette" with `data-palette`, combobox input, `listbox`/`option`/`group` structure, `aria-activedescendant`, wrapped arrow keys, Home and End, Enter, live region with the result count, property picker second step, unavailable actions with the reason, focus return or route-change focus, no transition under Reduced_Motion, 320px sizing with `dvh`
    - The "Show setup guide" action and the "Download backup" action are present; "Show setup guide" renders only when `SetupGuideContext` provides a handler (group E)
    - Tests: open and close paths, focus return, ARIA roles, keyboard, empty-query list, no network request without a query, axe in both Themes
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6, 2.7, 2.8, 3.4, 3.5, 3.7, 3.8, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 5.5, 5.6, 22.8_
  - [x] 3.12 Wire the shell
    - `AppLayout.tsx`: wrap in `NavigationGuardProvider`, `ShortcutsProvider` and `PaletteProvider`, add the header "Search" button (`SearchIcon`, `aria-label`, `aria-keyshortcuts`) with a 44px target on narrow viewports
    - `ProfileMenu.tsx`: add "Keyboard shortcuts"
    - Update `AppLayout.test.tsx`, `AppLayout.drawer.test.tsx` and `ProfileMenu.test.tsx` for the added controls only
    - _Requirements: 1.4, 6.7, 6.9, 22.5, 29.3_
  - [x] 3.13 Add the `new=1` parameter to the add flows
    - New `lib/useNewParam.ts` and `useNewParam.test.tsx` (opens once, removes the parameter with replace, StrictMode-safe, waits for `ready`)
    - Wire into `TransactionsPage`, `ItemizedExpensesPage`, `AssetsPage`, `LoansPage` and `PropertiesPage`, and extend their page tests
    - _Requirements: 3.2, 3.6_
  - [x] 3.14 Honor `year` on Combined Reports and `focus=backup` on Profile
    - `CombinedReportsPage.tsx`: initialize the year from `parseYearParam(searchParams.get("year"))` with the latest completed year as fallback (reuse the helper from 3.8 or the year-end-checklist work; do not define another)
    - `ProfilePage.tsx`: with `focus=backup`, focus `#backup-heading` (add `tabIndex={-1}`) once and start no download
    - Extend `CombinedReportsPage.test.tsx` and `ProfilePage.test.tsx`
    - _Requirements: 2.5, 2.6, 3.8_
  - [x] 3.15 Add `frontend/e2e/palette.spec.ts`
    - Chord opens, typing filters, arrows and Enter navigate, Escape returns focus, shortcuts ignored in a field and with an open `RecordModal`, help dialog by `?`, dirty Imports form shows the discard confirm, both Themes, and a 320px run
    - _Requirements: 23.4, 22.8_
  - [x] 3.16 Group A documentation
    - `docs/developer-guide.md`: the shortcuts registry and how to add a shortcut, the eligibility rules, palette items and actions, the navigation guard, `new` and `year` parameters
    - `docs/testing.md`: the new suites and `e2e/palette.spec.ts`
    - `CHANGELOG.md`: "Command palette and keyboard shortcuts"
    - _Requirements: 29.4_

  - [x] 3.17 Guard the sidebar links with the navigation guard
    - `frontend/src/components/MainNav.tsx`: each sidebar `NavLink` calls `useGuardedNavigate().go(to)` on a plain primary click (no modifier key, `button === 0`, not already default-prevented) after `preventDefault()`; modified and non-primary clicks keep the browser default; keep `href`, `aria-current`, the accessible names and keyboard activation; call the existing `onNavigate` prop (which closes the mobile drawer) only once navigation proceeds, so a cancelled confirm leaves the drawer open; `AppLayout.tsx` needs no change
    - Extend `MainNav.test.tsx`: dirty guard (confirm shown, Keep editing stays on the route, Discard navigates), clean guard (direct navigation), modifier click and middle click (no confirm), drawer stays open on cancel; extend `AppLayout.drawer.test.tsx` only if it asserts drawer closing on link click
    - New `frontend/e2e/sidebar-guard.spec.ts`: with a dirty Imports form, a sidebar click shows "Discard changes?"; Keep editing stays; Discard navigates
    - `CHANGELOG.md`: add a changed-behavior note: "Sidebar links now ask before discarding an unsaved import form (same guard as the command palette)"; `docs/developer-guide.md`: state that `MainNav` uses the navigation guard
    - _Requirements: 30.1, 30.2, 30.3, 30.4, 30.5, 30.6, 30.7, 30.8, 7.8, 29.3_
  - [x] 3.18 Honor `?year=` on the Transactions and per-property Reports pages (conditional)
    - Conditional: add if absent, reuse if present. Check whether the year-end-checklist work already initialized `taxYear` from a valid `?year=` in `frontend/src/pages/TransactionsPage.tsx` and `frontend/src/pages/ReportsPage.tsx`. Add only the missing initializers, using `parseYearParam` from `frontend/src/lib/taxYears.ts` with `latestCompletedTaxYear()` as the fallback; do not write the parameter back and do not define a second helper
    - Extend the two page tests for a valid, invalid and absent value only where those cases are not already covered; search result links (`/properties/{id}/transactions?year=...`) rely on this
    - _Requirements: 2.5, 2.6, 8.7_

- [x] 4. Checkpoint - Group A
  - Ensure all tests pass (`npm test`, `npm run lint`, `npm run build`, `npm run e2e`), ask the user if questions arise.

- [x] 5. Group E: Onboarding
  - [x] 5.1 Create `frontend/src/lib/onboardingStorage.ts`
    - `SetupState`, `DEFAULT_SETUP_STATE`, `setupKeys` (the dismissed key reuses `checklistKeys().dismissed`), `readSetupState`, `writeSetupState`, `clearSetupState`, `serializeSetupState`, `parseSetupState`; defaults on any storage error or invalid value
    - _Requirements: 26.1, 26.2, 26.5, 26.6, 26.8_
  - [x] 5.2 Write the setup state property test
    - **Property 29: Setup state round trip**
    - **Validates: Requirements 26.5, 26.7**
    - New `frontend/src/lib/onboardingStorage.property.test.ts`; add examples for unavailable storage and the existing dismissed key
  - [x] 5.3 Extend `frontend/src/components/dashboard/checklist.ts`
    - Add `nextStep(view)` and `stepReason(id)`; leave `computeChecklist`, its types and `checklistProgressText` unchanged
    - _Requirements: 24.1, 24.2, 24.8_
  - [x] 5.4 Write the setup guide derivation property test
    - **Property 28: Setup guide derivation**
    - **Validates: Requirements 24.1, 24.2, 24.6, 24.8**
    - Extend `frontend/src/components/dashboard/checklist.property.test.ts`
  - [x] 5.5 Update `ChecklistCard.tsx` and add `SetupGuideContext`
    - New `lib/setupGuide.tsx` (context with `showSetupGuide()` and a reset signal)
    - `ChecklistCard.tsx`: "Next" label and reason on the first incomplete step, Collapse and Expand button with `aria-expanded` and `aria-controls="checklist-steps"`, the all-done "You're set up" state with Dismiss, a `role="status"` live region announcing a completed step, the sample data link only while `has_properties` is false (to `/profile?focus=backup`, with the replace-all-data warning), no motion under Reduced_Motion
    - Extend `ChecklistCard.test.tsx` and keep the existing assertions ("x of 4 done", labels, dismiss) passing
    - _Requirements: 24.1, 24.2, 24.3, 24.4, 24.5, 24.6, 24.7, 24.8, 24.9, 26.1, 26.2, 26.3, 27.1, 27.2, 27.3, 27.4, 27.6_
  - [x] 5.6 Wire "Show setup guide" into the shell
    - Provide `SetupGuideContext` in `AppLayout.tsx`; add the account-menu item in `ProfileMenu.tsx`; register the palette action in `paletteItems.ts` only when the context is present; the action clears the stored state, navigates to `/` and moves focus to `#checklist-heading` once
    - Tests for the menu item, the palette action, the all-done case and focus placement
    - _Requirements: 26.3, 26.4_
  - [x] 5.7 Create `components/ui/EmptyGuide.tsx` and `lib/emptyCopy.ts`
    - `EmptyGuide` wraps `StateBlock kind="empty"` with title, description, primary action and optional secondary; `emptyCopy.ts` holds one entry per page
    - Export from `components/ui/index.ts`; test that no copy contains tax-advice phrasing ("you should report", "deduct", "deductible") and that each entry names what the app records
    - _Requirements: 25.4, 25.6, 27.5_
  - [x] 5.8 Add empty-state guidance to the pages
    - Transactions, Repairs, Assets, Loans, Properties, Reports and Combined Reports use `EmptyGuide` when loaded and empty (never while loading or failed); Properties and `DashboardEmptyState` add the "Explore with sample data" link only while the user owns no property; Reports link to Transactions and Import
    - Extend each page's test and keep existing empty-state assertions passing
    - _Requirements: 25.1, 25.2, 25.3, 25.5, 24.3_
  - [x] 5.9 Add `frontend/e2e/onboarding.spec.ts`
    - Empty account: the guide shows "Next", the sample link, collapse and expand by keyboard, dismiss, "Show setup guide" from the account menu and the palette; axe in both Themes; reduced-motion emulation shows no animation classes
    - _Requirements: 26.1, 26.2, 26.3, 27.5, 27.6_
  - [x] 5.10 Group E documentation
    - `docs/developer-guide.md`: setup state keys and storage rules, the guide derivation, `EmptyGuide` and `emptyCopy`
    - `docs/testing.md`; `CHANGELOG.md`: "Setup guide and empty-state guidance"
    - _Requirements: 29.4_

- [x] 6. Checkpoint - Group E
  - Ensure all tests pass (`npm test`, `npm run lint`, `npm run build`, `npm run e2e`), ask the user if questions arise.

- [x] 7. Group B: Global search
  - [x] 7.1 Create `backend/src/logstead/services/search_config.py` and `search_match.py`
    - `SearchConfig` and `SEARCH_CONFIG`; pure `normalize`, `tokenize`, `match_rank`, `sort_key`, `link_for`; no I/O
    - _Requirements: 8.9, 9.1, 9.2, 9.3, 9.4, 9.5, 9.9_
  - [x] 7.2 Write the matching property tests
    - **Property 9: Query normalization is idempotent**
    - **Validates: Requirements 9.1, 9.8**
    - **Property 8: Search matching** (pure part: every match contains every token, pattern characters are literal)
    - **Validates: Requirements 9.2, 9.9**
    - **Property 10: Search order and determinism** (pure ordering)
    - **Validates: Requirements 9.4, 9.7**
    - New `backend/tests/services/test_search_match_property.py` with unicode, combining marks and pattern characters
  - [x] 7.3 Create `backend/src/logstead/services/search.py`
    - `SearchHit`, `SearchGroup`, `SearchResult` and `SearchService.search` per the design: validate `q` and `limit`, list the user's properties and businesses, read each property's transactions, assets and loans once, count `scanned`, stop at the Scan_Cap and set `truncated`, search itemized entries on description and notes and other transactions on description, return the six groups in order with `total` independent of `limit`; no write, no S3
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 9.3, 9.5, 9.6, 10.1, 10.4, 12.1, 12.2, 12.3, 12.4, 12.5_
  - [x] 7.4 Write the search service property tests
    - **Property 8: Search matching** (service level)
    - **Validates: Requirements 8.2, 9.2, 9.5, 9.6, 9.10**
    - **Property 10: Search order and determinism** (service level)
    - **Validates: Requirements 9.4, 9.7**
    - **Property 11: Search is user-scoped and shaped**
    - **Validates: Requirements 8.3, 8.5, 10.1**
    - **Property 12: Money and links pass through unchanged**
    - **Validates: Requirements 8.7, 8.8, 8.9, 11.5**
    - **Property 13: Scan cap and truncation**
    - **Validates: Requirements 12.2, 12.3, 12.5**
    - New `backend/tests/services/test_search_service_property.py` over moto with a recording repository; add examples for the 20,000 item default cap, a corrupt loan returning the existing error, and `propertyId` restriction, and a case proving that a record whose amount, date, or category label contains the query but whose text fields do not is not returned (the searchable text is descriptions, notes, names and addresses only)
  - [x] 7.5 Add the `/search` route, throttle and route tests
    - In `router/handler.py`: `_search_service(wiring, user)`, `_search` handler (`propertyId` goes through the id validator and `_require_owned_property` first), `("GET", "/search", _search, False)` in `_ROUTES`, no other method; log only counts and the scanned total, never `q`
    - In `infra/template.yaml`: `RouteSettings` for `"GET /search"` (rate 2, burst 5, detailed metrics) and a `ThrottledSearch` event on `ApiFunction`
    - New `backend/tests/router/test_search_routes.py` (success, `400` for `q` and `limit`, malformed and missing and foreign `propertyId` with the byte-identical `404`, `POST` and `PUT` resolve to no route, no `q` in logs); extend `test_cross_user_authorization.py` and `backend/tests/infra` template checks
    - _Requirements: 8.1, 8.6, 9.3, 10.2, 10.3, 10.5, 10.6, 12.6, 29.2_
  - [x] 7.6 Create `frontend/src/api/search.ts`
    - `SearchApi` with an injectable `ApiClient`, `search(q, { limit, propertyId, signal })`, the response types, and the shared instance; `search.test.ts` for path, query string and abort
    - _Requirements: 8.1, 8.6, 11.1_
  - [x] 7.7 Create `frontend/src/lib/highlight.ts` and `safeLink.ts`
    - `highlightSegments(text, tokens)` (normalization-aware, preserves the original text) and `isSafeAppLink(link)`
    - _Requirements: 11.5, 11.9_
  - [x] 7.8 Write the highlight and link property tests
    - **Property 14: Highlight segments preserve the text**
    - **Validates: Requirements 11.9**
    - **Property 15: Safe link check**
    - **Validates: Requirements 11.5**
    - New `frontend/src/lib/highlight.property.test.ts` and `safeLink.property.test.ts`
  - [x] 7.9 Integrate search into the palette
    - New `components/search/HighlightedText.tsx`, `SearchResults.tsx`, and `components/palette/useGlobalSearch.ts` (250 ms debounce, abort, keep previous results, retry); extend `CommandPalette.tsx` and `PaletteList.tsx` with the group labels, "See all results", `aria-busy`, the truncation notice and the error state; navigation only for safe links
    - Tests with fake timers: no request below 2 characters, debounce, abort on change, busy state, error with retry, group labels, unsafe link ignored
    - _Requirements: 4.8, 5.5, 5.6, 11.1, 11.2, 11.3, 11.4, 11.5, 11.9, 11.10_
  - [x] 7.10 Add the Search page and the `focus` parameter
    - New `pages/SearchPage.tsx` (one `h1`, labeled field, live region, up to 25 hits per group, `q` kept in the URL with replace navigation), route `{ path: "search", element: <SearchPage /> }` in `routes.tsx`, and the route comment
    - New `lib/useFocusParam.ts` wired into `TransactionsPage`, `ItemizedExpensesPage`, `AssetsPage` and `LoansPage` (rows get `id="row-{id}"`); unknown ids are ignored
    - Tests for the page states, the focus hook, and `pageConformance.test.ts` and `routes.test.tsx` updates
    - _Requirements: 8.10, 8.11, 11.6, 11.7, 11.8, 28.3, 29.1_
  - [x] 7.11 Extend the browser tests for search
    - Add `GET /search` stubs to `e2e/fixtures.ts`; extend `e2e/palette.spec.ts` for typing a query, grouped results, Enter on a hit, "See all results", and the Search page with axe in both Themes
    - _Requirements: 23.4, 23.6_
  - [x] 7.12 Group B documentation
    - `docs/api.md`: `GET /search`, parameters, response, errors, limits; `docs/developer-guide.md`: search service, matching rules, the scan cap, how to add a searchable field; `docs/testing.md`; `CHANGELOG.md`: "Global search"
    - _Requirements: 29.4_

- [x] 8. Checkpoint - Group B
  - Ensure all backend and frontend tests pass (`pytest`, `npm test`, `npm run lint`, `npm run build`, `npm run e2e`), ask the user if questions arise.

- [x] 9. Group C: Activity history
  - [x] 9.1 Add the repository and key seams
    - `repository/keys.py`: `ACT_PREFIX`, `activity_sk`, `activity_list_prefix`, `activity_gsi1_pk`
    - `repository/dynamo_repo.py`: optional `start_key` on `query` (first request only) and optional `condition`, `names`, `values` on `put_item` with a `ConditionFailed` exception; existing signatures and behavior unchanged
    - New `backend/tests/repository/test_activity_keys.py`: key format, `ACT#` collides with no existing prefix, every `USER#` query in `services/*.py` uses a prefix (source scan), start key paging, conditional put success and failure
    - _Requirements: 18.2, 18.3, 15.4_
  - [x] 9.2 Create `activity_config.py` and `activity_events.py`
    - `ActivityConfig` and `ACTIVITY_CONFIG`; pure `FIELDS`, `project`, `diff`, `bound`, `summarize`, `inverted_millis`, `event_sk`, `encode_cursor`, `decode_cursor`, `is_restorable`; no I/O
    - Define `retention_days` (730) once in `activity_config.py`; add a source-scan test (in `test_activity_keys.py` or a new `test_activity_config.py`) asserting that no other backend source file contains a literal `730` and that the `ttl` computation reads `ACTIVITY_CONFIG.retention_days`
    - _Requirements: 13.10, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.9, 15.6, 17.1, 17.2, 18.1, 18.2, 18.12_
  - [x] 9.3 Write the pure event property tests
    - **Property 16: Event projection, diff and round trip**
    - **Validates: Requirements 13.10, 14.2, 14.3, 14.4, 14.5, 14.9**
    - **Property 17: Event bounds**
    - **Validates: Requirements 14.1, 14.6**
    - **Property 19: Event keys and retention**
    - **Validates: Requirements 18.1, 18.2**
    - **Property 21: Restorable classification**
    - **Validates: Requirements 17.1, 17.2**
    - New `backend/tests/services/test_activity_events_property.py`; Property 21 also checks agreement with the Undo rules in `undoMappers.ts` through a shared table of cases
  - [x] 9.4 Create `ActivityRecorder` in `backend/src/logstead/services/activity.py`
    - `NewEvent`, `ActivityRecorder.record` (builds the item, sets `ttl`, GSI1 keys and `restorePayload` only when restorable; catches every exception, logs a structured warning, returns), `purge_user`, `purge_property` (batched deletes); user id and clock from the constructor
    - Unit tests in `backend/tests/services/test_activity_recorder.py`: item shape, one write per event, failure swallowed and logged, purge scopes
    - _Requirements: 13.1, 13.11, 13.12, 14.1, 14.8, 17.2, 18.1, 18.2, 18.7, 18.10, 19.5, 20.1, 20.4_
  - [x] 9.5 Add `ActivityService` to `activity.py`
    - `list_user`, `list_property` (cursor, filters, 2,000 item read cap per request, skip expired items), and `restore` (property check first, lookup by `eventId`, claim by conditional put, re-create through the existing services, mark restored, release the claim on failure, treat a `pending` claim older than 5 minutes as free, record one `restore` event)
    - _Requirements: 13.9, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7, 15.9, 15.10, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9_
  - [x] 9.6 Write the activity service property tests
    - **Property 18: Event serialization round trip**
    - **Validates: Requirements 14.7, 14.8, 14.10**
    - **Property 20: Pagination completeness**
    - **Validates: Requirements 15.4, 15.5, 15.9**
    - New `backend/tests/services/test_activity_service_property.py` over moto
  - [x] 9.7 Write the restore property tests
    - **Property 22: Restore round trip**
    - **Validates: Requirements 17.4, 17.9, 17.12**
    - **Property 23: Restore is claimed once**
    - **Validates: Requirements 17.5, 17.6**
    - New `backend/tests/services/test_activity_restore_property.py`; examples for a failed re-create releasing the claim, a stale pending claim, a non-restorable event, and an unknown event
  - [x] 9.8 Wire recording and the new routes in `router/handler.py`
    - `_activity_recorder(wiring, user)`, `_activity_service(wiring, user)`, and the `_with_activity` decorator (best-effort before-read, record only after a `200`, `201` or `204`, inside `_property_scoped`)
    - Decorate the transaction, itemized, asset, loan and property mutation handlers, the Schedule E import handlers and the expense import confirm; call `purge_property` before the property delete event; after backup `restore` call `purge_user` then record the restore event; after backup `clear` call `purge_user`
    - Add `GET /activity`, `GET /properties/{propertyId}/activity` and `POST /properties/{propertyId}/activity/{eventId}/restore`, validating `limit`, `cursor`, `entity`, `action`, `propertyId` and the `eventId` shape; no other methods
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.12, 13.13, 15.1, 15.2, 15.3, 15.7, 15.8, 15.11, 17.3, 18.5, 18.6, 18.7, 18.8, 20.2, 20.3, 29.2_
  - [x] 9.9 Write router and backup tests
    - New `backend/tests/router/test_activity_routes.py`: each handler records one event with the right kind, a `400` or `404` records nothing, an unchanged update records nothing, bulk operations record one event, list filters and pagination, `400`s, byte-identical `404`s, `409` reasons, methods
    - Extend `test_cross_user_authorization.py` (activity list, property list and restore as another user) and the backup tests (export has no `ACT#` items and `schema_version` stays `"1"`; clear and restore purge; property delete purges that property's events)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.10, 13.11, 13.12, 15.6, 15.7, 15.8, 17.6, 17.7, 18.4, 18.5, 18.6, 18.7, 18.8_
  - [x] 9.10 Write the isolation property tests
    - **Property 24: Reports do not depend on activity**
    - **Validates: Requirements 19.2, 19.3, 19.4, 13.12**
    - **Property 25: Recording failure does not change the response**
    - **Validates: Requirements 20.1, 20.2**
    - **Property 26: Purge on clear, restore and property delete**
    - **Validates: Requirements 18.5, 18.6, 18.7, 13.8**
    - New `backend/tests/services/test_activity_isolation_property.py`; add a source scan test that `report.py`, `dashboard.py`, `carryforward.py`, `loan.py`, `depreciation.py`, `transaction.py` and `backup.py` do not import `services.activity`
  - [x] 9.11 Create `frontend/src/api/activity.ts` and `lib/activityText.ts`
    - `ActivityApi` (`list`, `listForProperty`, `restore`), the wire types, labels for actions and entities, `eventLink`; tests for paths, query strings and labels
    - _Requirements: 15.1, 15.2, 15.3, 16.3, 16.10, 17.3_
  - [x] 9.12 Build the Activity page and navigation entry
    - `pages/ActivityPage.tsx`, `components/activity/ActivityList.tsx` and `ActivityEventRow.tsx` (`Badge`, `time`, `dl` details with `formatMoney`, filters, Load more, polite count announcement, skeleton and error states, Empty_State); route `{ path: "activity", ... }` in `routes.tsx`; `{ to: "/activity", label: "Activity", icon: "activity" }` in the `tools` group of `navConfig.ts`, `"activity"` in `NavIconName`, `HistoryIcon` in `ui/icons.tsx` and `MainNav` ICONS; add the `g a` entry to `SHORTCUTS`
    - Update `navConfig.test.ts`, `MainNav.test.tsx`, `routes.test.tsx`, `pageConformance.test.ts`, the shortcut registry tests and the palette destination tests for the added entry only
    - _Requirements: 6.1, 16.1, 16.2, 16.3, 16.4, 16.5, 16.7, 16.8, 16.9, 28.3, 29.1, 29.3_
  - [x] 9.13 Add Restore to the Activity page
    - In `ActivityEventRow.tsx`: "Restore" only when `restorable` and not restored, `ConfirmDialog` stating the record returns with a new id, a toast with a link to the restored record, "Restored" state, no control on update events, error and `409` handling
    - _Requirements: 16.10, 17.10, 17.11, 17.13_
  - [x] 9.14 Add the Recent activity panel to the property Overview
    - New `components/activity/RecentActivityPanel.tsx` (latest 5 events through the property route, link to `/activity?property={id}`, empty and error states); render it in `PropertyDetailPage.tsx` below the tiles so a failure leaves the tiles usable; update `PropertyDetailPage.test.tsx`
    - _Requirements: 16.5, 16.6, 16.7, 16.8_
  - [x] 9.15 Extend browser tests for activity
    - Add `GET /activity`, property activity and restore stubs to `e2e/fixtures.ts` (stateful for the restore flow); extend `e2e/smoke.spec.ts`: delete a transaction, open Activity, restore it; add `/activity` to the a11y route list for both Themes
    - Add a toast Undo test (frontend test with the stubbed API): after deleting a transaction, choosing Undo in the toast calls the create route and never calls the restore route, and the activity list then shows a `create` event next to the `delete` event with no link between them
    - _Requirements: 17.14, 23.6, 28.2_
  - [x] 9.16 Group C documentation
    - `docs/api.md`: the four routes, parameters, response, errors; `docs/data-model.md`: the activity item type, key, GSI1 use, `ttl`, retention, cost basis, backup interplay and the purge rules; `docs/developer-guide.md`: recording an event from a handler, the allow-list, adding an entity, and the "Undo and record IDs" section updated for history restore and for the toast Undo staying client-side (recorded as an ordinary create); `docs/testing.md`; `CHANGELOG.md`: "Activity history"
    - `docs/future-improvements.md`: add "Restore with the original id", "Atomic activity recording" and "Route toast Undo through the history"
    - _Requirements: 18.11, 18.12, 29.4, 29.5_

- [x] 10. Checkpoint - Group C
  - Ensure all backend and frontend tests pass (`pytest`, `npm test`, `npm run lint`, `npm run build`, `npm run e2e`), ask the user if questions arise.

- [x] 11. Cross-cutting accessibility, guards and documentation
  - [x] 11.1 Consolidate accessibility and end-to-end coverage
    - `test/axeRoutes.test.tsx`: add `/search?q=oak` and `/activity`, plus the palette open, the shortcuts help open, and the setup guide on an empty dashboard
    - `e2e/a11y.spec.ts`: add the new routes and the palette in both Themes; confirm `color-contrast` is evaluated; extend `touchTargets.test.tsx` for the header Search button, the tab disclosure button, and the guide controls
    - _Requirements: 22.5, 23.1, 28.2, 28.3, 28.4, 28.5, 29.6_
  - [x] 11.2 Add the dependency, route and CSP guards
    - New `frontend/src/test/noNewDependencies.test.ts` (the `dependencies` and `devDependencies` name sets equal the committed list; no external URL, `dangerouslySetInnerHTML`, `eval` or inline script in the new sources); a backend test that `requirements.txt` is unchanged by name; a router test that the route table gained exactly the four documented routes and no changed route
    - _Requirements: 28.1, 28.6, 28.7, 28.8, 28.9, 29.1, 29.2_
  - [x] 11.3 Final documentation pass
    - `README.md`: add command palette, shortcuts, search, activity history, responsive layout and the setup guide to the feature list
    - `docs/future-improvements.md`: confirm the "Property tabs on mobile" item is gone and the deferred items from the design's recorded decisions are listed
    - Read `docs/developer-guide.md`, `docs/api.md`, `docs/data-model.md`, `docs/testing.md` and `CHANGELOG.md` once for consistency across the five groups
    - _Requirements: 29.4_

- [x] 12. Final checkpoint - full verification
  - Ensure backend `pytest`, frontend `vitest`, `npm run lint`, `npm run build`, the type check and `npm run e2e` pass, ask the user if questions arise.

## Notes

- Every leaf task is required. There are no optional sub-tasks in this plan, matching the year-end-checklist and itemized-expenses plans.
- Groups are independently shippable in the recommended order D, A, E, B, C. A group may be released without the groups after it: nothing in an earlier group links to a later group's page.
- The pure logic layers (shortcut eligibility and sequences, ranking, matching, event projection, keys, the section resolver, setup state) are the core. The providers, pages and routes add no rules of their own.
- Tasks that write the same file sit in different waves: `PropertySectionTabs.tsx` (1.3), `RecordModal.tsx` and `ResponsiveTable.tsx` (1.5), page and form files (1.6, 3.13, 3.14, 5.8, 7.10, 3.18), `MainNav.tsx` and `MainNav.test.tsx` (3.17, 9.12), `CHANGELOG.md` and the docs (1.8, 3.16, 3.17, 5.10, 7.12, 9.16), `AppLayout.tsx` and `ProfileMenu.tsx` (3.12, 5.6), `paletteItems.ts` (3.8, 5.6), `CommandPalette.tsx` and `PaletteList.tsx` (3.11, 7.9), `routes.tsx` (7.10, 9.12), `navConfig.ts` and `registry.ts` (3.2, 9.12), `router/handler.py` (7.5, 9.8), `infra/template.yaml` (7.5), `services/activity.py` (9.4, 9.5), `e2e/fixtures.ts` (7.11, 9.15), `e2e/palette.spec.ts` (3.15, 7.11), `test_cross_user_authorization.py` (7.5, 9.9), and the documentation files (1.8, 3.16, 5.10, 7.12, 9.16, 11.3).
- Verified gaps this plan closes: the palette cannot read the Imports dirty state from `AppLayout`, so a navigation guard is added (3.5); `RecordModal` uses `vh` and has no pinned footer (1.5); inputs use 14px text (1.4); `DynamoRepository` has no start key or conditional write (9.1).
- No deploy and no commit are part of this plan. The SAM template changes only by the `GET /search` throttle entries.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4", "3.1", "3.2", "3.8", "5.1", "5.3", "7.1", "7.7", "9.1", "9.2"] },
    { "id": 1, "tasks": ["1.2", "1.3", "1.5", "3.3", "3.4", "3.5", "3.6", "3.9", "5.2", "5.4", "5.7", "7.2", "7.3", "7.6", "7.8", "9.3", "9.4", "9.11"] },
    { "id": 2, "tasks": ["1.6", "3.7", "3.10", "5.5", "7.4", "7.5", "9.5"] },
    { "id": 3, "tasks": ["1.7", "3.11", "3.13", "3.14", "9.6", "9.7", "9.8"] },
    { "id": 4, "tasks": ["1.8", "3.12", "5.8", "7.9", "9.9", "9.10"] },
    { "id": 5, "tasks": ["3.15", "5.6", "7.10", "3.17"] },
    { "id": 6, "tasks": ["3.16", "5.9", "9.12", "3.18"] },
    { "id": 7, "tasks": ["5.10", "7.11", "9.13", "9.14"] },
    { "id": 8, "tasks": ["7.12", "9.15"] },
    { "id": 9, "tasks": ["9.16", "11.1", "11.2"] },
    { "id": 10, "tasks": ["11.3"] }
  ]
}
```
