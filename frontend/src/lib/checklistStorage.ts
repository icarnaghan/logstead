import { useEffect } from "react";
import { getUserProfile } from "./auth";

const VISITED = "logstead.checklist.visitedReport";
const DISMISSED = "logstead.checklist.dismissed";

/** Per-user localStorage keys; no suffix without a user id (Requirement 24.7). */
export function checklistKeys(userId?: string | null): {
  visited: string;
  dismissed: string;
} {
  const suffix = userId ? `.${userId}` : "";
  return { visited: `${VISITED}${suffix}`, dismissed: `${DISMISSED}${suffix}` };
}

/** Reads a flag; false on any storage error. */
export function readFlag(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

/** Writes a flag; no-op when storage is unavailable (Requirement 24.8). */
export function writeFlag(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // Storage unavailable; ignore.
  }
}

/** Marks the Schedule E report step as visited on mount. */
export function useMarkReportVisited(): void {
  useEffect(() => {
    writeFlag(checklistKeys(getUserProfile()?.sub).visited);
  }, []);
}
