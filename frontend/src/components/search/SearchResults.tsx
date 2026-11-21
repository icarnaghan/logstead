import { Link } from "react-router-dom";
import type { SearchGroup } from "../../api/search";
import { isSafeAppLink } from "../../lib/safeLink";
import { HighlightedText } from "./HighlightedText";
import { groupLabel, orderedGroups, TRUNCATION_NOTICE } from "./searchGroups";

export interface SearchResultsProps {
  groups: readonly SearchGroup[];
  truncated: boolean;
  /** Search tokens used to highlight matches. */
  tokens: readonly string[];
  /** Hits shown per group. */
  maxPerGroup?: number;
  /** Property names by id, for property-scoped hits. */
  propertyNames?: Readonly<Record<string, string>>;
}

/**
 * Grouped hit list shared by the search page. Titles render as text with
 * `mark` highlights; a hit links only when its link is a safe app path.
 */
export function SearchResults({
  groups,
  truncated,
  tokens,
  maxPerGroup = 25,
  propertyNames = {},
}: SearchResultsProps) {
  return (
    <div className="space-y-6">
      {truncated ? (
        <p className="text-sm text-fg-muted">{TRUNCATION_NOTICE}</p>
      ) : null}
      {orderedGroups(groups).map((group) => (
        <section key={group.kind} aria-label={groupLabel(group.kind)}>
          <h2 className="text-sm font-semibold text-fg">
            {groupLabel(group.kind)}{" "}
            <span className="font-normal text-fg-muted">({group.total})</span>
          </h2>
          <ul className="mt-2 divide-y divide-border rounded-md border border-border">
            {group.hits.slice(0, maxPerGroup).map((hit) => {
              const body = (
                <>
                  <span className="block text-sm text-fg">
                    <HighlightedText text={hit.title} tokens={tokens} />
                  </span>
                  <span className="block text-xs text-fg-muted">
                    {[
                      hit.property_id ? propertyNames[hit.property_id] : null,
                      hit.subtitle,
                      hit.amount,
                      hit.date,
                    ]
                      .filter((part): part is string => Boolean(part))
                      .join(" · ")}
                  </span>
                </>
              );
              return (
                <li key={`${hit.kind}:${hit.id}`}>
                  {isSafeAppLink(hit.link) ? (
                    <Link
                      to={hit.link}
                      className="block px-3 py-2 hover:bg-surface-muted"
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className="px-3 py-2">{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
