import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Opens an add flow once when the URL carries `new=1`, then removes the
 * parameter by replacing the history entry. Waits for `ready` (data loaded).
 */
export function useNewParam(open: () => void, ready: boolean): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("new") === "1";
  const handled = useRef(false);
  const openRef = useRef(open);
  openRef.current = open;

  useEffect(() => {
    if (!requested) {
      handled.current = false;
      return;
    }
    if (!ready || handled.current) return;
    handled.current = true;
    openRef.current();
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("new");
        return next;
      },
      { replace: true },
    );
  }, [requested, ready, setSearchParams]);
}
