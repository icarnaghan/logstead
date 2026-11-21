import { describe, it, expect } from "vitest";
import * as fc from "fast-check";

import { isEligiblePlainKey, isPaletteChord } from "./eligibility";
import type { KeyEventInfo, Platform, TargetKind } from "./eligibility";

/**
 * Property-based tests for shortcut eligibility. The oracles below are written
 * as independent truth tables over the event fields, not by re-using the
 * implementation's helpers.
 */

const keyEventArb: fc.Arbitrary<KeyEventInfo> = fc.record({
  key: fc.constantFrom("k", "K", "j", "g", "/", "?", "Enter", " ", "Dead", "Escape"),
  keyCode: fc.constantFrom(0, 75, 191, 229, 13),
  target: fc.constantFrom<TargetKind>("editable", "interactive", "other"),
  alt: fc.boolean(),
  ctrl: fc.boolean(),
  meta: fc.boolean(),
  shift: fc.boolean(),
  isComposing: fc.boolean(),
  repeat: fc.boolean(),
  defaultPrevented: fc.boolean(),
  blockingDialogOpen: fc.boolean(),
});

const platformArb = fc.constantFrom<Platform>("mac", "other");

/** Blockers for a plain key, listed one per reason. */
function plainKeyBlockers(e: KeyEventInfo): boolean[] {
  return [
    e.target === "editable",
    e.blockingDialogOpen,
    e.alt,
    e.ctrl,
    e.meta,
    e.isComposing,
    e.keyCode === 229,
    e.repeat,
    e.defaultPrevented,
  ];
}

describe("eligibility property tests", () => {
  // Feature: ui-polish, Property 1: Plain-key shortcut eligibility
  // **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.10**
  it("Property 1: a plain key is eligible iff no blocker applies, regardless of Shift", () => {
    fc.assert(
      fc.property(keyEventArb, (e) => {
        const expected = plainKeyBlockers(e).every((blocked) => !blocked);
        expect(isEligiblePlainKey(e)).toBe(expected);
        expect(isEligiblePlainKey({ ...e, shift: !e.shift })).toBe(expected);
      }),
      { numRuns: 200 },
    );
  });

  // Feature: ui-polish, Property 2: Palette chord eligibility
  // **Validates: Requirements 1.1, 1.7, 1.8**
  it("Property 2: the chord is Meta+K on mac or Ctrl+K elsewhere, unaffected by target kind", () => {
    fc.assert(
      fc.property(keyEventArb, platformArb, (e, platform) => {
        const isK = e.key === "k" || e.key === "K";
        const modifierOk = platform === "mac" ? e.meta && !e.ctrl : e.ctrl && !e.meta;
        // The implementation also refuses Alt, repeats and already-handled events.
        const expected =
          isK &&
          modifierOk &&
          !e.blockingDialogOpen &&
          !e.isComposing &&
          e.keyCode !== 229 &&
          !e.alt &&
          !e.repeat &&
          !e.defaultPrevented;
        expect(isPaletteChord(e, platform)).toBe(expected);
        for (const target of ["editable", "interactive", "other"] as const) {
          expect(isPaletteChord({ ...e, target }, platform)).toBe(expected);
        }
      }),
      { numRuns: 200 },
    );
  });
});
