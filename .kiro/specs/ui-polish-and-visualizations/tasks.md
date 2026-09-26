# Implementation Plan: UI Polish and Visualizations

## Overview

This plan turns the approved design into an incremental, dependency-ordered build. It follows the design's three stages — **foundation** (`lib/` helpers + `components/ui` primitives), **wayfinding & polish** (breadcrumbs, raw-id removal, delete confirmations, feedback, responsive tables, reports), and **charts** (accessibility-first, theme-aware, lazy-loaded). Each step is small enough to keep `make test-frontend` and `npm run build` green before the next begins, so nothing is left orphaned.

The stack is fixed by the design: React 19 + Vite 6 + TypeScript + Tailwind 3 + Radix UI, tested with vitest + React Testing Library + `@testing-library/user-event` + `vitest-axe`, plus `fast-check` (new dev dependency) for the eight correctness properties and `clsx` + `recharts` (new dependencies) for class composition and charts.

Conventions used below:
- Test-related sub-tasks are marked with `*` and MAY be skipped for a faster MVP; core implementation sub-tasks are never optional.
- Property tests reference the design's numbered Correctness Properties and are tagged `// Feature: ui-polish-and-visualizations, Property N: <text>` with `{ numRuns: 100 }`.
- "Verify green" means run `make test-frontend` and, where bundle behavior matters, `npm run build`.

## Tasks

- [x] 1. Foundation: class-composition and money helpers
  - [x] 1.1 Add `clsx` dependency and create `lib/cn.ts`
    - Add `clsx` to `frontend/package.json` dependencies (pinned version).
    - Create `frontend/src/lib/cn.ts` exporting `cn(...inputs: ClassValue[])` as a thin `clsx` wrapper.
    - _Requirements: 1.2, 1.6_

  - [ ]* 1.2 Write unit tests for `cn`
    - Cover conditional/falsy entries and array/object inputs merge correctly.
    - _Requirements: 1.2_

  - [x] 1.3 Create canonical `lib/money.ts`
    - Merge the three existing formatters (`components/transactions/money.ts`, `components/dashboard/money.ts`, and the inline formatter in `components/properties/PropertyDetailsView.tsx`) into one module.
    - Export `formatMoney`, `isLoss`, `isPositiveAmount`, `toMoneyString`, `sumMoney`, `toCents`, `centsToMoney`.
    - Use `en-US` USD locale; pass through non-numeric input unchanged; return `""` for empty/undefined; `toCents` returns `0` for unrecognized input. No floating-point arithmetic.
    - _Requirements: 7.1, 7.4, 13.1, 13.3_

  - [ ]* 1.4 Consolidate and write unit tests in `lib/money.test.ts`
    - Move/merge the existing `transactions/money` and `dashboard/money` unit tests here; add cases for the merged behavior (empty, non-numeric passthrough, negative, large amounts).
    - _Requirements: 7.1, 7.4_

  - [ ]* 1.5 Write property test: money formatting preserves exact value
    - **Property 1: Money formatting preserves exact value**
    - Custom `fast-check` arbitrary for `(-)?<digits>.<2 digits>`; assert formatted dollar-and-cent digits equal the input with no rounding.
    - **Validates: Requirements 7.1, 7.4, 10.4**

  - [ ]* 1.6 Write property test: money ↔ integer-cents round-trip
    - **Property 2: Money ↔ integer-cents round-trip (no floating point)**
    - Assert `toCents(s)` is an integer and `centsToMoney(toCents(s))` equals the normalized form of `s`.
    - **Validates: Requirements 13.1, 13.2, 13.3**

  - [x] 1.7 Re-point money imports and delete old modules
    - Re-point all imports (`components/transactions/*`, `components/dashboard/*`, `components/reports/*`, `PropertyDetailsView`, `DashboardPage`, `PropertyDetailPage`) to `../../lib/money`.
    - Delete `components/transactions/money.ts`, `components/dashboard/money.ts`, and the inline formatter in `PropertyDetailsView`.
    - _Requirements: 7.1, 7.4_

- [x] 2. Checkpoint — foundation helpers green
  - Ensure all tests pass and `npm run build` succeeds after the money consolidation. Ask the user if questions arise.

- [x] 3. Shared UI primitives in `components/ui/`
  - [x] 3.1 Add focus-ring constant, `Button`, and `Input` primitives
    - Export the single canonical focus-ring class fragment as a constant reused by every primitive.
    - `Button` supports `variant` (`primary`/`secondary`/`danger`), `size`, `asChild` (via `@radix-ui/react-slot`); token-only colors.
    - `Input` supports `invalid` (sets `aria-invalid` + danger ring); token-only styling + focus ring.
    - _Requirements: 1.1, 1.2, 1.3, 1.6, 8.5_

  - [ ]* 3.2 Write unit + axe tests for `Button` and `Input`
    - Variant-class rendering for `Button`; base classes + `aria-invalid` for `Input`; `toHaveNoViolations` for both.
    - _Requirements: 1.1, 1.3, 1.2_

  - [x] 3.3 Add `Card` + `Tile` and `Select` primitives
    - `Card` = elevation surface (`shadow-card`, token border/surface); `Tile` composes `Card` with a labelled heading (`title`, `headingId`).
    - `Select` = styled native `<select>` with `invalid`; token-only styling + focus ring.
    - _Requirements: 1.3, 8.1, 8.4, 8.5_

  - [ ]* 3.4 Write unit + axe tests for `Card`/`Tile` and `Select`
    - Base-class and heading rendering; `toHaveNoViolations`.
    - _Requirements: 1.3_

  - [x] 3.5 Add `ConfirmDialog` primitive
    - Wrap `@radix-ui/react-dialog`; token-derived overlay + shared card elevation; confirm = `Button variant="danger"`, cancel = `Button variant="secondary"`; `pending` disables confirm.
    - Props: `open`, `onOpenChange`, `title`, `description`, `confirmLabel`, `cancelLabel`, `destructive`, `onConfirm`, `pending`.
    - _Requirements: 1.4, 4.1, 4.5, 8.3, 8.5_

  - [ ]* 3.6 Write unit + axe tests for `ConfirmDialog`
    - Confirm calls `onConfirm`; cancel, Esc, and backdrop do NOT; `pending` disables confirm; `toHaveNoViolations`.
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 3.7 Add `ResponsiveTable` and `StateBlock` primitives
    - `ResponsiveTable`: `caption`, `columns`, `rows`; `<table>` in `overflow-x-auto` at ≥ `sm`, card-per-row layout at < `sm`.
    - `StateBlock`: `kind` (`loading`/`empty`), `title`, `description`, optional `action`; loading uses `role="status"`.
    - _Requirements: 1.3, 6.1, 6.2, 9.1, 9.2_

  - [ ]* 3.8 Write unit + axe tests for `ResponsiveTable` and `StateBlock`
    - Scroll wrapper present; card layout under mocked narrow `matchMedia`; loading `role="status"`; `toHaveNoViolations`.
    - _Requirements: 6.1, 6.2, 9.1, 9.2_

  - [x] 3.9 Add `toast/ToastProvider` + `useToast` and mount in `main.tsx`
    - Context + `@radix-ui/react-toast` viewport; `notify({ variant, title, description? })`; success → success token, error → danger token.
    - Mount `ToastProvider` once in `main.tsx` inside `ThemeProvider`, wrapping `App`.
    - _Requirements: 1.4, 5.5_

  - [ ]* 3.10 Write unit + axe tests for toast
    - `useToast().notify` emits success and error toasts into the live region; `toHaveNoViolations`.
    - _Requirements: 5.5_

  - [x] 3.11 Create `components/ui/index.ts` barrel export
    - Re-export all primitives (Button, Input, Card, Tile, Select, ConfirmDialog, ResponsiveTable, StateBlock, toast APIs) plus the focus-ring constant.
    - _Requirements: 1.1, 1.3, 1.4_

  - [ ]* 3.12 Write property test: primitives are focus-ringed and token-colored
    - **Property 5: Every focusable primitive is consistently focus-ringed and token-colored**
    - Table-driven `fast-check` over the barrel export; assert the canonical focus-ring fragment present and no hardcoded hex/`rgb(...)` color classes.
    - **Validates: Requirements 1.2, 1.6, 8.1**

- [x] 4. Checkpoint — primitives green
  - Ensure all tests pass and `npm run build` succeeds. Ask the user if questions arise.

- [x] 5. Migrate call sites to primitives (Part A polish)
  - [x] 5.1 Replace copy-pasted button/focus-ring strings with `Button`
    - Migrate accent `Link`s in `PropertyList` and dashboard quicklinks to `<Button asChild variant="primary">`; replace one-off button/focus-ring class strings across pages.
    - _Requirements: 1.1, 1.2, 1.5_

  - [x] 5.2 Unify tax-year selectors and Cancel/Delete styles
    - Replace `TaxYearSelector`, `TaxYearFilter`, and the inline `<select>` in the combined report page with the shared `Select`; standardize Cancel/Delete button pairings via `Button`.
    - _Requirements: 8.5_

  - [x] 5.3 Apply `Card`/`Tile` and dedupe local Tile definitions
    - Replace the two identical local `Tile` definitions in `DashboardPage` and `PropertyDetailPage` with the shared `Tile`; migrate `ReportView` section cards and `PropertyList` cards to shared `Card`.
    - _Requirements: 1.3, 8.4_

  - [x] 5.4 Fix token/style drift
    - `ProfilePage` separators → semantic border token (replace `divide-slate-200`); dialog overlay `bg-slate-900/40` + `shadow-xl` → token overlay + shared elevation; `PortfolioSummary` → shared `shadow-card` elevation.
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 5.5 Route `AssetList` cost basis and `ScheduleTable` amounts through `formatMoney`
    - Replace raw `Money_String` rendering with `formatMoney`; preserve `tabular-nums` alignment.
    - _Requirements: 7.2, 7.3, 7.5_

- [x] 6. Checkpoint — Part A style migration green
  - Ensure all tests pass and `npm run build` succeeds. Ask the user if questions arise.

- [x] 7. Wayfinding (Req 2, 3)
  - [x] 7.1 Add `PropertyLayout` layout route + property context
    - Add layout route at `properties/:propertyId` in `App.tsx` wrapping `index` (PropertyDetailPage), `transactions`, `assets`, `reports`.
    - Fetch the property once via `getProperty` (injectable loader pattern); provide `{ propertyId, status, property }` via `<Outlet context>`; export `usePropertyContext()`.
    - Handle loading (`"Loading property…"`) and error (neutral `"Property"` fallback) without leaking the raw id.
    - _Requirements: 2.1, 2.4, 3.1_

  - [ ]* 7.2 Write unit tests for `PropertyLayout` load/error states
    - Loading and error resolve heading/breadcrumb without exposing the raw id.
    - _Requirements: 2.1, 3.1_

  - [x] 7.3 Add `Breadcrumb` primitive
    - `nav[aria-label="Breadcrumb"] > ol`; `items: { label, to? }[]`; last crumb has no link.
    - _Requirements: 2.2, 2.3_

  - [ ]* 7.4 Write unit + axe tests for `Breadcrumb`
    - Renders `Properties > {name} > {sub-page}`; ancestor link targets `/properties`; `toHaveNoViolations`.
    - _Requirements: 2.2, 2.3_

  - [x] 7.5 Update `PropertySection` to show name + breadcrumb; remove `TransactionsPage` inline nav
    - `PropertySection` accepts resolved property name, renders `Breadcrumb`, replaces `Property: {propertyId}` with the name.
    - Remove `TransactionsPage`'s inline duplicated sub-nav so it renders `PropertySection` like the other sub-pages.
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 3.1_

  - [x] 7.6 Remove Cognito `sub` from `ProfilePage`
    - Drop the "User ID"/`sub` row; present only human-readable account info; keep the "managed by Cognito" note.
    - _Requirements: 3.2_

  - [x] 7.7 Replace raw `category_id` fallback in `TransactionList`
    - Show the mapped category label when present; otherwise a human-readable fallback (e.g. "Uncategorized"); never render the raw `category_id`.
    - _Requirements: 3.3, 3.4_

  - [ ]* 7.8 Write property tests for wayfinding raw-id removal
    - **Property 3: Sub-pages present the property name, never the raw identifier**
    - **Validates: Requirements 2.1, 3.1**
    - **Property 4: Transaction rows never expose the raw category id**
    - **Validates: Requirements 3.3, 3.4**

- [x] 8. Checkpoint — wayfinding green
  - Ensure all tests pass and `npm run build` succeeds. Ask the user if questions arise.

- [x] 9. Destructive-delete confirmations + feedback (Req 4, 5)
  - [x] 9.1 Wire property and transaction deletes through `ConfirmDialog` + toasts
    - Gate property delete (`PropertyList`, preserving the 409-conflict message) and transaction delete (`TransactionsPage`) via `ConfirmDialog`; success → success toast + refresh, failure → error toast.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.4_

  - [x] 9.2 Wire asset and receipt deletes through `ConfirmDialog` + toasts
    - Gate asset delete (`AssetsPage`) and receipt delete via `ConfirmDialog`; success/error toasts.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.2, 5.3, 5.4_

  - [x] 9.3 Emit success/error toasts on create/update
    - Transaction and asset create/update, and receipt upload emit success toasts; failures emit error toasts.
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 9.4 Write unit tests for delete confirmations and feedback wiring
    - Confirm performs delete + success toast; cancel leaves record unchanged; failures emit error toast for transaction/asset/receipt/property.
    - _Requirements: 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 5.4_

- [x] 10. Responsive tables (Req 6)
  - [x] 10.1 Apply `ResponsiveTable` to `TransactionList`, `AssetList`, `PropertyBreakdownTable`
    - Delegate layout to `ResponsiveTable` while keeping domain formatting and action buttons.
    - _Requirements: 6.1, 6.2, 6.3_

  - [ ]* 10.2 Write unit tests for responsive table application
    - Under mocked narrow `matchMedia`, the three tables render the card layout; ≥ `sm` renders the scroll-wrapped table.
    - _Requirements: 6.1, 6.2, 6.3_

- [x] 11. Richer empty/loading states (Req 9)
  - [x] 11.1 Apply `StateBlock` on transactions, assets, and reports sub-pages
    - Replace bare `Loading…` / `No … yet` with `StateBlock` loading + empty states offering the next action.
    - _Requirements: 9.1, 9.2, 9.3_

  - [ ]* 11.2 Write unit tests for empty/loading states
    - Loading state present while fetching; empty state offers next action on the three sub-pages.
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 12. Checkpoint — Part A complete
  - Ensure all tests pass and `npm run build` succeeds. Ask the user if questions arise.

- [x] 13. Reports as a hand-off document (Req 10, 16.2 surface)
  - [x] 13.1 Polish per-property `ReportView` document treatment
    - Migrate section cards to shared `Card`; route all amounts through `formatMoney`; keep clear income/expense/depreciation grouping and emphasized section totals + net.
    - _Requirements: 10.1, 10.2, 10.4, 7.3_

  - [x] 13.2 Add print styling for reports
    - Tailwind `print:` variants + a small `@media print` block in `index.css`: `print:hidden` on header/aside/nav/download buttons/charts, white bg + black text, remove card shadows/borders, `break-inside-avoid` on sections.
    - _Requirements: 10.3_

  - [x] 13.3 Add routed combined report page + nav entry
    - Create `CombinedReportsPage` at route `/reports` (avoid colliding with the per-property report page); add `{ to: "/reports", label: "Reports" }` to `PRIMARY_NAV` in `components/navConfig.ts`.
    - Point the dashboard combined summary tile's "View combined report" link at `/reports`.
    - _Requirements: 10.1, 16.2_

  - [x] 13.4 Add `CombinedReportView` over existing `/reports/combined` data
    - Render per-property `ReportView`s + portfolio totals from `getCombinedReport` (no new endpoint); apply document grouping, emphasized totals, and the same print styling.
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 16.2_

  - [ ]* 13.5 Write unit tests for reports document + print behavior
    - Section grouping and net emphasis present; app chrome/charts carry `print:hidden`; combined page composes per-property views over combined data.
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 14. Checkpoint — reports green
  - Ensure all tests pass and `npm run build` succeeds. Ask the user if questions arise.

- [x] 15. Chart foundation (Req 11–15)
  - [x] 15.1 Add `recharts` dependency and `components/charts/chartColors.ts`
    - Add `recharts` to dependencies; add `fast-check` dev dependency if not already present.
    - `useChartColors()` returns `rgb(var(--color-...))` strings (accent/success/danger/fg/fgMuted/grid), gridline from `--color-border`; subscribes to `useTheme()` so charts recolor on toggle.
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [ ]* 15.2 Write property test: chart colors are token references
    - **Property 6: Chart colors are always token references**
    - Assert every `useChartColors` value matches `rgb(var(--color-...))` and grid resolves to `rgb(var(--color-border))`.
    - **Validates: Requirements 11.2, 11.4**

  - [x] 15.3 Create `components/charts/prepare.ts`
    - `Money_String → Integer_Cents` datum builders: `CategoryDatum`, `IncomeExpenseNetDatum`, `PropertyNetDatum`, `DepreciationDatum`; expense-by-category sorted desc by cents; uses `toCents`, no floats.
    - _Requirements: 13.1, 13.3, 16.3_

  - [ ]* 15.4 Write property tests for `prepare.ts`
    - **Property 2 (reuse):** money↔cents round-trip through prep labels via `formatMoney(centsToMoney(cents))`.
    - **Property 8: Expense-by-category data is ranked by descending amount**
    - **Validates: Requirements 16.3** (and 13.1, 13.2, 13.3)

  - [x] 15.5 Add `ResizeObserver` stub to `src/test/setup.ts`
    - Register a `ResizeObserver` mock so Recharts' responsive container does not throw in jsdom.
    - _Requirements: 15.1_

  - [x] 15.6 Create `ChartCard` wrapper and `ChartPlaceholder`
    - `ChartCard`: `title`, `ariaLabel`, `chart`, `dataTable`, `height`; renders `role="img"` + non-empty `aria-label` on the chart region, always-present data table (below or via show-data toggle), keyboard tooltips via Recharts `accessibilityLayer`, `<ResponsiveContainer>` in a fixed-height `Card`, chart hidden + table shown at < `sm`; calm treatment (no 3D/gradient, minimal animation).
    - `ChartPlaceholder`: fixed-height `role="status"` "Loading chart…" fallback.
    - _Requirements: 11.5, 11.6, 12.1, 12.2, 12.3, 12.4, 15.1, 15.2, 15.3, 14.3_

  - [ ]* 15.7 Write property + axe/contract tests for `ChartCard`
    - **Property 7: Every chart carries its accessibility contract and its data table**
    - Assert `role="img"` + non-empty `aria-label`, one data-table row per datum present regardless of viewport; `toHaveNoViolations`; render with explicit width/height and mocked `ResizeObserver`.
    - **Validates: Requirements 12.1, 12.2, 12.4, 19.3**

  - [x] 15.8 Wire `React.lazy` + `Suspense` chart-loading with error boundary
    - Establish the lazy import boundary and `Suspense` fallback (`ChartPlaceholder`); add an error boundary around the chart region that falls back to the data table + "chart unavailable" note.
    - Optionally note `vite.config.ts` `manualChunks: { charts: ["recharts"] }` for a stable chunk name.
    - _Requirements: 14.1, 14.2, 14.3_

- [x] 16. Checkpoint — chart foundation green + lazy chunk verified
  - Ensure all tests pass; run `npm run build` and confirm `recharts` lands in a separate async chunk, NOT the initial bundle. Ask the user if questions arise.

- [x] 17. Phase 1 charts (Req 16, 17, 18)
  - [x] 17.1 Implement `ExpenseByCategoryChart` (ranked desc, horizontal bars)
    - Consume `CategoryDatum[]` from `prepare.ts`; render through `ChartCard` with always-present data table; lazy-loaded.
    - Place on per-property `ReportView` (below expense section) and on the combined `CombinedReportView`.
    - _Requirements: 16.1, 16.2, 16.3, 16.4_

  - [ ]* 17.2 Write unit test for expense-by-category chart placement
    - One primary `role="img"` chart on the report; data table present; bars ordered desc (asserted via prep in 15.4).
    - _Requirements: 16.1, 16.2, 16.3_

  - [x] 17.3 Implement `IncomeExpenseNetChart` (compact bars)
    - Consume `IncomeExpenseNetDatum[]`; render through `ChartCard`; lazy-loaded.
    - Place on `DashboardPage` `PortfolioSnapshotTile` (portfolio) and `PropertyDetailPage` `IncomeExpenseTile` (per property).
    - _Requirements: 17.1, 17.2, 17.3_

  - [x] 17.4 Implement `NetByPropertyChart` (ranked horizontal bars)
    - Consume `PropertyNetDatum[]` from `DashboardSummary.properties[].net`; render through `ChartCard` in its own dashboard tile; lazy-loaded.
    - _Requirements: 18.1, 18.2_

  - [ ]* 17.5 Write unit tests for dashboard/per-property chart wiring
    - Portfolio snapshot tile shows income/expenses/net chart; dashboard shows net-by-property chart in its own tile (Req 11.6 guideline: multiple charts allowed, each primary within its tile); per-property tile shows its chart; each keeps its data table; theme toggle re-renders with variable color strings; narrow-viewport falls back to table.
    - _Requirements: 17.1, 17.2, 18.1, 11.3, 11.6, 15.3_

- [x] 18. Checkpoint — Phase 1 charts green + bundle unchanged
  - Ensure all tests pass; run `npm run build` and confirm the initial bundle is not regressed (charts remain lazy chunks). Ask the user if questions arise.

- [x] 19. Phase 2 chart — asset depreciation schedule (Req 19)
  - [x] 19.1 Implement `DepreciationChart` (line/area)
    - Consume `DepreciationDatum[]` from `getSchedule(...)` `ScheduleRow[]`; render through `ChartCard` alongside `ScheduleTable` in the `AssetsPage` expanded schedule section; lazy-loaded.
    - _Requirements: 19.1, 19.2, 19.3_

  - [ ]* 19.2 Write unit test for depreciation chart
    - One primary `role="img"` chart in the schedule section; data table (schedule) present alongside; contract via `ChartCard`.
    - _Requirements: 19.1, 19.3_

- [x] 20. Final checkpoint — full suite green + lazy splitting confirmed
  - Ensure all tests pass; run `npm run build` and verify chart chunks are split out of the initial paint and the initial bundle is not regressed. Ask the user if questions arise.

- [ ]* 21. Phase 3 (OPTIONAL / STRETCH) — Year-over-year portfolio net trend (Req 20)
  - **Not built in this effort.** Documentation-only optional task capturing the approach:
    - Client-side stitching: reuse the existing per-year fetch pattern (`getDashboard(year)` / `getCombinedReport(year)`) behind a feature flag to assemble `[{ year, netCents }]` with no backend change.
    - Future backend dependency (out of current no-new-endpoint scope): `GET /dashboard/trend?from=<year>&to=<year>` returning `[{ tax_year, net }]` money strings for efficient single-request trends.
    - If implemented, reuse `ChartCard` + a line/area chart with an always-present data table.
    - _Requirements: 20.1, 20.2, 20.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; core implementation tasks are never marked optional.
- Each task references specific requirement sub-clauses for traceability.
- Checkpoints ensure incremental validation — run `make test-frontend` and, where bundle behavior matters, `npm run build` before moving on.
- Property tests (Properties 1–8) validate the pure, input-varying logic (money, chart prep, primitive/chart contracts) with `fast-check` at `{ numRuns: 100 }`, tagged `// Feature: ui-polish-and-visualizations, Property N: <text>`.
- Unit + `vitest-axe` tests validate specific examples, wiring, accessibility, and responsive/print behavior.
- Charts are lazy-loaded so `recharts` never enters the initial paint; the final chart tasks must confirm chunk splitting so the initial bundle is not regressed (Req 14).
- Task 21 (Phase 3 trend) is optional/stretch and documents a potential future backend dependency; it is not implemented here.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5", "1.6"] },
    { "id": 3, "tasks": ["1.7"] },
    { "id": 4, "tasks": ["3.1", "3.3", "3.7"] },
    { "id": 5, "tasks": ["3.2", "3.4", "3.5", "3.8"] },
    { "id": 6, "tasks": ["3.6", "3.9"] },
    { "id": 7, "tasks": ["3.10", "3.11"] },
    { "id": 8, "tasks": ["3.12", "5.1", "5.2", "5.3", "5.4", "5.5"] },
    { "id": 9, "tasks": ["7.1", "7.3", "7.6", "7.7"] },
    { "id": 10, "tasks": ["7.2", "7.4", "7.5", "7.8"] },
    { "id": 11, "tasks": ["9.1", "9.2", "9.3", "10.1", "11.1"] },
    { "id": 12, "tasks": ["9.4", "10.2", "11.2"] },
    { "id": 13, "tasks": ["13.1", "13.2", "13.3"] },
    { "id": 14, "tasks": ["13.4", "13.5"] },
    { "id": 15, "tasks": ["15.1", "15.3", "15.5"] },
    { "id": 16, "tasks": ["15.2", "15.4", "15.6"] },
    { "id": 17, "tasks": ["15.7", "15.8"] },
    { "id": 18, "tasks": ["17.1", "17.3", "17.4"] },
    { "id": 19, "tasks": ["17.2", "17.5", "19.1"] },
    { "id": 20, "tasks": ["19.2", "21"] }
  ]
}
```
