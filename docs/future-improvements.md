# Future Improvements

A running list of improvements we've identified but not yet scheduled. Nothing
here is committed work — it's a parking lot for ideas with enough context to
pick them up later.

## Reduce Amazon Textract cost on Schedule E extraction

**Status: addressed.** Resolved with upload guidance plus a page-count guard
rather than server-side PDF narrowing. The narrowing design is kept below in case
it is ever needed.

### What happened

Processing ~15 prior-year returns ran up roughly **$80** of Textract spend
(about 1,237 billed pages, ~$0.065 per page across FORMS + TABLES). The adapter
(`backend/src/logstead/adapters/textract.py`) sends the **entire uploaded PDF**
to `StartDocumentAnalysis`, but the parser
(`backend/src/logstead/services/schedule_e_parser.py`) only reads the one or two
Schedule E Part I pages. A full return is ~50 pages, so roughly 90%+ of the
billed pages were discarded. Both FORMS and TABLES are genuinely needed on the
Schedule E page, so dropping a feature was never the lever.

Part of the $80 was also a one-time debugging spike: `capture_textract.py` runs
the production adapter against whole returns, and it was used repeatedly while
fixing the H&R Block parser.

### What we did

Ask the user to upload **only the Schedule E pages**, and enforce it cheaply:

- `ExtractionService.begin_extraction` counts the uploaded PDF's pages with
  `pypdf` (no Textract) and rejects anything over `MAX_UPLOAD_PAGES` (5) with a
  message telling the user to upload only their Schedule E pages. The check runs
  before Textract is called, so a rejected upload costs nothing, and it fails
  open if the page count can't be read so it can never block an upload that
  works today.
- The upload form and page copy now say to upload only the Schedule E pages
  (usually 1-2), how to produce that PDF, and what the page limit is.

Expected cost: about $0.13 for a 2-page Schedule E, so ~15 returns is roughly
$2 instead of $80.

### Considered and deferred: automatic narrowing and result caching

Only worth revisiting if guidance plus the guard prove too much friction.

- **Server-side narrowing.** Find the Schedule E page(s) with `pypdf` text
  search, split them into a temporary S3 object (`StartDocumentAnalysis` takes an
  S3 object, not a page range), and submit only that, falling back to the whole
  PDF for scanned or unmatched documents. Needs a fallback path, a re-submit when
  the reduced PDF finds no Schedule E, and temp-object cleanup.
- **Content-hash result caching.** Cache raw Textract blocks per user and hash in
  S3 so retries and parser re-runs don't pay twice. At ~$0.13 per run this saves
  pennies once uploads are 1-2 pages, so it isn't worth the extra S3 prefix,
  lifecycle rule and PII-retention question.

### Considered and rejected

- **Route to a single feature (FORMS *or* TABLES).** The Schedule E page needs
  both.
- **`DetectDocumentText`.** Can't produce the Part I grid or key/value pairs.
- **Textract `Queries`.** Would mean rewriting hard-won layout handling for
  uncertain savings.
- **Text-layer-only extraction for digital PDFs.** The parser consumes Textract
  geometry/table blocks, so this is a real rewrite.

## Depreciation display rounding vs. the tax return (and the override tail)

### Context

For a $140,000, 27.5-year residential rental, the exact straight-line amount is
140,000 / 27.5 = **5,090.909…** per year. The app and the filed return agree on
the math but round the repeating decimal differently:

- **App: 5,091/yr.** The engine carries the exact two-decimal value (5,090.91);
  the whole-dollar display (nearest-dollar) rounds it up to 5,091.
- **Return: 5,090/yr.** Observed on a real asset (5807 36th Ave): every interior
  year reads a flat 5,090, which means the tax software **truncates** to a whole
  dollar (5,090.909 → 5,090), not nearest-dollar and not the mid-month table.

So the per-year $1 gap is purely **truncate (return) vs. nearest-dollar (app)**.
Neither is a math error; the app's schedule still sums to exactly 140,000 at the
cent level.

### Interaction with the per-year override (important, not a bug)

This asset also uses a first-year depreciation **override** (2010 pinned to the
filed 1,952 instead of the computed ~2,757.58 — see the
`depreciation-override-and-whole-dollar-display` spec). The override rolls its
entire delta into the **tail (final) year** to keep the schedule summing to
exactly the cost basis. Because the app reconciles in exact cents while the
return is built from truncated whole dollars, two things accumulate into the
app's tail year:

- the ~806 difference between the app's computed first year and the filed 1,952,
  and
- the ~$0.91/yr nearest-vs-truncate rounding gap across the interior years
  (~26 yrs × ~$0.91 ≈ ~$24).

Result, for this asset:

- **2010:** matches the return (override pins it to 1,952).
- **Interior years (2011+):** app 5,091 vs. return 5,090 — benign $1/yr.
- **Final (tail) year:** will differ by more than $1 — the app parks all the
  accumulated rounding + override delta there, by design (the exact-sum
  guarantee), whereas the return's tail follows its own truncation.
- **Totals:** both equal the cost basis (app exactly; return via its own
  per-year rounding).

### Why this matters for reconciliation

When comparing the app's depreciation (Schedule E Line 18) against the return,
expect a ~$1/yr difference on truncating assets and a larger tail-year
difference on overridden assets. This can nudge a year's Schedule E net across a
line and make the carryforward reconciliation **look** like a mismatch when the
figures are economically equivalent. It's a presentation/rounding artifact, not
a data error.

### Options (deferred)

- **Match the return's rounding convention (truncate) in the whole-dollar
  display.** The only lever that removes the per-year $1; the depreciation math
  is already correct. Treat as a deliberate decision — it would change **every**
  money figure in the app (not just depreciation), so it needs its own
  requirements/design pass, not a quiet tweak.
- **Leave as-is (recommended for now).** Nearest-dollar is the standard IRS
  display rounding; the $1/yr is expected and harmless as long as reconciliation
  treats sub-dollar (and override-tail) differences as non-mismatches.
- **Surface the rounding caveat in the UI** near depreciation / carryforward
  figures so a $1/yr or tail-year difference isn't mistaken for an error.

## Summarize where a carryforward chain first broke

**Status: addressed.** Implemented as a chain summary block above the table plus a hint on carried rows (spec: carryforward-chain-break-summary).

### Context

The carryforward page marks the first `mismatch` year and `carried` years after
it, and the mismatch hint names the line to check. The reader still has to trace
the chain by hand to see how much was dropped and where it started. On real data
the page showed 2016 to 2018 reported as `0.00` against expected carry-ins of
$2,452, $2,710 and $3,422, then a further $902 gap in 2021. The two causes were
only visible by comparing rows and drift values.

### Idea

Add a one-line summary above the table, for example: "The chain first breaks in
2016: the 2015 return carried out about $2,452, but the 2016 line shows $0. The
gap is $4,323 by 2025." The page already has what it needs: the first
`mismatch` year, the previous row's `expected_carryforward`, and the latest
year's `drift`. A second line could list later years where drift changes again
(for example 2021) as separate causes, so one root cause isn't mistaken for the
whole gap.

### Notes

- Frontend only. No new wire fields are required, and money stays in
  Money_Strings through `formatMoneyWholeDollars` with no float arithmetic.
- It should keep the existing disclaimer: this is a reconciliation aid, not tax
  advice, and the §469 limitation is not computed.
- Needs a short requirements/design pass for the wording and for how to present
  more than one break.
- Addressed: consecutive mismatch years are grouped as one break, later breaks
  are listed with their incremental amount (the change in drift), and the total
  gap is the latest reported year's drift.

## Loans: multiple balance checkpoints

### Context

Loans are anchored on a single known balance: the balance after a given
payment, the rate, and the P&I payment. The engine projects forward from that
anchor. Interest for years before the anchor, and for the part of the anchor
year before the anchor date, comes from Form 1098 overrides.

### Idea

Let a loan carry several balance checkpoints, for example the year-end balance
from each Form 1098 or a lender statement. The engine would re-anchor at each
checkpoint and amortize between them. Years between checkpoints would then get
close-to-actual generated interest without an override, and past extra
principal payments would show up as the difference between the projected and
the recorded balance.

### Notes

- Needs its own requirements/design pass. Questions to settle: how a checkpoint
  interacts with an interest override in the same year, how the UI shows the
  implied extra principal, and validation of out-of-order or inconsistent
  checkpoints.
- Backup would carry the checkpoint list. The change is additive, so
  `schema_version` can stay `"1"`.

## Security and refactor backlog follow-ups

### Context

Left open after the `security-and-refactor-backlog` spec. Details for each are in
`.kiro/specs/security-and-refactor-backlog/review.md` under "Remaining
follow-ups".

### Schedule E parser drops sparse property columns

`schedule_e_parser._prune_phantom_columns` drops any column with no Rents
(line 3) amount and fewer than two populated expense lines, because the blank
form's unused A/B/C column carries only totals and looks like that. A real
property with no rents and at most one expense line on the return would be
dropped too, losing its amounts on import (the rule keeps every column only
when it would reject all of them). A narrower test, for example matching the
column against the form's totals rows or requiring an address in the column,
would keep such a property. Low frequency, but it affects imported figures.

The property test that surfaced this
(`test_amounts_normalize_to_two_decimal_money_without_drift`) now always draws
a Rents token, so it no longer fails on it.

### Per-user S3 key prefix (A5)

New keys look like `photos/<property-id>/...`, with no user segment. Ownership is
checked before any key is issued, so this is defense in depth. Adding
`photos/<user-id>/...` would let IAM or bucket policy enforce isolation too.
Needs a migration plan for existing keys (or support both shapes), the user id
passed into `PhotoService` and `TransactionService`, and an IAM review.

### Field length and amount magnitude caps

Request strings are capped at 10,000 characters and transaction and asset
amounts at 9,999,999,999,999.99. Tighter per-field caps (name, address, notes)
and magnitude caps on loan, carryforward and Schedule E amounts would close the
remaining gaps.

### Textract status message returned to the client

A failed extraction job returns Textract's `status_message` as-is. Map known
codes to fixed user-facing text and log the original.

### Oversized uploads linger until the next list or confirm

Presigned PUT URLs can't limit size, so the server deletes oversized objects
when it next lists or confirms them. Until then they sit in S3. Switching to
presigned POST with `content-length-range` would reject them at upload time,
but both frontend upload helpers would need to change.

### Move the repo out of iCloud-synced `~/Documents`

iCloud creates `* 2.*` conflict copies of files that are changing, including
whole `node_modules/@types/* 2` folders that break `tsc -b`. `.gitignore` hides
them from git, but they confuse tooling. Moving the repo to a folder that is
not synced stops this. After the move, the `clean-icloud` and `clean-venv`
steps that `make build` runs are no longer needed; they are harmless and can be
removed from the `Makefile` later. To clear leftover copies in `node_modules`,
run `npm ci` in `frontend/` (`make deploy` already does this).

## Converting existing repairs transactions to itemized entries

### Context

The itemized-expenses feature does not convert existing repairs transactions
into itemized entries. Existing transactions remain entered totals. Only repairs
entered through the new itemized flow carry line items.

## Accountant package follow-ups

### Context

Left out of the `accountant-package` spec. A package is a ZIP the user downloads
and sends, with a PDF report, CSV and JSON files, and receipts. These items were
considered and deferred.

### Known limitation: PDF text outside Windows-1252 prints as `?`

The PDF renderer uses the standard Helvetica font without embedding it. Any
character outside Windows-1252 (for example some accented names, non-Latin
scripts, or emoji in a property name or note) prints as `?` in the PDF. The CSV
and JSON files in the package keep the original text.

### Unicode PDF font

Bundle and embed a Unicode font so characters outside Windows-1252 print as
typed. The font adds about 0.5 MB to the Lambda zip. Needs a license check on
the chosen font, a decision on whether to subset it, and updates to the PDF
text-safety tests, which currently expect `?` for these characters.

### Live sharing links and accountant accounts

A public or token-based report URL, plus accountant accounts, invitations and
roles, would let an accountant view current figures without a ZIP. Not
committed. Needs its own requirements/design pass: token scope and expiry,
revocation, what an accountant may see, audit logging, and how this fits the
single-user ownership model that every route relies on today.

### Emailing the package

Send the finished package or its download link by email from the app. Needs an
email sender (for example SES), recipient validation, and a decision on whether
to send the file or only a short-lived link. Today the user downloads the
package and sends it themselves.

### Shorter or configurable retention

Packages and generated PDFs live for 24 hours (`JOB_TTL_SECONDS` and the
one-day lifecycle rules). Package limits and retention are constants in
`services/package_config.py` and the template. A shorter retention, or one the
user can set, would reduce how long tax data sits in S3. Making it per-user
needs storage for the setting, and the lifecycle rule granularity is one day.

### Noncurrent-version expiry on existing lifecycle rules

`FilesBucket` has versioning on. The existing rules for `exports/` (30 days) and
`imports/schedule-e/` (1 day) have no `NoncurrentVersionExpiration`, so when a
current version expires the bytes stay behind as a noncurrent version. The new
package and PDF rules include noncurrent expiry. Add the same to the two
existing rules. Behavior change on a live bucket, so confirm nothing relies on
noncurrent versions first.

## Small-screen audit follow-ups (320px)

Found while auditing forms and toolbars for the ui-polish responsive pass. The
small fixes shipped (single-column forms, `flex-wrap` toolbars, sticky
`ModalFormActions` bar). These need a real browser or a larger change and were
left alone.

- **Schedule E import entry cards** (`PropertyEntryCard`, `DraftRow`): 22 line
  inputs per property in one long column on phones. A grouped or collapsible
  layout would shorten the page, but it changes the review flow.
- **Amortization and depreciation schedule tables** (`ScheduleTable` with its
  `w-28` override inputs, `YearlyRollupTable`, `PaymentRowsTable`): wide numeric
  tables that rely on the `ResponsiveTable` stacked rows. Check the editable
  schedule rows at 320px in Playwright before changing the input widths.
- **Import forms** (`ScheduleEImportForm` fixed `w-40` year select, expense
  import confirm table): fit at 320px by arithmetic but are not covered by a
  viewport test. Add them to `e2e/responsive.spec.ts` routes.
- **Property and business dialogs** are long forms. Splitting them into
  sections with a stepper would help on phones.

## Activity history follow-ups

### Restore with the original id

History restore and the toast Undo both re-create a deleted record through the
normal create route, so the record gets a new id and fresh `created_at` /
`updated_at` (see "Undo and record IDs" in the developer guide). Keeping the
original id would need a create path that accepts an id, a check that the id is
still free, and a decision about the timestamps. Links and bookmarks to the old
id would then work again. It also touches the `activityUndo` assumption that
the toast Undo never sends an id.

### Atomic activity recording

An event is a separate write made after the mutation succeeds, and a failure is
logged and ignored. A crash between the two writes, or a failed event write,
leaves a change with no event. Writing the event in the same `TransactWriteItems`
as the change would close that gap, but it needs the services to build their
write sets for the router to combine, and it breaks the rule that no domain
service knows about the history. Worth doing only if the history becomes a
record someone relies on.

### Route toast Undo through the history

The toast Undo is client-side and shows up as an ordinary `create` beside the
`delete`. Sending it to the restore route instead would link the two events,
mark the delete as restored, and stop a second restore of the same delete from
the Activity page. The cost is a request that depends on the history event still
existing (it expires after 24 months and recording is best effort), so the
toast would need a fallback to the create route.

## Search and onboarding follow-ups
### Search amounts, dates and category labels
`GET /search` matches text fields only: descriptions, notes, names, addresses and
legal names. A search for `1250` does not match an amount. Matching the stored
amount string is a small extension of `match_rank` in `services/search_match.py`.
Dates and category labels would need their own matching rules. Left out so
results stay about what a person typed into a text field.
### Search beyond the scan cap
Search reads at most 20,000 records per request and sets `truncated` when it
stops early. An account that grows past that point would need an index, or a
search store, instead of a scan. The palette matches pages, properties and tax
years in the browser and records on the server; revisit that split at the same
time.
### Onboarding state on the server
Whether the setup guide is collapsed or dismissed is stored per browser
(`localStorage`, keyed by user). Signing in on a second device shows the guide
again unless all four steps are done. A server-side preference store would fix
that. It needs a new stored item, a route and backup handling.
### Unreachable sample-data link in the setup guide
`ChecklistCard` renders an "Explore with sample data" link (to
`/profile?focus=backup`) only when the user owns no property. `DashboardPage`
never shows the card in that state: with no property it renders
`DashboardEmptyState` instead, so the card's link is dead code. New users still
reach sample data through the empty state's own button and the empty Properties
page. Two options: remove the link from `ChecklistCard` (smallest change), or
show the setup guide alongside the empty state so a first-time user sees the
"Add a property" step from the start (changes the first-run dashboard layout).
