# Data Model

Logstead uses a single Amazon DynamoDB table (single-table design). Binary files
live in S3; DynamoDB stores only metadata and S3 keys. The key scheme is
encapsulated in `backend/src/logstead/repository/keys.py` - services never build
keys directly.

## Guiding principles

- **The system of record is what is needed to reproduce a Schedule E report.**
  Transactions, assets, and depreciation inputs are authoritative; aggregates
  are derived on demand.
- **Money is stored as two-decimal strings**, never as DynamoDB `Number`.
- **Sparse attributes** naturally accommodate optional RentCast fields.

## Domain entities

- **User** - the single authenticated operator of the app.
- **Property** - a rental unit; one column of Schedule E Part I. Has a name,
  address, and property type, plus optional enriched details and usage days.
- **PropertyDetails** - optional RentCast-enriched attributes for a property.
  Sparse (every field individually optional) but now much richer: the full
  address/geo/structure fields plus `assessor_id`, `legal_description`,
  `subdivision`, `zoning`, `last_sale_date`, `last_sale_price`, a nested
  `features` map, HOA, owner, and year-keyed history lists. Persisted on create
  and returned by `GET /properties/{id}` (see below). Nested entities:
  - **PropertyFeatures** - descriptive `*_type` strings (architecture,
    exterior, foundation, roof, view, heating, cooling, garage, pool,
    fireplace), boolean presence flags (`heating`, `cooling`, `garage`, `pool`,
    `fireplace`), and counts (`garage_spaces`, `floor_count`, `room_count`,
    `unit_count`). Types and flags are kept separate so a boolean is never
    rendered as the string `"True"`.
  - **TaxAssessment** - a single year's assessment: `year`, `value`, `land`,
    `improvements`.
  - **PropertyTax** - a single year's property-tax `total`, keyed by `year`.
  - **SaleEvent** - one entry of sale history: `date`, `price`, `event`.
  - **HoaDetails** - HOA information (`fee`).
  - **PropertyOwner** - ownership (`names`, `type`, `occupied`).
- **Photo** - a property photo (metadata + S3 key).
- **Transaction** - a dated income or expense record for a property, categorized
  to a Schedule E line.
- **Receipt / Document** - a file attached to a transaction (metadata + S3 key).
- **Category** - a Schedule E category from the catalog (`CATEGORY_CATALOG`).
- **Depreciable Asset** - a capitalized item (building, improvement, appliance)
  with a cost basis, placed-in-service date, and recovery period.
- **Depreciation Schedule** - the year-by-year straight-line amounts computed for
  an asset (mid-month convention; default recovery period `27.5` years for
  residential rental buildings).
- **Import Session / Draft** - a staging area for expense-summary PDF line items
  before they are confirmed into transactions.

## DynamoDB key scheme

Items share a partition/sort key structure keyed off the owning entity. Key
prefixes used (see `keys.py`):

| Prefix | Represents |
| --- | --- |
| `USER#` | The user partition |
| `PROPERTY#` / `PROP#` | Property records |
| `DETAILS` | Property enrichment details (single `detailsJson` attribute) |
| `USAGE#` | Property usage days |
| `PHOTO#` | Property photos |
| `CATEGORY#` | Schedule E categories |
| `TXN#<invDate>#<id>` | Transactions, sort-keyed by inverted date |
| `ASSET#` | Depreciable assets |
| `ASSET#..#SCHED#` | Depreciation schedule rows for an asset |
| `IMPORT#` | Import sessions |
| `DRAFT#` | Draft line items within an import session |
| `DOC#` | Attached documents/receipts |

### Property details storage

The `PROPERTY#<id> / DETAILS` row stores the whole `PropertyDetails` tree as a
single `detailsJson` string attribute rather than spreading the nested fields
across many DynamoDB attributes. Inside that JSON, money is written as
two-decimal strings and lat/long as full-precision decimal strings, and absent
values are omitted so the document stays sparse. JSON is used here because the
top-level money serializer only covers top-level item attributes, so a nested
tree needs its own serialization boundary to keep the money invariant (see
`backend/src/logstead/models/property_details_json.py`). Details are persisted
when a property is created with enrichment and are parsed back and attached to
the property on `GET /properties/{id}`.

### Inverted transaction date

Transactions sort by an inverted date so the most recent appears first:
`invDate = 99999999 - YYYYMMDD`. This yields descending chronological order
within a property partition without a separate index.

### Global secondary indexes

- **GSI1** - reverse lookups, e.g. `USER#` <-> `PROP#` and
  `PROPERTY#` <-> `IMPORT#`.
- **GSI2** - tax-year access, keyed as `PROPERTY#<id>#YEAR#<year>`, so a year of
  transactions for a property can be read directly for reporting.

## Schedule E line mapping

Reports assemble Schedule E Part I from persisted data:

- **Lines 3-4** - rental income.
- **Lines 5-17** - deductible expense categories.
- **Line 18 (Depreciation)** - sourced from computed depreciation schedules, not
  from a transaction category.
- **Line 19 (Other)** - other expenses; each requires a description.

The reporting service (`ReportingService`) builds per-property
(`report_for`) and combined (`combined_report`) figures and can export them
(`export_report`, `export_combined_report`, returning a `ReportExport`). The
depreciation service computes schedule rows with `compute_schedule_rows`
(straight-line, mid-month convention).
