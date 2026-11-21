import type { ReactNode } from "react";
import { StateBlock } from "../ui";

export interface DataTileProps {
  /**
   * `loading`: first load in flight (skeleton). `error`: first load failed
   * (full error block). `ready`: content has loaded at least once; stays
   * `ready` through refreshes and refresh errors so content stays mounted.
   */
  status: "loading" | "error" | "ready";
  /** Error message for the data source; non-null with `ready` is a stale error. */
  error: string | null;
  /** Retry for the failed data source. */
  onRetry: () => void | Promise<unknown>;
  /** Placeholder shown during the first load. */
  skeleton: ReactNode;
  /** Title for the error block (one per data source, design D12). */
  errorTitle?: string;
  children: ReactNode;
}

/**
 * Picks skeleton, error, or content for one dashboard data source
 * (Requirements 23.1-23.5). A failed refresh keeps the content and adds a
 * compact error with Retry above it.
 */
export function DataTile({
  status,
  error,
  onRetry,
  skeleton,
  errorTitle = "Could not load the dashboard",
  children,
}: DataTileProps) {
  if (status === "loading") return <>{skeleton}</>;
  if (status === "error") {
    return (
      <div className="sm:col-span-2 lg:col-span-3">
        <StateBlock
          kind="error"
          title={errorTitle}
          description={error ?? undefined}
          onRetry={onRetry}
        />
      </div>
    );
  }
  return (
    <>
      {error ? (
        <div className="sm:col-span-2 lg:col-span-3">
          <StateBlock
            kind="error"
            compact
            title={errorTitle}
            description={error}
            onRetry={onRetry}
          />
        </div>
      ) : null}
      {children}
    </>
  );
}
