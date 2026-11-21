# Implementation Plan: Dashboard depreciable-assets summary & layout polish

## Overview

This plan implements two deliberately independent concerns, kept as separate sections so each can be built and verified on its own:

- **Section 1 — Dashboard depreciable-assets summary.** A new read-only backend aggregation endpoint (`DashboardService.asset_summary` + `GET /dashboard/assets?taxYear=Y`) plus a new frontend `DepreciableAssetsTile` and injectable `getAssetSummary` api function. Backend first, then frontend consumes it.
- **Section 2 — Layout & spacing polish (strictly bounded).** A reusable `PageContainer` width convention applied to only the four Panel_Pages, relaxing the shared `AppLayout` cap. Layout/spacing only — a hard boundary forbids any visual restyle (Requirement 10).

Section 2 shares no code paths with Section 1 and can proceed in parallel.

Engineering conventions followed throughout: backend uses pytest + Hypothesis + moto with money as two-decimal `Decimal` strings; frontend uses vitest + React Testing Library + vitest-axe with an injectable api layer and money typed as `string`.

### Environment notes

- The repo lives under iCloud; occasionally cleans leave `* 2.*` duplicate files — delete those duplicates if a module imports the wrong copy.
- If backend imports fail, rebuild the virtualenv before running pytest. Backend tests run via `.venv/bin/python -m pytest -q`.

## Tasks

### Section 1 — Dashboard depreciable-assets summary

- [x] 1. Add the backend `asset_summary` aggregation on `DashboardService`
  - [x] 1.1 Add DTOs and the `asset_summary(tax_year)` method
    - In `backend/src/logstead/services/dashboard.py`, add frozen dataclasses `PropertyAssetSummary` (`property_id`, `property_name`, `asset_count: int`, `depreciation_total: Money`) and `AssetSummary` (`tax_year: int`, `properties: tuple[PropertyAssetSummary, ...]`)
    - Inject a `DepreciationService` into `DashboardService.__init__` alongside the existing `properties` and `reports`
    - Implement `asset_summary(tax_year: int | None = None)`: default to the current tax year; iterate `self._properties.list()` (user-scoped); per property derive `asset_count` from `self._depreciation.list_assets(prop.id)` and `depreciation_total` from `self._depreciation.property_depreciation_for_year(prop.id, year)` (the SAME method feeding Schedule E Line 18); return `depreciation_total` as a two-decimal `Decimal` via `to_money`
    - Empty portfolio returns `properties=()`
    - _Requirements: 3.1, 3.3, 3.4, 6.1_

  - [x] 1.2 Wire the read-only route and handler in the router
    - In `backend/src/logstead/router/handler.py`, add handler `_dashboard_asset_summary(wiring, user, params, body, query)` following the existing dashboard-handler pattern: build the service via `_dashboard_service_or_503`, read optional `taxYear` from the query with `_int_param`, return `_response(200, service.asset_summary(tax_year))`
    - Update `_dashboard_service_or_503` to also construct the `DepreciationService` (via the existing `_depreciation_service(wiring)` per-request constructor) and pass it to `DashboardService`
    - Register `("GET", "/dashboard/assets", _dashboard_asset_summary, False)` in the existing Dashboard group of `_ROUTES` (alongside `/dashboard` and `/dashboard/properties`)
    - _Requirements: 3.1, 3.2, 3.4, 3.5_

  - [x]* 1.3 Write endpoint/handler tests (moto)
    - Seeded properties + assets: assert one row per property with expected `asset_count` and `depreciation_total` (Req 3.1)
    - taxYear param parsing; route registered `GET` only, no write path (Req 3.2)
    - User-scoping: two users with disjoint properties, assert A never sees B's properties (Req 3.4)
    - Money-as-two-decimal-string: each `depreciation_total` matches `^-?\d+\.\d{2}$` through `_to_jsonable` (Req 3.5)
    - Empty states: empty portfolio returns `properties: []`; asset-free property returns `asset_count: 0` and `"0.00"` (Req 5.1, 5.2)
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 5.1, 5.2_

  - [x]* 1.4 Write Hypothesis property-based reconciliation tests
    - **Property 1: Per-property depreciation reconciles with Schedule E Line 18** — generate properties with randomized assets (cost basis, placed-in-service date, recovery period) and a random tax year; assert the endpoint's per-property `depreciation_total` equals that property's Schedule E report Line 18 for the year. Tag comment: `# Feature: dashboard-assets-and-layout-polish, Property 1: Per-property depreciation reconciles with Schedule E Line 18`; `@settings(max_examples=100)` (or higher)
    - **Property 2: Portfolio depreciation reconciles with the combined report** — generate a portfolio and a random tax year; assert the sum of per-property `depreciation_total` equals the combined report's summed Line 18. Tag comment: `# Feature: dashboard-assets-and-layout-polish, Property 2: Portfolio depreciation reconciles with the combined report`; `@settings(max_examples=100)` (or higher)
    - **Validates: Requirements 6.1, 6.2, 6.3**

- [x] 2. Backend checkpoint
  - Run `.venv/bin/python -m pytest -q`. Ensure all tests pass; if imports fail, rebuild the venv and delete any iCloud `* 2.*` duplicate files, then re-run. Ask the user if questions arise.

- [x] 3. Add the frontend injectable api function
  - [x] 3.1 Add `getAssetSummary` and its types
    - In `frontend/src/api/assets.ts`, add `PropertyAssetSummary` (`property_id`, `property_name`, `asset_count: number`, `depreciation_total: string`) and `AssetSummary` (`tax_year: number`, `properties: readonly PropertyAssetSummary[]`) interfaces
    - Add `getAssetSummary(taxYear: number, client: ApiClient = apiClient): Promise<AssetSummary>` issuing `client.get<AssetSummary>("/dashboard/assets", { query: { taxYear } })`, following the existing injectable-`ApiClient` convention; keep money as a `string` with no `Number` coercion
    - _Requirements: 3.5, 4.1_

- [x] 4. Add the `DepreciableAssetsTile` to the dashboard
  - [x] 4.1 Implement the tile and wire it into `DashboardPage.tsx`
    - Create `DepreciableAssetsTile` rendering a `Tile` with a semantic list (`ul`/`li` + `dl`), one row per property showing property name, `asset_count`, and `formatMoney(depreciation_total)` (from `frontend/src/lib/money.ts`), each row with a `<Link>` to `/properties/{propertyId}/assets` (Req 1.2, 1.3, 2.1, 2.2)
    - Inject the loader via a new optional prop `loadAssetSummary = getAssetSummary` on `DashboardPageProps`, mirroring the existing `loadCombined`/`loadAssets` injection
    - Load once per selected tax year via a single `getAssetSummary(taxYear)` read (no per-property `listAssets` fan-out); reload on tax-year change; ignore aborted fetches via an `AbortController`/active flag (Req 1.4, 4.1)
    - Render the tile only when the portfolio has properties; the dashboard already short-circuits to `DashboardEmptyState` when there are none (Req 5.1)
    - Asset-free properties render count `0` and `formatMoney("0.00")` and still show the assets link (Req 5.2)
    - Own fetch state (`loading | loaded | error`); on failure render an inline `role="alert"` error for the tile and leave the rest of the dashboard rendered (Req 5.3)
    - Accessibility: each link is a focusable anchor in document order, carries the existing `focus-visible:outline ...` utility classes, and has an accessible name identifying the property (e.g. `aria-label={`View assets for ${property_name}`}`) (Req 7.1–7.4)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 4.1, 5.1, 5.2, 5.3, 7.1, 7.2, 7.3, 7.4_

  - [x]* 4.2 Write RTL + vitest-axe tests for the tile
    - Renders one row per property with count + `formatMoney` total; links target `/properties/{propertyId}/assets` with accessible names identifying the property (Req 1.1, 1.2, 1.3, 2.1, 7.1–7.4)
    - Changing the tax year refetches with the new year and updates totals; assert the loader is called with the new `taxYear` (Req 1.4)
    - Single aggregation read: `getAssetSummary` called once, no per-property `listAssets` fan-out (Req 4.1)
    - Empty/edge/error: no-properties shows the existing empty state and no tile (Req 5.1); asset-free property shows zero count/total and still links (Req 5.2); rejected fetch shows the tile error and leaves other tiles rendered (Req 5.3)
    - `axe(container)` over the dashboard with the tile present reports no new violations, following the existing `DashboardPage.test.tsx` axe pattern (Req 7.5)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 4.1, 5.1, 5.2, 5.3, 7.1, 7.2, 7.3, 7.4, 7.5_

### Section 2 — Layout & spacing polish (strictly bounded)

> HARD BOUNDARY (Requirement 10): every task in this section modifies ONLY page container max-widths, responsive breakpoints, and whitespace/spacing (`max-w-*`, `w-*`, `gap-*`, `space-*`, `px-*`/`py-*`, responsive prefixes). It MUST NOT change any color, typography/type scale, component visual styling, border radii, shadows, or design tokens, and MUST NOT edit the theme/token source or `ThemeProvider`. Existing light/dark/system theming is preserved exactly.

- [x] 5. Introduce the `PageContainer` width convention and relax the shell cap
  - [x] 5.1 Create `PageContainer` and relax `AppLayout`
    - Create `frontend/src/components/PageContainer.tsx`: a presentational `<div>` wrapper with a `width?: "wide" | "narrow"` prop (`wide` → `max-w-screen-2xl`, `narrow` → `max-w-6xl`) applying `mx-auto w-full ${max} space-y-6` — width/spacing utilities only, no color/type/token/radius/shadow classes
    - In `frontend/src/components/AppLayout.tsx`, relax the content-row `max-w-6xl` cap to the widened standardized max-width so Panel_Pages can fill the ~1440px desktop width, keeping the header visually aligned; change only width/breakpoint/spacing utilities
    - _Requirements: 8.1, 8.2, 9.1, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 5.2 Apply `PageContainer` (wide) to the four Panel_Pages
    - Wrap page content in `PageContainer` (default `wide`) in `DashboardPage.tsx`, `PropertyDetailPage.tsx`, `AssetsPage.tsx`, and `ReportsPage.tsx`; tune the shared vertical spacing rhythm and panel-group gaps to one consistent convention (Req 9.2, 9.3)
    - Leave out-of-scope pages (PropertiesPage, ProfilePage, ImportReviewPage, NotFoundPage) at the prior narrower width — do not add the widened container to them (Req 8.3)
    - Preserve each Panel_Page's existing semantic landmarks, heading structure, and keyboard focus order (`PageContainer` adds no landmark/heading/focusable element) (Req 11.1, 11.2)
    - _Requirements: 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 10.1, 11.1, 11.2_

  - [x]* 5.3 Write structural + boundary + axe tests for the layout change
    - Structural: each of the four Panel_Pages wraps content in the widened `PageContainer` width class; out-of-scope pages do NOT adopt the widened width (prior width preserved) (Req 8.1–8.3)
    - Spacing/breakpoints: assert the shared spacing-rhythm and responsive breakpoint utility classes are present and the layout stays usable below desktop (Req 9.1–9.4)
    - Hard-boundary guard: assert the change set touches only width/spacing/breakpoint utilities on `AppLayout` + `PageContainer` + the four Panel_Pages, and leaves the theme/token files, color/typography/radius/shadow definitions, and `ThemeProvider` unmodified; confirm token/theming usage unchanged (Req 10.1–10.6)
    - Accessibility: the existing landmark/heading-structure, keyboard focus-order, and `axe` tests for the Panel_Pages (`AppLayout.test.tsx`, `DashboardPage.test.tsx`, `ReportsPage.test.tsx`, `PropertyDetailPage.test.tsx`) remain green with no new violations (Req 11.1–11.3)
    - _Requirements: 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3_

### Final checkpoint

- [x] 6. Full-suite checkpoint
  - Run the full backend suite `.venv/bin/python -m pytest -q`, then frontend `npm test` and `npm run build`. Ensure everything passes and the build succeeds; if backend imports fail, rebuild the venv and delete any iCloud `* 2.*` duplicate files, then re-run. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional (tests) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each implementation task references the specific requirement clauses it satisfies for traceability.
- Section 1 is backend-first: the endpoint (tasks 1–2) must precede the frontend tile (tasks 3–4) that consumes it.
- Section 2 shares no code paths with Section 1 and can proceed in parallel.
- Property tests validate the Requirement 6 reconciliation invariants (minimum 100 examples each); example/edge/axe tests cover rendering, wiring, serialization, and accessibility.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1"] },
    { "id": 1, "tasks": ["1.2", "5.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "3.1", "5.3"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2"] }
  ]
}
```
