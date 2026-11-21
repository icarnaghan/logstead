import { useState } from "react";
import type { ItemizedEntryInput } from "../../api/itemized";
import type { ApiFieldError, Transaction } from "../../api/transactions";
import {
  Button,
  DateInput,
  ErrorSummary,
  FormField,
  Input,
  MoneyInput,
  Textarea,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import { useDirtyReporter } from "../../lib/dirty";
import { todayLocal } from "../../lib/dateInput";
import { isPositiveAmount, toMoneyString } from "../../lib/money";

interface ItemizedEntryFormProps {
  /** Selected tax year; new entries default into it. */
  taxYear: number;
  /** Singular noun for one entry, e.g. "repair". */
  entryNoun: string;
  /** When present, the form edits this entry; otherwise it creates one. */
  initial?: Transaction;
  /** Server field error (HTTP 400 with `field`) shown next to its control. */
  serverError?: ApiFieldError | null;
  submitting?: boolean;
  onSubmit: (input: ItemizedEntryInput) => void;
  onCancel: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

type Field = "date" | "amount" | "description" | "notes";
type FieldErrors = Partial<Record<Field, string>>;

const FIELD_ORDER = ["date", "amount", "description", "notes"] as const;
const FIELD_IDS: Record<Field, string> = {
  date: "itemized-date",
  amount: "itemized-amount",
  description: "itemized-description",
  notes: "itemized-notes",
};
const idFor = (field: string) => FIELD_IDS[field as Field] ?? field;

const MAX_DESCRIPTION = 200;
const MAX_NOTES = 1000;

/** Today when it falls in the year, otherwise Dec 31 of the year (Req 2.7). */
export function defaultEntryDate(taxYear: number, today = todayLocal()): string {
  return today.startsWith(`${taxYear}-`) ? today : `${taxYear}-12-31`;
}

/**
 * Add/edit form for an itemized entry (Requirements 2.7, 2.11, 16.3).
 * Client validation mirrors the server rules; server field errors are shown
 * next to their control and the first invalid field receives focus.
 */
export function ItemizedEntryForm({
  taxYear,
  entryNoun,
  initial,
  serverError,
  submitting = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: ItemizedEntryFormProps) {
  const [date, setDate] = useState<string>(
    initial?.date ?? defaultEntryDate(taxYear),
  );
  const [amount, setAmount] = useState<string>(initial?.amount ?? "");
  const [description, setDescription] = useState<string>(
    initial?.description ?? "",
  );
  const [notes, setNotes] = useState<string>(initial?.notes ?? "");
  const [initialValues] = useState(() => ({
    date: initial?.date ?? defaultEntryDate(taxYear),
    amount: initial?.amount ?? "",
    description: initial?.description ?? "",
    notes: initial?.notes ?? "",
  }));
  useDirtyReporter(
    initialValues,
    { date, amount, description, notes },
    onDirtyChange,
  );
  const [errors, setErrors] = useState<FieldErrors>({});
  const [attempt, setAttempt] = useState(0);
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (prevServerError !== serverError) {
    setPrevServerError(serverError);
    if (serverError?.field) setAttempt((n) => n + 1);
  }

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    if (!date) next.date = "Date is required.";
    else if (!date.startsWith(`${taxYear}-`)) {
      next.date = `Date must be in ${taxYear}.`;
    }
    if (!amount.trim()) next.amount = "Amount is required.";
    else if (!isPositiveAmount(amount)) {
      next.amount = "Amount must be a number greater than zero.";
    }
    const trimmed = description.trim();
    if (!trimmed) next.description = "Description / vendor is required.";
    else if (trimmed.length > MAX_DESCRIPTION) {
      next.description = `Description must be at most ${MAX_DESCRIPTION} characters.`;
    }
    if (notes.trim().length > MAX_NOTES) {
      next.notes = `Notes must be at most ${MAX_NOTES} characters.`;
    }
    return next;
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      setAttempt((n) => n + 1);
      return;
    }
    const input: ItemizedEntryInput = {
      date,
      amount: toMoneyString(amount),
      description: description.trim(),
    };
    const trimmedNotes = notes.trim();
    if (trimmedNotes) input.notes = trimmedNotes;
    onSubmit(input);
  }

  function fieldError(field: Field): string | undefined {
    if (serverError?.field === field) {
      return serverError.message ?? "This value was rejected.";
    }
    return errors[field];
  }

  const generalServerError =
    serverError && !serverError.field ? serverError.message : undefined;

  const shownErrors: Partial<Record<Field, string>> = {
    date: fieldError("date"),
    amount: fieldError("amount"),
    description: fieldError("description"),
    notes: fieldError("notes"),
  };
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
        headingId="itemized-error-summary"
      />

      <FormField
        id={FIELD_IDS.date}
        errorId="itemized-date-error"
        label="Date"
        required
        error={fieldError("date")}
      >
        {(control) => (
          <DateInput {...control} value={date} onValueChange={setDate} />
        )}
      </FormField>

      <FormField
        id={FIELD_IDS.amount}
        errorId="itemized-amount-error"
        label="Amount"
        required
        error={fieldError("amount")}
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

      <FormField
        id={FIELD_IDS.description}
        errorId="itemized-description-error"
        label="Description / vendor"
        hint={`What the ${entryNoun} was, or who did the work.`}
        required
        error={fieldError("description")}
      >
        {(control) => (
          <Input
            {...control}
            type="text"
            maxLength={MAX_DESCRIPTION}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="block w-full"
          />
        )}
      </FormField>

      <FormField
        id={FIELD_IDS.notes}
        errorId="itemized-notes-error"
        label="Notes (optional)"
        error={fieldError("notes")}
      >
        {(control) => (
          <Textarea
            {...control}
            rows={3}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            className="block w-full"
          />
        )}
      </FormField>

      <ModalFormActions>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? "Save changes" : "Add entry"}
        </Button>
      </ModalFormActions>
    </form>
  );
}
