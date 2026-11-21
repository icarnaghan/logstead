# Design Document

## Overview

This feature delivers two deliberately independent concerns for the Logstead Schedule E app, kept as cleanly separated sections so each can be built, reviewed, and verified on its own:

- **Section 1 — Dashboard depreciable-assets summary.** Add a lightweight, per-property depreciable-assets summary to the main Dashboard page. It surfaces, for the selected tax year, each property's depreciable-asset count and that property's depreciation total, with a link into the property's existing `/properties/{propertyId}/assets` page. It is backed by one new **read-only** aggregation endpoint and consumed with a single read. It is summary-plus-links only — not a portfolio asset-management screen, and it changes no write path and no data model (Non-Goals 3, 6, 7).
- **Section 2 — Layout & spacing polish (strictly bounded).** Widen and standardize page container max-widths for the ~1440px desktop viewport on the Panel_Pages (Dashboard, PropertyDetailPage, AssetsPage, ReportsPage), and improve responsive breakpoints, spacing rhythm, and panel grouping. This is layout and spacing only — **no** visual restyle of any kind (Requirement 10, Non-Goal 4).

The two sections share no code paths. Section 1 is a backend endpoint plus a frontend tile and api function. Section 2 is a frontend layout convention applied to specific pages. They are documented separately below.

### Grounding facts (confirmed from the codebase)

- The authoritative per-(property, year) depreciation figure is `DepreciationService.property_depreciation_for_year(property_id, tax_year)` in `backend/src/logstead/services/depreciation.py`. `ReportingService._build_report` (in `backend/src/logstead/services/report.py`) sets Schedule E **Line 18** (`DEPRECIATION_LINE = 18`) from exactly this method. The new endpoint will derive each property's depreciation total from the **same** method, so the dashboard figure and Line 18 are the same number by construction (Requirement 6.1).
- Per-property asset **count** comes from the existing per-property asset listing `DepreciationService.list_assets(property_id)` (confirmed in `depreciation.py`), which already filters schedule rows out and returns only asset records.
- The user's property list and user-scoping come from `PropertyService` (constructed with the resolved `current_user`). The router already wires `_property_service`, `_depreciation_service`, and `_reporting_service` per request in `backend/src/logstead/router/handler.py`; there is an existing dashboard route family (`GET /dashboard`, `GET /dashboard/properties`) and a `_dashboard_service_or_503` constructor pattern.
- Money is a `decimal.Decimal` in Python and is serialized to a two-decimal **string** by the router's `_to_jsonable` (Requirement 3.5). The frontend treats money as strings end-to-end and formats with `formatMoney` from `frontend/src/lib/money.ts`.
- The frontend shell `frontend/src/components/AppLayout.tsx` constrains **both** the header and the content row with `mx-auto ... max-w-6xl` and reserves a `w-56` sidebar, so the main content column is narrower than the viewport on a ~1440px MacBook Air. This is the confirmed root cause of "squished in the middle." Every route (including out-of-scope pages) renders through this one shell.

---

## Architecture

### Section 1 — Dashboard depreciable-assets summary

```mermaid
flowchart LR
  A[DashboardPage.tsx<br/>AssetSummary tile] -->|getAssetSummary(taxYear)| B[frontend/src/api/assets.ts<br/>new typed fn]
  B -->|GET /dashboard/assets?taxYear=Y| C[Router handler<br/>_asset_summary]
  C --> D[DashboardService<br/>asset_summary(taxYear)]
  D -->|list()| E[PropertyService<br/>user-scoped]
  D -->|list_assets(pid)| F[DepreciationService]
  D -->|property_depreciation_for_year(pid, Y)| F
  F --> G[(DynamoDB<br/>PROPERTY#id assets + GSI2 schedules)]
```

The new endpoint reuses existing infrastructure end to end: `PropertyService` for the user's properties and scoping, and `DepreciationService` for both the asset count and the authoritative depreciation total. No new repository, adapter, item type, or write path is introduced (Requirements 3.2, 3.3; Non-Goal 7).

### Section 2 — Layout & spacing polish (the key decision)

Every route renders through the single `AppLayout` shell, whose content row is bounded by `mx-auto flex max-w-6xl gap-6 px-4 py-6` with a `w-56` sidebar. Two options were considered:

- **Option A — widen the shared `AppLayout` container.** Simplest and DRY, but it changes the container width of **all** pages, including out-of-scope ones (PropertiesPage, ProfilePage, ImportReviewPage, NotFoundPage). That violates Requirement 8.3 ("applied only to the Panel_Pages ... SHALL NOT change the Page_Container of pages that are out of scope").
- **Option B (recommended) — a reusable page-container width convention applied only to the Panel_Pages.** Keep the `AppLayout` shell's current max-width as the *outer* bound, and introduce a small shared wrapper, `PageContainer`, that each Panel_Page uses to opt into the standardized, widened desktop max-width and spacing rhythm. Out-of-scope pages are untouched.

**Recommendation: Option B.** It satisfies "only Panel_Pages change" (Requirement 8.3) while staying DRY — the widened width and spacing live in exactly one component/convention, applied by the four Panel_Pages. To let the Panel_Pages actually use the extra width, the `AppLayout` content row's hard `max-w-6xl` cap is the one shared value that must be relaxed to a wider standardized max-width (e.g. `max-w-screen-2xl`), with the **narrower** width then re-imposed by the out-of-scope pages via their own (unchanged) content or by `PageContainer` defaulting non-Panel pages to the prior width. Concretely:

- Introduce `frontend/src/components/PageContainer.tsx`: a presentational wrapper that applies the standardized widened max-width tuned for the Desktop_Viewport plus consistent horizontal padding and vertical spacing rhythm. It renders a plain `<div>` with width/spacing utility classes only — no colors, type, radii, shadows, or tokens.
- Relax the `AppLayout` content row cap to the widened standardized max-width so Panel_Pages can fill the desktop width, and keep the header visually aligned.
- Apply `PageContainer` (widened variant) in the four Panel_Pages: `DashboardPage`, `PropertyDetailPage`, `AssetsPage`, `ReportsPage`.
- Keep out-of-scope pages at the prior narrower width (either they do not use `PageContainer`, or they use a `narrow` variant), so their effective content width is unchanged (Requirement 8.3).

This keeps the widened width defined once (DRY) and opted into only by Panel_Pages, with the out-of-scope width preserved.

#### The hard boundary (Requirement 10) — stated explicitly

The layout changes in this section **modify only**:

1. Page container **max-widths** (the `AppLayout` content-row cap and `PageContainer`),
2. responsive **breakpoints** (which width/column utilities apply at which viewport),
3. **whitespace/spacing** (gaps, padding, vertical rhythm).

The layout changes **must not** change any of the following, which are preserved exactly as-is (Requirements 10.2–10.6, Non-Goal 4):

- Monarch colors and color tokens (`bg-*`, `text-*`, `border-*` token values),
- typography and the type scale (font family, sizes, weights, `text-*` size utilities on content),
- component visual styling, border **radii**, and **shadows** (`rounded-*`, `shadow-*`),
- the existing design tokens,
- light/dark/system **theming** behavior.

How this is kept verifiable:

- No edits to the theme/token source (Tailwind theme config, token CSS variables, `ThemeProvider`), and no edits to `Card`/`Tile`/`Button` or other visual component styling. The change set is confined to `AppLayout.tsx`, the new `PageContainer.tsx`, and the four Panel_Page wrappers — touching only `max-w-*`, `w-*`, `gap-*`, `space-*`, `px-*`/`py-*`, and responsive-prefix utilities.
- A guard check (see Testing Strategy) asserts the diff introduces no new/changed color, typography, radius, shadow, or token classes on these pages and leaves the token/theme files unmodified.
- The existing theming tests and the Panel_Page axe/landmark/focus-order tests remain green.

## Components and Interfaces

### Section 1 — Dashboard depreciable-assets summary

**Backend — `DashboardService.asset_summary` (new method on the existing service in `backend/src/logstead/services/dashboard.py`).**

The existing `DashboardService` already composes `PropertyService` and `ReportingService` and is constructed by `_dashboard_service_or_503`. We add one read-only method and two small frozen dataclasses. To get the asset **count** and the authoritative depreciation total it needs the `DepreciationService` directly; it is already reachable because `ReportingService` holds one, but to keep the dependency explicit and avoid reaching through another service, the service gains an injected `DepreciationService`.

```python
@dataclass(frozen=True)
class PropertyAssetSummary:
    property_id: str
    property_name: str
    asset_count: int
    depreciation_total: Money  # two-decimal Decimal; rendered as a string by the router

@dataclass(frozen=True)
class AssetSummary:
    tax_year: int
    properties: tuple[PropertyAssetSummary, ...]
```

```python
class DashboardService:
    def __init__(self, properties, reports, depreciation) -> None: ...

    def asset_summary(self, tax_year: int | None = None) -> AssetSummary:
        year = _current_tax_year() if tax_year is None else tax_year
        rows: list[PropertyAssetSummary] = []
        for prop in self._properties.list():            # user-scoped (Req 3.4)
            assets = self._depreciation.list_assets(prop.id)   # count (Req 3.1)
            total = self._depreciation.property_depreciation_for_year(prop.id, year)  # authoritative (Req 6.1)
            rows.append(PropertyAssetSummary(prop.id, prop.name, len(assets), to_money(total)))
        return AssetSummary(tax_year=year, properties=tuple(rows))
```

Notes:
- `depreciation_total` is produced by the **same** `property_depreciation_for_year` method that feeds Schedule E Line 18, satisfying "single authoritative source" (Requirement 6.1) by construction.
- Empty portfolio returns `properties=()`; the endpoint still returns `200` with an empty list. The frontend's "no properties" empty state is driven separately by the existing dashboard summary (Requirement 5.1).
- `tax_year` defaults to the current year to match the existing dashboard default.

**Router — new route + handler in `backend/src/logstead/router/handler.py`.**

Follow the existing dashboard pattern exactly: a `GET`-only, user-scoped route whose handler reads `taxYear` from the query and calls the (lazily imported, 503-guarded) service.

```python
def _dashboard_asset_summary(wiring, user, params, body, query) -> dict[str, Any]:
    service = _dashboard_service_or_503(wiring, user)
    tax_year = _int_param(query.get("taxYear"), "taxYear") if query.get("taxYear") else None
    return _response(200, service.asset_summary(tax_year))
```

Route table entry, hung in the existing **Dashboard** group of `_ROUTES` (alongside `/dashboard` and `/dashboard/properties`):

```python
("GET", "/dashboard/assets", _dashboard_asset_summary, False),
```

`_dashboard_service_or_503` is updated to also construct the `DepreciationService` and pass it to `DashboardService`, matching the existing per-request constructor style (`_depreciation_service(wiring)`). The route is `GET`, so there is no write path (Requirement 3.2); scoping is inherited from the injected user-scoped `PropertyService`, consistent with every other route (Requirement 3.4).

**Frontend — new typed api function.**

Add to `frontend/src/api/assets.ts` (co-located with the per-property asset calls), following the injectable-`ApiClient` convention used across `api/`:

```ts
export interface PropertyAssetSummary {
  readonly property_id: string;
  readonly property_name: string;
  readonly asset_count: number;
  /** Fixed two-decimal money string, e.g. "1250.00". */
  readonly depreciation_total: string;
}
export interface AssetSummary {
  readonly tax_year: number;
  readonly properties: readonly PropertyAssetSummary[];
}
export function getAssetSummary(
  taxYear: number,
  client: ApiClient = apiClient,
): Promise<AssetSummary> {
  return client.get<AssetSummary>("/dashboard/assets", { query: { taxYear } });
}
```

Money stays a string; no `Number` coercion (consistent with `reports.ts` / `dashboard.ts`).

**Frontend — new tile on `DashboardPage.tsx`.**

Decision: add a **new tile**, `DepreciableAssetsTile`, rather than enhance the existing `PropertiesLaunchpadTile`. Rationale: the launchpad lists name + net and links to the property page; this summary lists count + depreciation and links to the property's **assets** page for the selected year. Mixing them would blur the "where do I enter depreciation" discoverability goal (Requirement 1 user story) and complicate the launchpad's net-focused contract. A dedicated tile keeps each concern single-purpose and matches the existing one-tile-per-concern dashboard structure. The tile:

- Is injected via a new optional prop `loadAssetSummary = getAssetSummary` on `DashboardPageProps` (mirrors the existing `loadCombined` / `loadAssets` injection for tests).
- Loads once per selected tax year through a single `getAssetSummary(taxYear)` read (Requirement 4.1) — not one `listAssets` per property. Reloads when the tax year changes (Requirement 1.4).
- Renders a semantic list inside a `Tile`; each row shows the property name, `asset_count`, `formatMoney(depreciation_total)` (Requirements 1.2, 1.3), and a link to `/properties/{propertyId}/assets`.
- Is rendered only when `summary.has_properties` is true (Requirement 5.1); the whole dashboard already short-circuits to `DashboardEmptyState` when there are no properties.
- Renders a per-property zero indication (count `0`, `formatMoney("0.00")`) for asset-free properties and still shows the link (Requirement 5.2) — this falls out of the endpoint returning `0` / `"0.00"`.
- Shows its own error region (`role="alert"`) and continues to render the rest of the dashboard when its fetch fails (Requirement 5.3), using the same local-state pattern as the existing `combined` tile (`loading | loaded | error`).

Accessibility (Requirement 7): each link is a real `<Link>` (anchor), keyboard-focusable in document order (7.1), carries the existing `focus-visible:outline ...` utility classes already used by every dashboard link for a visible focus ring (7.2), and has an accessible name that names the target property, e.g. `aria-label={`View assets for ${property_name}`}` (7.3). Markup reuses the `Tile` + `ul`/`li` + `dl` semantics already present on the dashboard (7.4). An axe pass over the dashboard with the tile present must report no new violations (7.5).

### Section 2 — Layout & spacing polish

`PageContainer` (new):

```tsx
// Width + spacing only. No color/type/token/radius/shadow classes.
export function PageContainer({
  width = "wide",          // "wide" = widened Panel_Page max-width; "narrow" = prior width
  children,
}: { width?: "wide" | "narrow"; children: React.ReactNode }) {
  const max = width === "wide" ? "max-w-screen-2xl" : "max-w-6xl";
  return <div className={`mx-auto w-full ${max} space-y-6`}>{children}</div>;
}
```

- Requirement 8.1/8.2: all four Panel_Pages wrap their content in `PageContainer` (default `wide`), giving a single standardized, widened, consistent max-width tuned for ~1440px.
- Requirement 9.1: at the desktop breakpoint the widened container is used rather than a narrow center column.
- Requirement 9.2/9.3: a consistent vertical spacing rhythm (`space-y-*`) and panel-group gaps provide breathing room and visually discernible grouping. The dashboard's existing grid `gap-*` and the per-property section spacing are tuned to one shared rhythm.
- Requirement 9.4: below the desktop breakpoint the layout remains fluid (`w-full` + responsive padding), preserving the current responsive behavior.
- Requirement 11: `PageContainer` is a non-semantic `<div>`; it introduces no landmark, no heading, and no focusable element, so existing landmarks, heading structure, and focus order are preserved (11.1, 11.2) and axe stays clean (11.3).

## Data Models

### Section 1 — Dashboard depreciable-assets summary

No persisted data model changes (Requirement 3.3, Non-Goal 7). Two new in-memory DTOs only: `PropertyAssetSummary` and `AssetSummary` (backend dataclasses; mirrored as frontend interfaces). All stored data is read from the existing `PROPERTY#{propertyId}` asset items and the existing GSI2 per-year schedule rows via the methods already defined on `DepreciationService`.

Wire shape of `GET /dashboard/assets?taxYear=2024`:

```json
{
  "tax_year": 2024,
  "properties": [
    { "property_id": "p1", "property_name": "Maple Duplex", "asset_count": 3, "depreciation_total": "4210.00" },
    { "property_id": "p2", "property_name": "Oak Cottage", "asset_count": 0, "depreciation_total": "0.00" }
  ]
}
```

### Data flow for the summary

1. `DashboardPage` renders for the selected `taxYear`; the `DepreciableAssetsTile` effect calls `loadAssetSummary(taxYear)` once.
2. The api function issues one `GET /dashboard/assets?taxYear=Y`.
3. The router resolves `current_user`, constructs the user-scoped services, and calls `DashboardService.asset_summary(Y)`.
4. The service lists the user's properties and, per property, reads `list_assets` (count) and `property_depreciation_for_year` (authoritative total) — the same source as Line 18.
5. The dataclass is serialized with money as two-decimal strings and returned as `200`.
6. The tile renders one row per property with count, formatted money, and an assets-page link, handling the empty/error states above.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Within this feature, universally quantified invariants apply to the Section 1 depreciation reconciliation (Requirement 6): they hold for all generated assets, properties, and tax years, and the backend already uses Hypothesis. The remaining Section 1 criteria are rendering/wiring/serialization contracts (example/edge/axe tests) and Section 2 is layout/CSS and diff-scope guarantees (structural/smoke/axe) — these are covered in the Testing Strategy rather than as universally quantified invariants.

After reflection, the per-property invariant (6.2) and the portfolio invariant (6.3) are distinct and non-redundant: 6.3 is not implied by 6.2 unless the combined report's total Line 18 equals the sum of per-property Line 18, which is itself the portfolio invariant being asserted. Both are kept.

### Property 1: Per-property depreciation reconciles with Schedule E Line 18

*For any* property owned by the user and *any* tax year, the `depreciation_total` the Asset_Summary_Endpoint returns for that property equals that property's Schedule E Line 18 depreciation total for that tax year (and equals the sum of that property's per-asset scheduled depreciation for the year, since Line 18 is derived from it).

**Validates: Requirements 6.1, 6.2**

### Property 2: Portfolio depreciation reconciles with the combined report

*For any* portfolio of the user's properties and *any* tax year, the sum across all properties of the endpoint's per-property `depreciation_total` equals the combined Schedule E report's total Line 18 depreciation for that tax year.

**Validates: Requirements 6.3**

---

## Error Handling

**Backend.** The endpoint is a straightforward read over the user's own properties, so it returns `200` with the (possibly empty) list in the normal case. A missing/invalid identity yields `401` via the router's existing `current_user` handling. A malformed `taxYear` yields `400` via `_int_param`. If the dashboard service module is not importable, the existing `_dashboard_service_or_503` surfaces a clean `503`. No new error kinds are introduced.

**Frontend.** The `DepreciableAssetsTile` owns its own fetch state (`loading | loaded | error`). On rejection it renders an inline `role="alert"` error for the tile and leaves every other tile intact (Requirement 5.3), mirroring the existing combined-report tile. Aborted fetches (tax-year change / unmount) are ignored via an `AbortController`/active flag, matching the existing effects in `DashboardPage`.

**Section 2.** Pure layout; no runtime error paths. The risk is a regression to accessibility or visual language, which the boundary guard and axe/theming regression tests catch.

## Testing Strategy

Dual approach: example/edge/integration tests for concrete behavior and serialization; property-based tests (Hypothesis) for the universal reconciliation invariants; structural/axe checks for layout and accessibility.

### Backend (Section 1)

- **Endpoint shape (Req 3.1):** moto-backed handler/service test with seeded properties and assets; assert one row per property with the expected `asset_count` and `depreciation_total`.
- **User-scoping (Req 3.4):** two users with disjoint properties; assert user A's response excludes user B's properties.
- **Money-as-string (Req 3.5):** assert each `depreciation_total` matches `^-?\d+\.\d{2}$` and flows through the router's `_to_jsonable`.
- **Empty states (Req 5.1/5.2):** empty portfolio returns `properties: []`; an asset-free property returns `asset_count: 0` and `"0.00"`.
- **Read-only / no-schema (Req 3.2, 3.3, 6.1 smoke):** assert the route is registered `GET` only and the service composes `list_assets` + `property_depreciation_for_year` (the same method `ReportingService` uses for Line 18); no new item type is written.
- **Property-based reconciliation (Hypothesis), Requirement 6 — the two correctness properties:**
  - *Property 1* — generate properties with randomized assets (cost basis, placed-in-service date, recovery period) and a random tax year; assert the endpoint's per-property `depreciation_total` equals that property's Schedule E report Line 18 for the year. Minimum 100 iterations. Tag: **Feature: dashboard-assets-and-layout-polish, Property 1: Per-property depreciation reconciles with Schedule E Line 18**.
  - *Property 2* — generate a portfolio and a random tax year; assert the sum of the endpoint's per-property `depreciation_total` equals the combined report's summed Line 18. Minimum 100 iterations. Tag: **Feature: dashboard-assets-and-layout-polish, Property 2: Portfolio depreciation reconciles with the combined report**.

### Frontend (Section 1)

RTL + vitest with the injectable api (`loadAssetSummary`), no network:

- Renders one summary row per property with count + `formatMoney` total and an assets-page link (Req 1.1, 1.2, 1.3).
- Changing the tax year refetches with the new year and updates totals (Req 1.4); assert the loader is called with the new `taxYear`.
- Single aggregation read: the tile calls `getAssetSummary` once and does not fan out to per-property `listAssets` for the summary (Req 4.1).
- Empty/edge/error states: no-properties shows the existing empty state and no summary (Req 5.1); asset-free property shows zero count/total and still links (Req 5.2); a rejected fetch shows the tile error and leaves other tiles rendered (Req 5.3).
- Accessibility: links are focusable anchors in document order with focus-visible classes and accessible names identifying the property (Req 7.1–7.4); `axe(container)` over the dashboard with the tile present reports no new violations (Req 7.5), following the existing `DashboardPage.test.tsx` axe pattern (`color-contrast` disabled, as elsewhere).

### Section 2 — layout boundary verification

- **Container width applied only to Panel_Pages (Req 8.1–8.3):** structural assertion that each Panel_Page wraps its content in the widened `PageContainer` width class, and that out-of-scope pages do **not** adopt the widened width (prior width preserved).
- **Spacing/breakpoints (Req 9.1–9.4):** structural assertions on the shared spacing-rhythm and responsive breakpoint utility classes; the responsive layout below desktop remains usable. (Pixel-exact spacing judgement is a documented manual visual check at ~1440px.)
- **Hard boundary guard (Req 10.1–10.6):** a diff-scope check asserting the change set touches only width/spacing/breakpoint utilities on `AppLayout` + `PageContainer` + the four Panel_Pages, and leaves the theme/token files, color/typography/radius/shadow definitions, and `ThemeProvider` **unmodified**. The existing theming (light/dark/system) tests remain green.
- **Accessibility preserved (Req 11.1–11.3):** the existing landmark/heading-structure, keyboard focus-order, and `axe` tests for the Panel_Pages (e.g. `AppLayout.test.tsx`, `DashboardPage.test.tsx`, `ReportsPage.test.tsx`, `PropertyDetailPage.test.tsx`) remain green after the layout change.

### Property test configuration

The backend already depends on Hypothesis. Each property test runs a minimum of 100 iterations, is implemented as a single property-based test per property, and carries the `Feature: dashboard-assets-and-layout-polish, Property N: ...` tag comment referencing the design property above. The reconciliation tests run against moto, so 100+ iterations are low-cost.
