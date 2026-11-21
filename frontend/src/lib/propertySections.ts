import {
  PROPERTY_NAV,
  propertyPath,
  type PropertyNavItem,
} from "../components/navConfig";

function stripTrailingSlash(path: string): string {
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

/**
 * Resolve which property section a pathname belongs to.
 *
 * Compares the pathname (without a trailing slash) with each `PROPERTY_NAV`
 * entry's path, preferring the longest match. The empty-segment Overview entry
 * matches exactly only. Returns `null` for a path outside the property.
 */
export function currentSection(
  pathname: string,
  propertyId: string,
): PropertyNavItem | null {
  const path = stripTrailingSlash(pathname);
  let best: PropertyNavItem | null = null;
  let bestLength = -1;
  for (const item of PROPERTY_NAV) {
    const base = propertyPath(propertyId, item.segment);
    const matches =
      path === base ||
      (item.segment !== "" && !item.end && path.startsWith(`${base}/`));
    if (matches && base.length > bestLength) {
      best = item;
      bestLength = base.length;
    }
  }
  return best;
}
