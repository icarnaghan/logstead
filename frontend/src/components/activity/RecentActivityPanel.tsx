import { Link } from "react-router-dom";
import {
  activityApi,
  type ActivityListParams,
  type ActivityPage,
} from "../../api/activity";
import { cn } from "../../lib/cn";
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
import { ActivityList } from "./ActivityList";

const PANEL_LIMIT = 5;

export interface RecentActivityPanelProps {
  propertyId: string;
  /** Test seam: property activity loader. Defaults to the real API module. */
  loadActivity?: (
    propertyId: string,
    params?: ActivityListParams,
  ) => Promise<ActivityPage>;
}

/**
 * "Recent activity" panel for the property Overview (Requirements 16.6, 16.7,
 * 16.8): the latest 5 events and a link to the full page filtered to this
 * property. Loads independently, so a failure leaves the tiles usable.
 */
export function RecentActivityPanel({
  propertyId,
  loadActivity = (id, params) => activityApi.listForProperty(id, params),
}: RecentActivityPanelProps) {
  const { data, error, status, reload } = useAsyncResource(
    (signal) => loadActivity(propertyId, { limit: PANEL_LIMIT, signal }),
    {
      resetKeys: [propertyId],
      enabled: propertyId !== "",
      describeError: () => "Could not load recent activity.",
    },
  );
  const view = useFirstLoad({
    loading: status === "loading" || status === "refreshing",
    error,
    resetKey: propertyId,
  });
  const events = (data?.events ?? []).slice(0, PANEL_LIMIT);
  return (
    <section aria-labelledby="recent-activity-heading" className="mt-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2
            id="recent-activity-heading"
            className="text-base font-semibold text-fg"
          >
            Recent activity
          </h2>
          <Link
            to={`/activity?property=${encodeURIComponent(propertyId)}`}
            className={cn(
              "rounded text-sm font-medium text-accent hover:underline",
              FOCUS_RING,
            )}
          >
            View all activity
          </Link>
        </div>
        {view.showSkeleton ? (
          <LoadingRegion label="Loading recent activity" className="mt-3">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="mt-2 h-5 w-2/3" />
          </LoadingRegion>
        ) : null}
        {view.showError ? (
          <div className="mt-3">
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load recent activity"
              description={error ?? undefined}
              onRetry={reload}
            />
          </div>
        ) : null}
        {view.refreshing ? <RefreshingIndicator className="mt-3" /> : null}
        {view.showContent && data ? (
          events.length === 0 ? (
            <div className="mt-3">
              <StateBlock
                kind="empty"
                compact
                title="No activity yet"
                description="Events appear after you add or change records. History is kept for 24 months."
              />
            </div>
          ) : (
            <div className="mt-3">
              <ActivityList events={events} label="Recent activity events" />
            </div>
          )
        ) : null}
      </Card>
    </section>
  );
}
