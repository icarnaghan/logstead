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
  to a Schedule E line. It may carry an `imported` marker (set by Schedule E
  import) and, for Repairs only, an `itemized` marker with optional `notes`
  (see "Itemized expenses" below).
- **Receipt / Document** - a file attached to a transaction (metadata + S3 key).
- **Category** - a Schedule E category from the catalog (`CATEGORY_CATALOG`).
- **Depreciable Asset** - a capitalized item (building, improvement, appliance)
  with a cost basis, placed-in-service date, and recovery period.
- **Depreciation Schedule** - the year-by-year straight-line amounts computed for
  an asset (mid-month convention; default recovery period `27.5` years for
  residential rental buildings).
- **Loan** / **LoanYearRollup** - a mortgage on a property and its derived
  per-tax-year totals (see "Mortgage loans" below).
- **Import Session / Draft** - a staging area for expense-summary PDF line items
  before they are confirmed into transactions.
- **Schedule E extraction job** - an uploaded Schedule E PDF being read by
  Textract into a reviewable draft for Schedule E import.
- **Business** - a business entity that owns or operates properties, with its
  own supporting documents.
- **Passive loss carryforward** - the reported prior-year unallowed loss per
  tax year (`PLCF#<year>`) plus an opening balance, reconciled against the
  expected chain.
- **Package job** - a transient accountant package build (see
  [Accountant package](#accountant-package)).
- **Activity event** - one recorded change, kept for 24 months (see
  [Activity history](#activity-history)).
- The **Year-end checklist** and **search** store nothing; both are computed
  from the records above on each request.

## DynamoDB key scheme

Items share a partition/sort key structure keyed off the owning entity. Key
prefixes used (see `keys.py`):

| Prefix | Represents |
| --- | --- |
| `USER#` | The user partition |
| `PROPERTY#` / `PROP#` | Property records |
| `DETAILS` | Property enrichment details (single `detailsJson` attribute) |
| `BUSINESS#` | Business entities |
| `USAGE#` | Property usage days |
| `PHOTO#` | Property photos |
| `CATEGORY#` | Schedule E categories |
| `TXN#<invDate>#<id>` | Transactions, sort-keyed by inverted date |
| `ASSET#` | Depreciable assets |
| `ASSET#..#SCHED#` | Depreciation schedule rows for an asset |
| `IMPORT#` | Import sessions |
| `DRAFT#` | Draft line items within an import session |
| `SEEXTRACT#` | Schedule E PDF extraction jobs |
| `PLCF#` | Passive loss carryforward values per tax year (`PLCF#<year>`; the opening balance uses `PLCF_OPENING`) |
| `DOC#` | Attached documents/receipts |
| `LOAN#` | Mortgage loans (`LOAN#<loanId>`) |
| `LOAN#..#YEAR#` | Yearly rollup rows for a loan (`LOAN#<loanId>#YEAR#<taxYear>`) |
| `ACCTPKG#` | Transient accountant package jobs (`ACCTPKG#<jobId>`) |
| `ACT#` | Activity events (`ACT#<invertedMillis>#<eventId>`), see [Activity history](#activity-history) |

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

## Mortgage loans

Loans mirror the depreciation design: an authoritative item holds the inputs,
and a pure engine derives per-year rows that are stored for fast tax-year reads.
The key helpers live in `keys.py` and the item builders (`loan_to_item`,
`rollup_to_item`) in the loan repository module, so backup restore can reuse
them.

### Loan entity

Two item types are stored in the property partition (`PK = PROPERTY#<id>`).

**Loan** - `SK = LOAN#<loanId>`. This is the source of truth.

#### Loan attributes (anchor shape)

A loan is described by a known balance on a known date (the anchor), not by its
origination terms. The schedule starts one month after the anchor date.

| Attribute | Notes |
| --- | --- |
| `id`, `propertyId` | Loan id and owning property |
| `description` | 1-200 characters |
| `annualInterestRate` | Plain decimal string, at most 4 decimals, never scientific notation. Not a money attribute |
| `monthlyPayment` | Money string; required. Must exceed the first month's interest |
| `anchorBalance` | Money string; required. The balance on `anchorDate` |
| `anchorDate` | `YYYY-MM-DD`; required, 1900-01-01 or later |
| `originalPrincipal` | Money string; informational, omitted when unset. Never affects results |
| `extraPrincipal` | Money string; `0.00` when unset |
| `closingDate`, `payoffDate` | `YYYY-MM-DD`; omitted when unset |
| `includeInReport` | Boolean; only included loans feed Line 12 |
| `interestOverrides` | Map of tax year (string) to two-decimal money string; omitted when empty |
| `createdAt`, `updatedAt` | Timestamps |

**LoanYearRollup** - `SK = LOAN#<loanId>#YEAR#<taxYear>`. Derived from the loan
and rewritten whenever the loan changes.

| Attribute | Notes |
| --- | --- |
| `loanId`, `propertyId`, `taxYear` | Identity |
| `payments` | Number of payments in the year |
| `interest` | Estimated interest (sum of payment-row interest) |
| `principal`, `totalPaid` | Money strings |
| `endingBalance` | Money string; omitted on an Override_Only_Rollup |
| `interestOverride` | Money string; omitted when no override for the year |
| `effectiveInterest` | The override when present, otherwise `interest`. This is what Line 12 uses |
| `includeInReport` | Copied from the loan |

#### Override_Only_Rollup row

A tax year with an interest override but no generated payments (any year before
the anchor year, or the anchor year itself when no payment falls in it) is
stored as an Override_Only_Rollup: `payments` is `0`, `interest`, `principal`
and `totalPaid` are `0.00`, `endingBalance` is omitted, and `interestOverride`
and `effectiveInterest` carry the override. Overrides are allowed from 1900 up
to the anchor year, and for any year that has generated payments. Clearing the
override removes the row.

Per-payment rows are never stored; they are computed on demand. Creating or
updating a loan writes the loan item, all rollups, and deletes of stale rollups
in one transaction, so the writes are all-or-nothing.

### Loan key prefixes

- `LOAN#<loanId>` holds the loan. `LOAN#<loanId>#YEAR#<taxYear>` holds a rollup.
  A loan id is a uuid hex string with no `#`, so the two forms are unambiguous.
- Neither form matches `ASSET#`, `TXN#`, `DOC#`, or `PHOTO#`, so asset listing,
  transaction queries, and backup clearing are unaffected.
- **GSI2** also indexes rollups: `GSI2PK = PROPERTY#<id>#YEAR#<taxYear>` and
  `GSI2SK = LOANYR#<loanId>`. The `LOANYR#` prefix does not collide with `TXN#`
  or `SCHED#` rows in the same tax-year partition.
- A property cannot be deleted while it still has loans.

### Line 12 precedence rule

Line 12 (mortgage interest) can come from loans or from manually entered
transactions, but never both.

- When the sum of Effective_Interest across the property's included loans for
  the tax year is above `0.00`, Line 12 equals that loan total.
- Otherwise Line 12 is the sum of the manual `mortgage-interest-banks`
  transactions, as before. This includes the case where every included loan has
  an Effective_Interest of `0.00`.
- When the loan figure wins, the manual transaction total and count are reported
  as the superseded figure (`superseded_manual_interest`, with `amount` and
  `count`). The manual transactions are kept, only excluded from the line.
- The report carries a `source` of `loan-generated` or `transaction-entered`
  for Line 12. Combined reports sum the per-property totals and superseded
  figures.


## Itemized expenses
A Repairs (Line 14) transaction is either an **entered total** (unmarked) or an
**itemized entry** (`itemized: true`, a non-blank description of 1-200
characters, optional `notes` up to 1000 characters). The attributes are stored
only when set, so existing items are unchanged and read back as `false`/absent.
- **Precedence:** if at least one unmarked row exists for the line and year, the
  line equals the sum of unmarked rows. Otherwise it equals the sum of itemized
  entries, or `0.00` with neither. Itemized detail is never added to a total.
  The rule lives in one place, `LineAccumulator` in
  `backend/src/logstead/services/itemized.py`, used by the report and the
  itemized summary. The dashboard and carryforward read report totals only.
- **Remainder:** with a total present, the remainder is total minus itemized
  sum, and is negative when entries exceed the total.
- **Markers are protected:** generic transaction updates keep the stored
  `imported` and `itemized` values, and reject a changed `itemized`. Schedule E
  re-import replaces only imported rows, so editing an imported total no longer
  causes a duplicate total. Itemized entries are untouched by re-import.
- **Receipts** on an entry or total move with it when its date changes.
- Only the `repairs` category is enabled (`ITEMIZED_CATEGORIES`); adding a
  category is a configuration change plus a page definition on the frontend.
Reports assemble Schedule E Part I from persisted data:

- **Lines 3-4** - rental income.
- **Lines 5-17** - deductible expense categories.
- **Line 18 (Depreciation)** - sourced from computed depreciation schedules, not
  from a transaction category.
- **Line 19 (Other)** - other expenses; each requires a description.

Line 14 (Repairs) follows the itemized-expenses precedence rule above.

The reporting service (`ReportingService`) builds per-property
(`report_for`) and combined (`combined_report`) figures and can export them
(`export_report`, `export_combined_report`, returning a `ReportExport`). The
depreciation service computes schedule rows with `compute_schedule_rows`
(straight-line, mid-month convention).

## Backup documents

A backup is a versioned JSON document (`schema_version` `"1"`, plus an
`exported_at` timestamp) holding a sparse per-property tree - each property
carries only what it has (details, note, usage years, transactions, assets).
Each transaction may include `imported`, `itemized` and `notes`; all are optional
and default to false/absent, so older backups restore unchanged. Restore rejects
an invalid value before writing anything, including `itemized` outside an
enabled category or on income, and `imported` together with `itemized`.
Money is written as two-decimal strings, consistent with the rest of the system.

The document deliberately **excludes** photo/receipt metadata, import sessions,
PDF drafts, the category catalog, and depreciation schedule rows - schedules are
recomputed on restore rather than trusted from the document. Restore preserves
original ids and timestamps, so a restored dataset is indistinguishable from one
that was hand-entered. See `backend/src/logstead/models/backup.py` and
`backend/src/logstead/services/backup.py`.

### Loan backup treatment

- Each property's `loans` list carries the loan inputs in the anchor shape
  (`monthly_payment`, `anchor_balance`, `anchor_date`, optional
  `original_principal`), including `interest_overrides`. Money and the rate are
  strings and override years are string keys.
- Only the anchor shape is accepted. A loan without the anchor fields is
  rejected on restore with the usual property, loan, and field message.
- Rollup rows and payment rows are not exported. Restore rebuilds them from the
  loan, like depreciation schedules.
- `schema_version` stays `"1"`. The change is additive: a document without
  `loans` restores as zero loans.
- A backup containing `loans` that is restored by an older build silently drops
  them.
- Loans are validated before the existing data is cleared, so an invalid loan
  rejects the whole restore. The restore summary reports a `loans` count.

### Loan input model change

The loan input model changed before release (origination inputs were replaced
by the balance anchor). No migration is needed, and there is no conversion of
old-shape loans. Any locally created loans must be re-entered.

## Year-end checklist

The year-end checklist stores no data. It adds no entity, DynamoDB key prefix,
index, item attribute, or backup field. Every response is computed on demand
from existing data by `ChecklistService`
(`backend/src/logstead/services/checklist.py`), which only reads. Nothing about
a checklist item is saved, so there is no completion state to restore, migrate,
or clean up. The thresholds are code constants in
`backend/src/logstead/services/checklist_config.py`, not stored settings.

Each item reads the following existing data for the property and tax year:

| Item | Reads |
| --- | --- |
| `income_entered` | Income lines of the Schedule E report (from transactions) |
| `expenses_entered` | Expense lines of the report, excluding Line 18 (from transactions) |
| `depreciation_present` | Line 18 of the report and the count of the property's assets that have depreciation schedule rows in the year |
| `line12_source` | The report's Line 12 total, its `source`, and `superseded_manual_interest`; loan facts for the year (inclusion flag and anchor date) |
| `loan_interest_confirmed` | The report's Line 12 `source` and, per loan, the year's interest, the interest override, the anchor date, and the inclusion flag |
| `carryforward_reconciled` | The carryforward reconciliation row for the year (status, reported and expected carry-in, drift, carried-from year) and its status tolerance. This is portfolio-wide, not per property |
| `repairs_exceed_total` | The property's `repairs` transactions for the year: the entered total and the itemized entries |
| `repairs_capital_candidates` | The itemized `repairs` entries for the year (amount, date, description) |
| `receipts_missing` | The year's transactions (type, `imported` marker, amount) and whether each large expense has a receipt attached |
| `yoy_swings` | The Schedule E reports for the tax year and the prior year, line by line |
| `imported_values_edited` | The year's transactions that carry the `imported` marker, comparing `created_at` with `updated_at` |

The summary routes read the same data for several years. The property summary
uses the most recent years that have data for the property (transactions,
depreciation schedule rows, or loans), capped by `summary_year_count`. The
portfolio summary runs the checklist for each property.

Details payload notes for items that expose row-level data:

- `receipts_missing` returns at most 25 transaction rows in `details`, with the
  full count in `missing_count`.
- `imported_values_edited` returns the edited rows under the `edited` key (not
  `rows`), each with `id`, `schedule_e_line`, `amount`, and `updated_at`, plus
  `imported_count`. A row counts as edited when both timestamps parse and
  `updated_at` is later than `created_at`.

## Accountant package

The accountant package is a ZIP of reports, a transactions CSV, and receipts for
one tax year. It is built from existing data and stores nothing else: the only
persisted state is the transient Package_Job item below and the S3 objects
listed under "S3 prefixes". It adds no other entity, key prefix, index, or
backup field. The key helper is `package_job_sk` in `keys.py`, and the job
lifecycle is in `backend/src/logstead/services/package_jobs.py`.

### Package_Job item

`PK = USER#<userId>`, `SK = ACCTPKG#<jobId>`. Ownership is the partition key, so
another user's job id reads as not found. The item is transient: DynamoDB TTL
removes it after 24 hours (`JOB_TTL_SECONDS` in `package_config.py`), and reads
treat an item whose `ttl` has passed as absent even before DynamoDB reaps it.

| Attribute | Notes |
| --- | --- |
| `PK`, `SK`, `userId`, `id` | Keys, owner, and the job id (uuid) |
| `status` | `queued`, `running`, `complete`, or `failed` |
| `taxYear` | Tax year of the package |
| `propertyIds` | List of included property ids |
| `createdAt` | ISO timestamp, set on creation |
| `ttl` | Epoch seconds, creation time plus 24 hours |
| `startedAt` | ISO timestamp; set by the worker when it starts running |
| `finishedAt` | ISO timestamp; set when the job completes or fails |
| `message` | Failure message; set when the job fails |
| `objectKey` | S3 key of the ZIP; set on completion, removed on failure |
| `sizeBytes`, `sha256`, `fileCount`, `receiptCount`, `skippedReceiptCount` | Result summary; set on completion |

A `queued` or `running` job with no change for more than 900 seconds
(`JOB_STALE_SECONDS`, measured from `startedAt`, else `createdAt`) is reported
as `failed` at read time; the stored item is not rewritten. A user has at most
one active job at a time, and listing returns the 10 most recent
(`JOB_LIST_LIMIT`).

### S3 prefixes

| Key | Contents |
| --- | --- |
| `exports/packages/<user_id>/<job_id>/logstead-accountant-package-<year>.zip` | The built ZIP (`package_key` in `adapters/s3_files.py`). Deleted when the user deletes the job |
| `exports/combined/<user_id>/<tax_year>/<filename>` | Combined-report exports (`combined_export_key`). Scoped by user id so one user's export can never share a key with another's |

Receipts are read from their existing keys and copied into the ZIP; they are not
duplicated in S3. Download links are presigned and expire after 900 seconds
(`DOWNLOAD_LINK_SECONDS`).

## Activity history

Each successful create, update, delete, restore and import writes one
**activity event**, so the Activity page can show what changed and offer to
restore a deleted record. The history is a log, not a source of truth: nothing
reads it to compute a report, and no code depends on an older event existing.

| Attribute | Notes |
| --- | --- |
| `PK`, `SK` | `USER#<userId>` and `ACT#<invertedMillis>#<eventId>`. `invertedMillis` is `99999999999999 - epoch milliseconds`, 14 digits, so an ascending query returns the newest event first (`keys.activity_sk`). |
| `GSI1PK`, `GSI1SK` | Only for an event with a property: `PROPERTY#<propertyId>` and the same value as `SK`. This is the per-property view. Events without a property (backup restore, a multi-property Schedule E import) have no GSI1 keys. |
| `entityType` | `ACTIVITY` |
| `eventId`, `at` | A UUID and the ISO time in milliseconds |
| `action` | `create`, `update`, `delete`, `restore` or `import` |
| `entity` | `transaction`, `itemized_entry`, `asset`, `loan`, `property`, `backup` or `schedule_e` |
| `summary` | One line, at most 200 characters |
| `propertyId`, `propertyName`, `recordId` | Optional. The name is a copy taken at the time, so it survives a rename |
| `beforeJson`, `afterJson` | Allow-listed fields only, as JSON text, each at most 2,048 bytes. An update holds only the changed fields |
| `truncated` | `true` when a value was cut to fit |
| `restorable`, `restorePayload` | Set on a `delete` event that can be re-created safely (see below). The payload is JSON text, at most 2,048 bytes; a larger one is not stored and the event is not restorable |
| `restoredAt`, `restoredAs` | Claim and result of a restore. `restoredAs` is `pending` while a claim is in flight, then the new record id |
| `ttl` | Epoch seconds: `at` plus the retention window |

Events are plain text of user-entered fields (descriptions, notes, names, money
as strings). They never hold receipts, photos, tokens, or the full property
details.

**Allow-list.** The fields recorded for each entity are fixed in
`FIELDS` in `services/activity_events.py` (transaction and itemized entry: date,
amount, type, category_id, description, notes; asset: description, cost_basis,
placed_in_service_date, recovery_period_years; loan: description, rate, payment,
anchor balance and date, include_in_report; property: name, address_text,
property_type, business_id). A field not listed is never written.

**GSI1 use.** `GSI1` already maps `PROPERTY#<id>` to child items, and the
`ACT#` prefix does not match any existing listing query, so activity items are
never returned by another listing. The property activity route queries `GSI1`
and filters to the caller's own `PK`.

**Restorable.** Only a `delete` of a transaction (not imported, not itemized,
no receipts), an itemized entry with no receipts, any asset, or a loan with no
yearly interest overrides. The count of receipts must be known to be zero. This
matches the toast Undo rule.

**Retention.** `ttl` is `at` plus 730 days (24 months). The value is the single
constant `retention_days` in `services/activity_config.py`, and the event `ttl`
and the tests read it. The table's existing TTL attribute (`ttl`) removes
expired items, typically within a few days of expiry. Reads also skip any
event whose `ttl` has passed.

**Cost basis.** Each event is designed to stay near 4 KB: a 200-character
summary plus the bounded JSON attributes. An event costs one base-table write
and, with a property, one GSI1 write. At 4 KB, 1,000 events a month is about
4 MB added per month and about 96 MB held at steady state across the 24 months.
Reads are one query per page of up to 100 events.

**Backup interplay.** The backup export excludes activity events, and
`schema_version` stays `"1"`. Restoring a backup does not bring history back.

**Purge rules.**

| Operation | Effect on history |
| --- | --- |
| `POST /backup/clear` | Deletes all of the user's events |
| `POST /backup/restore` | Deletes the user's earlier events, then writes one `import` event for the restore |
| Property delete | Deletes that property's events (through `GSI1`), then writes one `delete` event for the property |
| Schedule E re-import | One `import` event with created and replaced counts. Replaced rows get no delete events |
| Bulk operations | One event, whatever the number of rows |

Purges run after the primary operation succeeds, delete in batches of 25, and
never raise: a failed purge is logged and leaves events to expire by `ttl`.
Recording is best effort and a separate write from the mutation, so a failure
can leave a change without an event.
