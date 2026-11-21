import type { OtherItem } from "../../api/reports";
import { formatMoneyWholeDollars } from "../../lib/money";
import { Badge } from "../ui";

interface OtherItemsListProps {
  /** Accessible caption describing the itemization. */
  caption: string;
  /** The itemized Line 19 "Other" expenses (Requirement 10.5). */
  items: OtherItem[];
}

/**
 * Itemizes the Schedule E Line 19 "Other" expenses as an accessible table of
 * description + amount rows (Requirement 10.5). When a property has no Other
 * expenses for the year the list is empty and a short note is shown instead.
 */
export function OtherItemsList({ caption, items }: OtherItemsListProps) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No Line 19 "Other" expenses were recorded for this tax year.
      </p>
    );
  }

  return (
    <table className="w-full border-collapse text-sm">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-border text-left text-fg-muted">
          <th scope="col" className="py-1.5 pr-4 font-medium">
            Description
          </th>
          <th scope="col" className="py-1.5 text-right font-medium">
            Amount
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, index) => (
          <tr
            key={`${item.description}-${index}`}
            className="border-b border-border"
          >
            <th
              scope="row"
              className="py-1.5 pr-4 font-normal text-fg"
            >
              <span className="flex flex-wrap items-center gap-2">
                {item.description}
                {item.imported ? (
                  <Badge label="Imported from a Schedule E import">
                    Imported
                  </Badge>
                ) : null}
              </span>
            </th>
            <td className="py-1.5 text-right tabular-nums text-fg">
              {formatMoneyWholeDollars(item.amount)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
