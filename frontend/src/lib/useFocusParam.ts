import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

/** Default selector: the row id convention `row-{id}`. */
export const rowSelector = (id: string): string => `[id="row-${id}"]`;

/**
 * Scrolls to and focuses the record named by the `focus` query parameter,
 * once. Waits for `ready`; an id not in `rows` is ignored. The parameter stays
 * in the URL.
 */
export function useFocusParam(
  rows: readonly { id: string }[],
  ready: boolean,
  selector: (id: string) => string = rowSelector,
): void {
  const [searchParams] = useSearchParams();
  const focusId = searchParams.get("focus");
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (!focusId) {
      handled.current = null;
      return;
    }
    if (!ready || handled.current === focusId) return;
    if (!rows.some((row) => row.id === focusId)) return;
    const element = document.querySelector<HTMLElement>(selector(focusId));
    if (!element) return;
    handled.current = focusId;
    const reduced =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    element.scrollIntoView?.({
      block: "center",
      behavior: reduced ? "auto" : "smooth",
    });
    element.focus();
  }, [focusId, ready, rows, selector]);
}
