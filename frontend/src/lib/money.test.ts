import { describe, expect, it } from "vitest";
import {
  centsToMoney,
  formatMoney,
  isLoss,
  isPositiveAmount,
  sumMoney,
  toCents,
  toMoneyString,
} from "./money";

/**
 * Unit tests for the canonical money helpers (task 1.4).
 *
 * These merge the previously separate `transactions/money` and
 * `dashboard/money` unit suites and add cases for the merged superset behavior:
 * empty/undefined → "", non-numeric passthrough, negative and large amounts.
 *
 * Validates: Requirements 7.1, 7.4, 13.1, 13.3
 */

describe("isPositiveAmount", () => {
  it("accepts well-formed positive amounts", () => {
    expect(isPositiveAmount("0.01")).toBe(true);
    expect(isPositiveAmount("1")).toBe(true);
    expect(isPositiveAmount("1250")).toBe(true);
    expect(isPositiveAmount("99.9")).toBe(true);
    expect(isPositiveAmount("99.90")).toBe(true);
  });

  it("tolerates surrounding whitespace", () => {
    expect(isPositiveAmount("  12.50  ")).toBe(true);
  });

  it("rejects zero and zero-valued amounts", () => {
    expect(isPositiveAmount("0")).toBe(false);
    expect(isPositiveAmount("0.00")).toBe(false);
    expect(isPositiveAmount("0.0")).toBe(false);
  });

  it("rejects negative, non-numeric, and over-precise amounts", () => {
    expect(isPositiveAmount("-5")).toBe(false);
    expect(isPositiveAmount("-0.01")).toBe(false);
    expect(isPositiveAmount("")).toBe(false);
    expect(isPositiveAmount("abc")).toBe(false);
    expect(isPositiveAmount("12.")).toBe(false);
    expect(isPositiveAmount("12.345")).toBe(false);
    expect(isPositiveAmount("1,250.00")).toBe(false);
    expect(isPositiveAmount("$5")).toBe(false);
  });
});

describe("toMoneyString", () => {
  it("normalizes valid inputs to a fixed two-decimal string", () => {
    expect(toMoneyString("1250")).toBe("1250.00");
    expect(toMoneyString("99.9")).toBe("99.90");
    expect(toMoneyString("0.01")).toBe("0.01");
    expect(toMoneyString("5.00")).toBe("5.00");
    expect(toMoneyString("0")).toBe("0.00");
  });

  it("trims surrounding whitespace before normalizing", () => {
    expect(toMoneyString("  42  ")).toBe("42.00");
  });

  it("passes through malformed inputs unchanged (trimmed)", () => {
    expect(toMoneyString("  abc  ")).toBe("abc");
    expect(toMoneyString("12.345")).toBe("12.345");
    expect(toMoneyString("")).toBe("");
  });
});

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

  it("sums large amounts exactly", () => {
    expect(sumMoney(["9999999.99", "0.01"])).toBe("10000000.00");
  });
});

describe("isLoss", () => {
  it("is true for a negative amount", () => {
    expect(isLoss("-1.00")).toBe(true);
    expect(isLoss("-0.01")).toBe(true);
  });

  it("is false for zero and positive amounts", () => {
    expect(isLoss("0.00")).toBe(false);
    expect(isLoss("125.00")).toBe(false);
  });
});

describe("toCents", () => {
  it("parses money strings to exact integer cents", () => {
    expect(toCents("1250.00")).toBe(125000);
    expect(toCents("0.01")).toBe(1);
    expect(toCents("5")).toBe(500);
    expect(toCents("99.9")).toBe(9990);
  });

  it("parses negatives", () => {
    expect(toCents("-125.50")).toBe(-12550);
    expect(toCents("-0.01")).toBe(-1);
  });

  it("tolerates surrounding whitespace", () => {
    expect(toCents("  42.00  ")).toBe(4200);
  });

  it("returns 0 for unrecognized input", () => {
    expect(toCents("not-money")).toBe(0);
    expect(toCents("")).toBe(0);
    expect(toCents("$5")).toBe(0);
    expect(toCents("1,250.00")).toBe(0);
  });

  it("returns an integer for every recognized input", () => {
    for (const s of ["0.00", "1.23", "-9.99", "1000000.00"]) {
      expect(Number.isInteger(toCents(s))).toBe(true);
    }
  });
});

describe("centsToMoney", () => {
  it("renders integer cents back to a two-decimal string", () => {
    expect(centsToMoney(125000)).toBe("1250.00");
    expect(centsToMoney(1)).toBe("0.01");
    expect(centsToMoney(0)).toBe("0.00");
  });

  it("renders negatives with a leading minus", () => {
    expect(centsToMoney(-12550)).toBe("-125.50");
    expect(centsToMoney(-1)).toBe("-0.01");
  });

  it("round-trips with toCents on normalized strings", () => {
    for (const s of ["0.00", "1250.00", "-125.50", "99.90"]) {
      expect(centsToMoney(toCents(s))).toBe(s);
    }
  });
});

describe("formatMoney", () => {
  it("formats two-decimal strings as US currency", () => {
    expect(formatMoney("1250.00")).toBe("$1,250.00");
    expect(formatMoney("0.00")).toBe("$0.00");
    expect(formatMoney("99.90")).toBe("$99.90");
    expect(formatMoney("5")).toBe("$5.00");
  });

  it("formats negative amounts with a leading minus sign", () => {
    expect(formatMoney("-1250.00")).toBe("-$1,250.00");
    expect(formatMoney("-125.00")).toBe("-$125.00");
  });

  it("formats large amounts with grouping separators", () => {
    expect(formatMoney("1000000.00")).toBe("$1,000,000.00");
  });

  it("returns an empty string for empty, null, or undefined", () => {
    expect(formatMoney("")).toBe("");
    expect(formatMoney(null)).toBe("");
    expect(formatMoney(undefined)).toBe("");
  });

  it("returns non-numeric input unchanged", () => {
    expect(formatMoney("not-a-number")).toBe("not-a-number");
    expect(formatMoney("12.3x")).toBe("12.3x");
  });
});
