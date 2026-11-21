import { Link } from "react-router-dom";
import {
  yearEndChecklistApi,
  type YearEndChecklistApi,
} from "../../api/yearEndChecklist";
import { cn } from "../../lib/cn";
import { useAsyncResource } from "../../lib/useAsyncResource";
import {
  FOCUS_RING,
  LoadingRegion,
  RefreshingIndicator,
  StateBlock,
  Tile,
  TileSkeleton,
  useFirstLoad,
} from "../ui";
import { summaryHeadline } from "./yearEndText";

const HEADING_ID = "tile-year-end-checklist";
const TITLE = "Year-end checklist";
const LOAD_ERROR = "Your year-end checklist summary did not load.";

export interface YearEndDashboardCardProps {
  /**
   * The dashboard's displayed tax year. `null` while it is still unknown
   * (trends loading): the card shows its own skeleton and does not fetch.
   */
  taxYear: number | null;
  /** Injectable API for tests; defaults to the shared instance. */
  api?: YearEndChecklistApi;
}

/**
 * Dashboard card listing each property with its needs-attention count for the
 * dashboard's tax year, each row linking to that property's checklist for the
 * year. Loads on its own, so it never waits on other dashboard requests. It
 * renders nothing when the user owns no property.
 */
export function YearEndDashboardCard({
  taxYear,
  api = yearEndChecklistApi,
}: YearEndDashboardCardProps) {
  const resource = useAsyncResource(
    (signal) => api.getPortfolioSummary(taxYear, signal),
    {
      enabled: taxYear !== null,
      deps: [taxYear, api],
      describeError: () => LOAD_ERROR,
    },
  );
  const summary = resource.data;
  const view = useFirstLoad({
    loading: resource.status === "loading" || resource.status === "refreshing",
    error: resource.error,
  });

  if (summary && summary.properties.length === 0) return null;

  // No data and no error: still waiting on the year or the first response.
  if (!summary && resource.error === null) {
    return (
      <LoadingRegion label="Loading year-end checklist">
        <TileSkeleton />
      </LoadingRegion>
    );
  }

  if (!summary) {
    return (
      <Tile title={TITLE} headingId={HEADING_ID}>
        <StateBlock
          kind="error"
          compact
          title="Could not load the year-end checklist"
          description={resource.error ?? undefined}
          onRetry={() => resource.reload()}
        />
      </Tile>
    );
  }

  return (
    <Tile title={TITLE} headingId={HEADING_ID}>
      {view.refreshing ? <RefreshingIndicator /> : null}
      {view.errorIsStale ? (
        <StateBlock
          kind="error"
          compact
          title="Could not refresh the year-end checklist"
          description={resource.error ?? undefined}
          onRetry={() => resource.reload()}
        />
      ) : null}
      <p className="text-sm text-fg-muted">Tax year {summary.tax_year}</p>
      <ul className="mt-2 divide-y divide-border">
        {summary.properties.map((property) => (
          <li
            key={property.property_id}
            className="flex items-baseline justify-between gap-4 py-2"
          >
            <Link
              to={`/properties/${encodeURIComponent(property.property_id)}/checklist?year=${summary.tax_year}`}
              className={cn(
                "rounded font-medium text-accent hover:underline",
                FOCUS_RING,
              )}
            >
              {property.property_name}
            </Link>
            <span
              className={cn(
                "text-sm",
                property.counts.needs_attention > 0
                  ? "font-medium text-fg"
                  : "text-fg-muted",
              )}
            >
              {summaryHeadline(property.counts)}
            </span>
          </li>
        ))}
      </ul>
    </Tile>
  );
}
