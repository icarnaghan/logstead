# Implementation Plan: Logstead

## Overview

This plan converts the Logstead design into incremental, test-driven coding tasks for a serverless AWS application: a React + Vite + Tailwind + Radix SPA (hosted on S3/CloudFront) backed by a single monolithic Python 3.12 Lambda (router → application services → DynamoDB repository + S3 file adapter + external adapters), fronted by API Gateway (HTTP API) with a native Cognito JWT authorizer, all defined via AWS SAM.

The backend is built bottom-up: infrastructure and shared primitives (money/decimal utilities, DynamoDB single-table repository) first, then the Schedule E category catalog seed, then each application service with its property-based and unit tests placed close to the implementation so correctness is validated early. External integrations (RentCast, address autocomplete, PDF parsing) live behind stubbed adapters so tests never make live calls. The router wires services to HTTP routes, then the React SPA is built feature by feature and wired to the API. Each of the 28 design correctness properties is implemented as a single Hypothesis property-based test (minimum 100 iterations) tagged with the exact comment format `# Feature: logstead, Property {number}: {property_text}`.

Money is `decimal.Decimal` in code and two-decimal strings in DynamoDB throughout. Charts/visualizations are explicitly out of scope for this release; the dashboard renders numeric summaries only.

## Tasks

- [x] 1. Scaffold backend project structure and shared primitives
  - Create the Python 3.12 Lambda project layout: `backend/src/logstead/{router,services,repository,adapters,models,util}` packages with `__init__.py` files
  - Configure `pyproject.toml`/`requirements.txt` with `boto3`, `pdfplumber`/`pypdf`, and dev deps `pytest`, `hypothesis`, `moto`
  - Set up the `pytest` configuration (test discovery, Hypothesis default profile with `max_examples >= 100`)
  - _Requirements: 12.4, 13.3_

  - [x] 1.1 Implement money/decimal utilities
    - Write `util/money.py`: `to_money(str|Decimal) -> Decimal` quantized to two decimals, `money_to_str(Decimal) -> str` producing a fixed two-decimal string for DynamoDB, and a `Money` type alias
    - Enforce two-decimal quantization and reject non-finite/negative-where-invalid inputs at the boundary
    - _Requirements: 13.3_

  - [x] 1.2 Write property test for monetary precision round-trip
    - **Property 28: Monetary amounts preserve two-decimal precision**
    - **Validates: Requirements 13.3**
    - Use a Hypothesis strategy over two-decimal Decimals including `0.00`, `0.01`, and large amounts; assert `to_money(money_to_str(x)) == x` with no drift

- [x] 2. Define core data models and the single-table key scheme
  - [x] 2.1 Implement domain dataclasses in `models/`
    - Define `UserContext`, `PropertyInput`/`Property`, `PropertyDetails` (all fields optional, nested `features` map), `PropertyUsageYear`, `PropertyPhoto`, `ScheduleECategory`, `TransactionInput`/`Transaction`, `Document`, `AssetInput`/`DepreciableAsset`, `DepreciationScheduleRow`, `ImportSession`, `DraftTransaction`, and `Result[T]` success/typed-error wrapper
    - Money fields typed as `Decimal`
    - _Requirements: 2.9, 3.8, 5.1, 6.1, 8.1, 12.1, 12.4_

  - [x] 2.2 Implement the DynamoDB key scheme helpers
    - Write `repository/keys.py` encoding the PK/SK and GSI1/GSI2 conventions from the design: `USER#`, `PROPERTY#`, `PROP#`, `DETAILS`, `USAGE#`, `PHOTO#`, `CATEGORY#`, `TXN#<invDate>#<id>`, `ASSET#`, `ASSET#..#SCHED#`, `IMPORT#`, `DRAFT#`
    - Implement inverted-date encoding `invDate = 99999999 - YYYYMMDD` for date-descending ordering and the `GSI2PK=PROPERTY#<id>#YEAR#<year>` tax-year partition
    - _Requirements: 5.4, 5.5, 12.6, 13.1_

  - [x] 2.3 Write unit tests for key scheme and inverted-date encoding
    - Verify key construction/round-trip and that inverted-date ordering yields newest-first
    - _Requirements: 5.4, 5.5_

- [x] 3. Implement the DynamoDB repository layer
  - [x] 3.1 Implement the repository with single-table access
    - Write `repository/dynamo_repo.py`: `put_item`, `get_item`, `query` (with `begins_with`, GSI queries), `delete_item`, and a `transact_write(items)` wrapper over `TransactWriteItems`
    - Serialize money attributes as strings on write and parse back to `Decimal` on read; omit absent optional attributes on write (sparse items)
    - _Requirements: 12.2, 12.3, 13.1, 13.3_

  - [x] 3.2 Write property test for PropertyDetails sparse round-trip
    - **Property 4: Property_Details round-trip preserves present fields**
    - **Validates: Requirements 2.9, 3.3, 3.8, 12.1, 12.2, 12.3**
    - Strategy generates PropertyDetails with random subsets of fields present; assert present fields returned unchanged and absent fields reported unset (run against DynamoDB Local/moto)

  - [x] 3.3 Write integration tests for persistence round-trips
    - Against moto/DynamoDB Local: verify single-table writes/reads, date-descending transaction listing, tax-year GSI2 queries, and money string round-trips survive across simulated sign-out/sign-in
    - _Requirements: 13.1, 13.2, 5.4, 5.5_

- [x] 4. Seed and expose the Schedule E category catalog
  - [x] 4.1 Implement the category catalog and seeding
    - Define the fixed income categories (Rents received Line 3, Royalties received Line 4) and expense categories (Lines 5–17 and Other Line 19) as `ScheduleECategory` reference items; mark Other as `requiresDescription`; intentionally exclude Line 18
    - Write a `seed_categories()` routine that writes `CATEGORY#` items and a `list_categories()` read
    - _Requirements: 7.1, 7.2, 7.5_

  - [x] 4.2 Write property test excluding depreciation line from assignable categories
    - **Property 14: No assignable category maps to the depreciation line**
    - **Validates: Requirements 7.5**
    - Assert every user-assignable category's Schedule E line is not Line 18

- [x] 5. Implement the Auth component (current_user)
  - [x] 5.1 Implement `current_user(event)` claim extraction
    - Write `services/auth.py` reading the verified Cognito `sub`/claims from the API Gateway request context into a `UserContext`; no token parsing or password logic anywhere
    - Provide a helper services use to scope data to the authenticated user id
    - _Requirements: 1.5, 1.6_

  - [x] 5.2 Write property test for identity-gated access
    - **Property 1: API access requires a valid identity token**
    - **Validates: Requirements 1.1, 1.6**
    - Simulate request contexts with valid vs missing/malformed claims; assert the service layer is reached with a resolved identity only for valid, and rejected without side effects otherwise

  - [x] 5.3 Write unit tests for claim extraction edge cases
    - Cover `sub` resolution, missing username claim fallback, and remaining-claims passthrough
    - _Requirements: 1.6_

- [x] 6. Implement the Property Service
  - [x] 6.1 Implement property CRUD and usage days
    - Write `services/property.py`: `create_property` (reject blank name/address with field-identifying message), `list_properties`, `update_property`, `delete_property` (guarded by associated transactions/assets), `set_usage_days`, `get_property_with_details`
    - Use `transact_write` for multi-item writes (property `USER#` item + mirrored `PROPERTY#..META`)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 13.1_

  - [x] 6.2 Write property test for property creation validation
    - **Property 2: Property creation rejects blank name or address**
    - **Validates: Requirements 2.2**

  - [x] 6.3 Write property test for deletion guarded by associations
    - **Property 3: Property deletion is guarded by associations**
    - **Validates: Requirements 2.6, 2.7**
    - Generate arbitrary sets of associated transactions/assets; deletion succeeds iff both empty

  - [x] 6.4 Write property test for stored usage days in report header
    - **Property 25: Report header reflects stored usage days**
    - **Validates: Requirements 2.8, 10.2**

  - [x] 6.5 Write unit tests for property CRUD happy paths
    - Cover create/list/update happy paths and unlimited-properties support
    - _Requirements: 2.1, 2.3, 2.4, 2.5_

- [x] 7. Implement external enrichment adapters
  - [x] 7.1 Implement the RentCast adapter
    - Write `adapters/rentcast.py`: `get_property_record(address)` calling `GET /properties?address=` with a server-held API key and bounded timeout; map the response into `PropertyDetails` copying only provided fields; 404/empty → `None`, network/5xx/timeout → error
    - _Requirements: 3.2, 3.3, 3.8, 12.1, 12.2_

  - [x] 7.2 Implement the address autocomplete adapter
    - Write `adapters/autocomplete.py`: `suggestions(query)` returning `AddressSuggestion` list from the geocoding provider; failure degrades to empty suggestions
    - _Requirements: 3.1_

  - [x] 7.3 Implement the AddressEnrichmentService
    - Write `suggest_addresses` and `enrich(selected_address)` returning `EnrichmentResult{found|not_found|unavailable}` with prefilled editable details; property creation must never depend on enrichment
    - _Requirements: 3.2, 3.4, 3.5, 3.6, 3.7_

  - [x] 7.4 Write property test for creation-independent-of-RentCast
    - **Property 5: Property creation succeeds regardless of RentCast availability**
    - **Validates: Requirements 3.7**
    - Strategy over enrichment outcomes (found/not_found/unavailable) using a mocked adapter; assert property always created

  - [x] 7.5 Write unit/integration tests for adapters
    - RentCast adapter against a recorded/stubbed HTTP response (mapping, not_found, unavailable branches); autocomplete adapter stubbed
    - _Requirements: 3.5, 3.6_

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement the Photo Service and S3 file adapter
  - [x] 9.1 Implement the S3 file adapter
    - Write `adapters/s3_files.py`: pre-signed PUT/GET URL issuance and object delete over one bucket with prefixed keys
    - _Requirements: 4.1, 5.8_

  - [x] 9.2 Implement the Photo Service
    - Write `services/photo.py`: `request_upload` (validate content type against image allow-list before issuing a pre-signed URL), `confirm_upload` (write metadata after confirmed upload), `list`, `delete` (S3 object + metadata item)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 9.3 Write property test for photo type allow-list
    - **Property 6: Photo upload accepts exactly the allowed image types**
    - **Validates: Requirements 4.2**

  - [x] 9.4 Write integration tests for S3 operations
    - Exercise pre-signed URL issuance and photo metadata lifecycle against moto/local S3 stub
    - _Requirements: 4.1, 4.3, 4.4_

- [x] 10. Implement the Transaction Service
  - [x] 10.1 Implement transaction CRUD, ordering, and receipts
    - Write `services/transaction.py`: `create` (reject amount ≤ 0 and missing property/date/amount/category; record Schedule E line from category; require description for Other/Line 19), `list_for_property` (date-descending via inverted-date SK, optional tax-year filter via GSI2), `update`, `delete`, `attach_receipt` (pre-signed URL + `Document` metadata)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 7.3, 7.4_

  - [x] 10.2 Write property test for transaction validation
    - **Property 7: Transaction validation rejects invalid amounts and missing fields**
    - **Validates: Requirements 5.2, 5.3**

  - [x] 10.3 Write property test for date-descending ordering
    - **Property 8: Transaction listing is ordered by date descending**
    - **Validates: Requirements 5.4**

  - [x] 10.4 Write property test for tax-year filtering
    - **Property 9: Tax-year filter returns exactly in-year transactions**
    - **Validates: Requirements 5.5**

  - [x] 10.5 Write property test for category-to-line mapping
    - **Property 13: Category assignment records the correct Schedule E line**
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [x] 10.6 Write property test for Other-requires-description
    - **Property 15: Other expenses require a description**
    - **Validates: Requirements 7.4**

  - [x] 10.7 Write unit tests for transaction CRUD happy paths
    - Cover create/update/delete happy paths and receipt attachment metadata
    - _Requirements: 5.1, 5.6, 5.7, 5.8_

- [x] 11. Implement the Depreciation Service
  - [x] 11.1 Implement asset CRUD with 27.5-year default
    - Write `services/depreciation.py`: `create_asset` (reject cost basis ≤ 0 and missing fields; default recovery period 27.5), `update_asset` (recompute schedule), `delete_asset` (cascade schedule rows via transact_write), `list_assets`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 11.2 Implement the straight-line + mid-month schedule engine
    - Implement `compute_schedule`: annual = `cost_basis / recovery_period`; first year mid-month fraction `(12.5 - placed_in_service_month)/12`; final partial year takes the remainder; quantize each row to two decimals with the rounding residual assigned to the final year so the sum equals cost basis exactly; produce `remaining_basis` per row
    - Implement `schedule_for` and `property_depreciation_for_year`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 11.3 Write property test for asset validation
    - **Property 16: Asset validation rejects invalid basis and missing fields**
    - **Validates: Requirements 8.2, 8.3**

  - [x] 11.4 Write property test for straight-line mid-month schedule
    - **Property 17: Depreciation schedule is straight-line with mid-month convention**
    - **Validates: Requirements 9.1, 9.2, 8.5**
    - Strategy over cost basis, recovery periods (incl. 27.5), and placed-in-service dates across all twelve months

  - [x] 11.5 Write property test for depreciation summing to basis
    - **Property 18: Depreciation sums to the cost basis**
    - **Validates: Requirements 9.3**

  - [x] 11.6 Write property test for remaining-basis consistency
    - **Property 19: Remaining basis is consistent and terminates at zero**
    - **Validates: Requirements 9.4**

  - [x] 11.7 Write property test for property-year depreciation sum
    - **Property 20: Property-year depreciation equals the sum across assets**
    - **Validates: Requirements 9.5**

  - [x] 11.8 Write unit tests for asset CRUD and 27.5-year default
    - Cover create/delete/list happy paths and the default recovery-period selection
    - _Requirements: 8.1, 8.4, 8.6, 8.7_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Implement the Expense Import Service (draft lifecycle)
  - [x] 13.1 Implement the PDF parse adapter
    - Write `adapters/pdf_parse.py` using `pdfplumber`/`pypdf`: extract date/amount/description per line item with a bounded parse time; treat oversized/slow/zero-line-item documents as parse failure
    - _Requirements: 6.3, 6.12_

  - [x] 13.2 Implement the import session and draft lifecycle
    - Write `services/expense_import.py`: `start_import` (reject non-PDF with "PDF required"; associate property + tax year; create `ImportSession` + `DraftTransaction` staging items; attempt category mapping via keyword heuristics; no `Transaction` created), `get_drafts`, `update_draft` (re-flag missing fields), `remove_draft`, `confirm` (validate each draft against Requirement 5 rules; create Transactions for valid, reject others by field)
    - _Requirements: 6.1, 6.2, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_

  - [x] 13.3 Write property test for no-transaction-before-confirmation
    - **Property 10: No transaction exists before draft confirmation**
    - **Validates: Requirements 6.6**

  - [x] 13.4 Write property test for exact missing-fields flag
    - **Property 11: Draft missing-fields flag is exact**
    - **Validates: Requirements 6.9**

  - [x] 13.5 Write property test for confirmation partitioning
    - **Property 12: Confirmation partitions drafts into created and rejected**
    - **Validates: Requirements 6.10, 6.11**

  - [x] 13.6 Write unit tests for PDF parsing and failure branches
    - Parse representative expense-summary fixtures (line-item extraction, category heuristics) and the no-line-items/parse-failure branch
    - _Requirements: 6.3, 6.4, 6.12_

- [x] 14. Implement the Schedule E Report Service
  - [x] 14.1 Implement per-property and combined report generation
    - Write `services/report.py`: `report_for` (aggregate tax-year transactions into Schedule E line totals, header with address/type/fair-rental/personal-use days, Line 18 from depreciation, totals + net, Line 19 itemization), `combined_report` (per-property columns + totals column), all derived from persisted data only
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 12.5_

  - [x] 14.2 Implement report export
    - Write `export(report, "pdf"|"csv")` generating the file in the Lambda, writing to S3, and returning a pre-signed download URL
    - _Requirements: 10.7_

  - [x] 14.3 Write property test for report aggregation and balance
    - **Property 21: Report aggregation is correct and balances**
    - **Validates: Requirements 10.1, 10.4**

  - [x] 14.4 Write property test for report depreciation line
    - **Property 22: Report depreciation line equals computed depreciation**
    - **Validates: Requirements 10.3**

  - [x] 14.5 Write property test for Other-expense itemization
    - **Property 23: Other expenses are itemized and reconcile**
    - **Validates: Requirements 10.5**

  - [x] 14.6 Write property test for combined-report totals
    - **Property 24: Combined report totals equal per-property sums**
    - **Validates: Requirements 10.6**

  - [x] 14.7 Write property test for report reproducibility
    - **Property 27: Reports are reproducible from persisted data alone**
    - **Validates: Requirements 12.5**

  - [x] 14.8 Write integration test for report export
    - Verify PDF/CSV export writes to S3 and returns a downloadable pre-signed URL (moto)
    - _Requirements: 10.7_

- [x] 15. Implement the Dashboard Service
  - [x] 15.1 Implement portfolio and per-property summaries
    - Write `services/dashboard.py`: `portfolio_summary` and `per_property_summary` (income/expenses/net for a tax year, current-year default with year selector), `has_properties` (empty-state prompt). Numeric summaries only — no charts
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 15.2 Write property test for dashboard net equals per-property sum
    - **Property 26: Dashboard net equals the sum of per-property nets**
    - **Validates: Requirements 11.1, 11.2**

  - [x] 15.3 Write unit test for empty-state prompt
    - Verify `has_properties` false renders the add-first-property prompt path
    - _Requirements: 11.4_

- [x] 16. Wire the router and Lambda handler
  - [x] 16.1 Implement the handler/router
    - Write `router/handler.py`: parse the API Gateway proxy event (method/path/body), read the authenticated user via `current_user`, dispatch to the matching service method, serialize `Result` into HTTP responses (money → string, validation errors → 400 with field, not-found → 404), with no business rules in the router
    - Map routes for auth/session, addresses, properties/enrich, properties, photos, transactions, receipts, assets, schedules, imports/drafts, reports/export, and dashboard
    - _Requirements: 1.6, 2.2, 5.2, 5.3, 8.2, 8.3, 14.3_

  - [x] 16.2 Write integration tests for router dispatch and error mapping
    - Verify representative routes dispatch to services and map validation/not-found/success to correct status codes
    - _Requirements: 1.6, 14.3_

- [x] 17. Author the AWS SAM infrastructure template
  - Write `template.yaml` defining: the DynamoDB `Logstead` table with GSI1/GSI2; the S3 file bucket (CORS + lifecycle) and the static SPA bucket + CloudFront distribution (SPA routing to `index.html`); the Cognito User Pool + Hosted UI app client (Authorization Code + PKCE, Cognito domain, SPA callback/logout URLs); the API Gateway HTTP API with the native Cognito JWT authorizer (issuer/audience) — no custom Lambda authorizer; the Python 3.12 API Lambda with env config (table name, bucket, RentCast/autocomplete keys)
  - _Requirements: 1.1, 1.4, 1.5, 1.6, 13.1, 13.2_

  - [x] 17.1 Write integration test for JWT authorizer route guarding
    - Against the User Pool or a stubbed JWKS endpoint: valid tokens reach the Lambda; missing/malformed/expired tokens are rejected with 401
    - _Requirements: 1.1, 1.3, 1.6_

- [x] 18. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 19. Scaffold the React SPA and navigation shell
  - [x] 19.1 Initialize the React + Vite + Tailwind + Radix project
    - Set up `frontend/` with Vite React app, Tailwind CSS, Radix UI primitives, React Router, and a typed API client that attaches the Cognito Bearer token to requests
    - _Requirements: 14.1_

  - [x] 19.2 Implement the navigation shell and responsive layout
    - Build the persistent nav linking Dashboard, Properties, Transactions, Depreciable Assets, and Schedule E Reports; multi-column at ≥768px and single-column below; render validation messages adjacent to fields; build on accessible Radix primitives for keyboard/contrast conformance
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 19.3 Write component/accessibility tests for the shell
    - Snapshot the 768px breakpoint and nav structure; run automated axe checks for contrast/keyboard nav (note manual AT testing still required for full WCAG 2.1 AA)
    - _Requirements: 14.1, 14.2, 14.4_

- [x] 20. Implement SPA authentication and Hosted UI flow
  - [x] 20.1 Implement Cognito Hosted UI redirect and token handling
    - Redirect unauthenticated users to the Hosted UI; handle the callback (exchange authorization code with PKCE for tokens); store tokens and land on the dashboard; on 401 route back to Hosted UI; implement sign-out clearing tokens and calling the Cognito logout endpoint
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 20.2 Write component tests for auth routing
    - Verify unauthenticated redirect, successful callback → dashboard, and sign-out flow
    - _Requirements: 1.1, 1.2, 1.4_

- [x] 21. Implement SPA Properties feature with add/enrich flow
  - [x] 21.1 Build the properties list and add-property enrichment flow
    - List properties; add-property form with address autocomplete suggestions, RentCast enrich-on-select prefilling editable Property_Details, not_found/unavailable messages with manual entry, create always allowed; edit and guarded-delete; usage-days entry per tax year
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7, 2.8, 3.1, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [x] 21.2 Build the property photos UI
    - Upload images via pre-signed URL with type validation messaging, list, and delete photos
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [x] 21.3 Write component tests for add/enrich and photo flows
    - Cover enrich prefill/edit, not_found/unavailable manual-entry paths, and photo type-rejection messaging
    - _Requirements: 3.3, 3.5, 3.6, 4.2_

- [x] 22. Implement SPA Transactions and Expense Import features
  - [x] 22.1 Build the transactions UI
    - Create/edit/delete transactions with category selection (Other requires description), date-descending list, tax-year filter, and receipt attachment
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 7.4_

  - [x] 22.2 Build the expense-import review UI
    - Upload PDF (non-PDF rejected), review drafts with missing-field flags, edit/remove drafts, confirm to create transactions with per-draft rejection messaging, and the no-line-items manual-entry message
    - _Requirements: 6.1, 6.2, 6.5, 6.7, 6.8, 6.9, 6.10, 6.11, 6.12_

  - [x] 22.3 Write component tests for transactions and import review
    - Cover Other-description enforcement, tax-year filter, draft missing-field flagging, and confirm/reject rendering
    - _Requirements: 5.5, 6.9, 6.11, 7.4_

- [x] 23. Implement SPA Depreciable Assets and Schedules features
  - [x] 23.1 Build the depreciable assets and schedule UI
    - Create/edit/delete assets with 27.5-year default; display the year-by-year depreciation amount and remaining basis schedule
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 9.4_

  - [x] 23.2 Write component tests for asset forms and schedule display
    - Cover validation messaging, 27.5-year default selection, and schedule row rendering
    - _Requirements: 8.2, 8.4, 9.4_

- [x] 24. Implement SPA Schedule E Reports and Dashboard features
  - [x] 24.1 Build the Schedule E report UI
    - Per-property report by line with header (address/type/days), Line 18 depreciation, totals/net, Line 19 itemization; combined report with per-property columns + totals; export download
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7_

  - [x] 24.2 Build the dashboard UI (numeric summaries only)
    - Portfolio and per-property income/expenses/net for the current tax year with a year selector; empty-state add-first-property prompt. No charts in this release
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 24.3 Write component tests for reports and dashboard
    - Cover Line 19 itemization, combined totals column, year selector update, and empty-state prompt
    - _Requirements: 10.5, 10.6, 11.3, 11.4_

- [x] 25. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP, though they validate the 28 correctness properties and integration boundaries.
- Each task references specific requirements and/or design correctness properties for traceability.
- Property-based tests use Hypothesis at a minimum of 100 iterations and are tagged `# Feature: logstead, Property {number}: {property_text}`.
- External calls (RentCast, autocomplete, PDF parsing, S3, DynamoDB) are exercised via stubs/moto/DynamoDB Local; no live calls in tests.
- Charts/visualizations are a future enhancement and are intentionally absent from these tasks.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "2.2"] },
    { "id": 1, "tasks": ["1.2", "2.3", "3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "4.1", "5.1", "7.1", "7.2", "9.1", "13.1", "17"] },
    { "id": 3, "tasks": ["4.2", "5.2", "5.3", "6.1", "7.3", "9.2", "11.1", "17.1", "19.1"] },
    { "id": 4, "tasks": ["6.2", "6.3", "6.4", "6.5", "7.4", "7.5", "9.3", "9.4", "10.1", "11.2", "13.2", "19.2", "20.1"] },
    { "id": 5, "tasks": ["10.2", "10.3", "10.4", "10.5", "10.6", "10.7", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "13.3", "13.4", "13.5", "13.6", "14.1", "19.3", "20.2"] },
    { "id": 6, "tasks": ["14.2", "14.3", "14.4", "14.5", "14.6", "14.7", "15.1", "16.1", "21.1", "21.2", "22.1", "22.2", "23.1"] },
    { "id": 7, "tasks": ["14.8", "15.2", "15.3", "16.2", "21.3", "22.3", "23.2", "24.1", "24.2"] },
    { "id": 8, "tasks": ["24.3"] }
  ]
}
```
