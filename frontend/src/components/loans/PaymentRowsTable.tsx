import type { PaymentRow } from "../../api/loans";
import { formatMoney } from "../../lib/money";
import { ResponsiveTable } from "../ui/ResponsiveTable";
import type { ResponsiveTableColumn } from "../ui/ResponsiveTable";

interface PaymentRowsTableProps {
  /** Accessible caption describing which loan and year these payments are for. */
  caption: string;
  rows: PaymentRow[];
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "number", header: "Payment number", rowHeader: true },
  { key: "date", header: "Date" },
  { key: "payment", header: "Payment", numeric: true },
  { key: "interest", header: "Interest", numeric: true },
  { key: "principal", header: "Principal", numeric: true },
  { key: "balance", header: "Balance", numeric: true },
];

/**
 * Monthly payment rows for one tax year of a loan schedule (Requirements 9.10,
 * 9.11). Money renders to the cent via {@link formatMoney} with `tabular-nums`
 * alignment, using the shared {@link ResponsiveTable}.
 */
export function PaymentRowsTable({ caption, rows }: PaymentRowsTableProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">No payments in this year.</p>
    );
  }

  return (
    <ResponsiveTable
      caption={caption}
      columns={COLUMNS}
      stickyHeader
      maxHeightClass="max-h-96"
      rows={rows.map((row) => ({
        id: String(row.number),
        cells: {
          number: row.number,
          date: row.date,
          payment: formatMoney(row.payment),
          interest: formatMoney(row.interest),
          principal: formatMoney(row.principal),
          balance: formatMoney(row.balance),
        },
      }))}
    />
  );
}
