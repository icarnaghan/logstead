import type { SearchGroup } from "../../api/search";

/** Display label per search kind (ui-polish Requirement 11.2). */
const GROUP_LABELS: Record<string, string> = {
  property: "Properties",
  transaction: "Transactions",
  itemized_entry: "Repairs",
  asset: "Assets",
  loan: "Loans",
  business: "Businesses",
};

/** Display order of the groups. */
const GROUP_ORDER = Object.keys(GROUP_LABELS);

export const TRUNCATION_NOTICE =
  "Results may be incomplete because your data is large. Narrow your search.";

export const SEARCH_ERROR_TEXT = "Search is unavailable. Try again.";

export function groupLabel(kind: string): string {
  return GROUP_LABELS[kind] ?? kind;
}

/** Groups with at least one hit or a positive total, in display order. */
export function orderedGroups(groups: readonly SearchGroup[]): SearchGroup[] {
  const rank = (kind: string) => {
    const i = GROUP_ORDER.indexOf(kind);
    return i < 0 ? GROUP_ORDER.length : i;
  };
  return groups
    .filter((g) => g.hits.length > 0)
    .slice()
    .sort((a, b) => rank(a.kind) - rank(b.kind));
}
