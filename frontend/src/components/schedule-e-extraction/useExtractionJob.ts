import { useEffect, useRef, useState } from "react";
import {
  getExtraction as defaultGetExtraction,
  type CompleteOutcome,
  type ExtractionJobView,
  type JobStatus,
  type ReviewDraft,
} from "../../api/scheduleEExtraction";

/** Default poll cadence while a job is still running. */
export const DEFAULT_POLL_INTERVAL_MS = 2000;

/** The non-terminal statuses the poller keeps polling on. */
function isRunning(status: JobStatus): boolean {
  return status === "pending" || status === "processing";
}

/** The slice of {@link ExtractionJobView} the UI renders, plus a client error. */
export interface ExtractionJobState {
  /** Latest known job status, or null before the first successful poll. */
  status: JobStatus | null;
  /** Terminal outcome once `status === "complete"`. */
  outcome: CompleteOutcome | null;
  /** The pre-filled review draft when `outcome === "draft"`. */
  reviewDraft: ReviewDraft | null;
  /** Failure / no-Schedule-E message, when present. */
  message: string | null;
  /** Set when a poll itself failed (network/HTTP), distinct from a `failed` job. */
  error: string | null;
}

export interface UseExtractionJobOptions {
  /** Poll cadence in ms; overridable so tests can run it fast. */
  intervalMs?: number;
  /** Injected poll function; defaults to the real `getExtraction`. */
  getExtraction?: typeof defaultGetExtraction;
}

const INITIAL_STATE: ExtractionJobState = {
  status: null,
  outcome: null,
  reviewDraft: null,
  message: null,
  error: null,
};

function viewToState(view: ExtractionJobView): ExtractionJobState {
  return {
    status: view.status,
    outcome: view.outcome,
    reviewDraft: view.review_draft,
    message: view.message,
    error: null,
  };
}

/**
 * Job-status poller hook (task 11.3).
 *
 * Polls `getExtraction(jobId)` on `intervalMs` while the job status is in
 * `{pending, processing}` and **stops** the moment it observes a terminal
 * `complete` / `failed` status — a terminal poll schedules no further poll, so
 * no extra `getExtraction` calls happen once the job finishes (Req 3). Each
 * poll is made with an `AbortController` so an in-flight request is cancelled
 * on unmount or when `jobId` changes, and the pending timer is always cleared
 * on cleanup.
 *
 * Passing `null` for `jobId` keeps the hook inert (nothing polls) until a job
 * exists, so the parent can mount it unconditionally and simply flip `jobId`
 * once the upload control hands a job over.
 */
export function useExtractionJob(
  jobId: string | null,
  options: UseExtractionJobOptions = {},
): ExtractionJobState {
  const { intervalMs = DEFAULT_POLL_INTERVAL_MS } = options;
  const getExtraction = options.getExtraction ?? defaultGetExtraction;
  const [state, setState] = useState<ExtractionJobState>(INITIAL_STATE);

  // Keep the latest poll fn in a ref so changing it (tests) doesn't restart the
  // effect and the effect's dependency list stays limited to jobId/intervalMs.
  const getExtractionRef = useRef(getExtraction);
  getExtractionRef.current = getExtraction;

  useEffect(() => {
    if (jobId == null) {
      setState(INITIAL_STATE);
      return;
    }

    // Reset state for a freshly-handed-over job.
    setState(INITIAL_STATE);

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const poll = async () => {
      try {
        const view = await getExtractionRef.current(jobId, controller.signal);
        if (cancelled) return;
        setState(viewToState(view));
        // Only keep polling while the job is still running; a terminal state
        // schedules no further poll (Req 3.2–3.5).
        if (isRunning(view.status)) {
          timer = setTimeout(() => void poll(), intervalMs);
        }
      } catch {
        if (cancelled) return;
        setState((prev) => ({
          ...prev,
          error: "We couldn't check the extraction status. Please try again.",
        }));
        // Back off and retry on a transient error while still mounted.
        timer = setTimeout(() => void poll(), intervalMs);
      }
    };

    void poll();

    return () => {
      cancelled = true;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [jobId, intervalMs]);

  return state;
}
