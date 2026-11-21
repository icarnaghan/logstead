import { useCallback, useEffect, useRef, useState } from "react";
import {
  accountantPackageApi,
  type AccountantPackageApi,
  type PackageJobView,
} from "../../api/accountantPackage";
import { isTerminal, POLL_INTERVAL_MS } from "../../lib/packageJob";

/** Consecutive failed polls tolerated; the third failure stops polling. */
export const MAX_POLL_FAILURES = 3;

export interface UsePackageJobOptions {
  /** Poll interval in ms; injectable so tests can run it fast. */
  intervalMs?: number;
  /** Injected API; defaults to the shared instance. */
  api?: Pick<
    AccountantPackageApi,
    "createPackage" | "listPackages" | "getPackage" | "deletePackage"
  >;
}

export interface PackageJobState {
  /** Latest known job (active, or the most recent finished one), else null. */
  job: PackageJobView | null;
  /** Message from the API or a failed job; null when there is none. */
  error: string | null;
  /** True while a create, delete, refresh, or the initial resume is running. */
  busy: boolean;
  /** Start a package job and poll it. */
  start: (taxYear: number, propertyIds?: string[]) => Promise<void>;
  /** Delete the current finished job. */
  remove: () => Promise<void>;
  /** Reload the current job, for example to get a fresh download link. */
  refresh: () => Promise<void>;
}

function messageOf(err: unknown): string {
  return err instanceof Error && err.message
    ? err.message
    : "Something went wrong. Please try again.";
}

/**
 * Package job hook. Resumes from `listPackages` on mount, polls
 * `getPackage` every interval while the job is queued or running, tolerates
 * two failed polls and stops on the third, and stops on a terminal status and
 * on unmount.
 */
export function usePackageJob(
  options: UsePackageJobOptions = {},
): PackageJobState {
  const { intervalMs = POLL_INTERVAL_MS } = options;
  const api = options.api ?? accountantPackageApi;
  const apiRef = useRef(api);
  apiRef.current = api;

  const [job, setJob] = useState<PackageJobView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const controller = useRef<AbortController | null>(null);
  const jobRef = useRef<PackageJobView | null>(null);
  // Bumped on every new polling run so stale loops stop themselves.
  const generation = useRef(0);

  const stopPolling = useCallback(() => {
    generation.current += 1;
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = undefined;
    controller.current?.abort();
    controller.current = null;
  }, []);

  const apply = useCallback((next: PackageJobView) => {
    jobRef.current = next;
    setJob(next);
    setError(next.status === "failed" ? (next.message ?? "Package failed.") : null);
  }, []);

  const poll = useCallback(
    (jobId: string) => {
      stopPolling();
      const gen = generation.current;
      const ctl = new AbortController();
      controller.current = ctl;
      let failures = 0;

      const tick = async () => {
        try {
          const next = await apiRef.current.getPackage(jobId, ctl.signal);
          if (gen !== generation.current) return;
          failures = 0;
          apply(next);
          if (!isTerminal(next.status)) {
            timer.current = setTimeout(() => void tick(), intervalMs);
          }
        } catch (err) {
          if (gen !== generation.current) return;
          failures += 1;
          if (failures >= MAX_POLL_FAILURES) {
            setError(messageOf(err));
            return;
          }
          timer.current = setTimeout(() => void tick(), intervalMs);
        }
      };

      timer.current = setTimeout(() => void tick(), intervalMs);
    },
    [apply, intervalMs, stopPolling],
  );

  // Resume on mount: poll an active job, or show the latest finished one.
  useEffect(() => {
    mounted.current = true;
    const ctl = new AbortController();
    void (async () => {
      try {
        const { jobs } = await apiRef.current.listPackages(ctl.signal);
        if (ctl.signal.aborted) return;
        const latest = jobs[0];
        if (latest) {
          apply(latest);
          if (!isTerminal(latest.status)) poll(latest.id);
        }
      } catch (err) {
        if (!ctl.signal.aborted) setError(messageOf(err));
      } finally {
        if (!ctl.signal.aborted) setBusy(false);
      }
    })();
    return () => {
      mounted.current = false;
      ctl.abort();
      stopPolling();
    };
  }, [apply, poll, stopPolling]);

  const start = useCallback(
    async (taxYear: number, propertyIds?: string[]) => {
      setBusy(true);
      setError(null);
      try {
        const created = await apiRef.current.createPackage(taxYear, propertyIds);
        if (!mounted.current) return;
        apply(created);
        if (!isTerminal(created.status)) poll(created.id);
      } catch (err) {
        if (mounted.current) setError(messageOf(err));
      } finally {
        if (mounted.current) setBusy(false);
      }
    },
    [apply, poll],
  );

  const refresh = useCallback(async () => {
    const current = jobRef.current;
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const next = await apiRef.current.getPackage(current.id);
      if (!mounted.current) return;
      apply(next);
      if (!isTerminal(next.status)) poll(next.id);
    } catch (err) {
      if (mounted.current) setError(messageOf(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [apply, poll]);

  const remove = useCallback(async () => {
    const current = jobRef.current;
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await apiRef.current.deletePackage(current.id);
      if (!mounted.current) return;
      stopPolling();
      jobRef.current = null;
      setJob(null);
    } catch (err) {
      if (mounted.current) setError(messageOf(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }, [stopPolling]);

  return { job, error, busy, start, remove, refresh };
}
