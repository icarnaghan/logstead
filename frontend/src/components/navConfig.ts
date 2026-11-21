/**
 * Central navigation model for the app shell.
 *
 * Keeping the top-level items and the per-property sub-sections in one place
 * lets the desktop nav, the mobile nav, and the per-property sub-navigation
 * stay in sync (Requirement 14.1: a consistent navigation structure across
 * Dashboard, Properties, Transactions, Repairs, Depreciable Assets, and
 * Schedule E Reports).
 */

/** Names of the icons available to primary navigation items. */
export type NavIconName =
  | "dashboard"
  | "properties"
  | "businesses"
  | "reports"
  | "carryforward"
  | "import"
  | "activity";

/** A top-level destination in the primary navigation. */
export interface NavItem {
  /** Route path (used as a react-router `NavLink` target). */
  readonly to: string;
  /** Human-readable label shown in the nav and used as the accessible name. */
  readonly label: string;
  /**
   * When true, the active-state match must be exact. Used for the dashboard
   * ("/") so it is not marked active for every nested route.
   */
  readonly end?: boolean;
  /** Decorative icon shown next to the label in the primary nav. */
  readonly icon?: NavIconName;
}

/** A per-property sub-section (rendered once a property is selected). */
export interface PropertyNavItem {
  /** Path segment appended to `/properties/:propertyId`. Empty = the index. */
  readonly segment: string;
  /** Human-readable label. */
  readonly label: string;
  /**
   * When true, the active-state match must be exact. Used for the Overview
   * (index) entry so it is not marked active on sub-routes. Mirrors
   * `NavItem.end`.
   */
  readonly end?: boolean;
}

/** A labelled group of primary navigation destinations. */
export interface NavGroup {
  readonly id: "portfolio" | "tax" | "tools";
  readonly label: string;
  readonly items: readonly NavItem[];
}

/** Primary navigation, organised by purpose (Requirement 18.1, 18.2). */
export const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: "portfolio",
    label: "Portfolio",
    items: [
      { to: "/", label: "Dashboard", end: true, icon: "dashboard" },
      { to: "/properties", label: "Properties", icon: "properties" },
      { to: "/businesses", label: "Businesses", icon: "businesses" },
    ],
  },
  {
    id: "tax",
    label: "Tax",
    items: [
      { to: "/reports", label: "Reports", icon: "reports" },
      { to: "/carryforward", label: "Carryforward", icon: "carryforward" },
      { to: "/accountant-package", label: "Accountant package", icon: "reports" },
    ],
  },
  {
    id: "tools",
    label: "Tools",
    items: [
      { to: "/imports/schedule-e", label: "Import", icon: "import" },
      { to: "/activity", label: "Activity", icon: "activity" },
    ],
  },
];

/** Primary, always-visible navigation destinations (flattened groups). */
export const PRIMARY_NAV: readonly NavItem[] = NAV_GROUPS.flatMap(
  (g) => g.items,
);

/** Tabs of the Imports section (Enter manually first, then Upload PDF). */
export const IMPORT_NAV: readonly NavItem[] = [
  { to: "/imports/schedule-e", label: "Enter manually", end: true },
  { to: "/imports/schedule-e/extract", label: "Upload PDF" },
];

/** Sub-sections available under a selected property (Overview first). */
export const PROPERTY_NAV: readonly PropertyNavItem[] = [
  { segment: "", label: "Overview", end: true },
  { segment: "transactions", label: "Transactions" },
  { segment: "repairs", label: "Repairs" },
  { segment: "assets", label: "Depreciable Assets" },
  { segment: "loans", label: "Loans" },
  { segment: "reports", label: "Schedule E Report" },
  { segment: "checklist", label: "Checklist" },
];

/**
 * Build the absolute path for a property sub-section. An empty segment yields
 * the clean property index path (`/properties/{id}`) with no trailing slash;
 * non-empty segments append `/{segment}` as before.
 */
export function propertyPath(propertyId: string, segment: string): string {
  return segment
    ? `/properties/${propertyId}/${segment}`
    : `/properties/${propertyId}`;
}
