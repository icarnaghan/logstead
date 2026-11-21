import { cn } from "../../lib/cn";
import { Spinner } from "./Spinner";

export interface RefreshingIndicatorProps {
  className?: string;
}

/**
 * Small "Refreshing" status shown beside header actions while content stays
 * mounted during a reload (Requirement 14.3).
 */
export function RefreshingIndicator({ className }: RefreshingIndicatorProps) {
  return (
    <span
      role="status"
      className={cn("inline-flex items-center gap-2 text-sm text-fg-muted", className)}
    >
      <Spinner />
      <span>Refreshing</span>
    </span>
  );
}
