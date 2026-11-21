import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { omitDismissed } from "./useDismissibleErrors";

const FIELDS = ["name", "amount", "date", "category", "notes", "rate"] as const;
type Field = (typeof FIELDS)[number];

describe("omitDismissed properties", () => {
  // Feature: modal-forms-and-tabbed-imports, Property 4: Editing a field dismisses exactly that field's server error
  // **Validates: Requirements 5.5**
  it("keeps exactly the non-dismissed keys with original messages and does not mutate errors", () => {
    fc.assert(
      fc.property(
        fc.dictionary(fc.constantFrom(...FIELDS), fc.string()),
        fc.subarray([...FIELDS]),
        (errors, dismissedList) => {
          const dismissed = new Set<Field>(dismissedList);
          const snapshot = { ...errors };

          const result = omitDismissed<Field>(errors, dismissed);

          const expectedKeys = Object.keys(errors)
            .filter((k) => !dismissed.has(k as Field))
            .sort();
          expect(Object.keys(result).sort()).toEqual(expectedKeys);
          for (const key of expectedKeys) {
            expect(result[key as Field]).toBe(errors[key as Field]);
          }
          expect(errors).toEqual(snapshot);
          expect(Object.keys(errors).sort()).toEqual(Object.keys(snapshot).sort());
        },
      ),
      { numRuns: 100 },
    );
  });
});
