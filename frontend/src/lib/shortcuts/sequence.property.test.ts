import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { SHORTCUTS } from "./registry";
import { INITIAL_SEQUENCE_STATE, SEQUENCE_TIMEOUT_MS, stepSequence } from "./sequence";

const KEYS = ["g", "d", "p", "r", "c", "i", "a", "x", "/", "?", "Enter"];
const pairs = SHORTCUTS.filter((d) => d.keys.length === 2 && d.keys[0] !== "mod");

const streamArb = fc.array(
  fc.record({
    key: fc.constantFrom(...KEYS),
    delta: fc.oneof(
      fc.integer({ min: 0, max: SEQUENCE_TIMEOUT_MS }),
      fc.integer({ min: SEQUENCE_TIMEOUT_MS + 1, max: 5000 }),
    ),
  }),
  { maxLength: 40 },
);

describe("Property 3: Sequence matcher", () => {
  /**
   * **Validates: Requirements 6.3, 6.4**
   */
  it("fires a sequence iff the previous accepted key is its first key, within the timeout", () => {
    fc.assert(
      fc.property(streamArb, (stream) => {
        let state = INITIAL_SEQUENCE_STATE;
        // Independent oracle: the previous key still waiting for a second key.
        let prev: { key: string; at: number } | null = null;
        let now = 0;
        for (const { key, delta } of stream) {
          now += delta;
          const result = stepSequence(state, key, now, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
          const expected =
            prev !== null && now - prev.at <= SEQUENCE_TIMEOUT_MS
              ? pairs.find((d) => d.keys[0] === prev!.key && d.keys[1] === key)
              : undefined;
          expect(result.fired?.id).toBe(expected?.id);
          if (result.fired) {
            expect(result.fired.keys).toEqual([prev!.key, key]);
            prev = null;
            expect(result.state.pending).toBeNull();
          } else if (pairs.some((d) => d.keys[0] === key)) {
            prev = { key, at: now };
            expect(result.state.pending).toBe(key);
          } else {
            prev = null;
            expect(result.state.pending).toBeNull();
          }
          state = result.state;
        }
      }),
      { numRuns: 200 },
    );
  });

  it("never fires without a pending key, and never fires an unregistered pair", () => {
    fc.assert(
      fc.property(fc.constantFrom(...KEYS), fc.constantFrom(...KEYS), (a, b) => {
        const first = stepSequence(INITIAL_SEQUENCE_STATE, a, 0, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
        expect(first.fired).toBeNull();
        const second = stepSequence(first.state, b, 1, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
        const registered = pairs.some((d) => d.keys[0] === a && d.keys[1] === b);
        expect(second.fired !== null).toBe(registered);
      }),
    );
  });

  it("examples: g d fires, late d does not, interposed key cancels", () => {
    const g = stepSequence(INITIAL_SEQUENCE_STATE, "g", 100, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
    expect(g.state.pending).toBe("g");
    expect(stepSequence(g.state, "d", 1100, SHORTCUTS, SEQUENCE_TIMEOUT_MS).fired?.run).toBe("goDashboard");
    const late = stepSequence(g.state, "d", 1101, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
    expect(late.fired).toBeNull();
    expect(late.state.pending).toBeNull();
    const x = stepSequence(g.state, "x", 200, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
    expect(stepSequence(x.state, "d", 300, SHORTCUTS, SEQUENCE_TIMEOUT_MS).fired).toBeNull();
    const gg = stepSequence(g.state, "g", 200, SHORTCUTS, SEQUENCE_TIMEOUT_MS);
    expect(gg.state.pending).toBe("g");
  });
});
