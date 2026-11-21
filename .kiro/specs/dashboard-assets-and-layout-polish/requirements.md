# Requirements Document

## Introduction

This feature covers two clearly separated, independently scoped concerns for the Logstead single-user Schedule E rental tax app (React 19 + Vite + TypeScript SPA, Monarch-style theming; Python 3.12 Lambda over single-table DynamoDB).

- **Section 1 — Dashboard depreciable-assets summary ("bubble-up").** Depreciable assets are already fully implemented and managed per property (routes under `/properties/:propertyId/assets`; backend `DepreciableAsset` entity with a computed straight-line / mid-month schedule). The current pain is discoverability: it is not obvious where depreciation schedules for appliances and other assets are entered, because assets are only reachable by drilling into a property's sub-navigation. This section adds a lightweight, per-property depreciable-assets summary to the main Dashboard page (`frontend/src/pages/DashboardPage.tsx`) that links into each property's existing assets page. It is a summary plus links — not a portfolio-wide asset-management screen.

- **Section 2 — Layout & spacing polish (strictly bounded).** Since the earlier UI-polish and visualizations pass added cards, charts, and panels, page content feels "squished in the middle" on a MacBook Air (~1440px) because page containers stayed narrow. This section widens and standardizes page container max-widths for a desktop viewport and improves responsive breakpoints, spacing rhythm, and panel grouping/whitespace — on the Dashboard and the per-property pages that render panels only. It is layout and spacing only: it must not change the Monarch design language (no color, typography/type scale, component visual styling, radius, shadow, or design-token changes).

The two sections are deliberately kept as separate requirement groups so they read as independent concerns and can be verified independently.

## Glossary

- **Dashboard_Summary**: The depreciable-assets summary surfaced on the main Dashboard page by Section 1 (per-property asset count and that property's current-tax-year depreciation total, with a link into the property's assets page).
- **Asset_Summary_Endpoint**: A new read-only backend aggregation endpoint added by Section 1 that returns, for a given Tax_Year, one row per property of the authenticated user containing that property's depreciable-asset count and that property's depreciation total for that Tax_Year. It introduces no new write path and no change to the Depreciable_Asset data model.
- **Schedule_E_Line_18**: The depreciation expense total reported on Schedule E Line 18 for a property (and, in the combined report, across the portfolio) for a Tax_Year.
- **Depreciable_Asset**: An existing per-property entity (cost basis, placed-in-service date, recovery period) with a computed straight-line / mid-month depreciation schedule, managed under `/properties/:propertyId/assets`. Section 1 does not change where assets are entered or managed.
- **Assets_Page**: The existing per-property depreciable-assets management page at the route `/properties/:propertyId/assets`.
- **Dashboard_Page**: The main portfolio-home page at `frontend/src/pages/DashboardPage.tsx`.
- **Panel**: A visual grouping container on a page — a card, chart card, or tile (e.g. the components rendering `Card`, `ChartCard`, or `Tile`) added or expanded by the earlier UI-polish and visualizations pass.
- **Panel_Page**: A page in scope for Section 2 because it renders panels: the Dashboard page and the per-property pages that render cards/charts/tiles (property detail, per-property reports, and per-property assets pages).
- **Monarch_Design_Language**: The app's established "Monarch-style" visual aesthetic — its colors, typography and type scale, component visual styling, border radii, shadows, and design tokens — including light/dark/system theming.
- **Page_Container**: The layout wrapper that bounds a page's horizontal content width (its max-width/breakpoint constraints), including the shared application shell container.
- **Desktop_Viewport**: The target desktop sizing reference of approximately a 1440px-wide MacBook Air viewport.
- **Tax_Year**: The calendar year a depreciation figure is derived for, matching the Dashboard's existing tax-year selection.

## Requirements

### Section 1 — Feature: Dashboard depreciable-assets summary

### Requirement 1: Surface a per-property depreciable-assets summary on the dashboard

**User Story:** As the single user preparing my Schedule E return, I want a depreciable-assets summary on the main dashboard, so that it is obvious where depreciation schedules for assets like appliances are entered.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders for a user who owns one or more properties, THE Dashboard_Page SHALL display a Dashboard_Summary listing each of the user's properties.
2. WHERE a property is listed in the Dashboard_Summary, THE Dashboard_Page SHALL display that property's count of Depreciable_Asset records and that property's depreciation total for the selected Tax_Year.
3. THE Dashboard_Page SHALL present each property's depreciation total in the app's existing two-decimal money format.
4. WHEN the user changes the selected Tax_Year on the Dashboard_Page, THE Dashboard_Page SHALL update each property's displayed depreciation total in the Dashboard_Summary to the newly selected Tax_Year.

### Requirement 2: Link each property into its existing assets page

**User Story:** As the single user, I want each property in the dashboard summary to link into that property's assets page, so that I can go straight to entering or reviewing its depreciation schedules.

#### Acceptance Criteria

1. WHERE a property is listed in the Dashboard_Summary, THE Dashboard_Page SHALL provide a link to that property's existing Assets_Page at `/properties/{propertyId}/assets`.
2. WHEN the user activates a property's Dashboard_Summary link, THE Dashboard_Page SHALL navigate to that property's existing Assets_Page.

### Requirement 3: Provide a read-only per-property aggregation endpoint

**User Story:** As the maintainer, I want the dashboard summary backed by a single read-only aggregation endpoint, so that the summary gets proper per-property separation without making one `listAssets` call per property and without any data-model change.

#### Acceptance Criteria

1. THE Asset_Summary_Endpoint SHALL return, for a given Tax_Year, one entry per property owned by the authenticated user containing that property's count of Depreciable_Asset records and that property's depreciation total for that Tax_Year.
2. THE Asset_Summary_Endpoint SHALL be read-only and SHALL NOT introduce any new backend write path.
3. THE Asset_Summary_Endpoint SHALL NOT change the Depreciable_Asset data model, deriving all returned values from the existing per-property asset data stored under `PROPERTY#{propertyId}` and the existing per-asset computed depreciation.
4. THE Asset_Summary_Endpoint SHALL be user-scoped and SHALL return only the authenticated user's properties, consistent with every other route.
5. THE Asset_Summary_Endpoint SHALL serialize each depreciation total as a two-decimal string, consistent with the app's existing Decimal money convention.

### Requirement 4: Consume the aggregation endpoint from the dashboard summary

**User Story:** As the single user, I want the dashboard summary to load from one aggregation read, so that the summary stays responsive as the number of properties grows.

#### Acceptance Criteria

1. WHEN the Dashboard_Page builds the Dashboard_Summary for the selected Tax_Year, THE Dashboard_Summary SHALL obtain every property's asset count and depreciation total from a single read of the Asset_Summary_Endpoint rather than one per-property call for each property.
2. THE Dashboard_Summary SHALL NOT change the Depreciable_Asset data model.
3. THE Dashboard_Summary SHALL manage and enter Depreciable_Asset records only through the existing per-property Assets_Page, not on the Dashboard_Page.

### Requirement 5: Handle empty states gracefully

**User Story:** As the single user, I want the dashboard summary to behave sensibly when there is no asset data yet, so that an empty portfolio or an asset-free property is clear rather than broken.

#### Acceptance Criteria

1. IF the user owns no properties, THEN THE Dashboard_Page SHALL present its existing empty-state guidance and SHALL NOT render the Dashboard_Summary.
2. WHERE a listed property has no Depreciable_Asset records, THE Dashboard_Page SHALL display an empty indication for that property (for example, a zero count and a zero depreciation total) and SHALL still provide that property's link to its Assets_Page.
3. IF the depreciation data for the Dashboard_Summary cannot be loaded, THEN THE Dashboard_Page SHALL display an error message for the Dashboard_Summary and SHALL continue to render the rest of the Dashboard_Page.

### Requirement 6: Depreciation totals reconcile with Schedule E Line 18

**User Story:** As the single user, I want each property's dashboard depreciation figure to be the same authoritative number reported on Schedule E Line 18, so that the dashboard and my return never disagree.

#### Acceptance Criteria

1. THE Dashboard_Summary and the Schedule_E_Line_18 depreciation total SHALL be derived from a single authoritative depreciation source, not two parallel computations.
2. FOR a given property and Tax_Year, THE sum of that property's Depreciable_Asset scheduled depreciation SHALL equal that property's Schedule_E_Line_18 depreciation total for that Tax_Year. This reconciliation invariant is a correctness property suitable for a property-based test (the backend already uses Hypothesis).
3. FOR a given Tax_Year, THE sum across all of the user's properties of the per-property depreciation totals SHALL equal the combined Schedule E report's total Schedule_E_Line_18 depreciation for that Tax_Year.

### Requirement 7: Accessibility of the dashboard summary

**User Story:** As a keyboard and assistive-technology user, I want the dashboard assets summary to be fully accessible, so that I can read and navigate it without a mouse.

#### Acceptance Criteria

1. THE Dashboard_Summary SHALL expose each property's link to its Assets_Page as a keyboard-focusable control reachable in document order.
2. WHEN a Dashboard_Summary link receives keyboard focus, THE Dashboard_Page SHALL render a visible focus indicator on that link.
3. THE Dashboard_Summary SHALL provide an accessible name for each property's Assets_Page link that identifies the target property.
4. THE Dashboard_Summary SHALL render through semantic markup consistent with the existing dashboard.
5. WHEN the Dashboard_Page is evaluated with the project's automated accessibility checks (vitest-axe), THE Dashboard_Summary SHALL introduce no new accessibility violations.

### Section 2 — Layout & spacing polish (strictly bounded)

### Requirement 8: Widen and standardize page container max-widths

**User Story:** As the single user on a MacBook Air, I want pages with panels to use the available desktop width, so that panel content no longer feels squished in a narrow center column.

#### Acceptance Criteria

1. THE Panel_Pages SHALL use a standardized, widened Page_Container max-width tuned for the Desktop_Viewport so that panel content occupies the available desktop width.
2. THE Panel_Pages SHALL apply the same standardized Page_Container max-width convention across all pages in scope so their content widths are consistent.
3. THE layout changes SHALL be applied only to the Panel_Pages and SHALL NOT change the Page_Container of pages that are out of scope.

### Requirement 9: Improve responsive breakpoints and spacing rhythm

**User Story:** As the single user, I want improved breakpoints and spacing between panels, so that cards and charts have room to breathe and group clearly.

#### Acceptance Criteria

1. THE Panel_Pages SHALL apply responsive breakpoints such that at the Desktop_Viewport the panels use the widened Page_Container width rather than a narrow center column.
2. THE Panel_Pages SHALL apply a consistent spacing rhythm (gaps and whitespace) between and around panels.
3. THE Panel_Pages SHALL group related panels with whitespace so the grouping is visually discernible.
4. WHILE the viewport is below the desktop breakpoints, THE Panel_Pages SHALL retain a usable responsive layout.

### Requirement 10: Hard boundary — layout and spacing only, no visual restyle

**User Story:** As the maintainer, I want the layout polish to be strictly bounded to layout and spacing, so that the Monarch design language is preserved and nothing is restyled.

#### Acceptance Criteria

1. THE layout changes SHALL modify only Page_Container widths, responsive breakpoints, and whitespace/spacing.
2. THE layout changes SHALL preserve the Monarch_Design_Language colors unchanged.
3. THE layout changes SHALL preserve the Monarch_Design_Language typography and type scale unchanged.
4. THE layout changes SHALL preserve component visual styling, border radii, and shadows unchanged.
5. THE layout changes SHALL preserve the existing design tokens unchanged.
6. THE layout changes SHALL preserve the existing light/dark/system theming behavior unchanged.

### Requirement 11: Preserve accessibility through the layout changes

**User Story:** As a keyboard and assistive-technology user, I want the layout polish to preserve existing accessibility, so that the pages remain navigable and standards-compliant after the change.

#### Acceptance Criteria

1. THE Panel_Pages SHALL preserve their existing semantic landmarks and heading structure after the layout changes.
2. THE Panel_Pages SHALL preserve the existing keyboard focus order after the layout changes.
3. WHEN the Panel_Pages are evaluated with the project's automated accessibility checks (vitest-axe), THE layout changes SHALL introduce no new accessibility violations.

### Non-Goals (Explicitly Out of Scope)

The following are explicitly out of scope for this feature and SHALL NOT be implemented:

1. Maintenance, service-history, or equipment-lifecycle tracking.
2. The expense-import UI.
3. A portfolio-wide or "Fixed Asset Schedule" asset-management view (the dashboard summary is summary-plus-links only).
4. Any visual restyle, including changes to colors, typography/type scale, component visual styling, radii, shadows, or design tokens.
5. Vocabulary or relabeling changes (for example, renaming "Depreciable Assets").
6. Any change to where depreciable assets are entered or managed (they remain per property on the existing Assets_Page).
7. Any new backend write path, and any change to the Depreciable_Asset data model or single-table schema. The additive read-only Asset_Summary_Endpoint (Requirement 3) is explicitly ALLOWED: it only reads existing per-property asset data and introduces no write path and no schema change.

### Resolved Decisions

1. **Aggregation source for the dashboard summary (resolves prior Open Question 1).** The Dashboard_Summary uses proper per-property separation via a new read-only backend aggregation endpoint (the Asset_Summary_Endpoint, Requirement 3), consumed with a single aggregation read (Requirement 4) — not N client-side `listAssets` calls, and not a data-model or schema change. Assets are already stored per property under `PROPERTY#{propertyId}` and depreciation is already computed per asset, so no storage change is needed.
2. **Depreciation total semantics (resolves prior Open Question 2).** Each property's displayed depreciation figure is authoritative and reconciles with Schedule E Line 18: the dashboard figure and Line 18 are the same number from one authoritative source, captured as a testable reconciliation correctness property (Requirement 6), with portfolio-level consistency across all properties also required.
