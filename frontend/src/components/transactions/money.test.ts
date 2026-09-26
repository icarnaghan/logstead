import { describe, expect, it } from "vitest";
import { formatMoney, isPositiveAmount, toMoneyString } from "./money";

/**
 * Unit tests for the transactions money helpers (task 22.3).
 *
 * Money is a fixed two-decimal **string** across the API (Requirement 13.3),
 * so these helpers only validate/format — they never do arithmetic. The cases
 * pin down the edges that the transaction form relies on: rejecting zero and
 * malformed amounts (Requirement 5.2), normalizing to two decimals for the
 * payload, and formatting for display.
 *
 * Validates: Requirements 5.2, 13.3
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

  it("rejects zero and zero-valued amounts (Requirement 5.2)", () => {
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

describe("formatMoney", () => {
  it("formats two-decimal strings as US currency", () => {
    expect(formatMoney("1250.00")).toBe("$1,250.00");
    expect(formatMoney("0.00")).toBe("$0.00");
    expect(formatMoney("99.90")).toBe("$99.90");
    expect(formatMoney("5")).toBe("$5.00");
  });

  it("formats negative amounts with a leading minus sign", () => {
    expect(formatMoney("-1250.00")).toBe("-$1,250.00");
  });

  it("returns non-numeric input unchanged", () => {
    expect(formatMoney("not-a-number")).toBe("not-a-number");
    expect(formatMoney("12.3x")).toBe("12.3x");
  });
});
