# Architecture Overview

Logstead is a serverless AWS application for preparing an IRS Schedule E rental
tax return. This document describes the runtime components, how a request flows
through them, and the core invariants that the implementation preserves.

## Components

```
  Browser (React SPA)
        |  HTTPS, Bearer JWT
        v
  CloudFront ---> S3 (static SPA assets)
        |
        v
  API Gateway (HTTP API) --- Cognito JWT authorizer
        |  verified JWT claims on the request context
        v
  Single Python 3.12 Lambda ("API Lambda")
        |  router -> services -> repository / adapters
        +--> DynamoDB (single table)
        +--> S3 (photos, receipts, uploaded PDFs, exported reports)
        +--> Package worker Lambda (accountant package ZIPs, async invoke)
        +--> RentCast API (optional enrichment)
        +--> Address autocomplete provider
```

- **Frontend** - a plain React SPA built with Vite and TypeScript, styled with
  Tailwind CSS and Radix UI primitives. It is client-rendered and served as
  static files from S3 behind CloudFront. There is no server-side rendering.
- **API edge** - API Gateway HTTP API is the single front door. Its native
  Cognito JWT authorizer validates the access token before the request reaches
  the Lambda, and forwards the verified claims on the request context.
- **Compute** - one monolithic Python Lambda handles every route. It routes
  internally to logical services, keeping cold-start surface and operational
  overhead low. A second Lambda (`logstead-package-worker`, same source, a
  different handler) builds accountant package ZIPs in the background; the API
  starts it with an asynchronous invoke.
- **Data** - one DynamoDB table (single-table design) holds all durable records.
  S3 holds binary artifacts; DynamoDB stores only metadata and S3 keys.
- **External services** - RentCast enriches property data; an address
  autocomplete provider helps pick a clean address string. Both are optional to
  the core flow.

## Backend internal layering

The Lambda package (`backend/src/logstead/`) is organized into clear layers.
Business rules live only in services; nothing above the service layer builds
DynamoDB keys or talks to external APIs directly.

```
router/       HTTP routing, request parsing, auth extraction, result -> HTTP mapping
services/     Business logic: auth, property, photo, enrichment, transaction,
              itemized, depreciation, loan, report, report_pdf, dashboard,
              carryforward, checklist, search, activity, accountant_package,
              package_jobs, business, backup, schedule_e_import,
              schedule_e_extraction/parser, expense_import, category
repository/   DynamoDB single-table access; encapsulates the key scheme (keys.py)
adapters/     External integrations: RentCast, address autocomplete, S3 files,
              Textract, PDF parsing, and the package worker invoker
worker/       The package worker Lambda handler (package_worker.py)
models/       Domain models and value types (money as decimal.Decimal)
util/         Shared helpers
```

### Request flow

1. API Gateway validates the JWT and invokes the Lambda with the event.
2. `router/handler.py` matches `(METHOD, path)` against its `_ROUTES` table,
   extracts path params, parses the JSON body, and reads the caller identity
   from `event["requestContext"]["authorizer"]["jwt"]["claims"]`.
3. The matched handler calls the appropriate service.
4. The service applies business rules and uses repositories/adapters for
   persistence and external calls.
5. The service returns a result object, which the router maps to an HTTP
   response (see [API reference](api.md) for the status-code mapping).
6. For a successful mutation, the router records one activity event, best
   effort (`_with_activity` in `router/handler.py`). Services never see the
   recorder, so a recording failure cannot change the response.

### Dependency wiring and test seams

The router exposes `configure(repo=, files=, rentcast=, autocomplete=,
textract=, package_invoker=)` and `reset_wiring()` so tests can inject fakes/mocks for the repository, file store,
and external adapters. This keeps the service layer testable without AWS.

Runtime configuration comes from environment variables: `TABLE_NAME`,
`FILES_BUCKET`, `AWS_REGION`, `PACKAGE_WORKER_FUNCTION`, and the RentCast key
(`RENTCAST_API_KEY`, or the SSM parameter name in `RENTCAST_API_KEY_PARAM`; see
the [Developer guide](developer-guide.md)). Address lookup uses Amazon
Location Service (`geo-places`) via the Lambda's IAM role (no API key), in two
steps: Autocomplete returns candidate buildings, and a follow-up Geocode call
with the `SecondaryAddresses` feature returns a selected building's units
(apartments/suites). The Lambda role is granted both `geo-places:Autocomplete`
and `geo-places:Geocode`.

## Core invariants

These rules hold across the whole system:

- **Money is exact.** All monetary values are `decimal.Decimal` in code and are
  persisted as fixed two-decimal **strings** in DynamoDB - never floating point
  and never DynamoDB `Number`, both of which can drift for financial precision.
  Money is serialized to strings in API responses too.
- **Reports are reproducible from persisted data alone.** A Schedule E report
  can be regenerated from stored transactions, assets, and depreciation inputs.
  Aggregations are derived on demand and are never the source of truth.
- **RentCast is optional enrichment, never a gate.** Property creation always
  succeeds even if enrichment is unavailable; a RentCast outage maps to a 503
  for the enrichment endpoint only.
- **Drafts are not transactions.** In the backend, imported expense-summary
  line items live as separate draft staging items in DynamoDB until the user
  confirms them, at which point they become real transactions. (The expense
  import feature exists in the backend but is not part of the current UI flow -
  the SPA has no expense-import screen. Schedule E import is separate and is
  reachable from the Import nav entry.)
- **One precedence rule for itemized lines.** An entered total wins over
  itemized entries on a line and the two are never added; the rule is
  implemented once (`LineAccumulator`) and shared by reports and the summary.
- **History never feeds reports.** Activity events are written only by the
  router and read only by the activity routes. Report, dashboard, carryforward
  and backup code never import the activity service (a source-scan test
  enforces this), so reports stay reproducible from records alone.
- **Delegated, stateless auth.** Cognito Hosted UI handles sign-in and token
  issuance. The Lambda holds no session state and trusts the API Gateway JWT
  authorizer; it reads verified claims rather than verifying tokens itself.

## Services at a glance

- **auth** - resolves the current user from JWT claims; raises on missing/invalid
  identity.
- **property** - property CRUD, usage days, and enrichment orchestration; also
  persists enrichment `PropertyDetails` supplied at creation (as a single
  `detailsJson` attribute) and returns them on read.
- **transaction** - income/expense records categorized to Schedule E lines, plus
  receipt attachments.
- **itemized** - Repairs line items behind a Line 14 total, and
  `LineAccumulator`, the single implementation of the total-versus-itemized
  precedence rule.
- **loan** - mortgage loans projected from an anchor balance, with yearly
  interest rollups and Form 1098 overrides that feed Line 12.
- **carryforward** - the passive loss carryforward reconciliation.
- **depreciation** - depreciable assets and straight-line schedule computation
  (`compute_schedule_rows`, straight-line with the mid-month convention).
- **expense_import** - PDF parsing into draft line items and confirmation into
  transactions.
- **report** - `ReportingService` produces per-property and combined Schedule E
  reports and exports (`report_for`, `combined_report`, `export_report`,
  `export_combined_report`).
- **report_pdf** - renders the per-property and combined Schedule E PDFs
  (ReportLab) from report objects, with no money arithmetic.
- **dashboard** - `DashboardService` builds portfolio and per-property summaries.
- **checklist** - the read-only Year-end checklist (`ChecklistService`); its
  thresholds live in `checklist_config.py`.
- **search** - `SearchService`, text search over the user's records.
- **activity** - `ActivityRecorder` (used only by the router) and
  `ActivityService` (list and restore).
- **accountant_package / package_jobs** - the ZIP builder the worker Lambda
  runs, and the job records the API creates, lists and deletes.
- **business** - business entities that own or operate properties.
- **schedule_e_import / schedule_e_extraction** - manual Schedule E import and
  the Textract-backed PDF extraction that feeds it.
- **category** - the Schedule E category catalog and seeding/listing.
- **backup** - `BackupService` exports, restores, and clears a user's data. Restore
  validates the document, then does a replace-all preserving original ids and
  timestamps with depreciation schedules recomputed; clear also purges the user's
  S3 binaries (photos + receipts). A pure `validate_document` checks a document
  before any read/write. Activity history is not part of a backup; restore and
  clear delete it.

See [Data model](data-model.md) for entities and the DynamoDB key scheme, and
[API reference](api.md) for the full route table.
