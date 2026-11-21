import { PROPERTY_NAV, propertyPath } from "./navConfig";

/**
 * Pure helpers for the Property_Switcher (Requirement 19).
 */

/** Matches `/properties/{id}` optionally followed by `/{segment}[/...]`. */
const PROPERTY_ROUTE = /^\/properties\/([^/]+)(?:\/([^/]+))?(?:\/.*)?\/?$/;

/** Returns the property id for a property route, or null otherwise. */
export function propertyIdFromPath(pathname: string): string | null {
  const match = PROPERTY_ROUTE.exec(pathname);
  return match ? match[1] : null;
}

/**
 * Returns the Current_Section segment for a property route: "" for the
 * overview or an unknown segment, a known segment such as "loans" otherwise,
 * and null for non-property paths.
 */
export function sectionFromPath(pathname: string): string | null {
  const match = PROPERTY_ROUTE.exec(pathname);
  if (!match) return null;
  const segment = match[2] ?? "";
  return PROPERTY_NAV.some((item) => item.segment === segment && segment !== "")
    ? segment
    : "";
}

/**
 * Destination when switching to another property. Keeps the current section,
 * falls back to the overview on non-property routes, and carries over only
 * the `year` search parameter (Requirements 19.3, 19.4, 19.5, 19.7).
 */
export function switchPropertyPath(
  pathname: string,
  search: string,
  nextPropertyId: string,
): string {
  const base = propertyPath(nextPropertyId, sectionFromPath(pathname) ?? "");
  const year = new URLSearchParams(search).get("year");
  return year ? `${base}?year=${encodeURIComponent(year)}` : base;
}
