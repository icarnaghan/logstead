import { describe, expect, it } from "vitest";
import fc from "fast-check";
import { render } from "@testing-library/react";
import { ErrorSummary } from "../components/ui/ErrorSummary";
import { firstInvalidField, orderedErrors } from "./formErrors";

// Feature: ui-polish-and-consistency, Property 4: Error ordering and first invalid field
describe("formErrors property tests", () => {
  /** Unique ordered field list plus an error map over a subset (some empty messages). */
  const scenario = fc
    .uniqueArray(fc.string({ minLength: 1, maxLength: 8 }), {
      minLength: 0,
      maxLength: 10,
    })
    .chain((order) =>
      fc
        .record(
          Object.fromEntries(
            order.map((f) => [
              `k_${f}`,
              fc.option(fc.oneof(fc.constant(""), fc.string({ maxLength: 12 })), {
                nil: undefined,
              }),
            ]),
          ),
        )
        .map((raw) => {
          const errors: Record<string, string> = {};
          for (const f of order) {
            const v = (raw as Record<string, string | undefined>)[`k_${f}`];
            if (v !== undefined) errors[f] = v;
          }
          return { order, errors };
        }),
    );

  it("Property 4: returns non-empty entries in order, no duplicates, and first invalid field", () => {
    fc.assert(
      fc.property(scenario, ({ order, errors }) => {
        const result = orderedErrors(errors, order);
        const expected = order
          .filter((f) => typeof errors[f] === "string" && errors[f] !== "")
          .map((f) => ({ field: f, message: errors[f] }));

        expect(result).toEqual(expected);
        const fields = result.map((r) => r.field);
        expect(new Set(fields).size).toBe(fields.length);
        expect(result.every((r) => r.message.length > 0)).toBe(true);

        const first = firstInvalidField(errors, order);
        if (result.length === 0) {
          expect(first == null).toBe(true);
        } else {
          expect(first).toBe(result[0].field);
        }
      }),
      { numRuns: 100 },
    );
  });
});

// Feature: ui-polish-and-consistency, Property 5: Error summary heading states the count
describe("ErrorSummary property tests", () => {
  const item = fc.record({
    field: fc.option(fc.string({ minLength: 1, maxLength: 8 }), { nil: undefined }),
    message: fc.string({ minLength: 1, maxLength: 20 }),
  });

  it("Property 5: heading states the count, singular iff n is 1, nothing for empty", () => {
    fc.assert(
      fc.property(fc.array(item, { minLength: 0, maxLength: 12 }), (items) => {
        const { container, unmount } = render(
          <ErrorSummary items={items} idFor={(f) => `field-${f}`} />,
        );
        try {
          const heading = container.querySelector("h2");
          if (items.length === 0) {
            expect(container.firstChild).toBeNull();
            return;
          }
          const text = heading?.textContent ?? "";
          expect(text).toContain(String(items.length));
          if (items.length === 1) {
            expect(text).toMatch(/\bis\b/);
            expect(text).toMatch(/\berror\b/);
          } else {
            expect(text).toMatch(/\bare\b/);
            expect(text).toMatch(/\berrors\b/);
          }
        } finally {
          unmount();
        }
      }),
      { numRuns: 100 },
    );
  });
});
