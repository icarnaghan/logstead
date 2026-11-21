# Requirements Document

## Introduction

**Schedule E PDF Extraction** is "layer 2" built directly on top of the already-shipped **Schedule E Import** feature ("layer 1"). Layer 1 exposes a guided, multi-property, single-tax-year form (`POST /imports/schedule-e`) that takes an `Import_Submission` — one `Tax_Year` plus one or more `Property_Entries`, each mapping to an existing owned Property or an inline-created Property, each carrying per-line amounts for income lines 3-4, expense lines 5-17, and Line 19 (Other). Layer 1 then **synthesizes the backing transactions** that reproduce those line totals (Logstead does not store Schedule E reports; it derives them on demand), marks them as imported, validates the whole submission all-or-nothing, and replaces any prior imported set on re-import. Line 18 (Depreciation) is never imported.

This feature removes the manual typing step. The `Authenticated_User` **uploads a prior-year tax-return PDF**; the system locates the **Schedule E Part I** page(s) inside it, reads each property column's line amounts and physical address, and **pre-fills the layer-1 guided form** with the extracted values and suggested property mappings. The user then **reviews, corrects, and confirms** that pre-filled form, at which point the **existing layer-1 `Import_Service` write path persists** the result exactly as if the user had typed it. 

The governing principle is **extraction proposes, the human confirms, layer 1 persists**. Extraction output is a transient, pre-filled draft; it is never a direct write. The `Extraction_Service` MUST NOT create, modify, or delete any transaction or Property on its own — it only produces a draft that lands in the layer-1 form.

Extraction uses **Amazon Textract** (document analysis with the FORMS and TABLES features) as the engine, because Schedule E Part I is a structured government form. Because Textract document analysis is asynchronous and operates on an object in S3, the flow is: the browser **uploads the PDF to S3 via a pre-signed PUT URL** (reusing the exact pattern already used for receipts, property photos, and business documents), the backend **starts an asynchronous extraction job** against the uploaded object, the UI **polls job status** (pending / processing / complete / failed, plus a distinct "no Schedule E found" outcome), and on completion a **review screen pre-fills the layer-1 form** with editable extracted values, per-value confidence, and suggested-but-confirmable property mappings.

Because the uploaded document is a complete tax return containing highly sensitive PII, the **uploaded PDF MUST be auto-deleted from S3** once extraction completes, on a short TTL, or on failure. Only the user-confirmed numbers persist (as layer-1 imported transactions). The original return is never retained long-term.

This feature is distinct from, and MUST NOT replace or alter, the existing `/imports` PDF-**expense**-import feature (`ExpenseImportService`, which turns a property-manager expense-summary PDF into reviewable draft transactions). That feature is a useful UX precedent for upload → extract → review → confirm, but Schedule E PDF Extraction is a separate, Schedule-E-specific capability on its own route surface.

### Non-Goals (Out of Scope)

The following are explicitly out of scope for this feature and MUST NOT be implemented:

- **Direct writing of transactions or Properties by extraction.** The `Extraction_Service` only pre-fills the layer-1 guided form; the `Authenticated_User` confirms and the existing layer-1 `Import_Service` write path performs every persistent write. Extraction creates, modifies, and deletes nothing on its own.
- **Importing or extracting depreciation, or any Line 18 value.** No Line 18 (Depreciation) amount is ever read from the document, carried into the draft, or pre-filled, consistent with layer 1.
- **Reading or extracting any 1040 content other than Schedule E Part I.** Only Schedule E Part I (the property columns and lines 3-4, 5-17, and 19) is extracted; all other return content is ignored.
- **Multiple tax years or multiple returns per upload.** v1 handles exactly one tax return (one Tax_Year) per uploaded document.
- **Long-term storage of the uploaded tax-return PDF.** The uploaded PDF is auto-deleted after extraction completes, on a short TTL, or on failure; it is never retained.
- **Training a custom machine-learning model.** Amazon Textract is used as-is (document analysis with FORMS + TABLES); no custom model training is performed.
- **Changing layer 1's import/write path or how reports are computed.** This feature produces only a pre-filled draft consumed by the unchanged layer-1 `Import_Service`; it adds no new report computation.
- **Replacing or altering the existing `/imports` PDF-expense feature (`ExpenseImportService`).** That is a separate, shipping capability and is left untouched.

## Glossary

- **Logstead**: The single-user (per-authenticated-Cognito-user) serverless application for preparing an IRS Schedule E rental tax return.
- **Authenticated_User**: The person identified by a Cognito `sub`. Every object, job, and transient draft in this feature is scoped to this user.
- **Schedule_E_PDF_Extraction**: This feature — the capability that extracts Schedule E Part I data from an uploaded tax-return PDF and pre-fills the layer-1 guided import form for review and confirmation.
- **Extraction_Service**: The backend service component (to be created) that issues the upload URL, starts and tracks the asynchronous extraction job, parses the extracted result into a pre-filled draft, suggests property mappings, and ensures auto-deletion of the uploaded PDF. It performs no persistent domain writes.
- **Import_Service**: The existing layer-1 backend service (`services/schedule_e_import.py`) that validates an `Import_Submission` and synthesizes the backing imported transactions. This feature hands a user-confirmed `Import_Submission` to this unchanged service for persistence.
- **Import_Submission**: The layer-1 input shape — one `Tax_Year` and one or more `Property_Entries`. This feature produces a pre-filled, editable instance of this shape as its draft output.
- **Property_Entry**: One property column within an `Import_Submission` — a property mapping (existing or inline-created) plus the per-line amounts for income lines 3-4, expense lines 5-17, and Line 19 (Other). The analog of one Schedule E Part I property column (A, B, C, ...).
- **Tax_Return_PDF**: The uploaded prior-year tax-return document (PDF). Highly sensitive PII; auto-deleted after extraction, TTL, or failure.
- **Presigned_Upload**: A pre-signed S3 PUT URL issued to the browser so the `Tax_Return_PDF` is uploaded directly to S3 without passing through the Lambda, reusing the existing receipts / photos / business-document upload pattern.
- **Extraction_Job**: The asynchronous unit of work that runs Amazon Textract document analysis against the uploaded `Tax_Return_PDF` object and produces an `Extraction_Result`. It has a `Job_Status` and is scoped to the `Authenticated_User`.
- **Job_Status**: The lifecycle state of an `Extraction_Job`, one of: `pending`, `processing`, `complete`, or `failed`. A `complete` job additionally resolves to either an extracted draft or the distinct `no-Schedule-E-found` outcome.
- **Textract**: Amazon Textract document analysis (with the FORMS and TABLES feature types), the asynchronous extraction engine used as-is.
- **Schedule_E_Part_I**: The section of IRS Schedule E that lists rental real-estate income and expenses in property columns (A, B, C, and any additional) with lines 3-4 (income), 5-17 (expenses), 18 (depreciation — never extracted), and 19 (Other).
- **Extracted_Column**: The data read from one Schedule E Part I property column — its physical address and its per-line amounts for lines 3-4, 5-17, and 19. Each `Extracted_Column` becomes one pre-filled `Property_Entry`.
- **Extraction_Result**: The structured output of a completed `Extraction_Job`: the detected `Tax_Year`, the set of `Extracted_Columns`, suggested property mappings, and per-value confidence; or the `no-Schedule-E-found` outcome.
- **Extraction_Confidence**: A per-field / per-value measure (or at minimum a clear "please verify" indication) surfaced to the `Authenticated_User` so every extracted value can be reviewed before submission.
- **Suggested_Mapping**: A proposed mapping of an `Extracted_Column`'s physical address to one of the `Authenticated_User`'s existing Properties, produced by fuzzy address matching. A suggestion is never auto-applied; the user must confirm it.
- **Property_Service**: The existing service that lists the `Authenticated_User`'s Properties and creates Properties inline; the source of truth for fuzzy address matching and for inline creation during confirmation.
- **Money_Value**: A monetary amount handled as a `Decimal` in code and represented as a fixed two-decimal string, per Logstead's money convention (never a float, never a DynamoDB number).
- **Review_Draft**: The transient, pre-filled, fully editable `Import_Submission` presented on the review screen after a successful extraction. It persists nothing by itself.

## Requirements

### Requirement 1: Upload the tax-return PDF via pre-signed S3

**User Story:** As a Logstead user, I want to upload a prior-year tax-return PDF directly to storage, so that the system can read my Schedule E without my file passing through the application server.

#### Acceptance Criteria

1. WHEN the Authenticated_User requests to upload a Tax_Return_PDF, THE Extraction_Service SHALL issue a Presigned_Upload URL for a PDF object scoped to the Authenticated_User, reusing the existing pre-signed S3 PUT pattern.
2. THE Extraction_Service SHALL store the uploaded Tax_Return_PDF object under a key scoped to the Authenticated_User so that no other user can reference, extract from, or delete that object.
3. WHEN the Extraction_Service issues a Presigned_Upload URL, THE Extraction_Service SHALL bind the content type to the PDF content type so the authorized upload must declare a PDF.
4. IF the Authenticated_User requests a Presigned_Upload URL for a file whose declared type is not a PDF, THEN THE Extraction_Service SHALL reject the request with a validation error stating that a PDF file is required.
5. WHEN an Extraction_Job begins against an uploaded object, THE Extraction_Service SHALL confirm the object is a PDF by its content type or its `%PDF-` byte signature before processing, and SHALL otherwise fail the job with a message stating that a PDF file is required.

### Requirement 2: Start an asynchronous Textract extraction job

**User Story:** As a Logstead user, I want to kick off extraction after my upload finishes, so that the system reads my Schedule E in the background without blocking me.

#### Acceptance Criteria

1. WHEN the Authenticated_User starts extraction for an uploaded Tax_Return_PDF, THE Extraction_Service SHALL start an asynchronous Extraction_Job that runs Amazon Textract document analysis with the FORMS and TABLES feature types against the uploaded object.
2. WHEN the Extraction_Service starts an Extraction_Job, THE Extraction_Service SHALL create the Extraction_Job scoped to the Authenticated_User and return a job reference the Authenticated_User can use to poll Job_Status.
3. THE Extraction_Service SHALL set a newly started Extraction_Job to a Job_Status of `pending` or `processing`.
4. IF the Authenticated_User starts extraction against an object that does not exist within the Authenticated_User's scope, THEN THE Extraction_Service SHALL reject the request with a not-found error and SHALL NOT start an Extraction_Job.
5. THE Extraction_Service SHALL run extraction asynchronously and SHALL NOT require the extraction result to be available in the same request that starts the Extraction_Job.

### Requirement 3: Report extraction job status

**User Story:** As a Logstead user, I want to see whether extraction is pending, running, done, or failed, so that I know when my pre-filled form is ready.

#### Acceptance Criteria

1. WHEN the Authenticated_User polls an Extraction_Job the Authenticated_User owns, THE Extraction_Service SHALL report the current Job_Status as one of `pending`, `processing`, `complete`, or `failed`.
2. WHILE an Extraction_Job has not finished, THE Extraction_Service SHALL report a Job_Status of `pending` or `processing`.
3. WHEN an Extraction_Job finishes successfully and Schedule_E_Part_I data was extracted, THE Extraction_Service SHALL report a Job_Status of `complete` and make the Extraction_Result available for review.
4. WHEN an Extraction_Job finishes but no Schedule_E_Part_I was found in the document, THE Extraction_Service SHALL report a Job_Status of `complete` with a distinct `no-Schedule-E-found` outcome stating that no Schedule E was located in the uploaded document.
5. IF an Extraction_Job fails because Textract could not process the document, THEN THE Extraction_Service SHALL report a Job_Status of `failed` with a message describing the failure.
6. IF the Authenticated_User polls an Extraction_Job that does not exist within the Authenticated_User's scope, THEN THE Extraction_Service SHALL reject the request with a not-found error.

### Requirement 4: Extract Schedule E Part I property columns and lines

**User Story:** As a Logstead user, I want the system to read each property column and its line amounts from my Schedule E, so that my prior return's figures are captured without manual typing.

#### Acceptance Criteria

1. WHEN an Extraction_Job processes a Tax_Return_PDF, THE Extraction_Service SHALL locate the Schedule_E_Part_I page or pages within the document and SHALL ignore all other return content.
2. WHEN the Extraction_Service locates Schedule_E_Part_I, THE Extraction_Service SHALL produce one Extracted_Column for each property column present (A, B, C, and any additional column).
3. WHEN the Extraction_Service produces an Extracted_Column, THE Extraction_Service SHALL extract that column's amounts for income lines 3-4, expense lines 5-17, and Line 19 (Other).
4. WHEN the Extraction_Service produces an Extracted_Column, THE Extraction_Service SHALL extract that column's physical-address text from the Schedule E "Physical address of each property" box.
5. THE Extraction_Service SHALL NOT extract, carry, or pre-fill any Line 18 (Depreciation) amount from the document.
6. WHERE a Schedule_E_Line within an Extracted_Column has no readable amount, THE Extraction_Service SHALL treat that line's amount as the zero Money_Value in the Review_Draft.
7. THE Extraction_Service SHALL extract data for exactly one Tax_Return_PDF covering one Tax_Year per Extraction_Job.

### Requirement 5: Normalize extracted amounts to the Logstead money convention

**User Story:** As a Logstead user, I want extracted dollar figures to use the same precision as the rest of Logstead, so that my pre-filled form matches what layer 1 expects and my report reconciles exactly.

#### Acceptance Criteria

1. WHEN the Extraction_Service reads a line amount from an Extracted_Column, THE Extraction_Service SHALL normalize that amount to a Money_Value with exactly two decimal places for the Review_Draft.
2. IF a read line amount cannot be normalized to a two-decimal Money_Value, THEN THE Extraction_Service SHALL mark that value as requiring verification and SHALL present it for the Authenticated_User to correct rather than discarding the Extracted_Column.
3. WHEN the Extraction_Service pre-fills the layer-1 form, THE Extraction_Service SHALL represent every pre-filled line amount as a two-decimal Money_Value string consistent with the layer-1 `Import_Submission` shape.

### Requirement 6: Detect the tax year for the submission

**User Story:** As a Logstead user, I want the system to detect which tax year my return covers, so that the pre-filled submission targets the correct year.

#### Acceptance Criteria

1. WHEN the Extraction_Service produces an Extraction_Result, THE Extraction_Service SHALL set the Review_Draft's Tax_Year to the single tax year detected for the uploaded Tax_Return_PDF.
2. IF the Extraction_Service cannot confidently detect the Tax_Year, THEN THE Extraction_Service SHALL leave the Review_Draft's Tax_Year unset and mark it as requiring the Authenticated_User to select a Tax_Year.
3. THE Extraction_Service SHALL associate one Tax_Year with the Review_Draft, consistent with the one-return-per-upload scope.

### Requirement 7: Suggest confirmable property mappings via fuzzy address matching

**User Story:** As a Logstead user, I want the system to guess which of my existing properties each column belongs to, so that I can accept a correct guess with one click but still override it.

#### Acceptance Criteria

1. WHEN the Extraction_Service produces an Extracted_Column with a physical address, THE Extraction_Service SHALL fuzzy-match that address against the Authenticated_User's existing Properties using the existing Property_Service and SHALL attach a Suggested_Mapping for that column.
2. THE Extraction_Service SHALL NOT auto-apply any Suggested_Mapping and SHALL require explicit confirmation from the Authenticated_User before any column's mapping is used.
3. IF the fuzzy match for an Extracted_Column is low confidence or has no match, THEN THE Extraction_Service SHALL leave that column's mapping unmapped so the Authenticated_User must choose a mapping.
4. WHEN the Authenticated_User reviews a column's mapping, THE Schedule_E_PDF_Extraction SHALL allow the Authenticated_User to map the column to an existing owned Property or to create a Property inline, reusing the layer-1 per-entry mapping choices.
5. THE Extraction_Service SHALL scope fuzzy address matching to the Authenticated_User's own Properties so no other user's Properties are ever suggested.

### Requirement 8: Pre-fill the editable layer-1 form with confidence surfacing

**User Story:** As a Logstead user, I want every extracted number shown to me as an editable field with a confidence indicator, so that I can see and fix anything the system misread before I submit.

#### Acceptance Criteria

1. WHEN an Extraction_Job completes with extracted data, THE Schedule_E_PDF_Extraction SHALL present a Review_Draft that pre-fills the layer-1 guided form with one Property_Entry per Extracted_Column, each carrying its pre-filled line amounts and its Suggested_Mapping.
2. THE Schedule_E_PDF_Extraction SHALL make every pre-filled line amount editable by the Authenticated_User before submission.
3. THE Schedule_E_PDF_Extraction SHALL surface Extraction_Confidence per extracted value, or at minimum a clear "please verify" indication, so the Authenticated_User can identify values that need review.
4. THE Schedule_E_PDF_Extraction SHALL NOT present a Line 18 (Depreciation) field in the Review_Draft, consistent with the layer-1 form.
5. WHEN the Authenticated_User edits a pre-filled value, THE Schedule_E_PDF_Extraction SHALL use the Authenticated_User's edited value in the submitted Import_Submission in place of the extracted value.

### Requirement 9: Human confirmation hands off to the existing layer-1 import write path

**User Story:** As a Logstead user, I want my confirmed, corrected form to be saved by the same import path I would have used by hand, so that extraction never writes anything I did not approve.

#### Acceptance Criteria

1. THE Extraction_Service SHALL NOT create, modify, or delete any transaction or Property as a result of extraction alone.
2. WHEN the Authenticated_User confirms the reviewed Review_Draft, THE Schedule_E_PDF_Extraction SHALL submit it as a layer-1 Import_Submission to the existing Import_Service so that the Import_Service performs all persistent writes.
3. WHEN the Review_Draft is submitted to the Import_Service, THE Import_Service SHALL apply its existing all-or-nothing validation, synthesis, imported-marking, and replace-on-reimport behavior unchanged.
4. IF the Import_Service rejects the submitted Import_Submission for any validation or not-found reason, THEN THE Schedule_E_PDF_Extraction SHALL surface the per-entry and per-field errors on the Review_Draft so the Authenticated_User can correct and resubmit, and SHALL NOT persist any transaction.
5. THE Schedule_E_PDF_Extraction SHALL NOT introduce any new report computation and SHALL rely on the existing reporting path to derive reports from the transactions synthesized by the Import_Service.

### Requirement 10: Auto-delete the uploaded tax-return PDF

**User Story:** As a Logstead user, I want my uploaded tax return deleted automatically after extraction, so that my most sensitive document is not kept around.

#### Acceptance Criteria

1. WHEN an Extraction_Job reaches a Job_Status of `complete`, THE Extraction_Service SHALL delete the uploaded Tax_Return_PDF object from S3.
2. IF an Extraction_Job reaches a Job_Status of `failed`, THEN THE Extraction_Service SHALL delete the uploaded Tax_Return_PDF object from S3.
3. WHERE an Extraction_Job neither completes nor fails within a short bounded time-to-live, THE Extraction_Service SHALL delete the uploaded Tax_Return_PDF object from S3 after that time-to-live elapses.
4. THE Schedule_E_PDF_Extraction SHALL NOT retain the uploaded Tax_Return_PDF object beyond extraction completion, failure, or the time-to-live.
5. WHEN the Authenticated_User confirms a Review_Draft, THE Schedule_E_PDF_Extraction SHALL persist only the user-confirmed line amounts as layer-1 imported transactions and SHALL retain no copy of the original Tax_Return_PDF.

### Requirement 11: Per-user scoping

**User Story:** As a Logstead user, I want my upload, extraction job, and pre-filled draft isolated to my account, so that this feature behaves like every other record in the app.

#### Acceptance Criteria

1. THE Extraction_Service SHALL scope the uploaded Tax_Return_PDF object, the Extraction_Job, and the transient Review_Draft to the Authenticated_User identified by the Cognito `sub`.
2. IF the Authenticated_User references an uploaded object, an Extraction_Job, or a Review_Draft that belongs to a different user, THEN THE Extraction_Service SHALL reject the request with a not-found error.
3. WHEN the Review_Draft is submitted to the Import_Service, THE Import_Service SHALL apply its existing per-user ownership checks so a column mapping to a Property not owned by the Authenticated_User is rejected.

### Requirement 12: Error handling for bad input and extraction failure

**User Story:** As a Logstead user, I want clear messages when my file is unreadable, has no Schedule E, or extraction fails, so that I know whether to re-upload, choose a different file, or fall back to the manual form.

#### Acceptance Criteria

1. IF the uploaded object is corrupt or is not a readable PDF, THEN THE Extraction_Service SHALL fail the Extraction_Job with a message stating the document could not be read and that a valid PDF is required.
2. IF the Extraction_Job completes but locates no Schedule_E_Part_I, THEN THE Extraction_Service SHALL report the distinct `no-Schedule-E-found` outcome and SHALL produce no Review_Draft for the Authenticated_User to submit.
3. IF Amazon Textract returns a processing failure for the document, THEN THE Extraction_Service SHALL set the Extraction_Job to `failed` with a message describing the failure and SHALL delete the uploaded Tax_Return_PDF object.
4. WHEN an Extraction_Job fails or finds no Schedule E, THE Schedule_E_PDF_Extraction SHALL allow the Authenticated_User to proceed to the layer-1 manual guided form without any extracted pre-fill.
5. WHEN the Extraction_Service reports any failure or `no-Schedule-E-found` outcome, THE Extraction_Service SHALL create, modify, and delete no transaction or Property.

### Requirement 13: Separation from the existing PDF-expense import feature

**User Story:** As a Logstead maintainer, I want this Schedule-E extraction to stand apart from the existing PDF-expense import, so that neither feature breaks or is confused with the other.

#### Acceptance Criteria

1. THE Schedule_E_PDF_Extraction SHALL be exposed on its own distinct route surface, separate from the existing `/imports` PDF-expense import routes.
2. THE Schedule_E_PDF_Extraction SHALL NOT reuse, repurpose, modify, or remove the existing `ExpenseImportService`, its import-session and draft-transaction storage, or its routes.
3. THE Schedule_E_PDF_Extraction SHALL produce a layer-1 Import_Submission as its output and SHALL NOT produce the expense-import feature's draft-transaction entities.
