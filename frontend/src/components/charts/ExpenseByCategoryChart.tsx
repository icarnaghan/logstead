import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { centsToMoney, formatMoney } from "../../lib/money";
import { useChartColors } from "./chartColors";
import type { CategoryDatum } from "./prepare";

/**
 * Ranked expense-by-category chart (Requirements 16.1–16.4).
 *
 * Renders a Recharts **horizontal** bar chart — `layout="vertical"` in Recharts
 * puts the category labels on the Y axis and the amount on the X axis, so the
 * bars read left-to-right and stack top-to-bottom. The caller supplies `data`
 * already ranked by descending cents (via `expenseByCategory` /
 * `combinedExpenseByCategory` in `prepare.ts`, Requirement 16.3), so the largest
 * category sits at the top.
 *
 * Charts plot **integer cents** — never floating-point dollars (Requirement
 * 13.1). Both the X-axis ticks and the tooltip render money through
 * `formatMoney(centsToMoney(cents))` (Requirement 13.2) so nothing is lost.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references (Requirement 11.2): bars use `accent`, gridlines use `grid`
 * (derived from `--color-border`), and axis text uses `fgMuted`. The treatment
 * is calm — no gradients, no 3D, animation disabled (Requirement 11.5).
 *
 * `accessibilityLayer` enables keyboard traversal of the bars with a tooltip
 * readout (Requirement 12.3). The component is a **default export** so callers
 * can `React.lazy(() => import("./ExpenseByCategoryChart"))`; importing Recharts
 * here keeps the library confined to the lazy chart chunk (Requirement 14).
 */
export interface ExpenseByCategoryChartProps {
  /** Category slices, already ranked by descending cents (Req 16.3). */
  data: CategoryDatum[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function ExpenseByCategoryChart({
  data,
}: ExpenseByCategoryChartProps) {
  const colors = useChartColors();

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        layout="vertical"
        accessibilityLayer
        margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
      >
        <CartesianGrid stroke={colors.grid} horizontal={false} />
        <XAxis
          type="number"
          tickFormatter={(value) => formatCents(Number(value))}
          tick={{ fill: colors.fgMuted, fontSize: 12 }}
          stroke={colors.grid}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={120}
          tick={{ fill: colors.fgMuted, fontSize: 12 }}
          stroke={colors.grid}
        />
        <Tooltip
          formatter={(value) => formatCents(Number(value))}
          cursor={{ fill: colors.grid, fillOpacity: 0.2 }}
        />
        <Bar
          dataKey="cents"
          name="Amount"
          fill={colors.accent}
          isAnimationActive={false}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Re-export the always-present data table so call sites can import the chart and
 * its table together. The table itself lives in a Recharts-free sibling module
 * ({@link ./ExpenseByCategoryTable}) so it can be rendered eagerly without
 * pulling the charting library into the initial bundle (Requirement 14).
 */
export { ExpenseByCategoryTable } from "./ExpenseByCategoryTable";
