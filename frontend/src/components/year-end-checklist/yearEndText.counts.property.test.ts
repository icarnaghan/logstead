import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { countsText, summaryHeadline } from "./yearEndText";

// Feature: year-end-checklist, Property 24: Counts text and headline
// **Validates: Requirements 17.2, 19.4**

const countArb = fc.integer({ min: 0, max: 10_000 });
const countsArb = fc.record({
  done: countArb,
  needs_attention: countArb,
  not_applicable: countArb,
});

describe("Property 24: Counts text and headline", () => {
  it("countsText contains all three counts and their labels", () => {
    fc.assert(
      fc.property(countsArb, (counts) => {
        const text = countsText(counts);
        expect(text).toContain(`${counts.done} done`);
        expect(text).toContain(`${counts.not_applicable} not applicable`);
        expect(text).toMatch(
          new RegExp(`\\b${counts.needs_attention} needs? attention\\b`),
        );
        expect(text).toMatch(/needs? attention/);
      }),
      { numRuns: 100 },
    );
  });

  it("summaryHeadline is 'All clear' iff nothing needs attention and at least one is done", () => {
    fc.assert(
      fc.property(countsArb, (counts) => {
        const headline = summaryHeadline(counts);
        const allClear = counts.needs_attention === 0 && counts.done >= 1;
        expect(headline === "All clear").toBe(allClear);
        if (counts.needs_attention > 0) {
          expect(headline).toContain(String(counts.needs_attention));
        }
      }),
      { numRuns: 100 },
    );
  });
});
