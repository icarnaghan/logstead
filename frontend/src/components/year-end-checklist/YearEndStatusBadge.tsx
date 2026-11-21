import type { ChecklistStatus } from "../../api/yearEndChecklist";
import { AlertIcon, Badge, CheckIcon } from "../ui";
import { statusLabel } from "./yearEndText";

const STATUS_TEXT_CLASS: Record<ChecklistStatus, string> = {
  done: "text-success",
  needs_attention: "text-warning",
  not_applicable: "text-fg-muted",
};

/** Decorative dash for "not applicable" (the shared icon set has none). */
function DashIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
      className="h-4 w-4"
    >
      <path d="M6 12h12" />
    </svg>
  );
}

function StatusIcon({ status }: { status: ChecklistStatus }) {
  if (status === "done") return <CheckIcon className="h-4 w-4" />;
  if (status === "needs_attention") return <AlertIcon className="h-4 w-4" />;
  return <DashIcon />;
}

/**
 * Status pill: an icon plus the status text, so color is never the only cue.
 * The status text is part of the accessible name.
 */
export function YearEndStatusBadge({ status }: { status: ChecklistStatus }) {
  const label = statusLabel(status);
  return (
    <Badge label={label}>
      <span className={`inline-flex items-center gap-1 ${STATUS_TEXT_CLASS[status]}`}>
        <StatusIcon status={status} />
        {label}
      </span>
    </Badge>
  );
}
