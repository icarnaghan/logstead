import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { checklistKeys } from "./checklistStorage";

const userId = fc.string({ minLength: 1, maxLength: 40 });

// Feature: ui-polish-and-consistency, Property 25: Checklist storage keys are per user
describe("checklistKeys property", () => {
  it("gives distinct users disjoint keys that contain their id", () => {
    // **Validates: Requirements 24.7**
    fc.assert(
      fc.property(
        fc.tuple(userId, userId).filter(([a, b]) => a !== b),
        ([idA, idB]) => {
          const a = checklistKeys(idA);
          const b = checklistKeys(idB);
          expect(new Set([a.visited, a.dismissed, b.visited, b.dismissed]).size).toBe(4);
          expect(a.visited).toContain(idA);
          expect(a.dismissed).toContain(idA);
          expect(b.visited).toContain(idB);
          expect(b.dismissed).toContain(idB);
        },
      ),
      { numRuns: 100 },
    );
  });

  it("is stable for the same user", () => {
    // **Validates: Requirements 24.7**
    fc.assert(
      fc.property(userId, (id) => {
        expect(checklistKeys(id)).toEqual(checklistKeys(id));
      }),
      { numRuns: 100 },
    );
  });

  it("uses unsuffixed names when there is no user id", () => {
    // **Validates: Requirements 24.7**
    const expected = {
      visited: "logstead.checklist.visitedReport",
      dismissed: "logstead.checklist.dismissed",
    };
    fc.assert(
      fc.property(fc.constantFrom(undefined, null, ""), (id) => {
        expect(checklistKeys(id)).toEqual(expected);
      }),
      { numRuns: 100 },
    );
  });
});
