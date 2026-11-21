import { describe, it, expect } from "vitest";
import * as fc from "fast-check";
import { contrastRatio, relativeLuminance } from "./contrast";

const channel = fc.integer({ min: 0, max: 255 });
const color = fc.tuple(channel, channel, channel);

// Tolerance for floating point rounding at the 1 and 21 bounds.
const EPS = 1e-9;

describe("contrast properties", () => {
  // Feature: ui-polish-and-consistency, Property 13: Contrast ratio is a well-formed metric
  /** **Validates: Requirements 17.7** */
  it("Property 13: contrast ratio is a well-formed metric", () => {
    fc.assert(
      fc.property(color, color, (a, b) => {
        const ratio = contrastRatio(a, b);
        // Symmetry
        expect(contrastRatio(b, a)).toBe(ratio);
        // Range 1..21
        expect(ratio).toBeGreaterThanOrEqual(1);
        expect(ratio).toBeLessThanOrEqual(21 + EPS);
        // Identical colors
        expect(contrastRatio(a, a)).toBe(1);
        // Luminance is within 0..1
        const l = relativeLuminance(a);
        expect(l).toBeGreaterThanOrEqual(0);
        expect(l).toBeLessThanOrEqual(1 + EPS);
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish-and-consistency, Property 13: Contrast ratio is a well-formed metric
  /** **Validates: Requirements 17.7** */
  it("Property 13: black on white is 21", () => {
    expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 9);
    expect(contrastRatio([255, 255, 255], [0, 0, 0])).toBeCloseTo(21, 9);
  });
});
