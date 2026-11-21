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
import type { PropertyTrendSeries } from "./prepare";

/**
 * Net-by-property **trend** chart (Requirements 4.1, 4.4, 4.5).
 *
 * Renders a Recharts multi-line chart with **one line per property** tracing
 * that property's net across every Data_Year (X axis), so the lines read as
 * "how each property performed year over year" (Requirement 4.1). The caller
 * supplies the series via `netByPropertyTrend` in `prepare.ts`: one series per
 * owned property, each with one point per Data_Year in ascending order and a
 * label that is unique across series (Requirement 4.5). A property missing a
 * given year contributes `0` cents from the backend's `0.00` (Requirement 4.2).
 *
 * Recharts consumes row-oriented data, so the series are pivoted into one row
 * per Data_Year keyed by each series' unique label; each `<Line>` then plots
 * its own label's `dataKey`.
 *
 * Charts plot **integer cents** — never floating-point dollars (Requirement
 * 10.4). Both the Y-axis ticks and the tooltip render money through
 * `formatMoney(centsToMoney(cents))` so nothing is lost; the X-axis carries the
 * integer Data_Year.
 *
 * Colors come from {@link useChartColors} as `rgb(var(--color-...))` token
 * references: lines cycle through the semantic palette, gridlines use `grid`
 * (derived from `--color-border`), and axis text uses `fgMuted`. The treatment
 * is calm — animation disabled. Meaning never rests on color alone: each line
 * carries its label in the `<Legend>`, the tooltip announces each series name +
 * amount, and the always-present {@link ./NetByPropertyTrendTable} sits
 * alongside (Requirement 10.1).
 *
 * `accessibilityLayer` enables keyboard traversal of the points with a tooltip
 * readout. The component is a **default export** so callers can
 * `React.lazy(() => import("./NetByPropertyTrendChart"))`; importing Recharts
 * here keeps the library confined to the lazy chart chunk.
 */
export interface NetByPropertyTrendChartProps {
  /**
   * One series per owned property, each with a label unique across all series
   * and one point per Data_Year in ascending order (via `netByPropertyTrend`).
   */
  data: PropertyTrendSeries[];
}

/** Render integer cents as a US-currency string for axis ticks + tooltips. */
function formatCents(cents: number): string {
  return formatMoney(centsToMoney(cents));
}

export default function NetByPropertyTrendChart({
  data,
}: NetByPropertyTrendChartProps) {
  const colors = useChartColors();

  // Cycle lines through the semantic palette so each property reads distinctly;
  // meaning never rests on color alone (the Legend + table carry the labels).
  const palette = [colors.accent, colors.success, colors.danger, colors.fgMuted];

  // Recharts consumes row-oriented data. Every series carries one point per
  // Data_Year in the same ascending order, so the first series' points define
  // the year axis; each row is keyed by each series' unique label.
  const years = data.length > 0 ? data[0].points.map((p) => p.year) : [];
  const rows = years.map((year, rowIndex) => {
    const row: Record<string, number> = { year };
    for (const series of data) {
      row[series.label] = series.points[rowIndex]?.cents ?? 0;
    }
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={rows}
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
          labelFormatter={(label) => `Year ${label}`}
          cursor={{ stroke: colors.grid }}
        />
        <Legend />
        {data.map((series, index) => (
          <Line
            key={series.label}
            type="monotone"
            dataKey={series.label}
            name={series.label}
            stroke={palette[index % palette.length]}
            dot={false}
            isAnimationActive={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/**
 * Re-export the always-present data table so call sites can import the chart and
 * its table together. The table itself lives in a Recharts-free sibling module
 * ({@link ./NetByPropertyTrendTable}) so it can be rendered eagerly without
 * pulling the charting library into the initial bundle.
 */
export { NetByPropertyTrendTable } from "./NetByPropertyTrendTable";
