import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { centsToMoney, formatMoney } from "../../lib/money";
import { useChartColors } from "./chartColors";
import type { DepreciationTrendDatum } from "./prepare";

/**
 * Portfolio depreciation (Schedule E Line 18) trend chart (Requirements 5.1,
 * 5.3, 10.1, 10.4).
 *
 * Renders the portfolio depreciation total across every Data_Year supplied by
 * `depreciationTrend(series)` in `prepare.ts` as a Recharts **line** chart over
 * the Data_Year (X axis), so the write-off trend reads left-to-right in
 * ascending chronological order (Requirement 5.1). The series is derived from
 * the trends endpoint's per-year `depreciation_total` (Requirement 5.3).
 *
 * Charts plot **integer cents** — never floating-point dollars (Requirement
 * 10.4). Both the Y-axis ticks and the tooltip render money through
 * `formatMoney(centsToMoney(cents))` so nothing is lost; the X-axis carries the
 * integer Data_Year.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references: the depreciation line uses `accent`, gridlines use `grid`
 * (derived from `--color-border`), and axis text uses `fgMuted`. The treatment
 * is calm — no gradients, no 3D, animation disabled. Meaning never rests on
 * color alone: the always-present {@link ./DepreciationTrendTable} carries the
 * figures and the tooltip announces each year's amount.
 *
 * `accessibilityLayer` enables keyboard traversal of the points with a tooltip
 * readout. The component is a **default export** so callers can
 * `React.lazy(() => import("./DepreciationTrendChart"))`; importing Recharts
 * here keeps the library confined to the lazy chart chunk (Requirement 10.1).
 */
export interface DepreciationTrendChartProps {
  /** Portfolio Line 18 depreciation total per Data_Year, ascending. */
  data: DepreciationTrendDatum[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function DepreciationTrendChart({
  data,
}: DepreciationTrendChartProps) {
  const colors = useChartColors();

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={data}
        accessibilityLayer
        margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
      >
        <CartesianGrid stroke={colors.grid} />
        <XAxis
          type="number"
          dataKey="year"
          domain={["dataMin", "dataMax"]}
          allowDecimals={false}
          tick={{ fill: colors.fgMuted, fontSize: 12 }}
          stroke={colors.grid}
        />
        <YAxis
          type="number"
          tickFormatter={(value) => formatCents(Number(value))}
          tick={{ fill: colors.fgMuted, fontSize: 12 }}
          stroke={colors.grid}
          width={80}
        />
        <Tooltip
          formatter={(value) => formatCents(Number(value))}
          labelFormatter={(label) => `Data year ${label}`}
          cursor={{ stroke: colors.grid }}
        />
        <Line
          type="monotone"
          dataKey="cents"
          name="Depreciation"
          stroke={colors.accent}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/**
 * Re-export the always-present data table so call sites can import the chart and
 * its table together. The table itself lives in a Recharts-free sibling module
 * ({@link ./DepreciationTrendTable}) so it can be rendered eagerly without
 * pulling the charting library into the initial bundle (Requirement 10.1).
 */
export { DepreciationTrendTable } from "./DepreciationTrendTable";
