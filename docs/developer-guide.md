# Developer Guide

This guide covers setting up a local environment, project conventions, and the
day-to-day workflow for the backend and frontend.

## Prerequisites

- **Python 3.12** (the Lambda runtime target)
- **Node 18+** (Node 20+ recommended) and **npm**
- No AWS account is required for local development or the test suites; external
  services and AWS resources are faked in tests.

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

Runtime dependencies: `boto3`, `pdfplumber`, `pypdf`.
Dev dependencies: `pytest`, `hypothesis`, `moto`, `pytest-xdist`.

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
| `RENTCAST_API_KEY` | RentCast enrichment API key (optional feature) |

Address autocomplete uses **Amazon Location Service** (`geo-places`) via the
Lambda's IAM role - there is no autocomplete API key.

Tests do not require these; the router exposes `configure(...)` and
`reset_wiring()` to inject fakes for the repository, file store, and adapters.

## Frontend

The frontend is a React + Vite + TypeScript SPA at `frontend/`.

### Setup and workflow

```bash
cd frontend
npm install
npm run dev      # local dev server
npm test         # vitest run
npm run build    # tsc -b + vite build (must exit 0)
npm run lint     # tsc --noEmit type-check
```

The `build` output goes to `dist/`; remove it after a verification build if you
do not intend to deploy.

### Environment

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
  components/   Feature components: assets, dashboard, imports, photos,
                properties, reports, transactions, plus AppLayout, MainNav,
                PropertySection, navConfig, ProfileMenu, ThemeToggle
  theme/        ThemeProvider (light/dark/system) and theme context
  pages/        Routed page views (incl. PropertyDetailPage, ProfilePage)
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
- The PDF expense-import flow is not surfaced in the current UI (the
  `ImportReview` components and `/imports/*` routes still exist in the codebase,
  but there is no nav entry or route into them).

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

## The spec

The application was built from a spec under `.kiro/specs/logstead/`:
`requirements.md`, `design.md`, and `tasks.md`. These are the authoritative
source for intended behavior and rationale.
