/**
 * Shortcut registry (ui-polish Requirements 6.1, 6.3, 6.4, 6.8). Pure data
 * plus two helpers. The provider resolves each `run` id to a handler.
 */
import type { Platform } from "./eligibility";

export type ShortcutActionId =
  | "openPalette"
  | "openSearch"
  | "openHelp"
  | "goDashboard"
  | "goProperties"
  | "goReports"
  | "goCarryforward"
  | "goImport"
  | "goActivity";

export interface ShortcutDef {
  id: string;
  label: string;
  group: "General" | "Go to";
  /** `"mod"` stands for Cmd on macOS and Ctrl elsewhere. */
  keys: readonly string[];
  run: ShortcutActionId;
}

export const SHORTCUTS: readonly ShortcutDef[] = [
  { id: "palette", label: "Open command palette", group: "General", keys: ["mod", "k"], run: "openPalette" },
  { id: "search", label: "Search", group: "General", keys: ["/"], run: "openSearch" },
  { id: "help", label: "Show keyboard shortcuts", group: "General", keys: ["?"], run: "openHelp" },
  { id: "go-dashboard", label: "Go to Dashboard", group: "Go to", keys: ["g", "d"], run: "goDashboard" },
  { id: "go-properties", label: "Go to Properties", group: "Go to", keys: ["g", "p"], run: "goProperties" },
  { id: "go-reports", label: "Go to Reports", group: "Go to", keys: ["g", "r"], run: "goReports" },
  { id: "go-carryforward", label: "Go to Carryforward", group: "Go to", keys: ["g", "c"], run: "goCarryforward" },
  { id: "go-import", label: "Go to Import", group: "Go to", keys: ["g", "i"], run: "goImport" },
  { id: "go-activity", label: "Go to Activity", group: "Go to", keys: ["g", "a"], run: "goActivity" },
];

/** Display tokens for a shortcut; `"mod"` becomes Cmd or Ctrl. */
export function formatKeys(def: ShortcutDef, platform: Platform): string[] {
  return def.keys.map((key) => {
    if (key === "mod") return platform === "mac" ? "Cmd" : "Ctrl";
    return key.length === 1 ? key.toUpperCase() : key;
  });
}

/** Key combinations (joined with `+`) that more than one def uses. */
export function findDuplicates(defs: readonly ShortcutDef[]): string[] {
  const seen = new Set<string>();
  const dupes = new Set<string>();
  for (const def of defs) {
    const combo = def.keys.join("+");
    if (seen.has(combo)) dupes.add(combo);
    seen.add(combo);
  }
  return [...dupes];
}
