# Developer Guide

This guide covers setting up a local environment, project conventions, and the
day-to-day workflow for the backend and frontend.

## Prerequisites

- **Python 3.12** (the Lambda runtime target)
- **Node 18+** (Node 20+ recommended) and **npm**
- No AWS account is required for local development or the test suites; external
  services and AWS resources are faked in tests.

> Tip: a top-level `Makefile` wraps the common commands below. Run `make help`
> for the full list - e.g. `make install`, `make test`, `make dev`, `make deploy`.

## Backend

The backend is a Python package at `backend/src/logstead/`, packaged with
`pyproject.toml`.

### Setup

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # installs runtime + dev dependencies
```

Runtime dependencies: `boto3`, `pdfplumber`, `pypdf`, `reportlab` (pinned in
`requirements.txt`; see [Dependency policy](dependency-policy.md)).
Dev dependencies: `pytest`, `hypothesis`, `moto`, `pytest-xdist`, `PyYAML`.

### Running tests

```bash
.venv/bin/python -m pytest -q -n auto   # parallel, via pytest-xdist
```

Tests are organized under `backend/tests/` into `services/`, `adapters/`,
`repository/`, `router/`, `integration/`, and `util/`. See
[Testing guide](testing.md) for the different test styles.

### Configuration (environment variables)

The Lambda reads its configuration from the environment:

| Variable | Purpose |
| --- | --- |
| `TABLE_NAME` | DynamoDB single-table name |
| `FILES_BUCKET` | S3 bucket for photos, receipts, PDFs, exports |
| `AWS_REGION` | AWS region |
| `PACKAGE_WORKER_FUNCTION` | Name of the package worker Lambda (`PackageWorkerFunction`). The API starts it with an asynchronous invoke. `infra/template.yaml` sets it on `ApiFunction`. When unset (local runs), `POST /accountant-packages` returns 503 and creates no job; tests inject a fake invoker through `configure(package_invoker=...)`, and you can call `logstead.worker.package_worker.handler` directly |
| `RENTCAST_API_KEY` | RentCast enrichment API key, read directly (optional; used for local runs and tests) |
| `RENTCAST_API_KEY_PARAM` | Name of an SSM SecureString holding the RentCast key (how deploys pass it; the Lambda reads + decrypts at runtime). `RENTCAST_API_KEY` wins if both are set |

Address autocomplete uses **Amazon Location Service** (`geo-places`) via the
Lambda's IAM role - there is no autocomplete API key.

Tests do not require these; the router exposes `configure(...)` and
`reset_wiring()` to inject fakes for the repository, file store, and adapters.

## Frontend

The frontend is a React + Vite + TypeScript SPA at `frontend/`.

### Setup and workflow

```bash
cd frontend
npm ci             # lock-exact install (what deploys use)
npm run dev        # local dev server
npm test           # vitest run
npm run build      # tsc -b + vite build (must exit 0)
npm run lint       # ESLint
npm run typecheck  # tsc --noEmit
npm run e2e        # Playwright (npm run e2e:install once first)
```

The `build` output goes to `dist/`; remove it after a verification build if you
do not intend to deploy.

### Environment

> Deploying: the S3 files bucket CORS allows only one origin and no `*`. See
> "Files-bucket CORS" in [deployment.md](deployment.md) for setting
> `AllowedSpaOrigin` after the first deploy. Local dev (`http://localhost:5173`) works by default.

Copy `frontend/.env.example` to `frontend/.env` and set:

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Base URL of the API Gateway HTTP API |
| `VITE_COGNITO_DOMAIN` | Cognito Hosted UI domain |
| `VITE_COGNITO_CLIENT_ID` | Cognito app client ID |
| `VITE_COGNITO_REDIRECT_URI` | OAuth redirect URI |
| `VITE_COGNITO_SCOPES` | Requested OAuth scopes |
| `VITE_COGNITO_LOGOUT_URI` | Post-logout redirect URI |

### Frontend structure

```
src/
  api/          Typed API client calls to the backend
  auth/         Cognito Hosted UI / OAuth PKCE integration
  components/   Feature components: accountant-package, activity, assets,
                businesses, carryforward, charts, dashboard, imports, itemized,
                loans, palette, photos, properties, property-detail, reports,
                schedule-e-extraction, schedule-e-import, search, shortcuts,
                transactions, year-end-checklist, ui (shared primitives), plus
                AppLayout, MainNav, PropertySection, PropertySectionTabs,
                navConfig, ProfileMenu, ThemeToggle
  theme/        ThemeProvider (light/dark/system) and theme context
  pages/        Routed page views (incl. PropertyDetailPage, ProfilePage)
  data/         Bundled fixtures (e.g. sample-backup.json for "Load sample data")
  lib/          Shared helpers
  test/         Test setup and utilities
```

Notable frontend features:

- **Dark mode + theming.** A semantic color-token system (CSS variables plus
  Tailwind `darkMode: "class"`) with a `ThemeProvider` in `theme/`. A theme
  toggle (`ThemeToggle`, Light/Dark/System) defaults to System and persists an
  explicit choice to localStorage.
- **Profile menu.** A top-right `ProfileMenu` shows the signed-in email, links
  to the Profile & settings page (`/profile`, `ProfilePage`), hosts the theme
  toggle, and offers Sign out.
- **Property detail page.** `/properties/:propertyId` (`PropertyDetailPage`)
  shows the stored enrichment details for a property.
- **Backup & restore.** A section on the Profile & settings page (`/profile`)
  offers four flows: download a JSON backup, restore from a backup file, clear
  all data, and load sample data. The bundled sample fixture lives at
  `frontend/src/data/sample-backup.json`.
- **Imports section.** The **Import** nav entry opens `/imports`, rendered by
  `ImportsLayout` (`pages/`), which owns the page heading and an
  `ImportSectionTabs` tab bar. The tabs come from `IMPORT_NAV` in `navConfig`:
  "Enter manually" (`/imports/schedule-e`) and "Upload PDF"
  (`/imports/schedule-e/extract`), each rendered through the layout's `Outlet`.
- **RecordModal pattern.** Create/edit record forms open in a `RecordModal`
  (`components/ui/`) driven by the `useRecordModal` hook, which tracks the
  open/create/edit state for a list of records. Forms use `useDismissibleErrors`
  (`lib/`) so server field errors can be dismissed per field and reset when a
  new server error arrives.

### Year-end Schedule E model

The transaction UI is framed around **year-end Schedule E totals** plus
supporting documents:

- The transaction form has no Date field. New entries default to Dec 31 of the
  selected tax year (the date still lives in the data model for storage and
  sorting). Use one entry per Schedule E line per tax year.
- The per-transaction attachment UI is labeled **Documents** /
  "Supporting documents" - attach the year-end statement PDF as evidence. The
  backend routes and code identifiers are still named `receipts`; only the UI
  labels changed.
- Only the legacy PDF expense-import flow (the `ImportReview` components and
  the backend `/imports` session routes) is unrouted: it has no nav entry or
  route in the SPA. Schedule E import is reachable from the **Import** nav
  entry (see "Imports section" above).
- Itemized detail is optional supporting detail. The one-entry-per-line
  convention still applies to totals: the entered total remains the primary
  figure. A line with no entered total falls back to the itemized sum (see
  "Itemized expenses").

### Itemized expenses

The **Repairs** tab (`/properties/:propertyId/repairs`, between Transactions
and Depreciable Assets) lets a user keep per-entry detail (date, amount,
description/vendor, notes, documents) behind the Schedule E line 14 total for a
year. The category set is configuration-driven (`ITEMIZED_CATEGORIES` in
`services/itemized.py`); Repairs is the only enabled category.

- **Itemized marker.** An itemized entry is a transaction with
  `itemized = true`. Any transaction without it is an entered total row, so
  every pre-existing row is still a total and no migration is needed. The
  generic transaction create/update routes cannot set or change the marker;
  entries are managed on the Repairs page through
  `/properties/{propertyId}/itemized/{categoryId}/...`. Itemized rows also show
  on the Transactions page, badged and read-only. Receipts reuse the existing
  transaction receipt routes. Schedule E re-import replaces only `imported`
  rows and never touches itemized rows. Generic updates preserve the stored
  `imported` and `itemized` values, so editing an imported total keeps its
  marker and a re-import still replaces it instead of adding a second total.
  Receipts move with a transaction when its date (sort key) changes.
- **Precedence rule.** If an entered total exists, it is the line total. If
  not, the itemized sum is. With neither, the line is `0.00`. The itemized sum
  is never added to an entered total.
- **Single location.** The rule lives only in `LineAccumulator` in
  `backend/src/logstead/services/itemized.py`. `ReportingService._build_report`
  and `ItemizedExpenseService.summary` both use it. The dashboard, trends,
  carryforward, combined report and exports read `ReportingService.report_for`
  and inherit it. Do not sum itemized entries onto a line anywhere else; a
  source-scan test enforces this.
- **Backups.** Backup export and restore now carry `itemized`, `notes` and
  `imported` on transactions (additive; `schema_version` stays `"1"`). Restore a
  backup made with this feature on a version that includes it. An older version
  ignores `itemized`, which turns entries into totals and can double count,
  and drops `imported`.

### Year-end checklist

The Year-end checklist is a read-only reminder aid for one property and one
tax year. It stores nothing and changes nothing; it reads reports,
transactions, loans, assets and the carryforward through existing services.

- **Layout.** `services/checklist.py` holds the pure rule functions (one per
  item, no I/O), `build_checklist`, and `ChecklistService`, which gathers one
  `YearSnapshot` per request. Thresholds live only in
  `services/checklist_config.py`. Routes are `GET
  /properties/{propertyId}/checklist`, `GET
  /properties/{propertyId}/checklist/summary` and `GET /checklist/summary`.
  The query parameter is `taxYear`; response bodies use `tax_year`.
- **Item_Ids.** `ITEM_IDS` in `services/checklist.py` fixes the response
  order: `income_entered`, `expenses_entered`, `depreciation_present`,
  `line12_source`, `loan_interest_confirmed`, `carryforward_reconciled`,
  `repairs_exceed_total`, `repairs_capital_candidates`, `receipts_missing`,
  `yoy_swings`, `imported_values_edited`. Each item is `done`,
  `needs_attention` or `not_applicable`, with a Reason and a Link.
- **Checklist_Config.** `ChecklistConfig` is a frozen dataclass and
  `CHECKLIST_CONFIG` is the instance the service uses. Defaults:
  `large_entry_amount` 250.00, `capital_candidate_amount` 2500.00,
  `swing_percent` 50, `swing_minimum_amount` 500.00,
  `anchor_max_age_months` 12, `summary_year_count` 5. To change a threshold,
  edit the default in `checklist_config.py`; the rules, the Reason text and the
  applied thresholds echoed in the response all read from it. Money and
  percent values must be `Decimal` (a `float` raises `ChecklistConfigError`),
  money is not below 0.00, `swing_percent` is above 0, and the counts are at
  least 1. Comparisons against a threshold are inclusive. Do not write a
  threshold number anywhere else; source-scan tests (backend and frontend)
  enforce this.
- **Applicable_Loan rule.** `applicable_loan_count` counts loans that are
  included in the report and anchored on or before December 31 of the tax
  year. Item 4 (`line12_source`) flags a zero entered Line 12 only when such a
  loan exists; a loan anchored after the tax year, or excluded from the report,
  leaves it `not_applicable`. Loan facts come from `LoanService.year_facts`.
- **Adding an item.** Add one rule function with the signature
  `(snapshot, config) -> ChecklistItem`, register it in `_RULES`, and add its
  id to `ItemId` (which `ITEM_IDS` is derived from) in
  `services/checklist.py`. Rules read only the snapshot and the config. If the
  rule needs data the snapshot lacks, add it to `YearSnapshot` and gather it
  in `ChecklistService`; keep the read shared within the request.
- **Frontend.** Components, text helpers and the summary section and dashboard
  card use the `YearEnd` prefix and live in
  `frontend/src/components/year-end-checklist/` (the page is
  `pages/YearEndChecklistPage.tsx`). The API module is
  `api/yearEndChecklist.ts`. Item order and counts text are in
  `yearEndText.ts`. The page and the Transactions and Reports pages read
  `?year=` through the shared `parseYearParam` in `lib/taxYears.ts`; do not add
  a second parser.
- **Accountant package hook.** `provider_for(wiring, user)` in
  `services/checklist.py` returns a `ChecklistProvider`, a protocol with one
  method, `checklist_for(property_id, tax_year)`. `user` is a `UserContext` or
  a user id string. It builds the service through `build_checklist_service`
  (the public alias of `_checklist_service` in `router/handler.py`, imported
  lazily to avoid an import cycle) and reads nothing until `checklist_for`
  runs. The accountant package imports it at run time with
  `importlib.import_module("logstead.services.checklist")`, so keep the name
  and parameters unchanged.

### Accountant package

The accountant package is a ZIP of one tax year's reports, transactions and
receipts for one or more properties. It is built on demand by a separate
worker Lambda and stored only under `exports/packages/`.

- **Layout of the code.**
  - `router/handler.py`: `POST|GET /accountant-packages` and `GET|DELETE
    /accountant-packages/{jobId}` (create returns 202), plus the report PDF
    routes `POST /properties/{propertyId}/report/pdf` and `POST
    /reports/combined/pdf`. `build_package_service(wiring, user_id)` wires the
    report-side services exactly as the report routes do.
  - `services/package_jobs.py`: `PackageJobService` (create, list, get, delete)
    and the job states `queued`, `running`, `complete`, `failed`. A job that
    has not changed for `JOB_STALE_SECONDS` reports as `failed`.
  - `worker/package_worker.py`: `handler(event)`. The event carries only
    `user_id` and `job_id`; the year and property ids come from the stored job.
    Failure messages are fixed strings, so internal error text never reaches a
    job.
  - `services/accountant_package.py`: `PackageBuilder.build(tax_year,
    property_ids, zip_path)`, which returns a `PackageResult`.
  - `services/report_pdf.py`: `render_property_pdf` and `render_combined_pdf`.
  - `services/package_paths.py`: entry path helpers (`slugify`,
    `receipt_entry_path`, `is_safe_entry_path`).
- **ZIP layout.** `reports/schedule-e-<property>-<year>.{pdf,csv,json}` per
  property and `reports/schedule-e-combined-<year>.*` when two or more
  properties are selected; `transactions/transactions-<year>.csv`;
  `receipts/<property>/<category>/<date>_<txn8>_<filename>`;
  `checklist/year-end-checklist-<year>.json` when the checklist hook returns
  results; `README.txt`; and `manifest.json`, written last. Entries are sorted
  by path, text is compressed and receipts are stored. The manifest lists each
  file's size and SHA-256 (computed from the bytes written), the skipped
  receipts (`missing` or `oversized`), and `sections.checklist`.
- **Package_Config limits.** All limits live in
  `services/package_config.py` and nowhere else in the backend:
  `PACKAGE_MAX_BYTES` (400 MiB), `PACKAGE_MAX_RECEIPTS` (2000),
  `DOWNLOAD_LINK_SECONDS` (900), `JOB_TTL_SECONDS` (24 hours),
  `JOB_STALE_SECONDS` (900), `JOB_LIST_LIMIT` (10) and `COPY_CHUNK_BYTES`
  (1 MiB). The builder raises `PackageTooLarge` when the receipt count or the
  ZIP size passes a limit, and the worker puts its message on the job. A
  receipt larger than `MAX_DOCUMENT_BYTES` (`adapters/s3_files.py`, 25 MiB) is
  skipped as `oversized`. The retention values are mirrored by the one-day
  lifecycle rules in `infra/template.yaml`; change both together.
- **Adding a file to the package.** In `PackageBuilder.build`
  (`services/accountant_package.py`), add the entry with `add_fixed(path, kind,
  data)`. It rejects unsafe or duplicate paths and records the entry for the
  sorted write and the manifest, so the checksum and size come for free. Then:
  put the path through the helpers in `package_paths.py`, pass any
  user-controlled cell in a CSV through `neutralize_cell`, mention the file in
  `_readme`, and add the entry's `kind` to the tests. Do not write to the ZIP
  anywhere else, and keep `manifest.json` last. Read data through the existing
  services; do not recompute report figures in the builder.
- **Checklist hook.** The builder takes an optional `ChecklistProvider`.
  `default_checklist_provider(wiring, user)` imports
  `logstead.services.checklist` at run time and calls `provider_for(wiring,
  user)` (see "Year-end checklist" above). A missing module, a missing
  `provider_for`, or an exception means no checklist: the builder omits the
  file and records `not available in this release` or `could not be generated`
  in `sections.checklist`. A provider that returns an error for any property
  also omits the file. Keep the module name and the `provider_for` signature
  unchanged.
- **PDF text safety.** Every piece of user-controlled text (property names,
  addresses, descriptions, notes) that reaches a ReportLab `Paragraph` must go
  through `pdf_text` in `services/report_pdf.py`. It strips control
  characters, replaces characters outside Windows-1252 with `?`, and escapes
  `&`, `<` and `>` so no markup is interpreted. Text drawn directly
  (`drawString`) or set as document metadata uses `plain_pdf_text`, which does
  the same without the escaping. Do not build a `Paragraph` from raw text; use
  the `_p` helper, which applies `pdf_text`.

### Session tokens

The Cognito code + PKCE flow stores only the ID and access tokens (plus expiry) in `sessionStorage` via `lib/session.ts`. The refresh token is never persisted, and any legacy `logstead.refreshToken` key is removed on login success and by `clearSession`. Silent renewal is intentionally not implemented: when the access token expires, `getToken` returns null and the user signs in again. If renewal is added later, design it deliberately (for example an HttpOnly cookie via a backend), not by storing the refresh token in JS-readable storage.

## UI conventions

Shared primitives live in `frontend/src/components/ui/` and are exported from
its `index.ts`. Use them instead of hand-built markup.

### Type scale, spacing, and motion tokens

Defined in `frontend/tailwind.config.js` (see the comment block there). Use the
names, not literal sizes (for example, no `text-2xl` on a page).

| Token | Use |
| --- | --- |
| `text-page-title` | The page `h1` (one per page) |
| `text-section-title` | Section `h2` |
| `text-card-title` | Card headings |
| `text-body`, `text-small`, `text-caption` | Body, hints and notes, badges and group labels |
| `page-x`, `page-y`, `section`, `card`, `card-lg` | Spacing names for `p-*`, `m-*`, `gap-*`, `space-y-*` (`card-lg` is modal padding) |

Motion durations and easing are CSS variables on `:root` in `index.css`
(`--motion-fast`, `--motion-base`, `--motion-slow`, `--motion-ease`), exposed as
`duration-fast|base|slow` and `ease-standard`. A `prefers-reduced-motion:
reduce` rule in `index.css` limits animation and transition durations to 1ms
and disables smooth scrolling. Toast and `fade-in` keyframes are defined in the
Tailwind config; `tailwindcss-animate` is intentionally not used. Skeletons add
`motion-reduce:animate-none`.

### Color tokens and the contrast test

Components use semantic tokens backed by CSS variables in `index.css`
(`canvas`, `surface`, `surface-muted`, `border`, `fg`, `fg-muted`, `fg-subtle`,
`accent*`, `success*`, `danger*`, `warning*`), with a `.dark` override for each.
Never use literal palette colors.

- **Accent is teal** (light `15 118 110`, dark `45 212 191`). Changing the
  variables recolors every component.
- **`border-strong`** is for form control boundaries (3:1 against the
  surface). Use `border` only for decorative dividers.
- **Brand tokens:** `brand-orange` is decorative or chart use only, never text.
  `fill-brand-tagline` colors the logo tagline.
- **Contrast test:** `src/test/tokenContrast.test.ts` parses `index.css` and
  checks each pair in `TOKEN_PAIRS` (`src/lib/contrast.ts`) in both themes. When
  you add or change a token used for text or a control boundary, add or adjust
  its pair there.

### Buttons

`Button` supports variants `primary`, `secondary`, `danger`, and `ghost`, and
sizes `sm`, `md`, and `icon`.

- `loading` shows a centered `Spinner`, keeps the button width, sets
  `aria-busy`, and suppresses click and submit without using `disabled`. It is
  not supported with `asChild`.
- `size="icon"` needs `aria-label`, `aria-labelledby`, or `title`; development
  builds warn otherwise.
- Sizes grow to 44px on narrow viewports (`max-md:min-h-11`). `Input`,
  `Select`, and `Textarea` do the same.
- Icons come from `ui/icons.tsx` (shared `createIcon`; decorative by default).
  Add new icons there instead of inline SVG.

### Page structure, titles, and route focus

- Every routed page renders `PageHeader` (`title`, `description`, `meta`,
  `actions`, `breadcrumb`, `children`), which owns the single `h1`
  (`id="page-heading"`, `tabIndex={-1}`). `PropertySection` wraps it for
  per-property pages. Do not write `<h1>` in `pages/`; a source-scan test
  enforces this.
- Every page calls `useDocumentTitle("Page")`, which sets "Page - Logstead" and
  restores the previous title on unmount. `ScheduleEImportPage` and
  `ScheduleEExtractionPage` have no `h1` or title of their own because
  `ImportsLayout` owns them.
- `RouteAnnouncer` (mounted once in `AppLayout`) focuses `main h1` (falling back
  to `#main-content`) and announces the title through a polite live region when
  the pathname changes. It does nothing on first render or for hash and search
  only changes.

### Forms

- `FormField` wires label, hint, error, required marker, `aria-describedby`,
  `aria-required`, and `aria-invalid` to its control via a render prop. Use it
  with `Input`, `Select`, and `Textarea` (all accept `invalid`). Radio groups
  stay `fieldset` and `legend`.
- `ErrorSummary` (with `orderedErrors` and `firstInvalidField` from
  `lib/formErrors.ts`) lists all errors at the top of a form. Items focus their
  field. `useFocusFirstInvalid` moves focus to the first invalid field after a
  failed attempt. Form-level errors without a field do not move focus.
- `MoneyInput` shows a `$` prefix, sanitizes to a canonical string
  (`lib/moneyInput.ts`), and formats to two decimals on blur. Its `value` and
  `onValueChange` use canonical text, so existing validators and the API keep
  receiving plain money strings. Use it for currency fields.
- `DateInput` is a date `Input` with a "Today" button. `todayLocal()` builds the
  date from local parts, never `toISOString`.

### RecordModal and the discard guard

Forms report dirtiness with `useDirtyReporter(initial, current, onDirtyChange)`
(`lib/dirty.ts`; dirty means values differ, so restoring the original value is
clean). Pass `modal.setDirty` as `onDirtyChange`, then wire the modal:

```tsx
<RecordModal
  open={modal.open}
  onOpenChange={(next) => { if (!next) modal.requestClose(); }}
  discard={modal.discard}
  ...
>
  <MyForm onDirtyChange={modal.setDirty} onCancel={modal.requestClose} />
</RecordModal>
```

`requestClose()` closes immediately when clean and otherwise opens the "Discard
changes?" confirmation. `close()` is a force close (use it after a successful
save). Standalone dialogs use `useDiscardGuard` directly. The Imports section
uses an `ImportsDirtyContext` so tab switches prompt the same way, plus a
`beforeunload` listener while dirty.

**Footer and viewport.** The panel is `max-h-[90dvh]` (`dvh`, not `vh`, so
mobile browser toolbars and the on-screen keyboard do not push content off
screen), scrolls internally, and uses `p-4 sm:p-6` with
`w-[calc(100vw-1.5rem)] sm:w-[92vw]`. `RecordModal` takes an optional `footer`
prop, rendered in a sticky bottom bar inside the scrolling panel. Forms that
live inside the `<form>` element use `ModalFormActions` (`components/ui/`)
instead: a sticky, wrapping button bar that cancels the panel padding, so Save
stays reachable at 320px and submit buttons keep working. Wrap the Cancel and
Save buttons of a modal form in it.

**16px controls.** `Input`, `Select` and `Textarea` use `max-md:text-base`
(16px below `md`, `text-sm` at `md` and wider) so iOS Safari does not zoom on
focus. `MoneyInput` and `DateInput` wrap `Input` and inherit the rule. Do not
hand-build a form control with a smaller size on narrow viewports.

### Loading, errors, and skeletons

- `useFirstLoad({ loading, error, resetKey })` returns a `LoadView`
  (`showSkeleton`, `showContent`, `refreshing`, `showError`, `errorIsStale`).
  The skeleton shows only before the first successful load. Later reloads keep
  content mounted and show `RefreshingIndicator`. Pass `resetKey` (for example
  the property id) to reset when the subject changes.
- The load error alert (Load_Error_Alert) is `StateBlock kind="error"` with
  `title`, `description`, and `onRetry`. Retry shows a loading state while the
  returned promise is pending. Use `compact` for a one-row banner when stale
  content is still shown.
- Skeletons: `Skeleton`, `LoadingRegion` (`role="status"`, `aria-busy`),
  `TableSkeleton`, `TileSkeleton`, `ChartSkeleton`. `ResponsiveTable` takes
  `loading` to render a `TableSkeleton`.

### Toasts and Undo

`toastDurationMs` sets auto-dismiss: 5s by default, 10s for error toasts and
toasts with an action, or an explicit `duration`. Radix pauses on hover and
focus.

`useUndoableDelete({ remove, restore, refresh, deletedTitle, ... })` returns
`run(item)`. It deletes, refreshes, and shows a toast with an Undo action that
re-creates the record through the normal create API from the retained item.
Only use it for a **Safe_Delete**, one a single create call can fully restore:

- Assets: always safe.
- Loans: safe only with no yearly interest overrides (`isLoanSafeDelete`).
- Transactions: safe only when not imported, not itemized, and the receipt
  count is known to be zero (`isTransactionSafeDelete`).
- Itemized entries: safe only when the receipt count is known to be zero
  (`isItemizedEntrySafeDelete`). An unknown count is never safe.
- Everything else keeps a `ConfirmDialog`.

Classifiers and create-payload mappers are in `lib/undoMappers.ts`.

### Undo and record IDs
Undo is client-side only: it calls the normal create endpoint with the
retained fields. The server generates a **new id**, and `created_at` /
`updated_at` are reset. There is no tombstone: a deleted record is gone.

The toast Undo stays client-side. It never calls the history restore route, so
the server cannot tell an Undo from any other create: the Activity page shows an
ordinary `create` event next to the earlier `delete` event, with no link
between them. `activityUndo.test.tsx` checks this.

The **Activity page's Restore** (`POST /properties/{id}/activity/{eventId}/restore`)
is a second, server-side path. It re-creates a deleted transaction, itemized
entry, asset or loan from the payload stored on the `delete` event, using the
same safe-delete rules as the toast. The record also gets a **new id** and fresh
`created_at` / `updated_at`; the event is marked restored and a `restore` event
is recorded. The new id is returned as `record_id`. Restoring the original id is
listed in `docs/future-improvements.md`.

| Entity | Undoable | Id after Undo | Notes |
| --- | --- | --- | --- |
| Transaction | Yes, if not imported, not itemized, and the receipt count is known to be 0 | New | Receipts and S3 objects are never involved: a transaction with receipts (or an unknown count) uses a confirm dialog. Imported and itemized rows are excluded because generic create cannot set the `imported` or `itemized` marker. |
| Itemized entry (Repairs page) | Yes, if the receipt count is known to be 0 | New | Re-created through the itemized create route from the retained fields, with the itemized marker set. Entries with receipts (or an unknown count) use a confirm dialog. Fresh `created_at` / `updated_at`. |
| Entered total re-created after removal (Repairs page) | Yes, if the receipt count is known to be 0 | New | Re-created as a normal total row. Restoring a previous total amount by editing in place keeps the row id, so no id changes there. Creating an entry never edits the total, and setting the total never edits entries. |
| Loan | Yes, if no yearly interest overrides | New | Loans with overrides use a confirm dialog because the override rollup rows are deleted with the loan. |
| Asset | Always | New | Schedule rows are derived, so they are recomputed. Depreciation overrides are part of the create payload and are restored. |
| Any toast Undo, in the Activity history | n/a | New | The Undo is an ordinary create call, so the history records a `create` event beside the earlier `delete` event, not a `restore`, and does not mark the delete as restored. History restore (Activity page) is separate and also gives a new id. |
| Property, business, photo, receipt, business document | No | n/a | Always confirm-then-delete. Undo is never offered, so their ids, S3 objects and metadata are not at risk. |

What breaks after Undo, and why it is acceptable:
- Deep links and bookmarks to the old id (for example an expanded asset or
  transaction, or a selected loan) stop resolving. Pages clear state keyed to the
  old id in `remove` and re-read the list in `refresh`, so the UI shows the new
  id. Nothing navigates to the old id.
- No other record stores these ids. Loans, assets and transactions are
  siblings under a property. Business-to-property links and Schedule E import
  sessions reference properties, not these entities. Import results hold
  `created_transaction_ids` only in the response, and imported transactions are
  never undoable.
- Receipts and photos: not restorable by Undo, so deletes with receipts are
  never offered Undo (see table).
- Audit trail: the restored record is a new record with fresh timestamps; the
  original creation time is not preserved. The old id still appears in the
  history on the `delete` event (`record_id`).

When adding a new undoable entity, confirm that nothing else references its
id and that the create payload covers every child row, or keep the confirm
dialog. Tests: `lib/undoIds.test.tsx`.

### Navigation

`navConfig.ts` defines `NAV_GROUPS` (Portfolio, Tax, Tools); `PRIMARY_NAV` is
the flattened list. `MainNav` renders the groups with icons. Plain left clicks on its links go
through `useGuardedNavigate` (a dirty Imports form prompts "Discard changes?");
modified and middle clicks keep the browser default. `PropertySwitcher`
(a native `select` in the `AppLayout` header and mobile drawer, fed by
`ShellPropertiesContext`) jumps between properties while keeping the current
sub-section.

**Property section tabs (disclosure).** `PropertySectionTabs` renders one
`nav[aria-label="Property sections"]` with one `ul` of `NavLink`s built from
`PROPERTY_NAV`, at every width. Below the `md` breakpoint (768px) the list is
hidden behind a button labeled "Property sections: {current}" (`aria-expanded`,
`aria-controls`); at `md` and wider the button is hidden (`md:hidden`) and the
links show as a wrapping row (`md:flex-wrap`). The list closes when a link is
chosen, on Escape (focus returns to the button) and when focus leaves the nav.
The current label comes from `lib/propertySections.ts`:
`currentSection(pathname, propertyId)` returns the `PROPERTY_NAV` entry with
the longest matching path (the empty Overview segment matches exactly only) or
`null` outside the property. Fallback: if `e2e/responsive.spec.ts` shows more
than two rows of tabs at 768px, change `md:` to `lg:` in `PropertySectionTabs`,
update the viewport tests and record the change here.

### Keyboard shortcuts and the command palette

Provider order in `AppLayout`: `NavigationGuardProvider`, `ShellPropertiesProvider`,
`ShortcutsProvider`, `PaletteProvider`.

**Shortcuts registry.** `lib/shortcuts/registry.ts` exports `SHORTCUTS`, the one
list of shortcuts. Each `ShortcutDef` has `id`, `label`, `group` ("General" or
"Go to"), `keys` and `run` (a `ShortcutActionId`). `"mod"` in `keys` means Cmd on
macOS and Ctrl elsewhere; `formatKeys` renders it. `findDuplicates` returns key
combinations used twice (`registry.test.ts` covers it). The help dialog
(`components/shortcuts/ShortcutsHelp.tsx`) is built from the same list.

To add a shortcut:

1. Add an id to `ShortcutActionId` and an entry to `SHORTCUTS`. A single key or
   a two-key sequence (`["g", "x"]`) works; `mod+k` is the palette chord.
2. Handle the id in `run` inside `components/shortcuts/ShortcutsProvider.tsx`.
   A `g` sequence only needs an entry in `GO_TARGETS` (id to path).
3. Run `registry.test.ts` to check for duplicates. The help dialog picks it up.

**One listener.** `ShortcutsProvider` owns the only `document` `keydown`
listener. It builds a `KeyEventInfo` and applies the pure rules in
`lib/shortcuts/eligibility.ts`:

- `isEligiblePlainKey`: the target is not editable (`classifyTarget`: input,
  textarea, select, contenteditable), no blocking dialog is open
  (`hasBlockingDialog`: an open `role="dialog"` or `alertdialog` without
  `data-palette`, such as `RecordModal`), no Alt, Ctrl or Meta, not composing
  (IME, `keyCode` 229), not a repeat, and not already default-prevented. Shift
  is allowed so `?` works.
- `isPaletteChord`: Cmd+K on macOS, Ctrl+K elsewhere. It works from editable
  targets but not while a blocking dialog is open, and it toggles the palette.
- `lib/shortcuts/sequence.ts` (`stepSequence`) is the two-key state machine,
  with a `SEQUENCE_TIMEOUT_MS` of 1000. An ineligible event clears a pending
  key. Plain `/` opens the palette, `?` opens help, and `g` then `d`, `p`, `r`,
  `c`, `i` or `a` goes to Dashboard, Properties, Reports, Carryforward, Import
  or Activity.

**Palette.** `PaletteProvider` holds the open state and registers `open`,
`close` and `isOpen` with `ShortcutsProvider` through `PaletteContext`
(`usePalette`). `CommandPalette` and `PaletteList` render it. Pure logic:

- `paletteItems.ts`: `buildLocalItems` returns Destinations (Pages, Properties,
  Property sections for the active property, Tax years linking to
  `/reports?year=YYYY`) then Actions (`ActionId`: add-property, add-transaction,
  add-repair, add-asset, add-loan, import-schedule-e, switch-theme,
  keyboard-shortcuts, show-setup-guide, download-backup). `resolveActionTarget`
  decides a property-scoped add: the active property wins, then the only
  property, otherwise a property picker; with no property the action is
  unavailable ("Add a property first"). To add an Action, extend `ActionId` and
  `ACTIONS`, then handle it in `onRunItem` in `PaletteProvider.tsx`.
- `paletteRank.ts`: `rankLocal` keeps items containing every token (at most 5)
  and ranks exact label, then label-word prefix, then other matches.
  `moveHighlight` wraps at the ends.
- `useGlobalSearch.ts` supplies server search results; result links are checked
  with `lib/safeLink.ts` before navigating.

**Navigation guard.** `lib/navigationGuard.tsx`. A page holding unsaved input
calls `useRegisterDirty(key, dirty)` (today `ImportsLayout`, key `"imports"`).
Code that navigates for the user calls `useGuardedNavigate().go(to, onProceed?)`.
When clean it navigates at once; when dirty it shows the shared "Discard
changes?" confirm ("Keep editing" or "Discard"). Discard clears all flags,
navigates, then runs `onProceed`. The palette, the `g` shortcuts and `MainNav`
all use it. Outside the provider `go` falls back to plain `navigate`.

**`new`, `focus` and `year` parameters.** Palette Actions link to pages that
read query parameters:

- `?new=1` (`lib/useNewParam.ts`): once the page's data has loaded (`ready`) it
  opens its add flow, then removes `new` by replacing the history entry. Used by
  `PropertiesPage`, `TransactionsPage`, `ItemizedExpensesPage`, `AssetsPage` and
  `LoansPage`. Property-scoped actions link to
  `/properties/{id}/{transactions|repairs|assets|loans}?new=1`, and Add property
  links to `/properties?new=1`.
- `?focus={id}` (`lib/useFocusParam.ts`): scrolls to and focuses the row with
  `id="row-{id}"` once, ignoring ids not in the list. The parameter stays in the
  URL. Pass a selector function for other id schemes. `/profile?focus=backup`
  is separate: `ProfilePage` moves focus to the Backup section.
- `?year=YYYY`: `ReportsPage`, `TransactionsPage`, `CombinedReportsPage`,
  `ItemizedExpensesPage` and `YearEndChecklistPage` read it with
  `parseYearParam` (`lib/taxYears.ts`) and fall back to their default year.
  Tax-year palette items and checklist links use it.

### Global search

`GET /search` (see `docs/api.md`) is implemented in `backend/src/logstead/services/`:

- `search_config.py`: `SearchConfig` limits (`min_query_length` 2,
  `max_query_length` 100, `max_tokens` 5, `default_limit` 5, `max_limit` 25,
  `scan_cap` 20,000).
- `search_match.py`: pure functions with no I/O. `normalize` (NFKC, case-fold,
  whitespace), `tokenize`, `match_rank`, `sort_key` and `link_for`.
- `search.py`: `SearchService.search`. It reads only through the existing
  user-scoped services (`PropertyService`, `TransactionService`,
  `DepreciationService`, `LoanService`, `BusinessService`), writes nothing and
  makes no S3 call. `_search` in `router/handler.py` validates the query
  parameters and the owned `propertyId`, and logs counts only, never the query.

**Matching rules.** The query is never compiled into a pattern, so `*`, `%`,
`\` and `.` are literal. A record matches when every token occurs in the joined,
normalized searched fields. `match_rank` gives 0 when one field equals the
whole query, 1 when every token starts a word, otherwise 2. Hits sort by rank,
newest date, normalized title, title, id. Links come from `link_for`, which
rejects ids outside `[A-Za-z0-9_.:-]{1,128}` and a non-4-digit year; the record
is skipped when it raises.

**Scan cap.** `scanned` adds up the transactions, assets and loans read for each
property. When `scanned` reaches `scan_cap` the loop stops and `truncated` is
`true` if properties remain. Known open point: when the cap is hit exactly and
the remaining properties are empty, `truncated` is still `true` although nothing
was missed. Reading stops at the cap by design and does not look ahead.
The frontend shows `TRUNCATION_NOTICE` when `truncated` is set.

**Add a searchable field.**

1. In `search.py`, add `(name, text)` to the `fields` list passed to `match_rank`
   for that kind. `name` becomes `matched_field`. Searching a new text field
   changes what users can find, so check the spec first. Do not add amounts,
   dates or category labels.
2. Extend `test_search_service_property.py` (matching, and the "not searchable"
   examples) and add the field to the table in `docs/api.md`.
3. To add a new kind, also add it to `GROUP_KINDS`, `link_for`,
   `frontend/src/api/search.ts` and `components/search/searchGroups.ts`
   (`GROUP_LABELS`), and give the target page a row `id="row-{id}"` with
   `useFocusParam`.

**Frontend.** `api/search.ts` (`searchApi.search(q, { limit, propertyId, signal })`)
wraps the route. `components/palette/useGlobalSearch.ts` debounces by 250 ms,
sends nothing under 2 characters, aborts the previous request, keeps earlier
results while loading or after an error, and exposes `retry`. The palette asks
for 5 hits per group and `SearchPage` (`/search?q=`, 25 per group) writes the
field back to `q` with replace navigation. `components/search/SearchResults.tsx`
renders the groups; `HighlightedText` uses `lib/highlight.ts`
(`highlightSegments`, which returns text segments rendered as text nodes, never
HTML). Result links are checked with `lib/safeLink.ts` (`isSafeAppLink`: a
single leading `/`, no `//`, backslash or control character) before navigating.
Landing pages (`TransactionsPage`, `ItemizedExpensesPage`, `AssetsPage`,
`LoansPage`) call `useFocusParam` to scroll to and focus the `?focus=` row.

### Activity history

`GET /activity`, `GET /properties/{id}/activity` and the restore route are in
`docs/api.md`; the stored item is in `docs/data-model.md`.

**Where events are recorded.** Only in `router/handler.py`. No domain service
imports or receives the recorder, and a source scan test
(`test_activity_isolation_property.py`) fails if `report.py`, `dashboard.py`,
`carryforward.py`, `loan.py`, `depreciation.py`, `transaction.py` or `backup.py`
import `services.activity`. A report can therefore never depend on history.

**Recording an event from a handler.** Decorate the mutation handler with
`@_with_activity(_ActivitySpec(events, before=..., purge=...))`, below the
route's other decorators so it runs inside `_property_scoped`.

- `before(wiring, user, params, body, query)` reads the record ahead of the
  mutation. It is best effort; returning `None` or raising only costs the event
  its before values.
- `events(wiring, user, params, body, query, before, data)` returns a list of
  `NewEvent`. `data` is the parsed success body. Return `[]` to record nothing
  (an update that changed no allow-listed field does this).
  `_crud_event(...)` builds the usual create, update and delete event.
- The wrapper records only after a `200`, `201` or `204`, and catches every
  exception, so a `400`, `404` or failed write records nothing and a recording
  failure never changes the response.
- `purge="property"` or `"user"` deletes events after success and before the
  new event is written (property delete, backup restore and clear).
- Write one event per operation. A bulk operation (an import) is one event.

**The allow-list.** `FIELDS` in `services/activity_events.py` names the fields
stored per entity. `project` keeps only those, `diff` keeps the changed ones,
and `bound` truncates values to 200 characters and each JSON attribute to
2,048 bytes. Money stays a string. Add a field there only after checking it is
not sensitive; do not record receipts, photos, tokens or free-form payloads.

**Adding an entity.**
1. Add it to `FIELDS` and `_ENTITY_LABELS` in `activity_events.py`, and to
   `ENTITIES` in `services/activity.py`.
2. Decorate its create, update and delete handlers (the entity becomes an
   `entity` filter value, so the API accepts it automatically).
3. To make deletes restorable, add a case to `is_restorable`, include the
   create fields in `_restore_payload` (router) and add a branch to
   `ActivityService._creator` that builds the same input the create route uses.
   Keep the rule identical to the toast Undo rule.
4. Add the kind to `ActivityEntity` in `frontend/src/api/activity.ts` and to
   `ENTITY_LABELS` (and `ENTITY_SEGMENTS` for a link) in `lib/activityText.ts`.
5. Extend `test_activity_routes.py` and the restore property tests.

**Retention.** `retention_days` (730) in `services/activity_config.py` is the one
definition. Compute `ttl` through `ttl_for` and read the constant in tests and
docs; do not write 730 elsewhere.

**Restore.** `ActivityService.restore` claims the event with a conditional write
(`restoredAt` absent, or a `pending` claim older than 5 minutes), re-creates the
record through the existing service, then marks the event with the new id. A
failed create releases the claim. The record gets a new id (see "Undo and
record IDs").

**Frontend.** `api/activity.ts` (`activityApi.list`, `listForProperty`,
`restore`), `lib/activityText.ts` (labels and `eventLink`), `pages/ActivityPage.tsx`
(`/activity`, filters, Load more of 25), `components/activity/ActivityEventRow.tsx`
(details and the Restore confirm dialog) and `RecentActivityPanel.tsx` (latest 5
on the property Overview; a failure there leaves the tiles usable).

### Setup guide and empty-state guidance

**Stored state.** `lib/onboardingStorage.ts` keeps two local flags per user.
`setupKeys(userId)` returns `logstead.checklist.dismissed` (the key owned by
`lib/checklistStorage.ts`) and `logstead.checklist.collapsed`; each gets a
`.{userId}` suffix when the user id is known, and none otherwise. A flag is
stored as `"1"` and removed when false, so the defaults (not dismissed, not
collapsed) leave no key. `readSetupState` returns the defaults and
`writeSetupState` does nothing when storage throws, so the guide still works
with storage blocked, but the state then lasts only for the page view.
`writeSetupState(userId, patch)` changes only the flags in the patch, and
`clearSetupState` removes both. `serializeSetupState` and `parseSetupState`
define the canonical JSON form (`{"dismissed":bool,"collapsed":bool}`); anything
else parses to the defaults and `parseSetupState` never throws.
`onboardingStorage.property.test.ts` covers the round trip. The report-visited
flag (`logstead.checklist.visitedReport`) stays in `checklistStorage.ts`.

**Derivation.** `components/dashboard/checklist.ts` is pure.
`computeChecklist(flags, dismissed)` builds four steps in a fixed order
(`property`, `transactions`, `loanOrAsset`, `report`) and is `visible` when not
dismissed and fewer than four are done. `nextStep` returns the first incomplete
step, `stepReason` its one-sentence reason and `checklistProgressText` "x of 4
done". `ChecklistCard` fills the flags from the dashboard summary
(`has_properties`), the trends series (transactions, depreciation) and the
visited flag. Only when none of those show a loan or asset does it probe
`listLoans` and `listAssets` for the first five properties; a failed probe
counts as not done. The card shows a "Next" label and the reason on the first
incomplete step, a Collapse/Expand button (`aria-expanded`,
`aria-controls="checklist-steps"`), a "You're set up" state with Dismiss when all
four are done, and a `role="status"` live region that announces a step completed
after the first loaded render. It adds no animation, so Reduced_Motion needs no
special case.

**Where the guide shows.** `DashboardPage` renders `DashboardEmptyState`, not
`ChecklistCard`, when the summary reports no property. The card therefore
appears only once the user owns a property, and its own "Explore with sample
data" link (rendered while `has_properties` is false) is not reached from the
dashboard today. The sample data link a user without a property sees comes from
`DashboardEmptyState` and the empty `PropertiesPage`. All three go to
`/profile?focus=backup`; the card's copy warns that sample data replaces all
current data. The label is `SAMPLE_DATA_LINK_LABEL` in `lib/emptyCopy.ts`.

**Show setup guide.** `lib/setupGuide.tsx` exports `SetupGuideProvider` and
`useSetupGuide()` (`{ showSetupGuide, resetSignal }`, or `null` outside the
provider). `SetupGuideHost` in `components/AppLayout.tsx` provides it. Its
`showSetupGuide` calls `clearSetupState`, bumps `resetSignal`, navigates to `/`
with the guarded `go`, then focuses `#checklist-heading`, retrying each frame for
up to 5 seconds until focus lands. `ChecklistCard` re-reads its stored state when
`resetSignal` changes. Two entry points render only when the context is present:
the "Show setup guide" item in `ProfileMenu` (it skips the menu's focus return to
the trigger) and the `show-setup-guide` palette action (`PaletteProvider` drops
it without the context). With no property the dashboard shows the empty state,
so there is no guide heading to focus.

**EmptyGuide and emptyCopy.** `components/ui/EmptyGuide.tsx` wraps
`StateBlock kind="empty"` with `title`, `description`, a `primary` action and an
optional `secondary` action (each a button with `onClick` or a link with `to`).
It renders no landmark. `lib/emptyCopy.ts` exports `EMPTY_COPY`, one entry
(`title`, `description`, `primaryLabel`) per key: `transactions`, `repairs`,
`assets`, `loans`, `properties`, `reports`, `combinedReports`. The page decides
what the primary action does. Each description says what the page records and
how it reaches Schedule E, and gives no tax advice; the copy test rejects
phrases such as "you should report" and "deductible". Pages render `EmptyGuide`
only when loaded and empty, never while loading or failed. The Reports pages add
the `IMPORT_LINK_LABEL` link, and `PropertiesPage` adds the sample data link
only while the user owns no property. To add an empty state, add a key and entry
to `EMPTY_COPY` and use `EmptyGuide` in the page.

### ResponsiveTable

Besides `columns`, `rows`, and `caption`, `ResponsiveTable` supports
per-column `sortable` with `sortType` (`text`, `number`, `date`), a sticky
header (`stickyHeader`, `maxHeightClass`), `rowHeader` cells, and `loading`.
Sort cycles ascending, descending, none, and is stable (`ui/tableSort.ts`).
Cells carry pre-formatted nodes, so give numeric and date columns a sort type
that matches how they are displayed. The sticky scroll area defaults to
`maxHeightClass="max-h-[70dvh]"` (`dvh`, so it tracks the visible viewport on
mobile).

### Brand assets

- `docs/brand/logo-source.svg` is the editable artwork. It uses live text and
  `system-ui`, so it is never shipped. See `docs/brand/README.md`.
- The wordmark and tagline are outlined paths from Inter Bold and SemiBold
  (`docs/brand/fonts/`, SIL OFL). `frontend/scripts/outline-brand-text.mjs`
  produces `src/assets/brand/brand-paths.ts`, `logo.svg`, and `logo-mark.svg`.
- `frontend/scripts/generate-brand-icons.mjs` renders the static files in
  `frontend/public/` (`logo.svg`, `logo-mark.svg`, `favicon.svg`,
  `favicon-monogram.svg`, `favicon-32.png`, `apple-touch-icon.png`) from those
  assets.
- Neither script runs in `npm run build`; their output is committed. To
  regenerate, run from `frontend/`:

```bash
node scripts/outline-brand-text.mjs     # after changing the artwork constants
node scripts/generate-brand-icons.mjs   # after the outlined SVGs change
```

- Use `BrandLogo` (error boundary around `Logo`). `BrandMark` in
  `BrandLogo.tsx` is the single switch: point it at `WordmarkFallback` to fall
  back to text everywhere. A render failure also falls back to text.
- The tagline shows only on the sign-in splash at 640px (`sm`) and wider
  (`BrandSplash`). Do not enable `tagline` elsewhere.

### Accessibility tests (Axe_Suite)

`src/test/axeRoutes.test.tsx` renders every leaf route from `APP_ROUTES`
(`src/routes.tsx`, consumed by `App.tsx` through `useRoutes`) in light and dark
themes against a fetch stub (`src/test/apiStub.ts`, `src/test/fixtures.ts`). It
asserts exactly one `h1` and no axe violations (`color-contrast` is off in
jsdom; the token contrast test covers it).

- When you add a route to `APP_ROUTES`, the suite picks it up. If the path has a
  parameter, add a sample value to `SAMPLE_PARAMS` or the suite fails naming the
  route.
- Mark redirect-only routes with `handle: { redirect: true }` so `leafPaths`
  skips them.
- Pages rendered inside `ImportsLayout` are listed in `NO_OWN_H1`.
- Add canned responses to the stub or fixtures if a new page needs data to
  reach its normal render.

### Browser checks (Playwright: axe and smoke)
`frontend/e2e/a11y.spec.ts` opens every main route in Chromium (dashboard,
properties, property overview and each property tab, combined reports,
carryforward, businesses, accountant package, search, activity and profile),
plus the open palette, in light and dark themes, and runs `@axe-core/playwright` with the `wcag2a`, `wcag2aa`
and `wcag21aa` tags. Unlike the jsdom Axe_Suite, `color-contrast` is evaluated
against real computed styles. Any violation fails the test.
```bash
cd frontend
npm run e2e:install   # one-time: downloads Chromium
npm run e2e           # starts vite on :4173 and runs the specs
```
- No real AWS call is made. `playwright.config.ts` points `VITE_API_BASE_URL` at
  `https://api.e2e.invalid`; `e2e/fixtures.ts` answers it with the canned data
  from `src/test/fixtures.ts` via `page.route` and aborts every other
  non-localhost request.
- Auth is bypassed in the test only: an init script seeds the `sessionStorage`
  keys that `src/lib/session.ts` reads with placeholder tokens that expire in an
  hour, and sets `localStorage["logstead.theme"]` to `light` or `dark`.
- To cover a new route, add it to `ROUTES` in `e2e/a11y.spec.ts` and any new
  endpoint to `API_ROUTES` in `e2e/fixtures.ts`.
- `e2e/smoke.spec.ts` (review.md S10, R11) covers the end-to-end flows:
  - Sign-in: starts signed out (`prepare(page, theme, { authenticated: false })`),
    captures and aborts the redirect to the Cognito authorize endpoint, and
    checks `response_type=code`, `client_id`, `redirect_uri`, `state` and an
    S256 `code_challenge` that hashes the stored verifier. It then opens
    `/auth/callback?code=...&state=<saved state>` with `/oauth2/token` mocked,
    checks the token request body, lands on the dashboard, and asserts no
    refresh token is in session or local storage. A second test uses a wrong
    `state` and checks the error, no token request and no stored tokens.
  - Records: creates a property through the Add property dialog, adds a
    transaction, deletes it, clicks Undo in the toast, and checks the row comes
    back under a new id and the re-create POST carried no `id`.
- The Cognito values are fake (`https://auth.e2e.invalid`, client
  `e2e-client-id`, redirect `http://localhost:4173/auth/callback`) and set in
  `playwright.config.ts` for every spec. The a11y specs seed a session, so they
  never start sign-in.
- `createStatefulApi()` in `e2e/fixtures.ts` is an in-memory store for
  `/properties` and `/properties/{id}/transactions` that assigns ids on create
  and records every write. Pass its `handler` to `prepare(..., { handler })`;
  requests it does not handle fall back to the canned `API_ROUTES`.
- The dev server runs React StrictMode, so the signed-out app may redirect to
  Cognito twice. The spec picks the authorize URL whose `state` matches the one
  left in sessionStorage.
- The other specs are `responsive.spec.ts`, `palette.spec.ts`,
  `sidebar-guard.spec.ts`, `onboarding.spec.ts` and `activity.spec.ts`; see
  [Testing guide](testing.md). Axe calls go through a `runAxe` helper that waits
  for the page to settle and retries only on a navigation race.
- `playwright.config.ts` retries each test once locally (twice with `CI` set)
  and uses a 15 second `expect` timeout.
- `e2e/` is excluded from vitest and type-checked through `tsconfig.e2e.json`.
- Run with `npm run e2e` before UI changes merge (see [Local checks](local-checks.md)).

## Project conventions

- **Layering.** Business rules live only in backend services. The router parses
  requests and maps results to HTTP; repositories own the DynamoDB key scheme;
  adapters own external integrations. Do not build DynamoDB keys or call
  external APIs outside their designated layers.
- **Money.** Always use `decimal.Decimal`. Persist and serialize money as
  two-decimal strings. Never introduce floats or DynamoDB `Number` for money.
- **Reproducibility.** Keep transaction, asset, and depreciation inputs as the
  system of record. Do not persist derived aggregates as authoritative.
- **Drafts vs transactions.** Keep imported draft line items separate until the
  user confirms.
- **Tests accompany changes.** Add unit, property-based, and/or integration
  tests alongside behavior changes. See [Testing guide](testing.md).

## Checks

There is no hosted CI. Run the checks locally before merging: see
[Local checks](local-checks.md) for the commands, timings, the quick and full
backend runs, dependency audits, browser checks, cfn-lint and cfn-guard.

## The spec

The application was built from the spec in `.kiro/specs/logstead/`, and each
later feature has its own folder under `.kiro/specs/` (for example
`itemized-expenses`, `year-end-checklist`, `accountant-package`, `ui-polish`),
each with `requirements.md`, `design.md`, and `tasks.md`. These are the
authoritative source for intended behavior and rationale; where a later spec
changes an earlier one, the later spec wins.
