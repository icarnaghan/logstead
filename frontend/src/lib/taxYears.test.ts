import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { latestCompletedTaxYear, parseYearParam, taxYearRange } from "./taxYears";

const assetOn = (year: number) => ({
  placed_in_service_date: `${String(year).padStart(4, "0")}-06-15`,
});

describe("taxYearRange examples", () => {
  it("spans a 2010 earliest data year (no assets) through the latest completed year", () => {
    const latest = latestCompletedTaxYear();
    const years = taxYearRange([], latest, 6, 2010);
    expect(years[0]).toBe(latest);
    expect(years[years.length - 1]).toBe(2010);
    expect(years).toHaveLength(latest - 2010 + 1);
  });

  it("gives the six-year window when there is no data", () => {
    expect(taxYearRange([], 2024)).toEqual([2024, 2023, 2022, 2021, 2020, 2019]);
  });

  it("clamps a future earliest data year so the range is never empty", () => {
    expect(taxYearRange([], 2024, 6, 2035)).toEqual([
      2024, 2023, 2022, 2021, 2020, 2019,
    ]);
    expect(taxYearRange([assetOn(2030)], 2024, 1, 2035)).toEqual([2024]);
  });

  it("ignores an earliest data year below 1900", () => {
    expect(taxYearRange([], 2024, 6, 1850)).toEqual([
      2024, 2023, 2022, 2021, 2020, 2019,
    ]);
  });

  it("uses the earlier of an asset year and the earliest data year", () => {
    const years = taxYearRange([assetOn(2015)], 2024, 6, 2012);
    expect(years[years.length - 1]).toBe(2012);
    const years2 = taxYearRange([assetOn(2012)], 2024, 6, 2015);
    expect(years2[years2.length - 1]).toBe(2012);
  });
});

describe("taxYearRange property", () => {
  // Feature: carryforward-tolerance-and-year-range, Property 11: Year range spans the earliest known year to the latest completed year
  // **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
  it("is descending, starts at latest, non-empty, contiguous, and ends at the expected minimum", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1950, max: 2100 }),
        fc.array(fc.integer({ min: 1800, max: 2150 }), { maxLength: 6 }),
        fc.option(fc.integer({ min: 1500, max: 2200 }), { nil: null }),
        fc.integer({ min: 1, max: 10 }),
        (latest, assetYears, earliestData, fallbackCount) => {
          const years = taxYearRange(
            assetYears.map(assetOn),
            latest,
            fallbackCount,
            earliestData,
          );

          const candidates = [latest - (fallbackCount - 1)];
          for (const y of assetYears) if (y >= 1900) candidates.push(y);
          if (earliestData !== null && earliestData >= 1900) {
            candidates.push(earliestData);
          }
          const expectedMin = Math.min(Math.min(...candidates), latest);

          expect(years.length).toBeGreaterThan(0);
          expect(years[0]).toBe(latest);
          expect(years[years.length - 1]).toBe(expectedMin);
          for (let i = 1; i < years.length; i++) {
            expect(years[i]).toBe(years[i - 1] - 1);
          }
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("parseYearParam", () => {
  it("accepts canonical years 1900..2200 and rejects everything else", () => {
    expect(parseYearParam("1900")).toBe(1900);
    expect(parseYearParam("2200")).toBe(2200);
    expect(parseYearParam("2024")).toBe(2024);
    for (const bad of [null, undefined, "", "1899", "2201", "02024", "+2024", "2024.0", " 2024", "2024 ", "abc", "-2024", "0x7e8"]) {
      expect(parseYearParam(bad)).toBeNull();
    }
  });
  it("round-trips every in-range integer", () => {
    fc.assert(
      fc.property(fc.integer({ min: 1900, max: 2200 }), (n) => {
        expect(parseYearParam(String(n))).toBe(n);
      }),
    );
  });
});
