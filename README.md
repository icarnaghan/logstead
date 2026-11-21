# Logstead

Logstead is a single-user web application for preparing an IRS
**Schedule E (Form 1040)** rental tax return. It captures **year-end Schedule E
totals** and their supporting documents, computes straight-line depreciation
schedules, enriches property data from RentCast (persisted and shown on a
property detail page), and produces per-property and combined Schedule E
reports.

You record one entry per Schedule E line per tax year (the transaction form
defaults new entries to Dec 31 of the selected year) and attach the year-end
statement PDF as evidence under each entry's "supporting documents". A PDF
expense-import flow exists in the backend but is not currently surfaced in the
UI. Repairs (Line 14) can optionally be broken into itemized entries on the
Repairs tab; an entered total, when present, still wins and the two are never
added. Your Schedule E data can also be exported to a JSON backup, restored from
one, or cleared.

The **Year-end checklist** (the property page's "Checklist" tab at
`/properties/{propertyId}/checklist`, plus a property page section and a
dashboard card) reviews a property's records for a tax year and lists items
that need attention first. It is a read-only reminder aid and not tax advice:
it stores no data and changes none.

The per-property and combined report pages each have a **Download PDF** button
that produces a Schedule E report PDF. The **Accountant package** page (at
`/accountant-package`) builds a ZIP for a tax year and the properties you pick:
the Schedule E reports (PDF, CSV, JSON), a transactions CSV, your receipts, and
a manifest. The PDF report and the Accountant package are organizing aids for
sharing your records, not tax advice.

Other features:
- **Seven property tabs.** Overview, Transactions, Repairs, Depreciable Assets,
  Loans, Schedule E Report and Checklist. On screens narrower than 768px the
  tabs collapse into a "Property sections" menu.
- **Command palette and shortcuts.** Cmd+K (Ctrl+K elsewhere) or `/` opens a
  palette that jumps to pages, properties and tax years and runs actions such
  as adding a record or switching theme. `?` lists the shortcuts, and `g` then
  `d`, `p`, `r`, `c`, `i` or `a` goes to a page.
- **Search.** Find properties, transactions, repairs, assets, loans and
  businesses by text from the palette or the Search page (`/search`).
- **Activity history.** The Activity page (`/activity`) lists what changed,
  with before and after values, and can restore a deleted record. Events are
  kept for 24 months.
- **Onboarding guide.** The Dashboard setup guide shows the next step, can be
  collapsed or dismissed, and can be shown again from the account menu or the
  palette. Empty pages explain what they record, and the dashboard and
  Properties empty states offer sample data.
- **Responsive layout.** Forms and tables fit narrow screens, and modal forms
  keep Cancel and Save in view.

It is built as a **serverless AWS application**:

- **Frontend** - a React + Vite + TypeScript single-page app (Tailwind CSS +
  Radix UI), hosted as static assets (S3 + CloudFront). It has Monarch-style
  theming with light/dark/system modes, a profile menu (signed-in email,
  Profile & settings, Sign out), and a per-property detail page showing stored
  enrichment. The Profile & settings page also hosts Backup & restore - download
  a JSON backup, restore from a backup file, clear all data, or load sample data.
- **Backend** - a single monolithic Python 3.12 AWS Lambda behind an API
  Gateway HTTP API with a Cognito JWT authorizer, over a single-table DynamoDB
  design, with binary files (photos, receipts, uploaded PDFs, exported reports)
  in S3.
- **Package worker** - a second Lambda (`logstead-package-worker`, same source
  as the API function, different handler) that builds accountant package ZIPs.
  The API starts it with an asynchronous invoke.

> Scope: the initial release is deliberately narrow - everything needed to
> prepare the federal Schedule E for the rental activity, and nothing more.

## Repository layout

```
logstead/
  backend/            Python 3.12 Lambda: services, repository, adapters, router
    src/logstead/     Application package (router, services, repository, adapters, models, util)
    tests/            pytest + Hypothesis + moto (unit, property, integration)
    pyproject.toml    Package + pytest/hypothesis config
    requirements*.txt
  frontend/           React + Vite + TypeScript SPA
    src/              api/, components/, pages/, auth/, lib/
  infra/              AWS SAM template, deploy/seed scripts, and samconfig.toml.example
  docs/               Developer, architecture, API, testing, and deployment guides
  Makefile            Top-level dev + deploy commands (run `make help`)
  .kiro/specs/        One folder per feature spec (requirements.md, design.md,
                      tasks.md); .kiro/specs/logstead/ is the original app spec
```

## Quick start

Prerequisites: **Python 3.12**, **Node 18+** (Node 20+ recommended), and npm.

The quickest path is the top-level `Makefile` (run `make help` for the full
list). Common commands:

```bash
make install        # backend venv (dev extras) + frontend deps
make test           # backend (pytest) + frontend (vitest)
make dev            # frontend dev server
make deploy         # build + deploy infra (SAM) then publish the SPA
```

`make deploy` reinstalls the frontend dependencies with `npm ci` (a clean,
lock-exact install that deletes `node_modules` first) before it builds the SPA,
so there is no need to clear `node_modules` by hand before a deploy.

The steps below are the equivalent manual commands.

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"      # or: pip install -r requirements-dev.txt
pytest -q -n auto            # runs the suite in parallel (pytest-xdist)
```

### Frontend

```bash
cd frontend
npm ci                       # lock-exact install (npm install also works)
npm test                     # vitest run
npm run build                # type-check (tsc -b) + production bundle
npm run lint                 # ESLint
npm run dev                  # local dev server
npm run e2e                  # Playwright (run `npm run e2e:install` once first)
```

Copy `frontend/.env.example` to `frontend/.env` and fill in the Cognito / API
values before running the SPA against a real backend. See
[docs/developer-guide.md](docs/developer-guide.md).

## Documentation

- [Architecture overview](docs/architecture.md) - components, data flow, and the
  single-table DynamoDB design.
- [Developer guide](docs/developer-guide.md) - environment setup, project
  conventions, and day-to-day workflow.
- [API reference](docs/api.md) - the HTTP API routes, auth, and error model.
- [Data model](docs/data-model.md) - domain entities and the DynamoDB key scheme.
- [Testing guide](docs/testing.md) - unit, property-based, and integration tests.
- [Deployment](docs/deployment.md) - how the pieces map onto AWS.
- [Local checks](docs/local-checks.md) - the checks to run before merging (there
  is no hosted CI).
- [Dependency policy](docs/dependency-policy.md) - pinning, audits, and upgrades.
- [Future improvements](docs/future-improvements.md) - deferred work and known
  limitations.
- [Changelog](CHANGELOG.md) - notable changes per release.

## Key design rules

These invariants run through the whole codebase (see
[docs/architecture.md](docs/architecture.md) for detail):

- **Money is exact.** Monetary values are `decimal.Decimal` in code and stored
  as fixed two-decimal **strings** in DynamoDB - never floats, never DynamoDB
  `Number`.
- **Reports are reproducible from persisted data alone.** Aggregations are
  derived on demand, never cached as the source of truth.
- **RentCast is optional enrichment, never a gate.** Property creation always
  succeeds regardless of enrichment availability. Enrichment details captured at
  creation are persisted and returned on read (shown on the property detail
  page).
- **Drafts are not transactions.** In the backend, imported PDF line items stay
  as draft staging items until explicitly confirmed. (The import flow is not
  part of the current UI.)
- **Authentication is delegated.** Cognito Hosted UI handles sign-in; the API
  trusts the JWT authorizer verified claims and performs no token verification
  itself.
- **History never feeds reports.** Activity events are recorded by the router
  only, best effort, and no report, dashboard or carryforward code reads them.

## Status

All spec tasks under `.kiro/specs/` are implemented and tested, with unit,
property-based (Hypothesis and fast-check), integration and Playwright browser
coverage. See [docs/testing.md](docs/testing.md). Deferred work and known
limitations are in [docs/future-improvements.md](docs/future-improvements.md).

## License

Not yet specified.
