/**
 * Shared class string for section tab `NavLink`s (property sections and
 * import methods) so both tab strips look identical.
 */
export function sectionTabClassName(isActive: boolean): string {
  return [
    "inline-block rounded-md px-3 py-1.5 text-sm font-medium max-md:inline-flex max-md:min-h-11 max-md:items-center",
    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
    isActive
      ? "bg-accent text-accent-fg"
      : "text-fg-muted hover:bg-surface-muted",
  ].join(" ");
}
