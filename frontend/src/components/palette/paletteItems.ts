import type { Property } from "../../api/properties";
import type { Platform } from "../../lib/shortcuts/eligibility";
import { PRIMARY_NAV, PROPERTY_NAV, propertyPath } from "../navConfig";

/** Stable ids of the palette Actions (ui-polish Requirement 3.1). */
export type ActionId =
  | "add-property"
  | "add-transaction"
  | "add-repair"
  | "add-asset"
  | "add-loan"
  | "import-schedule-e"
  | "switch-theme"
  | "keyboard-shortcuts"
  | "show-setup-guide"
  | "download-backup";

export type DestinationGroup =
  | "Pages"
  | "Properties"
  | "Tax years"
  | "Property sections";

export type PaletteItem =
  | {
      kind: "destination";
      id: string;
      label: string;
      keywords: string[];
      to: string;
      group: DestinationGroup;
      hint?: string;
    }
  | {
      kind: "action";
      id: ActionId;
      label: string;
      keywords: string[];
      needsProperty: boolean;
      hint?: string;
    };

export type PropertyScopedActionId =
  | "add-transaction"
  | "add-repair"
  | "add-asset"
  | "add-loan";

const SCOPED_SEGMENTS: Record<PropertyScopedActionId, string> = {
  "add-transaction": "transactions",
  "add-repair": "repairs",
  "add-asset": "assets",
  "add-loan": "loans",
};

export const NO_PROPERTY_REASON = "Add a property first";

export interface BuildLocalItemsInput {
  properties: readonly Pick<Property, "id" | "name">[];
  /** Tax years in the portfolio year range. */
  years: readonly number[];
  /** Id of the active property route, or null outside a property route. */
  currentPropertyId: string | null;
  platform: Platform;
  /** True when the user owns at least one property. */
  hasProperty: boolean;
}

interface ActionDef {
  id: ActionId;
  label: string;
  needsProperty: boolean;
  keywords: string[];
}

const ACTIONS: readonly ActionDef[] = [
  { id: "add-property", label: "Add property", needsProperty: false, keywords: ["new", "create"] },
  { id: "add-transaction", label: "Add transaction", needsProperty: true, keywords: ["new", "income", "expense"] },
  { id: "add-repair", label: "Add repair", needsProperty: true, keywords: ["new", "maintenance"] },
  { id: "add-asset", label: "Add depreciable asset", needsProperty: true, keywords: ["new", "depreciation"] },
  { id: "add-loan", label: "Add loan", needsProperty: true, keywords: ["new", "mortgage"] },
  { id: "import-schedule-e", label: "Import Schedule E", needsProperty: false, keywords: ["upload", "pdf"] },
  { id: "switch-theme", label: "Switch theme", needsProperty: false, keywords: ["dark", "light", "appearance"] },
  { id: "keyboard-shortcuts", label: "Keyboard shortcuts", needsProperty: false, keywords: ["keys", "help"] },
  { id: "show-setup-guide", label: "Show setup guide", needsProperty: false, keywords: ["onboarding", "getting started"] },
  { id: "download-backup", label: "Download backup", needsProperty: false, keywords: ["export", "restore"] },
];

const ACTIVITY_PATH = "/activity";

/**
 * Build the local (non-server) palette items: page, property, property
 * section and tax-year Destinations, then Actions. Pure and deterministic.
 */
export function buildLocalItems({
  properties,
  years,
  currentPropertyId,
  platform,
  hasProperty,
}: BuildLocalItemsInput): PaletteItem[] {
  const items: PaletteItem[] = [];

  for (const nav of PRIMARY_NAV) {
    items.push({
      kind: "destination",
      id: `page:${nav.to}`,
      label: nav.label,
      keywords: [],
      to: nav.to,
      group: "Pages",
    });
  }
  if (!PRIMARY_NAV.some((nav) => nav.to === ACTIVITY_PATH)) {
    items.push({
      kind: "destination",
      id: `page:${ACTIVITY_PATH}`,
      label: "Activity",
      keywords: ["history", "log"],
      to: ACTIVITY_PATH,
      group: "Pages",
    });
  }

  for (const property of properties) {
    items.push({
      kind: "destination",
      id: `property:${property.id}`,
      label: property.name,
      keywords: [],
      to: propertyPath(property.id, ""),
      group: "Properties",
    });
  }

  if (currentPropertyId !== null) {
    const current = properties.find((p) => p.id === currentPropertyId);
    const name = current?.name ?? "this property";
    for (const section of PROPERTY_NAV) {
      items.push({
        kind: "destination",
        id: `section:${currentPropertyId}:${section.segment || "overview"}`,
        label: `${section.label} (${name})`,
        keywords: [section.label],
        to: propertyPath(currentPropertyId, section.segment),
        group: "Property sections",
      });
    }
  }

  for (const year of years) {
    items.push({
      kind: "destination",
      id: `year:${year}`,
      label: `Tax year ${year}`,
      keywords: [String(year)],
      to: `/reports?year=${year}`,
      group: "Tax years",
    });
  }

  for (const def of ACTIONS) {
    const item: PaletteItem = {
      kind: "action",
      id: def.id,
      label: def.label,
      keywords: def.keywords,
      needsProperty: def.needsProperty,
    };
    if (def.needsProperty && !hasProperty) {
      item.hint = NO_PROPERTY_REASON;
    } else if (def.id === "keyboard-shortcuts") {
      item.hint = "?";
    }
    items.push(item);
  }
  // Platform only changes the displayed chord, which the UI renders itself.
  void platform;
  return items;
}

export type ActionTarget =
  | { kind: "navigate"; to: string }
  | { kind: "pickProperty" }
  | { kind: "unavailable"; reason: string };

export function isPropertyScopedAction(id: ActionId): id is PropertyScopedActionId {
  return id in SCOPED_SEGMENTS;
}

/**
 * Resolve a property-scoped add action (Requirements 3.2 to 3.5): the active
 * property wins, then the only property, otherwise a picker; no property means
 * unavailable.
 */
export function resolveActionTarget(
  action: PropertyScopedActionId,
  properties: readonly Pick<Property, "id">[],
  currentPropertyId: string | null,
): ActionTarget {
  const segment = SCOPED_SEGMENTS[action];
  if (currentPropertyId !== null) {
    return { kind: "navigate", to: `${propertyPath(currentPropertyId, segment)}?new=1` };
  }
  if (properties.length === 0) {
    return { kind: "unavailable", reason: NO_PROPERTY_REASON };
  }
  if (properties.length === 1) {
    return { kind: "navigate", to: `${propertyPath(properties[0].id, segment)}?new=1` };
  }
  return { kind: "pickProperty" };
}
