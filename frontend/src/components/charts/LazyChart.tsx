import { Suspense, type ReactNode } from "react";
import { ChartPlaceholder } from "./ChartCard";
import { ChartErrorBoundary } from "./ChartErrorBoundary";

/**
 * Reusable lazy-loading composition for charts (Requirements 14.1–14.3).
 *
 * Charts are the lazy boundary: the actual Recharts-backed chart components are
 * created with `React.lazy(() => import("./XChart"))` at their call sites (built
 * in task 17.x). Because Recharts is only ever imported through those lazy
 * chunks, it lands in a separate async chunk that is absent from the initial
 * paint (Req 14.1) and is never fetched on screens with no chart (Req 14.2) —
 * the `import()` fires only when a chart actually mounts.
 *
 * `LazyChart` wraps a lazy chart node in the two guards every chart needs:
 *
 *   1. `ChartErrorBoundary` — if the chart chunk fails to load or the chart
 *      throws, it falls back to `fallbackTable` (the always-present data table
 *      plus a small "chart unavailable" note), so the data is never gated by a
 *      chart failure.
 *   2. `Suspense` — while the lazy chunk is loading it shows a
 *      `<ChartPlaceholder height={height} />` in the chart's area (Req 14.3),
 *      keeping layout stable.
 *
 * Example call site (in task 17.x):
 *
 * ```tsx
 * const ExpenseByCategoryChart = React.lazy(
 *   () => import("./ExpenseByCategoryChart"),
 * );
 *
 * <LazyChart fallbackTable={<ExpenseTable data={data} />} height={280}>
 *   {show && <ExpenseByCategoryChart data={data} />}
 * </LazyChart>
 * ```
 *
 * Note: this module intentionally does NOT import Recharts. Keeping the
 * scaffolding Recharts-free ensures the charting bundle stays out of the initial
 * paint until a real lazy chart mounts.
 */
export interface LazyChartProps {
  /** The (typically `React.lazy`) chart node to render. */
  children: ReactNode;
  /**
   * Fallback shown when the chart chunk fails to load or the chart throws —
   * typically the always-present data table plus a "chart unavailable" note.
   */
  fallbackTable: ReactNode;
  /** Chart-area height in px for the loading placeholder. Defaults to 280. */
  height?: number;
}

export function LazyChart({ children, fallbackTable, height }: LazyChartProps) {
  return (
    <ChartErrorBoundary fallback={fallbackTable}>
      <Suspense fallback={<ChartPlaceholder height={height} />}>
        {children}
      </Suspense>
    </ChartErrorBoundary>
  );
}
