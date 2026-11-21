import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { Card } from "./Card";

/**
 * Decorative loading placeholder (Requirements 8.1, 8.2). Hidden from
 * assistive tech; the pulse is disabled under reduced motion.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "rounded bg-surface-muted animate-pulse motion-reduce:animate-none",
        className,
      )}
    />
  );
}

/** Announces a loading area to assistive tech (Requirement 8.3). */
export function LoadingRegion({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-label={label} className={className}>
      {children}
    </div>
  );
}

/** Placeholder rows for a table first load (Requirement 8.4). */
export function TableSkeleton({
  rows = 5,
  columns,
}: {
  rows?: number;
  columns: number;
}) {
  return (
    <div className="space-y-3" data-testid="table-skeleton">
      <Skeleton className="h-4 w-full" />
      {Array.from({ length: rows }, (_, r) => (
        <div
          key={r}
          className="grid gap-4"
          style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
        >
          {Array.from({ length: columns }, (_, c) => (
            <Skeleton key={c} className="h-5" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Placeholder for a dashboard/summary tile (Requirement 8.5). */
export function TileSkeleton({ className }: { className?: string }) {
  return (
    <Card className={cn("p-card", className)}>
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="mt-3 h-8 w-1/2" />
    </Card>
  );
}

/** Placeholder for a chart tile (Requirement 8.5). */
export function ChartSkeleton() {
  return (
    <Card className="p-card">
      <Skeleton className="h-64 w-full" />
    </Card>
  );
}
