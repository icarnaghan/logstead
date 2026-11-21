/** Pure helpers for the accountant package job (queued, running, complete, failed). */

export type PackageJobStatus = 'queued' | 'running' | 'complete' | 'failed'

/** Poll interval for an active package job (Requirement 17.5). */
export const POLL_INTERVAL_MS = 3000

/** True once a job can no longer change status. */
export function isTerminal(status: PackageJobStatus): boolean {
  return status === 'complete' || status === 'failed'
}

const STATUS_LABELS: Record<PackageJobStatus, string> = {
  queued: 'Waiting to start',
  running: 'Preparing your package',
  complete: 'Package ready',
  failed: 'Package failed',
}

/** Plain-language label for a job status. */
export function statusLabel(status: PackageJobStatus): string {
  return STATUS_LABELS[status] ?? 'Unknown status'
}

/** Formats a byte count with binary units, for example `1.5 MB`. */
export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '0 B'
  if (n < 1024) return `${Math.floor(n)} B`
  const units = ['KB', 'MB', 'GB']
  let value = n / 1024
  let i = 0
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024
    i += 1
  }
  return `${value.toFixed(1)} ${units[i]}`
}

/** Whole minutes a download link stays valid, rounded up and at least 1. */
export function linkMinutes(seconds: number): number {
  if (!Number.isFinite(seconds) || seconds <= 0) return 1
  return Math.max(1, Math.ceil(seconds / 60))
}

/** Starts a browser download. Thin wrapper so tests can stub it. */
export function startDownload(url: string): void {
  window.location.assign(url)
}
