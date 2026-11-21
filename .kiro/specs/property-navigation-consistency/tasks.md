# Implementation Plan: Property Navigation Consistency

## Overview

Bring the property overview page (`PropertyDetailPage`) into line with its sibling sub-pages by reusing the shared breadcrumb + Section Tabs machinery and the shared property context, dropping its duplicate property fetch. The work is frontend-only and navigation/presentation-only: add an Overview entry to `PROPERTY_NAV`, extract `resolvePropertyName` and the Section Tabs into shared units, refactor `PropertySection` to consume them, and rework `PropertyDetailPage` to read identity from `usePropertyContext()`.

Tasks are ordered so shared units land first, then the consumers. Each task cites the requirement(s) it satisfies. Test sub-tasks are marked optional with `*`; core implementation tasks are never optional. The design has no Correctness Properties section (navigation/presentation-only), so there are no property-based tests — coverage is example-based with Vitest + React Testing Library + `vitest-axe`.

## Tasks

- [x] 1. Update the per-property navigation model (`frontend/src/components/navConfig.ts`)
  - Add optional `end?: boolean` to the `PropertyNavItem` interface (mirrors `NavItem.end`; exact active matching for the index route).
  - Make `PROPERTY_NAV` lead with `{ segment: "", label: "Overview", end: true }`, keeping the existing three entries unchanged and in order → ordered set {Overview, Transactions, Depreciable Assets, Schedule E Report}.
  - Make `propertyPath(propertyId, "")` return the clean base path `/properties/${propertyId}` (no trailing slash); non-empty segments unchanged.
  - _Requirements: 2.1, 2.2_

  - [x]* 1.1 Unit test navConfig changes
    - Assert `PROPERTY_NAV[0]` is `{ segment: "", label: "Overview", end: true }` and the four labels appear in order {Overview, Transactions, Depreciable Assets, Schedule E Report}.
    - Assert `propertyPath(id, "")` === `/properties/${id}` and `propertyPath(id, "transactions")` === `/properties/${id}/transactions`.
    - _Requirements: 2.1, 2.2_

- [x] 2. Extract `resolvePropertyName` into a shared module (`frontend/src/components/propertyName.ts`)
  - Move the private `resolvePropertyName(status, name)` out of `PropertySection` into `propertyName.ts`, exported with identical behavior (`loading` → `"Loading property…"`; `loaded` + name → name; else → `"Property"`).
  - Update `PropertySection` to import `resolvePropertyName` from the shared module (no behavior change).
  - _Requirements: 1.3, 3.4_

  - [x]* 2.1 Unit test `resolvePropertyName`
    - `loading` → placeholder; `loaded` + name → name; `loaded` without name / `error` → `"Property"`.
    - _Requirements: 1.3, 3.4_

- [x] 3. Extract shared `PropertySectionTabs` and refactor `PropertySection` (`frontend/src/components/PropertySectionTabs.tsx`, `frontend/src/components/PropertySection.tsx`)
  - Create a presentational `PropertySectionTabs({ propertyId })` component rendering the `<nav aria-label="Property sections">` built from `PROPERTY_NAV`, mapping each item to a `NavLink` whose `to={propertyPath(propertyId, item.segment)}` and `end={item.end}` (Overview uses exact matching), preserving the existing tab classNames and active/`aria-current` wiring.
  - Refactor `PropertySection` to render `<PropertySectionTabs propertyId={propertyId} />` in place of its inline `<nav>`, with no behavior change for sub-pages (breadcrumb still `Properties > {name} > {title}`; sub-pages gain the leading Overview tab from `PROPERTY_NAV`).
  - _Requirements: 1.5, 2.3, 2.5, 5.2, 5.3_

  - [x]* 3.1 Component test `PropertySectionTabs`
    - Renders the four tabs in order; the Overview tab targets `/properties/{id}` and carries `end`; active tab gets active styling and `aria-current="page"`.
    - _Requirements: 2.2, 2.4, 2.5, 5.3_

  - [x]* 3.2 Regression test `PropertySection` sub-page
    - At `/properties/{id}/transactions`: the four tabs render in order; the Overview tab links to the index and is NOT active while the current sub-tab is active; breadcrumb still `Properties > {name} > {title}`.
    - Update the existing `PropertySection` suite only as needed to match the extracted-tabs shape.
    - _Requirements: 2.3, 2.5_

- [x] 4. Rework `PropertyDetailPage` to consume the shared context and machinery (`frontend/src/pages/PropertyDetailPage.tsx`)
  - Remove the identity `getProperty` fetch, its `LoadState`, the `load`/`refresh` identity seam, the ad-hoc `← All properties` link, and the `<h1 id="property-heading">`.
  - Read identity from `usePropertyContext()` (`propertyId`, `status`, `property`); resolve the display name via the shared `resolvePropertyName(context.status, context.property?.name)`.
  - In `<section aria-labelledby="page-heading">`, render in every context state: `<Breadcrumb items={[{ label: "Properties", to: "/properties" }, { label: resolvedName }]} />`, a single `<h1 id="page-heading">{resolvedName}</h1>`, then `<PropertySectionTabs propertyId={propertyId} />`.
  - Keep all content fetches/seams unchanged: `loadPhotos`/`loadAssets`/`loadReport`/`loadNote`/`saveNote`; render the existing header card (photo/address/type/`TaxYearSelector`, minus its own `<h1>`) and the tile grid only when `context.status === "loaded"`.
  - Error state (`context.status === "error"`): show a single `role="alert"` in place of the loaded content while breadcrumb + tabs persist; remove the old overview-only property error/404 copy. Loading: breadcrumb + tabs with the `"Loading property…"` placeholder, tiles only when loaded.
  - Update the existing `PropertyDetailPage` tests only as needed to supply context instead of the removed `load` identity seam.
  - _Requirements: 1.1, 1.2, 1.4, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 5.1_

  - [x]* 4.1 Component tests — overview orientation
    - Breadcrumb is `Properties` (link) then the resolved name as the current non-link crumb with `aria-current="page"` (no trailing "Overview" crumb); four tabs in order with Overview active on the index route; exactly one `<h1>` showing the resolved name and the raw `propertyId` never appears as visible content.
    - _Requirements: 1.1, 1.2, 1.4, 2.4, 5.1_

  - [x]* 4.2 Component tests — identity from context and content seams
    - With context `loading`/`loaded`/`error`, the resolved name is placeholder/name/`"Property"` and breadcrumb + tabs persist in all three states; no identity fetch seam exists; `loadPhotos`/`loadAssets`/`loadReport`/`loadNote` are still invoked.
    - Error state shows a single `role="alert"` in place of the loaded tiles while breadcrumb + tabs persist (old "Could not load this property." path gone).
    - _Requirements: 3.1, 3.2, 3.3, 4.2, 4.3, 4.4_

  - [x]* 4.3 Accessibility tests — overview
    - `nav[aria-label="Breadcrumb"]` and `nav[aria-label="Property sections"]` resolve to distinct landmarks; `vitest-axe` reports no violations in loaded (and ideally loading/error) states.
    - _Requirements: 5.1, 5.2, 5.5_

- [x] 5. Checkpoint — verify the full frontend suite and build
  - Run `cd frontend && npm test -- --run` and `npm run build` (type-check + build must both pass).
  - Confirm the existing `PropertyDetailPage`, `PropertySection`, and `PropertyLayout` suites stay green after the refactor; adjust those existing tests only as needed to match the identity-from-context shape (removing the `load` identity seam may require providing context in `PropertyDetailPage` tests).
  - Note the iCloud `* 2.*` cleanup quirk when inspecting generated artifacts; ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster path; core implementation tasks (1, 2, 3, 4) and the checkpoint are not optional.
- Each implementation task references the specific requirement clauses it satisfies for traceability.
- No property-based tests: the design has no Correctness Properties section — the feature is navigation/presentation-only and the one candidate invariant is decided by React Router's `end` matching, which this feature configures rather than implements.
- Non-Goals respected: no backend change, no visual restyle, no global-nav change, no property switcher, no new navigation component beyond extracting existing machinery, no renaming/adding sections beyond the Overview entry.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["1.1", "2.1", "3"] },
    { "id": 2, "tasks": ["3.1", "3.2", "4"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] }
  ]
}
```
