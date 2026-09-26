import {
  DEPRECIATION_LINE,
  OTHER_LINE,
  type ScheduleEReport,
} from "../../api/reports";
import { formatMoney } from "../transactions/money";
import { ScheduleELineTable } from "./ScheduleELineTable";
import { OtherItemsList } from "./OtherItemsList";

interface ReportViewProps {
  /** The fetched Schedule E report to render. */
  report: ScheduleEReport;
}

/** True when a two-decimal money string represents a negative amount (a loss). */
function isLoss(amount: string): boolean {
  return Number(amount) < 0;
}

/**
 * Renders a per-property Schedule E report (Requirement 10) as
 * numbers-and-forms — never a chart.
 *
 * It shows the report header (property name/address/type and the year's
 * fair-rental & personal-use days), the per-line Schedule E totals split into
 * income and expense tables, the Line 18 depreciation total, the itemized
 * Line 19 "Other" expenses, and the income / expense / net totals. A negative
 * net is presented as a loss.
 */
export function ReportView({ report }: ReportViewProps) {
  const { header, lines, other_items, totals } = report;

  const incomeLines = lines.filter((line) => line.kind === "income");
  const expenseLines = lines.filter((line) => line.kind === "expense");
  const depreciationLine = lines.find((line) => line.line === DEPRECIATION_LINE);
  const otherLine = lines.find((line) => line.line === OTHER_LINE);

  const netLoss = isLoss(totals.net);

  return (
    <div className="space-y-8">
      <section
        aria-labelledby="report-header-heading"
        className="rounded-lg border border-border bg-surface p-4 shadow-card"
      >
        <h2
          id="report-header-heading"
          className="text-lg font-semibold text-fg"
        >
          {header.property_name}
        </h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="font-medium text-fg-muted">Address</dt>
            <dd className="text-fg">{header.address || "—"}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Property type</dt>
            <dd className="text-fg">{header.property_type ?? "—"}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Tax year</dt>
            <dd className="tabular-nums text-fg">{header.tax_year}</dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Fair rental days</dt>
            <dd className="tabular-nums text-fg">
              {header.fair_rental_days}
            </dd>
          </div>
          <div>
            <dt className="font-medium text-fg-muted">Personal use days</dt>
            <dd className="tabular-nums text-fg">
              {header.personal_use_days}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="report-income-heading">
        <h2
          id="report-income-heading"
          className="text-base font-semibold text-fg"
        >
          Income
        </h2>
        <div className="mt-2">
          <ScheduleELineTable
            caption={`Schedule E income lines for ${header.property_name}, tax year ${header.tax_year}`}
            lines={incomeLines}
          />
        </div>
      </section>

      <section aria-labelledby="report-expenses-heading">
        <h2
          id="report-expenses-heading"
          className="text-base font-semibold text-fg"
        >
          Expenses
        </h2>
        <div className="mt-2">
          <ScheduleELineTable
            caption={`Schedule E expense lines for ${header.property_name}, tax year ${header.tax_year}`}
            lines={expenseLines}
          />
        </div>
      </section>

      <section
        aria-labelledby="report-depreciation-heading"
        className="rounded-lg border border-border bg-surface p-4 shadow-card"
      >
        <h2
          id="report-depreciation-heading"
          className="text-base font-semibold text-fg"
        >
          Depreciation (Line 18)
        </h2>
        <p className="mt-2 text-sm text-fg-muted">
          Total property depreciation for the year, computed from the
          depreciation schedules.
        </p>
        <p className="mt-1 text-sm">
          <span className="font-medium text-fg-muted">
            Line 18 depreciation:{" "}
          </span>
          <span className="tabular-nums text-fg">
            {formatMoney(depreciationLine?.total ?? "0.00")}
          </span>
        </p>
      </section>

      <section aria-labelledby="report-other-heading">
        <h2
          id="report-other-heading"
          className="text-base font-semibold text-fg"
        >
          Other expenses (Line 19)
        </h2>
        {otherLine && (
          <p className="mt-1 text-sm">
            <span className="font-medium text-fg-muted">
              Line 19 total:{" "}
            </span>
            <span className="tabular-nums text-fg">
              {formatMoney(otherLine.total)}
            </span>
          </p>
        )}
        <div className="mt-2">
          <OtherItemsList
            caption={`Itemized Line 19 Other expenses for ${header.property_name}, tax year ${header.tax_year}`}
            items={other_items}
          />
        </div>
      </section>

      <section
        aria-labelledby="report-totals-heading"
        className="rounded-lg border border-border bg-surface p-4 shadow-card"
      >
        <h2
          id="report-totals-heading"
          className="text-base font-semibold text-fg"
        >
          Totals
        </h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <dt className="font-medium text-fg-muted">Total income</dt>
            <dd className="tabular-nums text-fg">
              {formatMoney(totals.total_income)}
            </dd>
          </div>
          <div className="flex items-center justify-between">
            <dt className="font-medium text-fg-muted">Total expenses</dt>
            <dd className="tabular-nums text-fg">
              {formatMoney(totals.total_expenses)}
            </dd>
          </div>
          <div className="flex items-center justify-between border-t border-border pt-2">
            <dt className="font-semibold text-fg">
              {netLoss ? "Net loss" : "Net income"}
            </dt>
            <dd
              className={[
                "font-semibold tabular-nums",
                netLoss ? "text-danger" : "text-fg",
              ].join(" ")}
            >
              {formatMoney(totals.net)}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
