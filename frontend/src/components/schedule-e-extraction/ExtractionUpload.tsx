import { useCallback, useId, useState } from "react";
import {
  beginExtraction as defaultBeginExtraction,
  startExtraction as defaultStartExtraction,
  uploadToPresignedUrl as defaultUploadToPresignedUrl,
} from "../../api/scheduleEExtraction";

/** The one content type the backend binds for Schedule E extraction uploads. */
export const PDF_CONTENT_TYPE = "application/pdf";

/**
 * The most pages an upload may have. Mirrors the backend's `MAX_UPLOAD_PAGES`
 * (`services/schedule_e_extraction.py`), which rejects anything larger before
 * Textract runs. Schedule E itself is 1-2 pages; Textract bills per page, so
 * uploading a whole ~50-page return is what makes extraction expensive.
 */
export const MAX_UPLOAD_PAGES = 5;

/**
 * True when `file` is a PDF the backend will accept. Mirrors the backend's
 * `application/pdf` binding (Req 1.3, 1.4): we trust the browser-reported MIME
 * type, and also accept a `.pdf` extension as a fallback for browsers/OSes that
 * leave `file.type` empty.
 */
export function isPdfFile(file: File): boolean {
  if (file.type === PDF_CONTENT_TYPE) return true;
  // Some environments report an empty type; fall back to the extension so a
  // genuine PDF is not rejected. A wrong non-empty type is still rejected.
  return file.type === "" && /\.pdf$/i.test(file.name);
}

/**
 * The three api functions this component drives, injectable so RTL tests run
 * the real presign → PUT → begin ordering without touching the network. They
 * default to the real `api/scheduleEExtraction` functions.
 */
export interface ExtractionUploadApi {
  startExtraction: typeof defaultStartExtraction;
  uploadToPresignedUrl: typeof defaultUploadToPresignedUrl;
  beginExtraction: typeof defaultBeginExtraction;
}

const DEFAULT_API: ExtractionUploadApi = {
  startExtraction: defaultStartExtraction,
  uploadToPresignedUrl: defaultUploadToPresignedUrl,
  beginExtraction: defaultBeginExtraction,
};

export interface ExtractionUploadProps {
  /**
   * Called with the new `job_id` once `beginExtraction` succeeds, so the parent
   * page can hand the job to the status poller. The upload control itself owns
   * no polling.
   */
  onJobStarted: (jobId: string) => void;
  /** Injected api seams; defaults to the real functions. */
  api?: Partial<ExtractionUploadApi>;
}

type Phase =
  | { kind: "idle" }
  | { kind: "requesting" }
  | { kind: "uploading" }
  | { kind: "starting" };

/**
 * Phase → human-readable progress copy announced in the status region.
 */
const PHASE_MESSAGE: Record<Exclude<Phase["kind"], "idle">, string> = {
  requesting: "Requesting a secure upload link…",
  uploading: "Uploading your PDF…",
  starting: "Starting extraction…",
};

/**
 * File picker + presign → PUT → begin control for Schedule E PDF extraction
 * (task 11.2).
 *
 * The flow on a valid PDF is: `startExtraction(file.name, "application/pdf")`
 * → `uploadToPresignedUrl(upload_url, file)` (the reused photos helper) →
 * `beginExtraction(job_id)`, then `onJobStarted(job_id)` hands the job to the
 * parent's poller.
 *
 * Non-PDF files are rejected client-side **before** any URL is requested
 * (mirroring the photos content-type guard, matching the backend binding —
 * Req 1.3, 1.4). Progress is announced in a `role="status"` region and errors
 * in a `role="alert"` region so the flow is accessible.
 */
export function ExtractionUpload({ onJobStarted, api }: ExtractionUploadProps) {
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [error, setError] = useState<string | null>(null);

  const fieldId = useId();
  const errorId = `${fieldId}-error`;
  const statusId = `${fieldId}-status`;
  const hintId = `${fieldId}-hint`;

  const busy = phase.kind !== "idle";

  const handleFileChange = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      // Clear the native input so re-selecting the same file re-fires onChange.
      event.target.value = "";
      if (!file) return;

      setError(null);

      // Client-side guard BEFORE requesting a URL (Req 1.3, 1.4).
      if (!isPdfFile(file)) {
        setError(
          `"${file.name}" is not a PDF. Upload a PDF (.pdf) containing just your Schedule E pages.`,
        );
        return;
      }

      const resolved: ExtractionUploadApi = { ...DEFAULT_API, ...api };
      try {
        setPhase({ kind: "requesting" });
        const started = await resolved.startExtraction(
          file.name,
          PDF_CONTENT_TYPE,
        );

        setPhase({ kind: "uploading" });
        await resolved.uploadToPresignedUrl(started.upload_url, file);

        setPhase({ kind: "starting" });
        const begun = await resolved.beginExtraction(started.job_id);

        setPhase({ kind: "idle" });
        onJobStarted(begun.job_id);
      } catch {
        setPhase({ kind: "idle" });
        setError(
          `We couldn't start extraction for "${file.name}". Please try again.`,
        );
      }
    },
    [onJobStarted, api],
  );

  return (
    <div className="space-y-2">
      <label
        htmlFor={fieldId}
        className="block text-sm font-medium text-fg-muted"
      >
        Choose your Schedule E pages (PDF)
      </label>
      <p id={hintId} className="text-sm text-fg-subtle">
        Upload <strong>only your Schedule E pages</strong> (usually 1–2 pages),
        not your whole tax return. Print or export just those pages to a new PDF
        first. Uploads longer than {MAX_UPLOAD_PAGES} pages are rejected.
      </p>
      <input
        id={fieldId}
        type="file"
        accept="application/pdf,.pdf"
        disabled={busy}
        onChange={handleFileChange}
        aria-describedby={
          error ? `${hintId} ${errorId}` : busy ? `${hintId} ${statusId}` : hintId
        }
        className="block w-full text-sm text-fg-muted file:mr-4 file:rounded-md file:border-0 file:bg-accent file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-accent-fg hover:file:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
      />

      {busy && (
        <p id={statusId} role="status" className="text-sm text-fg-subtle">
          {PHASE_MESSAGE[phase.kind]}
        </p>
      )}

      {error && (
        <p id={errorId} role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export default ExtractionUpload;
