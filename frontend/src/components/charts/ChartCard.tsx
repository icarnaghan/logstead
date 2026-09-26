import { useId } from "react";
import { Card } from "../ui/Card";
import { FOCUS_RING } from "../ui/focusRing";
import { cn } from "../../lib/cn";

/**
 * Shared chart wrapper carrying the accessibility + responsiveness contract so
 * every chart behaves identically (Requirements 11.5, 11.6, 12.1–12.4, 15.1–15.3).
 *
 * Numbers-first, accessibility-first: the `dataTable` is ALWAYS present in the
 * DOM (Req 12.1). The chart region is only the *visual* representation — it
 * carries `role="img"` + a summarizing `aria-label` (Req 12.2), sits at a fixed
 * height for a calm, consistent treatment (Req 11.5), and is CSS-hidden below
 * the `sm` breakpoint so the data table becomes the visible fallback on narrow
 * screens (Req 15.3). Nothing here encodes meaning by color alone — meaning
 * lives in the axis/tooltip text callers supply plus the always-present table
 * (Req 12.4).
 *
 * Callers wrap their (typically lazy) Recharts element in a `<ResponsiveContainer>`
 * and should enable Recharts' `accessibilityLayer` so tooltips are reachable by
 * keyboard (Req 12.3); the "Show data table" disclosure this wrapper renders is
 * itself a real, focusable control.
 */
export interface ChartCardProps {
  /** Heading for the card (Req 11.5 calm, labelled treatment). */
  title: string;
  /**
   * Summarizing label applied to the chart region's `role="img"` element so
   * assistive tech announces what the chart shows (Req 12.2). Must be non-empty.
   */
  ariaLabel: string;
  /**
   * The chart element — typically a lazy Recharts chart wrapped by the caller in
   * `<ResponsiveContainer>`. Rendered inside the fixed-height chart region.
   */
  chart: React.ReactNode;
  /**
   * The always-present tabular representation of the same data (Req 12.1). Never
   * removed from the DOM regardless of viewport; it is the visible fallback below
   * `sm` and available via the "Show data table" disclosure at/above `sm`.
   */
  dataTable: React.ReactNode;
  /** Consistent chart height in px (Req 11.5). Defaults to 280. */
  height?: number;
}

const DEFAULT_HEIGHT = 280;

export function ChartCard({
  title,
  ariaLabel,
  chart,
  dataTable,
  height = DEFAULT_HEIGHT,
}: ChartCardProps) {
  const headingId = useId();

  return (
    <Card as="section" aria-labelledby={headingId} className="p-4">
      <h2 id={headingId} className="text-sm font-medium text-fg-subtle">
        {title}
      </h2>

      {/*
        Chart region: the visual representation only. Carries the a11y contract
        (role="img" + aria-label, Req 12.2) and a fixed height (Req 11.5). Hidden
        below `sm` so the always-present data table is the mobile fallback
        (Req 15.3); shown from `sm` up.
      */}
      <div
        role="img"
        aria-label={ariaLabel}
        className={cn("mt-3 hidden w-full sm:block")}
        style={{ height }}
      >
        {chart}
      </div>

      {/*
        Data table: rendered exactly ONCE and ALWAYS in the DOM (Req 12.1), so
        there is one row per datum regardless of viewport. It lives inside a real,
        focusable `<details>` disclosure that starts open; the `<summary>` toggle
        is shown only at `sm`+ (where the chart is the primary visual and the card
        stays calm), and is hidden below `sm` so the table simply shows as the
        visible fallback (Req 15.3). CSS-only visibility — the table node is never
        removed from the DOM, so assistive tech always has the data. The
        `<summary>` control is itself focus-ringed (Req 12.3).
      */}
      <details className="group mt-3" open>
        <summary
          className={cn(
            "hidden cursor-pointer list-none rounded text-sm font-medium text-accent sm:block",
            FOCUS_RING,
          )}
        >
          <span className="group-open:hidden">Show data table</span>
          <span className="hidden group-open:inline">Hide data table</span>
        </summary>
        <div className="mt-3">{dataTable}</div>
      </details>
    </Card>
  );
}

/**
 * Fixed-height loading placeholder for the chart region, used as the `Suspense`
 * fallback while the lazy chart chunk loads (Requirement 14.3). Announces itself
 * via `role="status"` so assistive tech reports the pending state.
 */
export interface ChartPlaceholderProps {
  /** Match the chart height so layout does not jump when the chart resolves. */
  height?: number;
}

export function ChartPlaceholder({
  height = DEFAULT_HEIGHT,
}: ChartPlaceholderProps) {
  return (
    <div
      role="status"
      className="flex w-full items-center justify-center rounded-md border border-dashed border-border text-sm text-fg-muted"
      style={{ height }}
    >
      Loading chart…
    </div>
  );
}
