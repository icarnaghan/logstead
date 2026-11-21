import { useEffect, useMemo, useState } from "react";

import { getEarliestDataYear } from "../api/properties";
import { latestCompletedTaxYear, taxYearRange } from "./taxYears";

/** Minimal asset shape needed to derive the range (in-service date only). */
interface AssetLike {
  /** ISO date (YYYY-MM-DD) the asset was placed in service. */
  readonly placed_in_service_date: string;
}

/** Loader for the earliest year with recorded activity (null when none). */
type EarliestYearLoader = (
  propertyId: string,
  signal?: AbortSignal,
) => Promise<number | null>;

/**
 * Selectable tax years for a property, newest first.
 *
 * The range runs from the property's earliest activity (earliest transaction
 * or asset in-service year) up to the latest completed tax year. The earliest
 * data year is fetched once per `propertyId`; any failure is treated as "no
 * data" so the range degrades to the assets-only / recent-years fallback and
 * the page stays usable. A response arriving after the property changes or
 * the component unmounts is ignored.
 *
 * @param propertyId the property to load, or undefined before it is known
 * @param assets the property's depreciable assets (only the in-service date is read)
 * @param load injectable loader (test seam); defaults to {@link getEarliestDataYear}
 */
export function usePropertyYearRange(
  propertyId: string | undefined,
  assets: readonly AssetLike[],
  load: EarliestYearLoader = getEarliestDataYear,
): number[] {
  const [earliest, setEarliest] = useState<number | null>(null);

  useEffect(() => {
    setEarliest(null);
    if (!propertyId) return;
    let active = true;
    const controller = new AbortController();
    load(propertyId, controller.signal)
      .then((year) => {
        if (active) setEarliest(year);
      })
      .catch(() => {
        if (active) setEarliest(null);
      });
    return () => {
      active = false;
      controller.abort();
    };
    // `load` is intentionally omitted: fetch once per property, not per
    // loader identity (callers may pass an inline function).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propertyId]);

  return useMemo(
    () => taxYearRange(assets, latestCompletedTaxYear(), 6, earliest),
    [assets, earliest],
  );
}
