import { describe, expect, it } from "vitest";

import type { ReconciledYear } from "../api/carryforward";
import { carriedBreakInfo, summarizeChainBreaks } from "./carryforwardChain";

type Overrides = Partial<ReconciledYear> & { tax_year: number };

/** Build a row with sensible defaults; override only what a test cares about. */
function row(o: Overrides): ReconciledYear {
  return {
    schedule_e_net: "0.00",
    expected_carryforward: "0.00",
    reported_carryforward: "0.00",
    expected_carry_in: "0.00",
    allowed_loss: "0.00",
    fully_allowed: false,
    status: "ok",
    drift: "0.00",
    carried_from_year: null,
    ...o,
  };
}

/** Real-data shape: mismatch 2016-2018, carried 2019-2020, mismatch 2021, carried 2022-2025. */
function realSeries(): ReconciledYear[] {
  const carried = (year: number, from: number, drift: string) =>
    row({
      tax_year: year,
      status: "carried",
      carried_from_year: from,
      drift,
      reported_carryforward: "100.00",
    });
  return [
    row({
      tax_year: 2015,
      status: "ok",
      expected_carryforward: "2452.00",
      expected_carry_in: "0.00",
      reported_carryforward: "0.00",
      drift: "0.00",
    }),
    row({
      tax_year: 2016,
      status: "mismatch",
      expected_carry_in: "2452.00",
      expected_carryforward: "2710.00",
      reported_carryforward: "0.00",
      drift: "-2452.00",
    }),
    row({
      tax_year: 2017,
      status: "mismatch",
      expected_carry_in: "2710.00",
      expected_carryforward: "3422.00",
      reported_carryforward: "0.00",
      drift: "-2710.00",
    }),
    row({
      tax_year: 2018,
      status: "mismatch",
      expected_carry_in: "3422.00",
      expected_carryforward: "3422.00",
      reported_carryforward: "0.00",
      drift: "-3422.00",
    }),
    carried(2019, 2018, "-3422.00"),
    carried(2020, 2018, "-3422.00"),
    row({
      tax_year: 2021,
      status: "mismatch",
      expected_carry_in: "5000.00",
      reported_carryforward: "676.00",
      drift: "-4324.00",
    }),
    carried(2022, 2021, "-4323.00"),
    carried(2023, 2021, "-4323.00"),
    carried(2024, 2021, "-4323.00"),
    carried(2025, 2021, "-4323.00"),
  ];
}

describe("summarizeChainBreaks: real-data shape", () => {
  const summary = summarizeChainBreaks(realSeries());

  it("finds the first break as the 2016 to 2018 run", () => {
    expect(summary).not.toBeNull();
    const first = summary!.firstBreak;
    expect(first.startYear).toBe(2016);
    expect(first.endYear).toBe(2018);
    expect(first.startAmount).toBe("-2452.00");
    expect(first.endAmount).toBe("-3422.00");
    expect(first.reported).toBe("0.00");
    expect(first.expectedCarryIn).toBe("2452.00");
    expect(first.priorYear).toBe(2015);
    expect(first.priorCarryOut).toBe("2452.00");
  });

  it("reports one further break at 2021 with its incremental amount", () => {
    const further = summary!.furtherBreaks;
    expect(further).toHaveLength(1);
    expect(further[0].startYear).toBe(2021);
    expect(further[0].endYear).toBe(2021);
    expect(further[0].startAmount).toBe("-902.00");
    expect(further[0].endAmount).toBe("-902.00");
  });

  it("takes the total gap from the latest row", () => {
    expect(summary!.totalGap).toEqual({ year: 2025, drift: "-4323.00" });
  });

  it("gives carried rows their break year and the first break year", () => {
    const years = realSeries();
    const y2019 = years.find((y) => y.tax_year === 2019)!;
    const y2023 = years.find((y) => y.tax_year === 2023)!;
    expect(carriedBreakInfo(y2019, summary)).toEqual({
      breakYear: 2018,
      drift: "-3422.00",
      firstBreakYear: 2016,
    });
    expect(carriedBreakInfo(y2023, summary)).toEqual({
      breakYear: 2021,
      drift: "-4323.00",
      firstBreakYear: 2016,
    });
  });

  it("omits firstBreakYear when the row inherits from the first break", () => {
    const first = row({
      tax_year: 2019,
      status: "carried",
      carried_from_year: 2016,
      drift: "-2452.00",
    });
    expect(carriedBreakInfo(first, summary)?.firstBreakYear).toBeNull();
  });
});

describe("summarizeChainBreaks: edge cases", () => {
  it("returns null for an empty series", () => {
    expect(summarizeChainBreaks([])).toBeNull();
  });

  it("returns null when no row is a mismatch", () => {
    const years = [
      row({ tax_year: 2020, status: "ok" }),
      row({ tax_year: 2021, status: "carried", carried_from_year: 2019 }),
      row({
        tax_year: 2022,
        status: "unreported",
        reported_carryforward: null,
        drift: null,
      }),
    ];
    expect(summarizeChainBreaks(years)).toBeNull();
  });

  it("has null prior fields when the first row is the mismatch", () => {
    const summary = summarizeChainBreaks([
      row({
        tax_year: 2016,
        status: "mismatch",
        expected_carry_in: "500.00",
        reported_carryforward: "0.00",
        drift: "-500.00",
      }),
    ]);
    expect(summary!.firstBreak.priorYear).toBeNull();
    expect(summary!.firstBreak.priorCarryOut).toBeNull();
    expect(summary!.firstBreak.startAmount).toBe("-500.00");
    expect(summary!.furtherBreaks).toEqual([]);
  });

  it("has null prior fields when the prior row is unreported", () => {
    const summary = summarizeChainBreaks([
      row({
        tax_year: 2019,
        status: "unreported",
        reported_carryforward: null,
        drift: null,
        expected_carryforward: "300.00",
      }),
      row({
        tax_year: 2020,
        status: "mismatch",
        expected_carry_in: "300.00",
        reported_carryforward: "0.00",
        drift: "-300.00",
      }),
    ]);
    expect(summary!.firstBreak.priorYear).toBeNull();
    expect(summary!.firstBreak.priorCarryOut).toBeNull();
    expect(summary!.firstBreak.startAmount).toBe("-300.00");
  });

  it("gives a positive amount for a positive-drift mismatch", () => {
    const summary = summarizeChainBreaks([
      row({ tax_year: 2019, status: "ok", drift: "0.00" }),
      row({
        tax_year: 2020,
        status: "mismatch",
        expected_carry_in: "100.00",
        reported_carryforward: "350.50",
        drift: "250.50",
      }),
    ]);
    expect(summary!.firstBreak.startAmount).toBe("250.50");
    expect(summary!.firstBreak.endAmount).toBe("250.50");
    expect(summary!.totalGap).toEqual({ year: 2020, drift: "250.50" });
  });

  it("keeps two runs separated by an unreported row as two runs", () => {
    const summary = summarizeChainBreaks([
      row({ tax_year: 2018, status: "mismatch", drift: "-100.00" }),
      row({
        tax_year: 2019,
        status: "unreported",
        reported_carryforward: null,
        drift: null,
      }),
      row({ tax_year: 2020, status: "mismatch", drift: "-250.00" }),
    ]);
    expect(summary!.firstBreak.startYear).toBe(2018);
    expect(summary!.firstBreak.endYear).toBe(2018);
    expect(summary!.furtherBreaks).toHaveLength(1);
    expect(summary!.furtherBreaks[0].startYear).toBe(2020);
    // Unreported row has no drift, so the baseline stays at the 2018 drift.
    expect(summary!.furtherBreaks[0].startAmount).toBe("-150.00");
  });

  it("uses the last carried drift as a later run's baseline", () => {
    const summary = summarizeChainBreaks([
      row({ tax_year: 2016, status: "mismatch", drift: "-1000.00" }),
      row({
        tax_year: 2017,
        status: "carried",
        carried_from_year: 2016,
        drift: "-1000.50",
      }),
      row({ tax_year: 2018, status: "mismatch", drift: "-1300.50" }),
    ]);
    expect(summary!.furtherBreaks[0].startAmount).toBe("-300.00");
    expect(summary!.totalGap).toEqual({ year: 2018, drift: "-1300.50" });
  });

  it("does not mutate the input array or its rows", () => {
    const years = realSeries();
    const copy = JSON.parse(JSON.stringify(years));
    const summary = summarizeChainBreaks(years);
    carriedBreakInfo(years[4], summary);
    expect(years).toEqual(copy);
  });
});

describe("carriedBreakInfo: null cases", () => {
  const summary = summarizeChainBreaks(realSeries());

  it.each(["ok", "mismatch", "unreported"] as const)(
    "returns null for a %s row",
    (status) => {
      const r = row({
        tax_year: 2020,
        status,
        carried_from_year: 2018,
        drift: "-10.00",
      });
      expect(carriedBreakInfo(r, summary)).toBeNull();
    },
  );

  it("returns null for a carried row with no carried_from_year", () => {
    const r = row({
      tax_year: 2020,
      status: "carried",
      carried_from_year: null,
      drift: "-10.00",
    });
    expect(carriedBreakInfo(r, summary)).toBeNull();
  });

  it("returns null for a carried row with no drift", () => {
    const r = row({
      tax_year: 2020,
      status: "carried",
      carried_from_year: 2018,
      drift: null,
    });
    expect(carriedBreakInfo(r, summary)).toBeNull();
  });

  it("tolerates a null summary", () => {
    const r = row({
      tax_year: 2020,
      status: "carried",
      carried_from_year: 2018,
      drift: "-10.00",
    });
    expect(carriedBreakInfo(r, null)).toEqual({
      breakYear: 2018,
      drift: "-10.00",
      firstBreakYear: null,
    });
  });
});
