# Logstead

Logstead is a single-user, single-LLC web application for preparing an IRS
**Schedule E (Form 1040)** rental tax return. It captures **year-end Schedule E
totals** and their supporting documents, computes straight-line depreciation
schedules, enriches property data from RentCast (persisted and shown on a
property detail page), and produces per-property and combined Schedule E
reports.

You record one entry per Schedule E line per tax year (the transaction form
defaults new entries to Dec 31 of the selected year) and attach the year-end
statement PDF as evidence under each entry's "supporting documents". A PDF
expense-import flow exists in the backend but is not currently surfaced in the
UI.

It is built as a **serverless AWS application**:

- **Frontend** - a React + Vite + TypeScript single-page app (Tailwind CSS +
  Radix UI), hosted as static assets (S3 + CloudFront). It has Monarch-style
  theming with light/dark/system modes, a profile menu (signed-in email,
  Profile & settings, Sign out), and a per-property detail page showing stored
  enrichment.
- **Backend** - a single monolithic Python 3.12 AWS Lambda behind an API
  Gateway HTTP API with a Cognito JWT authorizer, over a single-table DynamoDB
  design, with binary files (photos, receipts, uploaded PDFs, exported reports)
  in S3.

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
  infra/              AWS SAM template, samconfig, and SPA deploy script
  docs/               Developer, architecture, API, testing, and deployment guides
  .kiro/specs/logstead/   requirements.md, design.md, tasks.md (the source spec)
```

## Quick start

Prerequisites: **Python 3.12**, **Node 18+** (Node 20+ recommended), and npm.

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
npm install
npm test                     # vitest run
npm run build                # type-check (tsc -b) + production bundle
npm run dev                  # local dev server
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

## Status

All spec tasks are implemented and tested: the backend service layer, single
Lambda router, and the SPA are complete, with unit, property-based (Hypothesis),
and integration coverage. See [docs/testing.md](docs/testing.md).

## License

Not yet specified.
