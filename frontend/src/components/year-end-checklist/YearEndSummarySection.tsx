import { Link } from "react-router-dom";
import {
  yearEndChecklistApi,
  type PropertyChecklistSummary,
} from "../../api/yearEndChecklist";
import { ApiError } from "../../api/properties";
import { useAsyncResource } from "../../lib/useAsyncResource";
import {
  Card,
  FOCUS_RING,
  LoadingRegion,
  RefreshingIndicator,
  Skeleton,
  StateBlock,
  useFirstLoad,
} from "../ui";
import { cn } from "../../lib/cn";
import { propertyPath } from "../navConfig";
import { countsText, summaryHeadline } from "./yearEndText";

export interface YearEndSummarySectionProps {
  propertyId: string;
  /** Test seam: summary loader. Defaults to the real API module. */
  loadSummary?: (
    propertyId: string,
    signal?: AbortSignal,
  ) => Promise<PropertyChecklistSummary>;
}

/**
 * "Year-end checklist" summary for the property page: one row per recent
 * year with its headline and counts, each linking to that year's checklist.
 * Loads independently, so a failure here leaves the rest of the page usable.
 */
export function YearEndSummarySection({
  propertyId,
  loadSummary = (id, signal) => yearEndChecklistApi.getPropertySummary(id, signal),
}: YearEndSummarySectionProps) {
  const { data, error, status, reload } = useAsyncResource(
    (signal) => loadSummary(propertyId, signal),
    {
      resetKeys: [propertyId],
      enabled: propertyId !== "",
      describeError: (err) =>
        err instanceof ApiError
          ? err.message
          : "Could not load the year-end checklist.",
    },
  );
  const view = useFirstLoad({
    loading: status === "loading" || status === "refreshing",
    error,
    resetKey: propertyId,
  });

  return (
    <section aria-labelledby="year-end-summary-heading" className="mt-4">
      <Card className="p-4">
        <h2
          id="year-end-summary-heading"
          className="text-base font-semibold text-fg"
        >
          Year-end checklist
        </h2>

        {view.showSkeleton ? (
          <LoadingRegion label="Loading year-end checklist" className="mt-3">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="mt-2 h-5 w-2/3" />
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <div className="mt-3">
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load the year-end checklist"
              description={error ?? undefined}
              onRetry={reload}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mt-3" /> : null}

        {view.showContent && data ? (
          data.years.length === 0 ? (
            <div className="mt-3">
              <StateBlock
                kind="empty"
                title="No years to check yet"
                description="Add transactions to start a year-end checklist."
                action={{
                  label: "Go to Transactions",
                  to: propertyPath(propertyId, "transactions"),
                }}
              />
            </div>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {data.years.map((year) => (
                <li
                  key={year.tax_year}
                  className="flex flex-wrap items-center justify-between gap-2 py-2"
                >
                  <div>
                    <span className="font-medium text-fg">{year.tax_year}</span>
                    <span className="ml-2 text-sm font-medium text-fg">
                      {summaryHeadline(year.counts)}
                    </span>
                    <p className="text-sm text-fg-muted">
                      {countsText(year.counts)}
                    </p>
                  </div>
                  <Link
                    to={`${propertyPath(propertyId, "checklist")}?year=${year.tax_year}`}
                    aria-label={`Open ${year.tax_year} checklist`}
                    className={cn("rounded text-sm font-medium text-accent", FOCUS_RING)}
                  >
                    Open checklist
                  </Link>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </Card>
    </section>
  );
}
