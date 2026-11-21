/**
 * Pure state machine for two-key sequences such as `g` then `d`
 * (ui-polish Requirements 6.3, 6.4).
 */
import type { ShortcutDef } from "./registry";

export const SEQUENCE_TIMEOUT_MS = 1000;

export interface SequenceState {
  pending: string | null;
  at: number;
}

export const INITIAL_SEQUENCE_STATE: SequenceState = { pending: null, at: 0 };

/**
 * Feed one accepted key press. A key completing a registered sequence from a
 * live pending key fires it. Any other key clears the pending key and, when
 * it starts a sequence itself, becomes the new pending key.
 */
export function stepSequence(
  state: SequenceState,
  key: string,
  now: number,
  defs: readonly ShortcutDef[],
  timeoutMs: number,
): { state: SequenceState; fired: ShortcutDef | null } {
  const sequences = defs.filter((d) => d.keys.length === 2 && d.keys[0] !== "mod");
  if (state.pending !== null && now - state.at <= timeoutMs) {
    const fired = sequences.find((d) => d.keys[0] === state.pending && d.keys[1] === key);
    if (fired) return { state: { pending: null, at: now }, fired };
  }
  if (sequences.some((d) => d.keys[0] === key)) {
    return { state: { pending: key, at: now }, fired: null };
  }
  return { state: { pending: null, at: now }, fired: null };
}
