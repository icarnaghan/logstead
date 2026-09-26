# API Reference

The backend exposes a single HTTP API (API Gateway HTTP API) fronting one Python
Lambda. Routes are defined by the `_ROUTES` table in
`backend/src/logstead/router/handler.py`.

## Authentication

All routes require a valid Cognito JWT **except** `GET /categories`, which is
public reference data. API Gateway validates the token with its native Cognito
JWT authorizer before invoking the Lambda. The Lambda reads the verified
identity from `event["requestContext"]["authorizer"]["jwt"]["claims"]` and does
not verify tokens itself. A missing or invalid identity results in `401`.

Send the token as a bearer credential on each request; the API is stateless and
holds no session.

## Conventions

- Request and response bodies are JSON.
- **Money values are serialized as strings** (two-decimal), matching the exact
  `decimal.Decimal` representation used server-side.
- Path parameters are shown in `{braces}`.

## Error model

The router maps service results to HTTP status codes as follows:

| Condition | Status |
| --- | --- |
| Success (read/update) | `200` |
| Success (create) | `201` |
| Validation error | `400` (includes the offending field where applicable) |
| Not found | `404` |
| Conflict | `409` |
| External service unavailable (e.g., RentCast) | `503` |
| Unauthorized (missing/invalid identity) | `401` |
| Unknown route | `404` |
| Malformed JSON body | `400` |
| Unhandled error | `500` |

## Routes

### Categories (public reference data)

| Method | Path | Auth |
| --- | --- | --- |
| GET | `/categories` | Public |

Returns the seeded Schedule E category catalog (16 entries). It is seeded once
per environment (see [Deployment](deployment.md)); an empty `[]` means the
catalog has not been seeded yet.

### Address enrichment

| Method | Path |
| --- | --- |
| GET | `/addresses` |
| GET | `/addresses/units` |
| POST | `/properties/enrich` |

Address suggestions come from Amazon Location Service (`geo-places`), called
server-side with the Lambda's IAM role (no API key). The flow is two steps:

- `GET /addresses?q=<partial>` (also accepts `?query=`) runs `geo-places`
  Autocomplete and returns candidate buildings - the base street address only.
- `GET /addresses/units?address=<addr>` (also accepts `?q=`) runs `geo-places`
  Geocode with `AdditionalFeatures=["SecondaryAddresses"]` on a selected
  building and returns that building's secondary addresses (units/apartments).
  Autocomplete never surfaces units, so this second call is how they are
  retrieved. A building with no units returns an empty list.

### Properties

| Method | Path |
| --- | --- |
| POST | `/properties` |
| GET | `/properties` |
| GET | `/properties/{propertyId}` |
| PUT | `/properties/{propertyId}` |
| DELETE | `/properties/{propertyId}` |
| PUT | `/properties/{propertyId}/usage` |
| GET | `/properties/{propertyId}/usage` |

Enrichment details supplied at creation are persisted, and
`GET /properties/{propertyId}` returns the stored `PropertyDetails` (when
present) alongside the property. See [Data model](data-model.md).

### Property photos

| Method | Path |
| --- | --- |
| POST | `/properties/{propertyId}/photos` |
| GET | `/properties/{propertyId}/photos` |
| DELETE | `/properties/{propertyId}/photos/{photoId}` |

### Transactions

| Method | Path |
| --- | --- |
| POST | `/properties/{propertyId}/transactions` |
| GET | `/properties/{propertyId}/transactions` |
| GET | `/properties/{propertyId}/transactions/{transactionId}` |
| PUT | `/properties/{propertyId}/transactions/{transactionId}` |
| DELETE | `/properties/{propertyId}/transactions/{transactionId}` |

### Receipts

| Method | Path |
| --- | --- |
| POST | `/properties/{propertyId}/transactions/{transactionId}/receipts` |
| GET | `/properties/{propertyId}/transactions/{transactionId}/receipts` |
| DELETE | `/properties/{propertyId}/transactions/{transactionId}/receipts/{documentId}` |

The routes are unchanged; the SPA presents these attachments as "supporting
documents" in the UI.

### Depreciable assets

| Method | Path |
| --- | --- |
| POST | `/properties/{propertyId}/assets` |
| GET | `/properties/{propertyId}/assets` |
| GET | `/properties/{propertyId}/assets/{assetId}` |
| PUT | `/properties/{propertyId}/assets/{assetId}` |
| DELETE | `/properties/{propertyId}/assets/{assetId}` |
| GET | `/properties/{propertyId}/assets/{assetId}/schedule` |

### Expense imports

| Method | Path |
| --- | --- |
| POST | `/imports` |
| GET | `/imports/{sessionId}` |
| GET | `/imports/{sessionId}/drafts` |
| PUT | `/imports/{sessionId}/drafts/{draftId}` |
| DELETE | `/imports/{sessionId}/drafts/{draftId}` |
| POST | `/imports/{sessionId}/confirm` |

Import sessions accept a PDF either inline (base64 in `pdf_base64` / `pdfBase64`)
or by S3 key (`pdf_s3_key` / `pdfS3Key`). Parsed line items are returned as
drafts and only become transactions after `POST /imports/{sessionId}/confirm`.

> These routes remain in the backend but are **not currently surfaced in the
> UI**: the SPA has no import screen or nav entry, so the import flow is not
> reachable from the app.

### Reports

| Method | Path |
| --- | --- |
| GET | `/properties/{propertyId}/report` |
| GET | `/reports/combined` |

### Dashboard

| Method | Path |
| --- | --- |
| GET | `/dashboard` |
| GET | `/dashboard/properties` |

### Backup & data portability

| Method | Path |
| --- | --- |
| GET | `/backup` |
| POST | `/backup/restore` |
| POST | `/backup/clear` |

`GET /backup` returns a full JSON export of the caller's Schedule E data
(properties, details, notes, usage years, transactions, assets), with money as
two-decimal strings and a `schema_version` and `exported_at` on the document.
`POST /backup/restore` validates the document first and only then performs a
replace-all: it clears the user's existing data and rewrites the document,
preserving original ids and timestamps; depreciation schedules are recomputed
rather than trusted from the document. An invalid document returns `400` naming
the offending field. `POST /backup/clear` removes all of the user's DynamoDB
rows and their S3 binaries (property photos and transaction receipts). Restore
and clear require the S3 bucket to be configured (`503` otherwise). All three
routes are user-scoped and require auth.

## Schedule E mapping

Reports map categorized transactions to IRS Schedule E lines: income on lines
3-4, expenses on lines 5-17, **Line 18 (Depreciation)** sourced from computed
depreciation schedules (not from a transaction category), and **Line 19 (Other)**
which requires a description. See [Data model](data-model.md) for details.
