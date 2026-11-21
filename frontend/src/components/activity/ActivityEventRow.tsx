import { useContext, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  activityApi,
  type ActivityEvent,
  type ActivityValues,
} from "../../api/activity";
import { actionLabel, entityLabel, eventLink } from "../../lib/activityText";
import { ApiError } from "../../lib/apiClient";
import { formatMoney } from "../../lib/money";
import { Badge, Button, ConfirmDialog } from "../ui";
import { ToastContext } from "../ui/toast/ToastProvider";

const MONEY_PATTERN = /^-?\d+\.\d{2}$/;

/** Local date and time of a UTC ISO timestamp; the raw value if unparsable. */
export function formatEventTime(at: string): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return at;
  return date.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function labelFor(key: string): string {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Display text for a stored value. Money strings are formatted, never parsed here. */
function displayValue(value: string | boolean | null): string {
  if (value === null || value === "") return "None";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return MONEY_PATTERN.test(value) ? formatMoney(value) : value;
}

function ValueList({
  title,
  values,
}: {
  title: string;
  values: ActivityValues | null;
}) {
  const entries = values ? Object.entries(values) : [];
  return (
    <div>
      <p className="text-caption font-medium uppercase tracking-wide text-fg-subtle">
        {title}
      </p>
      {entries.length === 0 ? (
        <p className="mt-1 text-sm text-fg-muted">None</p>
      ) : (
        <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {entries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-fg-muted">{labelFor(key)}</dt>
              <dd className="break-words text-fg tabular-nums">
                {displayValue(value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

const ALREADY_RESTORED = /already restored/i;

function errorMessage(err: unknown): { status: number | null; text: string } {
  if (err instanceof ApiError) {
    const body = err.body as { message?: unknown } | null;
    const text =
      body && typeof body.message === "string" ? body.message : err.message;
    return { status: err.status, text };
  }
  return { status: null, text: "Could not restore this record." };
}

/** One history entry (Requirements 16.3, 16.4, 16.10, 17.10, 17.11, 17.13). */
export function ActivityEventRow({ event }: { event: ActivityEvent }) {
  const navigate = useNavigate();
  const toast = useContext(ToastContext);
  const [restoredAs, setRestoredAs] = useState<string | null>(
    event.restored_as,
  );
  const [markedRestored, setMarkedRestored] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const link = eventLink(event);
  const restored = markedRestored || restoredAs !== null;
  const restoredLink = restoredAs
    ? eventLink({
        action: "create",
        entity: event.entity,
        record_id: restoredAs,
        property_id: event.property_id,
      })
    : null;
  const canRestore =
    event.action === "delete" &&
    event.restorable &&
    !restored &&
    event.property_id !== null;

  async function restore() {
    if (event.property_id === null) return;
    setPending(true);
    setRestoreError(null);
    try {
      const result = await activityApi.restore(event.property_id, event.id);
      const target = eventLink({
        action: "create",
        entity: event.entity,
        record_id: result.record_id,
        property_id: event.property_id,
      });
      setRestoredAs(result.record_id);
      setMarkedRestored(true);
      setConfirming(false);
      toast?.notify({
        variant: "success",
        title: "Record restored",
        description: "It was restored with a new id.",
        action: target
          ? { label: "View record", onClick: () => navigate(target) }
          : undefined,
      });
    } catch (err) {
      const { status, text } = errorMessage(err);
      setConfirming(false);
      if (status === 409 && ALREADY_RESTORED.test(text)) {
        setMarkedRestored(true);
      }
      setRestoreError(text);
    } finally {
      setPending(false);
    }
  }

  const hasDetails = event.before !== null || event.after !== null;
  return (
    <li className="border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <time dateTime={event.at} className="text-sm text-fg-muted">
          {formatEventTime(event.at)}
        </time>
        <Badge>{actionLabel(event.action)}</Badge>
        <span className="text-sm text-fg-muted">
          {entityLabel(event.entity)}
        </span>
        {event.property_name ? (
          <span className="text-sm text-fg-muted">{event.property_name}</span>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-fg">
        {link ? (
          <Link to={link} className="text-accent underline">
            {event.summary}
          </Link>
        ) : (
          event.summary
        )}
      </p>
      {restored ? (
        <p className="mt-2 flex items-center gap-3 text-sm">
          <Badge>Restored</Badge>
          {restoredLink ? (
            <Link to={restoredLink} className="text-accent underline">
              View restored record
            </Link>
          ) : null}
        </p>
      ) : null}
      {canRestore ? (
        <div className="mt-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setRestoreError(null);
              setConfirming(true);
            }}
          >
            Restore
          </Button>
        </div>
      ) : null}
      {restoreError ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {restoreError}
        </p>
      ) : null}
      <ConfirmDialog
        open={confirming}
        onOpenChange={(open) => {
          if (!pending) setConfirming(open);
        }}
        title="Restore this record?"
        description={`${event.summary} will be added back with a new id. Its other details stay the same.`}
        confirmLabel="Restore"
        destructive={false}
        pending={pending}
        onConfirm={restore}
      />
      {hasDetails ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-accent">
            Details
          </summary>
          <div className="mt-2 grid gap-4 sm:grid-cols-2">
            <ValueList title="Before" values={event.before} />
            <ValueList title="After" values={event.after} />
          </div>
          {event.truncated ? (
            <p className="mt-2 text-caption text-fg-muted">
              Some values were shortened in the history.
            </p>
          ) : null}
        </details>
      ) : null}
    </li>
  );
}
