import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { centsToMoney, formatMoney } from "../../lib/money";
import { useChartColors } from "./chartColors";
import type { TrendPointDatum } from "./prepare";

/**
 * Portfolio income / expenses / net **trend** chart (Requirements 3.1, 3.3,
 * 3.4, 10.1, 10.4).
 *
 * Renders a Recharts line chart with Data_Year on the X axis — ascending
 * chronological order, preserved from the caller's `incomeExpenseNetTrend`
 * (`prepare.ts`) — and three series plotted across the years: Income, Expenses,
 * and Net. The Income and Expenses lines use the `accent` and `fgMuted` tokens;
 * the Net line uses `success`. A negative net denotes a loss; meaning never
 * rests on color alone (Requirement 3.4): the always-present
 * {@link ./IncomeExpenseNetTrendTable} carries the textual "loss" cue and the
 * tooltip announces every amount.
 *
 * Charts plot **integer cents** — never floating-point dollars. Both the Y-axis
 * ticks and the tooltip render money through `formatMoney(centsToMoney(cents))`
 * (Requirement 10.4) so nothing is lost.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references; gridlines use `grid` (from `--color-border`) and axis text uses
 * `fgMuted`. The treatment is calm — no gradients, no 3D, animation disabled.
 *
 * `accessibilityLayer` enables keyboard traversal with a tooltip readout. The
 * component is a **default export** so callers can
 * `React.lazy(() => import("./IncomeExpenseNetTrendChart"))`; importing Recharts
 * here keeps the library confined to the lazy chart chunk.
 */
export interface IncomeExpenseNetTrendChartProps {
  /** One point per Data_Year, in ascending chronological order (Req 3.1). */
  data: TrendPointDatum[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function IncomeExpenseNetTrendChart({
  data,
}: IncomeExpenseNetTrendChartProps) {
  const colors = useChartColors();

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={data}
        accessibilityLayer
        margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
      >
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis
          type="category"
          dataKey="year"
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
          cursor={{ stroke: colors.grid }}
        />
        <Legend />
        <Line
          type="monotone"
          dataKey="income"
          name="Income"
          stroke={colors.accent}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="expenses"
          name="Expenses"
          stroke={colors.fgMuted}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="net"
          name="Net"
          stroke={colors.success}
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
 * ({@link ./IncomeExpenseNetTrendTable}) so it can be rendered eagerly without
 * pulling the charting library into the initial bundle.
 */
export { IncomeExpenseNetTrendTable } from "./IncomeExpenseNetTrendTable";
