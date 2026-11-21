import { useState } from "react";
import type { ApiFieldError } from "../../api/transactions";
import {
  Button,
  ErrorSummary,
  FormField,
  MoneyInput,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import { useDirtyReporter } from "../../lib/dirty";
import { isPositiveAmount, toMoneyString } from "../../lib/money";

interface TotalFormProps {
  /** Existing total amount when editing; absent when setting a new total. */
  initialAmount?: string;
  /** Display name of the category, e.g. "Repairs". */
  label: string;
  taxYear: number;
  serverError?: ApiFieldError | null;
  submitting?: boolean;
  onSubmit: (amount: string) => void;
  onCancel: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

const FIELD_ORDER = ["amount"] as const;
const AMOUNT_ID = "itemized-total-amount";
const idFor = () => AMOUNT_ID;

/**
 * Set or edit the year's entered total (Requirements 8.1, 8.3, 8.7, 16.3).
 * One amount greater than zero with at most two decimals.
 */
export function TotalForm({
  initialAmount,
  label,
  taxYear,
  serverError,
  submitting = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: TotalFormProps) {
  const [amount, setAmount] = useState<string>(initialAmount ?? "");
  const [initialValues] = useState(() => ({ amount: initialAmount ?? "" }));
  useDirtyReporter(initialValues, { amount }, onDirtyChange);
  const [clientError, setClientError] = useState<string | undefined>();
  const [attempt, setAttempt] = useState(0);
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (prevServerError !== serverError) {
    setPrevServerError(serverError);
    if (serverError?.field) setAttempt((n) => n + 1);
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    let found: string | undefined;
    if (!amount.trim()) found = "Amount is required.";
    else if (!isPositiveAmount(amount)) {
      found = "Amount must be a number greater than zero.";
    }
    setClientError(found);
    if (found) {
      setAttempt((n) => n + 1);
      return;
    }
    onSubmit(toMoneyString(amount));
  }

  const amountError =
    serverError?.field === "amount" || serverError?.field === "total"
      ? (serverError.message ?? "This value was rejected.")
      : clientError;
  const generalServerError =
    serverError && serverError.field !== "amount" && serverError.field !== "total"
      ? serverError.message
      : undefined;

  const shownErrors = { amount: amountError };
  useFocusFirstInvalid({
    errors: shownErrors,
    order: FIELD_ORDER,
    idFor,
    attempt,
  });
  const summaryItems: ErrorSummaryItem[] = [
    ...orderedErrors(shownErrors, FIELD_ORDER),
    ...(generalServerError ? [{ message: generalServerError }] : []),
  ];

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      <ErrorSummary
        items={summaryItems}
        idFor={idFor}
        headingId="itemized-total-error-summary"
      />
      <FormField
        id={AMOUNT_ID}
        errorId="itemized-total-amount-error"
        label={`${label} total for ${taxYear}`}
        hint="Removing the total later makes the line follow your itemized entries."
        required
        error={amountError}
      >
        {(control) => (
          <MoneyInput
            {...control}
            placeholder="0.00"
            value={amount}
            onValueChange={setAmount}
            className="block w-full"
          />
        )}
      </FormField>
      <ModalFormActions>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initialAmount !== undefined ? "Save total" : "Set total"}
        </Button>
      </ModalFormActions>
    </form>
  );
}
