# Requirements Document

## Introduction

This feature improves the look, feel, and usability of the whole Logstead frontend (React + Vite + Tailwind, Radix primitives, light and dark themes). It is delivered in three shippable phases. Each phase can be merged and released on its own, and each later phase builds on the earlier ones.

- **Phase 1 - Foundations**: type scale and spacing conventions, motion tokens, Button variants, PageHeader, document title and route-change focus and announcement, FormField, StateBlock error variant, and skeleton placeholders.
- **Phase 2 - Forms and states**: move the remaining hand-rolled dialogs onto RecordModal, dirty-state protection, form error summary, money and date inputs, first-load-only loading, consistent load-error presentation, undo for safe deletes, and toast improvements.
- **Phase 3 - Shell, tables, dashboard**: Logstead branding, grouped navigation, property switcher, upgraded tables, Transactions search and filters, progressive Dashboard with a first-run checklist, and an accessibility sweep.

This feature builds on the prior `modal-forms-and-tabbed-imports` feature (RecordModal, useRecordModal, useDismissibleErrors, and the tabbed Imports section). All color work goes through the existing semantic CSS-variable tokens in `frontend/src/index.css` and `frontend/tailwind.config.js`. No backend API changes are in scope.

### Prerequisites and Decisions

These items were open at the first review and are now resolved. None of them blocks any phase.

1. **Logo asset: satisfied.** The user saved the logo at `logo.svg` in the repository root. It is a 540 by 160 SVG. The design document decides where the file moves to (`frontend/src/assets/` and `frontend/public/`), how the square icon version is produced, and whether the text is converted to outlines. Requirement 16 (fallback) now applies only if the asset fails to load or is removed.
2. **Tagline: confirmed as "Schedule E simplified".** The artwork renders it in uppercase as "SCHEDULE E SIMPLIFIED". The tagline may be rendered where the design document designates, and may be hidden on narrow viewports and in the mobile header to save space. The tagline MUST NOT be claimed as shown anywhere the design document does not place it.
3. **Accent color: teal is chosen.** The default accent is teal, with `#0F766E` in the light theme as the base candidate. The design document picks the exact light and dark values and verifies WCAG_AA contrast numerically. Orange stays as a secondary brand color for decorative and illustrative elements and chart series only, and is never used for body text. Requirement 17 keeps its contrast test.
4. **Undo scope: approved.** Safe_Delete applies only where the full record can be re-created from client-retained data through existing APIs. Deletes with attached files or dependent child records keep the ConfirmDialog flow (Requirement 13).
5. **First-run checklist step 4: client-side flag.** The "Review Schedule E report" step uses a local visited flag in local storage, keyed per user when a user id is available on the client, with no backend change (Requirement 24).

### Logo Description (Brand Input)

The supplied logo (`logo.svg`, viewBox 540 by 160) has these parts:

- A house outline with a chimney, stroked with an amber-to-orange gradient (`#F59E0B` to `#EA580C`).
- Three ascending rounded bars inside the house: short orange (`#F97316` to `#EA580C`), medium amber (`#FBBF24` to `#D97706`), and tall teal (`#34D399` to `#0F766E`).
- The wordmark "logstead" as text with `fill="currentColor"`, system UI font, weight 700.
- The tagline "SCHEDULE E SIMPLIFIED" as text in `#0F766E`, weight 600, letter-spaced.

Because the wordmark uses `currentColor`, it follows the surrounding text color in both themes. The tagline color is fixed in the artwork and needs a lighter treatment in the dark theme.

Amber and gold MUST NOT be used for body-size text.

### Out of Scope

- A command palette and keyboard shortcuts.
- Migrating the dense Schedule E report tables to the shared table (they stay as they are).
- Migrating the chart data tables (they stay as they are).
- Any change to backend APIs.

## Glossary

- **Frontend**: The React + Vite + Tailwind single-page application in `frontend/`.
- **Semantic_Token**: A color defined as a CSS variable in `frontend/src/index.css` and exposed in `frontend/tailwind.config.js` (for example canvas, surface, fg, fg-muted, fg-subtle, accent, danger).
- **Type_Scale**: The defined set of font sizes, weights, and line heights used for headings, body, and captions.
- **Spacing_Convention**: The defined set of spacing values used for page padding, section gaps, and card padding.
- **Motion_Token**: A named duration or easing value used for transitions and animations.
- **Reduced_Motion_Rule**: A global CSS rule that disables or shortens animations and transitions when the user has `prefers-reduced-motion: reduce`.
- **Animate_Plugin**: The `tailwindcss-animate` Tailwind plugin that provides the `animate-in`, `animate-out`, and related utilities.
- **Button**: The shared button component in `frontend/src/components/ui/Button.tsx`.
- **PageHeader**: A new shared component that renders a page title (h1), optional description, optional actions, and optional breadcrumb.
- **Breadcrumb**: The existing component in `frontend/src/components/ui/Breadcrumb.tsx`.
- **Route_Announcer**: A visually hidden live region that announces the new page title after a route change.
- **useDocumentTitle**: A new hook that sets `document.title` for the current page.
- **FormField**: A new shared component that renders a label, optional hint, required marker, the control, and an error message, with correct ARIA wiring.
- **Error_Summary**: A block at the top of a form that lists all current validation errors and links each to its field.
- **StateBlock**: The existing component in `frontend/src/components/ui/StateBlock.tsx` for loading, empty, and error states.
- **Skeleton**: A placeholder shape shown in place of content while data loads.
- **RecordModal**: The existing modal form shell in `frontend/src/components/ui/RecordModal.tsx`.
- **useRecordModal**: The existing hook in `frontend/src/components/ui/useRecordModal.ts` that manages modal open, close, and editing state.
- **useDismissibleErrors**: The existing hook from the prior feature that manages dismissible error messages.
- **Legacy_Dialog**: A hand-rolled dialog that does not use RecordModal: the Transactions page dialog in `TransactionsPage.tsx`, AddPropertyDialog, EditPropertyDialog, AddBusinessDialog, and EditBusinessDialog.
- **Address_Autocomplete**: The address suggestion and RentCast enrichment behavior inside AddPropertyDialog.
- **Dirty_State**: The condition where a form has user edits that differ from its initial values and have not been saved.
- **Discard_Confirmation**: A ConfirmDialog titled "Discard changes?" shown before unsaved edits are thrown away.
- **ConfirmDialog**: The existing component in `frontend/src/components/ui/ConfirmDialog.tsx`.
- **Money_Input**: A new input for currency amounts with a currency prefix and a decimal input mode.
- **Date_Input**: A date input with a quick "Today" action.
- **First_Load_Loading**: A loading pattern where the loading indicator is shown only before data has loaded once; later refreshes keep the existing content mounted.
- **Load_Error_Alert**: The single shared presentation for a page-level load failure, including a Retry action.
- **Undo_Toast**: A toast offering an Undo action for a short time after a delete.
- **Toast**: A notification rendered by `frontend/src/components/ui/toast/ToastProvider.tsx`.
- **Safe_Delete**: A delete that can be fully reversed by re-creating the record from retained data, as designated in Requirement 13.
- **App_Shell**: The persistent layout around pages: header, primary navigation, mobile drawer, and profile menu (AppLayout.tsx, MainNav.tsx).
- **Primary_Nav**: The top-level navigation defined in `navConfig.ts`.
- **Nav_Group**: A labeled group of Primary_Nav items: Portfolio, Tax, or Tools.
- **Property_Switcher**: A header control for changing the current property.
- **Current_Section**: The property sub-section currently shown (for example Loans), from `PROPERTY_NAV` in `navConfig.ts`.
- **ResponsiveTable**: The existing shared table in `frontend/src/components/ui/ResponsiveTable.tsx`.
- **Sort_State**: The pair of sorted column key and direction (ascending, descending, or none) for a table.
- **Dense_Report_Table**: A Schedule E report table or chart data table that is explicitly excluded from migration.
- **Checklist_Card**: A Dashboard card listing first-run setup steps with completion state derived from existing data.
- **Brand_Assets**: The logo SVG, the square icon-only SVG, and the PNG icon fallbacks, saved into `frontend/public/` and `frontend/src/assets/`. They are present.
- **Wordmark_Fallback**: A plain text rendering of "logstead" in the `fg` token color, used only if the logo asset fails to load or is removed.
- **Monogram_Favicon**: A generated favicon showing the letter "L", used only if the icon assets fail to load or are removed.
- **Accent_Token**: The Semantic_Token `accent` and its related tokens (`accent-hover`, `accent-fg`, `accent-subtle`).
- **WCAG_AA**: WCAG 2.x Level AA contrast: at least 4.5:1 for body-size text and 3:1 for large text and UI component boundaries.
- **Touch_Target**: An interactive element's hit area.
- **Axe_Suite**: The automated vitest-axe test that renders every route in both light and dark themes and asserts no violations.
- **Route_Table**: The list of all routes defined in `App.tsx` that the Axe_Suite iterates over.

## Requirements

## Phase 1 - Foundations

### Requirement 1: Type Scale and Spacing Conventions

**User Story:** As a user, I want text sizes and spacing to be consistent on every page, so that the app feels coherent and is easy to scan.

#### Acceptance Criteria

1. THE Frontend SHALL define a Type_Scale with named levels for page title, section title, card title, body, small, and caption, each with a fixed font size, weight, and line height.
2. THE Frontend SHALL define a Spacing_Convention with fixed values for page padding, vertical gap between page sections, and card padding.
3. THE Frontend SHALL expose the Type_Scale and Spacing_Convention as Tailwind theme entries or shared class helpers so that components reference names rather than literal sizes.
4. WHEN a page renders its title, THE Frontend SHALL use the page title level of the Type_Scale.
5. THE Frontend SHALL document the Type_Scale and Spacing_Convention in a short comment block next to their definition.

### Requirement 2: Motion Tokens and Reduced Motion

**User Story:** As a user who is sensitive to motion, I want animations to be disabled or minimized when I ask my system for reduced motion, so that the app is comfortable to use.

#### Acceptance Criteria

1. THE Frontend SHALL define Motion_Tokens for at least a fast, a base, and a slow duration, and one standard easing curve.
2. THE Frontend SHALL apply a Reduced_Motion_Rule that, WHILE `prefers-reduced-motion: reduce` is set, limits animation and transition durations to no more than 1 millisecond and disables smooth scrolling.
3. WHEN Toast classes `animate-in` and `animate-out` are used, THE Frontend SHALL have the Animate_Plugin configured in `frontend/tailwind.config.js` so that these classes generate CSS.
4. THE Frontend SHALL include a test that builds or inspects the Tailwind output and fails IF the classes used by Toast animations do not generate CSS.
5. IF the Animate_Plugin is not installed as a dependency, THEN THE Frontend SHALL add it as a pinned dependency, or SHALL replace the Toast animation classes with equivalent classes defined from the Motion_Tokens.
6. WHEN a Toast opens or closes, THE Frontend SHALL animate it using the Motion_Tokens.

### Requirement 3: Button Variants

**User Story:** As a user, I want buttons that show progress and have consistent styles, so that I know when an action is running and can tell actions apart.

#### Acceptance Criteria

1. THE Button SHALL support a `loading` prop.
2. WHILE a Button has `loading` set, THE Button SHALL show a spinner, set `aria-busy="true"`, and ignore click events.
3. WHILE a Button has `loading` set, THE Button SHALL keep its width unchanged from its non-loading width.
4. THE Button SHALL support a `ghost` variant with a transparent background and a tinted hover background using Semantic_Tokens.
5. THE Button SHALL support an icon-only size that renders a square control.
6. IF an icon-only Button is rendered without an accessible name, THEN THE Button SHALL log a development-time warning.
7. THE Button SHALL render icon-only controls with a Touch_Target of at least 44 by 44 CSS pixels on viewports narrower than 768 pixels.
8. THE Button SHALL keep the existing variants and sizes working with unchanged call sites.

### Requirement 4: PageHeader Component

**User Story:** As a user, I want every page to start with the same header layout, so that I always know where I am and where the page actions are.

#### Acceptance Criteria

1. THE PageHeader SHALL render the page title as an `h1`.
2. WHERE a description is provided, THE PageHeader SHALL render it below the title using the muted text token.
3. WHERE actions are provided, THE PageHeader SHALL render them aligned to the end of the header on wide viewports and below the title on narrow viewports.
4. WHERE breadcrumb items are provided, THE PageHeader SHALL render a Breadcrumb above the title.
5. THE Frontend SHALL replace hand-built section and `h1` header markup on every page in `frontend/src/pages/` with PageHeader.
6. WHEN a page renders, THE Frontend SHALL contain exactly one `h1` element on that page.
7. THE PageHeader SHALL give the `h1` `tabIndex={-1}` so that it can receive programmatic focus (Requirement 5).

### Requirement 5: Document Title, Route Focus, and Route Announcement

**User Story:** As a keyboard or screen reader user, I want focus and an announcement to move to the new page when the route changes, so that I know the navigation worked.

#### Acceptance Criteria

1. THE useDocumentTitle hook SHALL set `document.title` to the format "{page title} - Logstead".
2. WHEN a page that uses useDocumentTitle unmounts, THE useDocumentTitle hook SHALL restore the previous document title.
3. WHEN the route changes, THE Frontend SHALL move focus to the `h1` of the new page.
4. WHEN the route changes, THE Route_Announcer SHALL announce the new page title through a polite live region.
5. WHEN the route changes only in the hash or only in search parameters on the same path, THE Frontend SHALL leave focus unchanged and SHALL NOT announce.
6. IF the new page has no `h1` when the route changes, THEN THE Frontend SHALL move focus to the main landmark.
7. THE Frontend SHALL NOT move focus on the initial page load.
8. THE Frontend SHALL apply useDocumentTitle on every page in `frontend/src/pages/`.

### Requirement 6: FormField Component

**User Story:** As a user, I want every form field to show its label, hint, required status, and error in the same way, so that forms are predictable and accessible.

#### Acceptance Criteria

1. THE FormField SHALL render a visible label associated with its control through `htmlFor` and `id`.
2. WHERE a hint is provided, THE FormField SHALL render the hint and link it to the control through `aria-describedby`.
3. WHERE the field is required, THE FormField SHALL render a required marker that is hidden from assistive technology and SHALL set `aria-required="true"` on the control.
4. WHEN an error message is provided, THE FormField SHALL render it with `role="alert"`, SHALL set `aria-invalid="true"` on the control, and SHALL link the error to the control through `aria-describedby`.
5. WHEN no error message is provided, THE FormField SHALL NOT set `aria-invalid` on the control.
6. THE FormField SHALL generate unique ids for the control, hint, and error when the caller does not supply them.
7. THE Frontend SHALL use FormField in all forms in RecordModal-based dialogs and in the ProfilePage form.

### Requirement 7: StateBlock Error Variant with Retry

**User Story:** As a user, I want a clear error message with a way to try again when something fails to load, so that I can recover without reloading the page.

#### Acceptance Criteria

1. THE StateBlock SHALL support an `error` variant that renders a title, a message, and an icon using the `danger` and `danger-subtle` tokens.
2. WHERE an `onRetry` callback is provided, THE StateBlock error variant SHALL render a Retry Button.
3. WHEN the Retry Button is activated, THE StateBlock SHALL call `onRetry`.
4. WHILE a retry is in progress, THE StateBlock error variant SHALL show the Retry Button in the loading state from Requirement 3.
5. THE StateBlock error variant SHALL render with `role="alert"`.
6. THE StateBlock SHALL keep the existing loading and empty variants working with unchanged call sites.

### Requirement 8: Skeleton Placeholders

**User Story:** As a user, I want placeholder shapes while data loads, so that the page layout does not jump and I can tell loading is under way.

#### Acceptance Criteria

1. THE Frontend SHALL provide a Skeleton primitive that renders an animated placeholder using the `surface-muted` token.
2. THE Frontend SHALL provide a table skeleton that renders a configurable number of rows and columns.
3. THE Frontend SHALL provide a tile skeleton that matches the size of a Dashboard tile.
4. WHILE the Reduced_Motion_Rule applies, THE Skeleton SHALL render without animation.
5. THE Skeleton SHALL be hidden from assistive technology, and the container SHALL expose `aria-busy="true"` and an accessible loading label.
6. WHERE a ResponsiveTable shows its first load, THE ResponsiveTable SHALL support rendering the table skeleton in place of rows.

## Phase 2 - Forms and States

### Requirement 9: Move Legacy Dialogs onto RecordModal

**User Story:** As a user, I want every create and edit dialog to look and behave the same, so that I do not have to relearn each one.

#### Acceptance Criteria

1. THE Frontend SHALL render the Transactions page dialog, AddPropertyDialog, EditPropertyDialog, AddBusinessDialog, and EditBusinessDialog using RecordModal and useRecordModal.
2. THE Frontend SHALL remove the Transactions page dialog's own hand-built close (x) button, so that RecordModal provides the only close control.
3. WHEN AddPropertyDialog is open, THE Address_Autocomplete SHALL suggest addresses and apply RentCast enrichment to the form fields exactly as before this feature.
4. WHEN a user selects an address suggestion, THE AddPropertyDialog SHALL populate the same fields with the same values as before this feature.
5. IF RentCast enrichment fails, THEN THE AddPropertyDialog SHALL keep the form open, retain the user's entered values, and allow manual entry.
6. WHEN a Legacy_Dialog form is submitted successfully, THE Frontend SHALL close the dialog and refresh the affected list.
7. IF a Legacy_Dialog form submission fails, THEN THE Frontend SHALL keep the dialog open, show the error inside the dialog, and retain the entered values.
8. THE Frontend SHALL preserve existing test coverage for each Legacy_Dialog, updated only for changed markup.
9. WHEN a RecordModal opens, THE RecordModal SHALL move focus to the first field, and WHEN it closes, THE RecordModal SHALL return focus to the element that opened it.

### Requirement 10: Dirty-State Discard Confirmation

**User Story:** As a user, I want a warning before I lose unsaved edits, so that I do not discard work by accident.

#### Acceptance Criteria

1. THE useRecordModal hook SHALL expose a `dirty` indicator that is true IF AND ONLY IF the current form values differ from the initial values.
2. WHEN a user attempts to close a RecordModal (Escape key, backdrop click, close icon, or Cancel button) WHILE Dirty_State is true, THE RecordModal SHALL show the Discard_Confirmation and SHALL keep the modal open.
3. WHEN a user confirms the Discard_Confirmation, THE RecordModal SHALL close and discard the edits.
4. WHEN a user cancels the Discard_Confirmation, THE RecordModal SHALL stay open with all edits retained.
5. WHEN a user attempts to close a RecordModal WHILE Dirty_State is false, THE RecordModal SHALL close without showing the Discard_Confirmation.
6. WHEN a form is submitted successfully, THE RecordModal SHALL close without showing the Discard_Confirmation.
7. WHEN a user restores every edited field to its initial value, THE useRecordModal hook SHALL report Dirty_State as false.
8. WHEN a user attempts to switch Imports tabs WHILE the manual form has Dirty_State true, THE ImportSectionTabs SHALL show the Discard_Confirmation and SHALL stay on the current tab until the user confirms.
9. WHEN a user attempts to switch Imports tabs WHILE the manual form has Dirty_State false, THE ImportSectionTabs SHALL switch tabs without confirmation.
10. WHILE the manual Imports form has Dirty_State true, THE Frontend SHALL register a `beforeunload` handler, and WHEN Dirty_State becomes false, THE Frontend SHALL remove the handler.

### Requirement 11: Form Error Summary and Focus First Invalid Field

**User Story:** As a user, I want to see all form errors at once and be taken to the first one, so that I can fix them quickly.

#### Acceptance Criteria

1. WHEN a form is submitted with one or more validation errors, THE Frontend SHALL render an Error_Summary at the top of the form listing each error message.
2. WHEN the Error_Summary renders, THE Frontend SHALL move focus to the first invalid field in document order.
3. WHEN a user activates an entry in the Error_Summary, THE Frontend SHALL move focus to the corresponding field.
4. THE Error_Summary SHALL have `role="alert"` and a heading that states the number of errors.
5. WHEN all validation errors are fixed, THE Frontend SHALL remove the Error_Summary.
6. THE Frontend SHALL show each field's error inline using FormField in addition to the Error_Summary.
7. IF a server error that is not tied to a field is returned, THEN THE Frontend SHALL show it in the Error_Summary without moving focus to a field.

### Requirement 12: Money Input and Date Input

**User Story:** As a user, I want currency and date fields that are easy to fill in, so that I can enter amounts and dates quickly and correctly.

#### Acceptance Criteria

1. THE Money_Input SHALL display a currency prefix before the value.
2. THE Money_Input SHALL set `inputMode="decimal"`.
3. WHEN a user types into the Money_Input, THE Money_Input SHALL accept digits, one decimal separator, and an optional leading minus sign where negative values are allowed, and SHALL reject other characters.
4. WHEN a pasted value contains a currency symbol or thousands separators, THE Money_Input SHALL strip them and keep the numeric value.
5. THE Money_Input SHALL limit the decimal part to two digits.
6. THE Money_Input SHALL expose the parsed numeric value to the form independently of its display format.
7. FOR ALL valid numeric amounts, formatting an amount for display and then parsing the displayed text SHALL produce the original amount (round-trip property).
8. THE Date_Input SHALL render a quick "Today" button adjacent to the input.
9. WHEN a user activates the "Today" button, THE Date_Input SHALL set the value to the current local date in `YYYY-MM-DD` format and SHALL move focus back to the input.
10. THE Frontend SHALL use Money_Input for all currency fields and Date_Input for all single-date fields in RecordModal-based forms.

### Requirement 13: Undo for Safe Deletes

**User Story:** As a user, I want to undo an accidental delete, so that I do not lose data by a misclick.

#### Acceptance Criteria

1. THE Frontend SHALL designate each delete as a Safe_Delete only WHERE the full record can be re-created from data retained on the client by calling existing APIs without backend changes.
2. WHEN a Safe_Delete succeeds, THE Frontend SHALL show an Undo_Toast with an Undo action.
3. WHEN a user activates Undo within the Undo_Toast lifetime, THE Frontend SHALL re-create the record with the retained field values and refresh the list.
4. IF re-creating the record fails, THEN THE Frontend SHALL show an error Toast and SHALL keep the list consistent with the server.
5. THE Undo_Toast SHALL remain visible for at least 8 seconds.
6. WHILE the user is hovering or focusing the Undo_Toast, THE Undo_Toast SHALL pause its dismissal timer.
7. WHERE a delete removes records that cannot be fully re-created (for example records with attached files or dependent child records), THE Frontend SHALL keep the existing ConfirmDialog flow and SHALL NOT show an Undo_Toast.
8. THE Frontend SHALL list each delete in the design document as Safe_Delete or ConfirmDialog-only.

### Requirement 14: First-Load-Only Loading, Consistent Load Errors, and Toasts

**User Story:** As a user, I want lists to stay in place while they refresh, errors to look and behave the same everywhere, and notifications that I can dismiss, so that the app feels stable and predictable.

#### Acceptance Criteria

1. WHILE data for a page has never loaded successfully, THE Frontend SHALL show the loading state (spinner or Skeleton).
2. WHEN data is refreshed after a first successful load, THE Frontend SHALL keep the existing content mounted and SHALL NOT replace it with a spinner.
3. WHILE a refresh is in progress after a first load, THE Frontend SHALL indicate activity without unmounting content, using a non-blocking indicator.
4. THE Frontend SHALL apply First_Load_Loading on every page and list that loads data, including the Properties page.
5. THE Frontend SHALL provide a shared hook or helper that derives the first-load state so that pages do not each reimplement it.
6. THE Frontend SHALL render every page-level load failure using the Load_Error_Alert (the StateBlock error variant from Requirement 7), replacing the hand-rolled red alert lines on the 11 pages that currently use them, including the different banner style on Properties and Businesses.
7. WHEN a load fails, THE Load_Error_Alert SHALL include a Retry action that re-runs the failed request.
8. IF a refresh fails after a first successful load, THEN THE Frontend SHALL keep the stale content visible and show the Load_Error_Alert above it.
9. THE Toast SHALL render a visible close button with an accessible name.
10. WHEN a success or info Toast opens, THE Toast SHALL stay visible for 5 seconds unless dismissed.
11. WHEN an error Toast opens, THE Toast SHALL stay visible for at least 10 seconds unless dismissed.
12. WHILE the pointer is over a Toast or focus is within a Toast, THE Toast SHALL pause its dismissal timer.
13. WHEN the Properties empty state renders, THE PropertiesPage SHALL show exactly one "Add property" button.

## Phase 3 - Shell, Tables, Dashboard

### Requirement 15: Brand and Shell

**User Story:** As a user, I want the app to carry the Logstead brand, so that it feels like a finished product.

#### Acceptance Criteria

1. THE App_Shell SHALL render the logo in the header, linked to the Dashboard, with an accessible name of "Logstead home".
2. THE Frontend SHALL reference the square icon-only version as the favicon through `frontend/index.html`, SHALL provide a `.png` fallback icon, and SHALL provide an `apple-touch-icon`.
3. THE Frontend SHALL set the base `<title>` in `frontend/index.html` to "Logstead".
4. THE Logo SHALL render the tagline "Schedule E simplified" (shown uppercase in the artwork) only in the layouts that the design document designates, and SHALL omit the tagline on viewports narrower than 640 pixels and in the App_Shell header.
5. WHILE the dark theme is active, THE Logo SHALL render the wordmark in the inherited text color and the tagline in a lightened token color, both at WCAG_AA contrast against their background.
6. THE logo image SHALL have alternative text "Logstead", or SHALL be marked decorative IF adjacent visible text already provides the name.
7. THE Frontend SHALL load the logo and favicon without a layout shift in the header by reserving its dimensions.

### Requirement 16: Brand Fallback If the Asset Fails or Is Removed

**User Story:** As a developer, I want the shell to stay branded and readable if the logo asset fails to load or is removed, so that a missing asset never breaks the header.

#### Acceptance Criteria

1. IF the logo asset fails to load or is removed, THEN THE App_Shell SHALL render the Wordmark_Fallback in the header in the `fg` token color.
2. WHILE the Wordmark_Fallback is rendered and the dark theme is active, THE Wordmark_Fallback SHALL meet WCAG_AA contrast against the dark header background.
3. THE Wordmark_Fallback SHALL expose the accessible name "Logstead".
4. IF the icon assets fail to load or are removed, THEN THE Frontend SHALL provide a Monogram_Favicon showing the letter "L".
5. WHEN the logo asset is restored, THE Frontend SHALL switch back to it by changing a single import or path constant, without further layout changes.
6. THE Wordmark_Fallback SHALL NOT use amber or gold for any text.

### Requirement 17: Accent and Palette Changes Keep Contrast

**User Story:** As a user, I want the brand colors to remain readable in both themes, so that the new look does not reduce accessibility.

#### Acceptance Criteria

1. THE Frontend SHALL implement the teal accent by changing Semantic_Token values in `frontend/src/index.css` only, without hard-coded palette colors in components.
2. THE Accent_Token set SHALL meet WCAG_AA in both light and dark themes for: `accent-fg` on `accent`, `accent` text on `canvas` and `surface`, and `accent` as a UI boundary or focus ring on `canvas` and `surface`, and `border-strong` as a form control boundary on `canvas` and `surface`.
3. THE Frontend SHALL NOT use gold or amber for body-size text in either theme.
4. THE Frontend SHALL use orange only for decorative and illustrative elements and chart series, and SHALL NOT use orange for body text.
5. THE Frontend SHALL choose teal Accent_Token values that meet WCAG_AA in both themes, with `#0F766E` as the light theme base candidate.
6. THE Frontend SHALL NOT retain indigo values in any Semantic_Token after the accent change.
7. THE Frontend SHALL include a test that computes contrast ratios for each token pair listed in Requirement 25.1 in both themes and fails IF any ratio is below its WCAG_AA threshold.

### Requirement 18: Grouped Primary Navigation

**User Story:** As a user, I want navigation grouped by purpose with icons, so that I can find things faster and see where I am.

#### Acceptance Criteria

1. THE Primary_Nav SHALL be organized into three Nav_Groups labeled Portfolio, Tax, and Tools.
2. THE Frontend SHALL assign existing destinations to Nav_Groups in `navConfig.ts` as: Portfolio = Dashboard, Properties, Businesses; Tax = Reports, Carryforward; Tools = Import.
3. THE Primary_Nav SHALL render an icon next to each item label, with the icon hidden from assistive technology.
4. THE Primary_Nav SHALL render each Nav_Group with an accessible group label.
5. WHILE a Primary_Nav item is active, THE Primary_Nav SHALL render it with a tinted background (`accent-subtle`) and an accent bar, and SHALL set `aria-current="page"`.
6. THE Primary_Nav SHALL NOT render the active item as a solid accent block.
7. THE Primary_Nav SHALL render the same groups and items in the desktop nav and the mobile drawer.
8. THE mobile drawer SHALL render a close icon Button with the accessible name "Close menu" and a Touch_Target of at least 44 by 44 CSS pixels.
9. WHEN the mobile drawer is open and the user presses Escape, THE mobile drawer SHALL close and return focus to the menu button, and WHEN the user selects a destination, THE mobile drawer SHALL close and the route change SHALL move focus to the new page `h1` (Requirement 5.3).

### Requirement 19: Property Switcher

**User Story:** As a user, I want to switch property without losing my place, so that I can compare the same section across properties.

#### Acceptance Criteria

1. WHERE at least one property exists, THE App_Shell SHALL render a Property_Switcher in the header listing the user's properties by name.
2. WHILE a property route is active, THE Property_Switcher SHALL show the current property as selected.
3. WHEN a user selects a different property, THE Property_Switcher SHALL navigate to the same Current_Section for the selected property.
4. WHEN a user selects a different property WHILE no property sub-section is active, THE Property_Switcher SHALL navigate to the property overview.
5. THE Property_Switcher SHALL build its target path using `propertyPath` from `navConfig.ts`.
6. FOR ALL properties and all `PROPERTY_NAV` segments, switching to a property and then reading the Current_Section from the resulting path SHALL return the same segment (round-trip property).
7. WHERE sub-section state is carried in the query string (for example a selected year), THE Property_Switcher SHALL preserve the `year` parameter when present.
8. THE Property_Switcher SHALL be keyboard operable and expose an accessible name of "Switch property".
9. WHILE the property list is loading, THE Property_Switcher SHALL show a Skeleton, and IF the property list fails to load, THEN THE Property_Switcher SHALL be hidden and SHALL NOT block the rest of the shell.

### Requirement 20: ResponsiveTable Upgrades

**User Story:** As a user, I want tables I can sort and scan easily, so that I can find numbers faster.

#### Acceptance Criteria

1. WHERE a column is marked sortable, THE ResponsiveTable SHALL render its header as a button that cycles the Sort_State through ascending, descending, and none.
2. WHILE a column is sorted, THE ResponsiveTable SHALL set `aria-sort` on that column header to `ascending` or `descending`, and SHALL render a direction indicator.
3. WHEN the Sort_State is none, THE ResponsiveTable SHALL show rows in their original input order.
4. WHEN sorting by a column, THE ResponsiveTable SHALL sort numeric columns by numeric value, date columns by date value, and text columns by locale-aware string comparison.
5. THE ResponsiveTable sort SHALL be stable, so that rows with equal sort keys keep their original relative order.
6. FOR ALL row sets and columns, sorting ascending and then sorting descending SHALL return rows in the reverse key order, and sorting SHALL preserve the number of rows and the set of rows (invariant property).
7. THE ResponsiveTable SHALL support a sticky header that stays visible when the table body scrolls.
8. WHEN a table row is hovered or contains focus, THE ResponsiveTable SHALL show a row highlight using Semantic_Tokens.
9. THE ResponsiveTable SHALL right-align columns marked numeric, in both header and body cells, and SHALL use tabular numerals for them.
10. WHERE a table has no sortable columns, THE ResponsiveTable SHALL render as before this feature, with unchanged call sites.
11. THE ResponsiveTable SHALL keep its existing mobile layout behavior.

### Requirement 21: Transactions Search and Filters

**User Story:** As a user, I want to search and filter my transactions, so that I can find a specific entry in a long list.

#### Acceptance Criteria

1. THE TransactionsPage SHALL render a search input with the accessible name "Search transactions".
2. WHEN a user types in the search input, THE TransactionsPage SHALL show only transactions whose description, category, or amount text contains the query, ignoring case.
3. THE TransactionsPage SHALL render a category filter listing the categories present in the loaded transactions.
4. WHEN a user selects a category, THE TransactionsPage SHALL show only transactions in that category.
5. WHEN both a search query and a category are active, THE TransactionsPage SHALL show only transactions that match both.
6. WHEN the search query is empty and no category is selected, THE TransactionsPage SHALL show all loaded transactions.
7. FOR ALL transaction lists, search queries, and category selections, every displayed transaction SHALL satisfy the filter, and every transaction that satisfies the filter SHALL be displayed (filter correctness property).
8. WHEN the filters match no transactions, THE TransactionsPage SHALL show an empty state that states no transactions match, with a "Clear filters" action.
9. WHEN filters are active, THE TransactionsPage SHALL show the count of displayed transactions out of the total and SHALL announce count changes through a polite live region.
10. THE TransactionsPage SHALL filter on the client using already loaded data, without new backend parameters.

### Requirement 22: Migrate High-Traffic Tables

**User Story:** As a user, I want the loan and asset tables to behave like the other tables, so that sorting, hover, and mobile layout are consistent.

#### Acceptance Criteria

1. THE LoansPage SHALL render YearlyRollupTable and PaymentRowsTable using ResponsiveTable.
2. THE asset ScheduleTable SHALL render using ResponsiveTable.
3. THE migrated tables SHALL display the same columns, values, and formatting as before the migration.
4. THE migrated tables SHALL right-align numeric columns and use sticky headers where the table scrolls.
5. WHERE the migrated table is a PaymentRowsTable with many rows, THE PaymentRowsTable SHALL keep sticky headers enabled.
6. THE Frontend SHALL keep the Dense_Report_Tables unchanged.
7. THE Frontend SHALL preserve existing tests for the migrated tables, updated only for changed markup.

### Requirement 23: Progressive Dashboard

**User Story:** As a user, I want the dashboard to show content as it arrives, so that I am not staring at a blocking spinner.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE DashboardPage SHALL render the page header and the layout immediately.
2. WHILE a Dashboard tile's data is loading for the first time, THE DashboardPage SHALL render the tile skeleton for that tile only.
3. WHEN a tile's data arrives, THE DashboardPage SHALL replace that tile's skeleton with the tile content without waiting for other tiles.
4. IF a tile's data fails to load, THEN THE DashboardPage SHALL render the Load_Error_Alert with Retry inside that tile and SHALL leave other tiles unaffected.
5. THE DashboardPage SHALL apply First_Load_Loading to each tile, per Requirement 14.
6. THE DashboardPage SHALL keep the existing error boundary behavior.

### Requirement 24: First-Run Checklist Card

**User Story:** As a new user, I want a checklist that shows me what to do next, so that I can get to my first Schedule E report quickly.

#### Acceptance Criteria

1. THE DashboardPage SHALL render a Checklist_Card with these steps in order: add a property, record income or expenses, add a loan or depreciable assets, review the Schedule E report.
2. THE Checklist_Card SHALL derive each step's completion from existing data: at least one property exists; at least one transaction exists; at least one loan or depreciable asset exists; the Schedule E report step is complete when a local visited flag is set, which happens when the user visits either report page (`/reports` or `/properties/:propertyId/reports`).
3. WHILE a step is incomplete, THE Checklist_Card SHALL render it as a link to the page where the step is done.
4. WHILE a step is complete, THE Checklist_Card SHALL render it with a check icon and an accessible text status of "Completed".
5. WHEN all steps are complete, THE Checklist_Card SHALL be hidden.
6. WHEN a user dismisses the Checklist_Card, THE Frontend SHALL hide it and SHALL persist the dismissal in local storage.
7. THE Frontend SHALL store the visited flag and the dismissal in local storage under keys that include the signed-in user id WHEN a user id is available on the client, and SHALL make no backend call for either.
8. IF local storage is unavailable, THEN THE Frontend SHALL treat the visited flag as unset and the Checklist_Card as not dismissed, and SHALL NOT raise an error.
9. WHILE checklist data is loading, THE Checklist_Card SHALL render a Skeleton, and IF checklist data fails to load, THEN THE Checklist_Card SHALL be hidden.
10. THE Checklist_Card SHALL show progress as "{completed} of {total} done".
11. FOR ALL combinations of step completion flags, the displayed completed count SHALL equal the number of true flags, and the Checklist_Card SHALL be visible IF AND ONLY IF at least one flag is false and it has not been dismissed (invariant property).

### Requirement 25: Accessibility Sweep

**User Story:** As a user with accessibility needs or a phone, I want targets that are easy to hit and text that is easy to read, so that the app is usable for everyone.

#### Acceptance Criteria

1. THE Frontend SHALL audit these token pairs in both themes: `fg` on `canvas`, `fg` on `surface`, `fg-muted` on `canvas`, `fg-muted` on `surface`, `fg-subtle` on `canvas`, `fg-subtle` on `surface`, `accent-fg` on `accent`, `accent` on `surface`, `danger` on `danger-subtle`, `success` on `success-subtle`, and `warning` on `warning-subtle`.
2. THE Frontend SHALL ensure each pair used for body-size text meets a contrast ratio of at least 4.5:1, and each pair used for large text or UI component boundaries meets at least 3:1.
3. IF `fg-subtle` on `surface` or `canvas` is below 4.5:1 in either theme, THEN THE Frontend SHALL either darken the `fg-subtle` token to reach 4.5:1 or restrict `fg-subtle` to placeholders, decorative text, and large text, and SHALL replace its use for body-size text with `fg-muted`.
4. THE Frontend SHALL give every interactive control a Touch_Target of at least 44 by 44 CSS pixels on viewports narrower than 768 pixels, including nav items, icon buttons, table sort headers, tabs, and form controls.
5. WHERE a visual element is smaller than 44 pixels, THE Frontend SHALL extend its hit area with padding or a pseudo-element without changing its visual size.
6. THE Axe_Suite SHALL render every entry in the Route_Table once in the light theme and once in the dark theme and SHALL assert that vitest-axe reports no violations.
7. WHEN a new route is added to `App.tsx`, THE Axe_Suite SHALL include it automatically by deriving its list from the Route_Table, or SHALL fail IF a route is missing from its list.
8. THE Axe_Suite SHALL also cover RecordModal open states for each migrated Legacy_Dialog, in both themes.
9. THE Frontend SHALL keep a visible focus indicator with at least 3:1 contrast on every interactive control in both themes.

## Testing Expectations

- **Component tests (vitest + React Testing Library)** SHALL cover each new or changed component: Button, PageHeader, FormField, StateBlock, Skeleton, Money_Input, Date_Input, RecordModal discard flow, Toast, ResponsiveTable, Property_Switcher, Primary_Nav, and Checklist_Card.
- **Accessibility tests (vitest-axe)** SHALL run over every route in both the light and dark themes (Requirement 25.6), and over each migrated dialog in its open state.
- **Property tests (fast-check, minimum 100 iterations)** SHALL cover pure logic and state logic where sensible:
  - dirty-state reducer or derivation: dirty is true if and only if values differ from initial; restoring the initial values returns to clean (Requirement 10.1, 10.7)
  - sort behavior: stability, reversal, and row preservation (Requirement 20.6)
  - transaction filtering correctness (Requirement 21.7)
  - money format and parse round-trip (Requirement 12.7)
  - property-switch path round-trip (Requirement 19.6)
  - checklist visibility and count (Requirement 24.11)
  - contrast ratio computation for token pairs (Requirement 17.7)
- **Configuration checks** SHALL verify that Toast animation classes generate CSS (Requirement 2.4) and that the Reduced_Motion_Rule is present in the built CSS.
- **Integration tests** SHALL verify that each migrated Legacy_Dialog preserves its previous behavior, including Address_Autocomplete and RentCast enrichment in AddPropertyDialog.
- **Existing tests** SHALL continue to pass, updated only where markup intentionally changes.
- **Phase gating**: each phase SHALL pass the full frontend test suite and Axe_Suite coverage for the routes it changed before it is considered shippable.
