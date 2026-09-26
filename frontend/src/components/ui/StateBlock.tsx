import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export interface StateBlockAction {
  /** Visible action label. */
  label: string;
  /** When set, the action renders as a react-router `<Link>` to this path. */
  to?: string;
  /** When set (and `to` is not), the action renders as a `<button>`. */
  onClick?: () => void;
}

export interface StateBlockProps {
  /** Whether this is a loading placeholder or an empty state. */
  kind: "loading" | "empty";
  /** Primary message (e.g. "Loading transactions…" or "No transactions yet"). */
  title: string;
  /** Optional supporting copy shown under the title in the empty state. */
  description?: string;
  /** Optional next-action, e.g. "Add transaction". */
  action?: StateBlockAction;
}

const ACTION_CLASSES = cn(
  "mt-4 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover",
  FOCUS_RING,
);

/**
 * Shared loading/empty-state primitive (Requirements 9.1, 9.2), modeled on the
 * existing DashboardEmptyState + PropertiesPage empty state, which pair a
 * message with a next-action link.
 *
 * - `kind="loading"`: a centered `role="status"` block announcing the title.
 * - `kind="empty"`: a dashed-border card with a heading, optional description,
 *   and an optional action rendered as a react-router `<Link>` (when `to` is
 *   set) or a `<button>` (when `onClick` is set). The focus ring is applied to
 *   the action.
 */
export function StateBlock({
  kind,
  title,
  description,
  action,
}: StateBlockProps) {
  if (kind === "loading") {
    return (
      <div role="status" className="p-8 text-center text-fg-muted">
        {title}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center">
      <h2 className="text-lg font-medium text-fg">{title}</h2>
      {description ? (
        <p className="mt-1 text-sm text-fg-subtle">{description}</p>
      ) : null}
      {action ? (
        action.to ? (
          <Link to={action.to} className={ACTION_CLASSES}>
            {action.label}
          </Link>
        ) : (
          <button type="button" onClick={action.onClick} className={ACTION_CLASSES}>
            {action.label}
          </button>
        )
      ) : null}
    </div>
  );
}
