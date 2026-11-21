import { describe, expect, it } from "vitest";
import type { ScheduleEReport } from "../../api/reports";
import { depreciationTotal, toReportState } from "./reportState";

const report = {
  lines: [
    { line: 9, total: "10.00" },
    { line: 18, total: "1234.50" },
  ],
} as unknown as ScheduleEReport;

describe("toReportState", () => {
  it("is idle only when idle with no data", () => {
    expect(toReportState("idle", null, null)).toEqual({ status: "idle" });
  });

  it("prefers loaded data over an error", () => {
    expect(toReportState("success", report, "boom")).toEqual({
      status: "loaded",
      report,
    });
  });

  it("reports the error message when there is no data", () => {
    expect(toReportState("error", null, "boom")).toEqual({
      status: "error",
      message: "boom",
    });
  });

  it("is loading otherwise", () => {
    expect(toReportState("loading", null, null)).toEqual({ status: "loading" });
  });
});

describe("depreciationTotal", () => {
  it("returns the Line 18 total", () => {
    expect(depreciationTotal({ status: "loaded", report })).toBe("1234.50");
  });

  it("falls back to 0.00 when Line 18 is absent", () => {
    const empty = { lines: [] } as unknown as ScheduleEReport;
    expect(depreciationTotal({ status: "loaded", report: empty })).toBe("0.00");
  });

  it("is null when not loaded", () => {
    expect(depreciationTotal({ status: "loading" })).toBeNull();
  });
});
