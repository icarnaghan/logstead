import type { PackageJobView } from "../../api/accountantPackage";
import {
  formatBytes,
  isTerminal,
  linkMinutes,
  statusLabel,
} from "../../lib/packageJob";
import { cn } from "../../lib/cn";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FOCUS_RING } from "../ui/focusRing";

export interface PackageStatusPanelProps {
  /** The current job, or null when none exists. */
  job: PackageJobView | null;
  /** Called when the user asks to delete a finished package. */
  onDelete: () => void;
  deleting?: boolean;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="break-all text-fg">{value}</dd>
    </div>
  );
}

function CompleteDetails({ job }: { job: PackageJobView }) {
  const skipped = job.skipped_receipt_count ?? 0;
  return (
    <div className="mt-3 space-y-3">
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        {job.size_bytes !== null && (
          <Detail label="File size" value={formatBytes(job.size_bytes)} />
        )}
        {job.file_count !== null && (
          <Detail label="Files" value={String(job.file_count)} />
        )}
        {job.receipt_count !== null && (
          <Detail label="Receipts" value={String(job.receipt_count)} />
        )}
        {job.sha256 && <Detail label="SHA-256 checksum" value={job.sha256} />}
      </dl>
      {skipped > 0 && (
        <p className="text-sm text-fg-muted">
          {skipped} {skipped === 1 ? "receipt was" : "receipts were"} left out.
          See manifest.json in the package for which ones and why.
        </p>
      )}
      {job.download_url && (
        <p className="flex flex-wrap items-center gap-3 text-sm">
          <a
            href={job.download_url}
            className={cn(
              "inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 font-medium text-accent-fg hover:bg-accent-hover max-md:min-h-11",
              FOCUS_RING,
            )}
          >
            Download package
          </a>
          {job.download_expires_in_seconds !== null && (
            <span className="text-fg-muted">
              The link works for {linkMinutes(job.download_expires_in_seconds)}{" "}
              {linkMinutes(job.download_expires_in_seconds) === 1
                ? "minute"
                : "minutes"}
              .
            </span>
          )}
        </p>
      )}
    </div>
  );
}

/**
 * Progress, completion details, and the delete action for one package job.
 * Progress and completion text sit in a polite live region. Nothing moves
 * focus. Status is always shown as text.
 */
export function PackageStatusPanel({
  job,
  onDelete,
  deleting = false,
}: PackageStatusPanelProps) {
  return (
    <Card as="section" aria-label="Package status" className="p-card">
      <div role="status" aria-live="polite">
        {job === null ? (
          <p className="text-sm text-fg-muted">No package prepared yet.</p>
        ) : (
          <p className="text-sm font-medium text-fg">
            {statusLabel(job.status)} for tax year {job.tax_year}
            {!isTerminal(job.status) && "…"}
          </p>
        )}
      </div>
      {job?.status === "complete" && <CompleteDetails job={job} />}
      {job && isTerminal(job.status) && (
        <div className="mt-3">
          <Button variant="danger" size="sm" loading={deleting} onClick={onDelete}>
            Delete package
          </Button>
        </div>
      )}
    </Card>
  );
}
