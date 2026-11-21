import fc from "fast-check";
import { describe, expect, it } from "vitest";
import type { ChecklistStatus } from "../../api/yearEndChecklist";
import { orderItems } from "./yearEndText";

const status = fc.constantFrom<ChecklistStatus>(
  "done",
  "needs_attention",
  "not_applicable",
);

// Each item gets a unique index so order and permutation can be checked exactly.
const items = fc
  .array(status, { maxLength: 30 })
  .map((statuses) => statuses.map((s, index) => ({ status: s, index })));

describe("yearEndText (property tests)", () => {
  // Feature: year-end-checklist, Property 23: Needs-attention items come first
  // **Validates: Requirements 19.5**
  it("Property 23: orderItems puts needs_attention first and keeps relative order", () => {
    fc.assert(
      fc.property(items, (input) => {
        const output = orderItems(input);

        // Permutation of the input.
        expect(output).toHaveLength(input.length);
        expect(output.map((i) => i.index).sort((a, b) => a - b)).toEqual(
          input.map((i) => i.index),
        );

        // Every needs_attention item precedes every other item.
        const firstOther = output.findIndex((i) => i.status !== "needs_attention");
        if (firstOther !== -1) {
          expect(
            output.slice(firstOther).some((i) => i.status === "needs_attention"),
          ).toBe(false);
        }

        // Relative order inside each group equals the input order.
        const attention = input.filter((i) => i.status === "needs_attention");
        const rest = input.filter((i) => i.status !== "needs_attention");
        expect(output).toEqual([...attention, ...rest]);
      }),
      { numRuns: 100 },
    );
  });
});
