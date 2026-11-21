import { useCallback, useEffect, useRef, useState } from "react";
import {
  searchApi,
  type SearchGroup,
  type SearchOptions,
  type SearchResponse,
} from "../../api/search";

/** Pause in typing before a request is sent (Requirement 11.1). */
export const SEARCH_DEBOUNCE_MS = 250;
export const MIN_SEARCH_LENGTH = 2;
export const MAX_SEARCH_LENGTH = 100;
/** Hits requested per group in the palette (Requirement 5.5). */
export const PALETTE_HITS_PER_GROUP = 5;

export type SearchFn = (
  q: string,
  options?: SearchOptions,
) => Promise<SearchResponse>;

export type GlobalSearchStatus = "idle" | "loading" | "loaded" | "error";

export interface GlobalSearch {
  groups: readonly SearchGroup[];
  status: GlobalSearchStatus;
  truncated: boolean;
  /** The trimmed query the current `groups` belong to. */
  resultQuery: string;
  retry: () => void;
}

const defaultSearch: SearchFn = (q, options) => searchApi.search(q, options);

interface State {
  groups: readonly SearchGroup[];
  truncated: boolean;
  resultQuery: string;
  status: GlobalSearchStatus;
}

/** Guards against a malformed body: groups must be an array of groups with hit arrays. */
function isWellFormed(response: unknown): response is SearchResponse {
  if (typeof response !== "object" || response === null) return false;
  const groups = (response as { groups?: unknown }).groups;
  return (
    Array.isArray(groups) &&
    groups.every(
      (g) =>
        typeof g === "object" &&
        g !== null &&
        Array.isArray((g as { hits?: unknown }).hits),
    )
  );
}

const EMPTY: State = { groups: [], truncated: false, resultQuery: "", status: "idle" };

/**
 * Debounced global search for the palette. Sends nothing below 2 characters,
 * aborts the previous request when the query changes and keeps the previous
 * results while a request is in flight or after a failure.
 */
export function useGlobalSearch(
  query: string,
  search: SearchFn = defaultSearch,
  limit: number = PALETTE_HITS_PER_GROUP,
): GlobalSearch {
  const trimmed = query.trim().slice(0, MAX_SEARCH_LENGTH);
  const active = trimmed.length >= MIN_SEARCH_LENGTH;
  const [state, setState] = useState<State>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  const immediateRef = useRef(false);
  const searchRef = useRef(search);
  searchRef.current = search;
  const limitRef = useRef(limit);
  limitRef.current = limit;

  useEffect(() => {
    if (!active) {
      setState(EMPTY);
      return undefined;
    }
    const controller = new AbortController();
    const delay = immediateRef.current ? 0 : SEARCH_DEBOUNCE_MS;
    immediateRef.current = false;
    setState((prev) => ({ ...prev, status: "loading" }));
    const timer = setTimeout(() => {
      searchRef
        .current(trimmed, { limit: limitRef.current, signal: controller.signal })
        .then((response) => {
          if (controller.signal.aborted) return;
          if (!isWellFormed(response)) throw new Error("Malformed search response");
          setState({
            groups: response.groups,
            truncated: response.truncated === true,
            resultQuery: trimmed,
            status: "loaded",
          });
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          setState((prev) => ({ ...prev, status: "error" }));
        });
    }, delay);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [active, trimmed, attempt]);

  const retry = useCallback(() => {
    immediateRef.current = true;
    setAttempt((n) => n + 1);
  }, []);

  if (!active) return { ...EMPTY, retry };
  return { ...state, retry };
}
