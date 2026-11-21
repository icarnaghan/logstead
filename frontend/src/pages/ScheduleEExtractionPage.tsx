/**
 * Schedule E PDF Extraction page shell ("layer 2" — upload + auto-extract).
 *
 * This page is the "From PDF" tab of the Imports section: it is rendered
 * inside {@link ./ImportsLayout}, which owns the page heading and tab bar, so
 * the page itself renders no `<h1>`.
 *
 * The landing surface for importing a prior year's Schedule E from a tax-return
 * PDF instead of typing it. The flow this page will host (built in later tasks)
 * is: upload a PDF → the system locates the Schedule E Part I page(s) and
 * auto-extracts each property column's line amounts and address → the user
 * reviews, corrects, and confirms, and the existing layer-1 write path persists
 * the result. Extraction only proposes; the human confirms and layer 1 persists.
 *
 * This page is deliberately distinct from BOTH existing import pages so the
 * three experiences never collide:
 * - {@link ./ImportReviewPage} — the PDF *expense* import (per-property
 *   `/properties/:propertyId/import`), a separate shipping capability.
 * - {@link ./ScheduleEImportPage} — the layer-1 *manual* guided Schedule E
 *   form, mounted at `/imports/schedule-e`.
 *
 * This page mounts at the sibling path `/imports/schedule-e/extract`.
 *
 * The page owns the `jobId` so the upload control (11.2) can hand a started
 * job to the status poller (11.3). On a `complete`/`draft` job it mounts the
 * {@link ExtractionReview} screen (task 12.2) — the existing layer-1
 * `ScheduleEImportForm` seeded from the extracted draft — in place of the
 * status region's draft-ready placeholder. Every other state (running /
 * failed / no-Schedule-E) stays with {@link ExtractionStatus}, which keeps the
 * manual-form fallback link for the failure outcomes (task 12.5).
 */
import { useState } from "react";
import {
  ExtractionReview,
  ExtractionStatus,
  ExtractionUpload,
  useExtractionJob,
  type ExtractionUploadApi,
} from "../components/schedule-e-extraction";
import type { ImportOutcome, ImportSubmission } from "../api/scheduleEImport";
import type { Property } from "../api/properties";
import type { getExtraction as GetExtraction } from "../api/scheduleEExtraction";

export interface ScheduleEExtractionPageProps {
  /**
   * Poll cadence (ms) for the status poller, overridable so tests can run it
   * fast. Defaults to the hook's production cadence.
   */
  pollIntervalMs?: number;
  /**
   * Injected poll function forwarded to {@link useExtractionJob}. Defaults to
   * the real `getExtraction`; tests inject a fake to drive the page through its
   * states (running → review on draft, terminal-negative → status fallback)
   * without the network.
   */
  getExtraction?: typeof GetExtraction;
  /**
   * Test seams forwarded to the review screen's seeded {@link
   * ScheduleEImportForm} so tests can drive the confirm hand-off without the
   * network. Defaulted to the real layer-1 `importScheduleE` / `listProperties`
   * inside {@link ExtractionReview}, so production uses the unchanged write path
   * (Req 9.2).
   */
  review?: {
    submit?: (submission: ImportSubmission) => Promise<ImportOutcome>;
    loadProperties?: (signal?: AbortSignal) => Promise<Property[]>;
  };
  /**
   * Injected api seams forwarded to the {@link ExtractionUpload} control.
   * Defaulted to the real presign → PUT → begin functions; tests inject fakes
   * to drive a file selection without the network.
   */
  upload?: Partial<ExtractionUploadApi>;
}

export default function ScheduleEExtractionPage({
  pollIntervalMs,
  review,
  getExtraction,
  upload,
}: ScheduleEExtractionPageProps = {}) {
  // Lifted here so the upload control (11.2) can hand a started job to the
  // poller (11.3). Null until the first `beginExtraction` succeeds.
  const [jobId, setJobId] = useState<string | null>(null);
  const jobState = useExtractionJob(jobId, {
    intervalMs: pollIntervalMs,
    getExtraction,
  });

  // A terminal, draft-ready job: mount the seeded layer-1 review form in place
  // of the status region's "ready" placeholder (task 12.2). Every other state
  // (running / failed / no-Schedule-E) stays with ExtractionStatus, which keeps
  // the manual-form fallback link for the failure outcomes (task 12.5).
  const draftReady =
    jobState.status === "complete" &&
    jobState.outcome === "draft" &&
    jobState.reviewDraft != null;

  return (
    <div>
      <p className="text-fg-muted">
        Skip the typing: upload a PDF of just the Schedule E pages from a prior
        year's tax return and Logstead reads each property's line amounts and
        address for you. You then review the extracted values, correct anything
        that needs a second look, and confirm. Nothing is saved until you
        confirm, and the uploaded PDF is deleted as soon as extraction finishes.
      </p>

      <p
        role="note"
        className="mt-4 rounded-md bg-surface-muted px-3 py-2 text-sm text-fg-muted"
      >
        <strong>Upload only your Schedule E pages, not the whole return.</strong>{" "}
        In your tax software or PDF viewer, print or export just the Schedule E
        pages (usually 1–2) to a new PDF. Whole-return uploads are rejected, and
        reading a full return costs far more than reading the pages that matter.
      </p>

      <p
        role="note"
        className="mt-4 rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
      >
        Depreciation (Line 18) is never read or imported. An imported year shows
        $0 depreciation for a property until you add a depreciation schedule for
        that property and year.
      </p>

      {/*
        The file picker + upload control (11.2), then either the seeded review
        form on a draft job (12.2) or the status poller rendering (11.3 / the
        failed + no-Schedule-E manual-form fallback, 12.5).
      */}
      <div
        className="mt-6 space-y-4"
        data-testid="schedule-e-extraction-slot"
        aria-live="polite"
      >
        <ExtractionUpload onJobStarted={setJobId} api={upload} />
        {draftReady && jobState.reviewDraft != null ? (
          <ExtractionReview
            reviewDraft={jobState.reviewDraft}
            submit={review?.submit}
            loadProperties={review?.loadProperties}
          />
        ) : (
          <ExtractionStatus state={jobState} />
        )}
      </div>
    </div>
  );
}
