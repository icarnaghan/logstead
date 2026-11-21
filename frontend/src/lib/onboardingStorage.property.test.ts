import { afterEach, describe, expect, it, vi } from "vitest";
import fc from "fast-check";
import {
  DEFAULT_SETUP_STATE,
  clearSetupState,
  parseSetupState,
  readSetupState,
  serializeSetupState,
  setupKeys,
  writeSetupState,
  type SetupState,
} from "./onboardingStorage";
import { checklistKeys } from "./checklistStorage";

const stateArb: fc.Arbitrary<SetupState> = fc.record({
  dismissed: fc.boolean(),
  collapsed: fc.boolean(),
});

describe("onboardingStorage properties", () => {
  // Feature: ui-polish, Property 29: Setup state round trip
  // **Validates: Requirements 26.5, 26.7**
  it("round trips every setup state", () => {
    fc.assert(
      fc.property(stateArb, (s) => {
        expect(parseSetupState(serializeSetupState(s))).toEqual(s);
      }),
      { numRuns: 100 },
    );
  });

  // Feature: ui-polish, Property 29: Setup state round trip
  // **Validates: Requirements 26.5, 26.7**
  it("returns defaults, without throwing, for any non-serialization", () => {
    const canonical = new Set(
      [true, false].flatMap((d) =>
        [true, false].map((c) => serializeSetupState({ dismissed: d, collapsed: c })),
      ),
    );
    const rawArb = fc.oneof(
      fc.string(),
      fc.json(),
      fc.constant(null),
      stateArb.map((s) => JSON.stringify({ ...s, extra: 1 })),
      stateArb.map((s) => ` ${serializeSetupState(s)}`),
      stateArb.map((s) => JSON.stringify({ collapsed: s.collapsed, dismissed: s.dismissed })),
      stateArb.map((s) => JSON.stringify({ dismissed: s.dismissed ? 1 : 0, collapsed: "no" })),
    );
    fc.assert(
      fc.property(
        rawArb.filter((r) => r === null || !canonical.has(r)),
        (raw) => {
          expect(parseSetupState(raw)).toEqual(DEFAULT_SETUP_STATE);
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe("onboardingStorage examples", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("reuses the existing checklist dismissed key", () => {
    expect(setupKeys("u1").dismissed).toBe(checklistKeys("u1").dismissed);
    expect(setupKeys().dismissed).toBe(checklistKeys().dismissed);
  });

  it("reads an existing dismissed flag written by the checklist", () => {
    window.localStorage.setItem(checklistKeys("u1").dismissed, "1");
    expect(readSetupState("u1")).toEqual({ dismissed: true, collapsed: false });
    expect(readSetupState("u2")).toEqual(DEFAULT_SETUP_STATE);
  });

  it("writes, reads and clears state", () => {
    writeSetupState("u1", { collapsed: true });
    expect(readSetupState("u1")).toEqual({ dismissed: false, collapsed: true });
    clearSetupState("u1");
    expect(readSetupState("u1")).toEqual(DEFAULT_SETUP_STATE);
  });

  it("falls back to defaults and does not throw when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readSetupState("u1")).toEqual(DEFAULT_SETUP_STATE);
    expect(() => writeSetupState("u1", { dismissed: true, collapsed: true })).not.toThrow();
    expect(() => clearSetupState("u1")).not.toThrow();
  });
});
