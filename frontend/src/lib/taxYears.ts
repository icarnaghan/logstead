/**
 * Shared tax-year range helpers.
 *
 * A property's selectable tax years run from the earliest year it had activity
 * — the earliest of the depreciable-asset placed-in-service years and an
 * optional caller-supplied earliest data year (e.g. earliest recorded
 * expense/income) — up to the
 * **latest completed** tax year (the prior calendar year). The current year is
 * never selectable because its return cannot be filed yet.
 *
 * Callers pass the ceiling explicitly via {@link latestCompletedTaxYear}. A
 * {@link currentTaxYear} ceiling is still exported for any future
 * current-year-inclusive context, but no caller uses it today.
 */

interface AssetLike {
  /** ISO date (YYYY-MM-DD) the asset was placed in service. */
  readonly placed_in_service_date: string;
}

/** The current calendar year. */
export function currentTaxYear(): number {
  return new Date().getFullYear();
}

/** The latest *completed* tax year — the prior calendar year (cannot-file cap). */
export function latestCompletedTaxYear(): number {
  return currentTaxYear() - 1;
}

/**
 * Build the selectable tax years, newest first, from the earliest depreciable
 * asset's placed-in-service year through `latest` (inclusive).
 *
 * When the property has no assets yet, falls back to a recent-years window of
 * `fallbackCount` years ending at `latest`, so the selector is never empty. A
 * future-dated (or otherwise out-of-range) in-service year is clamped so the
 * range never starts after `latest`.
 *
 * @param assets the property's depreciable assets (only the in-service date is read)
 * @param latest the inclusive top of the range (e.g. `currentTaxYear()` for
 *   data-entry views, `latestCompletedTaxYear()` for filing views)
 * @param fallbackCount how many recent years to offer when there are no assets
 * @param earliestDataYear optional earliest year with recorded data (e.g. the
 *   earliest expense/income year); when an integer >= 1900 it can extend the
 *   range further back. `null` (default) ignores it.
 */
export function taxYearRange(
  assets: readonly AssetLike[],
  latest: number,
  fallbackCount = 6,
  earliestDataYear: number | null = null,
): number[] {
  let earliest = latest - (fallbackCount - 1);
  for (const asset of assets) {
    const year = Number(asset.placed_in_service_date?.slice(0, 4));
    if (Number.isFinite(year) && year >= 1900 && year < earliest) {
      earliest = year;
    }
  }
  if (
    earliestDataYear !== null &&
    Number.isInteger(earliestDataYear) &&
    earliestDataYear >= 1900 &&
    earliestDataYear < earliest
  ) {
    earliest = earliestDataYear;
  }
  // Never start after the latest selectable year (guards a future in-service date).
  earliest = Math.min(earliest, latest);
  const span = Math.max(latest - earliest + 1, 1);
  return Array.from({ length: span }, (_, index) => latest - index);
}

/**
 * Parse a `?year=` query value. Returns the integer only for a canonical
 * decimal string (no sign, padding, whitespace or decimals) from 1900 through
 * 2200; otherwise `null`.
 */
export function parseYearParam(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !/^[1-9]\d{3}$/.test(value)) {
    return null;
  }
  const year = Number(value);
  return year >= 1900 && year <= 2200 ? year : null;
}
