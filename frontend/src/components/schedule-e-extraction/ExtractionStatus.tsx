import { Link } from "react-router-dom";
import type { ExtractionJobState } from "./useExtractionJob";

export interface ExtractionStatusProps {
  /** The poller state from {@link useExtractionJob}. */
  state: ExtractionJobState;
}

/**
 * Renders the Schedule E extraction job status (task 11.3).
 *
 * Four meaningful renderings, driven purely by the poller state:
 * - running (`pending` / `processing`) → a progress indicator in a status region.
 * - `failed` → the failure message plus a manual-form fallback link.
 * - `complete` + `no_schedule_e_found` → the distinct "No Schedule E found"
 *   message plus the manual-form fallback (Req 12.2 / Req 12.4).
 * - `complete` + `draft` → a placeholder "ready for review" region that passes
 *   the `reviewDraft` through. The actual review form is task 12.x and is NOT
 *   built here — this only indicates readiness.
 *
 * A client-side poll error (distinct from a `failed` job) is surfaced in a
 * `role="alert"` region.
 */
export function ExtractionStatus({ state }: ExtractionStatusProps) {
  const { status, outcome, reviewDraft, message, error } = state;

  // A terminal, draft-ready job: indicate readiness and hold the draft. The
  // review screen (task 12.x) mounts here later; we only expose readiness now.
  if (status === "complete" && outcome === "draft") {
    const columnCount = reviewDraft?.columns.length ?? 0;
    return (
      <div
        className="rounded-md border border-success-subtle bg-success-subtle px-4 py-3"
        data-testid="extraction-ready"
        data-column-count={columnCount}
      >
        <p role="status" className="text-sm font-medium text-success">
          Your Schedule E is ready for review.
        </p>
        <p className="mt-1 text-sm text-fg-muted">
          We read {columnCount} {columnCount === 1 ? "property" : "properties"}.
          Review and confirm the values on the next step.
        </p>
      </div>
    );
  }

  // Completed, but no Schedule E was located in the document.
  if (status === "complete" && outcome === "no_schedule_e_found") {
    return (
      <div className="space-y-2" data-testid="extraction-no-schedule-e">
        <p role="status" className="text-sm text-fg">
          {message ?? "No Schedule E was found in the uploaded document."}
        </p>
        <p className="text-sm text-fg-muted">
          You can still{" "}
          <Link
            to="/imports/schedule-e"
            className="font-medium text-accent underline hover:text-accent-hover"
          >
            enter your Schedule E manually
          </Link>
          .
        </p>
      </div>
    );
  }

  // The job ran but could not be read.
  if (status === "failed") {
    return (
      <div className="space-y-2" data-testid="extraction-failed">
        <p role="alert" className="text-sm text-danger">
          {message ?? "The document could not be read; a valid PDF is required."}
        </p>
        <p className="text-sm text-fg-muted">
          You can{" "}
          <Link
            to="/imports/schedule-e"
            className="font-medium text-accent underline hover:text-accent-hover"
          >
            enter your Schedule E manually
          </Link>{" "}
          instead.
        </p>
      </div>
    );
  }

  // Still running (pending / processing) — show progress.
  if (status === "pending" || status === "processing") {
    return (
      <p role="status" className="text-sm text-fg-subtle">
        Reading your document… this can take a moment.
      </p>
    );
  }

  // No job yet, but a poll error occurred (e.g. transient network failure).
  if (error) {
    return (
      <p role="alert" className="text-sm text-danger">
        {error}
      </p>
    );
  }

  // No job in flight yet.
  return null;
}

export default ExtractionStatus;
