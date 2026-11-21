# Requirements Document

## Introduction

Logstead is a single-user Schedule E rental tax app (React/Vite/Tailwind SPA; Python 3.12 Lambda over a single-table DynamoDB design; SAM infrastructure). A user who works with an accountant, or who wants to check the year against the form, has no way to hand over a year's records today. The Reports pages show the figures and let the browser download CSV or JSON built client-side. Receipts live in S3 behind individual transactions. Nothing produces a PDF, and nothing gathers the pieces.

This feature adds two things.

1. **Schedule E PDF report.** A printable PDF per property and a combined portfolio PDF, laid out like Schedule E Part I: income lines 3 and 4, expense lines 5 to 17, line 18 depreciation, line 19 other with its descriptions, totals, a Line 12 source note, and the itemized Repairs entries as an appendix when they exist. The PDF shows the same figures as the existing report. It is a worksheet, not an IRS form.
2. **Accountant package.** One ZIP for a tax year containing the PDF reports, the CSV and JSON report exports, a transactions CSV, the year's receipts organized by property and category, the year-end checklist summary when that feature exists, a README, and a manifest with SHA-256 checksums and the generation time. The ZIP is built by a background job and downloaded through a short-lived presigned S3 link.

Both are **read-only views of data the app already holds**. They compute no figure of their own, give no tax advice, and use no AI. Every figure comes from `ReportingService.report_for` and the services it already uses. The precedence rules (Line 12 loan interest, entered total versus itemized entries, Line 18 depreciation) are never restated.

### Out of scope

- Live sharing links, a public or token-based report URL, and accountant accounts, invitations, or roles. A package is a file the user downloads and sends. See `docs/future-improvements.md` (added by this work).
- Electronic filing, IRS form fill (the PDF is not Form 1040 Schedule E and says so), and tax computation of any kind.
- Emailing the package. The user downloads it.
- Schedules and forms other than Schedule E Part I (Form 8582, Form 4562, Schedule E Part II and later).
- Property photos, business documents, and the original Schedule E import PDFs. The package carries transaction receipts only.
- Any change to precedence rules, the carryforward algorithm, the loan schedule engine, or the Schedule E import parser.
- Per-user editing of package limits in the UI. The limits are configuration in one backend module.

### Grounding in the existing code

- `services/report.py` builds `ScheduleEReport` (`header`, `lines` for lines 3 to 19, `other_items`, `totals`, `line12`) and `CombinedScheduleEReport` (`properties`, `totals`, `line12`). `ReportingService.export_report` and `export_combined_report` exist and write CSV or JSON to S3 under `exports/`, but no route calls them. The private serializers `_report_to_csv`, `_report_to_json`, `_combined_to_csv`, and `_combined_to_json` hold the server-side CSV and JSON layout.
- The browser download on the Reports page is built client-side by `reportToCsv` and `reportToJson` in `frontend/src/api/reports.ts`. That CSV omits the `Schedule E Report` title row and uses `\n` line endings, whereas the server CSV uses the csv module defaults. The package uses the server serializers (Decisions recorded).
- `services/itemized.py` holds `LineAccumulator` and `ItemizedExpenseService.summary`, which return the entered total, the itemized entries, the itemized sum, and the line source for Repairs (Schedule E line 14).
- `services/transaction.py` lists a year's transactions (`list_for_property`) and stores receipts as `#DOC#` rows with an `s3_key`, `content_type`, and `original_filename`. Receipt objects live in S3 under `receipts/<transactionId>/<filename>`. `S3FileAdapter` (`adapters/s3_files.py`) holds the bucket, the key helpers, presigned URLs, and a 25 MiB cap (`MAX_DOCUMENT_BYTES`) on receipts.
- `services/schedule_e_extraction.py` is the existing async-job pattern: a transient per-user DynamoDB item (`USER#<userId>`, `SEEXTRACT#<jobId>`) with a `ttl` attribute, a status poll, and a `not_found` for a job owned by another user. The SAM template enables sparse TTL on the `ttl` attribute.
- `router/handler.py` guards `/properties/{propertyId}/...` routes with `_property_scoped`, validates path ids with `_check_path_ids` and `taxYear` with `_int_param`, and maps `Result` failures to the error model in `docs/api.md`. API Gateway HTTP API caps an integration at 30 seconds, and a synchronous Lambda response at 6 MB ([AWS HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html); [Lambda Invoke API](https://docs.aws.amazon.com/goto/WebAPI/lambda/Invoke)).
- `infra/template.yaml` defines one API Lambda (30 second timeout, 512 MB memory, reserved concurrency 10), a files bucket with versioning on, S3 grants limited to named prefixes, a 30-day lifecycle on `exports/`, and a catch-all `ANY /{proxy+}` route with explicit routes only for throttled paths.
- The CloudFront CSP allows `connect-src` to the files bucket and sets `default-src 'self'`. A download started by navigating to a presigned S3 link is not a fetch and needs no CSP change.
- Frontend: `PageHeader`, `PropertySection`, `StateBlock`, `Button`, `Select`, `Badge`, `ResponsiveTable`, `useAsyncResource`, `useFirstLoad`, `usePortfolioYearRange`, `DisclaimerNotice` wording on the carryforward page, the polling hook `useExtractionJob`, and the axe route suite in `frontend/e2e/a11y.spec.ts`.

### Decisions recorded

- **PDF library: ReportLab, server-side.** A browser print stylesheet cannot put a PDF inside a ZIP built on the server, cannot be tested from Python, and depends on the viewer's browser. ReportLab is BSD-licensed, ships as a pure-Python wheel, and renders the standard Helvetica font without embedding. See the design for the comparison with fpdf2, WeasyPrint, and headless Chromium.
- **Single PDFs are synchronous; the package is asynchronous.** One report PDF renders in the API Lambda well inside the 30 second limit. A package can hold hundreds of megabytes of receipts and cannot pass through a 6 MB response or a 30 second integration. The package is built by a separate worker Lambda started with an asynchronous invoke, and the browser polls a job.
- **Downloads use presigned S3 links.** The API never returns file bytes. It returns a link valid for 15 minutes, issued fresh on each status read after an ownership check.
- **The package uses the server CSV and JSON serializers.** They are the existing server-side export layout. The browser download keeps its own layout, unchanged.
- **Text cells are neutralized against spreadsheet formulas.** A description that starts with `=`, `+`, `-`, or `@` is prefixed with an apostrophe in every CSV the feature writes, because an accountant opens these files in a spreadsheet. This also applies to the existing server CSV serializers, which the package reuses.
- **One active package job per user.** A second create request while a job is queued or running returns `409`. This bounds cost and removes duplicate worker runs.
- **Missing receipts degrade; size overruns fail.** A receipt object that is absent or over the document cap is skipped and listed in the manifest. A package that would exceed the package size cap fails with a message that tells the user to select fewer properties.
- **The year-end checklist is optional.** The `year-end-checklist` spec exists in this repository and its code may or may not be present. The package includes the checklist file only when the checklist service is importable and returns a result. Otherwise the manifest records why it is absent.
- **The transactions CSV lists stored rows, not report amounts.** The report applies the entered-total-versus-itemized rule and the loan-interest rule. The CSV lists every stored row with its `itemized` and `imported` columns, and the README says its column sums can differ from the report.
- **No new stored entity beyond the job.** The only new item is the transient package job (24 hour TTL).
- **A new worker Lambda with reserved concurrency 2.** The package is built by a separate function, not by a longer API timeout. Reserved concurrency of 2 counts against the account's unreserved pool. If the account's Lambda concurrency limit blocks the reservation, the deployer requests a Lambda concurrency quota increase (documented in `docs/deployment.md`, Requirement 23.5). The fallback of a package without receipts is not adopted.
- **Finished packages can be deleted.** `DELETE /accountant-packages/{jobId}` is kept. The API role gains `s3:DeleteObject` on `exports/packages/*` and `exports/pdf/*` only, which narrowly loosens the "exports are never deleted by the app" stance.
- **Limits live in one module.** 400 MiB (`PACKAGE_MAX_BYTES`), 2000 receipts (`PACKAGE_MAX_RECEIPTS`), 15-minute links (`DOWNLOAD_LINK_SECONDS`), and 24-hour retention (`JOB_TTL_SECONDS` and the one-day lifecycle rules) are defined in `services/package_config.py` and the template, and nowhere else.
- **Known limitation: PDF text outside Windows-1252 prints as `?`.** The renderer uses the standard Helvetica font without embedding. Embedding a Unicode font is recorded as a future improvement in `docs/future-improvements.md` (Requirement 23.7).
- **The formula prefix applies to the existing server CSV.** The package reuses the server serializers, so the apostrophe prefix changes the existing server CSV output for the rare value that starts with `=`, `+`, `-`, or `@`. The change is recorded in `CHANGELOG.md` (Requirement 23.8). The browser CSV download is unchanged.
- **The combined export key is scoped by user id (bug fix in scope).** `ReportingService.export_combined_report` wrote to `exports/combined/<tax_year>/...` with no user id, so two users exporting the same year would overwrite one object. No route calls it today, so the defect is latent. This work changes the key to `exports/combined/<user_id>/<tax_year>/<filename>` and fixes the affected tests (Requirement 24). The package's combined files are bytes inside the ZIP built with the server serializers, and the package writes no combined export object outside the user-scoped prefixes.
- **The checklist hook is `logstead.services.checklist.provider_for(wiring, user)`.** It is defined by the `year-end-checklist` spec (its Requirement 24) and returns an object with `checklist_for(property_id, tax_year)`. The package imports it at run time and omits the checklist file when it is absent.
- **Two simultaneous create requests can both pass the active-job check.** The repository has no conditional write. The route throttle bounds the window and the result is two valid packages.
- **Local development.** Without `PACKAGE_WORKER_FUNCTION` the create route returns `503`. Tests inject a fake invoker.
- **Line labels.** The PDF labels line 20 "Total expenses" and line 21 "Net income or (loss)". Lines 22 and 23 are not shown.

## Glossary

- **Logstead_API**: The Python Lambda backend reached through the router in `router/handler.py`.
- **Logstead_UI**: The React single-page frontend.
- **Pdf_Renderer**: The backend module `services/report_pdf.py` that turns a `ScheduleEReport` or `CombinedScheduleEReport` plus Repairs detail into PDF bytes. It performs no I/O and holds no totals logic.
- **Pdf_Report**: A PDF produced by the Pdf_Renderer for one property and tax year (Property_Pdf) or for several properties and a tax year (Combined_Pdf).
- **Package_Service**: The backend service that creates, lists, reads, and deletes Package_Jobs and issues Download_Links.
- **Package_Worker**: The separate Lambda function that builds one Accountant_Package for one Package_Job.
- **Package_Builder**: The module `services/accountant_package.py` that assembles the ZIP from existing services. The Package_Worker calls it.
- **Accountant_Package**: The ZIP file built for one user and one tax year.
- **Package_Job**: The transient DynamoDB item `USER#<userId>` / `ACCTPKG#<jobId>` that tracks one build.
- **Job_Status**: One of `queued`, `running`, `complete`, or `failed`.
- **Download_Link**: A presigned S3 GET URL with a Content-Disposition of attachment, valid for `DOWNLOAD_LINK_SECONDS`.
- **Manifest**: The file `manifest.json` in the Accountant_Package listing every other file with its size and SHA-256 checksum, the generation time, and the tax year.
- **Readme_File**: The file `README.txt` in the Accountant_Package describing the contents and carrying the Package_Disclaimer.
- **Package_Config**: The single backend module `services/package_config.py` holding `PACKAGE_MAX_BYTES` (400 MiB, 419430400 bytes), `PACKAGE_MAX_RECEIPTS` (2000), `DOWNLOAD_LINK_SECONDS` (900), `JOB_TTL_SECONDS` (86400), `JOB_STALE_SECONDS` (900), and `JOB_LIST_LIMIT` (10).
- **Receipt**: A supporting document attached to a transaction through the existing receipt mechanism (the UI labels it "Document").
- **Skipped_Receipt**: A Receipt that the Package_Builder could not include, with a reason of `missing` (no S3 object) or `oversized` (larger than `MAX_DOCUMENT_BYTES`).
- **Slug**: A lowercase ASCII name made of letters, digits, and hyphens, derived from a property name or category label, used in ZIP entry paths.
- **Entry_Path**: The relative path of a file inside the Accountant_Package.
- **Repairs_Appendix**: The section of a Pdf_Report that lists itemized Repairs entries (Schedule E line 14) and the entered total.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string such as `"1250.00"`; never a float and never a DynamoDB `Number`.
- **Package_Disclaimer**: The notice stating that the package is an organizing aid built from the user's own records, is not tax advice, and does not tell the user what to report.
- **Completed_Tax_Year**: A tax year earlier than the current calendar year.
- **Combined_Export_Key**: The S3 key of a combined portfolio export object written by `ReportingService.export_combined_report`, of the form `exports/combined/<user_id>/<tax_year>/<filename>`.
- **Checklist_Hook**: The optional function `logstead.services.checklist.provider_for(wiring, user)` that returns an object exposing `checklist_for(property_id, tax_year)`.

## Requirements

### Requirement 1: Property Schedule E PDF

**User Story:** As the property owner, I want a printable PDF of a property's Schedule E for a tax year, so that I can check it against the form or hand it to my accountant.

#### Acceptance Criteria

1. WHEN the user requests a Property_Pdf for a property and a tax year, THE Logstead_API SHALL return a Download_Link for a PDF built from the `ReportingService.report_for` result for that property and year.
2. THE Pdf_Renderer SHALL show a header block with the property name, address, property type, tax year, fair rental days, and personal use days from the report header.
3. THE Pdf_Renderer SHALL list income lines 3 and 4, expense lines 5 to 17, line 18, and line 19 in ascending line order, each with the label and the two-decimal amount from the report line.
4. THE Pdf_Renderer SHALL show total income, total expenses (line 20), and net income or loss (line 21) from the report totals, with a negative net shown in parentheses.
5. THE Pdf_Renderer SHALL list each Line 19 other item with its description and amount below the line table, in the order of the report's `other_items`.
6. WHERE a report line has `includes_imported` set, THE Pdf_Renderer SHALL mark that line with a footnote symbol and SHALL print one footnote stating that the line includes values imported from a filed Schedule E.
7. THE Pdf_Renderer SHALL show the Line 12 source note stating whether Line 12 comes from the loan schedule or from entered transactions, and, WHEN the superseded manual interest count is greater than `0`, the count and the amount of hand-entered interest that the report did not use.
8. THE Pdf_Renderer SHALL print on every page a footer with the Package_Disclaimer text for a worksheet (not an IRS form, not tax advice), the property name, the tax year, and the page number.
9. THE Pdf_Renderer SHALL print the generation date supplied by its caller and SHALL NOT read the system clock.
10. IF the report for the property and year reports a failure, THEN THE Logstead_API SHALL return that failure through the existing error model and SHALL NOT return a Download_Link.

### Requirement 2: PDF figures equal the report

**User Story:** As the property owner, I want the PDF to show exactly the numbers on the Reports page, so that I never hold two versions of the year.

#### Acceptance Criteria

1. THE Pdf_Renderer SHALL take every line amount, total, Line 12 field, and other item from the `ScheduleEReport` it is given and SHALL NOT sum, subtract, or round any money value itself.
2. THE Logstead_API SHALL obtain the report for a Pdf_Report only from `ReportingService.report_for` or `ReportingService.combined_report`.
3. FOR ALL generated reports, every money value that the Pdf_Renderer prints SHALL equal the report's `Money` value formatted with thousands separators and two decimals.
4. FOR ALL generated reports, the text extracted from the Property_Pdf SHALL contain the formatted amount of each report line, each total, and each other item.
5. THE Pdf_Renderer SHALL contain no reference to the Line 12 precedence rule, the itemized precedence rule, or the carryforward tolerance rule.

### Requirement 3: Repairs appendix

**User Story:** As the property owner, I want my itemized repairs listed behind the report, so that my accountant can see what the Repairs total consisted of.

#### Acceptance Criteria

1. WHEN `ItemizedExpenseService.summary` for category `repairs`, the property, and the tax year reports at least one itemized entry, THE Pdf_Renderer SHALL add a Repairs_Appendix after the report.
2. THE Repairs_Appendix SHALL list each itemized entry with its date, description, and amount, ordered by date and then by id.
3. THE Repairs_Appendix SHALL show the entered total (or the text "No total entered"), the itemized sum, and the line source as reported by `ItemizedExpenseService.summary`.
4. THE Repairs_Appendix SHALL show the line 14 amount taken from the report line 14, and a note stating which source (entered total or itemized entries) produced that amount.
5. WHEN the summary reports no itemized entry, THE Pdf_Renderer SHALL omit the Repairs_Appendix.
6. FOR ALL generated Repairs summaries, the line 14 amount that the Repairs_Appendix shows SHALL equal the `line_total` of the same summary.
7. THE Repairs_Appendix SHALL state that the user decides whether an entry is a repair or an improvement and SHALL NOT state that an entry is or is not a capital improvement.

### Requirement 4: Combined portfolio PDF

**User Story:** As the property owner, I want one PDF for all my properties, so that I can see the portfolio year on one document.

#### Acceptance Criteria

1. WHEN the user requests a Combined_Pdf for a tax year, THE Logstead_API SHALL build it from `ReportingService.combined_report` and SHALL include every property of the user, or exactly the properties named in the `propertyIds` query parameter.
2. THE Pdf_Renderer SHALL lay the Combined_Pdf out with one column per property, labelled A, B, and C like Schedule E Part I, and SHALL start a new table for every three properties.
3. THE Pdf_Renderer SHALL show, after the property columns, a portfolio totals table with total income, total expenses, and net from the combined report totals, and the Line 12 total with the summed superseded manual interest count and amount.
4. THE Pdf_Renderer SHALL list each property's Line 19 other items under the property's name, and SHALL add each property's Repairs_Appendix under the same conditions as Requirement 3.
5. WHEN the user owns no property, THE Logstead_API SHALL return a `400` validation error identifying `propertyIds` and SHALL NOT return a Download_Link.
6. FOR ALL generated combined reports, the portfolio totals the Pdf_Renderer prints SHALL equal the `totals` of the combined report.

### Requirement 5: PDF text safety and rendering

**User Story:** As the property owner, I want any text I typed to appear as typed in the PDF, so that a description can never change the layout or fetch anything.

#### Acceptance Criteria

1. THE Pdf_Renderer SHALL render property names, addresses, descriptions, and notes as literal text, and SHALL NOT interpret any of them as markup, including `<`, `>`, `&`, `<img>`, `<font>`, and `<a>` sequences.
2. THE Pdf_Renderer SHALL make no network request and SHALL read no file other than its bundled standard fonts.
3. WHEN a text value contains a character outside the Windows-1252 character set, THE Pdf_Renderer SHALL replace that character with `?` so the PDF renders the rest of the value.
4. THE Pdf_Renderer SHALL wrap long text within its column and SHALL start a new page when a table does not fit, repeating the table header row.
5. THE Pdf_Renderer SHALL produce a valid PDF, readable by `pypdf`, for a report with every line at `0.00` and no other items.
6. THE Pdf_Renderer SHALL produce byte-identical output for identical inputs and an identical generation date.

### Requirement 6: PDF delivery and storage

**User Story:** As the property owner, I want to download the PDF without it passing through the API response, so that large documents and slow connections work.

#### Acceptance Criteria

1. THE Logstead_API SHALL expose `POST /properties/{propertyId}/report/pdf?taxYear={year}` returning `200` with a body holding `download_url`, `filename`, `content_type` (`application/pdf`), `size_bytes`, and `expires_in_seconds`.
2. THE Logstead_API SHALL expose `POST /reports/combined/pdf?taxYear={year}` with the optional `propertyIds` parameter, returning the same body shape.
3. THE Logstead_API SHALL store each generated PDF in the files bucket under `exports/pdf/<userId>/<random id>/<filename>` and SHALL issue a Download_Link valid for `DOWNLOAD_LINK_SECONDS` with a Content-Disposition of attachment.
4. THE Logstead_API SHALL build the filename from the Slug of the property name and the tax year, in the form `schedule-e-<slug>-<year>.pdf`, and `schedule-e-combined-<year>.pdf` for the combined report.
5. IF the files bucket is not configured, THEN THE Logstead_API SHALL return `503` through the existing error model.
6. THE Logstead_API SHALL use `POST` for both routes, because each call writes an object to S3.

### Requirement 7: Accountant package job

**User Story:** As the property owner, I want to ask for a package and come back to it, so that a large year does not tie up the page.

#### Acceptance Criteria

1. WHEN the user submits `POST /accountant-packages` with a `tax_year` and an optional `property_ids` list, THE Logstead_API SHALL create a Package_Job with Job_Status `queued`, start the Package_Worker with an asynchronous invoke, and return `202` with the job view.
2. THE Logstead_API SHALL expose `GET /accountant-packages/{jobId}` returning the job view, and `GET /accountant-packages` returning the user's most recent Package_Jobs, newest first, up to `JOB_LIST_LIMIT`.
3. THE job view SHALL contain `id`, `status`, `tax_year`, `property_ids`, `created_at`, `finished_at`, `message`, `size_bytes`, `sha256`, `file_count`, `receipt_count`, `skipped_receipt_count`, `download_url`, and `download_expires_in_seconds`, with `download_url` set only when the status is `complete`.
4. THE Logstead_API SHALL issue a fresh Download_Link on each read of a `complete` job and SHALL NOT store a Download_Link.
5. IF the user already has a Package_Job that is `queued` or `running` and not stale, THEN THE Logstead_API SHALL return `409` with a message naming that job's tax year and SHALL create no job.
6. IF the asynchronous invoke fails, THEN THE Logstead_API SHALL mark the job `failed` with a retry message and return `503` through the existing error model.
7. IF the Package_Worker function is not configured, THEN THE Logstead_API SHALL return `503` through the existing error model and SHALL create no job.
8. WHEN a job has been `queued` or `running` for longer than `JOB_STALE_SECONDS`, THE Logstead_API SHALL report its status as `failed` with a message that the build did not finish, and SHALL NOT count it as an active job.
9. WHEN the user submits `DELETE /accountant-packages/{jobId}` for a finished job, THE Logstead_API SHALL delete the job item and the package object from S3 and return `200`.
10. IF the user submits `DELETE /accountant-packages/{jobId}` for a job that is `queued` or `running` and not stale, THEN THE Logstead_API SHALL return `409` and SHALL delete nothing.

### Requirement 8: Package contents and layout

**User Story:** As an accountant, I want a predictable folder layout, so that I can find each document without asking.

#### Acceptance Criteria

1. THE Package_Builder SHALL name the ZIP `logstead-accountant-package-<year>.zip` and SHALL place these Entry_Paths inside it: `README.txt`, `manifest.json`, `reports/schedule-e-<slug>-<year>.pdf`, `reports/schedule-e-<slug>-<year>.csv`, `reports/schedule-e-<slug>-<year>.json` for each included property, `transactions/transactions-<year>.csv`, and `receipts/<property slug>/<category slug>/<file>` for each included Receipt.
2. WHERE two or more properties are included, THE Package_Builder SHALL also add `reports/schedule-e-combined-<year>.pdf`, `.csv`, and `.json`.
3. THE Package_Builder SHALL build every report file from the same `ReportingService.report_for` and `combined_report` results as the PDF, so that all report files for a property show identical figures.
4. THE Package_Builder SHALL build the CSV and JSON files with the existing server serializers, with the apostrophe prefix of Requirement 9.6 applied to text cells.
5. THE Package_Builder SHALL give every file a unique Entry_Path made only of letters, digits, `.`, `-`, `_`, and `/`, with no `..` segment, no leading `/`, no backslash, and a length of at most 200 characters.
6. WHEN two properties produce the same Slug, THE Package_Builder SHALL append a hyphen and the first six characters of the property id to the later Slug.
7. THE Package_Builder SHALL add entries in ascending Entry_Path order with the generation time as every entry's modification time, and SHALL compress text entries and store receipt entries without compression.
8. FOR ALL generated property names, category labels, and receipt filenames, every Entry_Path SHALL satisfy criterion 5 and SHALL be unique within the package.

### Requirement 9: Transactions CSV

**User Story:** As an accountant, I want every transaction of the year in one spreadsheet, so that I can sort and filter it.

#### Acceptance Criteria

1. THE Package_Builder SHALL write `transactions/transactions-<year>.csv` with one row for each transaction dated in the tax year of each included property, from `TransactionService.list_for_property`.
2. THE Package_Builder SHALL write the columns `property`, `transaction_id`, `date`, `type`, `category`, `schedule_e_line`, `amount`, `description`, `notes`, `imported`, `itemized`, `document_count`, and `document_paths`.
3. THE Package_Builder SHALL order rows by property name, then date, then transaction id.
4. THE Package_Builder SHALL write each `amount` as a Money_String and SHALL write `imported` and `itemized` as `true` or `false`.
5. THE Package_Builder SHALL write `document_paths` as the Entry_Paths of the transaction's included Receipts joined with a semicolon, and `document_count` as the number of Receipts stored for the transaction.
6. WHEN a text cell begins with `=`, `+`, `-`, `@`, a tab, or a carriage return, THE Package_Builder SHALL prefix the cell with an apostrophe.
7. FOR ALL generated transactions, parsing the CSV with the standard `csv` module SHALL return the same transaction ids, dates, amounts, and the same text values apart from the apostrophe prefix of criterion 6.
8. THE Readme_File SHALL state that the CSV lists every stored row, that the Schedule E report applies the entered-total and loan-interest rules, and that the sum of the CSV can therefore differ from a report line.

### Requirement 10: Receipts

**User Story:** As an accountant, I want the receipts filed by property and category, so that I can match them to the report.

#### Acceptance Criteria

1. THE Package_Builder SHALL include every Receipt of every transaction dated in the tax year of each included property, reading the object from S3 by the stored `s3_key`.
2. THE Package_Builder SHALL place each Receipt at `receipts/<property slug>/<category slug>/<date>_<first 8 characters of transaction id>_<sanitized filename>`, using `sanitize_filename` for the filename part.
3. WHEN a Receipt object is absent from S3, THE Package_Builder SHALL skip it, record a Skipped_Receipt with reason `missing`, and continue.
4. WHEN a Receipt object is larger than `MAX_DOCUMENT_BYTES`, THE Package_Builder SHALL skip it, record a Skipped_Receipt with reason `oversized`, and continue.
5. THE Package_Builder SHALL copy each Receipt into the ZIP in chunks, so that memory use does not grow with receipt size.
6. IF the number of Receipts exceeds `PACKAGE_MAX_RECEIPTS` or the ZIP file size exceeds `PACKAGE_MAX_BYTES`, THEN THE Package_Builder SHALL fail the job with a message that names the limit and tells the user to select fewer properties.
7. THE Package_Builder SHALL read Receipts only, and SHALL perform no S3 write other than the final ZIP object and no DynamoDB write other than the job item.
8. THE Package_Builder SHALL read each Receipt only for properties that the job's user owns.

### Requirement 11: Year-end checklist summary

**User Story:** As the property owner, I want the checklist result in the package when I have one, so that my accountant sees what I considered open.

#### Acceptance Criteria

1. WHERE the year-end checklist service is present, THE Package_Builder SHALL write `checklist/year-end-checklist-<year>.json` with the checklist of each included property for the tax year, serialized with Money_Strings.
2. WHERE the year-end checklist service is not present, THE Package_Builder SHALL build the package without the checklist file and SHALL record in the Manifest that the checklist is not included, with the reason `not available in this release`.
3. IF the checklist service is present and returns a failure for any included property, THEN THE Package_Builder SHALL omit the checklist file, record the reason `could not be generated` in the Manifest, and complete the package.
4. THE Package_Builder SHALL import the checklist service at run time, so that this feature builds, deploys, and passes its tests when the checklist code is absent.
5. THE Package_Builder SHALL describe the checklist file in the Readme_File as a reminder aid and not tax advice.
6. THE Package_Builder SHALL obtain the checklist through the optional hook `logstead.services.checklist.provider_for(wiring, user)`, which returns an object exposing `checklist_for(property_id, tax_year)`, and SHALL treat a missing module, a missing `provider_for`, or a provider that raises as an absent checklist.
7. THE test suite SHALL include a contract test proving that, when the checklist module is present, `provider_for(wiring, user)` returns an object whose `checklist_for(property_id, tax_year)` yields a result the Package_Builder serializes, and that the Package_Builder completes when the module is absent.

### Requirement 12: Manifest and README

**User Story:** As an accountant, I want to verify the package is complete and unaltered, so that I can trust what I received.

#### Acceptance Criteria

1. THE Package_Builder SHALL write `manifest.json` with `schema_version` (`1`), `app` (`Logstead`), `tax_year`, `generated_at` (ISO-8601 UTC), `disclaimer`, the included properties (`property_id` and `name`), `files`, `receipts_skipped`, `sections.checklist`, and `totals`.
2. THE Manifest `files` list SHALL contain, for every package entry except `manifest.json` itself, the Entry_Path, a `kind` (`report_pdf`, `report_csv`, `report_json`, `transactions_csv`, `receipt`, `checklist`, or `readme`), `size_bytes`, and the lowercase hexadecimal SHA-256 of the entry's bytes.
3. THE Package_Builder SHALL compute each checksum from the exact bytes written to the ZIP entry.
4. THE Manifest `receipts_skipped` list SHALL contain, for each Skipped_Receipt, the transaction id, the document id, the original filename, and the reason.
5. THE Manifest `totals` SHALL contain the number of files, the number of Receipts included, the number of Receipts skipped, and the total of `size_bytes`.
6. THE Package_Builder SHALL write `README.txt` with the tax year, the generation time, the Entry_Path layout, a note for each section, the Package_Disclaimer, and the instruction to verify a file with `shasum -a 256`.
7. FOR ALL generated packages, reading the ZIP back and computing the SHA-256 of each entry listed in the Manifest SHALL equal the Manifest checksum, and the entry set SHALL equal the Manifest `files` plus `manifest.json`.
8. THE Package_Builder SHALL record on the Package_Job the SHA-256 of the finished ZIP file, and THE job view SHALL return it as `sha256`.
9. THE Package_Builder SHALL take the generation time from an injected clock and SHALL NOT read the system clock directly.

### Requirement 13: Job execution, limits, and failure

**User Story:** As the property owner, I want a package to either finish or tell me why not, so that I am never left waiting on a job that died.

#### Acceptance Criteria

1. WHEN the Package_Worker starts a job, THE Package_Worker SHALL load the job by the user id and job id of its event, SHALL do nothing when the job is missing or its status is not `queued`, and SHALL set the status to `running` with a start time.
2. THE Package_Worker SHALL treat the user id and job id of the event as lookup keys only and SHALL take the tax year and property ids from the stored job.
3. WHEN the Package_Builder finishes, THE Package_Worker SHALL upload the ZIP to `exports/packages/<userId>/<jobId>/logstead-accountant-package-<year>.zip`, set the status to `complete` with the size, checksum, and counts, and delete the temporary file.
4. IF the build raises an error, THEN THE Package_Worker SHALL set the status to `failed` with a message that names no internal detail, log the error type and location only, and delete the temporary file.
5. IF a selected property no longer exists when the job runs, THEN THE Package_Worker SHALL set the status to `failed` with the message "A selected property no longer exists."
6. THE Package_Worker SHALL write the ZIP to temporary storage and SHALL upload it with a managed multipart upload, so that the ZIP size is limited by `PACKAGE_MAX_BYTES` and not by memory.
7. THE Package_Worker SHALL be configured with no automatic retry for asynchronous invocations, so that one request produces at most one run.
8. THE Package_Job item SHALL carry a `ttl` attribute set `JOB_TTL_SECONDS` after creation.
9. THE Logstead_API SHALL never include a stack trace, an S3 key, or a bucket name in a job message or an error body.

### Requirement 14: Download link, expiry, and cleanup

**User Story:** As the property owner, I want a financial package to disappear on its own, so that it does not sit in storage indefinitely.

#### Acceptance Criteria

1. THE Logstead_API SHALL issue each Download_Link with an expiry of `DOWNLOAD_LINK_SECONDS` and a Content-Disposition of attachment with the package filename.
2. THE infrastructure SHALL expire objects under `exports/packages/` and `exports/pdf/` after one day and SHALL expire their noncurrent versions after one day.
3. THE infrastructure SHALL allow the API function to delete objects under `exports/packages/` and `exports/pdf/` only.
4. WHEN a Package_Job item reaches its `ttl`, THE database SHALL remove the item through the existing sparse TTL, and THE Logstead_API SHALL treat a job whose `ttl` has passed but whose item still exists as not found.
5. WHEN the user deletes a finished job, THE Logstead_API SHALL delete the S3 object before it deletes the job item.
6. IF the S3 delete of a finished job's object fails, THEN THE Logstead_API SHALL keep the job item and return `503` through the existing error model.

### Requirement 15: Authorization and input validation

**User Story:** As the property owner, I want my package reachable only by me and bad input rejected, so that the new routes are as safe as the existing ones.

#### Acceptance Criteria

1. THE Logstead_API SHALL guard `POST /properties/{propertyId}/report/pdf` with the existing `_property_scoped` ownership check before the service runs.
2. WHEN a user requests a Package_Job with another user's job id, THE Logstead_API SHALL return a `404` response byte-identical to the response for a job id that does not exist, and SHALL read no S3 object and issue no Download_Link.
3. WHEN a user requests a Pdf_Report or creates a package naming another user's property id, THE Logstead_API SHALL return a `404` response byte-identical to the response for a property id that does not exist, and SHALL create no job and write no object.
4. THE Logstead_API SHALL scope the package job list, the Combined_Pdf, and the default property set to the authenticated user's properties.
5. THE Logstead_API SHALL validate path ids with the existing `_check_path_ids`, `taxYear` and `tax_year` with the existing 1900 to 2200 bounds, and `property_ids` as a list of at most 100 ids that match the existing id pattern, and SHALL return `400` with the offending `field` otherwise.
6. THE Logstead_API SHALL build every S3 key from the authenticated user id, a server-generated random id, and a server-built filename, and SHALL embed no client-supplied path segment.
7. THE Package_Worker SHALL read data only through services scoped to the user id of the stored job.
8. THE Logstead_API SHALL return errors in the existing error model of `docs/api.md` and SHALL document the `202` success status.

### Requirement 16: Money handling

**User Story:** As the property owner, I want exact amounts everywhere, so that the PDF, the CSV, and the report agree to the cent.

#### Acceptance Criteria

1. THE Logstead_API SHALL carry every monetary value of the feature as a `Decimal` in code and a two-decimal Money_String in JSON and CSV output.
2. THE Pdf_Renderer SHALL format money through one function that takes a `Decimal` and returns a string with a dollar sign, thousands separators, and two decimals, with a negative value in parentheses.
3. THE Package_Builder SHALL perform no arithmetic on money values.
4. FOR ALL generated amounts, formatting then parsing the PDF money text SHALL return the original `Decimal`.

### Requirement 17: Accountant package page

**User Story:** As the property owner, I want one page to prepare and download the package, so that I do not need to know where the files come from.

#### Acceptance Criteria

1. THE Logstead_UI SHALL add an "Accountant package" entry to the Tax group of the primary navigation and a page at `/accountant-package`, built with `PageHeader`, one `h1`, and a document title of "Accountant package".
2. THE page SHALL provide a tax-year selector that defaults to the latest Completed_Tax_Year and offers the portfolio year range, and a list of properties with a checkbox for each that is checked by default.
3. THE page SHALL show the Package_Disclaimer near the top in every state, with wording consistent with the carryforward disclaimer.
4. THE page SHALL list the contents of the package (reports, transactions CSV, receipts, checklist when available, manifest) in plain language before the user prepares it.
5. WHEN the user chooses "Prepare package", THE Logstead_UI SHALL call `POST /accountant-packages` and SHALL poll `GET /accountant-packages/{jobId}` every 3 seconds until the status is `complete` or `failed`.
6. WHILE the job is `queued` or `running`, THE Logstead_UI SHALL show a progress message in a polite live region and SHALL disable "Prepare package".
7. WHEN the job is `complete`, THE Logstead_UI SHALL show a "Download package" link, the file size, the SHA-256 checksum, the counts of files and receipts, the number of skipped receipts with a pointer to the manifest, and the time the download link stays valid.
8. WHEN the Download_Link has expired, THE Logstead_UI SHALL reload the job to obtain a fresh link, and SHALL NOT keep a link in storage.
9. IF the job is `failed` or a request fails, THEN THE Logstead_UI SHALL show an error `StateBlock` with the message from the Logstead_API and a retry action.
10. WHEN the page loads, THE Logstead_UI SHALL read the user's recent jobs and SHALL resume polling an active job or show the latest finished job.
11. THE page SHALL provide a "Delete package" action for a finished job with a confirm dialog.
12. THE page SHALL contain no AI-generated text and no tax advice.

### Requirement 18: PDF buttons on the report pages

**User Story:** As the property owner, I want a PDF button where I read the report, so that I do not look for it elsewhere.

#### Acceptance Criteria

1. THE per-property Reports page SHALL show a "Download PDF" button next to the CSV and JSON buttons, enabled when a report is shown.
2. THE combined Reports page SHALL show a "Download PDF" button and a link to the Accountant package page.
3. WHEN the user chooses "Download PDF", THE Logstead_UI SHALL call the PDF route, SHALL show a busy state on the button, and SHALL start the download from the returned link.
4. IF the PDF request fails, THEN THE Logstead_UI SHALL show an error toast with the message from the Logstead_API and re-enable the button.
5. THE Logstead_UI SHALL keep the existing print stylesheet behavior of the Reports pages unchanged.

### Requirement 19: Accessibility and UI conventions

**User Story:** As a keyboard and screen-reader user, I want the new page and buttons to follow the app's accessibility conventions, so that they are usable.

#### Acceptance Criteria

1. THE Logstead_UI SHALL build the Accountant package page only from the shared primitives (`PageHeader`, `StateBlock`, `Button`, `Select`, `Card`, `ConfirmDialog`, the toast system) and semantic color and type tokens.
2. THE Accountant package page SHALL pass the axe route suite in light and dark themes with exactly one `h1` in the idle, preparing, complete, and failed states, and the route SHALL be added to the Playwright accessibility spec.
3. THE Logstead_UI SHALL expose job progress and completion through a polite live region and SHALL move no focus automatically.
4. THE property checkboxes SHALL be inside a `fieldset` with a `legend`, each with a visible label.
5. THE Logstead_UI SHALL keep touch targets at 44px on narrow viewports through the shared `Button` and link styles.
6. THE Logstead_UI SHALL express job status through text in addition to color.
7. THE page SHALL satisfy the existing `pageConformance.test.ts` checks (page header, document title, first-load and error states) without an allowlist entry.

### Requirement 20: Dependencies and infrastructure

**User Story:** As the maintainer, I want the new dependency and infrastructure changes small, explicit, and reviewable, so that the Lambda stays within its package limits and permissions stay narrow.

#### Acceptance Criteria

1. THE project SHALL add `reportlab` pinned exactly in `backend/requirements.txt` and listed in `backend/pyproject.toml`, and SHALL record the version, license (BSD), and audit result in `docs/dependency-policy.md`.
2. THE project SHALL measure the unzipped size of the API and worker deployment packages before and after adding the dependency and SHALL record the result in `docs/deployment.md`, with the figure staying below the 250 MB unzipped Lambda limit.
3. THE SAM template SHALL define the Package_Worker as a separate function built from the same source with a 600 second timeout, 1024 MB memory, 1024 MB ephemeral storage, and reserved concurrency of 2.
4. THE SAM template SHALL grant the Package_Worker DynamoDB access to the table, `s3:GetObject` on `receipts/*`, and `s3:PutObject` and multipart actions on `exports/packages/*`, and SHALL grant it nothing else.
5. THE SAM template SHALL grant the API function `lambda:InvokeFunction` on the Package_Worker only, `s3:DeleteObject` on `exports/packages/*` and `exports/pdf/*` only, and SHALL pass the worker function name in the environment.
6. THE SAM template SHALL set the worker's asynchronous invoke configuration to zero retries and a maximum event age of 300 seconds.
7. THE SAM template SHALL add explicit throttled routes and route settings for `POST /accountant-packages`, `POST /properties/{propertyId}/report/pdf`, and `POST /reports/combined/pdf`.
8. THE project SHALL make no change to the CloudFront CSP, the files-bucket CORS rules, or the Cognito configuration.
9. THE project SHALL make no change to the DynamoDB table definition, keys, or indexes.

### Requirement 21: No tax advice

**User Story:** As the property owner, I want the new documents to stay in their lane, so that I am not told what to report.

#### Acceptance Criteria

1. THE Pdf_Report, THE Readme_File, THE Logstead_UI page, and THE Manifest SHALL contain a Package_Disclaimer stating that the content is built from the user's own records, is an organizing aid, is not tax advice, and does not tell the user what to report.
2. THE Pdf_Report SHALL state that it is a worksheet laid out like Schedule E Part I and is not an IRS form.
3. THE Logstead_API SHALL generate no text other than fixed templates filled with the user's own values, and SHALL use no AI.

### Requirement 22: Verification

**User Story:** As the maintainer, I want strong tests around figure agreement, path safety, checksums, and authorization, so that a package cannot disagree with the report or leak across users.

#### Acceptance Criteria

1. THE test suite SHALL include a Hypothesis property test, run through the real `ReportingService` over moto, proving that the amounts extracted from the Property_Pdf equal the `report_for` amounts for arbitrary small generated state.
2. THE test suite SHALL include a Hypothesis property test proving that, for arbitrary text including markup, non-Latin characters, and very long strings, the Pdf_Renderer output is a valid PDF that contains the text literally (apart from the Windows-1252 replacement) and that no network call is made.
3. THE test suite SHALL include a Hypothesis property test proving that every Entry_Path is relative, unique, and within the character and length rules for arbitrary property names, category labels, and filenames.
4. THE test suite SHALL include a Hypothesis property test proving that the Manifest checksums and entry set equal the ZIP contents.
5. THE test suite SHALL include a Hypothesis property test proving the CSV round trip and the formula-neutralizing prefix for arbitrary text.
6. THE test suite SHALL include example tests, over moto S3 and DynamoDB, for a package with receipts, with a missing receipt, with an oversized receipt, with the checklist absent, with the checklist failing, with the checklist present, with one property, and with several properties.
7. THE test suite SHALL include a test proving that exceeding `PACKAGE_MAX_BYTES` and `PACKAGE_MAX_RECEIPTS` fails the job with the documented message and leaves no ZIP object.
8. THE test suite SHALL include router tests for every new route covering success, validation errors with `field`, the `409` active-job case, the stale-job case, and the cross-user `404` byte-identity, added to `test_cross_user_authorization.py`.
9. THE test suite SHALL include worker tests proving that a missing or non-queued job is ignored, that a failed build marks the job `failed` and removes the temporary file, and that no other user's data is read.
10. THE test suite SHALL include a test proving that the SAM template contains the worker, the narrow grants, the lifecycle rules with noncurrent-version expiry, and no change to the CSP.
11. THE frontend test suite SHALL include tests for the Accountant package page states (idle, preparing, complete, failed, skipped receipts, resumed job, delete), the PDF buttons, the nav entry, the route, and the route in the axe suite.
12. AFTER the feature is implemented, THE existing backend and frontend test suites, the frontend build, and the type check SHALL remain green.
13. THE test suite SHALL include a Hypothesis property test proving that combined export keys for two different users never collide (Requirement 24.4), and example tests proving that the updated `test_report_export.py` and `test_report.py` assertions hold for the user-scoped key.

### Requirement 23: Documentation

**User Story:** As the maintainer, I want the docs to describe the package, so that future work has context.

#### Acceptance Criteria

1. THE `docs/api.md` file SHALL document the new routes, the job view, the `202` status, the `409` cases, and the PDF routes.
2. THE `docs/data-model.md` file SHALL document the Package_Job item and its TTL and state that the package stores no other data.
3. THE `docs/developer-guide.md` file SHALL document the package layout, the Package_Config limits, how to add a file to the package, the optional checklist hook, and the PDF text-safety rule.
4. THE `docs/testing.md` file SHALL describe the new property tests, the worker tests, and the template test.
5. THE `docs/deployment.md` file SHALL document the worker function, its permissions, the lifecycle rules, the reserved concurrency, the package size measurement, and a note that a deployment blocked by the account's Lambda concurrency limit needs a Lambda concurrency quota increase requested through Service Quotas.
6. THE `docs/dependency-policy.md` file SHALL record the `reportlab` pin and audit.
7. THE `docs/future-improvements.md` file SHALL list live sharing links, accountant accounts, the other out-of-scope items, and a Unicode PDF font so that characters outside Windows-1252 print as typed instead of as `?`.
8. THE `CHANGELOG.md` and `README.md` files SHALL record the feature, and THE `CHANGELOG.md` file SHALL state that the server CSV export now prefixes an apostrophe to text cells that start with `=`, `+`, `-`, or `@`, and that the combined export key now includes the user id.

### Requirement 24: User-scoped combined export key

**User Story:** As a property owner, I want my combined export stored under my own user id, so that another user's export of the same year can never overwrite mine.

#### Acceptance Criteria

1. THE Logstead_API SHALL build the Combined_Export_Key from the authenticated user id, the tax year, and a server-built filename, in the form `exports/combined/<user_id>/<tax_year>/schedule-e-combined-<tax_year>.<format>`.
2. WHEN `ReportingService.export_combined_report` stores an export, THE Logstead_API SHALL write the object at the Combined_Export_Key and SHALL write no object at a key of the form `exports/combined/<tax_year>/...`.
3. THE Logstead_API SHALL obtain the user id for the Combined_Export_Key from the user that scopes the `PropertyService` of the `ReportingService`, and SHALL accept no client-supplied path segment.
4. FOR ALL pairs of distinct user ids and any tax year and format, THE Combined_Export_Key of the first user SHALL differ from the Combined_Export_Key of the second user.
5. THE Package_Builder SHALL build its combined report files from `serialize_combined` as ZIP entries and SHALL write no S3 object under `exports/combined/` that lacks the user id.
6. THE project SHALL update `backend/tests/integration/test_report_export.py` and `backend/tests/services/test_report.py` so that their combined export assertions expect the user-scoped key, and SHALL add a test proving that two users' combined exports for the same tax year never share a key.
