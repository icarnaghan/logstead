# Changelog

All notable changes to Logstead are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Released
versions correspond to git tags.

## [Unreleased]

## [1.2.0] - 2026-11-21

A minor release adding mortgage loans, the passive loss carryforward, business
entities, Schedule E import (manual and PDF extraction), itemized Repairs, the
Year-end checklist, Schedule E PDF reports and the accountant package, plus a
command palette, global search, activity history, an onboarding guide and a
responsive layout. Adds one Lambda (the package worker); no data migration.

### Added
- **Activity history.** A new Activity page (`/activity`, `g` then `a`, under
  Tools) lists what changed, newest first: transactions, repairs, assets, loans,
  properties, Schedule E imports and backup restores, with before and after
  values for the allow-listed fields. Filter by property, kind and action, and
  use Load more for older events. Restore on a deleted transaction, repair,
  asset or loan re-creates it with a new id and records a restore event. The
  Undo toast is unchanged: it stays client-side and shows in the history as an
  ordinary create. The property Overview shows the latest five events. New
  routes `GET /activity`, `GET /properties/{propertyId}/activity` and
  `POST /properties/{propertyId}/activity/{eventId}/restore`. Events expire
  after 24 months, are left out of backups, and are deleted by "Clear all data",
  by restoring a backup and with their property. Recording is best effort and
  never changes the result of a save. Reports do not read the history.
- **Setup guide and empty-state guidance.** The Dashboard setup guide marks the
  first unfinished step with a "Next" label and a one-sentence reason, collapses
  and expands (the choice is remembered per user), and shows "You're set up"
  with Dismiss when all four steps are done. A screen reader hears when a step
  completes. "Show setup guide" in the account menu and the command palette
  clears a dismissal, returns to the Dashboard and focuses the guide. Empty
  Transactions, Repairs, Assets, Loans, Properties, Reports and Combined Reports
  pages now say what the page records and how it reaches Schedule E, with a
  primary action. The Dashboard and Properties empty states link to "Explore with
  sample data" (Profile, Backup) while you have no property; sample data replaces
  all current data. Frontend only.
- **Command palette and keyboard shortcuts.** Press Cmd+K (Ctrl+K on other
  systems), `/`, or use the header Search button to open a palette that jumps
  to pages, properties, property sections and tax years, and runs actions: add
  a property, transaction, repair, depreciable asset or loan, import Schedule E,
  switch theme, show the keyboard shortcuts, show the setup guide and download a
  backup. Press `?` for the shortcut list. `g` then `d`, `p`, `r`, `c`, `i` or
  `a` goes to Dashboard, Properties, Reports, Carryforward, Import or Activity. Plain-key
  shortcuts are ignored while typing in a field or with a dialog open. Add
  actions open the matching form through a `?new=1` link; `/reports?year=YYYY`
  selects a tax year. Frontend only.

- **Global search.** New `GET /search?q=&limit=&propertyId=` route (read-only,
  throttled to 2 requests per second, burst 5) finds properties, transactions,
  repairs, assets, loans and businesses by text: descriptions, notes, names,
  addresses and legal names. The query is plain text, matched in any case, and
  amounts, dates and category labels are not searched. The command palette
  shows grouped results with a "See all results" link to a new Search page at
  `/search?q=`. Result links open the record's page with `?focus={id}`, which
  scrolls to and focuses the row. Search reads at most 20,000 records and sets
  `truncated` when it stops early; the page then says results may be
  incomplete. The flag is also set when the cap is reached exactly and the
  unread properties are empty.

- **Schedule E PDF report.** `POST /properties/{propertyId}/report/pdf` and
  `POST /reports/combined/pdf` render the Schedule E worksheet as a PDF, stored
  under `exports/pdf/<userId>/...`, and return a short-lived download link. The
  PDF is an organizing aid, not tax advice. Text outside Windows-1252 prints as
  `?`. The PDF is built with the new ReportLab dependency.
- **Accountant package.** A ZIP for one tax year, built in the background by a
  separate worker Lambda. New routes: `POST` and `GET /accountant-packages`,
  and `GET` and `DELETE /accountant-packages/{jobId}`. Packages are stored
  under `exports/packages/` and, like the PDFs, expire after one day. The create
  route returns `503` when the worker is not configured. It is an organizing
  aid, not tax advice.
- **New dependency: `reportlab==5.1.0`.** Pinned in `backend/requirements.txt`
  and listed in `backend/pyproject.toml` (the two files must change together).
  It adds about 8.9 MiB to the unzipped Lambda package; see
  `docs/dependency-policy.md`.
- **Year-end checklist.** A read-only reminder aid, not tax advice, that checks
  a property's records for a tax year. It stores no data of its own and has no
  control that changes data. The property page now has a seventh tab,
  "Checklist" (`/properties/{propertyId}/checklist`), with a year picker. The
  property page also gets a Year-end checklist section with one row per year,
  and the dashboard gets a Year-end checklist card. Items that need attention
  are listed first. New routes: `GET /properties/{propertyId}/checklist`
  (takes `taxYear`), `GET /properties/{propertyId}/checklist/summary` and
  `GET /checklist/summary`. The Transactions and Reports pages now read a
  `?year=` query parameter for the initial tax year, so checklist links open
  on the right year. The service exposes a `provider_for(wiring, user)` hook
  that returns a `ChecklistProvider`, which the accountant package imports at
  run time.
- **Itemized Repairs.** A new Repairs tab on the property page
  lets you keep line-item detail (date, amount, description/vendor, notes,
  documents) behind Schedule E Line 14. An entered total still wins on the line
  and the itemized sum is used only when no total exists; the two are never
  added. The page shows the remainder, flags entries that exceed the total, and
  offers "Update total to itemized sum" with a confirmation and Undo. Itemized
  rows are badged and read-only on the Transactions page. New routes under
  `/properties/{propertyId}/itemized/{categoryId}` (summary, entries, total).
  Backups carry optional `itemized`, `notes` and `imported` transaction fields
  (`schema_version` stays `"1"`; restore a backup made with this feature on a
  version that includes it).

- **Business entities.** A Businesses section records the entities that own or
  operate properties, with legal details and supporting documents, and a
  property can be linked to its owning business. Routes under `/businesses`.
- **Schedule E import.** The Import nav entry enters a prior year's Schedule E
  Part I figures per property, manually or by uploading the return PDF (read
  with Amazon Textract into a reviewable draft). Imported rows carry an
  `imported` marker, and a re-import replaces them. Routes under
  `/imports/schedule-e`.
- **Passive loss carryforward.** A Carryforward page reconciles the reported
  prior-year unallowed loss for each year against the expected chain from the
  Schedule E results, with an opening balance. Routes under `/carryforward`.
- **Dashboard trends and asset summary.** Year-over-year income, expense and
  net trends per property and for the portfolio (`GET /dashboard/trends`), and
  a depreciable assets summary (`GET /dashboard/assets`).
- **Per-year depreciation overrides.** An asset's computed depreciation can be
  replaced for a given year to match a filed return. Tax-oriented displays round
  to whole dollars like the return; stored values and math stay exact.
- **Loans projected from a known balance.** A property can have one or more
  loans. A loan is an interest rate, a monthly principal-and-interest payment,
  and one known balance (the anchor balance) on one date (the anchor date).
  Logstead projects the monthly schedule forward from the anchor and derives the
  remaining payments, payoff date and final smaller payment. Original principal
  and closing date are optional and informational. Extra principal and an early
  payoff date are supported. The loan input model changed before release, so no
  migration is needed; any loans created locally with the earlier
  origination fields (term, first payment date, payment override) must be
  re-entered.
- **Per-year Form 1098 interest override, including past years.** The interest
  for a loan and tax year can be replaced with the figure from the lender's Form
  1098; removing the override returns to the generated amount. Overrides are
  accepted for any year from 1900 through the anchor year, including years with
  no generated payments, which are stored as override-only yearly totals with a
  `null` ending balance. The anchor year's estimate covers only payments after
  the anchor date.
- **Generated loan interest feeds Schedule E Line 12 and the carryforward.**
  Loan interest flows into Line 12 for each property report and the combined
  report, and from there into expenses, net income and the passive loss
  carryforward. Loans can be left out of reports with `include_in_report`.
- **Loans page and property tab.** A Loans tab on the property page lists a property's loans,
  shows each schedule and yearly interest, edits overrides, and notes the years
  where loan interest replaces hand-entered mortgage interest.
- **Loans in backup and restore.** `GET /backup` exports loans and their
  interest overrides and restore brings them back. Schedules and yearly totals
  are derived on restore. `schema_version` stays `"1"`; older builds ignore the
  `loans` section on restore.
- **Loan routes.** `POST` and `GET /properties/{propertyId}/loans`,
  `GET`, `PUT` and `DELETE .../loans/{loanId}`, `GET .../loans/{loanId}/schedule`,
  `PUT` and `DELETE .../loans/{loanId}/interest-overrides/{taxYear}`, and
  `GET .../loans/line-12-impact`.
- **`line12` on report responses and exports.** Each property report includes a
  `line12` object (`total`, `source`, `superseded_manual_interest`) and the
  combined report includes a top-level `line12`. CSV and JSON exports carry the
  same figures. The new fields are additive.
- **`errors` on validation failures.** Validation errors that involve more than
  one field carry an additive `errors` list of `{field, message}` entries; the
  top-level `field` and `message` still describe the first entry.
- **`GET /carryforward` `status_tolerance`.** The summary now includes
  `status_tolerance`, the largest difference still treated as a match, as a
  two-decimal string (`"2.00"`). The new field is additive.
- **`GET /properties/{propertyId}/earliest-year`.** A read-only route returning
  `{"earliest_year": <int or null>}`: the earlier of the property's oldest
  transaction year and its earliest asset placed-in-service year, or `null`
  when it has neither. It returns 404 for a property the user does not own.

- **`GET /carryforward` carry-in fields.** Each year now includes
  `expected_carry_in`, and the summary includes `next_year` (integer or null)
  and `next_year_expected_carry_in`, all money values as two-decimal strings.
  The existing fields (`expected_carryforward` as the carry-out,
  `reported_carryforward` as the carry-in, `drift`, `status`, and so on) keep
  their names, and the new fields are additive.
- **Carryforward chain break summary.** The page shows a summary above the
  table when a year is a mismatch, naming the year the chain first breaks, the
  amount that appears dropped there, any further separate breaks and the total
  gap; carried rows now hint at the break they inherited. Derived from existing
  fields in the browser; no API change.
### Changed
- **Sidebar links now ask before discarding an unsaved import form** (same guard
  as the command palette). Before this release a sidebar link left a dirty
  Imports form with no prompt. Modified and middle clicks are unchanged.

- **Responsive property tabs and small-screen form fixes.** Below 768px the
  property section tabs collapse into a "Property sections: {current}"
  disclosure button; wider screens keep a wrapping row. Form inputs, selects and
  textareas use 16px text on narrow screens so iOS does not zoom on focus. Modal
  forms keep Cancel and Save in a sticky footer, the modal and sticky tables
  size with `dvh`, and form grids and toolbars fit at 320px. Frontend only.

- **Line 12 uses loan interest instead of hand-entered mortgage interest.** When
  the included loans produce interest above `0.00` for a year, Schedule E
  Line 12 (Mortgage interest paid to banks) is that loan interest and the
  hand-entered Line 12 transactions are not added to it (never both). Otherwise
  Line 12 is the hand-entered amount, as before. The report shows which source
  was used and how much manual interest was superseded.
- **A property with loans cannot be deleted.** `DELETE /properties/{propertyId}`
  now returns `409` while the property still has loans; remove its loans first.
- **Passive loss carryforward — reported value is now the carry-in.** The figure
  entered for each year is the Form 8582 "Prior years unallowed losses" line,
  i.e. the balance carried *into* that year. Previously it was compared with the
  expected end-of-year balance, so every entered figure was checked against the
  wrong year (for example a 2015 form showing the end-2014 balance was flagged
  as a mismatch). Status and drift now compare the reported carry-in of a year
  with that year's expected carry-in, and the chain check applies the prior
  year's step to the prior year's reported carry-in. The running-balance math
  (unallowed portion added, gains absorbed, floored at `0.00`, no IRC §469
  limitation) is unchanged.
- **Carryforward page copy and layout.** The table now shows "Expected entering
  year", "Prior years' unallowed losses (Form 8582)" (the reported editor) and
  "Expected to carry out" columns, a "Expected to carry into {next year}" line
  after the latest year, and status hints that name the prior return to review.
  Helper text, the disclaimer, and docstrings use carry-in / carry-out wording.
- **Carryforward status comparison now has a $2 tolerance.** Returns are filed
  in whole dollars while the expected balances are computed to the cent, so a
  reported figure within $2.00 of the expected carry-in (or of the chain value)
  is now treated as matching and no longer flagged as a mismatch. Drift and the
  expected values stay exact to the cent, and the status precedence and
  root-cause attribution are unchanged. The page notes the tolerance beneath
  the table.
- **Carryforward mismatch hint names the line to check.** The hint now says
  what the prior return carried out and what this return's line shows, and
  points to this year's Form 8582 line and the prior return's carry-out.
- **Year pickers start at the property's earliest activity.** The Reports,
  Transactions and Property Detail year pickers now begin at the year of the
  property's earliest transaction or asset placed-in-service date (still
  ending at the latest completed tax year) instead of a fixed window or the
  earliest asset alone. A property with no data keeps the existing window.
- **Server CSV export neutralizes formula-like text cells.** In the server-side
  CSV export, a text cell (property name, address, property type, other-item
  description) that starts with `=`, `+`, `-`, `@`, a tab or a carriage return
  now gets a leading apostrophe so spreadsheets do not run it as a formula. This
  affects rare values only; the browser CSV download is unchanged.
### Fixed

- **Combined export key is now scoped to the user.** Server combined report
  exports are written to `exports/combined/<user_id>/<tax_year>/<filename>`
  instead of a key without the user id, which could let two users overwrite each
  other's export for the same year.
- **Editing an imported total no longer allows a duplicate on re-import.**
  Generic transaction updates now preserve the stored `imported` marker, so a
  later Schedule E import replaces the edited row instead of adding a second
  total. Backups now carry `imported` as well.
- **Receipts follow a transaction when its date is edited.** Changing a
  transaction's date moved the row but left its receipts under the old key, so
  they disappeared and their files leaked. They now move with the transaction.
- **Amount errors name the field.** An unparseable or oversized amount now
  returns `field: "amount"` on the transaction, asset and loan routes.
- **Long rows no longer break the Schedule E PDF.** A table row taller than a
  page (for example a very long Repairs description) now splits across pages
  instead of failing the render.
- **Intermittent backend test failures.** The loan payoff round-trip and
  Schedule E extraction money property tests could generate inputs the code
  correctly rejects (a loan that cannot be paid off in 600 payments, a column
  the parser prunes as the form's totals column). Their generators now stay
  inside the valid domain. Test-only change.

- **Schedule E PDF extraction — property column over-counting.** The parser that
  reads a Schedule E Part I page from an uploaded return now derives property
  columns from the printed A/B/C header letters on the located page rather than
  from the widest table's width, so an unrelated wide worksheet elsewhere in the
  return no longer inflates the count (a real 2023 return reported 10 properties
  for 2 actual ones). The Part I page locator was tightened to require
  Schedule-E-specific evidence, so a Schedule C page sharing generic expense
  labels is no longer mistaken for Part I.
- **Schedule E PDF extraction — phantom totals column.** Because the IRS form
  always prints three column headers (A, B, C) even when fewer properties are
  used, the unused header's totals/summary column was being emitted as an extra
  property. Detected columns are now pruned to genuine properties (those with
  rents or real per-property expenses), while a royalty-only property with its
  own expenses is preserved.
- **Schedule E PDF extraction — per-line amount accuracy.** Each amount is now
  anchored to the Schedule E line number the form prints in the row, instead of
  fuzzy-matching the row's label text. This stops the form's dense totals rows
  (lines 20-26) — whose labels mention other lines — from overwriting real
  per-line values. Line 18 (Depreciation) remains excluded throughout.
### Notes

- **Deploy:** the template adds a `logstead-package-worker` Lambda (600 s
  timeout, 1024 MB memory), an `InvokePackageWorker` permission on the API
  function, a `PACKAGE_WORKER_FUNCTION` environment variable, a
  `logstead-package-worker-errors` CloudWatch alarm, and one-day lifecycle rules
  for `exports/packages/` and `exports/pdf/`. Redeploy the stack with
  `sam build` and `sam deploy` (or `make deploy`); no data migration is needed.
  The template also adds route throttles for the package, PDF and search
  routes. The worker reserves 2 concurrent executions: if the deploy fails on
  the account's Lambda concurrency limit, request a quota increase in Service
  Quotas. See `docs/deployment.md`.

- No data migration is needed. The stored per-year value (`PLCF#<year>`,
  `amount`) was already entered as the carry-in; only how it is interpreted
  changed. Storage keys, write routes and validators are untouched.
## [1.1.0] - 2026-10-10

A minor release adding data portability (backup, restore, clear, and sample
data) on the existing Lambda / DynamoDB / S3 architecture, with no new
infrastructure.

### Added

- **Backup export** - `GET /backup` returns a full JSON backup of the
  authenticated user's Schedule E data (properties, details, notes, usage years,
  transactions, assets). Money is serialized as two-decimal strings, and the
  document carries a `schema_version` and `exported_at`.
- **Restore** - `POST /backup/restore` validates the document first, then
  performs a replace-all that preserves original ids and timestamps;
  depreciation schedules are recomputed rather than trusted from the document.
- **Clear** - `POST /backup/clear` deletes all of the user's DynamoDB records and
  their S3 binaries (property photos and transaction receipts), S3-first and
  best-effort.
- **Profile "Backup & restore" section** with four flows - download a JSON
  backup, restore from a backup file, clear all data, and load sample data (no
  new nav entry).
- **Bundled sample dataset** (`frontend/src/data/sample-backup.json`) - two
  properties with five years of Schedule E data, powering "Load sample data".
- Full property-based (Hypothesis / fast-check), integration, and UI test
  coverage for the new feature.

### Changed

- `make deploy-infra` now runs `sam deploy` non-interactively
  (`--no-confirm-changeset --no-fail-on-empty-changeset`) so `make deploy` runs
  unattended.
- Documentation updated across the README and `docs/` (API reference,
  architecture, data model, and developer guide).

## [1.0.0] - 2026-09-26

The initial public release.

### Added

- Serverless AWS application for preparing an IRS Schedule E (Form 1040) rental
  tax return: a React + Vite + TypeScript SPA (S3 + CloudFront) and a single
  Python 3.12 Lambda behind API Gateway with a Cognito JWT authorizer, over a
  single-table DynamoDB design with binary files in S3.
- Properties, transactions (year-end Schedule E totals), depreciable assets with
  straight-line depreciation schedules, usage days, receipts / supporting
  documents, and per-property plus combined Schedule E reports.
- RentCast property enrichment (optional, persisted) and Amazon Location Service
  address autocomplete.
- UX polish and data visualizations; light / dark / system theming.

[unreleased]: https://gitlab.com/carnaghan/logstead/-/compare/v1.2.0...HEAD
[1.2.0]: https://gitlab.com/carnaghan/logstead/-/compare/v1.1.0...v1.2.0
[1.1.0]: https://gitlab.com/carnaghan/logstead/-/compare/v1.0.0...v1.1.0
[1.0.0]: https://gitlab.com/carnaghan/logstead/-/tags/v1.0.0
