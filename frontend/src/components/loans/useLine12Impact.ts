import { useCallback, useEffect, useRef, useState } from "react";

import * as loansApiDefault from "../../api/loans";
import type { Line12ImpactYear } from "../../api/loans";

/** The subset of the loans API module the hook uses (test seam). */
export type Line12ImpactApi = Pick<typeof loansApiDefault, "getLine12Impact">;

export interface UseLine12ImpactResult {
  /** Per-year impact entries; empty while loading or after a failed load. */
  impact: Line12ImpactYear[];
  /** True when the last load failed, so the notice area should be hidden. */
  failed: boolean;
  /** Reload after a Loan create, update or delete. */
  refresh: () => Promise<void>;
}

/**
 * Loads the Line 12 impact once per property and again whenever `refresh` is
 * called (after Loan changes). A failed load yields an empty list and
 * `failed = true` and never throws, so the notice area is hidden without
 * blocking the page (Requirement 9.17).
 */
export function useLine12Impact(
  propertyId: string | undefined,
  api: Line12ImpactApi = loansApiDefault,
): UseLine12ImpactResult {
  const [impact, setImpact] = useState<Line12ImpactYear[]>([]);
  const [failed, setFailed] = useState(false);

  const apiRef = useRef(api);
  apiRef.current = api;
  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    const id = ++requestId.current;
    if (!propertyId) {
      setImpact([]);
      setFailed(false);
      return;
    }
    try {
      const result = await apiRef.current.getLine12Impact(propertyId);
      if (id === requestId.current) {
        setImpact(result);
        setFailed(false);
      }
    } catch {
      if (id === requestId.current) {
        setImpact([]);
        setFailed(true);
      }
    }
  }, [propertyId]);

  useEffect(() => {
    setImpact([]);
    setFailed(false);
    void refresh();
    return () => {
      // requestId is a request counter, not a DOM ref: we want the latest value
      // so in-flight responses from this effect are discarded.
      // eslint-disable-next-line react-hooks/exhaustive-deps
      requestId.current++;
    };
  }, [refresh]);

  return { impact, failed, refresh };
}
