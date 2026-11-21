import { describe, expect, it } from "vitest";
import { ApiError } from "../../lib/apiClient";
import { toFieldErrors, toOverrideErrors } from "./assetErrors";

const apiError = (body: unknown) => new ApiError(400, "Bad request", body);

describe("toFieldErrors", () => {
  it("maps a field body to a field error", () => {
    expect(
      toFieldErrors(apiError({ field: "cost_basis", message: "Must be > 0" })),
    ).toEqual({
      fieldErrors: { cost_basis: "Must be > 0" },
      message: "Must be > 0",
    });
  });

  it("returns only a message when no field is present", () => {
    expect(toFieldErrors(apiError({ message: "Nope" }))).toEqual({
      fieldErrors: {},
      message: "Nope",
    });
  });

  it("falls back to the ApiError message for a non-object body", () => {
    expect(toFieldErrors(apiError(null))).toEqual({
      fieldErrors: {},
      message: "Bad request",
    });
  });

  it("uses a generic message for unknown errors", () => {
    expect(toFieldErrors(new Error("x")).message).toBe(
      "Something went wrong. Please try again.",
    );
  });
});

describe("toOverrideErrors", () => {
  it("maps a dotted field to a per-year error", () => {
    expect(
      toOverrideErrors(
        apiError({ field: "depreciation_overrides.2024", message: "Too big" }),
      ),
    ).toEqual({
      yearErrors: { "2024": "Too big" },
      generalError: null,
      message: "Too big",
    });
  });

  it("maps the bare field to a general error", () => {
    expect(
      toOverrideErrors(
        apiError({ field: "depreciation_overrides", message: "Sum too big" }),
      ),
    ).toEqual({ yearErrors: {}, generalError: "Sum too big", message: "Sum too big" });
  });

  it("returns null for unrelated fields, empty year and non-ApiErrors", () => {
    expect(
      toOverrideErrors(apiError({ field: "description", message: "x" })),
    ).toBeNull();
    expect(
      toOverrideErrors(
        apiError({ field: "depreciation_overrides.", message: "x" }),
      ),
    ).toBeNull();
    expect(toOverrideErrors(new Error("x"))).toBeNull();
  });
});
