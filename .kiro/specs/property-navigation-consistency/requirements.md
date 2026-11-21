# Requirements Document

## Introduction

Logstead is a single-user React 19 + Vite + TypeScript SPA for preparing an IRS Schedule E rental tax return. Within a selected property, the per-property sub-pages (Transactions, Depreciable Assets, Schedule E Report) already present consistent wayfinding — a breadcrumb trail and a per-property section tab bar — through the shared `PropertySection` component, which reads the property context fetched once by `PropertyLayout`.

The property overview page (the property index route) is the one page in the per-property section that does **not** share this machinery: it renders an ad-hoc `← All properties` link and its own heading instead of the breadcrumb and section tabs, and it issues a second, redundant fetch of the property it is already given through the shared context. The result is that orientation ("knowing where you are") disappears the moment the user lands on, or returns to, the property overview, and there is no section tab anywhere that leads back to the overview.

This feature brings the property overview page into line with its sibling sub-pages so that orientation is consistent across every property-scoped page. It is frontend-only and navigation/presentation-only: it reuses the existing `PropertySection`, `Breadcrumb`, and `PropertyLayout` shared-context machinery, adds a single "Overview" entry to the per-property navigation model, and removes the overview page's duplicate property fetch. No backend changes, no visual restyle, no changes to the global navigation, and no property switcher.

## Glossary

- **Property Overview Page**: The page rendered by `PropertyDetailPage` at the property index route `/properties/{propertyId}`. The per-property landing page that shows property identity and summary tiles.
- **Property Sub-Page**: Any per-property page under the overview — Transactions (`/transactions`), Depreciable Assets (`/assets`), or Schedule E Report (`/reports`) — rendered through `PropertySection`.
- **Property-Scoped Page**: The Property Overview Page together with all Property Sub-Pages; every page nested under the `properties/:propertyId` layout route.
- **Property Context**: The `{ propertyId, status, property }` value fetched once by `PropertyLayout` and shared with its child routes via React Router `<Outlet context>`, read through `usePropertyContext()`.
- **Breadcrumb**: The labelled `nav` landmark (accessible name "Breadcrumb") rendered by the `Breadcrumb` component, showing the ancestor trail `Properties > {property name} > {current page}`.
- **Section Tabs**: The per-property sub-navigation rendered by `PropertySection` as a labelled `nav` landmark (accessible name "Property sections"), built from `PROPERTY_NAV` using `NavLink` with active highlighting and `aria-current`.
- **Primary Navigation**: The global, always-visible app navigation (`AppLayout` / `MainNav`), out of scope for this feature.
- **Resolved Property Name**: The human-readable property display string produced by the existing `resolvePropertyName` behavior — the property's name when loaded, a neutral placeholder while loading, and a neutral fallback on error — never the raw property id.
- **PROPERTY_NAV**: The per-property navigation model in `navConfig.ts` from which the Section Tabs are built.

## Requirements

### Requirement 1: Consistent orientation on the property overview page

**User Story:** As a single user preparing my Schedule E return, I want the property overview page to show the same breadcrumb and section tabs as the other property pages, so that I always know which property I am in and where I am within it.

#### Acceptance Criteria

1. WHEN the Property Overview Page is displayed, THE Property Overview Page SHALL render the Breadcrumb using the same shared machinery used by the Property Sub-Pages.
2. WHEN the Property Overview Page is displayed, THE Property Overview Page SHALL render the Section Tabs using the same shared machinery used by the Property Sub-Pages.
3. THE Property Overview Page SHALL present the property by its Resolved Property Name and SHALL NOT display the raw property id as user-facing content.
4. WHEN the Property Overview Page renders the Breadcrumb, THE Breadcrumb SHALL show the trail `Properties > {Resolved Property Name}` as the ancestor path for the overview.
5. THE Property Overview Page SHALL reuse the existing `PropertySection`, `Breadcrumb`, and `PropertyLayout` shared-context components and SHALL NOT introduce a new navigation component.

### Requirement 2: Overview entry in the per-property navigation model

**User Story:** As a single user navigating a property, I want an "Overview" tab in the per-property section navigation, so that I can return to the property overview from any property sub-page.

#### Acceptance Criteria

1. THE PROPERTY_NAV model SHALL include an "Overview" entry that targets the property index route `/properties/{propertyId}`.
2. WHEN the Section Tabs are rendered on any Property-Scoped Page, THE Section Tabs SHALL present the set {Overview, Transactions, Depreciable Assets, Schedule E Report} in that order.
3. WHEN a Property Sub-Page is displayed, THE Section Tabs SHALL render the "Overview" tab as a link to the property index route so the user can navigate to the Property Overview Page.
4. WHILE the Property Overview Page (the property index route) is the active route, THE Section Tabs SHALL mark the "Overview" tab as the active tab and SHALL apply `aria-current="page"` to it.
5. WHILE a Property Sub-Page is the active route, THE Section Tabs SHALL NOT mark the "Overview" tab as active, using exact (end) matching for the index route so the "Overview" tab's active state does not spuriously match sub-routes.

### Requirement 3: Orientation present across all property context states

**User Story:** As a single user, I want the breadcrumb and section tabs to stay in place while a property is loading or if it fails to load, so that orientation never disappears.

#### Acceptance Criteria

1. WHILE the Property Context status is `loading`, THE Property Overview Page SHALL render the Breadcrumb and Section Tabs, showing the loading placeholder as the Resolved Property Name.
2. WHEN the Property Context status is `loaded`, THE Property Overview Page SHALL render the Breadcrumb and Section Tabs, showing the property's name as the Resolved Property Name.
3. IF the Property Context status is `error`, THEN THE Property Overview Page SHALL render the Breadcrumb and Section Tabs, showing the neutral fallback as the Resolved Property Name.
4. THE Resolved Property Name shown on the Property Overview Page SHALL match the existing `resolvePropertyName` behavior used by the Property Sub-Pages.

### Requirement 4: Overview consumes the shared property context

**User Story:** As a single user, I want the property name shown on the overview to come from the same source as the rest of the property section, so that identity and orientation are consistent and the property is not fetched twice.

#### Acceptance Criteria

1. THE Property Overview Page SHALL obtain the property for identity and orientation from the shared Property Context via `usePropertyContext()`.
2. THE Property Overview Page SHALL NOT issue its own duplicate fetch of the property that `PropertyLayout` has already fetched.
3. WHERE the Property Overview Page loads overview-specific content that is not provided by the Property Context (for example photos, depreciable assets, or the Schedule E report), THE Property Overview Page SHALL retain those existing content fetches unchanged.
4. WHEN the Property Context status is `error`, THE Property Overview Page SHALL present the error state consistently with the rest of the property section rather than through a separate overview-only property error.

### Requirement 5: Accessible, distinct navigation landmarks

**User Story:** As a user relying on assistive technology and keyboard navigation, I want the breadcrumb, section tabs, and primary navigation to be distinguishable and operable, so that I can orient and move around the property section without confusion.

#### Acceptance Criteria

1. THE Breadcrumb on the Property Overview Page SHALL be a `nav` landmark with the accessible name "Breadcrumb".
2. THE Section Tabs on the Property Overview Page SHALL be a `nav` landmark with an accessible name distinct from the Breadcrumb and from the Primary Navigation.
3. WHILE a Section Tab corresponds to the active route, THE Section Tabs SHALL apply `aria-current` to that tab.
4. WHEN a user navigates the Property Overview Page by keyboard, THE Property Overview Page SHALL expose a sensible focus order in which the Breadcrumb and Section Tabs are reachable and operable with visible focus.
5. WHEN the Property Overview Page is evaluated with the project's automated accessibility checks (vitest-axe), THE Property Overview Page SHALL introduce no new accessibility violations.

## Non-Goals

- Any backend change.
- Any change to the global Primary Navigation (`AppLayout` / `MainNav`); it is intentionally left as-is.
- A property switcher or any cross-property quick-switch.
- Any visual restyle (colors, typography, design tokens, component styling) beyond placing the existing Breadcrumb and Section Tabs components.
- Renaming existing property sections (Transactions, Depreciable Assets, Schedule E Report).
- Changing the behavior of the Property Sub-Pages, which already present the Breadcrumb and Section Tabs correctly; only the Property Overview Page is brought into line.
- Adding new per-property sections beyond the existing ones plus the Overview entry.

## Resolved Decisions

1. **Overview breadcrumb form (resolved — option a).** The Property Sub-Pages' breadcrumb ends with the current sub-page label (`Properties > {name} > {sub-page}`). For the Property Overview Page, the trail ends at the property name — `Properties > {Resolved Property Name}` — with **no trailing crumb**; the resolved name is the current (non-link) tail crumb. There is no literal "Overview" trailing crumb ("Overview" appears only as a Section Tab label). This confirms the form already assumed by Requirement 1.4.
