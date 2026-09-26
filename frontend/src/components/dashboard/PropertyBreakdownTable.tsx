import { Link } from "react-router-dom";
import type { PropertySummary } from "../../api/dashboard";
import { propertyPath } from "../navConfig";
import { formatMoney, isLoss } from "../../lib/money";
import { ResponsiveTable, type ResponsiveTableColumn } from "../ui";

interface PropertyBreakdownTableProps {
  /** Per-property summaries to render, one row each. */
  properties: readonly PropertySummary[];
  /** The tax year the figures are for; used in the table caption. */
  taxYear: number;
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "property", header: "Property" },
  { key: "income", header: "Income", align: "right" },
  { key: "expenses", header: "Expenses", align: "right" },
  { key: "net", header: "Net", align: "right" },
];

/**
 * Per-property numeric breakdown table (Requirement 11.2).
 *
 * One row per property showing its income, expenses, and net income or loss
 * for the tax year, with the property name linking to that property's
 * transactions. Numbers only — no charts (Requirement 11).
 *
 * A negative net is rendered with a visible "loss" cue so it is not conveyed by
 * sign alone (Requirement 11.1, 14.4). Layout is delegated to the shared
 * {@link ResponsiveTable} primitive (Requirement 6.3): a scroll-wrapped table
 * at ≥ `sm` and a card-per-row layout below it.
 */
export function PropertyBreakdownTable({
  properties,
  taxYear,
}: PropertyBreakdownTableProps) {
  const rows = properties.map((property) => {
    const loss = isLoss(property.net);
    return {
      id: property.property_id,
      cells: {
        property: (
          <Link
            to={propertyPath(property.property_id, "transactions")}
            className="font-medium text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            {property.property_name}
          </Link>
        ),
        income: (
          <span className="tabular-nums text-fg">
            {formatMoney(property.total_income)}
          </span>
        ),
        expenses: (
          <span className="tabular-nums text-fg">
            {formatMoney(property.total_expenses)}
          </span>
        ),
        net: (
          <span
            className={[
              "tabular-nums",
              loss ? "text-danger" : "text-fg",
            ].join(" ")}
          >
            {formatMoney(property.net)}
            {loss ? (
              <span className="ml-1 text-xs font-medium uppercase tracking-wide text-danger">
                {" "}
                (loss)
              </span>
            ) : null}
          </span>
        ),
      },
    };
  });

  return (
    <div className="mt-4">
      <ResponsiveTable
        caption={`Per-property income, expenses, and net for ${taxYear}`}
        columns={COLUMNS}
        rows={rows}
      />
    </div>
  );
}
