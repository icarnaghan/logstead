import { checklistKeys, readFlag } from "./checklistStorage";

export interface SetupState {
  dismissed: boolean;
  collapsed: boolean;
}

export const DEFAULT_SETUP_STATE: SetupState = { dismissed: false, collapsed: false };

const COLLAPSED = "logstead.checklist.collapsed";

/** Per-user keys. The dismissed key is the existing checklist key. */
export function setupKeys(userId?: string | null): {
  dismissed: string;
  collapsed: string;
} {
  const suffix = userId ? `.${userId}` : "";
  return { dismissed: checklistKeys(userId).dismissed, collapsed: `${COLLAPSED}${suffix}` };
}

/** Canonical JSON for a setup state. */
export function serializeSetupState(s: SetupState): string {
  return JSON.stringify({ dismissed: s.dismissed, collapsed: s.collapsed });
}

/** Inverse of serializeSetupState; defaults for anything else. Never throws. */
export function parseSetupState(raw: string | null): SetupState {
  if (typeof raw !== "string") return { ...DEFAULT_SETUP_STATE };
  try {
    const v: unknown = JSON.parse(raw);
    if (v && typeof v === "object") {
      const { dismissed, collapsed } = v as Record<string, unknown>;
      if (typeof dismissed === "boolean" && typeof collapsed === "boolean") {
        const state = { dismissed, collapsed };
        if (serializeSetupState(state) === raw) return state;
      }
    }
  } catch {
    // Invalid JSON; fall through to defaults.
  }
  return { ...DEFAULT_SETUP_STATE };
}

/** Reads the stored state; defaults on any storage error. */
export function readSetupState(userId?: string | null): SetupState {
  const keys = setupKeys(userId);
  try {
    return {
      dismissed: readFlag(keys.dismissed),
      collapsed: window.localStorage.getItem(keys.collapsed) === "1",
    };
  } catch {
    return { ...DEFAULT_SETUP_STATE };
  }
}

/** Applies a patch to the stored state; no-op when storage is unavailable. */
export function writeSetupState(
  userId: string | null | undefined,
  patch: Partial<SetupState>,
): void {
  const keys = setupKeys(userId);
  const apply = (key: string, value: boolean | undefined) => {
    if (value === undefined) return;
    try {
      if (value) window.localStorage.setItem(key, "1");
      else window.localStorage.removeItem(key);
    } catch {
      // Storage unavailable; ignore.
    }
  };
  apply(keys.dismissed, patch.dismissed);
  apply(keys.collapsed, patch.collapsed);
}

/** Removes both stored flags; no-op when storage is unavailable. */
export function clearSetupState(userId?: string | null): void {
  writeSetupState(userId, { dismissed: false, collapsed: false });
}
