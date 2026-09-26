/**
 * Central navigation model for the app shell.
 *
 * Keeping the top-level items and the per-property sub-sections in one place
 * lets the desktop nav, the mobile nav, and the per-property sub-navigation
 * stay in sync (Requirement 14.1: a consistent navigation structure across
 * Dashboard, Properties, Transactions, Depreciable Assets, and Schedule E
 * Reports).
 */

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
}

/** A per-property sub-section (rendered once a property is selected). */
export interface PropertyNavItem {
  /** Path segment appended to `/properties/:propertyId`. */
  readonly segment: string;
  /** Human-readable label. */
  readonly label: string;
}

/** Primary, always-visible navigation destinations. */
export const PRIMARY_NAV: readonly NavItem[] = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/properties", label: "Properties" },
  { to: "/reports", label: "Reports" },
];

/** Sub-sections available under a selected property. */
export const PROPERTY_NAV: readonly PropertyNavItem[] = [
  { segment: "transactions", label: "Transactions" },
  { segment: "assets", label: "Depreciable Assets" },
  { segment: "reports", label: "Schedule E Report" },
];

/** Build the absolute path for a property sub-section. */
export function propertyPath(propertyId: string, segment: string): string {
  return `/properties/${propertyId}/${segment}`;
}
