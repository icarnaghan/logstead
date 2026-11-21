import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FormField, Input, PageHeader, StateBlock } from "../components/ui";
import { useShellProperties } from "../components/ShellPropertiesContext";
import {
  MAX_SEARCH_LENGTH,
  MIN_SEARCH_LENGTH,
  useGlobalSearch,
  type SearchFn,
} from "../components/palette/useGlobalSearch";
import { tokenize } from "../components/palette/paletteRank";
import { SearchResults } from "../components/search/SearchResults";
import { SEARCH_ERROR_TEXT } from "../components/search/searchGroups";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/** Hits shown per group on the page (Requirement 11.6). */
export const PAGE_HITS_PER_GROUP = 25;

interface SearchPageProps {
  /** Test seam: search function. Defaults to the shared search API. */
  search?: SearchFn;
}

/**
 * Search page at `/search?q=` (Requirements 11.6, 11.7, 11.8). The field value
 * is written back to `q` with replace navigation as the user types.
 */
export default function SearchPage({ search }: SearchPageProps = {}) {
  useDocumentTitle("Search");
  const [searchParams, setSearchParams] = useSearchParams();
  const [value, setValue] = useState(() => searchParams.get("q") ?? "");
  const { properties } = useShellProperties();
  const global = useGlobalSearch(value, search, PAGE_HITS_PER_GROUP);
  const tokens = useMemo(() => tokenize(value), [value]);
  const propertyNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const p of properties) names[p.id] = p.name || p.address_text || p.id;
    return names;
  }, [properties]);

  const trimmed = value.trim();
  const active = trimmed.length >= MIN_SEARCH_LENGTH;
  const hitCount = global.groups.reduce((n, g) => n + g.hits.length, 0);
  const busy = active && global.status === "loading";
  const failed = active && global.status === "error";
  const showResults = active && global.resultQuery !== "";
  const noResults =
    active && global.status === "loaded" && hitCount === 0 && !global.truncated;

  let announcement = "";
  if (!active) announcement = "";
  else if (busy) announcement = "Searching…";
  else if (failed) announcement = SEARCH_ERROR_TEXT;
  else if (global.status === "loaded")
    announcement = hitCount === 0 ? "No results" : `${hitCount} results`;

  function onChange(next: string) {
    setValue(next);
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === "") params.delete("q");
        else params.set("q", next);
        return params;
      },
      { replace: true },
    );
  }

  return (
    <section aria-labelledby="page-heading">
      <PageHeader
        title="Search"
        description="Find properties, transactions, repairs, assets, loans and businesses."
      />
      <div className="mt-4 max-w-xl">
        <FormField
          label="Search"
          hint={`Type at least ${MIN_SEARCH_LENGTH} characters.`}
        >
          {(control) => (
            <Input
              {...control}
              type="search"
              value={value}
              maxLength={MAX_SEARCH_LENGTH}
              autoComplete="off"
              onChange={(e) => onChange(e.target.value)}
            />
          )}
        </FormField>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <div className="mt-6" aria-busy={busy}>
        {failed ? (
          <StateBlock
            kind="error"
            title={SEARCH_ERROR_TEXT}
            onRetry={global.retry}
            compact
          />
        ) : null}
        {showResults ? (
          <SearchResults
            groups={global.groups}
            truncated={global.truncated}
            tokens={tokens}
            maxPerGroup={PAGE_HITS_PER_GROUP}
            propertyNames={propertyNames}
          />
        ) : null}
        {noResults ? (
          <StateBlock kind="empty" title="No results" />
        ) : null}
      </div>
    </section>
  );
}
