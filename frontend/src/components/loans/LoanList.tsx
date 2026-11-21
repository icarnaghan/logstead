import type { Loan } from "../../api/loans";
import { formatMoney } from "../../lib/money";
import { Badge, Button, EmptyGuide, ResponsiveTable } from "../ui";
import { EMPTY_COPY } from "../../lib/emptyCopy";
import type {
  ResponsiveTableColumn,
  ResponsiveTableRow,
} from "../ui";

export interface LoanListProps {
  /** Loans of the current property. */
  loans: Loan[];
  /** Id of the currently selected Loan, if any. */
  selectedLoanId?: string | null;
  /** Called when the user selects a Loan to view its schedule. */
  onSelect: (loan: Loan) => void;
  /** Called when the user chooses to edit a Loan. */
  onEdit: (loan: Loan) => void;
  /** Called when the user chooses to delete a Loan. */
  onDelete: (loan: Loan) => void;
  /** Called by the empty-state control to start creating a Loan. */
  onCreate: () => void;
}

const COLUMNS: ResponsiveTableColumn[] = [
  { key: "description", header: "Description" },
  { key: "balance", header: "Balance", align: "right" },
  { key: "rate", header: "Rate", align: "right" },
  { key: "payment", header: "Monthly payment", align: "right" },
  { key: "remaining", header: "Remaining payments", align: "right" },
  { key: "status", header: "Status" },
  { key: "actions", header: "Actions" },
];

/** Formats a payment count, e.g. "1 payment" or "148 payments". */
function formatPayments(count: number): string {
  return `${count} ${count === 1 ? "payment" : "payments"}`;
}

/**
 * Lists a property's Loans with description, anchor balance and anchor date,
 * rate, monthly payment, remaining payments with projected payoff date, and
 * status (active or ended), plus Select, Edit and Delete buttons whose
 * accessible names include the Loan description (Requirements 11.1, 9.20).
 * Shows an empty state with the create control when there are no Loans
 * (Requirement 9.7). Money is passed through as strings and never coerced.
 */
export function LoanList({
  loans,
  selectedLoanId = null,
  onSelect,
  onEdit,
  onDelete,
  onCreate,
}: LoanListProps) {
  if (loans.length === 0) {
    return (
      <EmptyGuide
        title={EMPTY_COPY.loans.title}
        description={EMPTY_COPY.loans.description}
        primary={{ label: EMPTY_COPY.loans.primaryLabel, onClick: onCreate }}
      />
    );
  }

  const rows: ResponsiveTableRow[] = loans.map((loan) => {
    const selected = loan.id === selectedLoanId;
    return {
      id: loan.id,
      cells: {
        description: <span className="font-medium">{loan.description}</span>,
        balance: (
          <>
            <span className="block">{formatMoney(loan.anchor_balance)}</span>
            <span className="block text-xs">as of {loan.anchor_date}</span>
          </>
        ),
        rate: `${loan.annual_interest_rate}%`,
        payment: formatMoney(loan.monthly_payment),
        remaining: (
          <>
            <span className="block">
              {formatPayments(loan.remaining_payments)}
            </span>
            <span className="block text-xs">
              {loan.projected_payoff_date
                ? `Payoff ${loan.projected_payoff_date}`
                : loan.payoff_balance
                  ? `Payoff balance ${formatMoney(loan.payoff_balance)}`
                  : "No payoff date"}
            </span>
          </>
        ),
        status: (
          <Badge>{loan.status === "active" ? "Active" : "Ended"}</Badge>
        ),
        actions: (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              aria-pressed={selected}
              aria-label={`Select ${loan.description}`}
              onClick={() => onSelect(loan)}
            >
              {selected ? "Selected" : "Select"}
            </Button>
            <Button
              type="button"
              size="sm"
              aria-label={`Edit ${loan.description}`}
              onClick={() => onEdit(loan)}
            >
              Edit
            </Button>
            <Button
              type="button"
              size="sm"
              variant="danger"
              aria-label={`Delete ${loan.description}`}
              onClick={() => onDelete(loan)}
            >
              Delete
            </Button>
          </div>
        ),
      },
    };
  });

  return <ResponsiveTable caption="Loans" columns={COLUMNS} rows={rows} focusableRows />;
}
