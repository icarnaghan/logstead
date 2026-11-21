import { Link } from "react-router-dom";
import type { Transaction } from "../../api/transactions";
import { formatMoney } from "../../lib/money";
import { propertyPath } from "../navConfig";
import { Badge, Button, Card } from "../ui";

interface EnteredTotalCardProps {
  propertyId: string;
  taxYear: number;
  /** Display name of the category, e.g. "Repairs". */
  label: string;
  /** Schedule E line number, e.g. 14. */
  line: number;
  /** The rows that make up the entered total (zero, one, or several). */
  rows: readonly Transaction[];
  /** Whether the single row's documents panel is expanded. */
  documentsExpanded: boolean;
  onSet: () => void;
  onEdit: (row: Transaction) => void;
  onRemove: (row: Transaction) => void;
  onToggleDocuments: (row: Transaction) => void;
  /** Rendered inside the expanded documents panel (the receipts list). */
  renderReceipts: (row: Transaction) => React.ReactNode;
}

const LINK_CLASSES =
  "text-accent underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/**
 * Manage the year's entered total (Requirements 3.3, 7.7, 7.8, 7.10, 8.1,
 * 8.3, 8.6, 8.7).
 *
 * - No rows: "Set total".
 * - One row: Edit, Remove, Documents, and the Imported badge with its
 *   re-import hint.
 * - Several rows: actions are not offered; the rows are listed with an
 *   explanation and a link to the Transactions page for the year.
 */
export function EnteredTotalCard({
  propertyId,
  taxYear,
  label,
  line,
  rows,
  documentsExpanded,
  onSet,
  onEdit,
  onRemove,
  onToggleDocuments,
  renderReceipts,
}: EnteredTotalCardProps) {
  const transactionsLink = `${propertyPath(propertyId, "transactions")}?year=${taxYear}`;
  const lowerLabel = label.toLowerCase();

  let body: React.ReactNode;
  if (rows.length === 0) {
    body = (
      <>
        <p className="text-fg-muted">
          No total entered. Line {line} follows your itemized entries until you
          set a total.
        </p>
        <div className="mt-3">
          <Button type="button" variant="primary" onClick={onSet}>
            Set total
          </Button>
        </div>
      </>
    );
  } else if (rows.length === 1) {
    const row = rows[0];
    body = (
      <>
        <p className="flex flex-wrap items-center gap-2">
          <span className="tabular-nums text-fg">{formatMoney(row.amount)}</span>
          {row.imported ? (
            <Badge label="Imported from a Schedule E import">Imported</Badge>
          ) : null}
        </p>
        {row.imported ? (
          <p className="mt-1 text-small text-fg-muted">
            Re-importing a Schedule E for {taxYear} replaces this imported
            total.
          </p>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            aria-expanded={documentsExpanded}
            onClick={() => onToggleDocuments(row)}
          >
            Documents
            <span className="sr-only"> for the {taxYear} {lowerLabel} total</span>
          </Button>
          <Button type="button" variant="secondary" onClick={() => onEdit(row)}>
            Edit total
          </Button>
          <Button type="button" variant="danger" onClick={() => onRemove(row)}>
            Remove total
          </Button>
        </div>
        <p className="mt-3 text-small text-fg-muted">
          Remove the total to make line {line} follow your itemized entries.
        </p>
        {documentsExpanded ? (
          <div className="mt-3 rounded border border-border bg-surface-muted px-2 py-2">
            {renderReceipts(row)}
          </div>
        ) : null}
      </>
    );
  } else {
    body = (
      <>
        <p className="text-fg-muted">
          {rows.length} {lowerLabel} total rows for {taxYear} are combined into
          the entered total. Set, edit, and remove are unavailable while there
          is more than one. Manage them on the{" "}
          <Link to={transactionsLink} className={LINK_CLASSES}>
            Transactions page
          </Link>
          .
        </p>
        <ul className="mt-2 space-y-1">
          {rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-2">
              <span className="text-fg-muted">{row.date}</span>
              <span className="tabular-nums text-fg">
                {formatMoney(row.amount)}
              </span>
              {row.imported ? (
                <Badge label="Imported from a Schedule E import">Imported</Badge>
              ) : null}
            </li>
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" variant="secondary" disabled>
            Edit total
          </Button>
          <Button type="button" variant="danger" disabled>
            Remove total
          </Button>
        </div>
      </>
    );
  }

  return (
    <Card as="section" aria-labelledby="entered-total-heading" className="p-card">
      <h2 id="entered-total-heading" className="text-sm font-medium text-fg-subtle">
        Entered total
      </h2>
      <div className="mt-2">{body}</div>
    </Card>
  );
}
