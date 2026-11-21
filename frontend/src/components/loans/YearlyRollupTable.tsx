import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LoanSchedule, YearlyRollup } from "../../api/loans";
import { formatMoney, formatMoneyWholeDollars } from "../../lib/money";
import { ResponsiveTable } from "../ui/ResponsiveTable";
import type {
  ResponsiveTableColumn,
  ResponsiveTableRow,
} from "../ui/ResponsiveTable";
import { PaymentRowsTable } from "./PaymentRowsTable";

interface YearlyRollupTableProps {
  /** Accessible caption describing which loan this table is for. */
  caption: string;
  schedule: LoanSchedule;
  /**
   * Renders the per-year interest override control (`InterestOverrideControl`)
   * for a yearly row. The hosting page owns persistence and error state, so the
   * table stays presentational. When omitted, no Override column is shown.
   */
  renderOverrideControl?: (year: YearlyRollup) => ReactNode;
  /**
   * The loan's anchor date (YYYY-MM-DD). When given, the anchor-year row shows
   * "payments after <anchor date> only" as text.
   */
  anchorDate?: string;
}

const DASH = "\u2014";

/**
 * Describes the override-vs-estimate variance in words, e.g. "$120.00 lower
 * than the estimate". `variance` is a signed money string (override minus
 * estimate); it is inspected as text, with no floating-point arithmetic.
 */
function describeVariance(variance: string): string {
  const trimmed = variance.trim();
  const negative = trimmed.startsWith("-");
  const magnitude = negative ? trimmed.slice(1) : trimmed;
  const isZero = /^0*\.?0*$/.test(magnitude);
  if (isZero) return "Same as the estimate";
  const amount = formatMoney(magnitude);
  return `${amount} ${negative ? "lower" : "higher"} than the estimate`;
}

/**
 * Yearly rollup of a loan schedule (Requirements 9.8 to 9.13): one row per tax
 * year in ascending order, whole-dollar money, a per-year toggle button that
 * reveals that year's monthly {@link PaymentRowsTable}, a text "Filed value"
 * marker plus variance in words when an interest override exists, and an
 * optional per-year override control.
 */
export function YearlyRollupTable({
  caption,
  schedule,
  renderOverrideControl,
  anchorDate,
}: YearlyRollupTableProps) {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());

  const years = useMemo(
    () => [...schedule.yearly].sort((a, b) => a.tax_year - b.tax_year),
    [schedule.yearly],
  );

  const paymentsByYear = useMemo(() => {
    const groups = new Map<string, LoanSchedule["payments"]>();
    for (const payment of schedule.payments) {
      const key = payment.date.slice(0, 4);
      const list = groups.get(key);
      if (list) list.push(payment);
      else groups.set(key, [payment]);
    }
    return groups;
  }, [schedule.payments]);

  if (years.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No yearly schedule is available for this loan.
      </p>
    );
  }

  const showOverride = renderOverrideControl !== undefined;

  const columns: ResponsiveTableColumn[] = [
    { key: "year", header: "Tax year", rowHeader: true },
    { key: "interest", header: "Interest", numeric: true },
    { key: "principal", header: "Principal", numeric: true },
    { key: "total", header: "Total paid", numeric: true },
    { key: "balance", header: "Ending balance", numeric: true },
    { key: "payments", header: "Payments" },
    ...(showOverride
      ? [{ key: "override", header: "Interest override" }]
      : []),
  ];

  function toggle(year: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(year)) next.delete(year);
      else next.add(year);
      return next;
    });
  }

  const rows: ResponsiveTableRow[] = years.map((year) => {
    const isOpen = expanded.has(year.tax_year);
    const panelId = `loan-${schedule.loan_id}-year-${year.tax_year}-payments`;
    const hasOverride = year.interest_override !== null;
    const payments = paymentsByYear.get(String(year.tax_year)) ?? [];
    const overrideOnly = year.payments === 0;
    const isAnchorYear =
      anchorDate !== undefined &&
      anchorDate.slice(0, 4) === String(year.tax_year);
    return {
      id: String(year.tax_year),
      cells: {
        year: (
          <>
            {year.tax_year}
            {overrideOnly ? (
              <span className="ml-2 inline-block rounded border border-border px-1.5 py-0.5 text-xs font-medium text-fg-muted">
                Override only
              </span>
            ) : null}
            {isAnchorYear ? (
              <span className="mt-0.5 block text-xs font-normal text-fg-subtle">
                Anchor year: payments after {anchorDate} only
              </span>
            ) : null}
          </>
        ),
        interest: (
          <>
            {formatMoneyWholeDollars(year.interest)}
            {hasOverride ? (
              <span className="mt-1 block text-right">
                <span className="inline-block rounded border border-border px-1.5 py-0.5 text-xs font-medium text-fg-muted">
                  Filed value
                </span>
                {year.variance !== null ? (
                  <span className="mt-0.5 block text-xs font-normal text-fg-subtle">
                    {describeVariance(year.variance)}
                  </span>
                ) : null}
              </span>
            ) : null}
          </>
        ),
        principal: overrideOnly ? DASH : formatMoneyWholeDollars(year.principal),
        total: overrideOnly ? DASH : formatMoneyWholeDollars(year.total_paid),
        balance:
          overrideOnly || year.ending_balance === null
            ? DASH
            : formatMoneyWholeDollars(year.ending_balance),
        payments: overrideOnly ? null : (
          <button
            type="button"
            className="rounded border border-border px-2 py-1 text-xs text-fg-muted"
            aria-expanded={isOpen}
            aria-controls={panelId}
            onClick={() => toggle(year.tax_year)}
          >
            {isOpen ? "Hide" : "Show"} payments for {year.tax_year}
          </button>
        ),
        ...(renderOverrideControl
          ? { override: renderOverrideControl(year) }
          : {}),
      },
      detail: overrideOnly ? undefined : isOpen ? (
        <PaymentRowsTable
          caption={`Payments for ${year.tax_year}`}
          rows={payments}
        />
      ) : (
        // Non-null so the (hidden) detail row exists for aria-controls.
        <></>
      ),
      detailId: panelId,
      detailOpen: isOpen,
    };
  });

  return (
    <div className="mt-2">
      <ResponsiveTable caption={caption} columns={columns} rows={rows} />
    </div>
  );
}
