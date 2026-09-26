import { describe, expect, it } from "vitest";
import { formatMoney, isLoss, sumMoney } from "./money";

describe("sumMoney", () => {
  it("sums two-decimal strings exactly", () => {
    expect(sumMoney(["1250.00", "5833.33"])).toBe("7083.33");
  });

  it("returns 0.00 for an empty list", () => {
    expect(sumMoney([])).toBe("0.00");
  });

  it("handles cent carries without floating-point error", () => {
    // 0.10 + 0.20 = 0.30 exactly (float would give 0.30000000000000004).
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(["0.99", "0.01"])).toBe("1.00");
  });

  it("supports negatives (losses)", () => {
    expect(sumMoney(["-500.00", "200.00"])).toBe("-300.00");
    expect(sumMoney(["-125.50", "-74.50"])).toBe("-200.00");
  });

  it("sums a single value", () => {
    expect(sumMoney(["42.00"])).toBe("42.00");
  });

  it("ignores unparseable entries as zero", () => {
    expect(sumMoney(["not-money", "10.00"])).toBe("10.00");
  });
});

describe("isLoss", () => {
  it("is true for a negative amount", () => {
    expect(isLoss("-1.00")).toBe(true);
  });

  it("is false for zero and positive amounts", () => {
    expect(isLoss("0.00")).toBe(false);
    expect(isLoss("125.00")).toBe(false);
  });
});

describe("formatMoney", () => {
  it("formats as US currency", () => {
    expect(formatMoney("1250.00")).toBe("$1,250.00");
    expect(formatMoney("-125.00")).toBe("-$125.00");
  });
});
