/**
 * Resolve the human-readable property name from the shared context, never
 * leaking the raw identifier (Requirements 2.1, 3.1).
 *
 * - `"loaded"` → the property's name.
 * - `"loading"` → a neutral placeholder while the fetch is in flight.
 * - `"error"` (or any missing name) → a neutral "Property" fallback.
 */
export function resolvePropertyName(
  status: "loading" | "loaded" | "error",
  name: string | undefined,
): string {
  if (status === "loading") return "Loading property…";
  if (status === "loaded" && name) return name;
  return "Property";
}
