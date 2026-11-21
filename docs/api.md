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
| Accepted for background processing (`POST /accountant-packages`) | `202` |
| Validation error | `400` (includes the offending field where applicable) |
| Not found | `404` |
| Conflict (e.g., a package is already being prepared, or a package being prepared is deleted) | `409` |
| External service unavailable (e.g., RentCast) | `503` |
| Unauthorized (missing/invalid identity) | `401` |
| Unknown route | `404` |
| Malformed JSON body | `400` |
| Unhandled error | `500` |

Amount parse errors (unparseable or too large) carry `field: "amount"`.
Error bodies have the shape `{"error": "<code>", "message": "...", "field": "..."}`
(`field` is present where a single field applies). Validation failures that
involve more than one offending field also carry an additive `errors` list. The
top-level `field` and `message` still describe the first entry, so existing
clients keep working:

```json
{
  "error": "validation",
  "message": "Original principal must be greater than zero.",
  "field": "original_principal",
  "errors": [
    { "field": "anchor_balance", "message": "Anchor balance must be greater than zero." },
    { "field": "monthly_payment", "message": "Monthly payment must exceed the first month's interest." }
  ]
}
```

`errors` is omitted when there is only a single offending field and no list was
built. Loan routes report every offending field in one response.

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

### Itemized expenses
Optional line-item detail for a Schedule E line. Only the `repairs` category
(Line 14) is enabled; an unknown category returns `404` and a known but not
enabled one returns `400` on `category_id`. Entries are expense transactions
carrying an `itemized` marker, so they also appear (read-only) in the
transactions list. The marker cannot be set through the generic transaction
routes.
| Method | Path |
| --- | --- |
| GET | `/properties/{propertyId}/itemized/{categoryId}?taxYear=YYYY` |
| POST | `/properties/{propertyId}/itemized/{categoryId}/entries` |
| PUT | `/properties/{propertyId}/itemized/{categoryId}/entries/{entryId}` |
| DELETE | `/properties/{propertyId}/itemized/{categoryId}/entries/{entryId}` |
| PUT | `/properties/{propertyId}/itemized/{categoryId}/total` |
| DELETE | `/properties/{propertyId}/itemized/{categoryId}/total?taxYear=YYYY` |
- **Entry body:** `date`, `amount`, `description` (1-200 characters), optional
  `notes` (up to 1000 characters) and optional `tax_year`. The date must fall in
  the tax year. `itemized`, `imported`, `type` and `property_id` in the body are
  ignored.
- **Total body (`PUT .../total`):** `tax_year` and `amount`. It creates one
  `{year}-12-31` expense row when there is no entered total, and updates the
  single row in place otherwise (same id, date, description, receipts). With
  several total rows it returns `409` on `total`; `DELETE` with no total
  returns `404`.
- **Summary response:** the entered total, itemized sum and count, remainder
  (`null` when there is no total), line total, and the source of the line
  figure (`entered_total`, `itemized` or `none`).
- Receipts on an entry use the existing receipt routes below.
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

### Loans

| Method | Path |
| --- | --- |
| POST | `/properties/{propertyId}/loans` |
| GET | `/properties/{propertyId}/loans` |
| GET | `/properties/{propertyId}/loans/line-12-impact` |
| GET | `/properties/{propertyId}/loans/{loanId}` |
| PUT | `/properties/{propertyId}/loans/{loanId}` |
| DELETE | `/properties/{propertyId}/loans/{loanId}` |
| GET | `/properties/{propertyId}/loans/{loanId}/schedule` |
| PUT | `/properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}` |
| DELETE | `/properties/{propertyId}/loans/{loanId}/interest-overrides/{taxYear}` |

A loan belongs to a property. A loan is an interest rate, a monthly
principal-and-interest payment and one known balance (the anchor balance) on one
date (the anchor date). Logstead projects the monthly amortization schedule
forward from the anchor (an estimate) and rolls it up into one total per tax
year; the yearly interest feeds Schedule E Line 12. Every loan route checks that the property belongs to
the caller: a missing property and another user's property both return `404`
`{"error": "not_found", "message": "Property not found."}`. A missing loan returns
`404` with `"message": "Loan not found."` and `"field": "loan_id"`.

Money, the interest rate and the interest-override values are sent and returned
as **strings**; a JSON number for `annual_interest_rate`, `monthly_payment`,
`anchor_balance`, `extra_principal`, `original_principal` or `interest` is a
`400` on that field. Request bodies accept snake_case or camelCase keys;
responses use snake_case. Payment rows are not stored: the schedule route
recomputes them on demand. The removed fields `term_months`,
`first_payment_date` and `payment_override` are ignored and do not satisfy the
required fields.

Create request (`POST`; `PUT` takes the same body and replaces the loan's
fields):

```json
{
  "description": "First mortgage",
  "annual_interest_rate": "6.875",
  "monthly_payment": "1970.79",
  "anchor_balance": "214500.00",
  "anchor_date": "2025-06-01",
  "extra_principal": "0.00",
  "payoff_date": null,
  "original_principal": "300000.00",
  "closing_date": "2022-02-14",
  "include_in_report": true
}
```

| Field | Rules |
| --- | --- |
| `description` | Required, 1-200 characters after trimming |
| `annual_interest_rate` | Required percentage, 0-100, at most four decimals |
| `monthly_payment` | Required, greater than 0, two decimals, at most `999999999.99`; must exceed one month of interest on `anchor_balance`; the loan may need at most 600 payments |
| `anchor_balance` | Required, greater than 0, two decimals, at most `999999999.99`; the balance immediately after the payment made on `anchor_date` |
| `anchor_date` | Required `YYYY-MM-DD`, not before 1900-01-01; the first projected payment is one month later, and no payment may fall after year 9999 |
| `extra_principal` | Optional, two decimals, `0.00` or more (defaults to `0.00`) |
| `payoff_date` | Optional date, not before the next payment date; the schedule stops at it |
| `original_principal` | Optional, informational, greater than 0, two decimals; never used in calculations |
| `closing_date` | Optional, informational date; never used in calculations |
| `include_in_report` | Optional boolean, defaults to `true`; `false` keeps the loan out of the reports |

Create returns `201`; get, update and each list item return `200` with:

```json
{
  "id": "9f1c...", "property_id": "a31b...",
  "description": "First mortgage",
  "annual_interest_rate": "6.875",
  "monthly_payment": "1970.79",
  "anchor_balance": "214500.00",
  "anchor_date": "2025-06-01",
  "extra_principal": "0.00",
  "payoff_date": null,
  "original_principal": "300000.00",
  "closing_date": "2022-02-14",
  "include_in_report": true,
  "interest_overrides": { "2023": "20650.12", "2025": "7410.55" },
  "remaining_payments": 148,
  "next_payment_date": "2025-07-01",
  "projected_payoff_date": "2037-10-01",
  "payoff_balance": null,
  "status": "active",
  "created_at": "2025-06-02T15:04:05+00:00",
  "updated_at": "2025-06-02T15:04:05+00:00"
}
```

Derived fields are never accepted as input. `remaining_payments` is the number
of projected payments, `next_payment_date` is the date of the first one,
`projected_payoff_date` is the date of the final (possibly smaller) payment when
the balance reaches `0.00` (otherwise `null`), and `payoff_balance` is set only
when a `payoff_date` leaves a positive balance. `status` is `active` or
`ended`. Updating a loan keeps each existing interest override whose tax year is
from 1900 through the new anchor year or still has a payment, and drops the
rest. The update body does not carry overrides; use the override routes.

`DELETE` returns `200` with a `null` body and removes the loan, its yearly
totals and its overrides. A property that still has loans cannot be deleted
(`409`); remove its loans first.

`GET .../loans/{loanId}/schedule`:

```json
{
  "loan_id": "9f1c...",
  "estimate": true,
  "payoff_balance": null,
  "payments": [
    { "number": 1, "date": "2024-03-01", "payment": "1970.79", "interest": "1718.75",
      "principal": "252.04", "balance": "299747.96" }
  ],
  "yearly": [
    { "tax_year": 2024, "payments": 10, "interest": "7010.12", "estimated_interest": "14180.30",
      "interest_override": "7010.12", "variance": "-7170.18",
      "principal": "5528.30", "total_paid": "19708.60", "ending_balance": "294471.70" }
  ]
}
```

In each `yearly` entry `interest` is the effective interest that Line 12 uses
(the override when set, otherwise `estimated_interest`), and `variance` is
`interest_override - estimated_interest`, or `null` without an override. Years
with no payments and no override have no entry and count as `0.00`. A year with
an override but no payments (any year from 1900 through the anchor year) has an
override-only entry: `payments` is `0`, `estimated_interest`, `principal` and
`total_paid` are `"0.00"`, and `ending_balance` is `null`:

```json
{ "tax_year": 2023, "payments": 0, "interest": "20650.12", "estimated_interest": "0.00",
  "interest_override": "20650.12", "variance": "20650.12",
  "principal": "0.00", "total_paid": "0.00", "ending_balance": null }
```

The anchor year's estimate covers only payments after the anchor date, so enter
the Form 1098 interest as an override for the anchor year and earlier years.

Interest overrides let the user replace a year's estimate with the figure on the
lender's Form 1098. `PUT .../interest-overrides/{taxYear}` takes
`{"interest": "7010.12"}` (a non-negative string with at most two decimals) and
returns the updated yearly object above. The year must be from 1900 through the
anchor year, or a year that has payments; otherwise the request is a `400` on
`interest_overrides.<year>`. Payment rows and balances are unchanged. `DELETE`
clears the override, returns the yearly object with `interest_override` and
`variance` set to `null`, and succeeds when no override was set. For a year
with no payments, clearing the override removes its entry and returns a `null`
body.

`GET .../loans/line-12-impact` lists the years where a loan replaces
hand-entered mortgage interest. Only years with loan interest above `0.00` and at
least one Line 12 transaction are returned:

```json
[
  { "tax_year": 2024, "loan_interest": "14180.30",
    "superseded_manual_interest": { "amount": "13900.00", "count": 12 } }
]
```

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
> UI**: the SPA has no expense-import screen or nav entry, so the expense-import
> flow is not reachable from the app. This applies only to the `/imports`
> expense-import routes above; Schedule E import is reachable from the Import
> nav entry.

### Reports

| Method | Path |
| --- | --- |
| GET | `/properties/{propertyId}/report` |
| GET | `/reports/combined` |
| POST | `/properties/{propertyId}/report/pdf?taxYear=YYYY` |
| POST | `/reports/combined/pdf?taxYear=YYYY&propertyIds=a,b` |

Line 12 (Mortgage interest paid to banks) uses loan interest when a loan
produces it. If the included loans' effective interest for the year is above
`0.00`, Line 12 is that loan interest and the hand-entered Line 12 transactions
are not added to it (never both). Otherwise Line 12 is the hand-entered amount.
Loans with `include_in_report` set to `false` are ignored. Line 12 flows into
expenses, net income and the passive-loss carryforward through the existing
totals. Each property report gains a `line12` object:

```json
"line12": {
  "source": "loan-generated",
  "superseded_manual_interest": { "amount": "1234.00", "count": 3 }
}
```

- `source` is `loan-generated` or `transaction-entered`.
- `superseded_manual_interest` is the hand-entered Line 12 total and
  transaction count that the loan figure replaced. It is `"0.00"` and `0` when
  nothing is superseded.

The combined report adds a top-level `line12` with `total` (the sum of the
property Line 12 totals) and `superseded_manual_interest` (summed `amount` and
`count`). It has no `source`, because properties can mix both.

CSV exports add `Line 12 Source`, `Line 12 Superseded Manual Interest` and
`Line 12 Superseded Transaction Count` rows after each property's line table, and
`Line 12 Total`, `Line 12 Superseded Manual Interest` and
`Line 12 Superseded Transaction Count` in the combined portfolio block. JSON
exports carry the `line12` objects as returned by the API.

The server CSV export prefixes an apostrophe to text cells (property name,
address, property type, other-item descriptions) that start with `=`, `+`, `-`
or `@` (also a tab or carriage return), so spreadsheets do not treat them as
formulas. The combined export is stored under
`exports/combined/<user_id>/<tax_year>/<filename>`.

#### Report PDFs

`POST /properties/{propertyId}/report/pdf` and `POST /reports/combined/pdf`
render the Schedule E report (with the Repairs detail) as a PDF, store it under
`exports/pdf/<user_id>/<random id>/`, and return `200` with a download link:

```json
{
  "download_url": "https://...",
  "filename": "schedule-e-<property-slug>-2024.pdf",
  "content_type": "application/pdf",
  "size_bytes": 12345,
  "expires_in_seconds": 900
}
```

The combined filename is `schedule-e-combined-<taxYear>.pdf`. Both routes take
no body.

- `taxYear` (query, required): an integer within the supported range. Missing
  or invalid returns `400` with `field: "taxYear"`.
- `propertyIds` (combined only, optional): comma-separated property ids, at most
  100. A malformed list returns `400` with `field: "propertyIds"`. A selection
  with no properties also returns `400` with `field: "propertyIds"`.
- An unknown property returns `404`. `503` is returned when file storage is not
  configured.

### Accountant packages

| Method | Path |
| --- | --- |
| POST | `/accountant-packages` |
| GET | `/accountant-packages` |
| GET | `/accountant-packages/{jobId}` |
| DELETE | `/accountant-packages/{jobId}` |

A package is a ZIP of reports, a transactions CSV, receipts and a manifest for
one tax year. It is built in the background by a separate worker, so create
returns immediately with a job to poll. Jobs belong to the caller; another
user's job id returns `404`, the same as a missing one. A job expires after 24
hours.

**Create.** `POST /accountant-packages` with body
`{"tax_year": 2024, "property_ids": ["..."]}`. `property_ids` is optional and
defaults to all of the caller's properties. The camelCase spellings `taxYear`
and `propertyIds` are also accepted. Returns `202` with the job view below.

- `400` with `field: "tax_year"` (or `taxYear`) when the year is missing, not an
  integer, or out of range.
- `400` with `field: "property_ids"` (or `propertyIds`) when the list is not a
  list of at most 100 valid ids, or when the user has no properties
  (`Select at least one property.`).
- `404` when any listed property does not exist.
- `409` when the caller already has a package being prepared (status `queued`
  or `running`, and not stale).
- `503` when file storage or the package worker is not configured, or when the
  worker could not be started. In the latter case the job is stored as `failed`.

**List.** `GET /accountant-packages` returns `200` with
`{"jobs": [<job view>, ...]}`: unexpired jobs, newest first, at most 10.

**Get.** `GET /accountant-packages/{jobId}` returns `200` with the job view, or
`404`.

**Delete.** `DELETE /accountant-packages/{jobId}` removes the job and its ZIP
and returns `200` with `{}`. It returns `404` when the job does not exist, `409`
while the package is still being prepared, and `503` when the ZIP could not be
deleted (the job is kept so the delete can be retried).

**Job view.**

```json
{
  "id": "8f0c...",
  "status": "complete",
  "tax_year": 2024,
  "property_ids": ["..."],
  "created_at": "2025-01-15T12:00:00+00:00",
  "finished_at": "2025-01-15T12:00:20+00:00",
  "message": null,
  "size_bytes": 1048576,
  "sha256": "ab12...",
  "file_count": 14,
  "receipt_count": 8,
  "skipped_receipt_count": 0,
  "download_url": "https://...",
  "download_expires_in_seconds": 900
}
```

- `status` is `queued`, `running`, `complete` or `failed`. A `queued` or
  `running` job that has not changed for 15 minutes is reported as `failed` with
  the message `The package did not finish. Try again.`
- `download_url` and `download_expires_in_seconds` are set only when `status` is
  `complete`. The link is pre-signed and valid for 900 seconds; fetch the job
  again for a fresh one.
- The result fields (`size_bytes`, `sha256`, `file_count`, `receipt_count`,
  `skipped_receipt_count`) and `finished_at` are `null` until the worker records
  them. `message` is `null` unless the job failed or was marked stale.

### Dashboard

| Method | Path |
| --- | --- |
| GET | `/dashboard` |
| GET | `/dashboard/properties` |

### Search

| Method | Path |
| --- | --- |
| GET | `/search?q=&limit=&propertyId=` |

Read-only substring search over the signed-in user's properties, transactions,
itemized entries (Repairs), depreciable assets, loans and businesses. Only
`GET` resolves.

| Parameter | Required | Rules |
| --- | --- | --- |
| `q` | yes | 2 to 100 characters after trimming, with searchable text. At most 5 tokens are used (extra tokens are ignored). |
| `limit` | no | Integer from 1 to 25, default 5. Hits returned per group. |
| `propertyId` | no | Restricts the search to one owned property. Properties and businesses are then not searched. |

Matching is plain text, not a pattern: `*`, `%`, `\` and `.` match literally.
Text is normalized (NFKC, case-folded, whitespace collapsed). A record matches
when every token appears in the searched fields. Only these fields are
searched; amounts, dates and category labels never match:

| Kind | Fields |
| --- | --- |
| `property` | `name`, `address_text` |
| `transaction` | `description` |
| `itemized_entry` | `description`, `notes` |
| `asset`, `loan` | `description` |
| `business` | `legal_name`, `business_address` |

Hits are ordered by rank (a whole field equals the query, then every token
starts a word, then any substring), then newest date first, then title, then
id.

Response (`200`), always six groups in this order: `property`, `transaction`,
`itemized_entry`, `asset`, `loan`, `business`:

```json
{
  "query": "roof",
  "groups": [
    {
      "kind": "itemized_entry",
      "total": 3,
      "hits": [
        {
          "kind": "itemized_entry",
          "id": "…",
          "property_id": "…",
          "title": "Roof repair",
          "subtitle": "12 Oak St · 2024-05-02",
          "matched_field": "description",
          "link": "/properties/…/repairs?year=2024&focus=…",
          "amount": "1250.00",
          "date": "2024-05-02"
        }
      ]
    }
  ],
  "truncated": false,
  "scanned": 412
}
```

- `query` is the normalized, token-joined query. `total` counts every match in
  the group; `hits` holds at most `limit` of them.
- `amount` is a two-decimal string (transaction and itemized entry amount, asset
  cost basis) or `null`. `date` and `amount` are `null` for properties, loans
  and businesses. `subtitle` and `property_id` can be `null` (businesses have
  no `property_id`).
- `link` is an in-app path built from validated ids.
- `scanned` counts transactions, itemized entries, assets and loans read.
  Reading stops once it reaches the scan cap of 20,000 records (a property is
  read whole, so `scanned` can exceed the cap). After the cap
  the remaining properties are not read and `truncated` is `true`.
  **Known open point:** if the cap is reached exactly and any properties are
  left unread, `truncated` is `true` even when those properties hold no
  records. This is by design, because reading stops at the cap and the service
  does not read ahead to check.

Errors: `400` for a missing or invalid `q` (field `q`) or a non-integer or out
of range `limit` (field `limit`); `404` "Property not found." when `propertyId`
is malformed, missing or belongs to another user (all three give the same
response, before any record is read); `401` without a valid identity. The query
text is never logged. The route is throttled at 2 requests per second with a
burst of 5.

### Activity history

| Method | Path |
| --- | --- |
| GET | `/activity?limit=&cursor=&entity=&action=&propertyId=` |
| GET | `/properties/{propertyId}/activity?limit=&cursor=&entity=&action=` |
| POST | `/properties/{propertyId}/activity/{eventId}/restore` |

A per-user log of changes, newest first. The two `GET` routes are read-only and
write nothing. The list routes accept `GET` only and the restore route `POST`
only. Events are recorded by the router after a mutation succeeds
(`200`, `201` or `204`); a recording failure never changes the mutation's
response. History is not part of a backup (see `docs/data-model.md`).

| Parameter | Rules |
| --- | --- |
| `limit` | Integer from 1 to 100, default 50. |
| `cursor` | The `next_cursor` of the previous page. An opaque value; a malformed one is a `400`. A valid cursor only ever positions a read inside the caller's own events. |
| `entity` | One of `transaction`, `itemized_entry`, `asset`, `loan`, `property`, `backup`, `schedule_e`. |
| `action` | One of `create`, `update`, `delete`, `restore`, `import`. |
| `propertyId` | `GET /activity` only. Restricts the list to one owned property. |

Response (`200`):

```json
{
  "events": [
    {
      "id": "99999998123456.0b9f…",
      "at": "2025-03-02T14:05:09.123Z",
      "action": "delete",
      "entity": "transaction",
      "summary": "Deleted transaction: Roof repair",
      "record_id": "…",
      "property_id": "…",
      "property_name": "12 Oak St",
      "before": { "date": "2025-02-10", "amount": "1250.00", "type": "expense", "category_id": "repairs", "description": "Roof repair", "notes": null },
      "after": null,
      "truncated": false,
      "restorable": true,
      "restored_at": null,
      "restored_as": null
    }
  ],
  "next_cursor": null
}
```

- `id` is the event id used in the restore path: 14 digits, a dot, then a
  UUID.
- `before` and `after` hold only allow-listed fields (money as strings). A
  create has no `before`, a delete has no `after`, and an update holds only the
  fields that changed. Import and backup events carry counts in `after`.
  `truncated` is `true` when a long value was cut to fit the size limit.
- `next_cursor` is `null` on the last page. Following it from the first page
  returns every visible event once, in order.
- Events past their expiry time are never returned, even before DynamoDB
  deletes them.
- `restorable` is `true` only on a `delete` event that can be re-created
  safely. `restored_at` and `restored_as` (the new record id) are set once it
  has been restored.

`POST .../restore` re-creates the deleted record from the event's stored
payload through the normal create path and returns `200`:

```json
{ "record_id": "…", "event_id": "99999998123456.0b9f…", "restored_at": "2025-03-02T14:09:00.000Z" }
```

The record comes back with a **new id** and fresh `created_at` / `updated_at`
(see "Undo and record IDs" in the developer guide). One `restore` event is
recorded. Restore works for deleted transactions, itemized entries, assets and
loans.

Errors:

| Status | When |
| --- | --- |
| `400` | `limit` is not an integer from 1 to 100 (field `limit`), `cursor` is malformed (field `cursor`), or `entity` / `action` is not a known kind (fields `entity`, `action`). On restore, an error from the create itself is passed through with its own status and the event stays restorable. |
| `404` | `Property not found.` when the property is missing, malformed, or owned by another user. All three give the same response, including for `propertyId` on `GET /activity`. `Activity event not found.` when the event id is malformed, unknown, or belongs to another property. |
| `409` | Restore of an event that is not a `delete` ("Only a delete event can be restored."), is not restorable ("This event cannot be restored."), has stored data that is no longer readable or valid, or was already restored ("This event was already restored."). |
| `401` | No valid identity. |

A restore claims the event with a conditional write before creating the record,
so two concurrent requests create one record. A claim that is still pending
after 5 minutes is treated as abandoned and can be taken again. If the create
fails, the claim is released.

### Year-end checklist

Read-only review prompts for one tax year. The checklist stores nothing and
changes nothing; every response is computed from existing Schedule E data.

| Method | Path |
| --- | --- |
| GET | `/properties/{propertyId}/checklist` |
| GET | `/properties/{propertyId}/checklist/summary` |
| GET | `/checklist/summary` |

**`taxYear` query parameter.** `GET /properties/{propertyId}/checklist` and
`GET /checklist/summary` accept an optional integer `taxYear`. When it is
absent, the latest completed tax year (the prior calendar year) is used. A value
that is not an integer, or is outside 1900 to 2200, returns `400` with
`field: "taxYear"`. `GET /properties/{propertyId}/checklist/summary` takes no
parameters; it chooses its own years.

**Errors.**

| Status | When |
| --- | --- |
| `400` | `taxYear` is not an integer or is outside 1900 to 2200 |
| `404` | The property does not exist or belongs to another user (same response for both). Applies to the two `/properties/{propertyId}/...` routes |
| `503` | The carryforward service is not available |

#### `GET /properties/{propertyId}/checklist`

```json
{
  "property_id": "…",
  "tax_year": 2024,
  "items": [
    {
      "id": "income_entered",
      "title": "Income entered",
      "status": "done",
      "reason": "Income of $12,000.00 is entered for 2024.",
      "link": "/properties/…/transactions?year=2024",
      "details": { "income_total": "12000.00" }
    }
  ],
  "counts": { "done": 6, "needs_attention": 3, "not_applicable": 2, "total": 11 },
  "thresholds": {
    "large_entry_amount": "250.00",
    "capital_candidate_amount": "2500.00",
    "swing_percent": "50",
    "swing_minimum_amount": "500.00",
    "anchor_max_age_months": 12,
    "summary_year_count": 5
  }
}
```

`items` always holds eleven entries in the fixed order listed below. `status` is
`done`, `needs_attention` or `not_applicable`. `reason` is a plain-language
sentence and `link` is an in-app path (`?year=` is added for the transactions,
repairs and reports pages). `details` is item-specific and may be `null`. Money
is a two-decimal string. `thresholds` echoes the values applied.

`details` keys per item:

| Item `id` | `details` keys |
| --- | --- |
| `income_entered` | `income_total` |
| `expenses_entered` | `expense_total` (excludes Line 18 depreciation) |
| `depreciation_present` | `assets_with_schedule_rows`, `line_18_total` |
| `line12_source` | `source`, `line_12_total`, `superseded_count`, `superseded_amount` |
| `loan_interest_confirmed` | `loans`: list of `loan_id`, `name`, `confirmed`, `anchor_date`, `interest`. Omitted (`null`) when Line 12 is not loan-generated |
| `carryforward_reconciled` | `status`, `reported_carry_in`, `expected_carry_in`, `drift`, `carried_from_year`, `status_tolerance`. The item covers all properties and is the same on every property's checklist |
| `repairs_exceed_total` | `entered_total`, `itemized_sum`, `remainder`, `line_source` |
| `repairs_capital_candidates` | `flagged_count`, `entries`: list of `id`, `date`, `description`, `amount`, `link` |
| `receipts_missing` | `evaluated_count`, `missing_count`, `transactions`: up to 25 of `id`, `date`, `category`, `description`, `amount` (`missing_count` is the full count) |
| `yoy_swings` | `swings`: list of `line`, `label`, `prior_total`, `current_total`, `change` (signed), `percent` (one decimal; `null` when the prior total is `0.00`) |
| `imported_values_edited` | `imported_count`, `edited`: list of `id`, `schedule_e_line`, `amount`, `updated_at` |

Item ids, in order: `income_entered`, `expenses_entered`,
`depreciation_present`, `line12_source`, `loan_interest_confirmed`,
`carryforward_reconciled`, `repairs_exceed_total`, `repairs_capital_candidates`,
`receipts_missing`, `yoy_swings`, `imported_values_edited`.

#### `GET /properties/{propertyId}/checklist/summary`

Counts for the most recent years that have data for the property (up to
`summary_year_count`, currently 5), newest first. No items are returned.

```json
{
  "property_id": "…",
  "years": [
    { "tax_year": 2024, "counts": { "done": 6, "needs_attention": 3, "not_applicable": 2, "total": 11 } }
  ]
}
```

#### `GET /checklist/summary`

Counts per property for one tax year (`taxYear`, defaulting as above), for the
dashboard card.

```json
{
  "tax_year": 2024,
  "properties": [
    {
      "property_id": "…",
      "property_name": "…",
      "counts": { "done": 6, "needs_attention": 3, "not_applicable": 2, "total": 11 }
    }
  ]
}
```

### Backup & data portability

| Method | Path |
| --- | --- |
| GET | `/backup` |
| POST | `/backup/restore` |
| POST | `/backup/clear` |

`GET /backup` returns a full JSON export of the caller's Schedule E data
(properties, details, notes, usage years, transactions, assets, loans with their
interest overrides), with money as
two-decimal strings and a `schema_version` and `exported_at` on the document.
`POST /backup/restore` validates the document first and only then performs a
replace-all: it clears the user's existing data and rewrites the document,
preserving original ids and timestamps; depreciation schedules are recomputed
rather than trusted from the document. An invalid document returns `400` naming
the offending field. `POST /backup/clear` removes all of the user's DynamoDB
rows and their S3 binaries (property photos and transaction receipts). Each
backup transaction carries optional `imported`, `itemized` and `notes` fields;
documents without them restore as `false`/absent and `schema_version` stays
`"1"`. Restore
and clear require the S3 bucket to be configured (`503` otherwise). All three
routes are user-scoped and require auth.

## Schedule E mapping

Reports map categorized transactions to IRS Schedule E lines: income on lines
3-4, expenses on lines 5-17, **Line 18 (Depreciation)** sourced from computed
depreciation schedules (not from a transaction category), and **Line 19 (Other)**
which requires a description. On Line 14 (Repairs) an entered total wins over
itemized entries and the two are never added; with no entered total the line is
the itemized sum. See [Data model](data-model.md) for details.
