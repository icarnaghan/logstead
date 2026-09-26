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
  overhead low.
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
services/     Business logic: auth, property, transaction, depreciation,
              expense_import, report, dashboard, category
repository/   DynamoDB single-table access; encapsulates the key scheme (keys.py)
adapters/     External integrations: RentCast, address autocomplete, S3 files
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

### Dependency wiring and test seams

The router exposes `configure(repo=, files=, rentcast=, autocomplete=)` and
`reset_wiring()` so tests can inject fakes/mocks for the repository, file store,
and external adapters. This keeps the service layer testable without AWS.

Runtime configuration comes from environment variables: `TABLE_NAME`,
`FILES_BUCKET`, `AWS_REGION`, and `RENTCAST_API_KEY`. Address lookup uses Amazon
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
  the SPA has no import screen.)
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
- **depreciation** - depreciable assets and straight-line schedule computation
  (`compute_schedule_rows`, straight-line with the mid-month convention).
- **expense_import** - PDF parsing into draft line items and confirmation into
  transactions.
- **report** - `ReportingService` produces per-property and combined Schedule E
  reports and exports (`report_for`, `combined_report`, `export_report`,
  `export_combined_report`).
- **dashboard** - `DashboardService` builds portfolio and per-property summaries.
- **category** - the Schedule E category catalog and seeding/listing.

See [Data model](data-model.md) for entities and the DynamoDB key scheme, and
[API reference](api.md) for the full route table.
