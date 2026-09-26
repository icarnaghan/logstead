# Requirements Document

## Introduction

Logstead is a single-user, serverless AWS application for preparing an IRS Schedule E rental-tax return. The frontend is a client-rendered React 19 + Vite + TypeScript + Tailwind CSS + Radix UI single-page application served from S3/CloudFront. The application already has a mature semantic color-token system, an accessible theme toggle (Light/Dark/System), exact-decimal money handling, accessibly labeled forms, a WAI-ARIA combobox for address autocomplete, and an accessible app shell with a skip link, landmarks, and responsive navigation.

This spec captures two related bodies of work, both constrained to the **current backend functionality**:

1. **Part A — UX/UI Polish.** A professional pass over the existing interface: extracting shared UI primitives, improving navigation wayfinding, removing raw identifiers from the UI, adding delete confirmations and consistent success feedback, making tables responsive, unifying money formatting, cleaning up style/token drift, enriching empty/loading states, and polishing the Schedule E report as a hand-off document.

2. **Part B — Visualizations.** Introducing data visualizations (charts) to the app. The earlier MVP deliberately shipped without charts; that decision is now reversed. Charts are introduced as an accessibility-preserving enhancement that always sits alongside the underlying data, reads the existing theme tokens, respects the exact-decimal money model, and is phased so that Phases 1 and 2 use only data the current API already returns.

**Data constraint that shapes this spec:** The dashboard and reports endpoints return **single-tax-year snapshots**, not time series. The only native multi-period series available today is the per-asset depreciation schedule. Year-over-year trend visualizations therefore require either stitching multiple per-year fetches on the client (the tax-year selector already fetches per-year, so the pattern exists) or a new backend endpoint; that work is captured as an explicitly optional stretch item.

This document defines functional and quality requirements only. Technical design decisions (chart library selection, component structure, file layout) are deferred to the design phase, with the specific exception that this document records the recommended default library so the design phase can make and justify the final call.

## Glossary

- **Logstead**: The overall application. Used as the system name in ubiquitous requirements.
- **User**: The single authenticated person who owns and operates the rental activity and uses Logstead.
- **UI_Primitive**: A shared, reusable presentational component (Button, Input, Card/Tile, Select, ConfirmDialog, Toast) intended to replace copy-pasted class strings and one-off markup across the frontend.
- **Button_Variant**: One of the visual/semantic styles a shared Button supports: `primary`, `secondary`, or `danger`.
- **Focus_Ring**: The visible keyboard-focus indicator applied consistently by shared UI_Primitives.
- **ConfirmDialog**: A shared modal that requires explicit User confirmation before a destructive action proceeds.
- **Toast**: A shared, transient status message that communicates the success or failure of an action, matching the existing notes-save/enrichment feedback pattern.
- **Destructive_Action**: An action that permanently removes User data: deleting a Property, Transaction, Depreciable_Asset, or Receipt.
- **Breadcrumb**: A navigational trail showing the User's location in the app hierarchy (for example, `Properties > {property name} > Transactions`).
- **PropertySection_Nav**: The existing shared sub-navigation component used to move between a Property's Transactions, Assets, and Reports sub-pages.
- **Sub_Page**: A Property-scoped page reached from a Property: the Transactions, Assets, or Reports page.
- **Raw_Identifier**: A machine-oriented identifier not meant for human reading, such as a Property UUID, a Cognito `sub`, or a raw `category_id`.
- **formatMoney**: The single, canonical money-formatting function that renders exact-decimal money strings as currency for display.
- **Money_String**: An exact monetary value represented as a two-decimal string, computed with integer-cents math (never a floating-point number).
- **Integer_Cents**: A monetary value represented as a whole number of cents, used internally by the chart layer to avoid floating-point arithmetic.
- **Schedule_E_Report**: A per-Property or combined, per-Tax_Year summary that presents Schedule E line-item totals; the app's primary hand-off document.
- **Tax_Year**: A calendar year for which income, expenses, and depreciation are aggregated for reporting.
- **Chart**: A data visualization rendered in the UI (for example, a horizontal bar chart or a line/area chart).
- **Chart_Colors_Helper**: A small helper that resolves the application's semantic CSS color tokens into color values consumable by the charting layer, via `rgb(var(--color-...))`.
- **Data_Table**: The tabular representation of the same data a Chart visualizes, always present so the data is available without relying on the Chart.
- **Depreciation_Schedule**: The genuine multi-year series of depreciation amounts for a Depreciable_Asset, available from the assets schedule endpoint.
- **Theme**: The active light or dark appearance, toggled via the `.dark` class on the document root.

## Requirements

---

# Part A — UX/UI Polish

### Requirement 1: Shared UI Primitives

**User Story:** As the developer maintaining Logstead, I want a set of shared, reusable UI primitives, so that styling is defined once, stays consistent, and every other UX improvement can build on a common foundation.

#### Acceptance Criteria

1. THE Logstead SHALL provide a shared Button UI_Primitive that supports the Button_Variants `primary`, `secondary`, and `danger`.
2. THE Logstead SHALL apply a consistent Focus_Ring to every shared UI_Primitive that is keyboard-focusable.
3. THE Logstead SHALL provide shared Input, Card/Tile, and Select UI_Primitives.
4. THE Logstead SHALL provide a shared ConfirmDialog UI_Primitive and a shared Toast UI_Primitive.
5. WHERE a component previously used a copy-pasted accent-button class string or Focus_Ring fragment, THE Logstead SHALL render the corresponding shared Button UI_Primitive instead.
6. THE Logstead SHALL preserve the existing semantic color tokens and Theme behavior when rendering shared UI_Primitives, so that primitives adapt to light and dark Themes without hardcoded colors.

### Requirement 2: Navigation Wayfinding

**User Story:** As the User, I want to always know which property I am working in and how to get back, so that I can move between a property's sub-pages without losing my place.

#### Acceptance Criteria

1. WHEN the User views any Sub_Page, THE Logstead SHALL display the Property name as the page context rather than the Property Raw_Identifier.
2. WHEN the User views any Sub_Page, THE Logstead SHALL display a Breadcrumb trail of the form `Properties > {property name} > {sub-page name}`.
3. WHEN the User activates a Breadcrumb ancestor link, THE Logstead SHALL navigate to that ancestor location.
4. THE Logstead SHALL render the shared PropertySection_Nav on every Property Sub_Page.
5. WHERE a Sub_Page previously duplicated the sub-navigation markup inline, THE Logstead SHALL render the shared PropertySection_Nav instead.

### Requirement 3: Remove Raw Identifiers From the UI

**User Story:** As the User, I want to see human-readable names and labels instead of machine identifiers, so that the interface is understandable and trustworthy.

#### Acceptance Criteria

1. WHEN the User views a Sub_Page, THE Logstead SHALL present the Property by its name and SHALL NOT present the Property Raw_Identifier as User-facing content.
2. WHEN the User views the profile page, THE Logstead SHALL present human-readable account information and SHALL NOT present the Cognito `sub` Raw_Identifier as User-facing content.
3. WHEN a Transaction's category name is available, THE Logstead SHALL display the category name in the transaction list.
4. IF a Transaction's category name is unavailable, THEN THE Logstead SHALL display a human-readable fallback label and SHALL NOT display the raw `category_id`.

### Requirement 4: Confirmation on Destructive Deletes

**User Story:** As the User, I want to confirm before permanently deleting my records, so that I do not lose data by accident.

#### Acceptance Criteria

1. WHEN the User initiates a Destructive_Action, THE Logstead SHALL present a ConfirmDialog identifying the record to be deleted before performing the deletion.
2. WHEN the User confirms the ConfirmDialog, THE Logstead SHALL perform the deletion.
3. WHEN the User cancels or dismisses the ConfirmDialog, THE Logstead SHALL leave the record unchanged.
4. THE Logstead SHALL require ConfirmDialog confirmation for deleting a Property, a Transaction, a Depreciable_Asset, and a Receipt.
5. THE Logstead SHALL use the shared ConfirmDialog UI_Primitive for all Destructive_Action confirmations.

### Requirement 5: Consistent Success Feedback

**User Story:** As the User, I want clear confirmation when an action succeeds, so that I know my change was saved.

#### Acceptance Criteria

1. WHEN the User successfully creates, updates, or deletes a Transaction, THE Logstead SHALL display a Toast confirming the outcome.
2. WHEN the User successfully creates, updates, or deletes a Depreciable_Asset, THE Logstead SHALL display a Toast confirming the outcome.
3. WHEN the User successfully uploads or deletes a Receipt, THE Logstead SHALL display a Toast confirming the outcome.
4. IF an action fails, THEN THE Logstead SHALL display a Toast that communicates the failure to the User.
5. THE Logstead SHALL use the shared Toast UI_Primitive for success and failure feedback, consistent with the existing notes-save and enrichment feedback pattern.

### Requirement 6: Responsive Tables

**User Story:** As the User on a phone, I want tables to remain usable on a small screen, so that I can review transactions, assets, and dashboard breakdowns on mobile.

#### Acceptance Criteria

1. WHEN a data table is wider than the viewport, THE Logstead SHALL provide a horizontal-scroll wrapper so that all columns remain reachable without breaking page layout.
2. WHERE the viewport width is below the small breakpoint, THE Logstead SHALL present the transactions, assets, and dashboard breakdown data in a card layout instead of a multi-column row layout.
3. THE Logstead SHALL apply responsive table behavior to the transactions table, the assets table, and the dashboard breakdown table.

### Requirement 7: Unified Money Formatting

**User Story:** As the User, I want every monetary value to be formatted the same way, so that amounts are consistent and easy to read across the app.

#### Acceptance Criteria

1. THE Logstead SHALL format every User-facing monetary value through the single canonical formatMoney function.
2. WHEN the assets list displays a cost basis, THE Logstead SHALL render the cost basis through formatMoney rather than as a raw Money_String.
3. WHEN the Schedule E report table displays an amount, THE Logstead SHALL render the amount through formatMoney rather than as a raw Money_String.
4. THE Logstead SHALL consolidate the previously separate money formatters into the single formatMoney function used everywhere.
5. THE Logstead SHALL render formatted monetary values using tabular figures, preserving the existing numeric alignment behavior.

### Requirement 8: Token and Style Drift Cleanup

**User Story:** As the User, I want a visually consistent interface, so that the app feels professionally finished and coherent across pages.

#### Acceptance Criteria

1. THE Logstead SHALL express surface, border, and elevation styling through the existing semantic color tokens and shared UI_Primitives rather than through one-off raw color utility classes.
2. WHEN the profile page renders separators, THE Logstead SHALL use the semantic border token rather than a raw color utility class.
3. WHEN a modal overlay renders, THE Logstead SHALL derive its backdrop and elevation from the shared UI_Primitives and semantic tokens rather than one-off raw color and shadow utilities.
4. WHEN portfolio summary cards render, THE Logstead SHALL apply the shared card elevation styling consistently with other cards.
5. THE Logstead SHALL present a single consistent Tax_Year selector style and a single consistent Cancel/Delete button style across the app.

### Requirement 9: Richer Empty and Loading States

**User Story:** As the User, I want helpful empty and loading states on every sub-page, so that I understand what to do next and receive feedback while data loads.

#### Acceptance Criteria

1. WHILE a Sub_Page is loading its data, THE Logstead SHALL display a loading state on the transactions, assets, and reports Sub_Pages.
2. WHEN a Sub_Page has no records to display, THE Logstead SHALL display an empty state that explains the absence and offers the next action, consistent with the existing add-first-property empty state.
3. THE Logstead SHALL apply richer empty and loading states to the transactions, assets, and reports Sub_Pages.

### Requirement 10: Reports as a Hand-Off Document

**User Story:** As the User, I want the Schedule E report to read like a clean document I can hand to a tax preparer, so that year-end filing is straightforward.

#### Acceptance Criteria

1. WHEN the User views a Schedule_E_Report, THE Logstead SHALL group line items into clearly delineated income, expense, and depreciation sections.
2. WHEN the User views a Schedule_E_Report, THE Logstead SHALL visually emphasize section totals and the net result.
3. WHERE the User prints or exports a Schedule_E_Report, THE Logstead SHALL apply print-friendly styling that renders the report legibly on paper.
4. THE Logstead SHALL format every monetary value in the Schedule_E_Report through formatMoney.

---

# Part B — Visualizations

### Requirement 11: Charting Foundation and Theme Integration

**User Story:** As the User, I want charts that match the app's look in both light and dark modes, so that visualizations feel native and remain readable when I switch themes.

#### Acceptance Criteria

1. THE Logstead SHALL render Charts using a single charting approach selected in the design phase, with Recharts recorded here as the recommended default and visx noted as the lower-level alternative.
2. THE Logstead SHALL resolve Chart colors from the existing semantic CSS color tokens through the Chart_Colors_Helper using `rgb(var(--color-...))` and SHALL NOT use a hardcoded color palette.
3. WHEN the User changes the Theme, THE Logstead SHALL render Charts using the colors of the newly active Theme.
4. WHEN a Chart draws gridlines, THE Logstead SHALL derive gridline color from the `--color-border` token.
5. THE Logstead SHALL apply a consistent Chart height and a calm visual treatment, omitting 3D effects, gradients, and heavy animation.
6. THE Logstead SHALL keep Charts purposeful and avoid visual clutter, favoring a small number of meaningful Charts per screen; a data-dense screen such as the dashboard MAY present several Charts, while most screens present a single primary Chart. (Guideline, not a hard limit.)

### Requirement 12: Chart Accessibility

**User Story:** As a User relying on assistive technology or unable to distinguish colors, I want the data behind every chart to remain fully available, so that charts enhance rather than gate my access to information.

#### Acceptance Criteria

1. THE Logstead SHALL present the Data_Table for a Chart alongside the Chart, either below the Chart or via a show-data toggle.
2. THE Logstead SHALL apply `role="img"` and a summarizing `aria-label` to each Chart's rendered SVG.
3. WHEN the User interacts with a Chart using the keyboard, THE Logstead SHALL make Chart tooltips reachable via keyboard.
4. THE Logstead SHALL convey Chart meaning through means in addition to color, and SHALL NOT encode meaning by color alone.

### Requirement 13: Chart Money Precision

**User Story:** As the User, I want chart values to reflect exact money amounts, so that visualized figures agree with the numbers shown elsewhere.

#### Acceptance Criteria

1. WHEN the Logstead prepares monetary data for a Chart, THE Logstead SHALL convert each Money_String to Integer_Cents for the chart layer.
2. WHEN the Logstead labels a Chart axis or tooltip with a monetary value, THE Logstead SHALL format the value through formatMoney.
3. THE Logstead SHALL NOT introduce floating-point arithmetic when preparing or displaying monetary Chart values.

### Requirement 14: Chart Performance

**User Story:** As the User, I want the initial dashboard to load quickly, so that adding charts does not slow down the app.

#### Acceptance Criteria

1. THE Logstead SHALL lazy-load Chart components so that the charting code is not included in the initial application paint.
2. WHERE a screen does not display a Chart, THE Logstead SHALL NOT load the charting bundle for that screen.
3. WHILE a lazily-loaded Chart is loading, THE Logstead SHALL display a fallback placeholder in the Chart's area.

### Requirement 15: Chart Responsiveness

**User Story:** As the User on a phone, I want charts to adapt to small screens, so that visualizations stay legible on mobile.

#### Acceptance Criteria

1. THE Logstead SHALL render each Chart in a responsive container that maintains a fixed aspect ratio across viewport sizes.
2. WHERE the viewport width is below the small breakpoint, THE Logstead SHALL present bar Charts using a horizontal orientation.
3. WHERE the viewport width is below the small breakpoint, THE Logstead SHALL fall back to the Data_Table in place of the Chart.

### Requirement 16: Phase 1 Charts — Expense Breakdown by Category

**User Story:** As the User, I want to see which expense categories dominate a property's costs, so that I can understand my spending at a glance.

#### Acceptance Criteria

1. WHEN the User views a per-Property Schedule_E_Report, THE Logstead SHALL display a ranked horizontal bar Chart of expenses by Schedule E category.
2. WHEN the User views the combined report, THE Logstead SHALL display a ranked horizontal bar Chart of expenses by Schedule E category.
3. THE Logstead SHALL order the expense-by-category bars by descending amount.
4. THE Logstead SHALL source the expense-by-category Chart data from the existing report data without requiring a new backend endpoint.

### Requirement 17: Phase 1 Charts — Income vs Expenses vs Net

**User Story:** As the User, I want a compact visual of income, expenses, and net for a snapshot, so that I can quickly gauge profitability.

#### Acceptance Criteria

1. WHEN the User views the dashboard portfolio snapshot, THE Logstead SHALL display a compact bar Chart of income, expenses, and net for the selected Tax_Year.
2. WHEN the User views a per-Property income/expense tile, THE Logstead SHALL display a compact bar Chart of income, expenses, and net for that Property and Tax_Year.
3. THE Logstead SHALL source the income/expenses/net Chart data from the existing dashboard data without requiring a new backend endpoint.

### Requirement 18: Phase 1 Charts — Net Contribution by Property

**User Story:** As the User, I want to see how each property contributes to my portfolio net, so that I can compare properties against one another.

#### Acceptance Criteria

1. WHEN the User views the dashboard, THE Logstead SHALL display a horizontal bar Chart of net contribution by Property for the selected Tax_Year.
2. THE Logstead SHALL source the net-contribution-by-Property Chart data from the existing dashboard properties data without requiring a new backend endpoint.

### Requirement 19: Phase 2 Chart — Asset Depreciation Schedule

**User Story:** As the User, I want to visualize an asset's depreciation over time, so that I can see how its remaining basis declines across the recovery period.

#### Acceptance Criteria

1. WHEN the User views a Depreciable_Asset's Depreciation_Schedule, THE Logstead SHALL display a line or area Chart of the multi-year Depreciation_Schedule.
2. THE Logstead SHALL derive the Depreciation_Schedule Chart from the existing asset schedule endpoint, which provides a genuine multi-year series.
3. THE Logstead SHALL present the Depreciation_Schedule Chart alongside its Data_Table, consistent with the Chart accessibility requirements.

### Requirement 20: Phase 3 Chart (Optional/Stretch) — Year-Over-Year Portfolio Net Trend

**User Story:** As the User, I want to see how my portfolio net has trended across years, so that I can understand my rental activity over time. (This requirement is explicitly optional and may depend on backend work.)

#### Acceptance Criteria

1. WHERE the year-over-year portfolio net trend feature is enabled, THE Logstead SHALL display a Chart of portfolio net across multiple Tax_Years.
2. WHERE the trend data is assembled on the client, THE Logstead SHALL obtain each year's value by fetching per-Tax_Year data using the existing per-year fetch pattern and stitching the results together.
3. IF a dedicated backend endpoint is required to serve the multi-year trend efficiently, THEN THE design SHALL document that endpoint as a new backend dependency and mark this requirement as a stretch item outside the current no-new-endpoint constraint.

---

## Non-Goals

- THE Logstead SHALL NOT add new backend endpoints as part of this effort, with the sole exception of the explicitly optional year-over-year trend endpoint described in Requirement 20.
- THE Logstead SHALL NOT surface the expense-import flow in the UI; the expense-import routes remain out of scope.
- THE Logstead SHALL NOT change the exact-decimal money model; Charts consume converted Integer_Cents and format labels through formatMoney.
- THE Logstead SHALL NOT replace numeric or tabular representations with Charts; Charts augment the numbers-first, accessibility-first design and never become the sole representation of data.
