import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  activityApi,
  type ActivityAction,
  type ActivityEntity,
  type ActivityEvent,
} from "../api/activity";
import { ActivityList } from "../components/activity/ActivityList";
import { useShellProperties } from "../components/ShellPropertiesContext";
import {
  Button,
  FormField,
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  Select,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
} from "../components/ui";
import { actionLabel, entityLabel } from "../lib/activityText";
import { useDocumentTitle } from "../lib/useDocumentTitle";

const PAGE_SIZE = 25;
const ENTITIES: readonly ActivityEntity[] = [
  "transaction",
  "itemized_entry",
  "asset",
  "loan",
  "property",
  "backup",
  "schedule_e",
];
const ACTIONS: readonly ActivityAction[] = [
  "create",
  "update",
  "delete",
  "restore",
  "import",
];

/**
 * Activity page at `/activity` (Requirements 16.1, 16.3, 16.5, 16.7, 16.8,
 * 16.9). The property filter is mirrored in the `property` query parameter.
 */
export default function ActivityPage() {
  useDocumentTitle("Activity");
  const [searchParams, setSearchParams] = useSearchParams();
  const propertyId = searchParams.get("property") ?? "";
  const { properties } = useShellProperties();
  const [entity, setEntity] = useState<ActivityEntity | "">("");
  const [action, setAction] = useState<ActivityAction | "">("");
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastAfter = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(
    async (after: string | null) => {
      controller.current?.abort();
      const ctl = new AbortController();
      controller.current = ctl;
      const more = after !== null;
      lastAfter.current = after;
      setError(null);
      if (more) setLoadingMore(true);
      else setLoading(true);
      try {
        const params = {
          limit: PAGE_SIZE,
          cursor: after,
          entity: entity || null,
          action: action || null,
          signal: ctl.signal,
        };
        const page = propertyId
          ? await activityApi.listForProperty(propertyId, params)
          : await activityApi.list(params);
        if (ctl.signal.aborted) return;
        const incoming = page.events ?? [];
        setEvents((prev) => (more ? [...prev, ...incoming] : incoming));
        setCursor(page.next_cursor ?? null);
        setLoading(false);
        setLoadingMore(false);
      } catch {
        if (ctl.signal.aborted) return;
        setError(
          more
            ? "Could not load more activity."
            : "Could not load activity.",
        );
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [propertyId, entity, action],
  );

  useEffect(() => {
    void load(null);
    return () => controller.current?.abort();
  }, [load]);

  const announcement =
    loading || loadingMore || error !== null
      ? ""
      : `${events.length} ${events.length === 1 ? "event" : "events"}`;

  const view = useFirstLoad({ loading, error });

  function onPropertyChange(next: string) {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === "") params.delete("property");
        else params.set("property", next);
        return params;
      },
      { replace: true },
    );
  }

  const showEmpty = view.showContent && !loading && !error && events.length === 0;

  return (
    <section aria-labelledby="page-heading">
      <PageHeader
        title="Activity"
        description="A history of changes to your records."
      />
      <div className="mt-4 flex flex-wrap gap-4">
        <FormField label="Property">
          {(control) => (
            <Select
              {...control}
              value={propertyId}
              onChange={(e) => onPropertyChange(e.target.value)}
            >
              <option value="">All properties</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name || p.address_text || p.id}
                </option>
              ))}
            </Select>
          )}
        </FormField>
        <FormField label="Record type">
          {(control) => (
            <Select
              {...control}
              value={entity}
              onChange={(e) => setEntity(e.target.value as ActivityEntity | "")}
            >
              <option value="">All types</option>
              {ENTITIES.map((value) => (
                <option key={value} value={value}>
                  {entityLabel(value)}
                </option>
              ))}
            </Select>
          )}
        </FormField>
        <FormField label="Action">
          {(control) => (
            <Select
              {...control}
              value={action}
              onChange={(e) => setAction(e.target.value as ActivityAction | "")}
            >
              <option value="">All actions</option>
              {ACTIONS.map((value) => (
                <option key={value} value={value}>
                  {actionLabel(value)}
                </option>
              ))}
            </Select>
          )}
        </FormField>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      <div className="mt-6" aria-busy={loading || loadingMore}>
        {view.showSkeleton ? (
          <LoadingRegion label="Loading activity">
            <TableSkeleton columns={3} />
          </LoadingRegion>
        ) : null}
        {view.showError ? (
          <div className="mb-4">
            <StateBlock
              kind="error"
              title={error ?? "Could not load activity."}
              onRetry={() => load(lastAfter.current)}
              compact={view.errorIsStale}
            />
          </div>
        ) : null}
        {view.refreshing ? <RefreshingIndicator /> : null}
        {showEmpty ? (
          <StateBlock
            kind="empty"
            title="No activity yet"
            description="Events appear after you add or change records. History is kept for 24 months."
          />
        ) : null}
        {view.showContent && events.length > 0 ? (
          <>
            <ActivityList events={events} label="Activity events" />
            {cursor ? (
              <div className="mt-4 text-center">
                <Button
                  variant="secondary"
                  loading={loadingMore}
                  onClick={() => void load(cursor)}
                >
                  Load more
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </section>
  );
}
