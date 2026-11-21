/**
 * Pure text and ordering helpers for the Year-end checklist UI.
 *
 * No thresholds and no money arithmetic live here; the API supplies every
 * Reason and detail value.
 */

import type {
  ChecklistCounts,
  ChecklistItem,
  ChecklistStatus,
} from "../../api/yearEndChecklist";
import { PROPERTY_NAV } from "../navConfig";

const CARRYFORWARD_PATH = "/carryforward";
const FALLBACK_LINK_LABEL = "Open";

/** Stable partition: `needs_attention` first, then the rest, each in input order. */
export function orderItems<T extends Pick<ChecklistItem, "status">>(
  items: readonly T[],
): T[] {
  const attention = items.filter((item) => item.status === "needs_attention");
  const rest = items.filter((item) => item.status !== "needs_attention");
  return [...attention, ...rest];
}

function needsAttentionText(count: number): string {
  return count === 1 ? "1 needs attention" : `${count} need attention`;
}

/** "3 need attention, 6 done, 2 not applicable" (singular: "1 needs attention"). */
export function countsText(
  counts: Pick<ChecklistCounts, "done" | "needs_attention" | "not_applicable">,
): string {
  return [
    needsAttentionText(counts.needs_attention),
    `${counts.done} done`,
    `${counts.not_applicable} not applicable`,
  ].join(", ");
}

/**
 * Short headline for a year: "All clear" only when nothing needs attention and
 * at least one item is done; "Nothing to check" when neither applies.
 */
export function summaryHeadline(
  counts: Pick<ChecklistCounts, "done" | "needs_attention">,
): string {
  if (counts.needs_attention === 0) {
    return counts.done >= 1 ? "All clear" : "Nothing to check";
  }
  return needsAttentionText(counts.needs_attention);
}

const STATUS_LABELS: Record<ChecklistStatus, string> = {
  done: "Done",
  needs_attention: "Needs attention",
  not_applicable: "Not applicable",
};

export function statusLabel(status: ChecklistStatus): string {
  return STATUS_LABELS[status];
}

/**
 * Destination name for a checklist link: the matching `PROPERTY_NAV` label for
 * a property segment, "Carryforward" for `/carryforward`.
 */
export function linkLabel(link: string): string {
  const path = link.split(/[?#]/)[0] ?? "";
  if (path === CARRYFORWARD_PATH) return "Carryforward";
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "properties") {
    const segment = parts[2] ?? "";
    const match = PROPERTY_NAV.find((entry) => entry.segment === segment);
    if (match) return match.label;
  }
  return FALLBACK_LINK_LABEL;
}
