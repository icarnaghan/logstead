import { useEffect, useMemo, useState } from "react";

import {
  getEarliestDataYear,
  listProperties,
  type Property,
} from "../api/properties";
import { latestCompletedTaxYear, taxYearRange } from "./taxYears";

/** Loads the user's properties (test seam; defaults to {@link listProperties}). */
type PropertiesLoader = (signal?: AbortSignal) => Promise<readonly Property[]>;

/** Loads one property's earliest activity year (null when it has none). */
type EarliestYearLoader = (
  propertyId: string,
  signal?: AbortSignal,
) => Promise<number | null>;

/**
 * Selectable tax years for the whole portfolio, newest first.
 *
 * The range runs from the earliest activity year across every property the
 * user owns (earliest transaction or asset in-service year) up to the latest
 * completed tax year. The properties and their earliest years are fetched once
 * on mount. A property whose lookup fails is skipped, and if the property list
 * itself fails the range degrades to the recent-years window, so the page stays
 * usable. A response arriving after unmount is ignored.
 *
 * @param loadProperties injectable properties loader (test seam)
 * @param loadEarliest injectable per-property earliest-year loader (test seam)
 */
export function usePortfolioYearRange(
  loadProperties: PropertiesLoader = listProperties,
  loadEarliest: EarliestYearLoader = getEarliestDataYear,
): number[] {
  const [earliest, setEarliest] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    (async () => {
      const properties = await loadProperties(controller.signal);
      const years = await Promise.all(
        properties.map((property) =>
          loadEarliest(property.id, controller.signal).catch(() => null),
        ),
      );
      const known = years.filter((y): y is number => y !== null);
      if (active) setEarliest(known.length > 0 ? Math.min(...known) : null);
    })().catch(() => {
      if (active) setEarliest(null);
    });
    return () => {
      active = false;
      controller.abort();
    };
    // Fetch once on mount; the loaders are test seams, not reactive inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return useMemo(
    () => taxYearRange([], latestCompletedTaxYear(), 6, earliest),
    [earliest],
  );
}
