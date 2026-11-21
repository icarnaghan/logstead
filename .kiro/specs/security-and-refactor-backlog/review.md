# Security and Best-Practices Review

Scope: a targeted review, not an exhaustive audit. Read in full or in part: frontend auth/session/API client, `infra/template.yaml`, the new UI work from the ui-polish-and-consistency branch, `package.json`, tracked-file hygiene. Sampled only: backend adapters (autocomplete). NOT reviewed in depth: backend request handlers, DynamoDB access patterns, input validation, the extraction service. Those are listed as audit tasks, not findings.

`npm audit --omit=dev` reports 0 known vulnerabilities (frontend).

## Findings

### Security

| ID | Severity | Finding |
|----|----------|---------|
| S1 | High | No security response headers on CloudFront (no CSP, HSTS, X-Content-Type-Options, frame-ancestors, Referrer-Policy). A strict CSP is the main mitigation for token theft via XSS because tokens live in JS-readable storage. |
| S2 | Medium | Access, ID and refresh tokens are stored in `sessionStorage` (`lib/session.ts`). Any XSS can read them. The refresh token is stored but never used anywhere in `src`, so it adds exposure for no benefit. **Resolved (task 1.2):** refresh token no longer stored; legacy key removed. |
| S3 | Medium | No session renewal path. Tokens expire and `getToken` returns null; users are bounced to sign in. If renewal is added, do it with care (see S2). **Decision (task 1.2):** silent renewal not implemented; users re-sign in on expiry. See developer guide, "Session tokens". |
| S4 | Medium | API Gateway has no visible throttling or WAF. Public `GET /categories` and the autocomplete/enrichment endpoints (paid third parties: RentCast, Amazon Location, Textract) can be abused for cost. Needs per-route throttling and per-user limits. **Update (task 2.3):** monthly budget (80% actual / 100% forecast) and per-route request-count alarms for the paid routes added, notifying `AlertEmail` when set; RentCast usage is tracked via the `POST /properties/enrich` count (see docs/decisions/waf.md). cfn-lint passes; not deployed. |
| S5 | Medium | IAM uses `Resource: "*"` for `geo-places:*` and `textract:*`. Geo-places is resource-less, but Textract grants should be reviewed and scoped where the API allows. **Resolved (task 3.1):** per the [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_geo-places.html), geo-places:Autocomplete/Geocode do support the `provider` resource, so the grant is now scoped to `arn:aws:geo-places:<region>::provider/default`. textract:StartDocumentAnalysis/GetDocumentAnalysis have no resource types or condition keys ([service reference JSON](https://servicereference.us-east-1.amazonaws.com/v1/textract/textract.json)), so `"*"` stays, with an explanatory comment. `S3CrudPolicy` was replaced with explicit `s3:GetObject`/`PutObject` on `photos/ receipts/ business-docs/ imports/ exports/` and `s3:DeleteObject` on all but `exports/`. `DynamoDBCrudPolicy` is kept (table-scoped; a few unused actions, noted in a comment). Added `ReservedConcurrentExecutions: 10` (docs/decisions/waf.md). cfn-lint and `sam validate --lint` pass; not deployed. **Enforced in CI (task 3.3):** cfn-guard rule `iam_least_privilege` in `infra/guard/rules.guard` fails on Action `"*"` or an Allow with Resource `"*"` unless every action is `textract:*` (the documented exception). See "IaC policy checks". |
| S6 | Medium | S3 files bucket CORS: when no custom domain is set, `AllowedOrigins` falls back to `"*"` with `AllowedHeaders: ["*"]` and PUT/POST. Fine for dev only; must not reach production.**Resolved (task 3.2):** the `*` origin is gone. The bucket allows one origin: `https://<DomainName>` with a custom domain, else the new `AllowedSpaOrigin` parameter, else `http://localhost:5173`. The CloudFront domain can't be referenced from the bucket (CSP policy -> bucket, distribution -> policy), so non-custom-domain deploys set `AllowedSpaOrigin` from the `CloudFrontDomain` output on a second deploy (documented in docs/deployment.md and samconfig.toml.example). `AllowedHeaders` is now `[Content-Type]` (all the frontend sends on presigned PUTs), methods `GET, PUT, HEAD` (POST dropped), `ExposedHeaders: [ETag]` kept. `DomainName` is not hard-required by a template rule (CloudFormation can't make a parameter conditionally required); a custom-domain deploy already needs the cert and domain. cfn-lint passes; not deployed. **Enforced in CI (task 3.3):** cfn-guard rule `s3_cors_no_wildcard` fails on a `"*"` AllowedOrigins (including inside the nested `!If` branches) or AllowedHeaders. |
| S7 | Low | `target`/`rel` and `window.open` usage not found, and no `dangerouslySetInnerHTML` or `eval` in source (good). Keep it that way with a lint rule (see R1). |
| S8 | Low | Presigned upload: confirm the backend pins `ContentType`, maximum size and key prefix per user; the client only sends what it is given. **Audited (task 4.3).** Content type pinned and allow-listed, short expiry, filenames sanitised, size enforced server-side after upload. Per-user key prefix left as a recommendation (see A5). See "Presigned upload audit". |
| S9 | Low | `.env.production` is not tracked (good). `frontend/.env.example` is. Confirm no real IDs are in it. |
| S10 | Info | PKCE and `state` are implemented (verifier and state stored in sessionStorage, validated on callback). No `nonce` handling was seen; ID token signature/claims are validated server-side by the JWT authorizer, but confirm the client never trusts decoded ID-token claims for authorization. |

### Best practices and maintainability

| ID | Finding |
|----|---------|
| R1 | No ESLint. `npm run lint` is just `tsc --noEmit`. There is no `react-hooks/exhaustive-deps`, no security plugin, no import hygiene. An `eslint-disable` was added in `Button.tsx` and others rely on manual care. |
| R2 | Dependency ranges are mixed (`^` on most, exact pins on newer additions). No lockfile policy, no Dependabot/Renovate, no `npm audit` in CI that we can see. |
| R3 | Every page hand-rolls `loading/error/data` state plus `useFirstLoad` plumbing (about 10 pages). Extract a shared `useAsyncResource` (abortable, retry, refreshing) to cut duplication and race bugs (several pages needed ad-hoc `loadedFor` guards). |
| R4 | Very large files: `CarryforwardPage.tsx` (~1,180 lines), `PropertyDetailPage.tsx` (~620), `AssetsPage.tsx` (~555). Split into feature folders with hooks and subcomponents. |
| R5 | `ResponsiveTable` renders every cell twice (table and card list). This forced id workarounds (`useId`) and doubled queries in tests. Consider one DOM with responsive CSS, or render only one layout via a `useMediaQuery` hook. |
| R6 | Several tests rely on source-text scans and raw-file reads (`touchTargets`, `pageConformance`, `paletteRules`). They are useful guards but brittle; pair with real rendered assertions and move class-contract checks into a lint rule where possible. |
| R7 | Tests repeat jsdom polyfills (pointer capture, localStorage stub) in several files. Move to `vitest.setup`. |
| R8 | Color contrast cannot be verified in jsdom (axe rule disabled). Add a browser-based a11y check (Playwright + axe) for key routes in both themes. |
| R9 | Repo hygiene: `.hypothesis/`, `.pytest_cache/`, `.aws-sam/` and `dist/` exist in the working tree; confirm all are ignored. Untracked Finder duplicates (`* 2.tsx`) appeared during the work and should be purged. **Resolution (5.5):** root `.gitignore` now also covers `.hypothesis/`, `*.tsbuildinfo` and a `* 2` / `* 2.*` guard; frontend/ and backend/ already covered the rest. None are tracked and no `* 2*` duplicates exist on disk, so nothing was deleted. Likely root cause: the repo lives under the iCloud-synced `~/Documents`, which creates conflict copies named "name 2". |
| R10 | `console.warn` dev-only warnings exist in `Button`; fine, but there is no central logger or error boundary strategy beyond a logo boundary. Add a top-level error boundary with safe messaging. |
| R11 | Undo for safe deletes re-creates records with new IDs. Document that links to the old ID break, and make sure audit trails/imports are not affected. **Resolution (6.6):** audited: only transactions, loans and assets are undoable, and each gets a new id. Nothing else stores those ids (children are derived schedule rows or excluded by the safe-delete classifiers), imported transactions and transactions with receipts are never undoable, and properties, businesses, photos and receipts have no Undo. No bug found. Documented in docs/developer-guide.md ("Undo and record IDs"), tested in `frontend/src/lib/undoIds.test.tsx`. Known limitation: restored records get fresh `created_at`/`updated_at`. |
| R12 | `lib/apiClient` attaches the access token to all calls; verify absolute URLs cannot be passed (token leakage to other origins) and that `uploadToPresignedUrl` never carries it. |

## Backend authorization audit

Scope: every route in `backend/src/logstead/router/handler.py` (`_ROUTES`, 74 entries), the services they call, and the repository key scheme. Task 4.1.

### Method

* **Identity.** `current_user()` reads only `requestContext.authorizer.jwt.claims.sub`. No handler reads a user id from the body, query string or path (`_property_input`, `_business_input`, `_transaction_input` etc. never map one). Verified by `test_user_id_comes_only_from_jwt_claims`. Missing claims give 401.
* **Key scheme.** `USER#<sub>` partitions are user-scoped by construction. `PROPERTY#<id>`, `BUSINESS#<id>` and `IMPORT#<id>` partitions are keyed by resource id only, and the GSI2 tax-year partition (`PROPERTY#<id>#YEAR#<y>`) and GSI1 import index (`PROPERTY#<id>`) are too. Isolation for everything under a property therefore depends on proving ownership of the property first. Ownership lives on `PROPERTY#<id>/META.userId`.
* **Test.** `backend/tests/router/test_cross_user_authorization.py` creates one of every resource type as user A, then calls every route below as user B with A's real ids. Each response must be 404 and identical to the response for a random non-existent id. A second test checks that A's data is unchanged after all of B's writes and deletes.

### Findings and fixes

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| A1 | **Critical** | Photos, transactions, receipts, depreciable assets and asset schedules had no ownership check. `TransactionService`, `PhotoService` and `DepreciationService` take no user and key by property id, so any signed-in user who knew a property id could read, edit and delete another user's transactions, receipts (with presigned GET/PUT URLs), photos and assets. | **Fixed.** `_property_scoped` decorator in the router calls `PropertyService.get` first; foreign and missing ids return the same 404. |
| A2 | **Critical** | Expense-import sessions (`/imports/{sessionId}...`) had no owner. Any user could read, edit or confirm another user's session, and `POST /imports` accepted any `property_id`. Confirm would write transactions into the victim's property. | **Fixed.** `POST /imports` checks the property. Every session route resolves the session's property and checks ownership (`_require_owned_session`). Foreign and missing sessions return the same 404. |
| A3 | **High** | `POST /backup/restore` preserves ids from the uploaded document. A document reusing another user's property id overwrote that user's META/list rows and children and flipped `userId`, taking the property over. | **Fixed.** Before the clear, restore rejects any document property whose META row belongs to a different user (400, `field=id`). Nothing is mutated on refusal. Residual: this reveals that the uuid is in use; only someone who already holds the uuid can probe it. |
| A4 | Medium | `ExpenseImportService.confirm` built `TransactionService(self._repo)` without the required `files` argument, so confirm without an injected creator raised `TypeError` (500). | **Fixed** in `_import_service`: the router injects a creator that builds the file-backed `TransactionService` on demand. |
| A5 | Low | S3 keys are `photos/<propertyId>/<photoId>/<name>`, `receipts/<txnId>/<docId>/<name>`, `business-docs/<businessId>/<docId>/<name>`. They contain unguessable uuids but not the user's `sub`, so a bucket-level policy cannot scope by user. Only the Schedule E extraction key (`imports/schedule-e/<sub>/<jobId>.pdf`) includes the user. With A1 fixed, a key is only issued after the property or business is proven owned, so there is no cross-user path through the API. `filename` is client-controlled and not sanitised (`..`, `/`); the presigned signature binds the exact key, so it cannot reach another object. | **Partly fixed (task 4.3).** `filename` is now sanitised to a safe basename. **Open, recommended:** add `<sub>/` after the top-level prefix on new keys; not done because `PhotoService` and `TransactionService` have no user id (constructed in ~10 places incl. backup/import) and ownership is already proven by the property/business/transaction id. Needs a migration plan for existing objects and an infra IAM review (task owner for infra). |
| A6 | Info | Ownership error bodies are identical for missing and foreign ids except the message text, which is the same string for both cases per route. No 403 is returned anywhere. | OK |

### Route verdicts

Legend: **PASS** = user from JWT, ownership proven, 404 for foreign ids (covered by a cross-user test). **FIXED** = was vulnerable, now PASS. **N/A** = no per-user data.

| Route | Verdict | How access is scoped |
|-------|---------|----------------------|
| `GET /categories` | N/A | Static catalog, no user data. Now requires sign-in (task 2.2) |
| `GET /addresses`, `GET /addresses/units`, `POST /properties/enrich` | N/A | Authenticated; call external providers only, no stored data. Cost abuse is tracked as S4 |
| `POST /properties`, `GET /properties` | PASS | `USER#<sub>` partition; owner set from JWT |
| `GET/PUT/DELETE /properties/{propertyId}` | PASS | `_owned_meta` compares `META.userId` to JWT sub |
| `GET/PUT /properties/{propertyId}/usage`, `/notes` | PASS | `_owned_meta` in service |
| `GET /properties/{propertyId}/earliest-year` | PASS | Router `PropertyService.get` first |
| `PUT /properties/{propertyId}/business` | PASS | Property owned and target business owned (`set_business`) |
| `POST/GET /properties/{propertyId}/photos`, `DELETE .../photos/{photoId}`, `PUT .../photos/{photoId}/cover` | FIXED | `_property_scoped` |
| `POST/GET /properties/{propertyId}/transactions` (incl. `?taxYear=`, GSI2) | FIXED | `_property_scoped`; GSI2 partition is only queried after the check |
| `GET/PUT/DELETE /properties/{propertyId}/transactions/{transactionId}` | FIXED | `_property_scoped` |
| `POST/GET /properties/{propertyId}/transactions/{transactionId}/receipts`, `DELETE .../receipts/{documentId}` | FIXED | `_property_scoped`; presigned key from the owned transaction |
| `POST/GET /properties/{propertyId}/assets`, `GET/PUT/DELETE .../assets/{assetId}`, `GET .../assets/{assetId}/schedule` | FIXED | `_property_scoped` |
| `POST/GET /properties/{propertyId}/loans`, `GET .../loans/line-12-impact`, `GET/PUT/DELETE .../loans/{loanId}`, `GET .../schedule`, `PUT/DELETE .../interest-overrides/{taxYear}` | PASS | Each handler calls `_require_owned_property` first |
| `GET /properties/{propertyId}/report` | PASS | `ReportingService.report_for` calls user-scoped `PropertyService.get` |
| `GET /reports/combined` (incl. `propertyIds=`) | PASS | Default list is the user's properties; explicit ids go through `report_for` |
| `POST /imports` | FIXED | Body `property_id` ownership checked |
| `GET /imports/{sessionId}`, `.../drafts`, `PUT/DELETE .../drafts/{draftId}`, `POST .../confirm` | FIXED | `_require_owned_session` (session to property to owner) |
| `POST /imports/schedule-e`, `DELETE /imports/schedule-e/{propertyId}/{taxYear}` | PASS | `ImportService` checks every property via user-scoped `PropertyService` before any write |
| `POST /imports/schedule-e/extractions`, `POST .../{jobId}/start`, `GET .../{jobId}` | PASS | Jobs stored under `USER#<sub>`, loaded by sub; upload key contains `<sub>`; Textract is not called for a foreign job |
| `GET /dashboard`, `/dashboard/properties`, `/dashboard/assets`, `/dashboard/trends` | PASS | Iterate only `PropertyService.list()` for the JWT user |
| `GET /carryforward`, `PUT /carryforward/opening-balance`, `PUT/DELETE /carryforward/years/{taxYear}` | PASS | Items under `USER#<sub>`; property data via user-scoped services |
| `GET /backup` | PASS | Driven by the user's property list |
| `POST /backup/clear` | PASS | Driven by the user's property list |
| `POST /backup/restore` | FIXED | Foreign property ids refused before the clear (A3) |
| `POST/GET /businesses`, `GET/PUT/DELETE /businesses/{businessId}` | PASS | `_owned_meta` compares `META.userId` |
| `POST/GET /businesses/{businessId}/documents`, `DELETE .../documents/{documentId}` | PASS | `_owned_meta` before key creation, listing or delete |

### GSI queries

* GSI1 (`USER#<sub>` / `PROP#`): only the user's own partition is queried (`PropertyService.list`); the import index (`GSI1PK=PROPERTY#<id>`) is written but never queried by id from a request.
* GSI2 (`PROPERTY#<id>#YEAR#<y>`): used by `list_for_property(taxYear)` and Schedule E import undo. Both are now reached only after the property is proven owned (A1, and `ImportService` ownership checks).

### Tests added or changed

* New: `backend/tests/router/test_cross_user_authorization.py` (60 tests, all pass). Run against the pre-fix code, 27 of them fail, covering A1, A2 and A3.
* Changed: `tests/router/test_schedule_e_import_routes.py::test_pdf_import_drafts_route_still_resolves` asserted that an unknown session's drafts returned 200 with an empty list. It now expects the 404 that foreign sessions also get.
* Full suite: 1442 passed, 1 failed. The failure, `tests/services/test_schedule_e_extraction_money_property.py::test_amounts_normalize_to_two_decimal_money_without_drift`, is a parser property test that imports neither the router nor backup and is unrelated to this task; it is left for the owner of that area.

## Backend input validation audit

Scope: task 4.2. Every route in `backend/src/logstead/router/handler.py` and the services it calls, checked for malformed JSON, wrong types, oversized strings and arrays, negative/NaN/huge numbers, bad dates, unknown enum values, invalid path ids, and for error bodies that leak internals.

### Method

A throwaway probe sent about 290 hostile requests (wrong types for every body field, `NaN`/`Infinity`/`1e400`/`1e30`, 20 KB strings, 2,000-item lists, 50-deep JSON, 3,000-character and `#`-containing path ids, bad years, bad base64) through the router against moto and listed every 5xx and every unexpected 200. The probe was deleted. The regression tests are in `backend/tests/router/test_input_validation.py` (76 tests).

What was already sound: malformed JSON, non-object bodies and bad base64 give 400; unmatched routes give 404; the catch-all returns `{"error":"internal","message":"An unexpected error occurred."}` with no detail; money in services goes through `to_money`, which rejects floats, NaN and Infinity; bad dates and unknown enums (`type`, `property_type`, `entity_type`, Schedule E line) are rejected by the services with a `field`.

### Findings and fixes

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| V1 | High | `recovery_period_years` had no upper bound. The schedule engine builds `ceil(period) + 1` rows, so `1e30` hung the Lambda (CPU/memory denial of service) on `POST /assets`. A period over about 98 also exceeded the 100-item DynamoDB transaction limit and returned 500. | **Fixed.** `DepreciationService` rejects a period over 50 years (`MAX_RECOVERY_PERIOD_YEARS`) with a 400 on `recovery_period_years`. |
| V2 | Medium | Wrong JSON types caused 500s: non-string `name`, `address_text`, `property_type`, business fields, transaction `date`/`type`/`category_id`/`description`, asset and loan text fields, import `content_type`. | **Fixed.** `_opt_str` returns a 400 naming the field. |
| V3 | Medium | `NaN`, `Infinity`, `-Infinity`, `1e400` and floats such as `1e30` as a transaction or asset amount gave 500; booleans, lists and objects were stringified. | **Fixed.** `_decimal_or_none` rejects non-finite, boolean, list and object values, and magnitudes above 9,999,999,999,999.99. Asset `recovery_period_years` uses the same parser, so `abc`, `[]`, `true` now give 400 instead of 500. |
| V4 | Medium | Asset override years went through `int(year)`, so a non-numeric key (`abc`, `1e3`, `null`) gave 500. | **Fixed.** Parsed with `_int_param`, 400. |
| V5 | Medium | `bool(body["fully_allowed"])` made the string `"false"` mean true. A non-string note (`123`, `[]`, `{}`) was silently coerced. | **Fixed.** Both now require the correct JSON type (400 with `field`). |
| V6 | Medium | Error bodies leaked internals. `POST /backup/restore` appended `str(exc)` (boto text, table name) to its 409. PDF parse failures returned library exception text. RentCast transport failures returned the `URLError` text (host, errno). | **Fixed.** Fixed messages are returned; the cause is logged server side. |
| V7 | Low | The catch-all 500 handler did not log, so a 500 left no trace. | **Fixed.** `logger.exception` records the traceback; the response is unchanged. |
| V8 | Low | No size limits: a single string could exceed the 400 KB DynamoDB item limit (500), lists and objects were unbounded, deeply nested JSON could raise `RecursionError` (500). | **Fixed.** Every route except `POST /backup/restore` and `POST /imports` rejects strings over 10,000 characters, lists or objects over 1,000 entries and nesting deeper than 10 (400). Pathological nesting at parse time is a 400. |
| V9 | Low | Path ids were unchecked. A 3,000-character id exceeds the DynamoDB key limit (real DynamoDB would 500), and `#` is the key delimiter. | **Fixed.** Any path parameter named `*Id` must match `^[A-Za-z0-9_.:-]{1,128}$`, otherwise 404 `Not found.` (the same as an unknown id). `propertyIds` in `GET /reports/combined` is checked the same way and capped at 100 ids. |
| V10 | Low | `taxYear` accepted `1_000`, non-ASCII digits and any magnitude (`99999999999` was stored as a carryforward year). | **Fixed.** `_int_param` accepts ASCII digits only, at most 18, and `taxYear` must be 1900 to 2200. Loan interest-override years are exempt so the loan service keeps reporting `interest_overrides.<year>`. |

### Remaining

* **Usage days have no upper bound.** `fair_rental_days` and `personal_use_days` accept any non-negative integer below 10^18. A cap of 366 is the obvious rule, but `tests/services/test_usage_days_property.py` treats larger values as valid (acceptance criterion 2.8). I did not change it. Decision needed.
* **No per-field length limits beyond 10,000 characters.** A 9,000-character property name or note is accepted. Tighter caps (name 200, address 500, note 10,000) are business rules for the services; add them if wanted.
* **Money upper bound only at the router for transaction and asset amounts.** Loan money, carryforward amounts and Schedule E line amounts go through `to_money` and have no magnitude cap beyond Decimal's 28-digit quantize limit (which returns a validation error, not a 500).
* **Textract `status_message` is returned to the client** in the extraction `message` field. It is AWS-authored text (for example `PAGE_LIMIT_EXCEEDED`), not an internal path, but it is not ours to control. Consider mapping known codes to fixed text.
* **Non-string `description` coercion elsewhere**: `filename`/`content_type` on photo, receipt and document uploads are wrapped in `str()` (so `123` becomes `"123"`) and validated by the services. They do not 500, but the S3 key hardening is task 4.3.
* **Pre-existing, unrelated test failures** (fail identically without these changes): `test_schedule_e_extraction_money_property.py::test_amounts_normalize_to_two_decimal_money_without_drift` and `test_loan_payoff_roundtrip_property.py::test_payoff_set_and_clear_is_a_round_trip` (replays a stored Hypothesis example that now trips the 600-payment rule).

## Public /categories decision (task 2.2)

`GET /categories` now requires the Cognito JWT authorizer, which closes the last unauthenticated route. The frontend only calls it through the authenticated `apiClient` after sign-in, so no client change was needed. The route also has its own throttle (rate 5, burst 10) and returns `Cache-Control: private, max-age=3600`. `private` keeps shared caches from storing a response to an authenticated request. Tests: `test_categories_requires_claims` and `test_dispatch_categories_with_claims_sets_cache_control` in `tests/router/test_handler_integration.py`.


## Presigned upload audit (task 4.3, S8/A5)

Only one place mints presigned upload URLs: `S3FileAdapter.presigned_put_url`. Callers: photos (`PhotoService.request_upload`), receipts (`TransactionService.attach_receipt`), business documents (`BusinessService.request_document_upload`), Schedule E extraction (`ExtractionService.start_extraction`). Exports and report files are written server-side with `put_object` and only returned as presigned GET URLs. There is no other import upload.

| Control | Before | Now |
|---|---|---|
| Content-type allowlist | Photos: images. Business docs: images+PDF. Extraction: PDF. Receipts: **any non-empty string**. | Receipts now limited to images+PDF (`RECEIPT_CONTENT_TYPES`), compared lowercase. Others unchanged. |
| Content type in signature | Yes (`ContentType` param). | Unchanged; verified by test. |
| Expiry | 3600s. | 600s for uploads (`UPLOAD_EXPIRY_SECONDS`). GET URLs stay 3600s. |
| Filename | Raw client value in key and metadata. | `sanitize_filename`: basename only, control/unsafe chars replaced, leading dots stripped, 100-char cap keeping the extension, fallback `file`. Applied to key and stored `original_filename`. Extraction keys never used the filename. |
| Key construction | Server-side (uuid + prefix). | Unchanged. |
| Size | None. | Server-side after upload (below). |
| Per-user prefix (A5) | None except extraction. | Not implemented (recommendation). |

**Size decision.** A presigned PUT cannot carry a size limit. Presigned POST with `content-length-range` would work but needs the API response to return form fields and both frontend upload helpers (`photos.ts`, `transactions.ts`, shared by extraction and business docs) rewritten to send multipart. Requiring a client-declared size also needs frontend and API changes and is not trusted anyway. I chose the smaller option that needs no frontend change: check actual size with `head_object` on the next server step and delete oversized objects. Limits: images 25 MB, receipts/business docs 25 MB, Schedule E PDFs 20 MB.
- Extraction: `begin_extraction` (the confirm step) purges an oversized object and marks the job failed before reading or calling Textract.
- Photos, receipts, business documents have no confirm step, so `list_photos`/`list_receipts`/`list_documents` purge an oversized object and its metadata row when the item is listed.
- Residual: an oversized object can exist in S3 until the next confirm/list, within the 600s URL window and beyond. The S3 bucket policy or a presigned POST migration would close this; both are follow-ups. Receipt uploads with an empty browser MIME type (`application/octet-stream` fallback in `ReceiptList.tsx`) are now rejected with a 400. Adding `accept="image/*,application/pdf"` to that input is a suggested frontend follow-up (not done; frontend untouched).

Tests: `tests/adapters/test_s3_files.py`, `tests/services/test_business_documents.py`, `tests/services/test_transaction.py`.

## Logging audit (task 4.4)
Scope: every `logging`/`print` call in `backend/src/logstead`, the API Gateway access log format, and `console.*` in `frontend/src`.

| Site | Before | Now |
|---|---|---|
| `router/handler.py` catch-all 500 | `_log.exception(...)` wrote a full traceback. Exception messages in a traceback can echo request values (amounts, addresses, validation input). | `_log.error` with method, `%r` path and `exc_summary(exc)`: exception types along the cause chain plus `file:line function` per frame, no messages or locals. No headers, event, or body are logged. |
| `services/backup.py` restore write failure | `logging.exception` (traceback with boto/item values). | `exc_summary` only. |
| `adapters/pdf_parse.py` parse failure | Logged the library message (can quote document text). | `exc_summary` only, for both the `_ParseFailure` and the generic extractor error. |
| `adapters/rentcast.py` transport error | Logs `type(exc).__name__` only. | No change. The API key is only placed in the `X-Api-Key` header and never logged. |

New helper: `util/logsafe.py::exc_summary`. Tests: `tests/util/test_logsafe.py` (helper, PDF extractor failure) and `tests/router/test_logging_audit.py` (500 handler log has no message, Authorization value, amount or address, and the response body is generic).
No other logging or `print` calls exist in the backend. Presigned URLs, Textract output, JWTs and event dicts are never passed to a logger.

Trade-off: 500 logs no longer show the exception message, so debugging relies on type and code location. Re-add messages case by case only for exceptions known to be value-free.

API Gateway access log (`infra/template.yaml`, read-only): logs requestId, source IP, method, `$context.path`, status, protocol, responseLength and integrationErrorMessage. No Authorization header, query string, body or claims. `$context.path` has resource ids but no query string, so presigned URLs are not recorded. Source IP is personal data under some regimes; acceptable for a security log with 90-day retention. `integrationErrorMessage` is an API Gateway integration message, not application output.

Frontend: only `console.warn` in `BrandLogo.tsx` (render error and component stack) and `Button.tsx` (dev-only a11y warnings), plus a test spy. None log tokens or payloads. No changes.

## IaC policy checks (task 3.3, S5/S6)
The CI `infra` job runs `cfn-lint` and then cfn-guard 3.2.1 (official release binary, pinned by version and SHA-256 in `.gitlab-ci.yml`) against `infra/template.yaml` with `infra/guard/rules.guard`.

| Rule | Enforces |
|---|---|
| `s3_block_public_access` | All four PublicAccessBlock flags true on every bucket. |
| `s3_encryption` | Default SSE (`AES256` or KMS) on every bucket. |
| `s3_cors_no_wildcard` | No `"*"` in AllowedOrigins (top level and two levels of `!If`) or AllowedHeaders (S6). |
| `iam_least_privilege` | No Action `"*"`; no Allow with Resource `"*"` unless every action is `textract:` (S5 exception); no `NotAction`/`NotResource` on Allow. Covers SAM `Policies` inline statements, the same inside `!If`, and native `AWS::IAM::Role`/`Policy`/`ManagedPolicy`. |
| `lambda_reserved_concurrency` | `ReservedConcurrentExecutions >= 1` on every function (S4/S5). |
| `cloudfront_default_behavior`, `cloudfront_extra_behaviors` | `ResponseHeadersPolicyId` set and `ViewerProtocolPolicy` `redirect-to-https` or `https-only` (S1). |
| `log_group_retention` | `RetentionInDays` set on every log group. |

**Raw template, not transformed.** Guard runs on the raw SAM template, so rules target `AWS::Serverless::Function` and its `Policies` list. The alternative, `sam validate`/`sam build` and then `sam package` or the SAM translator to get the transformed template, needs the SAM CLI in the job and, for the managed policy templates, AWS credentials or extra tooling. The raw template is simpler and has no network or account dependency. Limits: SAM policy templates (`DynamoDBCrudPolicy`) are AWS-defined and not inspected; the IAM role SAM generates is not seen. Guard 3.2.1 crashes on chained filters (`[a][b]`), so the rules use one filter per `let`.

**Verified locally (macOS arm64 binary, same version):** the current template passes (`cloudfront_extra_behaviors` skips; there are no extra cache behaviors). Each of 14 mutated copies fails on the intended rule with exit 19: bucket public access flag off, encryption removed, `"*"` origin at the top level and in the nested `!If`, `"*"` header, Action `"*"`, Resource `"*"` on the S3 list, on geo-places, and on the `!If` SSM statement, `s3:ListBucket` added to the Textract statement, reserved concurrency removed, `allow-all` viewer policy, response headers policy removed, log retention removed. A synthetic template confirmed the native IAM role/managed policy and extra cache behavior checks fail. The Linux CI download and checksum were not run in a container (Docker unavailable); the pinned SHA-256 was computed from the release asset.

**AWS Guard rules registry:** not added. Its compliance rule packs include generic checks this single-user app has not adopted (for example S3 server access logging, Lambda inside a VPC, Lambda DLQs, KMS customer-managed keys), so it would need many suppressions for little gain over the targeted rules above. It was not run against the template.


## Status summary (task 8)

Status: Fixed / Partly fixed / Accepted risk / Open. "Task" is the spec task that addressed it; see `git log` for the commit (batch 1 `79167bf`, batch 2 `d3fae86`, `9ac0d5d`, `6f34694`, batch 3 `e062ac3`, `e1d1b9e`, `9287853`, `8753ecb`, `b3a68ef`, `1d67d4c`, `d385ec1`).

| ID | Status | Task / commit | Remaining |
|---|---|---|---|
| S1 CSP and security headers | Fixed | 1.1 (`79167bf`), enforced by cfn-guard 3.3 (`9287853`) | Verify real headers after deploy (checklist below). |
| S2 Refresh token in storage | Fixed | 1.2 (`79167bf`) | None. Access and ID tokens remain in sessionStorage by design; CSP is the mitigation. |
| S3 No session renewal | Accepted risk | 1.2 decision | Users re-sign in on expiry. |
| S4 API abuse and cost | Partly fixed | 2.1 (`d3fae86`), 2.2 (`6f34694`), 2.3 (`e062ac3`), 2.4 | Alarms and budget need `AlertEmail` set and the SNS subscription confirmed. Throttles and WAF decision are not verified on a deployed stage. No per-user limits. |
| S5 IAM wildcards | Fixed | 3.1 (`9ac0d5d`), 3.3 (`9287853`) | `textract:*` on `"*"` is an accepted AWS limitation (documented, allowed by the guard rule). |
| S6 S3 CORS wildcard | Fixed | 3.2 (`9ac0d5d`), 3.3 | Non-custom-domain deploys need a second deploy to set `AllowedSpaOrigin`. |
| S7 Unsafe DOM APIs | Fixed | 5.1 (ESLint rules) | None. |
| S8 Presigned upload | Partly fixed | 4.3 (`e062ac3`) | Size enforced after upload only (see follow-ups). |
| S9 `.env.example` | Fixed | Reviewed, no real IDs | None. |
| S10 PKCE/state/nonce | Partly fixed | 7.3 (`1d67d4c`) e2e covers PKCE and state mismatch | No `nonce`. Server validates the ID token. Client never uses ID-token claims for authorization (not re-audited here). |
| R1 ESLint | Fixed | 5.1 (`9ac0d5d`) | None. |
| R2 Dependency policy | Fixed | 4.5, 5.2, 5.3 (`e1d1b9e`) | Renovate app install (manual). |
| R3 `useAsyncResource` | Fixed | 6.1 (`e1d1b9e`, `8753ecb`) | None. |
| R4 Large files | Fixed | 6.2, 6.3 (`8753ecb`) | None. |
| R5 ResponsiveTable duplicate DOM | Fixed | 6.4 (`b3a68ef`) | None. |
| R6 Source-scan tests | Fixed | 7.2 (`e1d1b9e`) | Some conformance tests (`pageConformance`) still read source; accepted. |
| R7 jsdom polyfills | Fixed | 5.4 | None. |
| R8 Contrast checks | Fixed | 7.1 (`8753ecb`), 30 Playwright tests pass | Manual Playwright job in CI untested on GitLab. |
| R9 Repo hygiene | Fixed | 5.5 | iCloud-synced `~/Documents` may recreate " 2" copies. |
| R10 Error boundary | Fixed | 6.5 (`e1d1b9e`) | None. |
| R11 Undo IDs | Fixed | 6.6 (`8753ecb`) | Restored records get fresh timestamps (documented). |
| R12 apiClient token leakage | Fixed | 1.3 (`79167bf`) | None. |
| A1 Cross-user property children | Fixed | 4.1 (`d3fae86`) | None. |
| A2 Import sessions | Fixed | 4.1 | None. |
| A3 Backup restore takeover | Fixed | 4.1 | UUID-in-use probe by someone already holding the UUID. |
| A4 Import confirm TypeError | Fixed | 4.1 | None. |
| A5 Per-user S3 prefix | Partly fixed | 4.3 (filename sanitised) | Per-user prefix not implemented. |
| V1 to V10 Input validation | Fixed | 4.2 (`6f34694`) | Length and magnitude caps, usage days (see follow-ups). |
| Presigned upload audit | Partly fixed | 4.3 (`e062ac3`) | Size check after upload only. |
| Logging audit | Fixed | 4.4 (`e062ac3`) | None. |
| IaC policy checks | Fixed | 3.3 (`9287853`) | First GitLab run (x86_64 cfn-guard) not yet seen. |

## Remaining follow-ups

1. **Schedule E parser money bug (latent).** `tests/services/test_schedule_e_extraction_money_property.py::test_amounts_normalize_to_two_decimal_money_without_drift` fails only by replaying a stored example in the local `.hypothesis` DB. Needs a parser fix.
2. **Loan payoff test.** `tests/services/test_loan_payoff_roundtrip_property.py::test_payoff_set_and_clear_is_a_round_trip` replays a stored example that exceeds the 600-payment rule. Constrain the generator or handle the rule. Fails only via the local `.hypothesis` DB.
3. **Usage-days upper bound: accepted risk.** The user declined a 366 cap, so `fair_rental_days` and `personal_use_days` stay unbounded (below 10^18).
4. **A5:** add a per-user prefix to new S3 keys (needs a migration plan and IAM review).
5. **Length and magnitude caps:** per-field length caps (name, address, note) and magnitude caps on loan, carryforward and Schedule E amounts.
6. **Textract `status_message`** is returned to the client; map known codes to fixed text.
7. **Oversized objects** can remain in S3 until the next list or confirm. Close with a bucket policy or presigned POST `content-length-range`. Optionally add `accept` to the receipt file input.
8. **Renovate:** install the Mend app or set up a runner (manual, see `docs/dependency-policy.md`).
9. **First CI run on GitLab runners:** includes the x86_64 cfn-guard download and checksum, and the manual Playwright job.
10. **Deploy-time checks:** see the post-deploy checklist below. Nothing here was verified on a deployed stage.

## Checkpoint (task 8)

Run on branch `security/backlog-batch-3`, macOS arm64, no code changes.

| Check | Result |
|---|---|
| `npm audit --omit=dev` | 0 vulnerabilities |
| `npx tsc -b` | clean |
| `npx eslint .` | clean |
| `npx vitest run` | 197 files, 1835 tests passed |
| `npm run build` | succeeded |
| `npm run e2e` | 30 passed (axe in both themes, mobile, sign-in/PKCE, create/delete/Undo smoke) |
| Backend `pytest -q -n 8` | 1537 passed, 2 failed (15 min). Both failures are the known `.hypothesis`-replay tests, follow-ups 1 and 2. |
| `pip-audit -r backend/requirements.txt` | no known vulnerabilities |
| `cfn-lint infra/template.yaml` | clean |
| `cfn-guard` 3.2.1 (macOS arm64, downloaded to `/tmp/guard`) | passes `infra/guard/rules.guard` |

### Static response-header check

`SpaResponseHeadersPolicy` in `infra/template.yaml` (lines ~295 to 332) contains:

* CSP with `default-src 'self'`, `script-src 'self'` (no `unsafe-inline` or `unsafe-eval` for scripts), `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`. `style-src` allows `'unsafe-inline'` (styles only, accepted). `connect-src` and `img-src` list only the API, Cognito domain and files bucket.
* HSTS max-age 31536000, includeSubdomains, no preload.
* `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`.
* `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()`.

`frontend/dist/index.html` from `npm run build` has two `<script>` tags, both with `src` (`/theme-init.js`, and the module bundle). There are no inline scripts. `theme-init.js` is a static file in `frontend/public`.

Not verified: actual headers served by CloudFront, and that the CSP does not block anything at runtime (task 1.1 note: test in staging).

### Post-deploy checklist

1. `curl -sI https://<site>/` and confirm `content-security-policy`, `strict-transport-security`, `x-content-type-options`, `referrer-policy`, `permissions-policy`, `x-frame-options`. Also `curl -sI https://<site>/theme-init.js` returns 200 with the same headers.
2. Open the site with the browser console open; confirm no CSP violations.
3. `aws apigatewayv2 get-stage --api-id <id> --stage-name <stage>` and confirm default and per-route throttles (autocomplete, enrich, extraction, categories).
4. Confirm the SNS alert subscription email (set `AlertEmail`) and that the budget exists.
5. For non-custom-domain deploys, set `AllowedSpaOrigin` from the `CloudFrontDomain` output and redeploy; check the bucket CORS shows only that origin.
6. Smoke test: sign in (PKCE redirect and callback), create a property, add a transaction, upload a photo and a receipt, run address autocomplete, run a Schedule E extraction, delete with Undo.

## Update: hosted CI removed

The GitLab pipeline from tasks 5.2 and 3.3 was removed to stay within the free
tier's compute minutes (the backend suite took about 11 minutes per push on the
2-vCPU shared runner). The same checks, including cfn-lint, cfn-guard, the
dependency audits and Playwright, are now run locally as documented in
`docs/local-checks.md`. References above to "CI" describe the removed pipeline;
the pipeline is recoverable from git history.
