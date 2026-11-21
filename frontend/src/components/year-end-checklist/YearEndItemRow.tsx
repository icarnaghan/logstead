import { Link } from "react-router-dom";
import type { ChecklistItem } from "../../api/yearEndChecklist";
import { Button, FOCUS_RING } from "../ui";
import { cn } from "../../lib/cn";
import { YearEndItemDetails } from "./YearEndItemDetails";
import { YearEndStatusBadge } from "./YearEndStatusBadge";
import { linkLabel } from "./yearEndText";

function hasDetails(details: ChecklistItem["details"]): boolean {
  return details !== null && details !== undefined && Object.keys(details).length > 0;
}

/**
 * One checklist entry as a list item: title, status badge, Reason, a link to
 * the page that fixes it, and a collapsed disclosure for `details`.
 * Renders only API-supplied text; it holds no thresholds and does no math.
 */
export function YearEndItemRow({ item }: { item: ChecklistItem }) {
  const destination = linkLabel(item.link);
  return (
    <li className="rounded-lg border border-border bg-surface p-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-fg">{item.title}</h2>
        <YearEndStatusBadge status={item.status} />
      </div>
      <p className="mt-2 text-sm text-fg-muted">{item.reason}</p>
      <div className="mt-3">
        <Button asChild variant="secondary" size="sm">
          <Link to={item.link} aria-label={`${destination}: ${item.title}`}>
            {destination}
          </Link>
        </Button>
      </div>
      {hasDetails(item.details) ? (
        <details className="group mt-3">
          <summary
            className={cn(
              "cursor-pointer list-none rounded text-sm font-medium text-accent",
              FOCUS_RING,
            )}
          >
            <span className="group-open:hidden">Show details</span>
            <span className="hidden group-open:inline">Hide details</span>
            <span className="sr-only"> for {item.title}</span>
          </summary>
          <div className="mt-2">
            <YearEndItemDetails itemId={item.id} details={item.details} />
          </div>
        </details>
      ) : null}
    </li>
  );
}
