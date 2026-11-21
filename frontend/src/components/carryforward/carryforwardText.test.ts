import { describe, expect, it } from "vitest";
import { ApiError } from "../../lib/apiClient";
import {
  amountErrorMessage,
  driftText,
  fieldErrorMessage,
  isNonNegativeAmount,
} from "./carryforwardText";

describe("isNonNegativeAmount", () => {
  it.each(["0", "0.00", "12", "1234.5", " 7.25 "])("accepts %j", (v) => {
    expect(isNonNegativeAmount(v)).toBe(true);
  });
  it.each(["", "-1", "1.234", "abc", "1,000", ".5"])("rejects %j", (v) => {
    expect(isNonNegativeAmount(v)).toBe(false);
  });
});

describe("driftText", () => {
  it("adds direction cues", () => {
    expect(driftText("500.00")).toBe("+$500 over");
    expect(driftText("-500.00")).toBe("-$500 under");
  });
  it("keeps the sign cue when the magnitude rounds to zero", () => {
    expect(driftText("-0.01")).toMatch(/^-.* under$/);
  });
  it("shows zero without a cue", () => {
    expect(driftText("0.00")).toBe("$0");
  });
});

describe("error message helpers", () => {
  const apiError = (body: unknown) =>
    new ApiError(400, "bad request", body);

  it("falls back for non-ApiError values", () => {
    expect(amountErrorMessage(new Error("x"), "fallback")).toBe("fallback");
    expect(fieldErrorMessage("x", ["a"], "fallback")).toBe("fallback");
  });
  it("uses the body message on a 400", () => {
    expect(
      amountErrorMessage(apiError({ field: "amount", message: "Too big" }), "f"),
    ).toBe("Too big");
    expect(
      fieldErrorMessage(
        apiError({ field: "allowedLoss", message: "Nope" }),
        ["allowed_loss", "allowedLoss"],
        "f",
      ),
    ).toBe("Nope");
  });
});
