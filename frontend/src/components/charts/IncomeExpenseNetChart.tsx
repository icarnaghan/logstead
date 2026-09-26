import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { centsToMoney, formatMoney } from "../../lib/money";
import { useChartColors } from "./chartColors";
import type { IncomeExpenseNetDatum } from "./prepare";

/**
 * Compact income / expenses / net bar chart (Requirements 17.1–17.3).
 *
 * Renders a Recharts **vertical** bar chart of the three portfolio (or
 * per-property) figures — Income, Expenses, Net — with the figure name on the X
 * axis and the amount on the Y axis, so the three bars read left-to-right. The
 * caller supplies `data` via `incomeExpenseNet(totals)` in `prepare.ts`, which
 * fixes the readable Income / Expenses / Net order.
 *
 * The Income and Expenses bars use the `accent` token. The Net bar reflects
 * gain vs. loss with the `success` / `danger` tokens, but meaning never rests
 * on color alone (Requirement 12.4): the always-present
 * {@link ./IncomeExpenseNetTable} carries the textual "income" / "loss" cue and
 * the tooltip announces the amount.
 *
 * Charts plot **integer cents** — never floating-point dollars (Requirement
 * 13.1). Both the Y-axis ticks and the tooltip render money through
 * `formatMoney(centsToMoney(cents))` (Requirement 13.2) so nothing is lost.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references (Requirement 11.2); gridlines use `grid` (from `--color-border`)
 * and axis text uses `fgMuted`. The treatment is calm — no gradients, no 3D,
 * animation disabled (Requirement 11.5).
 *
 * `accessibilityLayer` enables keyboard traversal of the bars with a tooltip
 * readout (Requirement 12.3). The component is a **default export** so callers
 * can `React.lazy(() => import("./IncomeExpenseNetChart"))`; importing Recharts
 * here keeps the library confined to the lazy chart chunk (Requirement 14).
 */
export interface IncomeExpenseNetChartProps {
  /** The three Income / Expenses / Net figures, in that fixed order. */
  data: IncomeExpenseNetDatum[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function IncomeExpenseNetChart({
  data,
}: IncomeExpenseNetChartProps) {
  const colors = useChartColors();

  /** Per-bar fill: Net reflects gain/loss; the rest use accent (Req 12.4). */
  function barFill(datum: IncomeExpenseNetDatum): string {
    if (datum.key !== "Net") return colors.accent;
    return datum.cents < 0 ? colors.danger : colors.success;
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart
        data={data}
        accessibilityLayer
        margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
      >
        <CartesianGrid stroke={colors.grid} vertical={false} />
        <XAxis
          type="category"
          dataKey="key"
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
          cursor={{ fill: colors.grid, fillOpacity: 0.2 }}
        />
        <Bar dataKey="cents" name="Amount" isAnimationActive={false}>
          {data.map((datum) => (
            <Cell key={datum.key} fill={barFill(datum)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Re-export the always-present data table so call sites can import the chart and
 * its table together. The table itself lives in a Recharts-free sibling module
 * ({@link ./IncomeExpenseNetTable}) so it can be rendered eagerly without
 * pulling the charting library into the initial bundle (Requirement 14).
 */
export { IncomeExpenseNetTable } from "./IncomeExpenseNetTable";
