import { useState } from "react";

/**
 * Derived view state for a data load (Requirements 14.1, 14.2, 14.3, 14.5).
 *
 * The skeleton shows only before the first success. Once content has loaded
 * it stays mounted through refreshes and refresh errors.
 */
export interface LoadView {
  /** Never loaded and no error. */
  showSkeleton: boolean;
  /** Has loaded once; stays true on refresh and on refresh error. */
  showContent: boolean;
  /** Content shown while a new load is in flight. */
  refreshing: boolean;
  /** An error is present. */
  showError: boolean;
  /** An error is present while content is shown. */
  errorIsStale: boolean;
}

export interface LoadInput {
  hasLoaded: boolean;
  loading: boolean;
  error: string | null;
}

/** Pure derivation of the view state from the sticky `hasLoaded` flag. */
export function deriveLoadView({ hasLoaded, loading, error }: LoadInput): LoadView {
  const hasError = error !== null;
  return {
    showSkeleton: !hasLoaded && !hasError,
    showContent: hasLoaded,
    refreshing: hasLoaded && loading,
    showError: hasError,
    errorIsStale: hasError && hasLoaded,
  };
}

export interface UseFirstLoadInput {
  loading: boolean;
  error: string | null;
  /** When this value changes, the hook forgets that content has loaded. */
  resetKey?: unknown;
}

/**
 * Tracks whether a load has ever succeeded. `hasLoaded` becomes true the
 * first time `loading` is false and `error` is null, and resets when
 * `resetKey` changes. State is adjusted during render (no effect), so the
 * returned view is never a frame behind.
 */
export function useFirstLoad({ loading, error, resetKey }: UseFirstLoadInput): LoadView {
  const [hasLoadedState, setHasLoaded] = useState(false);
  const [prevKey, setPrevKey] = useState<unknown>(resetKey);

  let hasLoaded = hasLoadedState;

  if (!Object.is(prevKey, resetKey)) {
    setPrevKey(resetKey);
    setHasLoaded(false);
    hasLoaded = false;
  }

  if (!hasLoaded && !loading && error === null) {
    setHasLoaded(true);
    hasLoaded = true;
  }

  return deriveLoadView({ hasLoaded, loading, error });
}
