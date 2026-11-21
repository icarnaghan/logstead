# Testing Guide

Logstead has test suites for both the backend and the frontend. All tests run
locally with no AWS account: external services and AWS resources are faked.

## Backend

Backend tests use **pytest** with **Hypothesis** (property-based testing),
**moto** (mocked AWS), and **pytest-xdist** (parallel execution).

### Running

```bash
cd backend
source .venv/bin/activate
pytest -q -n auto            # parallel; -n auto uses all cores
```

The full run takes roughly 15 to 25 minutes. `HYPOTHESIS_PROFILE` selects a
Hypothesis profile from `tests/conftest.py` (`quick` for a fast pass, `ci` for
more examples); see [Local checks](local-checks.md) for the quick command.

To run a subset, target a directory or file:

```bash
pytest -q tests/services
pytest -q tests/router/test_handler.py
```

### Layout

Tests under `backend/tests/` mirror the package layers:

| Directory | Focus |
| --- | --- |
| `services/` | Business-logic unit and property-based tests |
| `adapters/` | External integrations (RentCast, autocomplete, S3 files) |
| `repository/` | DynamoDB single-table access and the key scheme |
| `router/` | HTTP routing, request parsing, and result -> HTTP mapping, plus cross-user authorization |
| `models/` | Model and serialization helpers |
| `infra/` | Checks on `infra/template.yaml` (functions, IAM, lifecycle rules, throttles) |
| `integration/` | End-to-end flows across layers |
| `util/` | Shared helpers |

### Test styles

- **Unit tests** exercise a single service or function with fakes injected via
  the router `configure(...)` / `reset_wiring()` seams.
- **Property-based tests (Hypothesis)** assert invariants across generated
  inputs - for example, that money round-trips exactly as two-decimal strings,
  that depreciation schedules sum correctly, and that reports are reproducible
  from persisted data.
- **Integration tests** wire the layers together (with moto-backed DynamoDB/S3)
  to check whole flows such as import -> draft -> confirm -> report.

### What the tests protect

The suites encode the core invariants:

- Money stays exact (`decimal.Decimal`, two-decimal strings; no floats/Number).
- Reports are reproducible from persisted records.
- Property creation succeeds even when RentCast is unavailable.
- Drafts remain separate from transactions until confirmed.
- Itemized detail never changes a line that has an entered total, the report,
  dashboard, carryforward and exports agree, and the `imported` and `itemized`
  markers survive edits, backups and re-import.
- The Year-end checklist stays read-only, agrees with the report, and keeps its
  thresholds in one place (see [Year-end checklist tests](#year-end-checklist-tests)).
- Result-to-HTTP status mapping is correct (see [API reference](api.md)).

## Frontend

Frontend tests use **vitest** with the React Testing Library setup under
`frontend/src/test/`.

### Running

```bash
cd frontend
npm test          # vitest run
npm run build     # tsc -b + vite build; must exit 0
npm run lint      # ESLint
npm run typecheck # tsc --noEmit
npm run e2e       # Playwright browser specs (npm run e2e:install once first)
```

Component and page tests live alongside the code they cover (for example
`App.test.tsx`, `components/AppLayout.test.tsx`). The production build
(`npm run build`) doubles as a type-check gate and must exit cleanly; remove the
generated `dist/` directory afterward if you are only verifying.

Browser specs live in `frontend/e2e/` and run against a local Vite server with
every API call mocked: `a11y.spec.ts`, `responsive.spec.ts`, `palette.spec.ts`,
`sidebar-guard.spec.ts`, `onboarding.spec.ts`, `activity.spec.ts` and
`smoke.spec.ts`. The sections below say what each covers; the developer guide
explains the fixtures and the auth bypass.

## Year-end checklist tests

The Year-end checklist is covered by backend tests in
`backend/tests/services/test_checklist*.py` and frontend tests under
`frontend/src/components/year-end-checklist/`, plus
`frontend/src/pages/YearEndChecklistPage.test.tsx`.

### Backend

Property tests (Hypothesis, `*_property.py`):

- Rules and config: `test_checklist_rules_property.py` (carryforward mapping,
  itemized repairs), `test_checklist_report_rules_property.py`,
  `test_checklist_loan_rule_property.py`, `test_checklist_swings_property.py`,
  `test_checklist_edited_imports_property.py`,
  `test_checklist_config_property.py` (config validation),
  `test_checklist_thresholds_property.py` (comparisons are inclusive) and
  `test_checklist_threshold_interpolation_property.py` (applied thresholds are
  echoed in the Reason text).
- Shape and values: `test_checklist_shape_property.py` (counts, determinism),
  `test_checklist_money_property.py` (money in wire form) and
  `test_checklist_helpers_property.py` (recent-year selection, links embed only
  validated ids and the year).
- Agreement, run through the real services over moto:
  `test_checklist_agreement_property.py` (detail line totals equal the report),
  `test_checklist_route_agreement_property.py` (counts match across the three
  routes) and `test_checklist_backup_property.py` (edited classification
  survives backup and restore).

Read-only and read-sharing tests:

- `test_checklist_read_only_property.py` runs the checklist, the property
  summary and the dashboard summary over generated data and asserts zero
  repository writes.
- `test_checklist_read_sharing_property.py` asserts that upstream reads are
  shared within a request instead of repeated per item or per property.

Example tests: `test_checklist_rules.py` (every status branch of items 1 to 11
with exact Reason text), `test_checklist_config.py`, `test_checklist_service.py`,
`test_checklist_edited_import.py` and `test_checklist_seams.py` (the read seams
`LoanService.year_facts`, `TransactionService.has_receipt` and
`resolve_category_rows`).

Source scans:

- `test_checklist_config.py` checks that none of the default threshold numbers
  appears as a literal in `services/*.py` outside `checklist_config.py`. Change
  a threshold in the Checklist_Config only.
- `test_checklist_service.py` parses `checklist.py` and fails if it compares
  against `STATUS_TOLERANCE` or sums over `schedule_e_line`, so the checklist
  reuses the report and reconciliation results instead of recomputing them.

Provider contract test: `test_checklist_provider_contract.py` checks that
`provider_for(wiring, user)` accepts a `UserContext` or a user id string, that
`checklist_for(property_id, tax_year)` matches `ChecklistService.checklist_for`
without writing, and that a wiring missing a collaborator makes `provider_for`
raise. When `logstead.services.accountant_package` is importable it also checks
that the package includes `checklist/year-end-checklist-<year>.json` and still
builds when the checklist module cannot be imported.

### Frontend

- Property tests: `yearEndText.property.test.ts` (needs-attention items come
  first, relative order kept) and `yearEndText.counts.property.test.ts` (counts
  text and the "All clear" headline).
- Component and page tests: `YearEndChecklistPage.test.tsx`,
  `YearEndSummarySection.test.tsx`, `YearEndDashboardCard.test.tsx` and
  `YearEndItemDetails.test.tsx`.
- Source scan: `noHardCodedThresholds.test.ts` parses the feature files with
  TypeScript and fails on any numeric literal other than `0`, `1` and `-1` in
  non-string code. Thresholds come from the API, never from the UI.

Run the backend set with `pytest -q -n auto tests/services -k checklist` and the
frontend set with `npm test -- year-end-checklist YearEndChecklistPage`.

## Accountant package tests
The accountant package (report PDFs, the package ZIP and the asynchronous
package job) is covered by backend tests under `backend/tests/` and frontend
tests under `frontend/src/`. Backend tests run over moto with no AWS account.

### PDF text extraction approach
PDFs are verified by reading them back, not by comparing bytes. Tests extract
the text of every page with `pypdf` (`PdfReader(io.BytesIO(pdf)).pages`,
`page.extract_text()`), collapse whitespace, and then assert on the text. For
example, they check that each report figure appears in its two-decimal wire
form and that the package PDF agrees with `ReportingService.report_for`.
Determinism is the one byte-level check: rendering the same report with the
same generated-on date twice yields identical bytes.

### Backend property tests (Hypothesis, `*_property.py`)
Under `tests/services/`:
- PDF renderer: `test_report_pdf_content_property.py` (the text carries every
  report figure), `test_report_pdf_money_property.py` (money format round
  trip), `test_report_pdf_safety_property.py` (user text is made safe for the
  PDF), `test_report_pdf_determinism_property.py`,
  `test_report_pdf_repairs_property.py` (Repairs appendix) and
  `test_report_pdf_combined_property.py` (combined portfolio layout and totals).
- Package contents: `test_package_report_agreement_property.py` (package PDF,
  CSV and JSON equal the report, built over moto),
  `test_package_transactions_csv_property.py` (transactions CSV round trip),
  `test_package_manifest_property.py` (the manifest matches the real ZIP, and
  money and counts keep their wire form) and `test_package_paths_property.py`
  (entry paths and S3 keys are safe and unique).
- Safety and isolation: `test_csv_safe_property.py` (spreadsheet formula
  neutralization), `test_package_write_set_property.py` (a build writes only
  the ZIP and the job record), `test_package_message_leak_property.py`
  (messages never expose internals) and
  `test_report_combined_export_key_property.py` (combined export keys are scoped
  to the user).
- Job state: `test_package_job_state_property.py` (job state classification).

### Backend example tests
- `tests/services/test_report_pdf.py` (PDF renderer examples),
  `test_accountant_package.py` and `test_accountant_package_smoke.py`
  (`PackageBuilder` over moto) and `test_package_checklist_contract.py` (the
  built package's checklist import contract; the provider side is in
  `test_checklist_provider_contract.py`).
- Worker and job tests: `test_package_worker.py` (the worker handler, run
  under `mock_aws`) and `test_package_jobs.py` (`PackageJobService`).
- Routes: `tests/router/test_pdf_routes.py` covers the PDF routes, including
  the 400, 503 and conflict responses and that other users' properties look
  like missing ones.
- `tests/router/test_package_routes.py` covers the package job routes (create
  returns 202 and calls the invoker once, list order and limit, 409 for an
  active job, 400 field errors, 503 with no worker configured, and no route for
  `PUT` and `PATCH`).
- `tests/router/test_cross_user_authorization.py` is extended to the package
  and PDF routes: another user's job, property and `propertyIds` entries get
  responses identical to a missing id, with no S3 read or write.

### Template test
`tests/infra/test_template_accountant_package.py` parses `infra/template.yaml`
(CloudFormation `!` intrinsics become `{"!Tag": value}` mappings) and asserts
the package worker function and its limits, its narrow policy, the API invoke
and delete grants, the lifecycle rules, the throttled routes and the
asynchronous invoke configuration. It also checks that the CSP resource and the
DynamoDB table are unchanged from a recorded fingerprint. Update the
fingerprint deliberately when you change either one.

### Frontend and end-to-end
- Unit and component tests: `lib/packageJob.test.ts` (polling interval,
  terminal states, labels, size and validity formatting),
  `api/accountantPackage.test.ts`,
  `components/accountant-package/usePackageJob.test.ts` and
  `pages/AccountantPackagePage.test.tsx` (idle, progress, completed, skipped
  receipts, failed and retry, resumed polling and delete).
- Playwright specs under `frontend/e2e/`: `smoke.spec.ts` prepares a package
  and follows the download link, and `a11y.spec.ts` checks the
  `/accountant-package` page.

Run the backend set with
`pytest -q -n auto tests/services tests/router/test_pdf_routes.py tests/infra/test_template_accountant_package.py -k "package or pdf or csv_safe or combined_export or template"`
and the frontend set with `npm test -- packageJob accountantPackage usePackageJob AccountantPackagePage`.

## Responsive viewport checks

`frontend/e2e/responsive.spec.ts` (Playwright, run with `npm run e2e`) covers
small screens:

- Widths 320, 375, 768, 1023 and 1280 in the light and dark Themes: each
  primary route (dashboard, properties, property overview, transactions,
  assets, loans, property and combined reports, profile) has no horizontal page
  scroll and no axe violation.
- Property tabs at 375, 768 and 1023: the disclosure opens by keyboard, shows
  `aria-current` on the current section, closes on Escape with focus back on
  the button, and closes and updates its label after a link is chosen. Where
  the wrapping row shows, the spec clones a `li` to simulate the seven-tab set
  (year-end checklist) and asserts at most two rows and no horizontal scroll.
  Keep this check: it decides whether `md` stays the disclosure breakpoint.
- The add-transaction modal at 320x640: Save and the panel stay inside the
  viewport and every form control computes at least 16px.

Unit tests cover the pieces: `propertySections.property.test.ts` (section
resolver round trip), `PropertySectionTabs.test.tsx`, `RecordModal.test.tsx`
(`dvh` and footer slot), `ResponsiveTable.test.tsx` and `touchTargets.test.tsx`
(16px control classes).

## Command palette and keyboard shortcut tests

Unit and property tests (vitest, fast-check) sit beside the code:

- `lib/shortcuts/eligibility.property.test.ts` (plain-key and chord rules),
  `sequence.property.test.ts` (two-key sequences and the timeout) and
  `registry.test.ts` (no duplicate key combinations).
- `components/palette/paletteItems.property.test.ts` (items and action
  resolution), `paletteRank.property.test.ts` (matching, ranking, highlight
  wrap), `CommandPalette.test.tsx` and `CommandPalette.search.test.tsx`.
- `components/shortcuts/ShortcutsProvider.test.tsx` (listener, `g` sequences,
  ignored in fields and with an open dialog, help dialog).
- `lib/navigationGuard.test.tsx`, `lib/useNewParam.test.tsx`,
  `lib/useFocusParam.test.tsx`, plus the guard cases in `MainNav.test.tsx`.

Browser specs (Playwright, `npm run e2e`):

- `frontend/e2e/palette.spec.ts`: the chord and header button open the palette
  and Escape returns focus; typing filters and arrows with Enter navigate; `g`
  sequences navigate; shortcuts are ignored in a field and with an open
  `RecordModal`; `?` opens the help dialog; a dirty Imports form shows the
  discard confirm; reduced motion; axe in the light and dark Themes; and a
  320px run.
- `frontend/e2e/sidebar-guard.spec.ts`: with a dirty Imports form a sidebar
  click shows "Discard changes?"; Keep editing stays, Discard navigates.

## Global search tests

Backend (pytest, Hypothesis):

- `tests/services/test_search_match_property.py`: normalization is idempotent,
  tokens are well formed, every match contains every token, pattern characters
  are literal, sort order is deterministic.
- `tests/services/test_search_service_property.py`: matching (Property 8),
  order and determinism (10), user scoping and shape (11), money and link
  pass-through (12), scan cap and truncation (13). Examples cover the default
  cap of 20,000, a corrupt loan error, the `propertyId` filter, fields that are
  not searchable and validation errors. Property 13 documents the `truncated`
  behavior at the exact cap (see the open point in `docs/developer-guide.md`).
- `tests/router/test_search_routes.py`: six groups with string money, property
  filter and user scoping, 400s, identical 404 for a bad, missing or foreign
  `propertyId`, `GET` only, authentication, and that the query is never logged.
- `tests/infra/test_template_accountant_package.py`: the `GET /search` throttle
  and `ThrottledSearch` route.

Frontend (vitest, fast-check): `api/search.test.ts`,
`components/palette/CommandPalette.search.test.tsx`, `pages/SearchPage.test.tsx`,
`lib/highlight.property.test.ts`,
`lib/safeLink.property.test.ts` and `lib/useFocusParam.test.tsx`.

Browser specs (Playwright, `npm run e2e`) stub `GET /search` in
`frontend/e2e/fixtures.ts`; `frontend/e2e/palette.spec.ts` covers typing a
query, grouped results, Enter on a hit, "See all results" and the Search page
with axe in both Themes.

## Setup guide and empty-state tests
Unit and property tests (vitest, fast-check) sit beside the code:
- `lib/onboardingStorage.property.test.ts` (setup state serialization round
  trip, defaults for malformed input, per-user keys) and
  `components/dashboard/checklist.property.test.ts` (step derivation).
- `components/dashboard/ChecklistCard.test.tsx` ("Next" label and reason,
  collapse and expand, the all-done state and Dismiss, the live region, the
  sample data link, the existing "x of 4 done" and dismiss assertions).
- `components/AppLayout.setupGuide.test.tsx` and `components/ProfileMenu.test.tsx`
  ("Show setup guide" from the menu and the palette, focus on the heading).
- `components/ui/EmptyGuide.test.tsx` (the component, no tax-advice phrasing in
  `EMPTY_COPY`, each entry names what the page records),
  `components/dashboard/DashboardEmptyState.test.tsx` and the page tests for the
  empty states (`PropertiesPage.test.tsx` and the other list and report pages).

Browser spec (Playwright, `npm run e2e`): `frontend/e2e/onboarding.spec.ts`.
With one property and no transactions the guide shows "Next" and no sample data
link. With no property the dashboard shows the empty state with "Explore with
sample data" (to `/profile?focus=backup`), and `/properties` shows its empty
state with the same link. Other cases: collapse and expand by keyboard (Enter and
Space, state kept after reload), dismiss persisting across a reload, "Show setup
guide" from the account menu and from the palette with focus on the heading,
reduced-motion emulation showing no animation classes or computed animations,
and axe in the light and dark Themes for the expanded guide, the collapsed guide
and the empty Properties page.
## Activity history tests

Backend (pytest, Hypothesis; the repository is moto-backed):
- `tests/repository/test_activity_keys.py`: the `ACT#` key, its 14-digit
  inverted time and newest-first order.
- `tests/services/test_activity_config.py`: the retention constant
  (`retention_days`, 730). Tests and docs read the constant; none repeats 730.
- `tests/services/test_activity_events_property.py`: the allow-list projection,
  `diff`, bounds and truncation, summaries, cursor encoding and `ttl`.
- `tests/services/test_activity_recorder.py`: one item per event, GSI1 keys,
  and a failed write that is logged and not raised.
- `tests/services/test_activity_service_property.py`: pagination completeness,
  filters, user scoping, expired events hidden, and no write on a list.
- `tests/services/test_activity_restore_property.py`: the restore round trip,
  a restore that is claimed once, a failed re-create that releases the claim, a
  stale pending claim, a non-restorable event and an unknown event.
- `tests/services/test_activity_isolation_property.py`: reports do not depend on
  activity (including a source scan that the report, dashboard, carryforward,
  loan, depreciation, transaction and backup modules do not import
  `services.activity`), a recording failure leaves the response unchanged, and
  purge on clear, restore and property delete.
- `tests/router/test_activity_routes.py`: one event of the right kind per
  handler, nothing recorded on a `400` or `404` or an unchanged update, list
  filters and pagination, `400` fields, identical `404`s, the `409` reasons and
  methods. `test_cross_user_authorization.py` covers the list, property list and
  restore as another user. The backup tests check that an export has no `ACT#`
  items and `schema_version` stays `"1"`.

Frontend (vitest): `api/activity.test.ts` (paths and query strings),
`lib/activityText.test.ts` (labels and links), `pages/ActivityPage.test.tsx`
(filters, Load more, Restore confirm, `409` handling),
`pages/activityUndo.test.tsx` (the toast Undo calls the create route, never the
restore route, and the list shows a `create` beside the `delete` with no link)
and `pages/PropertyDetailPage.test.tsx` (the Recent activity panel).

Browser specs (Playwright, `npm run e2e`): `frontend/e2e/activity.spec.ts`
(filters, Load more, details, Restore with confirmation and toast, a `409`, the
`g a` shortcut, and the Overview panel including a failing activity route);
`e2e/smoke.spec.ts` deletes a transaction, opens Activity and restores it; and
`/activity` is in the axe route list in `e2e/a11y.spec.ts` for both Themes. The
activity routes are stubbed in `e2e/fixtures.ts`, stateful for the restore flow.

## Adding tests with changes

When you change behavior, add or update tests in the same layer. Prefer a
property-based test when asserting an invariant over many inputs, and an
integration test when a change spans multiple layers.

Keep property-test generators inside the domain the code accepts. Two tests
used to fail intermittently because their generators could produce inputs the
code rightly rejects: a loan that cannot be paid off within the 600-payment
limit, and a Schedule E column with no Rents and too few expense lines, which
the parser prunes as the form's unused totals column. When a property test
fails, first check whether the generated input is one the product should
accept.
