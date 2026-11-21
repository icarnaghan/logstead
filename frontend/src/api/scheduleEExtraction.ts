/**
 * Schedule E PDF Extraction API module ("layer 2").
 *
 * Typed, transport-only wrapper over the shared {@link apiClient} for the
 * Schedule E PDF Extraction feature. The user uploads a prior-year tax-return
 * PDF; the backend locates the Schedule E Part I page(s), reads each property
 * column's line amounts and physical address, and returns a pre-filled
 * {@link ReviewDraft} the SPA seeds into the existing layer-1 guided form. This
 * module only drives the three extraction routes (plus the reused S3 upload
 * helper):
 *
 *  - `startExtraction(filename, contentType)`
 *       → `POST /imports/schedule-e/extractions`            → `{ job_id, upload_url }`
 *  - `beginExtraction(jobId)`
 *       → `POST /imports/schedule-e/extractions/{jobId}/start` → `{ job_id, status }`
 *  - `getExtraction(jobId)`
 *       → `GET  /imports/schedule-e/extractions/{jobId}`     → {@link ExtractionJobView}
 *
 * This surface is **distinct** from both the expense `api/imports.ts` and the
 * layer-1 `api/scheduleEImport.ts` — both of which are left untouched (Req
 * 13.1). Confirm is NOT a route here: the review screen hands the reviewed
 * draft back to the unchanged layer-1 `importScheduleE` (`POST
 * /imports/schedule-e`).
 *
 * The backend serializes dataclasses with snake_case field names, so the wire
 * types below mirror {@link ExtractionJobView} exactly. Money and identifiers
 * are strings end-to-end (never floating point, never coerced to numbers),
 * matching the backend contract (Req 5.3); the only numbers on the wire are
 * `tax_year`, `schedule_e_line`, and the per-value `confidence` scores.
 *
 * By default this module uses the shared `apiClient`. Tests inject a custom
 * {@link ApiClient} (backed by a fake `fetch`) via
 * {@link setScheduleEExtractionClient} so they can exercise the real
 * request/parse path without hitting the network;
 * {@link resetScheduleEExtractionClient} restores the shared production client.
 */

import { ApiClient, apiClient, ApiError } from "../lib/apiClient";
// Reuse the layer-1/photos pre-signed PUT helper verbatim: the upload+extract
// page PUTs the PDF bytes to the signed URL exactly like a photo upload.
import { uploadToPresignedUrl } from "./photos";

// Re-export the error class as a value so callers can both catch it
// (`err instanceof ApiError`) and reference its type without importing the
// shared apiClient module directly.
export { ApiError };

// Re-export the reused S3 upload helper so the extraction page can import the
// whole transport surface from this one module (Design "Upload + extract page").
export { uploadToPresignedUrl };

/**
 * Extraction job lifecycle, mirroring the backend `JobStatus` literal.
 * `pending` → upload requested; `processing` → Textract running; `complete` →
 * Textract succeeded (see {@link CompleteOutcome}); `failed` → the document
 * could not be read.
 */
export type JobStatus = "pending" | "processing" | "complete" | "failed";

/**
 * Terminal outcome once `status === "complete"`, mirroring the backend
 * `CompleteOutcome` literal. `draft` → a {@link ReviewDraft} was produced;
 * `no_schedule_e_found` → the document ran but held no Schedule E Part I.
 */
export type CompleteOutcome = "draft" | "no_schedule_e_found";

/**
 * One pre-filled Schedule E line within an {@link ExtractedColumn}, mirroring
 * the backend `ExtractedLine` dataclass. The amount is money as a two-decimal
 * string ("0.00" when unreadable), consistent with layer-1's
 * `LineAmountInput.amount`. Line 18 (depreciation) never appears (Req 4.5,
 * 8.4).
 */
export interface ExtractedLine {
  /** Schedule E Part I line: 3-4 (income) or 5-17, 19 (expense); never 18. */
  schedule_e_line: number;
  /** Money as a fixed two-decimal string ("0.00" when unreadable). */
  amount: string;
  /** True when confidence is low or the value was unreadable (Req 5.2, 8.3). */
  needs_verification: boolean;
  /** Textract block confidence (0-100), when available. */
  confidence: number | null;
}

/**
 * One Schedule E Part I property column (A, B, C, ...) → one layer-1
 * `PropertyEntryInput`, mirroring the backend `ExtractedColumn` dataclass. The
 * fuzzy-match suggestion is attached but NEVER auto-applied — the user confirms
 * it in the form (Req 7.2).
 */
export interface ExtractedColumn {
  /** The read physical-address text, or null when unreadable. */
  address_text: string | null;
  /** Confidence (0-100) attached to the address read, when available. */
  address_confidence: number | null;
  /** Fuzzy-match suggestion to an existing owned property (never auto-applied). */
  suggested_property_id: string | null;
  /** Display name of the suggested property, when a suggestion exists. */
  suggested_property_name: string | null;
  /** Similarity score (0-1) of the suggested mapping, when a suggestion exists. */
  mapping_confidence: number | null;
  /** The column's extracted Schedule E line amounts. */
  lines: ExtractedLine[];
}

/**
 * The transient pre-filled import submission presented for review (Req 8),
 * mirroring the backend `ReviewDraft` dataclass. Its columns map one-to-one
 * onto layer-1 `PropertyEntryInput`s at confirm time.
 */
export interface ReviewDraft {
  /** Detected tax year, or null when not confidently detected (Req 6.2). */
  tax_year: number | null;
  /** True when the tax year was not confidently detected and must be verified. */
  tax_year_needs_verification: boolean;
  /** One column per detected Schedule E Part I property column. */
  columns: ExtractedColumn[];
}

/**
 * What a status poll returns to the SPA, mirroring the backend
 * `ExtractionJobView` dataclass. `outcome` is set only when
 * `status === "complete"`; `review_draft` is set only when
 * `outcome === "draft"`; `message` carries the failure / no-Schedule-E text.
 */
export interface ExtractionJobView {
  job_id: string;
  status: JobStatus;
  /** Set only when `status === "complete"`. */
  outcome: CompleteOutcome | null;
  /** Failure / no-Schedule-E message, when present. */
  message: string | null;
  /** Set only when `outcome === "draft"`. */
  review_draft: ReviewDraft | null;
}

/** Response body of `POST /imports/schedule-e/extractions` (201). */
export interface StartExtractionResponse {
  job_id: string;
  /** Pre-signed S3 PUT URL the browser uploads the PDF bytes to. */
  upload_url: string;
}

/** Response body of `POST /imports/schedule-e/extractions/{jobId}/start` (200). */
export interface BeginExtractionResponse {
  job_id: string;
  status: JobStatus;
}

// The client is a module-level singleton so components share one instance, but
// tests can swap it for one backed by an injected fetch.
let client: ApiClient = apiClient;

/** Override the API client used by this module (tests inject a fake fetch). */
export function setScheduleEExtractionClient(next: ApiClient): void {
  client = next;
}

/** Reset back to the shared production client (call in test teardown). */
export function resetScheduleEExtractionClient(): void {
  client = apiClient;
}

/**
 * Request a pre-signed upload URL for a prior-year tax-return PDF. Posts the
 * snake_case `{ filename, content_type }` body to
 * `/imports/schedule-e/extractions` and returns the new `job_id` plus the
 * `upload_url` the browser PUTs the bytes to via {@link uploadToPresignedUrl}.
 * A non-PDF content type is rejected by the backend as an {@link ApiError}
 * (400, Req 1.4); the UI also guards client-side first (Req 1.3).
 */
export function startExtraction(
  filename: string,
  contentType: string,
  signal?: AbortSignal,
): Promise<StartExtractionResponse> {
  return client.post<StartExtractionResponse>(
    "/imports/schedule-e/extractions",
    { body: { filename, content_type: contentType }, signal },
  );
}

/**
 * Begin extraction once the PDF bytes are uploaded. Targets
 * `POST /imports/schedule-e/extractions/{jobId}/start`, which confirms the
 * object is a PDF, starts the Textract job, and marks the job `processing`
 * (Req 2). A job/object outside the user's scope surfaces as an
 * {@link ApiError} (404).
 */
export function beginExtraction(
  jobId: string,
  signal?: AbortSignal,
): Promise<BeginExtractionResponse> {
  return client.post<BeginExtractionResponse>(
    `/imports/schedule-e/extractions/${encodeURIComponent(jobId)}/start`,
    { signal },
  );
}

/**
 * Poll a job's status. Targets `GET /imports/schedule-e/extractions/{jobId}`
 * and returns the {@link ExtractionJobView}. A failed / no-Schedule-E job is a
 * **successful** poll (HTTP 200) whose body carries `status: "failed"` /
 * `outcome: "no_schedule_e_found"` — the job ran; the outcome is just negative
 * (Req 3.4, 3.5). A job outside the user's scope surfaces as an
 * {@link ApiError} (404, Req 3.6).
 */
export function getExtraction(
  jobId: string,
  signal?: AbortSignal,
): Promise<ExtractionJobView> {
  return client.get<ExtractionJobView>(
    `/imports/schedule-e/extractions/${encodeURIComponent(jobId)}`,
    { signal },
  );
}
