import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { centsToMoney, formatMoney } from "../../lib/money";
import { useChartColors } from "./chartColors";
import type { DepreciationDatum } from "./prepare";

/**
 * Asset depreciation-schedule chart (Requirements 19.1–19.3).
 *
 * Renders the genuine multi-year depreciation series supplied by
 * `depreciationSeries(rows)` in `prepare.ts` as a Recharts **composed** chart
 * over the tax year (X axis): an area for the declining **remaining basis** and
 * a line for the **annual depreciation amount**. The two series read as a clear
 * "the basis winds down while each year's write-off is charged" story
 * (Requirement 19.1) and are derived from the existing asset schedule endpoint
 * (Requirement 19.2).
 *
 * Charts plot **integer cents** — never floating-point dollars (Requirement
 * 13.1). Both the Y-axis ticks and the tooltip render money through
 * `formatMoney(centsToMoney(cents))` (Requirement 13.2) so nothing is lost; the
 * X-axis carries the integer tax year.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references (Requirement 11.2): the remaining-basis area uses `accent`, the
 * annual-amount line uses `success`, gridlines use `grid` (derived from
 * `--color-border`), and axis text uses `fgMuted`. The treatment is calm — no
 * gradients, no 3D, animation disabled (Requirement 11.5). Meaning never rests
 * on color alone (Requirement 12.4): the two series carry text labels in the
 * `<Legend>`, the tooltip announces each series name + amount, and the
 * always-present schedule table sits alongside.
 *
 * `accessibilityLayer` enables keyboard traversal of the points with a tooltip
 * readout (Requirement 12.3). The component is a **default export** so callers
 * can `React.lazy(() => import("./DepreciationChart"))`; importing Recharts here
 * keeps the library confined to the lazy chart chunk (Requirement 14).
 */
export interface DepreciationChartProps {
  /** The multi-year depreciation series, oldest year first. */
  data: DepreciationDatum[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function DepreciationChart({ data }: DepreciationChartProps) {
  const colors = useChartColors();

  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart
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
          labelFormatter={(label) => `Tax year ${label}`}
          cursor={{ stroke: colors.grid }}
        />
        <Legend />
        <Area
          type="monotone"
          dataKey="remainingCents"
          name="Remaining basis"
          stroke={colors.accent}
          fill={colors.accent}
          fillOpacity={0.15}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="amountCents"
          name="Depreciation amount"
          stroke={colors.success}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
