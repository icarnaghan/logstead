import { Link } from "react-router-dom";
import type { PropertySummary } from "../../api/dashboard";
import { propertyPath } from "../navConfig";
import { formatMoney, isLoss } from "./money";

interface PropertyBreakdownTableProps {
  /** Per-property summaries to render, one row each. */
  properties: readonly PropertySummary[];
  /** The tax year the figures are for; used in the table caption. */
  taxYear: number;
}

/**
 * Per-property numeric breakdown table (Requirement 11.2).
 *
 * One row per property showing its income, expenses, and net income or loss
 * for the tax year, with the property name linking to that property's
 * transactions. Numbers only — no charts (Requirement 11).
 *
 * A negative net is rendered with a visible "loss" cue so it is not conveyed by
 * sign alone (Requirement 11.1, 14.4).
 */
export function PropertyBreakdownTable({
  properties,
  taxYear,
}: PropertyBreakdownTableProps) {
  return (
    <table className="mt-4 w-full border-collapse text-sm">
      <caption className="sr-only">
        Per-property income, expenses, and net for {taxYear}
      </caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-subtle">
          <th scope="col" className="py-2 pr-4 font-medium">
            Property
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Income
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Expenses
          </th>
          <th scope="col" className="py-2 pr-4 text-right font-medium">
            Net
          </th>
        </tr>
      </thead>
      <tbody>
        {properties.map((property) => {
          const loss = isLoss(property.net);
          return (
            <tr
              key={property.property_id}
              className="border-b border-border"
            >
              <td className="py-2 pr-4">
                <Link
                  to={propertyPath(property.property_id, "transactions")}
                  className="font-medium text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  {property.property_name}
                </Link>
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-fg">
                {formatMoney(property.total_income)}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums text-fg">
                {formatMoney(property.total_expenses)}
              </td>
              <td
                className={[
                  "py-2 pr-4 text-right tabular-nums",
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
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
