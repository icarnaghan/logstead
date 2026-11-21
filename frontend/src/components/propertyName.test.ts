import { describe, expect, it } from "vitest";
import { resolvePropertyName } from "./propertyName";

/**
 * Unit tests for the shared `resolvePropertyName` helper (task 2.1).
 *
 * Locks in the Requirement 1.3 / 3.4 contract: the overview and sub-pages
 * resolve a human-readable display name from the shared property context and
 * never leak the raw identifier.
 * - `"loading"` → the neutral placeholder, regardless of any provided name.
 * - `"loaded"` + name → the property's name.
 * - `"loaded"` without a usable name / `"error"` → the neutral `"Property"`.
 */
describe("resolvePropertyName (Requirements 1.3, 3.4)", () => {
  it("returns the loading placeholder while the fetch is in flight", () => {
    expect(resolvePropertyName("loading", undefined)).toBe("Loading property…");
  });

  it("ignores a provided name while still loading", () => {
    expect(resolvePropertyName("loading", "Maple Duplex")).toBe(
      "Loading property…",
    );
  });

  it("returns the property name once loaded", () => {
    expect(resolvePropertyName("loaded", "Maple Duplex")).toBe("Maple Duplex");
  });

  it("falls back to \"Property\" when loaded without a name", () => {
    expect(resolvePropertyName("loaded", undefined)).toBe("Property");
  });

  it("falls back to \"Property\" when loaded with an empty name", () => {
    expect(resolvePropertyName("loaded", "")).toBe("Property");
  });

  it("falls back to \"Property\" in the error state", () => {
    expect(resolvePropertyName("error", "whatever")).toBe("Property");
  });
});
