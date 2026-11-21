/**
 * Display text and links for activity events (Requirements 16.3, 16.10).
 */

import type {
  ActivityAction,
  ActivityEntity,
  ActivityEvent,
} from "../api/activity";

const ACTION_LABELS: Record<ActivityAction, string> = {
  create: "Created",
  update: "Updated",
  delete: "Deleted",
  restore: "Restored",
  import: "Imported",
};

const ENTITY_LABELS: Record<ActivityEntity, string> = {
  transaction: "Transaction",
  itemized_entry: "Repair entry",
  asset: "Asset",
  loan: "Loan",
  property: "Property",
  backup: "Backup",
  schedule_e: "Schedule E",
};

/** Page segment under `/properties/{id}/` that lists each entity. */
const ENTITY_SEGMENTS: Partial<Record<ActivityEntity, string>> = {
  transaction: "transactions",
  itemized_entry: "repairs",
  asset: "assets",
  loan: "loans",
};

export function actionLabel(action: ActivityAction): string {
  return ACTION_LABELS[action];
}

export function entityLabel(entity: ActivityEntity): string {
  return ENTITY_LABELS[entity];
}

/**
 * Link to the event's record with the `focus` parameter, or null when the
 * record is gone (delete) or has no page (backup, Schedule E import, or
 * missing ids).
 */
export function eventLink(
  event: Pick<ActivityEvent, "action" | "entity" | "record_id" | "property_id">,
): string | null {
  if (event.action === "delete" || !event.record_id) return null;
  const focus = `focus=${encodeURIComponent(event.record_id)}`;
  if (event.entity === "property") return `/properties?${focus}`;
  const segment = ENTITY_SEGMENTS[event.entity];
  if (!segment || !event.property_id) return null;
  return `/properties/${encodeURIComponent(event.property_id)}/${segment}?${focus}`;
}
