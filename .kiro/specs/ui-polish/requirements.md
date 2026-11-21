# Requirements Document

## Introduction

Logstead is a single-user Schedule E rental tax app (React/Vite/Tailwind SPA; Python 3.12 Lambda over a single-table DynamoDB design; SAM infrastructure). The app now has many pages (Dashboard, Properties, Businesses, Reports, Carryforward, Import, and per property Overview, Transactions, Repairs, Depreciable Assets, Loans, Schedule E Report). Moving between them, finding a record, seeing what changed, using the app on a phone or tablet, and getting started all take more steps than they should.

This feature is a UI polish release in five independently shippable areas:

- **A. Command palette and keyboard shortcuts.** A Cmd/Ctrl+K palette to jump to pages, properties and tax years and to start common actions, plus a small discoverable shortcut set and a help dialog.
- **B. Global search.** One search across properties, transaction descriptions, itemized entry descriptions and notes, asset descriptions, loans and businesses, with grouped results and links, reachable from the palette and from a search page.
- **C. Activity history.** A user-visible log of changes (create, update, delete, restore, import) on transactions, itemized entries, assets, loans and properties, with timestamps and before/after summaries, viewable globally and per property, and a narrow "restore a deleted record" action that extends Undo beyond the toast where a single create call can fully restore the record.
- **D. Mobile and tablet layout.** A responsive pattern for the property tabs (six today, seven if the year-end-checklist spec lands) and a pass over tables and forms on small screens, with Playwright viewport coverage.
- **E. Onboarding.** A dismissible, resumable setup guide and empty-state guidance that build on the sample data loader and the dashboard "Get set up" card.

The release changes no tax computation. Reports, the dashboard, the carryforward reconciliation and backups derive from stored records alone and never read the activity history.

### Out of scope

- Any change to a Schedule E line total, the precedence rules, the carryforward algorithm, the loan schedule engine, or the Schedule E import parser.
- Full-text or fuzzy server-side search engines (OpenSearch, a search index table), and search over receipt file contents, photos, or imported PDFs.
- Restoring an edit (reverting an update) from the history, restoring deleted properties, businesses, receipts or photos, and restoring imported or itemized-with-receipt rows.
- Syncing onboarding state across devices (the state is stored per browser).
- A guided product tour with spotlight overlays, and any third-party tour or command-palette library.
- The year-end-checklist feature itself. This spec only adapts to the number of property tabs (Requirement 21).
- Changes to the SAM stack beyond route throttle entries for the new routes.

### Grounding in the existing code

- Navigation: `components/navConfig.ts` (`NAV_GROUPS`, `PROPERTY_NAV`, `propertyPath`), `MainNav`, `AppLayout` (mobile drawer in a Radix `Dialog`, `closedByNavigation` focus handling), `PropertySectionTabs` (a `flex-wrap` list of `NavLink`s inside `nav[aria-label="Property sections"]`), `RouteAnnouncer` (moves focus to the page heading and announces on pathname change).
- Dialogs and guards: `RecordModal` (Radix `Dialog`), `ConfirmDialog`, `useRecordModal`, `useDiscardGuard`, `useOpenerFocusReturn`, `ImportsDirtyContext` and `useBeforeUnloadWhen`.
- Data already loaded in the shell: `ShellPropertiesProvider` holds the property list. `usePortfolioYearRange` and `usePropertyYearRange` give tax years.
- Undo: `useUndoableDelete`, `lib/undoMappers.ts` (`isTransactionSafeDelete`, `isLoanSafeDelete`, create-payload mappers). Undo re-creates through the normal create API and the record gets a new id (`docs/developer-guide.md`, "Undo and record IDs").
- Storage: one DynamoDB table `Logstead` with GSI1 and GSI2, a sparse TTL on the `ttl` attribute (used today only by Extraction_Job items), `PAY_PER_REQUEST`, point-in-time recovery. `repository/keys.py` is the only key scheme. `DynamoRepository.query` supports `limit` but not a start key or a conditional write.
- Router: `_property_scoped` proves ownership before any child read, and a missing and a foreign property return the identical `Property not found.` 404. `_check_path_ids` validates ids. Per-route throttles are listed in `infra/template.yaml`.
- Backup: `BackupService` exports transactions, assets, loans and usage per property and excludes receipts, photos, import sessions and schedule rows. `clear` deletes per property partition.
- Onboarding: `components/dashboard/ChecklistCard.tsx` ("Get set up", four steps, dismissal in `localStorage` through `lib/checklistStorage.ts`) and the Profile page "Load sample data" button, which replaces all current data after a confirm dialog.
- Tests and tooling: vitest, fast-check, React Testing Library, `vitest-axe` (`axeRoutes.test.tsx`), `pageConformance.test.ts`, `touchTargets.test.tsx`, Playwright (`e2e/a11y.spec.ts`, `e2e/smoke.spec.ts`, `e2e/fixtures.ts`), pytest with Hypothesis and moto.

### Decisions recorded

- **Palette without a library.** The palette is built on the existing `@radix-ui/react-dialog` and the WAI-ARIA combobox/listbox pattern. No `cmdk` or similar package is added (Requirement 28).
- **Search runs on the server.** Transactions, itemized entries, assets and loans are not loaded by the shell, and loading them all in the browser would send the full dataset on every first search. A new `GET /search` route reads through the existing services and filters in the Lambda. Pages, properties and tax years in the palette are matched in the browser from data already loaded (Requirement 8 and 9).
- **Search is bounded, never silently truncated.** A scan cap applies, and a capped response says so (Requirement 12).
- **Activity history is its own item type under the user partition.** Events live at `PK=USER#<id>`, `SK=ACT#<invertedTimestamp>#<eventId>` with a GSI1 entry per property. It adds no new table or index and reuses the existing `ttl` attribute for retention (Requirements 13 through 20).
- **Recording is best effort and after the change.** A failed history write is logged and never fails the user's save. History is a convenience log, not a source of truth (Requirement 20).
- **Retention is 24 months.** Events carry a `ttl` of 730 days. History is excluded from backups, deleted by "Clear all data" and by restore from backup, and deleted with a property (Requirement 18).
- **Scope is view-only plus restore of safe deletes.** Updates are never reverted from the history. A deleted transaction, itemized entry, asset or loan can be restored from the history only when the toast Undo rules would allow it, using a new id (Requirement 17).
- **Bulk operations log one event.** A Schedule E import, an expense import confirmation and a backup restore each write one summary event, not one per row (Requirement 13).
- **Activity is not a property tab.** The Activity page is `/activity` (with a property filter) plus a "Recent activity" panel on the property Overview, so the tab count does not grow (Requirement 16).
- **Property tabs collapse to a disclosure below 768px.** At and above 768px the existing wrapping row stays. Below 768px the tabs sit behind a "Property sections" disclosure button that shows the current section (Requirement 21).
- **Onboarding is inline, not a modal tour.** The setup guide extends the dashboard card, stays out of the way, and can be reopened from the account menu and the palette. State stays in `localStorage` per user, as `ChecklistCard` already does (Requirements 24 through 27).
- **Sample data is offered only to an empty account.** "Load sample data" replaces all data, so the onboarding prompts show it only while the user owns no property (Requirement 24).
- **Existing tests keep passing.** Existing accessible names, tab labels, the "x of 4 done" text and route paths stay as they are. New routes and controls are additive (Requirement 29), with one deliberate exception recorded next.
- **Sidebar links use the same navigation guard as the palette (deliberate behavior change).** Today the sidebar links leave a dirty Imports form without a prompt. After this work they route through the shared guard, so a dirty form shows "Discard changes?" first. This changes existing behavior, so it has its own requirement (Requirement 30), a test, and a `CHANGELOG.md` note.
- **Search matches text fields only.** The Search_Service matches property names and addresses, transaction and itemized-entry descriptions, itemized-entry notes, asset and loan descriptions, and business names and addresses. It never matches amounts, dates, or category labels (Requirement 9.10). Adding amount matching is a possible later extension.
- **History is purged by "Clear all data" and by restore from backup.** A restore leaves exactly one event ("Restored from backup"). History is not part of backups (Requirements 18.5 and 18.6).
- **Retention is defined once.** The 24-month retention (730 days) is the single constant `retention_days` in `activity_config.py`, and every use reads it (Requirement 18.12).
- **Toast Undo stays client-side.** Undo through the toast keeps calling the normal create API and does not use the restore route. The history shows it as an ordinary `create` event next to the original `delete` event, and does not link the two (Requirement 17.14).
- **The shared `parseYearParam` and `?year=` support are conditional and non-conflicting.** Whichever of the `year-end-checklist` spec and this spec lands first adds `parseYearParam` to `lib/taxYears.ts` and the `?year=` initializers on the per-property Transactions and Reports pages. The other reuses them. Each spec's task reads: add if absent, reuse if present. The Combined Reports initializer follows the same rule.
- **The seven-tab disclosure breakpoint stays `md`.** The Playwright check at 768px stays. If the seven-tab wrapping row needs more than two rows at 768px, the breakpoint moves from `md` to `lg` (a one-class change in `PropertySectionTabs`), as documented in Requirement 21.13.

## Glossary

- **Logstead_UI**: The React single-page frontend.
- **Logstead_API**: The Python Lambda backend reached through `router/handler.py`.
- **Command_Palette**: The modal dialog opened with Cmd/Ctrl+K that lists destinations, actions and search results in one filterable list.
- **Palette_Item**: One selectable row of the Command_Palette: a Destination, an Action, or a Search_Hit.
- **Destination**: A Palette_Item that navigates to a page, a property, or a tax year.
- **Action**: A Palette_Item that starts a task (for example "Add transaction") or changes a setting (for example "Switch theme").
- **Shortcut_Engine**: The Logstead_UI module that listens for key presses on the document, decides whether a press is eligible, and runs the matching shortcut.
- **Shortcut**: A registered key or key sequence with an id, a label, a group and a handler.
- **Chord**: A key press with a modifier, such as Cmd+K (macOS) or Ctrl+K (other platforms).
- **Sequence**: Two plain key presses in a row within the Sequence_Timeout, such as `g` then `d`.
- **Sequence_Timeout**: The configured time, 1000 ms, after which a pending Sequence is discarded.
- **Editable_Target**: An element that accepts typed text: `input` (except button-like types), `textarea`, `select`, or an element with `contenteditable`.
- **Blocking_Dialog**: Any open element with role `dialog` or `alertdialog` other than the Command_Palette and the Shortcuts_Help, including the `RecordModal`, the `ConfirmDialog`, the discard-changes confirmation and the mobile navigation drawer.
- **Shortcuts_Help**: The dialog that lists every registered Shortcut by group.
- **Search_Service**: The backend service that answers `GET /search`.
- **Search_Query**: The user's text after trimming and Unicode NFKC normalization, case-folded.
- **Search_Token**: One whitespace-separated part of a Search_Query.
- **Search_Hit**: One matching record, with a kind, an id, a title, a subtitle, the matched field, and a Link.
- **Search_Group**: The Search_Hits of one kind (`property`, `transaction`, `itemized_entry`, `asset`, `loan`, `business`).
- **Scan_Cap**: The configured maximum number of stored items one search request may read: 20,000.
- **Link**: An app-relative path starting with a single `/`, built by the Logstead_API from validated ids.
- **Activity_Event**: One stored history entry: `id`, `at`, `action`, `entity`, `record_id`, `property_id`, `property_name`, `summary`, `before`, `after`, `restorable`, and the restore marker.
- **Action_Kind**: One of `create`, `update`, `delete`, `restore`, `import`.
- **Entity_Kind**: One of `transaction`, `itemized_entry`, `asset`, `loan`, `property`, `backup`, `schedule_e`.
- **Activity_Recorder**: The backend collaborator that builds and writes Activity_Events after a successful change.
- **Activity_Service**: The backend service that lists Activity_Events and restores a restorable one.
- **Change_Summary**: A one-line plain-language description of an event, for example `Deleted transaction "Water bill" (125.00, 2024-03-07)`.
- **Field_Diff**: The `before` and `after` maps of an event, limited to the allow-listed fields of the Entity_Kind that changed.
- **Retention_Window**: The configured lifetime of an Activity_Event, 730 days.
- **Safe_Restore**: A restore of a deleted record that one create call fully performs, under the same rules as the toast Undo (`undoMappers.ts`).
- **Money_String**: A monetary value serialized as a fixed two-decimal string such as `"1250.00"`; never a float and never a DynamoDB `Number`.
- **Property_Tabs**: The per-property section navigation built from `PROPERTY_NAV`.
- **Narrow_Viewport**: A viewport narrower than 768 CSS pixels (the Tailwind `md` breakpoint).
- **Tablet_Viewport**: A viewport from 768 up to 1023 CSS pixels.
- **Setup_Guide**: The dashboard card and its steps that guide a first-time user (the extended `ChecklistCard`).
- **Setup_State**: The per-user browser-stored state of the Setup_Guide: dismissed, collapsed.
- **Empty_State**: The `StateBlock` shown when a list has no records.
- **Reduced_Motion**: The user setting `prefers-reduced-motion: reduce`.
- **Theme**: The light or dark color scheme driven by the semantic color tokens in `index.css`.

## Requirements

### Requirement 1: Open and close the command palette

**User Story:** As the property owner, I want to open a palette from anywhere with one chord, so that I can reach any page or record without hunting through menus.

#### Acceptance Criteria

1. WHEN the user presses Cmd+K on macOS or Ctrl+K on other platforms and no Blocking_Dialog is open, THE Logstead_UI SHALL open the Command_Palette and move focus to its search field.
2. WHEN the user presses the same Chord while the Command_Palette is open, THE Logstead_UI SHALL close the Command_Palette.
3. WHEN the user presses Escape while the Command_Palette is open, THE Logstead_UI SHALL close the Command_Palette.
4. THE Logstead_UI SHALL show a "Search" button in the app header that opens the Command_Palette, so that touch users and users without a keyboard can open the palette.
5. WHEN the Command_Palette closes without a navigation, THE Logstead_UI SHALL return focus to the element that was focused before the palette opened, or to `#page-heading` when that element no longer exists.
6. WHEN the Command_Palette closes because the user chose a Destination, THE Logstead_UI SHALL leave focus placement to the route change so that focus lands on the new page heading.
7. WHEN the user presses the Chord while focus is inside an Editable_Target and no Blocking_Dialog is open, THE Logstead_UI SHALL open the Command_Palette and call `preventDefault` on the event.
8. IF a Blocking_Dialog is open, THEN THE Logstead_UI SHALL ignore the Chord, so that no navigation can bypass a discard-changes confirmation.

### Requirement 2: Palette destinations

**User Story:** As the property owner, I want the palette to list pages, properties and tax years, so that I can jump to them by typing a few letters.

#### Acceptance Criteria

1. THE Command_Palette SHALL list one Destination for each entry of `PRIMARY_NAV` and one for the Activity page.
2. THE Command_Palette SHALL list one Destination for each property in the shell property list, labeled with the property name, that opens the property Overview.
3. WHILE a property route is active, THE Command_Palette SHALL also list one Destination for each entry of `PROPERTY_NAV` for that property, labeled "{section} ({property name})".
4. THE Command_Palette SHALL list one Destination for each tax year in the portfolio year range, labeled "Tax year {year}", that opens `/reports?year={year}`.
5. WHEN the Combined Reports page opens with a valid `year` query parameter, THE Logstead_UI SHALL select that tax year.
6. IF the `year` query parameter is missing, not an integer, or outside 1900 through 2200, THEN THE Logstead_UI SHALL fall back to the latest completed tax year.
7. WHEN the shell property list has not loaded, THE Command_Palette SHALL list the page Destinations and show the property group as loading.
8. IF the shell property list failed to load, THEN THE Command_Palette SHALL list the page Destinations and show a short notice that properties could not be loaded.

### Requirement 3: Palette actions

**User Story:** As the property owner, I want to start common tasks from the palette, so that adding a record takes a few keystrokes.

#### Acceptance Criteria

1. THE Command_Palette SHALL list these Actions: "Add property", "Add transaction", "Add repair", "Add depreciable asset", "Add loan", "Import Schedule E", "Switch theme", "Keyboard shortcuts", "Show setup guide", and "Download backup".
2. WHEN the user chooses "Add transaction", "Add repair", "Add depreciable asset" or "Add loan" and a property route is active, THE Logstead_UI SHALL navigate to that property's matching page with the query parameter `new=1`.
3. WHEN the user chooses one of those four Actions and no property route is active and the user owns exactly one property, THE Logstead_UI SHALL use that property.
4. WHEN the user chooses one of those four Actions and no property route is active and the user owns more than one property, THE Command_Palette SHALL show a property picker as a second step, and Escape or Backspace on an empty field SHALL return to the first step.
5. IF the user owns no property, THEN THE Command_Palette SHALL show the four property-scoped Actions as unavailable with the reason "Add a property first" and SHALL NOT navigate when one is chosen.
6. WHEN a transactions, repairs, assets or loans page loads with `new=1`, THE Logstead_UI SHALL open the add dialog once and SHALL remove the `new` parameter from the URL by replacing the history entry.
7. WHEN the user chooses "Switch theme", THE Logstead_UI SHALL toggle the Theme and keep the palette closed.
8. WHEN the user chooses "Download backup", THE Logstead_UI SHALL navigate to the Profile page with the query parameter `focus=backup`, and the Profile page SHALL move focus to the "Backup & restore" heading without starting a download.
9. THE Command_Palette SHALL NOT include "Clear all data", "Restore from file", "Load sample data" or any delete Action.

### Requirement 4: Palette keyboard interaction and semantics

**User Story:** As a keyboard or screen reader user, I want the palette to follow a standard pattern, so that I can use the palette without a mouse.

#### Acceptance Criteria

1. THE Command_Palette SHALL render as a Radix `Dialog` with an accessible name "Command palette", a visually hidden description, and a focus trap.
2. THE Command_Palette SHALL expose the search field as `role="combobox"` with `aria-expanded`, `aria-controls` the listbox, and `aria-activedescendant` the highlighted option.
3. THE Command_Palette SHALL render results as a `role="listbox"` of `role="option"` rows, grouped with `role="group"` and an `aria-labelledby` group label.
4. WHEN the user presses ArrowDown or ArrowUp, THE Command_Palette SHALL move the highlight to the next or previous option, wrapping at the ends, without moving DOM focus off the search field.
5. WHEN the user presses Home or End while the field is empty or the caret is at the start or end, THE Command_Palette SHALL highlight the first or last option.
6. WHEN the user presses Enter, THE Command_Palette SHALL run the highlighted Palette_Item.
7. WHEN the highlight changes, THE Command_Palette SHALL scroll the highlighted option into view.
8. WHEN the list changes, THE Command_Palette SHALL announce the number of results through a polite live region, for example "5 results" or "No results".
9. WHEN the search field has no text, THE Command_Palette SHALL list the page Destinations and Actions in a fixed order, and no search request SHALL be sent.
10. THE Command_Palette SHALL show each option's shortcut hint, when the item has one, as text readable by screen readers.
11. WHERE Reduced_Motion is set, THE Command_Palette SHALL open and close without a transition.
12. THE Command_Palette SHALL use only the semantic color tokens and shared focus ring, so that contrast holds in both Themes.

### Requirement 5: Palette filtering and ranking

**User Story:** As the property owner, I want typing to narrow the list sensibly, so that the item I want is near the top.

#### Acceptance Criteria

1. WHEN the user types text, THE Command_Palette SHALL keep only local Palette_Items whose label or keywords contain every Search_Token, compared after NFKC normalization and case folding.
2. THE Command_Palette SHALL rank a label that equals the Search_Query first, then a label whose word starts with a token, then a label that contains a token, and SHALL break ties by the fixed item order and then by label.
3. FOR ALL candidate lists and queries, THE Command_Palette SHALL return the same ordered result for the same inputs (deterministic ranking).
4. FOR ALL candidate lists and queries, every returned local item SHALL contain every Search_Token in its label or keywords.
5. THE Command_Palette SHALL show at most 8 local items and at most 5 items per Search_Group, and each group SHALL show a "See all results" link to the Search page when more hits exist.
6. WHEN no local item and no Search_Hit matches, THE Command_Palette SHALL show "No results" and a link to the Search page for the same query.

### Requirement 6: Keyboard shortcuts and the help dialog

**User Story:** As a keyboard user, I want a short, discoverable set of shortcuts, so that I can move around without the mouse.

#### Acceptance Criteria

1. THE Shortcut_Engine SHALL register these Shortcuts: Cmd/Ctrl+K "Open command palette", `/` "Search", `?` "Show keyboard shortcuts", `g` then `d` "Go to Dashboard", `g` then `p` "Go to Properties", `g` then `r` "Go to Reports", `g` then `c` "Go to Carryforward", `g` then `a` "Go to Activity", and `g` then `i` "Go to Import".
2. WHEN the user presses `/` or `?` and the press is eligible (Requirement 7), THE Shortcut_Engine SHALL open the Command_Palette or the Shortcuts_Help respectively and call `preventDefault`.
3. WHEN the user presses `g` and then a second registered key within the Sequence_Timeout and both presses are eligible, THE Shortcut_Engine SHALL navigate to the matching page.
4. WHEN the Sequence_Timeout elapses, or a key that is not registered for the pending Sequence is pressed, THE Shortcut_Engine SHALL discard the pending Sequence.
5. THE Shortcuts_Help SHALL list every registered Shortcut, grouped as "General" and "Go to", with its keys rendered in `kbd` elements and a visible label, and SHALL show Cmd on macOS and Ctrl elsewhere.
6. WHEN the user presses Escape or activates the Close button, THE Shortcuts_Help SHALL close and return focus to the opener.
7. THE Logstead_UI SHALL offer "Keyboard shortcuts" in the account menu and the palette, so the help dialog is reachable without knowing the `?` key.
8. THE Shortcut_Engine SHALL read its Shortcuts from one registry, and the registry SHALL have no two Shortcuts with the same key or Sequence.
9. WHERE the viewport is a Narrow_Viewport and the device has no hardware keyboard, THE Logstead_UI SHALL still offer the header Search button and the account-menu entry.

### Requirement 7: When shortcuts must not fire

**User Story:** As the property owner, I want shortcuts to stay out of the way while I type or confirm something, so that I never lose an edit or trigger a surprise.

#### Acceptance Criteria

1. WHILE the event target is an Editable_Target, THE Shortcut_Engine SHALL ignore every plain-key Shortcut and Sequence.
2. WHILE a Blocking_Dialog is open, THE Shortcut_Engine SHALL ignore every Shortcut and Sequence.
3. WHILE the key event has `isComposing` set or a `keyCode` of 229, THE Shortcut_Engine SHALL ignore the event.
4. WHILE the Alt, Ctrl or Meta modifier is held, THE Shortcut_Engine SHALL ignore plain-key Shortcuts, so that browser and assistive-technology shortcuts keep working.
5. WHEN `event.defaultPrevented` is already set, THE Shortcut_Engine SHALL ignore the event.
6. WHEN the key event is an auto-repeat, THE Shortcut_Engine SHALL ignore the event.
7. WHEN the event target is a button, link, `summary`, or an element with role `menuitem`, `tab`, `option` or `treeitem`, THE Shortcut_Engine SHALL ignore the Space and Enter keys, and no registered Shortcut SHALL use those keys.
8. WHILE a navigation guard is active (the Imports dirty context is dirty, or a form behind `useDiscardGuard` is dirty), THE Command_Palette SHALL send Destination navigation through the shared navigation guard so a confirm decides, and SHALL NOT change `window.location` directly. The sidebar links follow the same rule (Requirement 30).
9. THE Shortcut_Engine SHALL attach one `keydown` listener to `document` and remove the listener when the provider unmounts.
10. FOR ALL combinations of target kind, modifiers, composition state, dialog state and repeat flag, THE Shortcut_Engine SHALL treat a plain-key press as eligible only when the target is not an Editable_Target, no Blocking_Dialog is open, no Alt, Ctrl or Meta modifier is held, the event is not composing, not repeated and not already default-prevented.

### Requirement 8: Search route and scope

**User Story:** As the property owner, I want one search that covers my properties, records and businesses, so that I can find a record without remembering which page holds it.

#### Acceptance Criteria

1. THE Logstead_API SHALL expose `GET /search?q={text}` returning Search_Groups for the authenticated user only.
2. THE Search_Service SHALL search these fields: property name and address text; transaction description (rows that are not itemized entries); itemized entry description and notes; depreciable asset description; loan description; business legal name and business address.
3. THE Search_Service SHALL return Search_Groups in the fixed order `property`, `transaction`, `itemized_entry`, `asset`, `loan`, `business`, and SHALL omit no group, so a group with no hits has `total` `0` and an empty `hits` list.
4. THE Search_Service SHALL read data through the existing property, transaction, depreciation, loan and business services and SHALL add no stored item, key, index, or table.
5. THE Search_Service SHALL perform no repository write and no S3 call.
6. WHERE the query parameter `propertyId` is present, THE Search_Service SHALL restrict property-scoped groups to that property and SHALL return no `property` or `business` hits.
7. THE Search_Service SHALL give each Search_Hit a `kind`, `id`, `title`, `subtitle`, `matched_field`, `link`, and, for transactions, itemized entries and assets, the `amount` as a Money_String, and for transactions and itemized entries the `date`.
8. THE Search_Service SHALL return each Money_String exactly as stored, and SHALL perform no arithmetic on it.
9. THE Search_Service SHALL build every Link from validated ids: `/properties/{id}` for a property, `/properties/{id}/transactions?year={year}&focus={transactionId}` for a transaction, `/properties/{id}/repairs?year={year}&focus={entryId}` for an itemized entry, `/properties/{id}/assets?focus={assetId}`, `/properties/{id}/loans?focus={loanId}`, and `/businesses/{id}`.
10. WHEN a page opens with a `focus` query parameter that matches a row on the page, THE Logstead_UI SHALL scroll that row into view and move focus to the row's primary control or heading once.
11. IF the `focus` value matches no row, THEN THE Logstead_UI SHALL ignore the parameter without an error.

### Requirement 9: Matching and ranking

**User Story:** As the property owner, I want predictable matching, so that typing part of a word finds the record.

#### Acceptance Criteria

1. THE Search_Service SHALL form the Search_Query by trimming, NFKC-normalizing and case-folding the `q` value, and SHALL split the Search_Query on whitespace into at most 5 Search_Tokens.
2. THE Search_Service SHALL return a record as a Search_Hit only when each Search_Token occurs as a substring of the record's normalized searchable text.
3. IF the Search_Query is shorter than 2 characters or longer than 100 characters after trimming, THEN THE Logstead_API SHALL return `400` with `field` equal to `q`.
4. THE Search_Service SHALL rank a hit whose whole field equals the Search_Query first, then a hit whose word starts with every token, then any other hit, and SHALL break ties by most recent date, then by title, then by id.
5. THE Search_Service SHALL return at most `limit` hits per Search_Group, where `limit` defaults to 5, is at most 25, and is validated as an integer.
6. THE Search_Service SHALL report, for each Search_Group, the `total` number of matching records, which is independent of `limit`.
7. THE Search_Service SHALL return the same response for the same stored data and the same request (deterministic output).
8. FOR ALL Search_Queries, normalizing a normalized Search_Query SHALL produce the same Search_Query (idempotence).
9. THE Search_Service SHALL NOT interpret `q` as a pattern, so characters such as `*`, `%`, `\` and `.` match as plain text.
10. THE Search_Service SHALL build the searchable text of a record only from the text fields listed in Requirement 8.2, and SHALL NOT match a Search_Token against an amount, a date, or a category label.

### Requirement 10: Search authorization and errors

**User Story:** As the property owner, I want search to show only my data and to reveal nothing about anyone else's, so that my records stay private.

#### Acceptance Criteria

1. THE Search_Service SHALL include only records of properties the authenticated user owns and businesses the authenticated user owns.
2. WHERE the `propertyId` query parameter names a property that is missing or owned by another user, THE Logstead_API SHALL return a response byte-identical to the `Property not found.` 404 the property routes return for a missing id, and SHALL read no child record.
3. IF the `propertyId` value fails id validation, THEN THE Logstead_API SHALL return the same `400` the other property routes return for a malformed id.
4. IF a collaborator reports a failure such as a corrupt stored loan, THEN THE Logstead_API SHALL return that failure through the existing error model and SHALL NOT return a partial response.
5. THE Logstead_API SHALL accept `GET` only on `/search`.
6. THE Logstead_API SHALL NOT log the Search_Query text or any record text, and SHALL log only the user id hash used by the existing request log, the result counts and the scanned item count.

### Requirement 11: Search interface

**User Story:** As the property owner, I want grouped results with links, in the palette and on a page, so that I can open the record I found.

#### Acceptance Criteria

1. WHEN the Command_Palette field holds a Search_Query of at least 2 characters, THE Logstead_UI SHALL request `GET /search` after a 250 ms pause in typing and SHALL abort the previous request.
2. THE Command_Palette SHALL show Search_Hits under group labels "Properties", "Transactions", "Repairs", "Assets", "Loans" and "Businesses", after the local items.
3. WHILE a search request is in flight, THE Command_Palette SHALL keep the previous results visible and show a busy status through `aria-busy`, and SHALL show no layout jump.
4. IF a search request fails, THEN THE Command_Palette SHALL keep the local items and show "Search is unavailable. Try again." with a retry button.
5. WHEN the user chooses a Search_Hit, THE Logstead_UI SHALL navigate to its Link only when the Link starts with `/` and not `//`.
6. THE Logstead_UI SHALL provide a Search page at `/search?q={text}` that shows every group with its `total`, up to 25 hits per group, the property name for property-scoped hits, and the amount and date where present.
7. THE Search page SHALL have one `h1`, a search field labeled "Search", a results region announced through a polite live region, and the same Empty_State wording as the palette.
8. WHEN the Search page loads with a `q` parameter, THE Logstead_UI SHALL run that search and SHALL write the field value back to `q` with replace navigation as the user types.
9. THE Logstead_UI SHALL show hit titles as text only and SHALL highlight matched text with `mark` elements built from text nodes, and SHALL NOT insert record text as HTML.
10. WHEN a response has `truncated` set to `true`, THE Logstead_UI SHALL show the notice "Results may be incomplete because your data is large. Narrow your search."

### Requirement 12: Search data volume and cost

**User Story:** As the maintainer, I want search to stay cheap and bounded on a single-table design, so that a large account cannot slow the API or raise the bill.

#### Acceptance Criteria

1. THE Search_Service SHALL read stored items only through partition queries by property id or user id, and SHALL perform no table scan.
2. THE Search_Service SHALL stop reading once the number of stored items read reaches the Scan_Cap and SHALL set `truncated` to `true` in the response.
3. WHEN the Scan_Cap is not reached, THE Search_Service SHALL set `truncated` to `false`.
4. THE Search_Service SHALL read each property's transactions, assets and loans once per request.
5. THE Logstead_API SHALL return the number of stored items read as `scanned` in the response.
6. THE SAM template SHALL declare an explicit throttle for `GET /search` of 2 requests per second with a burst of 5.
7. THE Search_Service SHALL complete a request over 20,000 stored items without exceeding the Lambda timeout of 30 seconds.

### Requirement 13: Recording activity

**User Story:** As the property owner, I want a record of what changed, so that I can see what I or an import did to my data.

#### Acceptance Criteria

1. WHEN a transaction that is not an itemized entry is created, updated or deleted, THE Activity_Recorder SHALL write one Activity_Event with Entity_Kind `transaction` and the matching Action_Kind.
2. WHEN an itemized entry is created, updated or deleted, or an itemized total is set or removed, THE Activity_Recorder SHALL write one Activity_Event with Entity_Kind `itemized_entry` for an entry and Entity_Kind `transaction` for a total.
3. WHEN a depreciable asset is created, updated or deleted, THE Activity_Recorder SHALL write one Activity_Event with Entity_Kind `asset`.
4. WHEN a loan is created, updated or deleted, or a loan interest override is set or removed, THE Activity_Recorder SHALL write one Activity_Event with Entity_Kind `loan`.
5. WHEN a property is created, updated or deleted, THE Activity_Recorder SHALL write one Activity_Event with Entity_Kind `property`.
6. WHEN a Schedule E import for a property and year completes, THE Activity_Recorder SHALL write one Activity_Event with Action_Kind `import`, Entity_Kind `schedule_e`, and the counts of rows created and replaced.
7. WHEN an expense import session is confirmed, THE Activity_Recorder SHALL write one Activity_Event with Action_Kind `import`, Entity_Kind `transaction`, and the count of transactions created.
8. WHEN a backup restore completes, THE Activity_Recorder SHALL write one Activity_Event with Action_Kind `import`, Entity_Kind `backup`, and the restore summary counts.
9. WHEN a restore from the history completes (Requirement 17), THE Activity_Recorder SHALL write one Activity_Event with Action_Kind `restore`.
10. WHEN an update changes no allow-listed field, THE Activity_Recorder SHALL write no Activity_Event.
11. THE Activity_Recorder SHALL write one event per operation, so a bulk operation produces exactly one event, regardless of the number of rows it touches.
12. THE Activity_Recorder SHALL write the event only after the change has succeeded, and a request that fails validation, authorization or the write SHALL produce no event.
13. THE Activity_Recorder SHALL NOT record reads, receipt uploads, receipt deletes, photo changes, usage-day changes, note changes, or backup downloads.

### Requirement 14: Event content

**User Story:** As the property owner, I want each event to say what happened in plain words and show the old and new values, so that I can understand a change without opening the record.

#### Acceptance Criteria

1. THE Activity_Recorder SHALL give each Activity_Event an `id`, an `at` UTC timestamp with millisecond precision, an Action_Kind, an Entity_Kind, the `record_id` (null for `backup`), the `property_id` (null for `backup`), the `property_name` at the time of the event, a Change_Summary of at most 200 characters, and `restorable`.
2. THE Activity_Recorder SHALL fill `before` for update and delete events and `after` for create, update and restore events, each limited to the allow-listed fields of the Entity_Kind.
3. THE Activity_Recorder SHALL allow these fields: for transactions and itemized entries `date`, `amount`, `type`, `category_id`, `description`, `notes`; for assets `description`, `cost_basis`, `placed_in_service_date`, `recovery_period_years`; for loans `description`, `annual_interest_rate`, `monthly_payment`, `anchor_balance`, `anchor_date`, `include_in_report`; for properties `name`, `address_text`, `property_type`, `business_id`.
4. FOR an update event, THE Activity_Recorder SHALL include in `before` and `after` only the allow-listed fields whose values differ.
5. THE Activity_Recorder SHALL store every money field in `before` and `after` as a Money_String equal to the stored value, with no rounding.
6. THE Activity_Recorder SHALL truncate each text value to 200 characters and mark the event `truncated` when a value was cut, and SHALL keep the serialized `before` and `after` at or below 2,048 bytes each.
7. THE Activity_Recorder SHALL NOT store receipt file names, S3 keys, presigned URLs, photo data, tokens, or the raw request body.
8. THE Activity_Recorder SHALL store `before` and `after` as JSON strings, so nested money strings stay out of the repository's top-level money serializer.
9. FOR ALL pairs of allow-listed field maps, applying the `after` map over the `before` map SHALL equal the allow-listed projection of the new record, and swapping the pair SHALL produce the inverse diff (round trip).
10. THE Activity_Service SHALL return events with `before` and `after` as objects, and money values as Money_Strings.

### Requirement 15: Activity routes

**User Story:** As the property owner, I want to read my activity globally and for one property, so that I can see recent changes in context.

#### Acceptance Criteria

1. THE Logstead_API SHALL expose `GET /activity` returning the authenticated user's events, newest first.
2. THE Logstead_API SHALL expose `GET /properties/{propertyId}/activity` returning that property's events, newest first, guarded by the existing property ownership check.
3. THE Logstead_API SHALL accept the query parameters `limit` (default 50, at most 100), `cursor`, `entity` and `action` on both routes, and `propertyId` on `GET /activity`.
4. THE Logstead_API SHALL return `events` and `next_cursor`, where `next_cursor` is `null` on the last page.
5. FOR ALL event sets and page sizes, following `next_cursor` from the first page to the last SHALL return every visible event exactly once, in order, with no duplicates (pagination completeness).
6. IF `cursor` is not a well-formed cursor value, THEN THE Logstead_API SHALL return `400` with `field` equal to `cursor`, and a well-formed cursor SHALL only ever position a read inside the authenticated user's own events.
7. IF `entity` or `action` is not a defined kind, or `limit` is not an integer from 1 through 100, THEN THE Logstead_API SHALL return `400` with the offending field name.
8. WHERE the `propertyId` of `GET /activity` names a missing property or a property owned by another user, THE Logstead_API SHALL return the byte-identical `Property not found.` 404.
9. THE Activity_Service SHALL exclude events whose `ttl` is at or before the current time, even when DynamoDB has not yet deleted them.
10. THE Activity_Service SHALL perform no write on a list request.
11. THE Logstead_API SHALL accept `GET` only on the two list routes.

### Requirement 16: Activity interface

**User Story:** As the property owner, I want a readable activity page and a short recent-activity panel, so that I can see what changed without leaving my work.

#### Acceptance Criteria

1. THE Logstead_UI SHALL provide an Activity page at `/activity` with one `h1`, a property filter, an entity filter, an action filter, and a list of events with "Load more".
2. THE Logstead_UI SHALL add "Activity" to the "Tools" group of `NAV_GROUPS` and SHALL NOT add a property tab.
3. THE Logstead_UI SHALL show each event with its local date and time (a `time` element with the UTC value in `dateTime`), the Action_Kind as a `Badge` with text, the Change_Summary, the property name, and an expandable "Details" region showing the before and after values as a `dl`.
4. THE Logstead_UI SHALL present money values with `formatMoney` and SHALL NOT parse them to floating point.
5. WHEN the user selects a property in the filter, THE Logstead_UI SHALL load `GET /properties/{propertyId}/activity` and write the selection to the `property` query parameter.
6. THE property Overview SHALL show a "Recent activity" panel with the latest 5 events of that property and a link to `/activity?property={id}`.
7. WHEN a property has no events, THE Logstead_UI SHALL show an Empty_State that explains events appear after the user adds or changes records and that history is kept for 24 months.
8. WHEN loading, THE Logstead_UI SHALL show a skeleton on first load and keep previous rows during a reload, and WHEN loading fails, THE Logstead_UI SHALL show an error `StateBlock` with a retry.
9. THE Logstead_UI SHALL announce "{n} events" through a polite live region after a filter change or a page load.
10. WHEN the event's record still exists and the event is not a delete, THE Logstead_UI SHALL link the Change_Summary to the record's page with the `focus` parameter.

### Requirement 17: Restore a deleted record from the history

**User Story:** As the property owner, I want to bring back a record I deleted, even after the Undo toast is gone, so that a mistaken delete is not permanent when that is safe.

#### Acceptance Criteria

1. THE Activity_Recorder SHALL set `restorable` to `true` on a delete event only for a transaction that is not imported, not itemized and has no receipt; an itemized entry that has no receipt; an asset; and a loan with no interest override.
2. THE Activity_Recorder SHALL set `restorable` to `false` on every other event, and SHALL store the full create payload of the deleted record only on an event with `restorable` set to `true`.
3. THE Logstead_API SHALL expose `POST /properties/{propertyId}/activity/{eventId}/restore`, guarded by the existing property ownership check.
4. WHEN the user requests a restore of a restorable delete event that has not been restored, THE Activity_Service SHALL re-create the record through the same service create path the toast Undo uses, mark the event as restored with the new record id and time, write one `restore` event, and return the new record id.
5. THE Activity_Service SHALL claim the event with a conditional write before creating the record, so that two simultaneous restore requests create exactly one record.
6. IF the event is not restorable, not a delete event, or already restored, THEN THE Activity_Service SHALL return `409` with a message naming the reason, and SHALL create no record.
7. IF the event does not exist for the property, or belongs to another user's property, THEN THE Logstead_API SHALL return the byte-identical `Property not found.` or `Activity event not found.` 404 the ownership check or lookup defines, and SHALL NOT reveal which case applies.
8. IF the re-create fails validation (for example the category no longer exists), THEN THE Activity_Service SHALL release the claim, create no record, and return the validation error.
9. THE Activity_Service SHALL give the restored record a new id and new timestamps, the same as the toast Undo.
10. THE Logstead_UI SHALL show a "Restore" button only on an event with `restorable` set to `true` that has not been restored, SHALL confirm with a `ConfirmDialog` that states the record will return with a new id, and SHALL show the result in a toast with a link to the restored record.
11. WHEN a restore completes, THE Logstead_UI SHALL mark the event "Restored" and disable the button.
12. FOR ALL records that are safe to restore, creating, deleting and restoring SHALL produce a record equal to the original in every allow-listed field, differing only in `id`, `created_at` and `updated_at` (restore round trip).
13. THE Logstead_UI SHALL NOT offer "Restore" or "Undo" for an update event.
14. THE toast Undo SHALL stay client-side and SHALL NOT call the restore route, so that an Undo re-creates the record through the normal create route and THE Activity_Recorder SHALL record it as an ordinary `create` event, separate from the original `delete` event and not linked to it.

### Requirement 18: Retention, deletion, backup and re-import

**User Story:** As the property owner, I want the history to expire, to follow "Clear all data", and to stay out of my backups, so that old text about my records does not linger and my backups stay the record of truth.

#### Acceptance Criteria

1. THE Activity_Recorder SHALL set the `ttl` attribute of each event to its `at` time plus the Retention_Window, in epoch seconds.
2. THE Activity_Recorder SHALL write events as a new item type with `PK=USER#<userId>` and `SK=ACT#<invertedMillis>#<eventId>`, and, for an event with a property, `GSI1PK=PROPERTY#<propertyId>` and `GSI1SK` equal to the `SK`.
3. THE Activity_Recorder SHALL NOT use any existing item type, key prefix, or attribute name for a different purpose, and the prefix `ACT#` SHALL NOT match the prefix of any existing listing query.
4. THE backup export SHALL exclude Activity_Events, and the backup `schema_version` SHALL stay `"1"`.
5. WHEN "Clear all data" completes, THE Logstead_API SHALL delete every Activity_Event of the user in the same request.
6. WHEN a backup restore completes, THE Logstead_API SHALL delete the user's earlier Activity_Events and write the single restore event of Requirement 13.8.
7. WHEN a property is deleted, THE Logstead_API SHALL delete that property's Activity_Events and write one `delete` event for the property.
8. WHEN a Schedule E re-import replaces imported rows, THE Activity_Recorder SHALL write one event whose Change_Summary states the number of imported rows replaced and created, and the replaced rows SHALL NOT produce individual delete events.
9. THE Activity_Service SHALL treat the history as best effort: a deleted `ttl`-expired event simply disappears and no code SHALL depend on an older event existing.
10. THE Activity_Recorder SHALL add at most one repository write (and its GSI1 write) per user operation.
11. THE data-model documentation SHALL state the storage cost basis: an event of at most 4 KB, and the retention of 730 days.
12. THE Logstead_API SHALL define the Retention_Window once, as the constant `retention_days` (730) in `activity_config.py`, and every computation of an event `ttl` and every document or test that states the retention SHALL read that constant.

### Requirement 19: Reports are unchanged by activity

**User Story:** As the property owner, I want my reports to depend only on my records, so that the history can never change a number on a tax form.

#### Acceptance Criteria

1. THE ReportingService, DashboardService, CarryforwardService, LoanService, DepreciationService and BackupService export SHALL NOT import or call the Activity_Recorder or the Activity_Service.
2. FOR ALL stored states, THE Schedule E report, the combined report, the dashboard summary, the carryforward reconciliation and the backup export SHALL be identical whether or not Activity_Events exist for the user.
3. THE Activity_Recorder SHALL write no attribute on a transaction, asset, loan or property item.
4. FOR ALL operations, the stored records after the operation SHALL be identical whether or not the Activity_Recorder is enabled.
5. THE Activity_Recorder SHALL receive the user id and the clock from its constructor, and no service SHALL read an Activity_Event to decide a result.

### Requirement 20: Failure isolation of recording

**User Story:** As the property owner, I want my edits to save even if the history cannot be written, so that a logging fault never blocks my work.

#### Acceptance Criteria

1. IF writing an Activity_Event fails, THEN THE Activity_Recorder SHALL log a structured warning with the Entity_Kind, Action_Kind and error class and SHALL return normally.
2. THE Logstead_API SHALL return the same status and body for a mutation whether or not the Activity_Recorder write succeeded.
3. THE Logstead_API SHALL attach the Activity_Recorder at the router layer, around the mutation handlers, and no domain service (transaction, itemized, depreciation, loan, property, import, backup) SHALL take the Activity_Recorder as a parameter, so existing service callers and tests are unaffected.
4. THE Activity_Recorder SHALL complete its write within the same request and SHALL NOT start a background thread or a second invocation.

### Requirement 21: Property tabs on narrow viewports

**User Story:** As a phone user, I want the property sections to fit my screen, so that I can switch sections without a cluttered tab block.

#### Acceptance Criteria

1. WHILE the viewport is a Narrow_Viewport, THE Property_Tabs SHALL show one button labeled "Property sections: {current section}" with `aria-expanded` and `aria-controls`, and SHALL hide the list of links until the button is activated.
2. WHEN the user activates the button, THE Property_Tabs SHALL show the list of all `PROPERTY_NAV` links, each at least 44 CSS pixels tall, with the current link marked `aria-current="page"`.
3. WHEN the user chooses a link, THE Property_Tabs SHALL close the list and leave focus placement to the route change.
4. WHEN the user presses Escape while the list is open, THE Property_Tabs SHALL close the list and return focus to the button.
5. WHEN focus leaves the open list through Tab, THE Property_Tabs SHALL close the list.
6. WHILE the viewport is at least 768 CSS pixels wide, THE Property_Tabs SHALL show the list of links as a wrapping row and SHALL hide the button.
7. THE Property_Tabs SHALL render one `nav` landmark labeled "Property sections" and one `ul` of links at every width, so existing role queries find exactly one landmark.
8. THE Property_Tabs SHALL derive the button label from the current path, so that a section added to `PROPERTY_NAV` appears in the list and in the label with no further change.
9. FOR ALL entries of `PROPERTY_NAV` and all property ids, resolving the current section from `propertyPath(id, segment)` SHALL return that entry (round trip).
10. THE Property_Tabs SHALL NOT scroll horizontally, so content stays reflowable at 320 CSS pixels.
11. WHERE the viewport is a Tablet_Viewport, THE Property_Tabs SHALL fit within two rows with the seven-tab set, verified at 768 and 1023 pixels.
12. THE Property_Tabs SHALL use only the existing tab styles and semantic tokens, and SHALL show no transition under Reduced_Motion.
13. THE Property_Tabs SHALL switch between the disclosure and the wrapping row at the Tailwind `md` breakpoint, and IF the Playwright check at 768 pixels shows the seven-tab wrapping row on more than two rows, THEN the implementation SHALL move the breakpoint from `md` to `lg` by changing the responsive classes in `PropertySectionTabs`, SHALL update the Narrow_Viewport definition in this document and the tests that rely on it, and SHALL record the change in `docs/developer-guide.md`.

### Requirement 22: Tables and forms on small screens

**User Story:** As a phone or tablet user, I want pages, tables and forms to fit without sideways scrolling, so that I can enter and review data on the go.

#### Acceptance Criteria

1. THE Logstead_UI SHALL render each page with no horizontal page scroll at widths of 320, 375, 768 and 1024 CSS pixels.
2. WHILE the viewport is a Narrow_Viewport, THE Logstead_UI SHALL render every `ResponsiveTable` as stacked rows, and a table with a sticky header SHALL keep its scroll area inside the table container only.
3. THE `RecordModal` SHALL fit within the visual viewport height, scroll its body internally, keep its title and its Save and Cancel buttons reachable without scrolling the page, and stay within the width of the viewport at 320 CSS pixels.
4. WHILE the viewport is a Narrow_Viewport, THE form layouts of the transaction, itemized entry, asset, loan, property and import forms SHALL use a single column, with labels above fields and controls at least 44 CSS pixels tall.
5. THE Logstead_UI SHALL give each icon-only button a target of at least 44 by 44 CSS pixels on a Narrow_Viewport, and the existing `touchTargets` test SHALL cover each new control.
6. WHEN a text field receives focus on a Narrow_Viewport, THE Logstead_UI SHALL use a computed font size of at least 16 CSS pixels so that mobile browsers do not zoom the page.
7. THE dashboard tiles, the year selector group, the report page toolbar and the property Overview tiles SHALL wrap into rows without clipping at 320 CSS pixels.
8. THE Command_Palette SHALL be usable at 320 CSS pixels: a width of the viewport minus 1 rem on each side, a list that scrolls inside the dialog, and a visible Close button.
9. WHEN the on-screen keyboard reduces the visual viewport, THE focused field SHALL remain visible, and the `RecordModal` and the Command_Palette SHALL size to the dynamic viewport (`dvh`).
10. THE Logstead_UI SHALL print the Schedule E report layouts exactly as before, and the responsive classes SHALL NOT change print output.

### Requirement 23: Viewport test coverage

**User Story:** As the maintainer, I want automated checks at phone and tablet sizes, so that layout regressions are caught.

#### Acceptance Criteria

1. THE Playwright suite SHALL run, at 320x640, 375x800, 768x1024 and 1024x768, a check that each primary route has no horizontal page scroll and no axe violation in both Themes.
2. THE Playwright suite SHALL check at 375 and 768 pixels that the Property_Tabs follow Requirement 21, including opening the list with the keyboard, choosing a section, Escape, and `aria-current`.
3. THE Playwright suite SHALL check at 320 pixels that the add-transaction `RecordModal` keeps its Save button inside the viewport.
4. THE Playwright suite SHALL check that the Command_Palette opens with Cmd/Ctrl+K, filters, navigates with the keyboard, and returns focus, and that the shortcuts do not fire while typing in a field or while a `RecordModal` is open.
5. THE vitest suite SHALL cover the shortcut eligibility function, the palette ranking function and the tab section resolver with fast-check properties of at least 100 runs each.
6. THE e2e fixtures SHALL stub `GET /search` and `GET /activity` so no real endpoint is called.

### Requirement 24: Setup guide

**User Story:** As a first-time user, I want a short guide that tells me what to do next, so that I reach my first Schedule E report without reading documentation.

#### Acceptance Criteria

1. THE Setup_Guide SHALL keep the existing four steps (add a property, record a transaction, add a loan or an asset, view a Schedule E report), the existing labels, and the "{n} of 4 done" progress text.
2. THE Setup_Guide SHALL mark the first incomplete step as "Next" with a visible text label and a one-sentence reason why the step matters, and SHALL NOT use color alone to show the next step.
3. WHEN the user owns no property, THE Setup_Guide SHALL show a secondary action "Explore with sample data" that links to the Profile page with `focus=backup`, and SHALL state that sample data replaces all current data.
4. WHEN the user owns at least one property, THE Setup_Guide SHALL NOT show the sample data action.
5. WHEN a step becomes complete, THE Setup_Guide SHALL announce "{step label} done. {n} of 4 done." through a polite live region.
6. WHEN all four steps are complete, THE Setup_Guide SHALL show "You're set up" with a "Dismiss" button instead of the steps, and SHALL stop showing after dismissal.
7. WHEN the dashboard data failed to load, THE Setup_Guide SHALL render nothing, as it does today.
8. THE Setup_Guide SHALL derive step completion from loaded data and the existing visited-report flag, so progress resumes without stored step state.
9. THE Setup_Guide SHALL add no network request beyond the loan and asset probe it already makes.

### Requirement 25: Empty-state guidance

**User Story:** As a first-time user, I want an empty page to explain itself and offer the next action, so that I am never left on a blank list.

#### Acceptance Criteria

1. WHEN a property has no transactions, repairs, depreciable assets or loans, THE Logstead_UI SHALL show an Empty_State on the matching page with a title, one sentence on what the page is for and how the data reaches Schedule E, and a primary button that opens the add dialog.
2. WHEN the Properties page has no property, THE Empty_State SHALL offer "Add property" and, WHERE the user owns no property, the "Explore with sample data" link.
3. WHEN the Reports pages have no data for the selected year, THE Empty_State SHALL link to the Transactions page and the Import page.
4. THE Empty_State of each page SHALL use the existing `StateBlock` with `kind="empty"` and SHALL be a landmark-free region inside `main`.
5. WHILE a page is loading or failed to load, THE Logstead_UI SHALL NOT show the empty guidance.
6. THE Empty_State copy SHALL avoid tax advice, and SHALL state what the app records without saying what the user should report.

### Requirement 26: Dismiss and resume

**User Story:** As a user, I want to dismiss the guide and bring it back, so that it does not nag me and does not vanish for good.

#### Acceptance Criteria

1. WHEN the user activates "Dismiss setup guide", THE Setup_Guide SHALL store the dismissal under the existing per-user key and hide.
2. WHEN the user activates "Collapse", THE Setup_Guide SHALL hide the steps, keep the heading, progress text and an "Expand" button, and store the collapsed state per user.
3. WHEN the user chooses "Show setup guide" in the account menu or the palette, THE Logstead_UI SHALL clear the stored dismissal and collapsed state, navigate to the Dashboard, and move focus to the Setup_Guide heading once it renders.
4. WHERE all four steps are complete, THE account menu and the palette SHALL still list "Show setup guide", and choosing it SHALL show the "You're set up" state.
5. THE Setup_State storage SHALL be keyed by the user id, and SHALL fall back to defaults when the stored value is missing, unreadable, or not valid JSON.
6. WHERE `localStorage` is unavailable, THE Setup_Guide SHALL work for the current page view and SHALL show no error.
7. FOR ALL stored Setup_State values, reading a written value SHALL return the same state (round trip), and reading any other string SHALL return the defaults.
8. THE Setup_State SHALL contain no personal data other than the user id in the key name.

### Requirement 27: Onboarding accessibility

**User Story:** As a keyboard or screen reader user, I want the guide to be operable and understandable, so that onboarding does not exclude me.

#### Acceptance Criteria

1. THE Setup_Guide SHALL render as a `section` labeled by its `h2`, with the steps as an ordered list.
2. THE Setup_Guide controls SHALL be native buttons and links with visible text or an `aria-label`, reachable in reading order, and each at least 44 CSS pixels on a Narrow_Viewport.
3. THE Setup_Guide SHALL NOT open a modal, trap focus, auto-focus on page load, or move focus without a user action.
4. THE collapse button SHALL expose `aria-expanded` and `aria-controls` the steps region.
5. THE Setup_Guide and Empty_State components SHALL pass axe in both Themes and SHALL use only semantic color tokens.
6. WHERE Reduced_Motion is set, THE Setup_Guide SHALL show no animation when collapsing, expanding or completing a step.

### Requirement 28: Accessibility, themes and dependencies

**User Story:** As the maintainer, I want every new surface to meet the existing accessibility and dependency standards, so that this release adds no regressions.

#### Acceptance Criteria

1. THE Logstead_UI SHALL build every new surface from the shared primitives in `components/ui` and the semantic color tokens, with no raw palette utility and no hex color, as enforced by the existing lint rules.
2. THE new Pages and dialogs SHALL pass axe with the tags `wcag2a`, `wcag2aa` and `wcag21aa` in both Themes, through `axeRoutes.test.tsx` and `e2e/a11y.spec.ts`.
3. THE new Pages SHALL have one `h1`, set the document title, and satisfy `pageConformance.test.ts`.
4. THE new interactive controls SHALL have a visible focus indicator that uses the shared focus ring.
5. THE new text and background pairs SHALL meet 4.5:1 contrast for text and 3:1 for non-text, and the existing token contrast test SHALL cover any new token.
6. THE Logstead_UI SHALL add no runtime npm dependency and SHALL add no test dependency that is not already in `package.json`; any later addition SHALL be justified against `docs/dependency-policy.md`.
7. THE Logstead_API SHALL add no Python dependency.
8. THE Logstead_UI SHALL load no external script, style, font or image, and SHALL use no inline script or `eval`, so the existing Content-Security-Policy stays valid.
9. THE Logstead_UI SHALL insert no record text as HTML (`dangerouslySetInnerHTML` stays banned by lint).
10. THE new motion SHALL use the existing motion tokens and respect Reduced_Motion.

### Requirement 29: No regressions and documentation

**User Story:** As the maintainer, I want the release to be additive and documented, so that existing tests and flows keep working.

#### Acceptance Criteria

1. THE Logstead_UI SHALL keep every existing route path, accessible name, tab label and test id used by the existing tests, and SHALL add routes `/search` and `/activity` only.
2. THE Logstead_API SHALL change no existing route path, method, request shape or response shape, and SHALL add `GET /search`, `GET /activity`, `GET /properties/{propertyId}/activity` and `POST /properties/{propertyId}/activity/{eventId}/restore` only.
3. THE existing frontend and backend test suites SHALL pass unchanged except for tests that list `NAV_GROUPS` items or the app header contents, which SHALL be updated for the added entries, and `MainNav` tests, which SHALL be extended for the guarded sidebar links of Requirement 30.
4. THE documentation SHALL be updated: `docs/api.md` (the four routes), `docs/data-model.md` (the activity item type, key, retention, backup interplay), `docs/developer-guide.md` (shortcuts registry, palette items, search, recording an event from a service, tab pattern, onboarding state), `docs/testing.md` (new suites and viewport checks), `CHANGELOG.md`, `README.md`, and `docs/future-improvements.md` (the "Property tabs on mobile" item removed).
5. THE `docs/developer-guide.md` "Undo and record IDs" section SHALL mention the history restore and its new-id behavior, and that the toast Undo stays client-side and appears in the history as an ordinary create.
6. THE implementation SHALL add or extend an accessibility and end-to-end task that covers the new routes, the palette, the shortcuts help, the responsive tabs and the setup guide.

### Requirement 30: Sidebar links use the navigation guard

**User Story:** As the property owner, I want the sidebar links to ask before they discard an unsaved import form, so that every way of leaving the page protects my edits.

#### Acceptance Criteria

1. WHILE a navigation guard is active, WHEN the user activates a sidebar link in the primary navigation or in the mobile drawer, THE Logstead_UI SHALL show the "Discard changes?" confirm of the shared navigation guard and SHALL navigate only after the user confirms.
2. WHEN the user chooses "Keep editing" in that confirm, THE Logstead_UI SHALL stay on the current route and SHALL keep the form content unchanged.
3. WHILE no navigation guard is active, WHEN the user activates a sidebar link, THE Logstead_UI SHALL navigate directly with no confirm.
4. THE Logstead_UI SHALL keep every sidebar link a real anchor with its `href`, `aria-current` marking, keyboard activation, and accessible name unchanged.
5. WHEN the user activates a sidebar link with a modifier key or a non-primary mouse button, THE Logstead_UI SHALL leave the browser default behavior in place and SHALL show no confirm.
6. WHEN a sidebar link is activated in the mobile drawer and the guard confirm is shown, THE Logstead_UI SHALL close the drawer only after navigation proceeds.
7. THE `CHANGELOG.md` file SHALL record this as a deliberate behavior change: before this release a sidebar link left a dirty Imports form with no prompt.
8. THE test suite SHALL include a `MainNav` test covering a dirty guard (confirm shown, Keep editing stays, Discard navigates), a clean guard (direct navigation), and the modifier-click case, and a browser test that a dirty Imports form shows the confirm on a sidebar click.
