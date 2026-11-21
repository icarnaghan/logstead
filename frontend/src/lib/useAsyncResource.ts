import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Lifecycle of an async resource.
 *
 * - `idle`: disabled (`enabled: false`), or nothing to show yet.
 * - `loading`: a load is in flight and no data has ever arrived.
 * - `refreshing`: a load is in flight and prior data is still held.
 * - `success`: the last load succeeded.
 * - `error`: the last load failed (prior data, if any, is kept).
 */
export type AsyncResourceStatus =
  | "idle"
  | "loading"
  | "refreshing"
  | "success"
  | "error";

export interface UseAsyncResourceOptions {
  /**
   * When any of these change, held data is discarded and the resource loads
   * again from scratch (status goes back to `loading`). Typically a route id.
   */
  resetKeys?: readonly unknown[];
  /**
   * When any of these change, the resource loads again but keeps its prior
   * data meanwhile (status `refreshing`). Typically a filter or tax year.
   */
  deps?: readonly unknown[];
  /** When false nothing loads and any in-flight load is aborted. Default true. */
  enabled?: boolean;
  /** Maps a thrown value to the message stored in `error`. */
  describeError?: (error: unknown) => string;
}

export interface AsyncResource<T> {
  data: T | null;
  error: string | null;
  status: AsyncResourceStatus;
  /** Starts a new load, keeping prior data. Resolves once it settles. */
  reload: () => Promise<void>;
  /** Replaces the held data (optimistic updates, post-save results). */
  setData: (next: T | null | ((prev: T | null) => T | null)) => void;
}

interface State<T> {
  data: T | null;
  hasData: boolean;
  error: string | null;
  loading: boolean;
}

const DEFAULT_ERROR = "Something went wrong. Please try again.";

function defaultDescribe(): string {
  return DEFAULT_ERROR;
}

function sameKeys(a: readonly unknown[], b: readonly unknown[]): boolean {
  return a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

const NO_KEYS: readonly unknown[] = [];

/**
 * Loads one async resource with abort, stale-result protection, retry and
 * refresh built in.
 *
 * The loader runs on mount and whenever `resetKeys` or `deps` change. Each run
 * gets its own `AbortSignal`, aborted on unmount, on a key change and when a
 * newer load starts, so a slow earlier response can never overwrite a newer
 * one. Aborted loads and `AbortError` rejections are ignored, never surfaced as
 * errors. The latest `loader` is used without being a dependency, so passing an
 * inline function does not retrigger loading.
 *
 * Key changes are applied while rendering, so the returned status is never a
 * frame behind.
 *
 * @param loader fetches the resource; should honour `signal` when it can
 * @param options keys, enablement and error mapping
 */
export function useAsyncResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  options: UseAsyncResourceOptions = {},
): AsyncResource<T> {
  const {
    resetKeys = NO_KEYS,
    deps = NO_KEYS,
    enabled = true,
    describeError = defaultDescribe,
  } = options;

  const [state, setState] = useState<State<T>>({
    data: null,
    hasData: false,
    error: null,
    loading: enabled,
  });
  const [generation, setGeneration] = useState(0);
  const [tracked, setTracked] = useState({ resetKeys, deps, enabled });

  if (!sameKeys(tracked.resetKeys, resetKeys)) {
    setTracked({ resetKeys, deps, enabled });
    setState({ data: null, hasData: false, error: null, loading: enabled });
    setGeneration((g) => g + 1);
  } else if (!sameKeys(tracked.deps, deps) || tracked.enabled !== enabled) {
    setTracked({ resetKeys, deps, enabled });
    setState((s) => ({ ...s, error: null, loading: enabled }));
    setGeneration((g) => g + 1);
  }

  const loaderRef = useRef(loader);
  const describeRef = useRef(describeError);
  const waiters = useRef<Array<() => void>>([]);
  useEffect(() => {
    loaderRef.current = loader;
    describeRef.current = describeError;
  });

  const flushWaiters = useCallback(() => {
    const pending = waiters.current;
    waiters.current = [];
    for (const resolve of pending) resolve();
  }, []);

  // The in-flight load's controller; replaced (and the old one aborted) each
  // time a load starts.
  const controllerRef = useRef<AbortController | null>(null);

  // Starts a load immediately (not via an effect), so a `reload()` issues its
  // request in the same tick as the caller, like a hand-written fetch would.
  const start = useCallback(() => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const { signal } = controller;
    let promise: Promise<T>;
    try {
      promise = Promise.resolve(loaderRef.current(signal));
    } catch (err) {
      promise = Promise.reject(err);
    }
    promise
      .then((data) => {
        if (signal.aborted) return;
        setState({ data, hasData: true, error: null, loading: false });
        flushWaiters();
      })
      .catch((err: unknown) => {
        if (signal.aborted || isAbortError(err)) return;
        setState((s) => ({
          ...s,
          error: describeRef.current(err),
          loading: false,
        }));
        flushWaiters();
      });
  }, [flushWaiters]);

  // Key, enablement and unmount handling. Runs after the ref-sync effect above.
  useEffect(() => {
    if (!enabled) {
      flushWaiters();
      return;
    }
    start();
    return () => {
      controllerRef.current?.abort();
      controllerRef.current = null;
    };
  }, [generation, enabled, start, flushWaiters]);

  // Release anyone awaiting `reload()` if we unmount mid-load.
  useEffect(() => flushWaiters, [flushWaiters]);

  const reload = useCallback((): Promise<void> => {
    if (!enabled) return Promise.resolve();
    const done = new Promise<void>((resolve) => {
      waiters.current.push(resolve);
    });
    setState((s) => ({ ...s, error: null, loading: true }));
    start();
    return done;
  }, [enabled, start]);

  const setData = useCallback(
    (next: T | null | ((prev: T | null) => T | null)) => {
      setState((s) => {
        const value =
          typeof next === "function"
            ? (next as (prev: T | null) => T | null)(s.data)
            : next;
        return { ...s, data: value, hasData: s.hasData || value !== null };
      });
    },
    [],
  );

  let status: AsyncResourceStatus;
  if (!enabled) status = "idle";
  else if (state.loading) status = state.hasData ? "refreshing" : "loading";
  else if (state.error !== null) status = "error";
  else status = state.hasData ? "success" : "idle";

  return { data: state.data, error: state.error, status, reload, setData };
}

/** True while a load is in flight (first load or refresh). */
export function isAsyncLoading(status: AsyncResourceStatus): boolean {
  return status === "loading" || status === "refreshing";
}
