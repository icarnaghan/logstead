# Implementation Plan: Schedule E PDF Extraction

## Overview

Convert the Schedule E PDF Extraction design ("layer 2") into incremental,
independently-schedulable coding tasks. The governing principle holds throughout:
**extraction proposes, the human confirms, layer 1 persists** — the new
`ExtractionService` performs no persistent domain writes; its only durable write
is a transient, TTL'd `Extraction_Job` record, and the uploaded PDF is
auto-deleted the moment a job reaches a terminal state. Only the user-confirmed
numbers persist, and only via the **unchanged** layer-1 `ImportService`
(`POST /imports/schedule-e`) write path.

Ordering: infra/key scaffolding first (`SEEXTRACT#` key helpers, Textract IAM
statement, S3 lifecycle rule, DynamoDB TTL), then the backend pure cores
(`schedule_e_parser`, `address_match`, service-layer models) and the
`TextractAdapter` seam, then the `ExtractionService` built up as discrete leaves
(job persistence → `start_extraction` → `begin_extraction` → `get_status` poll →
terminal-state PDF delete), then routes + per-request wiring in `router/handler.py`,
then the five Hypothesis correctness properties, then the frontend (typed
injectable `api/scheduleEExtraction.ts` → upload+extract page with the status
poller → review screen that seeds the **existing** `ScheduleEImportForm` /
`PropertyEntryCard` and hands off to the unchanged `importScheduleE`).

Every implementation step is its own decimal **leaf** so the DAG queue can
dispatch it independently; parent headings (`1.`, `5.`, ...) carry **no code**
and only group. Optional (`*`) test leaves sit beside the leaf they cover.

Separation from the existing `/imports` PDF-**expense** feature
(`ExpenseImportService`, its `IMPORT#`/`DRAFT#` storage, `api/imports.ts`,
`pages/ImportReviewPage.tsx`) is strict (Req 13): this feature mounts under the
distinct `/imports/schedule-e/extractions` surface, uses the distinct
`SEEXTRACT#` key prefix and `ExtractionService` class, and produces only a
layer-1 `ImportSubmission` draft. The handler's existing `_import_service`
(expense) and `_schedule_e_import_service` (layer-1) constructors are left
untouched; a new `_extraction_service` + `_require_textract` are added alongside.

Conventions: backend `pytest` + `moto` (S3 + DynamoDB) + a **fake/stub
`TextractAdapter`** and canned Textract-response JSON fixtures for the pure
parser — **live Amazon Textract is never called in any test**. `Hypothesis`
property tests at `@settings(max_examples=100)`, tagged
`# Feature: schedule-e-pdf-extraction, Property N: <text>`. Money as a
two-decimal `Decimal`/string through `util/money` (`to_money`, `money_to_str`);
ids and money carried as strings over the wire, snake_case bodies. Frontend
`vitest` + React Testing Library + `vitest-axe`, UI driven through an injectable
`api/` layer. Backend verify: `cd backend && .venv/bin/python -m pytest -q`.
Frontend verify: `cd frontend && npm test -- --run` and `npm run build`.

## Tasks

- [x] 1. Infra and key scaffolding

  - [x] 1.1 Add the `SEEXTRACT#` key helpers to `repository/keys.py`
    - Add the module constant `SEEXTRACT_PREFIX = "SEEXTRACT#"` alongside the existing prefix constants.
    - Add `extraction_job_sk(job_id)` → `f"{SEEXTRACT_PREFIX}{job_id}"` and `extraction_job_list_prefix()` → `SEEXTRACT_PREFIX`, documenting the `PK=USER#<userId> / SK=SEEXTRACT#<jobId>` convention in the module docstring key table.
    - The prefix must be new and distinct from `IMPORT#` / `DRAFT#` so there is zero collision with the expense feature.
    - _Requirements: 11.1, 13.2 — Design "Extraction_Job — a new transient DynamoDB entity (distinct keys + TTL)"_

  - [x]* 1.2 Write unit tests for the `SEEXTRACT#` key helpers
    - Assert `extraction_job_sk` and `extraction_job_list_prefix` emit the expected shapes and that `SEEXTRACT_PREFIX` is distinct from `IMPORT_PREFIX` / `DRAFT_PREFIX`.
    - _Requirements: 13.2_

  - [x] 1.3 Add the Textract IAM statement to `ApiFunction` in `infra/template.yaml`
    - Under `ApiFunction.Properties.Policies`, add a `Statement` granting `textract:StartDocumentAnalysis` and `textract:GetDocumentAnalysis` on `Resource: "*"` (Textract async analysis is a resource-less API).
    - Add no SNS topic and no Textract service role — the chosen v1 flow is the polling path.
    - IaC change: verify with cfn-lint / cfn validate if available, else by inspection.
    - _Requirements: 2.1 — Design "Infra / IAM deltas", item 1_

  - [x] 1.4 Add the `ExpireScheduleEImports` S3 lifecycle rule to `FilesBucket` in `infra/template.yaml`
    - Under `FilesBucket.Properties.LifecycleConfiguration.Rules`, add a sibling of the existing `ExpireExports` rule: `Id: ExpireScheduleEImports`, `Status: Enabled`, `Prefix: imports/schedule-e/`, `ExpirationInDays: 1`.
    - This is the defense-in-depth backstop for abandoned uploads (the service's explicit delete is the primary mechanism).
    - IaC change: verify with cfn-lint / cfn validate if available, else by inspection.
    - _Requirements: 10.3 — Design "Infra / IAM deltas", item 2_

  - [x] 1.5 Enable DynamoDB TTL on the `ttl` attribute of the `Logstead` table in `infra/template.yaml`
    - Add `TimeToLiveSpecification: { AttributeName: ttl, Enabled: true }` to the table resource; TTL is sparse so existing entities without a `ttl` attribute are unaffected.
    - IaC change: verify with cfn-lint / cfn validate if available, else by inspection.
    - _Requirements: 10.3, 11.1 — Design "Extraction_Job" item shape (TTL attribute `ttl`)_

  - [x]* 1.6 Write an infra assertion test for the lifecycle rule and TTL
    - Parse `infra/template.yaml` and assert `FilesBucket` carries the `ExpireScheduleEImports` rule on `imports/schedule-e/` and the `Logstead` table enables TTL on `ttl`.
    - _Requirements: 10.3 — Design "Testing Strategy" / Infra assertion_

- [x] 2. Service-layer models (`models/schedule_e_extraction.py`)

  - [x] 2.1 Define the extraction service-layer models
    - Create `models/schedule_e_extraction.py` with the `JobStatus` / `CompleteOutcome` `Literal`s and the dataclasses `StartExtractionOutcome`, `ExtractedLine`, `ExtractedColumn`, `ReviewDraft`, and `ExtractionJobView`, exactly as in the design (fields and types verbatim).
    - `ExtractedLine.schedule_e_line` is restricted to the allow-set {3,4,5-17,19}; no field for Line 18 exists.
    - These serialize through the handler's existing `_to_jsonable` (dataclasses → snake_case dicts, `Decimal` → string).
    - _Requirements: 3.1, 5.3, 6.2, 7.1, 8.1, 8.3 — Design "Input / output shapes (service-layer models)"_

  - [x]* 2.2 Write unit tests for the extraction models
    - Assert the dataclass field names/types match the wire shape and that `ExtractedLine` cannot represent Line 18.
    - _Requirements: 4.5, 8.4_

- [x] 3. Pure parser (`services/schedule_e_parser.py`)

  - [x] 3.1 Implement Schedule E Part I page location and the no-Schedule-E outcome
    - Create `services/schedule_e_parser.py` with `parse_schedule_e(blocks, *, min_confidence) -> ParsedExtraction` (pure; no S3/DynamoDB/boto3). Define the `ParsedExtraction` result (columns + detected tax year + `no_schedule_e_found` flag).
    - Scan `LINE` text for the characteristic markers ("Schedule E", "Part I", "Income or Loss From Rental Real Estate", and line labels like "Rents received", "Advertising", "Cleaning and maintenance"); treat a page as Part I only when the title/Part-I marker co-occurs with a couple of line labels. Ignore non-matching pages; when none match, return the `no_schedule_e_found` result with no columns.
    - _Requirements: 4.1, 3.4, 12.2 — Design "The parser (pure)" steps (a), (f)_

  - [x] 3.2 Implement property-column + line-amount reading for the allow-set {3,4,5-17,19}
    - For each located Part I page, produce one `ExtractedColumn` per property column (A, B, C, ...). Prefer the TABLES result (line-label row × property column cell); fall back to geometry (numeric tokens on the same horizontal band bucketed left-to-right by `Left`).
    - Read only the explicit allow-set `{3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,19}`; **never** read Line 18. An absent/unreadable allowed line becomes `0.00` with `needs_verification=true`.
    - _Requirements: 4.2, 4.3, 4.5, 4.6 — Design "The parser (pure)" step (b)_

  - [x] 3.3 Implement per-column physical-address reading
    - Read each column's "Physical address of each property" box via FORMS key text (paired value per column) with a geometry fallback bucketed into the same column positions as the amounts; populate `ExtractedColumn.address_text` / `address_confidence`.
    - _Requirements: 4.4 — Design "The parser (pure)" step (c)_

  - [x] 3.4 Implement tax-year detection and per-value confidence
    - Scan header `LINE`s for a four-digit year / "For calendar year 20YY"; set the single detected year, or leave it unset + flagged when not confidently found.
    - Attach each contributing block's `Confidence` to the produced line/address/year values and set `needs_verification=true` when confidence is below `min_confidence` or the value could not be read/normalized.
    - _Requirements: 6.1, 6.2, 6.3, 5.2, 8.3 — Design "The parser (pure)" steps (d), (e)_

  - [x]* 3.5 Write parser unit tests driven by canned Textract JSON fixtures
    - Add fixtures: a clean Schedule E Part I response, a response with **no** Schedule E, and a low-confidence/garbled response. Assert: Part I located and other pages ignored (4.1); one column per property column (4.2); lines 3-4/5-17/19 and the address box read (4.3, 4.4); Line 18 never present (4.5); unreadable cell → `0.00` + verify (4.6); tax year detected, and unset+flagged when absent (6.1, 6.2); no-Schedule-E fixture → `no_schedule_e_found` with no columns (12.2).
    - Never call live Textract — fixtures only.
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 6.1, 6.2, 12.2_

- [x] 4. Pure fuzzy address matcher (`services/address_match.py`)

  - [x] 4.1 Implement `best_match(address, candidates) -> AddressMatch | None`
    - Create `services/address_match.py` (pure; no AWS). Normalize both the extracted address and each candidate's `address_text` (lowercase, collapse whitespace, strip punctuation, standardize common abbreviations st/street, ave/avenue, apt/unit, ...). Score by token-set overlap (Jaccard over normalized tokens, numeric street-number token weighted). Return the best candidate with a `confidence`; return `None` when the top score is below threshold or there are no candidates.
    - _Requirements: 7.1, 7.3 — Design "Fuzzy property matching (pure)"_

  - [x]* 4.2 Write unit tests for the fuzzy matcher
    - Assert an exact normalized match returns high confidence; "12 Maple" vs "120 Maple" do not collide; below-threshold / empty-candidates → `None` (unmapped).
    - _Requirements: 7.3 — Design "Testing Strategy" / Fuzzy matcher_

- [x] 5. Textract adapter (`adapters/textract.py`)

  - [x] 5.1 Implement the `TextractAdapter` thin boto3 wrapper
    - Create `adapters/textract.py` mirroring `S3FileAdapter`'s injected-client shape: `__init__(self, textract_client)`; `start_document_analysis(bucket, key) -> str` (JobId, `FeatureTypes=['FORMS','TABLES']`); `get_document_analysis(job_id) -> TextractResult` draining `NextToken` pages into a single value object (`status` in {IN_PROGRESS, SUCCEEDED, FAILED, PARTIAL_SUCCESS} + aggregated blocks list + status message).
    - The adapter holds no policy — only issues the two calls and aggregates pages.
    - _Requirements: 2.1 — Design "TextractAdapter (new)"_

  - [x]* 5.2 Write adapter tests with a moto/fake Textract client
    - Assert `start_document_analysis` passes `FeatureTypes=['FORMS','TABLES']` and returns the JobId; `get_document_analysis` drains `NextToken` pages and surfaces status + aggregated blocks. Never hit live AWS.
    - _Requirements: 2.1_

- [x] 6. ExtractionService (`services/schedule_e_extraction.py`)

  - [x] 6.1 Implement `Extraction_Job` persistence (serialize / deserialize)
    - Create `services/schedule_e_extraction.py` with the `ExtractionService` constructor `(repo, user, files, textract)` composing `S3FileAdapter`, `TextractAdapter`, the repo, and (lazily) `PropertyService`. Implement job-item serialize/deserialize for the item shape in the design (`id`, `userId`, `status`, `outcome`, `uploadedKey`, `textractJobId`, `message`, `reviewDraftJson`, `createdAt`, `ttl`) keyed at `PK=user_pk(user)` / `SK=extraction_job_sk(jobId)`; `reviewDraftJson` holds the serialized `ReviewDraft` with two-decimal money strings.
    - _Requirements: 11.1 — Design "ExtractionService", "Extraction_Job" item shape_

  - [x]* 6.2 Write unit tests for job persistence round-trip (moto DynamoDB)
    - Assert a job (including a cached `ReviewDraft` with money strings and a `ttl`) round-trips through serialize → put → get → deserialize unchanged, under the `USER#<user> / SEEXTRACT#<jobId>` keys.
    - _Requirements: 11.1_

  - [x] 6.3 Implement `start_extraction(filename, content_type)`
    - Validate the declared content type is the PDF content type; on a non-PDF return `Result.failure("validation", ..., field="file")` with no job and no URL issued. On success mint a job id, issue a presigned PUT to `imports/schedule-e/<user>/<jobId>.pdf` (via `S3FileAdapter.presigned_put_url` bound to `application/pdf`), persist the job `status="pending"` with `ttl` set, and return `StartExtractionOutcome(job_id, upload_url)`.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.3 — Design "ExtractionService.start_extraction", two-step-start note_

  - [x]* 6.4 Write unit tests for `start_extraction` (moto S3/DynamoDB)
    - Assert PDF content type presigns with `application/pdf` and creates a `pending` job scoped under the user; a non-PDF content type → `validation(field="file")`, no job, no URL.
    - _Requirements: 1.3, 1.4, 2.3_

  - [x] 6.5 Implement `begin_extraction(job_id)`
    - Load the job scoped to the user (`not_found` when missing / owned by another user). Confirm the uploaded object exists and is a PDF by content type or `%PDF-` byte signature; when absent → `not_found` and Textract is never called; when present-but-not-a-PDF → mark the job `failed` with "a valid PDF is required" and delete the object. On success call `TextractAdapter.start_document_analysis`, store `textractJobId`, mark `status="processing"`, and return the `ExtractionJobView`.
    - _Requirements: 1.5, 2.1, 2.2, 2.4, 11.2, 12.1 — Design "ExtractionService.begin_extraction"_

  - [x]* 6.6 Write unit tests for `begin_extraction` (moto + fake Textract)
    - Assert: absent / other-user object → `not_found`, Textract never called; object without `%PDF-` → `failed` + "valid PDF required" + object deleted; valid PDF → `processing` with `textractJobId` set.
    - _Requirements: 1.5, 2.4, 11.2, 12.1_

  - [x] 6.7 Implement `get_status(job_id)` polling with parse-once caching
    - Load the job scoped to the user (`not_found` otherwise). When `status in {complete, failed}` return the cached result without re-calling Textract or re-parsing. When `processing`, call `TextractAdapter.get_document_analysis`: `IN_PROGRESS` → `processing`; `FAILED`/`PARTIAL_SUCCESS` with no usable blocks → `failed` + message; `SUCCEEDED` → drain pages, `parse_schedule_e(blocks, min_confidence=...)`, then either build the `ReviewDraft` (fuzzy-match via `address_match.best_match` over `PropertyService.list()`, normalize money via `util/money.to_money`/`money_to_str`), cache it as `reviewDraftJson`, and mark `complete`/`outcome="draft"`, OR mark `complete`/`outcome="no_schedule_e_found"` with no draft. Return the `ExtractionJobView`.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.1, 5.3, 6.1, 7.1, 7.3, 7.5, 11.2, 12.2, 12.3 — Design "ExtractionService.get_status", "The async-completion mechanism", "Pagination of Textract results"_

  - [x]* 6.8 Write unit tests for `get_status` (moto + fake Textract)
    - Assert the status mapping (`IN_PROGRESS→processing`, `FAILED→failed`+message, `SUCCEEDED`+Schedule-E fixture → `complete`/`draft`, `SUCCEEDED`+non-Schedule-E fixture → `complete`/`no_schedule_e_found` with no draft); parse-and-cache runs once and later polls return the cached draft without re-calling Textract; a poll for a job not in the user's scope → `not_found`.
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.6, 12.2, 12.3_

  - [x] 6.9 Implement terminal-state auto-delete of the uploaded PDF
    - On every transition to `complete` (draft or no-Schedule-E) or `failed`, call `S3FileAdapter.delete_object(uploadedKey)` as the primary deletion (idempotent); keep `uploadedKey` on the job only to target the delete. No transaction or Property is ever created/modified/deleted by extraction.
    - _Requirements: 10.1, 10.2, 10.4, 12.3, 12.5 — Design "Auto-delete of the uploaded PDF"_

  - [x]* 6.10 Write unit tests for terminal-state PDF deletion
    - Assert the uploaded object is absent from S3 after `complete` (draft and no-Schedule-E) and after `failed`, and that no transaction/Property rows change across any outcome.
    - _Requirements: 10.1, 10.2, 10.4, 12.5_

- [x] 7. Routes and per-request wiring (`router/handler.py`)

  - [x] 7.1 Add the lazy Textract adapter to the container wiring
    - In `_build_wiring_from_env`, construct the boto3 `textract` client lazily (like the S3 client) and build a `TextractAdapter`, stored on `_Wiring` as `wiring.textract`; extend `_Wiring.__init__` and `configure(...)` with an optional `textract` collaborator (defaulting to `None`) so tests can inject a fake. Leave the existing `files`/`rentcast`/`autocomplete` wiring untouched.
    - _Requirements: 2.1 — Design "Route surface + wiring" / Per-request wiring_

  - [x] 7.2 Add `_require_textract` and `_extraction_service` constructors
    - Add `_require_textract(wiring)` returning `wiring.textract` or raising a `_RouterError(503, ...)` when unconfigured (mirroring `_require_files`), and `_extraction_service(wiring, user)` constructing `ExtractionService(wiring.repo, user, files=_require_files(wiring), textract=_require_textract(wiring))`. Leave `_import_service` (expense) and `_schedule_e_import_service` (layer-1) unchanged.
    - _Requirements: 11.1, 13.2 — Design "Route surface + wiring" / Per-request wiring_

  - [x] 7.3 Add the three thin extraction handlers
    - Add `_start_extraction` (parse `filename`/`content_type` from the body, call `start_extraction`, map `Result→HTTP` with `success_status=201`), `_begin_extraction` (`jobId` path param → `begin_extraction`, 200), and `_get_extraction` (`jobId` path param → `get_status`, 200). Handlers stay thin (parse + wire + `Result→HTTP`), no business rules — mirror `_import_schedule_e`. A `failed`/`no_schedule_e_found` poll is a successful `200` whose body carries the negative outcome.
    - _Requirements: 2.2, 3.1, 3.4, 3.5, 13.1 — Design "Route surface + wiring" (request/response shapes)_

  - [x] 7.4 Register the extraction routes in `_ROUTES`
    - Add `("POST", "/imports/schedule-e/extractions", _start_extraction, False)`, `("POST", "/imports/schedule-e/extractions/{jobId}/start", _begin_extraction, False)`, and `("GET", "/imports/schedule-e/extractions/{jobId}", _get_extraction, False)`, placed with the existing Schedule E entries and **before** the expense `/imports` entries. The literal `schedule-e`/`extractions` segments and distinct segment counts (3, 5, 4) disambiguate them from `/imports/schedule-e` (2-seg layer-1), `/imports/schedule-e/{propertyId}/{taxYear}` (4-seg layer-1 undo), and the expense `/imports/{sessionId}` (2-seg) under `_match_path`.
    - _Requirements: 13.1, 13.2 — Design "Route surface + wiring" (placement in `_ROUTES`)_

  - [x]* 7.5 Write handler/integration tests incl. a routing regression guard
    - Assert the three new routes resolve to the extraction handlers and return 201/200 as specified (fake Textract via `configure`); a non-PDF `start_extraction` → 400; a job not in the user's scope → 404; Textract unconfigured → 503. Regression: assert `/imports/{sessionId}` still resolves to the untouched expense handler and `/imports/schedule-e` + `/imports/schedule-e/{propertyId}/{taxYear}` still resolve to the layer-1 handlers.
    - _Requirements: 2.4, 3.6, 13.1, 13.2_

- [x] 8. Backend correctness property tests (Hypothesis, `@settings(max_examples=100)`)

  - [x]* 8.1 Property 1 — extraction never writes a transaction or property
    - `# Feature: schedule-e-pdf-extraction, Property 1: Extraction never writes a transaction or property`
    - Generate arbitrary start→upload→begin→poll sequences across all three Textract outcomes (SUCCEEDED-draft, SUCCEEDED-no-Schedule-E, FAILED) on moto + fake Textract; assert the user's Transaction and Property rows are exactly unchanged — only the layer-1 confirm path ever writes.
    - **Validates: Requirements 9.1, 7.2, 12.5**

  - [x]* 8.2 Property 2 — the uploaded PDF is always deleted on a terminal state
    - `# Feature: schedule-e-pdf-extraction, Property 2: The uploaded PDF is always deleted on a terminal state`
    - For any job that reaches `complete` (draft or no-Schedule-E) or `failed`, assert the uploaded object is absent from S3 after the terminal transition.
    - **Validates: Requirements 10.1, 10.2, 10.4, 12.3**

  - [x]* 8.3 Property 3 — amounts normalize to two-decimal money with no drift; unreadable values flagged, not dropped
    - `# Feature: schedule-e-pdf-extraction, Property 3: Extracted amounts normalize to two-decimal money with no drift, and unreadable values are flagged, not dropped`
    - Drive a Hypothesis generator that builds a Schedule E Part I Textract-shaped block fixture (random column count, random per-line amounts incl. blanks/garbled, optional Line 18, random year/addresses). Assert each draft amount equals `money_to_str(to_money(token))` with no drift, and an un-normalizable amount yields `"0.00"` + `needs_verification` while still keeping the column (parser round-trip of amounts/addresses/year folded in).
    - **Validates: Requirements 5.1, 5.2, 5.3, 4.6**

  - [x]* 8.4 Property 4 — per-user scoping isolates jobs, drafts, and uploaded objects
    - `# Feature: schedule-e-pdf-extraction, Property 4: Per-user scoping isolates jobs, drafts, and uploaded objects`
    - Generate two distinct users; assert a job/draft/object created by A resolves to `not_found` on every read/poll/begin by B, and that `best_match` candidates for A's columns come only from A's `PropertyService.list()` (fold in the matcher happy path).
    - **Validates: Requirements 11.1, 11.2, 1.1, 1.2, 2.2, 3.6, 7.5**

  - [x]* 8.5 Property 5 — no Line 18 (Depreciation) ever appears in a Review_Draft
    - `# Feature: schedule-e-pdf-extraction, Property 5: No Line 18 (Depreciation) ever appears in a Review_Draft`
    - For any generated document — including one whose Part I carries a Line 18 amount — assert the produced `ReviewDraft` contains no `ExtractedLine` with `schedule_e_line == 18` (parser reads only the allow-set {3,4,5-17,19}).
    - **Validates: Requirements 4.5, 8.4**

- [x] 9. Backend checkpoint
  - Run the full backend suite: `cd backend && .venv/bin/python -m pytest -q`. Regression guard: BOTH the existing `/imports` PDF-expense feature (`ExpenseImportService`, `IMPORT#`/`DRAFT#`, its routes) AND the layer-1 `/imports/schedule-e` import feature must still pass unchanged. Ensure all tests pass, ask the user if questions arise.

- [x] 10. Frontend API module (`api/scheduleEExtraction.ts`)

  - [x] 10.1 Implement the typed injectable extraction api module
    - Create `api/scheduleEExtraction.ts` (transport-only, snake_case wire types mirroring `ExtractionJobView`): `startExtraction(filename, contentType) -> { job_id, upload_url }` (`POST /imports/schedule-e/extractions`), `beginExtraction(jobId) -> { job_id, status }` (`POST .../extractions/{jobId}/start`), `getExtraction(jobId) -> { status, outcome, message, review_draft }` (`GET .../extractions/{jobId}`), and re-export/reuse `uploadToPresignedUrl` from `api/photos.ts`. Provide an injectable client (set/reset) like `api/scheduleEImport.ts`. Money and ids are strings. Keep this separate from `api/imports.ts` and `api/scheduleEImport.ts` (both untouched).
    - _Requirements: 1.1, 2.2, 3.1, 5.3, 13.1 — Design "New api module `api/scheduleEExtraction.ts`"_

  - [x]* 10.2 Write unit tests for the extraction api module
    - With an injected fake client, assert each call hits the correct method/path and parses the snake_case response; money/ids stay strings.
    - _Requirements: 1.1, 2.2, 3.1_

- [x] 11. Frontend upload + extract page (`pages/ScheduleEExtractionPage.tsx`)

  - [x] 11.1 Add the page shell, route, and nav entry
    - Create `pages/ScheduleEExtractionPage.tsx` (distinct from `pages/ImportReviewPage.tsx` and `pages/ScheduleEImportPage.tsx`); add `<Route path="imports/schedule-e/extract" element={<ScheduleEExtractionPage />} />` in `App.tsx` beside the existing `imports/schedule-e` route, and a nav entry to reach it.
    - _Requirements: 13.1 — Design "Frontend components (SPA)" / Upload + extract page_

  - [x] 11.2 Implement the file picker + presign → PUT → begin flow
    - A PDF file input that rejects non-PDF files client-side before requesting a URL (mirroring the photo content-type guard, matching the backend `application/pdf` binding), then `startExtraction(filename, "application/pdf")` → `uploadToPresignedUrl(upload_url, file)` (reuse the existing helper verbatim) → `beginExtraction(job_id)`.
    - _Requirements: 1.3, 1.4, 2.1 — Design "Upload + extract page"_

  - [x] 11.3 Implement the job-status poller hook and status rendering
    - Add a small `useExtractionJob(jobId)` hook that polls `getExtraction` on an interval while `status in {pending, processing}`, stops on `complete`/`failed`, uses an `AbortController`, and clears its timer on unmount; render pending/processing/complete/failed and the distinct "no Schedule E found" message.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 12.2 — Design "Job-status poller"_

  - [x]* 11.4 Write RTL + axe tests for the upload page and poller
    - Assert non-PDF files are rejected client-side and the presign→PUT→begin flow runs against a fake api (1.4); the poller transitions pending/processing→complete/failed and stops on a terminal state; `vitest-axe` has no violations.
    - _Requirements: 1.4, 3.2, 3.3_

- [x] 12. Frontend review screen (seed the existing layer-1 form)

  - [x] 12.1 Add additive seed props to `ScheduleEImportForm`
    - Extend `ScheduleEImportForm` with optional, defaulted `initialTaxYear` / `initialEntries` props so an extraction `ReviewDraft` can seed the form (one `EntryState` per `ExtractedColumn`: `amounts` from the extracted lines, `propertyId` pre-selected to `suggested_property_id` when present, `otherDescription` from the Line 19 extract). Defaults keep the existing manual-entry mount in `pages/ScheduleEImportPage.tsx` unchanged.
    - _Requirements: 8.1, 8.2 — Design "Review screen (reuses layer-1 components)"_

  - [x] 12.2 Render the review screen seeded from the draft on `complete`/`draft`
    - On `status=complete, outcome="draft"`, map the `review_draft` into `initialTaxYear`/`initialEntries` and render the **existing** `ScheduleEImportForm` / `PropertyEntryCard`: one card per column with pre-filled, editable amounts and the suggested mapping shown but never auto-applied.
    - _Requirements: 7.2, 8.1, 8.2, 8.5 — Design "Review screen"_

  - [x] 12.3 Surface per-value confidence / "please verify" indicators
    - Show an accessible, informational "verify" badge (distinct from an error) on each pre-filled line input when `needs_verification` is true, and show the suggested property name + mapping confidence requiring explicit confirm; never render a Line 18 field (inherited from the layer-1 form).
    - _Requirements: 7.2, 8.3, 8.4 — Design "Confidence / 'please verify' surfacing"_

  - [x] 12.4 Wire confirm handoff to the unchanged `importScheduleE` and route layer-1 errors
    - On confirm, submit the edited draft via the **existing** `importScheduleE` (`POST /imports/schedule-e`) with no change; surface layer-1 per-entry/per-field validation errors (and the not-owned-property 404) back onto the form via the existing structured-field routing, persisting nothing on failure.
    - _Requirements: 9.2, 9.3, 9.4, 11.3 — Design "Review screen" / confirm hand-off_

  - [x] 12.5 Implement the manual-form fallback on no-Schedule-E / failure
    - On `status=failed` or `outcome="no_schedule_e_found"`, offer a one-click path to the layer-1 manual guided form (`pages/ScheduleEImportPage.tsx`) with no pre-fill.
    - _Requirements: 12.4 — Design "Error Handling" (manual fallback)_

  - [x]* 12.6 Write RTL + axe tests for the review screen
    - Assert: one card per column seeded with pre-filled amounts and the suggested mapping shown (never auto-applied) (8.1, 7.2); each amount editable and an edit flows into the submitted `ImportSubmission` (8.2, 8.5); a low-confidence value shows an accessible "verify" badge (8.3); no Line 18 field rendered (8.4); confirm posts to `importScheduleE` and a layer-1 validation error routes to the right field (9.2, 9.4); `failed`/`no_schedule_e_found` offer the manual-form link (12.4); `vitest-axe` has no violations.
    - _Requirements: 7.2, 8.1, 8.2, 8.3, 8.4, 8.5, 9.2, 9.4, 12.4_

- [x] 13. Final checkpoint
  - Run the full backend suite (`cd backend && .venv/bin/python -m pytest -q`), the frontend tests (`cd frontend && npm test -- --run`), and the frontend build (`npm run build`). Ensure all pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test leaves and can be skipped for a faster MVP; core implementation leaves are never optional.
- Each leaf references the specific requirement clause(s) and/or design element it satisfies for traceability.
- Parent headings (`1.`, `3.`, `6.`, ...) carry no code and only group schedulable decimal leaves.
- Live Amazon Textract is never called in any test: the adapter seam is always a `moto` client or an in-memory fake returning canned Textract-shaped block fixtures.
- The five correctness properties map one-to-one to leaves 8.1-8.5, each tagged and citing its validated requirements.
- The existing `/imports` PDF-expense feature and the layer-1 `/imports/schedule-e` feature are left untouched; this feature adds only new modules, the new `SEEXTRACT#` key, new routes, and additive/defaulted props and wiring.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "1.4", "1.5", "2.1", "3.1", "4.1", "5.1", "10.1"] },
    { "id": 1, "tasks": ["1.2", "1.6", "2.2", "3.2", "3.3", "4.2", "5.2", "6.1", "10.2", "11.1", "12.1"] },
    { "id": 2, "tasks": ["3.4", "6.2", "6.3", "6.5", "11.2", "12.5"] },
    { "id": 3, "tasks": ["3.5", "6.4", "6.6", "6.7", "6.9", "7.1", "11.3", "12.2"] },
    { "id": 4, "tasks": ["6.8", "6.10", "7.2", "7.3", "11.4", "12.3"] },
    { "id": 5, "tasks": ["7.4", "8.1", "8.2", "8.3", "8.4", "8.5", "12.4"] },
    { "id": 6, "tasks": ["7.5", "12.6"] }
  ]
}
```
