import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { cn } from "../../lib/cn";
import { Button } from "./Button";
import { Spinner } from "./Spinner";

export interface StateBlockAction {
  /** Visible action label. */
  label: string;
  /** When set, the action renders as a react-router `<Link>` to this path. */
  to?: string;
  /** When set (and `to` is not), the action renders as a `<button>`. */
  onClick?: () => void;
}

export interface StateBlockProps {
  /** Loading placeholder, empty state, or error with optional retry. */
  kind: "loading" | "empty" | "error";
  /** Primary message (e.g. "Loading transactions…" or "No transactions yet"). */
  title: string;
  /** Supporting copy (empty state) or error message (error state). */
  description?: string;
  /** Optional next-action, e.g. "Add transaction" (empty state). */
  action?: StateBlockAction;
  /** Error state: renders a Retry button that calls this. May be async. */
  onRetry?: () => void | Promise<unknown>;
  /** Error state: externally controlled retry-in-progress flag. */
  retrying?: boolean;
  /** Error state: render as a single-row banner. */
  compact?: boolean;
}

const ACTION_CLASSES = "mt-4";

function ErrorIcon({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("h-5 w-5 shrink-0 text-danger", className)}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5" />
      <path d="M12 16.5h.01" />
    </svg>
  );
}

/**
 * Shared loading/empty/error-state primitive (Requirements 7.1-7.6, 9.1, 9.2).
 *
 * - `kind="loading"`: a centered `role="status"` block with a spinner and title.
 * - `kind="empty"`: a dashed-border card with a heading, optional description,
 *   and an optional action rendered as a `Button` (`asChild` Link when `to`).
 * - `kind="error"`: a `role="alert"` danger block with icon, title, message and
 *   an optional Retry button. The button is loading while `retrying` is true or
 *   while the promise returned by `onRetry` is unresolved. `compact` renders a
 *   single-row banner.
 */
export function StateBlock({
  kind,
  title,
  description,
  action,
  onRetry,
  retrying = false,
  compact = false,
}: StateBlockProps) {
  const [pending, setPending] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  if (kind === "loading") {
    return (
      <div
        role="status"
        className="flex items-center justify-center gap-2 p-8 text-center text-fg-muted"
      >
        <Spinner />
        <span>{title}</span>
      </div>
    );
  }

  if (kind === "error") {
    const handleRetry = async () => {
      if (!onRetry) return;
      setPending(true);
      try {
        await onRetry();
      } catch {
        // The caller owns error reporting; avoid an unhandled rejection.
      } finally {
        if (mounted.current) setPending(false);
      }
    };

    const retryButton = onRetry ? (
      <Button
        variant="secondary"
        size="sm"
        loading={retrying || pending}
        onClick={handleRetry}
      >
        Retry
      </Button>
    ) : null;

    if (compact) {
      return (
        <div
          role="alert"
          className="flex items-center gap-3 rounded-md border border-danger bg-danger-subtle px-3 py-2"
        >
          <ErrorIcon />
          <div className="min-w-0 flex-1 text-sm">
            <span className="font-medium text-fg">{title}</span>
            {description ? (
              <span className="ml-2 text-fg-muted">{description}</span>
            ) : null}
          </div>
          {retryButton}
        </div>
      );
    }

    return (
      <div
        role="alert"
        className="rounded-lg border border-danger bg-danger-subtle p-6 text-center"
      >
        <ErrorIcon className="mx-auto mb-2 h-6 w-6" />
        <h2 className="text-lg font-medium text-fg">{title}</h2>
        {description ? (
          <p className="mt-1 text-sm text-fg-muted">{description}</p>
        ) : null}
        {retryButton ? <div className="mt-4">{retryButton}</div> : null}
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
          <Button variant="primary" asChild className={ACTION_CLASSES}>
            <Link to={action.to}>{action.label}</Link>
          </Button>
        ) : (
          <Button
            variant="primary"
            onClick={action.onClick}
            className={ACTION_CLASSES}
          >
            {action.label}
          </Button>
        )
      ) : null}
    </div>
  );
}
