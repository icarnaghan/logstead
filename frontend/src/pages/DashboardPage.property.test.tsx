import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { centsToMoney, formatMoney } from "../lib/money";
import { depreciationTrend } from "../components/charts/prepare";
import type { TrendsSeries, TrendYear } from "../api/dashboard";

/**
 * Property-based test for the DashboardPage trends view (task 9.3).
 *
 * The Depreciation_Summary_Tile derives from the Latest_Data_Year — the last
 * `TrendYear` of the series — and renders `formatMoney(year.depreciation_total)`
 * (see `DepreciationSummaryTile` in DashboardPage.tsx). The paired
 * Depreciation_Trend_Chart's last point renders
 * `formatMoney(centsToMoney(depreciationTrend(series).at(-1).cents))`, where the
 * datum's cents come from `toCents(year.depreciation_total)` inside
 * {@link depreciationTrend}.
 *
 * Property 13 (Requirements 12.1, 12.3, 12.4): the summary tile and the
 * depreciation trend's final point show the exact same dollar amount for any
 * series with at least one Data_Year.
 */

/**
 * Well-formed two-decimal money string `(-)?<digits>.<2 digits>` constrained to
 * the money model's input space — the shape of every `depreciation_total` on
 * the wire. Mirrors the `moneyString` generator in
 * `components/charts/prepare.property.test.ts`.
 */
const moneyString: fc.Arbitrary<string> = fc
  .tuple(
    fc.boolean(),
    fc.nat({ max: 99_999_999 }),
    fc.integer({ min: 0, max: 99 }),
  )
  .map(([negative, dollars, cents]) => {
    const sign = negative && (dollars > 0 || cents > 0) ? "-" : "";
    return `${sign}${dollars}.${String(cents).padStart(2, "0")}`;
  });

/**
 * A {@link TrendsSeries} with at least one Data_Year, each year carrying an
 * arbitrary two-decimal `depreciation_total`. Only `tax_year` and
 * `depreciation_total` matter for this property — the other figures are held at
 * a neutral "0.00" with no per-property points, since the summary tile and the
 * trend both read `depreciation_total` alone.
 */
const trendsSeries: fc.Arbitrary<TrendsSeries> = fc
  .array(
    fc.record({
      tax_year: fc.integer({ min: 2000, max: 2035 }),
      depreciation_total: moneyString,
    }),
    { minLength: 1, maxLength: 8 },
  )
  .map((entries): TrendsSeries => {
    const years: TrendYear[] = entries.map((e) => ({
      tax_year: e.tax_year,
      total_income: "0.00",
      total_expenses: "0.00",
      net: "0.00",
      properties: [],
      depreciation_total: e.depreciation_total,
    }));
    return { years };
  });

/**
 * The Depreciation_Summary_Tile's rendered figure: `formatMoney` over the
 * Latest_Data_Year's `depreciation_total`. Mirrors `DepreciationSummaryTile` in
 * DashboardPage.tsx verbatim.
 */
function summaryTileMoney(series: TrendsSeries): string {
  const latestYear = series.years[series.years.length - 1];
  return formatMoney(latestYear.depreciation_total);
}

/**
 * The Depreciation_Trend_Chart's last point's rendered figure:
 * `formatMoney(centsToMoney(cents))` over the final datum of
 * {@link depreciationTrend}. Mirrors the chart/table formatting boundary.
 */
function trendLastPointMoney(series: TrendsSeries): string {
  const data = depreciationTrend(series);
  const last = data[data.length - 1];
  return formatMoney(centsToMoney(last.cents));
}

// Feature: dashboard-year-over-year-trends, Property 13: Depreciation summary reconciles exactly with the depreciation trend's last point
describe("Property 13: Depreciation summary reconciles exactly with the depreciation trend's last point", () => {
  // Validates: Requirements 12.1, 12.3, 12.4
  it("summary tile money equals the depreciation trend's last-point money for any series", () => {
    fc.assert(
      fc.property(trendsSeries, (series) => {
        // The depreciation trend carries exactly one datum per Data_Year, so
        // its last point reconciles with the Latest_Data_Year the tile uses.
        expect(depreciationTrend(series)).toHaveLength(series.years.length);

        // Both render paths produce the exact same displayed dollar amount.
        expect(summaryTileMoney(series)).toBe(trendLastPointMoney(series));
      }),
      { numRuns: 100 },
    );
  });
});
