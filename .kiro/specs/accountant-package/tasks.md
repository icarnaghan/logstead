# Implementation Plan: Accountant Package

## Overview

This plan adds a Schedule E PDF report (per property and combined) and an Accountant package ZIP for a tax year. The design is a pure ReportLab renderer (`services/report_pdf.py`), pure path and CSV helpers, a package builder that assembles the ZIP from existing services, a `PackageJobService` over a transient DynamoDB job item, a separate worker Lambda that runs the builder, and new routes that return presigned S3 links. The PDF routes are synchronous. The package is asynchronous. Every figure comes from `ReportingService`; nothing restates a precedence rule.

Languages: Python 3.12 (backend) and TypeScript/React (frontend), as in the design. Backend tests use pytest, Hypothesis, and moto, with `pypdf` and `pdfplumber` to read PDFs. Frontend tests use vitest, React Testing Library, and Playwright with axe. Every property-based test runs at least 100 iterations and is tagged `# Feature: accountant-package, Property N: ...` (`//` in TypeScript).

Ordering: configuration, pure helpers, and adapter additions come first, then the PDF renderer and its routes, then the package builder, then jobs, the worker, and the package routes. Infrastructure follows the backend. The frontend starts from the API module and pure helpers, builds the components and page, adds the PDF buttons, and wires the nav entry and route once the page exists. Documentation closes the plan. This is a spec-only deliverable; implementation happens task by task later. Nothing here deploys or commits.

## Tasks

- [x] 1. Backend: dependency, configuration, and pure helpers
  - [x] 1.1 Add the ReportLab dependency and record the size and audit
    - Pin `reportlab==5.1.0` in `backend/requirements.txt` and list `reportlab` in `backend/pyproject.toml` (the SAM makefile build installs from `pyproject.toml`)
    - In a throwaway venv, run a dry-run install, confirm that Pillow and charset-normalizer are already pulled in by `pdfplumber`, measure the unzipped size of the install target before and after, and run `pip-audit`
    - Update `docs/dependency-policy.md` with the pin, the BSD license, the audit result, and a line stating both files must change together; note the measured size for `docs/deployment.md` (task 12.5)
    - _Requirements: 20.1, 20.2, 23.6_
  - [x] 1.2 Create `services/package_config.py` and `services/csv_safe.py`
    - `package_config.py`: `PACKAGE_MAX_BYTES` (400 MiB), `PACKAGE_MAX_RECEIPTS` (2000), `DOWNLOAD_LINK_SECONDS` (900), `JOB_TTL_SECONDS` (86400), `JOB_STALE_SECONDS` (900), `JOB_LIST_LIMIT` (10), `COPY_CHUNK_BYTES` (1 MiB)
    - `csv_safe.py`: `neutralize_cell(value)` prefixing an apostrophe when the text starts with `=`, `+`, `-`, `@`, a tab, or a carriage return
    - _Requirements: 9.6, 13.8, 14.1_
  - [x] 1.3 Create `services/package_paths.py`
    - `slugify`, `unique_slugs` (hyphen plus the first six characters of the id on collision), `receipt_entry_path` (uses `sanitize_filename`), `is_safe_entry_path`, `dedupe_entry_path`
    - _Requirements: 8.5, 8.6, 8.8, 10.2_
  - [x] 1.4 Extend `adapters/s3_files.py`
    - `presigned_get_url(..., download_filename=None)` adding a quoted attachment Content-Disposition; `open_stream(key)` returning the body stream and length or `None`; `upload_file(path, key, content_type)` using a managed multipart upload; `package_key(user_id, job_id, year)` and `pdf_key(user_id, random_id, filename)` built on `export_key`
    - Existing callers and signatures keep working
    - _Requirements: 6.3, 10.5, 13.3, 13.6, 14.1, 15.6_
  - [x] 1.5 Add the job key helpers and the receipt metadata read
    - In `repository/keys.py` add `PACKAGE_JOB_PREFIX`, `package_job_sk(job_id)`, and the entity line in the module docstring
    - In `services/transaction.py` add `receipt_documents(property_id, transaction)` returning `Document` rows from the `#DOC#` prefix with no S3 call, no presigned URL, no purge, and no write
    - _Requirements: 10.1, 10.7, 13.8_
  - [x] 1.6 Add public report serializers and neutralize text cells in `services/report.py`
    - Add `serialize_report(report, format)` and `serialize_combined(report, format)` wrapping the private CSV and JSON functions
    - Pass property name, address, property type, and other-item descriptions through `neutralize_cell` in `_report_to_csv` and `_combined_to_csv`; leave the signatures of `export_report` and `export_combined_report` unchanged (the combined key changes in task 1.10)
    - _Requirements: 8.4, 9.6_
  - [x] 1.7 Write the formula neutralization property test
    - **Property 10: Spreadsheet formula neutralization**
    - **Validates: Requirements 9.6**
    - New `backend/tests/services/test_csv_safe_property.py`
  - [x] 1.8 Write the entry path property test
    - **Property 9: Entry paths are safe and unique**
    - **Validates: Requirements 8.5, 8.6, 8.8, 10.2, 15.6**
    - New `backend/tests/services/test_package_paths_property.py` with adversarial names, duplicates, and the S3 key helpers
  - [x] 1.9 Write example tests for the adapter and serializer changes
    - Extend `backend/tests/adapters/test_s3_files.py`: `presigned_get_url` with and without `download_filename`, `open_stream` for a present and an absent key, `upload_file`, `package_key`, `pdf_key`
    - Extend `backend/tests/integration/test_report_export.py`: existing assertions unchanged; new cases for the apostrophe prefix; add `backend/tests/services/test_transaction_receipt_documents.py` for `receipt_documents` (no S3 call, receipts of another transaction excluded)
    - _Requirements: 1.1, 8.4, 9.6, 10.1, 14.1_
  - [x] 1.10 Fix the combined export key to include the user id
    - In `adapters/s3_files.py` add `combined_export_key(user_id, tax_year, filename)` returning `exports/combined/<user_id>/<tax_year>/<filename>` through `export_key`
    - In `services/property.py` add a read-only `user_id` property on `PropertyService`
    - In `services/report.py` make `export_combined_report` build its key with `combined_export_key(self._properties.user_id, tax_year, filename)`; the constructor and every existing `ReportingService(...)` call stay unchanged; `export_report` keeps its key scheme
    - Confirm the Package_Builder calls `serialize_combined` and not `export_combined_report`, so the package writes no object under `exports/combined/`
    - _Requirements: 24.1, 24.2, 24.3, 24.5_
  - [x] 1.11 Update the existing combined export tests for the scoped key
    - `backend/tests/integration/test_report_export.py`: in `test_combined_export_download_url_round_trips` and `test_combined_csv_export_download_url_round_trips`, assert `export.key.startswith(f"exports/combined/{USER}/")` (the test module's user id constant) instead of `exports/combined/`, keeping the year, object-presence, and byte assertions
    - `backend/tests/services/test_report.py`: in `test_export_combined_report_stores_under_exports_prefix`, assert the same user-scoped prefix, using the user id of the fixture's `PropertyService`
    - Add a two-user example test: two `ReportingService` instances for two user ids over the same bucket export the same year and format; assert the two keys differ, both objects exist, and each holds its own bytes
    - _Requirements: 24.1, 24.2, 24.6, 22.13_
  - [x] 1.12 Write the combined export key property test
    - **Property 16: Combined export keys are user-scoped**
    - **Validates: Requirements 24.1, 24.2, 24.4**
    - New `backend/tests/services/test_report_combined_export_key_property.py`: generated pairs of distinct user ids, years, and formats over moto; assert the stored keys differ, start with `exports/combined/<user_id>/<tax_year>/`, and that no key of the form `exports/combined/<tax_year>/...` exists

- [x] 2. Backend: PDF renderer
  - [x] 2.1 Create `services/report_pdf.py` with models and pure helpers
    - `RepairsEntry`, `RepairsDetail`, `format_money` (dollar sign, separators, two decimals, parentheses for negatives), `pdf_text` (Windows-1252 replacement with `?`, control characters removed, XML escaped), `chunk_columns`, the fixed disclaimer and note strings, and a `NumberedCanvas` for "Page N of M"
    - No I/O, no clock, no money arithmetic
    - _Requirements: 1.8, 2.1, 5.1, 5.3, 16.2, 21.1, 21.2_
  - [x] 2.2 Implement `render_property_pdf`
    - Title, header table, line table (lines 3 to 19 with totals, dagger footnote for `includes_imported`), Line 12 source note, Line 19 other items table, Repairs appendix with the review sentence, footer on every page; ReportLab `invariant=1`; user text only through `Paragraph(pdf_text(...))`
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 5.1, 5.2, 5.4, 5.5, 5.6, 21.2_
  - [x] 2.3 Implement `render_combined_pdf`
    - Columns A, B, and C per chunk of three properties, portfolio totals and portfolio Line 12 note, per-property Line 19 tables and Repairs appendices
    - _Requirements: 4.2, 4.3, 4.4, 4.6, 5.4, 21.1, 21.2_
  - [x] 2.4 Write the money format property test
    - **Property 2: Money format round trip**
    - **Validates: Requirements 2.3, 16.2, 16.4**
    - New `backend/tests/services/test_report_pdf_money_property.py`
  - [x] 2.5 Write the PDF text content property test
    - **Property 1: The PDF text carries every report figure**
    - **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.4, 21.1, 21.2**
    - New `backend/tests/services/test_report_pdf_text_property.py` extracting text with `pypdf`; include a report with enough other items to span several pages
  - [x] 2.6 Write the PDF text safety property test
    - **Property 3: PDF text safety**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    - New `backend/tests/services/test_report_pdf_safety_property.py` with markup, `<img src="http://...">`, `<font>`, control characters, non-Windows-1252 text, and very long strings; patch `socket.socket` to fail on use
  - [x] 2.7 Write the PDF determinism property test
    - **Property 4: PDF determinism**
    - **Validates: Requirements 1.9, 5.6**
    - New `backend/tests/services/test_report_pdf_determinism_property.py`
  - [x] 2.8 Write the Repairs appendix property test
    - **Property 5: Repairs appendix**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
    - New `backend/tests/services/test_report_pdf_repairs_property.py`
  - [x] 2.9 Write the combined layout property test
    - **Property 6: Combined layout and totals**
    - **Validates: Requirements 4.2, 4.3, 4.6**
    - New `backend/tests/services/test_report_pdf_combined_property.py` for 1 to 10 properties
  - [x] 2.10 Write renderer example tests
    - New `backend/tests/services/test_report_pdf.py`: an all-zero report is a valid PDF; Line 12 wording for each source and for superseded interest; the dagger footnote; the Repairs appendix with and without an entered total; the disclaimer on every page; a source scan finding no money arithmetic (`+`, `-`, `sum(`, `quantize`) on `Decimal` values and no precedence terms in `report_pdf.py`
    - _Requirements: 1.7, 1.8, 2.1, 2.5, 3.3, 5.5, 21.1, 21.2_

- [x] 3. Checkpoint - renderer
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 4. Backend: PDF routes
  - [x] 4.1 Add the PDF routes and the public wiring accessors in `router/handler.py`
    - Add `get_wiring` and `to_jsonable` as public aliases of `_wiring` and `_to_jsonable`, and `build_package_service(wiring, user_id)` wiring `ReportingService`, `ItemizedExpenseService`, `TransactionService`, and `PropertyService` as the report routes do
    - Add `_property_report_pdf` (`@_property_scoped`) and `_combined_report_pdf`, register `POST /properties/{propertyId}/report/pdf` and `POST /reports/combined/pdf`, build the PDF through `ReportingService`, `ItemizedExpenseService.summary`, and `render_*_pdf`, store it with `pdf_key`, and return `download_url`, `filename`, `content_type`, `size_bytes`, `expires_in_seconds`
    - Reuse the existing `propertyIds` validation; return `400` with `field: "propertyIds"` when the user owns no property
    - _Requirements: 1.1, 1.10, 4.1, 4.5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 15.1, 15.3, 15.4, 15.5, 15.6_
  - [x] 4.2 Write PDF route tests
    - New `backend/tests/router/test_report_pdf_routes.py`: success for both routes with the key prefix and attachment disposition, the filename forms, `400` for a bad `taxYear` and bad `propertyIds`, no-property `400`, no-bucket `503`, a report conflict passes through with no link, `GET` on both paths resolves to no route, and route resolution of `/reports/combined` and `/properties/{propertyId}/report` is unchanged
    - Extend `backend/tests/router/test_cross_user_authorization.py`: user B requests a PDF for user A's property and names it in `propertyIds`; each response is byte-identical to the missing-id response and writes no object
    - _Requirements: 1.1, 1.10, 4.5, 6.1, 6.2, 6.5, 6.6, 15.3, 15.5_

- [x] 5. Backend: package builder
  - [x] 5.1 Create `services/accountant_package.py` with `PackageBuilder`
    - `PackageResult`, `PackageTooLarge`, `PackageBuildError`, and `PackageBuilder.build(tax_year, property_ids, zip_path)`: reports (PDF, CSV, JSON per property and combined for two or more), `RepairsDetail` from `ItemizedExpenseService.summary`, the transactions CSV (columns, ordering, `neutralize_cell`, `document_paths`), receipts streamed in chunks with `missing` and `oversized` skips, the receipt count and size limits, `README.txt`, and `manifest.json` last
    - Compute checksums and sizes from the bytes written; sort entries by path; use the injected clock for the manifest and entry timestamps; compress text, store receipts; return the ZIP's SHA-256
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.8, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.8, 12.9, 16.3, 21.1_
  - [x] 5.2 Add the optional checklist provider to `accountant_package.py`
    - `ChecklistProvider` protocol (`checklist_for(property_id, tax_year)`), `default_checklist_provider(wiring, user)` importing `logstead.services.checklist` at run time and returning the object from `provider_for(wiring, user)`, or `None` when the module or `provider_for` is absent or raises; the builder writes `checklist/year-end-checklist-<year>.json` when the provider returns results, and records `not available in this release` or `could not be generated` in `sections.checklist` otherwise
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_
  - [x] 5.3 Write the transactions CSV property test
    - **Property 11: Transactions CSV round trip**
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.7**
    - New `backend/tests/services/test_package_transactions_csv_property.py`
  - [x] 5.4 Write the manifest and wire form property tests
    - **Property 12: Manifest matches the ZIP**
    - **Property 15: Wire form of money and counts**
    - **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5, 12.7, 12.8, 16.1, 9.4**
    - New `backend/tests/services/test_package_manifest_property.py` building real ZIPs in a temp directory from moto receipts
  - [x] 5.5 Write the report agreement property test
    - **Property 7: Package files agree with the report**
    - **Validates: Requirements 2.1, 2.2, 8.3, 3.6**
    - New `backend/tests/services/test_package_agreement_property.py` through the real `ReportingService` over moto
  - [x] 5.6 Write builder example tests
    - New `backend/tests/services/test_accountant_package.py`: one and several properties and the resulting entry set, receipts at the layout path, a missing and an oversized receipt in the manifest, the receipt-count limit and the size limit with lowered constants (job fails and no ZIP object remains), the checklist provider absent, failing, and present, a fixed clock gives identical output, entry order and compression types, chunked copy with a fake stream that records read sizes, the README text including the CSV caveat
    - Assert that a built package leaves no object under `exports/combined/` and that the package write set contains no key without the user id
    - _Requirements: 8.1, 8.2, 8.7, 9.8, 10.2, 10.3, 10.4, 10.5, 10.6, 11.1, 11.2, 11.3, 12.6, 12.9, 22.6, 22.7, 24.5_
  - [x] 5.7 Write the checklist import contract test
    - New `backend/tests/services/test_accountant_package_checklist_contract.py`: with a stub `logstead.services.checklist` module on `sys.modules` exposing `provider_for(wiring, user)` that returns an object with `checklist_for(property_id, tax_year)`, `default_checklist_provider` returns that object and the builder writes `checklist/year-end-checklist-<year>.json`; with the module absent, or present without `provider_for`, or with `provider_for` raising, the package completes and the manifest `sections.checklist` records the reason; when the real `logstead.services.checklist` module exists in the repository, run the same contract against it and skip otherwise
    - _Requirements: 11.2, 11.3, 11.4, 11.6, 11.7_

- [x] 6. Backend: jobs, worker, and package routes
  - [x] 6.1 Create `services/package_jobs.py` and `adapters/package_invoker.py`
    - `PackageJobService` (`create`, `list`, `get`, `delete`) and the pure `effective_status`, `is_active`, `is_expired`; `create` resolves and checks properties, rejects an empty set, returns `conflict` for an active job, writes the job `queued` with `ttl`, and invokes the worker; an invoke error marks the job `failed` and returns `unavailable`; `get` and `list` issue a fresh link for `complete` jobs only; `delete` removes the S3 object first, then the item, and returns `conflict` for an active job
    - `PackageInvoker(lambda_client, function_name).invoke(user_id, job_id)` with `InvocationType="Event"` and a two-id payload
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.8, 7.9, 7.10, 13.8, 14.4, 14.5, 14.6, 15.3, 15.4_
  - [x] 6.2 Create the worker `backend/src/logstead/worker/package_worker.py`
    - `handler(event, context)` loads the job by user id and job id, ignores a missing or non-`queued` job, marks it `running`, runs `PackageBuilder` inside a `TemporaryDirectory`, uploads with `upload_file`, and marks `complete` or `failed` with the fixed messages; logs error type and location only; imports only `get_wiring`, `to_jsonable`, and `build_package_service` from the router
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.9, 15.7_
  - [x] 6.3 Add the package routes and invoker wiring in `router/handler.py`
    - Add `package_invoker` to `_Wiring`, `_build_wiring_from_env` (from `PACKAGE_WORKER_FUNCTION`), and `configure(...)`; add `_create_package` (202), `_list_packages`, `_get_package`, `_delete_package`; register the four routes; `503` when the invoker or files are not configured; validate `tax_year` and `property_ids`
    - _Requirements: 7.1, 7.2, 7.3, 7.6, 7.7, 7.9, 15.2, 15.4, 15.5, 15.8_
  - [x] 6.4 Write the job state property test
    - **Property 8: Job state classification**
    - **Validates: Requirements 7.5, 7.8, 7.10, 14.4**
    - New `backend/tests/services/test_package_job_state_property.py`
  - [x] 6.5 Write the write set property test
    - **Property 13: The build writes only the ZIP and the job**
    - **Validates: Requirements 10.7, 10.8, 15.7**
    - New `backend/tests/services/test_package_write_set_property.py` running the worker over a recording repository and a recording S3 adapter
  - [x] 6.6 Write the message leak property test
    - **Property 14: Messages never leak internals**
    - **Validates: Requirements 13.9**
    - New `backend/tests/services/test_package_messages_property.py`
  - [x] 6.7 Write job service and worker example tests
    - New `backend/tests/services/test_package_jobs.py`: create, list order and limit, get, fresh link on each read, no link stored, expired job is `not_found`, delete order (S3 first) and S3 failure keeps the item, the invoke failure path, one active job
    - New `backend/tests/services/test_package_worker.py`: missing and non-`queued` jobs ignored, success, `PackageTooLarge`, property gone, unexpected exception, the temporary directory is removed in every case, the job `ttl`, only the stored job's user data is read
    - _Requirements: 7.1, 7.4, 7.5, 7.6, 7.9, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.8, 14.4, 14.5, 14.6, 22.9_
  - [x] 6.8 Write package route tests and extend the cross-user tests
    - New `backend/tests/router/test_package_routes.py`: create returns `202` and calls a fake invoker once; list order and limit; `409` for an active job and for deleting one; the stale job; `400` with the right `field` for year, `property_ids`, and an over-long list; `503` with no worker configured; `PUT` and `PATCH` resolve to no route
    - Extend `backend/tests/router/test_cross_user_authorization.py`: user B reads, deletes, and creates against user A's job and property; each response is byte-identical to the missing-id response with no S3 read
    - _Requirements: 7.1, 7.2, 7.5, 7.7, 7.10, 15.2, 15.3, 15.5, 22.8_

- [x] 7. Checkpoint - backend
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 8. Infrastructure
  - [x] 8.1 Update `infra/template.yaml` and `backend/Makefile`
    - Add `PackageWorkerFunction` (600 second timeout, 1024 MB memory, 1024 MB ephemeral storage, reserved concurrency 2, event invoke config with zero retries and a 300 second event age, narrow policy) and `build-PackageWorkerFunction`
    - On `ApiFunction`: `PACKAGE_WORKER_FUNCTION` environment variable, `lambda:InvokeFunction` on the worker, `s3:DeleteObject` on `exports/packages/*` and `exports/pdf/*`, and the updated comment; add throttled events and `RouteSettings` for the three new POST routes
    - On `FilesBucket`: the `ExpireAccountantPackages` and `ExpireGeneratedPdfs` lifecycle rules with one-day expiry and one-day noncurrent expiry
    - Add `PackageWorkerErrorsAlarm`; leave the CSP, CORS, Cognito, and table resources unchanged
    - _Requirements: 14.2, 14.3, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9_
  - [x] 8.2 Write the template test
    - New `backend/tests/infra/test_template_accountant_package.py` in the style of `test_template_schedule_e_extraction.py`: the worker function and its limits, its policy has no actions beyond those listed, the API invoke and delete grants, the lifecycle rules including noncurrent expiry, the throttled routes, the event invoke config, and the CSP resource and table definition are unchanged from a recorded fingerprint
    - _Requirements: 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 22.10_

- [x] 9. Frontend: API modules and helpers
  - [x] 9.1 Add the API modules
    - New `frontend/src/api/accountantPackage.ts`: `AccountantPackageApi` with an injectable `ApiClient`, `createPackage`, `listPackages`, `getPackage`, `deletePackage`, the wire types, and a shared instance
    - Extend `frontend/src/api/reports.ts` with `createReportPdf(propertyId, taxYear)` and `createCombinedReportPdf(taxYear, propertyIds?)` returning `PdfDownload`; the browser CSV and JSON functions are unchanged
    - Add `frontend/src/api/accountantPackage.test.ts` and extend `frontend/src/api/reports.test.ts` for paths, methods, bodies, and query strings
    - _Requirements: 7.1, 7.2, 6.1, 6.2, 17.5, 18.3_
  - [x] 9.2 Add pure helpers in `frontend/src/lib/packageJob.ts`
    - `isTerminal`, `statusLabel`, `formatBytes`, `linkMinutes`, `POLL_INTERVAL_MS` (3000), and `startDownload(url)` (a thin wrapper over `window.location.assign` so tests can stub it), with `packageJob.test.ts`
    - _Requirements: 17.5, 17.7, 19.6_
  - [x] 9.3 Add the polling hook `components/accountant-package/usePackageJob.ts`
    - Modeled on `useExtractionJob`: create, poll at an injectable interval, resume from `listPackages` on mount, stop on a terminal status and on unmount, tolerate two failed polls and stop on the third, expose `{ job, error, busy, start, remove, refresh }`; add `usePackageJob.test.ts` with fake timers
    - _Requirements: 17.5, 17.8, 17.9, 17.10_

- [x] 10. Frontend: components, page, and PDF buttons
  - [x] 10.1 Build the components in `frontend/src/components/accountant-package/`
    - `PackageDisclaimer` (`role="note"`), `PackageContentsList`, `PropertyPicker` (`fieldset` and `legend`, a labelled checkbox per property, all checked by default), `PackageStatusPanel` (progress live region, completion details, skipped receipts note, download link, delete button), and `index.ts`
    - Build only from shared primitives and semantic tokens; no money arithmetic
    - _Requirements: 17.3, 17.4, 17.6, 17.7, 17.11, 19.1, 19.3, 19.4, 19.5, 19.6, 21.1_
  - [x] 10.2 Build `frontend/src/pages/AccountantPackagePage.tsx`
    - `PageHeader` titled "Accountant package", document title, year `Select` from `usePortfolioYearRange` defaulting to `latestCompletedTaxYear()`, `PropertyPicker`, "Prepare package" `Button` disabled while a job is active, `PackageStatusPanel`, error `StateBlock` with retry, `ConfirmDialog` for delete, `useFirstLoad` for the first job-list load
    - Add `AccountantPackagePage.test.tsx` covering idle, preparing, complete, failed with retry, skipped receipts, resumed active job, resumed finished job, delete with confirm, year change, property selection, and the disclaimer in every state
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 17.11, 17.12, 19.1, 19.7, 22.11_
  - [x] 10.3 Add the PDF buttons to the report pages
    - In `frontend/src/pages/ReportsPage.tsx` and `frontend/src/pages/CombinedReportsPage.tsx` add a "Download PDF" `Button` (busy state, `startDownload` on success, error toast on failure, `print:hidden`); add a link to `/accountant-package` on the combined page; leave the print behavior unchanged
    - Extend `ReportsPage.test.tsx` and `CombinedReportsPage.test.tsx`
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 22.11_

- [x] 11. Frontend: navigation, route, and accessibility
  - [x] 11.1 Add the nav entry and the route
    - Add `{ to: "/accountant-package", label: "Accountant package", icon: "reports" }` to the Tax group in `frontend/src/components/navConfig.ts`; add `{ path: "accountant-package", element: <AccountantPackagePage /> }` and update the route comment in `frontend/src/routes.tsx`
    - Update `navConfig.test.ts`, `MainNav.test.tsx`, and `routes.test.tsx` where they enumerate entries; confirm `pageConformance.test.ts` needs no allowlist entry
    - _Requirements: 17.1, 19.7, 22.11_
  - [x] 11.2 Add accessibility and browser coverage
    - Add canned package list and job responses to `frontend/src/test/apiStub.ts` and `frontend/src/test/fixtures.ts`; add `["accountant package", "/accountant-package"]` to `ROUTES` in `frontend/e2e/a11y.spec.ts` and the API stubs to `frontend/e2e/fixtures.ts`; cover the idle, preparing, complete, and failed states in light and dark themes with one `h1`
    - Add a smoke test in `frontend/e2e/smoke.spec.ts` that prepares a package against stubs and asserts the download link
    - _Requirements: 19.2, 22.11_

- [x] 12. Documentation
  - [x] 12.1 Update `docs/api.md`
    - Document the five new routes and the two PDF routes, the job view, the `202` status added to the error model table, the `409` cases, and the `400` fields
    - Note that the server CSV export now prefixes an apostrophe to text cells that start with `=`, `+`, `-`, or `@`, and that the combined export key is `exports/combined/<user_id>/<tax_year>/<filename>`
    - _Requirements: 23.1, 15.8, 24.1_
  - [x] 12.2 Update `docs/data-model.md`
    - Add the Package_Job item, its keys and TTL, the S3 prefixes, and a statement that the feature stores nothing else, and the user-scoped `exports/combined/<user_id>/<tax_year>/` prefix
    - _Requirements: 23.2_
  - [x] 12.3 Update `docs/developer-guide.md`
    - Document the package layout, the Package_Config limits, how to add a file to the package, the optional checklist hook (`provider_for`), the PDF text-safety rule (all user text through `pdf_text`), and the new `PACKAGE_WORKER_FUNCTION` variable
    - _Requirements: 23.3_
  - [x] 12.4 Update `docs/testing.md`
    - Describe the new property tests, the worker and job tests, the template test, and the PDF text extraction approach
    - _Requirements: 23.4_
  - [x] 12.5 Update `docs/deployment.md`
    - Document the worker function, its permissions, the lifecycle rules, reserved concurrency, the measured package size from task 1.1, and a note that a deployment blocked by the account's Lambda concurrency limit needs a Lambda concurrency quota increase requested through Service Quotas (reserved concurrency 2 counts against the unreserved pool)
    - _Requirements: 23.5, 20.2_
  - [x] 12.6 Update `docs/future-improvements.md`
    - Add live sharing links, accountant accounts, emailing the package, a Unicode PDF font (so characters outside Windows-1252 stop printing as `?`; about 0.5 MB bundled), a shorter or configurable retention, and the missing noncurrent-version expiry on the existing `exports/` and `imports/schedule-e/` lifecycle rules (the combined export key finding is fixed by task 1.10)
    - Record the Windows-1252 limitation under known limitations
    - _Requirements: 23.7_
  - [x] 12.7 Update `CHANGELOG.md`
    - Record the PDF report, the Accountant package, the worker, and the new dependency
    - Add a changed-behavior note: the server CSV export now prefixes an apostrophe to text cells that start with `=`, `+`, `-`, or `@` (rare values only; the browser CSV download is unchanged)
    - Add a fixed note: the combined export key now includes the user id (`exports/combined/<user_id>/<tax_year>/...`), closing a latent cross-user overwrite
    - _Requirements: 23.8_
  - [x] 12.8 Update `README.md`
    - Add the PDF report and Accountant package to the feature list with a line that they are organizing aids and not tax advice
    - _Requirements: 23.8_

- [x] 13. Final checkpoint - full verification
  - Ensure backend `pytest`, frontend `vitest`, `npm run lint`, `npm run build`, the type check, and `cfn-lint` on the template pass, ask the user if questions arise.

## Notes

- Every leaf task is required. There are no optional sub-tasks in this plan, matching the year-end-checklist plan.
- The pure layers (tasks 1 and 2) are the core. The builder, jobs, worker, and routes add no figures of their own.
- The combined export key fix (1.10) is a bug fix to existing code. It is the only change to existing export behavior apart from the CSV cell prefix (1.6), and both are recorded in the changelog (12.7).
- Tasks that write the same file sit in different waves: `services/report.py` (1.6, 1.10), `test_report_export.py` (1.9, 1.11), `services/report_pdf.py` (2.1, 2.2, 2.3), `router/handler.py` (4.1, 6.3), `services/accountant_package.py` (5.1, 5.2), `test_cross_user_authorization.py` (4.2, 6.8), `ReportsPage.tsx` and `CombinedReportsPage.tsx` (10.3).
- The nav entry and route (11.1) come after the page exists so no entry points at a missing page.
- The year-end checklist is optional. This plan neither requires nor implements it. Tasks 5.2, 5.6, and 5.7 test the package with the provider absent, failing, and present.
- No deploy and no commit are part of this plan.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4", "1.5", "9.1", "9.2"] },
    { "id": 1, "tasks": ["1.6", "1.7", "1.8", "2.1", "9.3", "10.1"] },
    { "id": 2, "tasks": ["1.9", "1.10", "2.2", "2.4", "10.2", "10.3"] },
    { "id": 3, "tasks": ["1.11", "1.12", "2.3", "2.5", "2.6", "2.7", "2.8", "11.1"] },
    { "id": 4, "tasks": ["2.9", "2.10", "4.1", "5.1", "11.2"] },
    { "id": 5, "tasks": ["4.2", "5.2", "5.3", "6.1"] },
    { "id": 6, "tasks": ["5.4", "5.5", "5.6", "5.7", "6.2", "6.4", "8.1"] },
    { "id": 7, "tasks": ["6.3", "6.5", "6.6", "6.7", "8.2"] },
    { "id": 8, "tasks": ["6.8", "12.1", "12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "12.8"] }
  ]
}
```
