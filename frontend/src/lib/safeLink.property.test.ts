import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { isSafeAppLink } from "./safeLink";

/**
 * Property 15: Safe link check.
 *
 * **Validates: Requirements 11.5**
 */

// Control characters: C0 range, DEL and C1 range.
const hasControl = (s: string): boolean =>
  [...s].some((c) => {
    const n = c.codePointAt(0) ?? 0;
    return n <= 0x1f || (n >= 0x7f && n <= 0x9f);
  });

const oracle = (s: string): boolean =>
  s.startsWith("/") && !s.startsWith("//") && !s.includes("\\") && !hasControl(s);

const linkArb = fc.oneof(
  fc.string({ unit: "binary", maxLength: 20 }),
  // Bias toward strings near the boundary of the rule.
  fc
    .tuple(
      fc.constantFrom("", "/", "//", "/a", "http://", "javascript:"),
      fc.array(fc.constantFrom("a", "z", "0", "/", "?", "=", "&", "#", ".", "\\", "\u0000", "\u001f", "\u007f", "\u0080", "\u009f", "\u00a0", " ", "-"), { maxLength: 12 }).map((a) => a.join("")),
    )
    .map(([a, b]) => a + b),
);

describe("Property 15: isSafeAppLink", () => {
  it("is true iff single leading slash, no backslash, no control character", () => {
    fc.assert(
      fc.property(linkArb, (s) => {
        expect(isSafeAppLink(s)).toBe(oracle(s));
      }),
      { numRuns: 500 },
    );
  });

  it("accepts app paths and rejects unsafe ones", () => {
    expect(isSafeAppLink("/properties/1?year=2024#x")).toBe(true);
    expect(isSafeAppLink("//evil.com")).toBe(false);
    expect(isSafeAppLink("/a\\b")).toBe(false);
    expect(isSafeAppLink("/a\nb")).toBe(false);
    expect(isSafeAppLink("https://x.com")).toBe(false);
    expect(isSafeAppLink("")).toBe(false);
  });
});
