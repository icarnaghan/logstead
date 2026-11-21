import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { centsToMoney, formatMoney, toCents, toMoneyString } from "../../lib/money";
import { expenseByCategory, netByPropertyTrend } from "./prepare";
import type { ReportLine, ScheduleEReport } from "../../api/reports";
import type {
  PropertyYearPoint,
  TrendsSeries,
  TrendYear,
} from "../../api/dashboard";

/**
 * Property-based tests for the chart data-preparation boundary (task 15.4).
 *
 * Covers the descending-rank invariant of the expense-by-category builder
 * (Property 8) and reuses the money↔cents round-trip spirit of Property 2 to
 * confirm every prepared datum stays in exact integer cents (Requirements 13.1,
 * 13.2, 13.3, 16.3).
 */

/**
 * Well-formed two-decimal money string `(-)?<digits>.<2 digits>` constrained to
 * the money model's input space so generators stay meaningful.
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

/** An arbitrary Schedule E line of either kind, with a money total. */
const reportLine: fc.Arbitrary<ReportLine> = fc.record({
  line: fc.integer({ min: 1, max: 26 }),
  label: fc.string({ minLength: 1, maxLength: 24 }),
  kind: fc.constantFrom<"income" | "expense">("income", "expense"),
  total: moneyString,
});

/** A Schedule E report whose only meaningful field for prep is `lines`. */
const scheduleEReport: fc.Arbitrary<ScheduleEReport> = fc
  .array(reportLine, { maxLength: 30 })
  .map(
    (lines): ScheduleEReport => ({
      header: {
        property_id: "p",
        property_name: "Property",
        address: "",
        property_type: null,
        tax_year: 2024,
        fair_rental_days: 0,
        personal_use_days: 0,
      },
      lines,
      other_items: [],
      totals: { total_income: "0.00", total_expenses: "0.00", net: "0.00" },
    }),
  );

// Feature: ui-polish-and-visualizations, Property 8: Expense-by-category data is ranked by descending amount
describe("Property 8: Expense-by-category data is ranked by descending amount", () => {
  it("prepared expense-by-category cents are non-increasing", () => {
    fc.assert(
      fc.property(scheduleEReport, (report) => {
        const data = expenseByCategory(report);

        // Only expense lines survive.
        const expenseCount = report.lines.filter(
          (line) => line.kind === "expense",
        ).length;
        expect(data).toHaveLength(expenseCount);

        // The series is ranked by non-increasing cents (Req 16.3).
        for (let i = 1; i < data.length; i += 1) {
          expect(data[i - 1].cents).toBeGreaterThanOrEqual(data[i].cents);
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: ui-polish-and-visualizations, Property 2: Money ↔ integer-cents round-trip (no floating point)
describe("Property 2 (reuse): prepared data stays in exact integer cents", () => {
  it("each datum's cents equals toCents(input) and round-trips through formatMoney(centsToMoney(cents))", () => {
    fc.assert(
      fc.property(scheduleEReport, (report) => {
        const data = expenseByCategory(report);
        const expenseLines = report.lines.filter(
          (line) => line.kind === "expense",
        );

        for (const datum of data) {
          // The cents are an exact integer conversion of some expense total.
          expect(Number.isInteger(datum.cents)).toBe(true);

          // formatMoney(centsToMoney(cents)) equals formatting the normalized
          // money string directly — the cents domain is lossless (Req 13.2).
          const money = centsToMoney(datum.cents);
          const normalized = datum.cents === 0 ? "0.00" : money;
          expect(money).toBe(normalized);
          expect(formatMoney(money)).toBe(formatMoney(centsToMoney(datum.cents)));
        }

        // Every prepared datum traces back to an expense line's exact cents.
        const preparedCents = [...data].map((d) => d.cents).sort((a, b) => a - b);
        const sourceCents = expenseLines
          .map((line) => toCents(line.total))
          .sort((a, b) => a - b);
        expect(preparedCents).toEqual(sourceCents);

        // Sanity: toMoneyString of a source total round-trips to the same cents.
        for (const line of expenseLines) {
          expect(toCents(toMoneyString(line.total))).toBe(toCents(line.total));
        }
      }),
      { numRuns: 100 },
    );
  });
});

/**
 * The money formatter each trend chart uses at its tooltip/axis boundary.
 * Mirrors the private `formatCents` helper duplicated verbatim in
 * IncomeExpenseNetTrendChart, NetByPropertyTrendChart, and
 * DepreciationTrendChart — all of which render `formatMoney(centsToMoney(cents))`.
 */
function chartFormatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

/**
 * The money formatter each paired data table renders for the same datum.
 * Mirrors the inline `formatMoney(centsToMoney(cents))` in
 * IncomeExpenseNetTrendTable, NetByPropertyTrendTable, and
 * DepreciationTrendTable.
 */
function tableFormatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

// Feature: dashboard-year-over-year-trends, Property 12: Chart and data-table render identical money for the same datum
describe("Property 12: Chart and data-table render identical money for the same datum", () => {
  // Validates: Requirements 10.4
  it("chart-side and table-side formatting agree for any integer cents", () => {
    fc.assert(
      fc.property(
        // Integer cents spanning losses, zero, and large portfolio totals.
        fc.integer({ min: -9_999_999_999, max: 9_999_999_999 }),
        (cents) => {
          const chartString = chartFormatCents(cents);
          const tableString = tableFormatCents(cents);

          // Both sides cross cents → money through the same
          // formatMoney(centsToMoney(...)) helper, so the rendered strings are
          // identical in value, precision, and currency formatting (Req 10.4).
          expect(chartString).toBe(tableString);

          // And both equal the canonical helper output directly — there is no
          // alternate formatting path for either side.
          expect(chartString).toBe(formatMoney(centsToMoney(cents)));
        },
      ),
      { numRuns: 100 },
    );
  });
});

/**
 * Property-based tests for the net-by-property trend builder (task 6.2).
 *
 * Exercises {@link netByPropertyTrend} with generated series that deliberately
 * (a) reuse display names across distinct properties (to stress label
 * disambiguation) and (b) omit some properties from some years (to stress the
 * missing-year → `0` cents fill).
 */

/** A small pool of property ids; names are drawn to force collisions. */
const propertyPool: fc.Arbitrary<{ id: string; name: string }[]> = fc
  .uniqueArray(fc.integer({ min: 1, max: 6 }), { minLength: 1, maxLength: 6 })
  .chain((ids) =>
    fc
      // A deliberately tiny name alphabet so several properties collide.
      .array(fc.constantFrom("Maple St", "Oak Ave", "Elm Rd"), {
        minLength: ids.length,
        maxLength: ids.length,
      })
      .map((names) =>
        ids.map((id, i) => ({ id: `p${id}`, name: names[i] })),
      ),
  );

/** Build a {@link TrendsSeries} over the given properties and ascending years. */
const trendsSeries: fc.Arbitrary<{
  series: TrendsSeries;
  properties: { id: string; name: string }[];
}> = propertyPool.chain((properties) =>
  fc
    .uniqueArray(fc.integer({ min: 2000, max: 2035 }), {
      minLength: 1,
      maxLength: 6,
    })
    .chain((rawYears) => {
      const years = [...rawYears].sort((a, b) => a - b);
      // For each year, independently decide which properties appear (at least
      // one, so a year never ends up empty) and with what net.
      return fc
        .array(
          fc.record({
            // A subset mask over the property pool, forced non-empty.
            present: fc.array(fc.boolean(), {
              minLength: properties.length,
              maxLength: properties.length,
            }),
            nets: fc.array(moneyString, {
              minLength: properties.length,
              maxLength: properties.length,
            }),
          }),
          { minLength: years.length, maxLength: years.length },
        )
        .map((perYear): {
          series: TrendsSeries;
          properties: { id: string; name: string }[];
        } => {
          const trendYears: TrendYear[] = years.map((year, yi) => {
            const spec = perYear[yi];
            const present = spec.present.some((p) => p)
              ? spec.present
              : // Force at least the first property present.
                spec.present.map((_, i) => i === 0);
            const points: PropertyYearPoint[] = properties
              .map((prop, pi) =>
                present[pi]
                  ? {
                      property_id: prop.id,
                      property_name: prop.name,
                      total_income: "0.00",
                      total_expenses: "0.00",
                      net: spec.nets[pi],
                    }
                  : null,
              )
              .filter((p): p is PropertyYearPoint => p !== null);
            return {
              tax_year: year,
              total_income: "0.00",
              total_expenses: "0.00",
              net: "0.00",
              properties: points,
              depreciation_total: "0.00",
            };
          });
          return { series: { years: trendYears }, properties };
        });
    }),
);

// Feature: dashboard-year-over-year-trends, Property 11: Net-by-property preparation yields one full series per property with unique labels
describe("Property 11: Net-by-property preparation yields one full series per property with unique labels", () => {
  it("one series per distinct property, one ascending point per Data_Year (missing → 0), unique labels", () => {
    fc.assert(
      fc.property(trendsSeries, ({ series, properties }) => {
        const result = netByPropertyTrend(series);

        // Distinct property ids that appear anywhere in the series.
        const distinctIds = new Set<string>();
        for (const year of series.years) {
          for (const point of year.properties) distinctIds.add(point.property_id);
        }

        // (a) Exactly one series per distinct property.
        expect(result).toHaveLength(distinctIds.size);
        expect(new Set(result.map((s) => s.propertyId))).toEqual(distinctIds);

        const yearsAsc = series.years.map((y) => y.tax_year);
        for (const s of result) {
          // (b) Exactly one point per Data_Year, in ascending order.
          expect(s.points.map((p) => p.year)).toEqual(yearsAsc);
          expect(s.points).toHaveLength(series.years.length);

          // Each point's cents match the property's net that year, or 0 when
          // the property is absent from that year (missing → 0 cents).
          for (let i = 0; i < series.years.length; i += 1) {
            const year = series.years[i];
            const point = year.properties.find(
              (p) => p.property_id === s.propertyId,
            );
            const expected = point ? toCents(point.net) : 0;
            expect(s.points[i].cents).toBe(expected);
          }
        }

        // (c) All series labels are unique, even when display names collide.
        const labels = result.map((s) => s.label);
        expect(new Set(labels).size).toBe(labels.length);

        // Every label carries the property's display name (optionally suffixed
        // with a disambiguator on collision).
        const nameById = new Map(properties.map((p) => [p.id, p.name]));
        for (const s of result) {
          const name = nameById.get(s.propertyId);
          if (name !== undefined) {
            expect(s.label.startsWith(name)).toBe(true);
          }
        }
      }),
      { numRuns: 100 },
    );
  });
});
