import type { DashboardSummary } from "../../api/dashboard";
import { formatMoney, isLoss } from "../../lib/money";
import { Card } from "../ui";

interface PortfolioSummaryProps {
  /** The dashboard summary whose portfolio totals are displayed. */
  summary: DashboardSummary;
}

/**
 * Portfolio-level numeric summary (Requirement 11.1).
 *
 * Displays total income, total expenses, and net income or loss across all
 * properties for the summary's tax year, prominently and as numbers only — no
 * charts or visualizations (Requirement 11 / design "Dashboard Component").
 *
 * The net figure is labelled "Net income" or "Net loss" depending on its sign
 * so a loss is unambiguous to screen-reader users, not conveyed by colour or a
 * minus sign alone (Requirement 11.1, 14.4).
 */
export function PortfolioSummary({ summary }: PortfolioSummaryProps) {
  const loss = isLoss(summary.net);
  const netLabel = loss ? "Net loss" : "Net income";

  return (
    <section
      aria-label={`Portfolio totals for ${summary.tax_year}`}
      className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3"
    >
      <Card className="p-4">
        <p className="text-sm font-medium text-fg-subtle">Total income</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-fg">
          {formatMoney(summary.total_income)}
        </p>
      </Card>

      <Card className="p-4">
        <p className="text-sm font-medium text-fg-subtle">Total expenses</p>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-fg">
          {formatMoney(summary.total_expenses)}
        </p>
      </Card>

      <div
        className={[
          "rounded-lg border p-4 shadow-card",
          loss
            ? "border-danger bg-danger-subtle"
            : "border-success bg-success-subtle",
        ].join(" ")}
      >
        <p className="text-sm font-medium text-fg-muted">{netLabel}</p>
        <p
          className={[
            "mt-1 text-2xl font-semibold tabular-nums",
            loss ? "text-danger" : "text-success",
          ].join(" ")}
        >
          {formatMoney(summary.net)}
          {loss ? (
            <span className="ml-2 align-middle text-xs font-medium uppercase tracking-wide text-danger">
              Loss
            </span>
          ) : null}
        </p>
      </div>
    </section>
  );
}
