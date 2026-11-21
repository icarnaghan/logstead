import { describe, it, expect, beforeEach } from "vitest";
import fc from "fast-check";
import {
  computeChecklist,
  nextStep,
  stepReason,
  type ChecklistFlags,
  type StepId,
} from "./checklist";
import { readSetupState, writeSetupState } from "../../lib/onboardingStorage";

const ORDER: StepId[] = ["property", "transactions", "loanOrAsset", "report"];
const FLAG_KEYS: (keyof ChecklistFlags)[] = [
  "hasProperty",
  "hasTransactions",
  "hasLoanOrAsset",
  "visitedReport",
];

const flagsArb: fc.Arbitrary<ChecklistFlags> = fc.record({
  hasProperty: fc.boolean(),
  hasTransactions: fc.boolean(),
  hasLoanOrAsset: fc.boolean(),
  visitedReport: fc.boolean(),
});

describe("setup guide derivation", () => {
  beforeEach(() => window.localStorage.clear());

  // Feature: ui-polish-and-consistency, Property 28: Setup guide derivation
  // **Validates: Requirements 24.1, 24.2, 24.6, 24.8**
  it("nextStep is the first incomplete step, or null when all are done", () => {
    fc.assert(
      fc.property(flagsArb, fc.boolean(), (flags, dismissed) => {
        const view = computeChecklist(flags, dismissed);
        const expected = ORDER.find((_, i) => !flags[FLAG_KEYS[i]]) ?? null;
        expect(nextStep(view)).toBe(expected);
        expect(view.steps.map((s) => s.id)).toEqual(ORDER);
      }),
      { numRuns: 100 },
    );
  });

  // **Validates: Requirements 24.6, 24.8**
  it("is visible iff not dismissed and fewer than four steps are complete", () => {
    fc.assert(
      fc.property(flagsArb, fc.boolean(), (flags, dismissed) => {
        const view = computeChecklist(flags, dismissed);
        const count = FLAG_KEYS.filter((k) => flags[k]).length;
        expect(view.completed).toBe(count);
        expect(view.visible).toBe(!dismissed && count < 4);
        expect(nextStep(view) === null).toBe(count === 4);
      }),
      { numRuns: 100 },
    );
  });

  // **Validates: Requirements 24.8**
  it("setting any flag to true never decreases completed", () => {
    fc.assert(
      fc.property(
        flagsArb,
        fc.constantFrom(...FLAG_KEYS),
        fc.boolean(),
        (flags, key, dismissed) => {
          const before = computeChecklist(flags, dismissed);
          const after = computeChecklist({ ...flags, [key]: true }, dismissed);
          expect(after.completed).toBeGreaterThanOrEqual(before.completed);
        },
      ),
      { numRuns: 100 },
    );
  });

  // **Validates: Requirements 24.2, 24.8**
  it("derivation ignores stored setup state, and every step has a one-sentence reason", () => {
    fc.assert(
      fc.property(
        flagsArb,
        fc.boolean(),
        fc.boolean(),
        (flags, dismissed, collapsed) => {
          const baseline = nextStep(computeChecklist(flags, false));
          writeSetupState("u1", { dismissed, collapsed });
          expect(readSetupState("u1")).toEqual({ dismissed, collapsed });
          expect(nextStep(computeChecklist(flags, dismissed))).toBe(baseline);
          window.localStorage.clear();
        },
      ),
      { numRuns: 50 },
    );
    for (const id of ORDER) {
      const reason = stepReason(id);
      expect(reason.trim().length).toBeGreaterThan(0);
      expect(reason.match(/[.!?]/g)).toHaveLength(1);
      expect(reason.endsWith(".")).toBe(true);
    }
  });
});
