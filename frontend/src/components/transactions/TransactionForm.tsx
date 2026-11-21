import { useMemo, useState } from "react";
import type {
  ApiFieldError,
  Category,
  Transaction,
  TransactionInput,
  TransactionType,
} from "../../api/transactions";
import { CategorySelect } from "./CategorySelect";
import {
  Button,
  ErrorSummary,
  FormField,
  MoneyInput,
  Textarea,
  useFocusFirstInvalid,
  ModalFormActions,
} from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";
import { useDirtyReporter } from "../../lib/dirty";
import { isPositiveAmount, toMoneyString } from "../../lib/money";

interface TransactionFormProps {
  categories: readonly Category[];
  /**
   * The tax year new entries belong to. Entries are year-end totals, so the
   * date field is hidden and the stored date defaults to Dec 31 of this year.
   */
  taxYear: number;
  /**
   * Keys (`categoryId:year`) of categories with itemized entries in the loaded
   * list. Drives the Requirement 10.4 hint; never blocks saving.
   */
  itemizedYears?: ReadonlySet<string>;
  /** When present, the form edits this transaction; otherwise it creates one. */
  initial?: Transaction;
  /**
   * A server-side field error (HTTP 400 with `field`) to surface adjacent to
   * the offending control (Requirement 14.3).
   */
  serverError?: ApiFieldError | null;
  submitting?: boolean;
  onSubmit: (input: TransactionInput) => void;
  onCancel: () => void;
  /** Reports whether the form has unsaved edits. */
  onDirtyChange?: (dirty: boolean) => void;
}

type FieldErrors = Partial<
  Record<"date" | "amount" | "category_id" | "description", string>
>;

const FIELD_ORDER = ["amount", "category_id", "description"] as const;
const FIELD_IDS: Record<(typeof FIELD_ORDER)[number], string> = {
  amount: "tx-amount",
  category_id: "tx-category",
  description: "tx-description",
};
const idFor = (field: string) =>
  FIELD_IDS[field as keyof typeof FIELD_IDS] ?? field;

/** Dec 31 of the given tax year as an ISO date (year-end totals default). */
const yearEnd = (year: number) => `${year}-12-31`;

/**
 * Create/edit form for a transaction (Requirements 5.1, 5.2, 5.3, 5.6, 7.3,
 * 7.4).
 *
 * Client-side validation blocks submit for a missing date/amount/category, a
 * non-positive amount, and — when the selected category requires it (the
 * "Other" / Line 19 expense) — a missing description (Requirement 7.4). Server
 * 400 field errors are surfaced next to their control too, so the server stays
 * the source of truth. The category select shows the Schedule E line for the
 * chosen category (Requirement 7.3).
 */
export function TransactionForm({
  categories,
  taxYear,
  itemizedYears,
  initial,
  serverError,
  submitting = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: TransactionFormProps) {
  const [type, setType] = useState<TransactionType>(initial?.type ?? "expense");
  // Year-end totals: keep an editing entry's own date, else default to the
  // selected tax year's Dec 31. The date field itself is not shown.
  const [date] = useState<string>(initial?.date ?? yearEnd(taxYear));
  const [amount, setAmount] = useState<string>(initial?.amount ?? "");
  const [categoryId, setCategoryId] = useState<string>(
    initial?.category_id ?? "",
  );
  const [description, setDescription] = useState<string>(
    initial?.description ?? "",
  );
  const [initialValues] = useState(() => ({
    type: initial?.type ?? "expense",
    amount: initial?.amount ?? "",
    categoryId: initial?.category_id ?? "",
    description: initial?.description ?? "",
  }));
  useDirtyReporter(
    initialValues,
    { type, amount, categoryId, description },
    onDirtyChange,
  );
  const [errors, setErrors] = useState<FieldErrors>({});
  const [attempt, setAttempt] = useState(0);
  const [prevServerError, setPrevServerError] = useState(serverError);
  if (prevServerError !== serverError) {
    setPrevServerError(serverError);
    if (serverError?.field) setAttempt((n) => n + 1);
  }

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId),
    [categories, categoryId],
  );
  const descriptionRequired = selectedCategory?.requires_description ?? false;
  const showItemizedHint =
    !initial &&
    selectedCategory !== undefined &&
    (itemizedYears?.has(`${selectedCategory.id}:${taxYear}`) ?? false);

  function validate(): FieldErrors {
    const next: FieldErrors = {};
    if (!amount.trim()) {
      next.amount = "Amount is required.";
    } else if (!isPositiveAmount(amount)) {
      next.amount = "Amount must be a number greater than zero.";
    }
    if (!categoryId) next.category_id = "Category is required.";
    if (descriptionRequired && !description.trim()) {
      next.description =
        "A description is required for the Other category (Line 19).";
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

    const input: TransactionInput = {
      date,
      amount: toMoneyString(amount),
      type,
      category_id: categoryId,
    };
    const trimmedDescription = description.trim();
    if (trimmedDescription) input.description = trimmedDescription;
    onSubmit(input);
  }

  // A server error for a field takes precedence over the (cleared) client one.
  function fieldError(
    field: "date" | "amount" | "category_id" | "description",
  ): string | undefined {
    if (serverError?.field === field) {
      return serverError.message ?? "This value was rejected.";
    }
    return errors[field];
  }

  const generalServerError =
    serverError && !serverError.field ? serverError.message : undefined;

  const shownErrors: Partial<Record<(typeof FIELD_ORDER)[number], string>> = {
    amount: fieldError("amount"),
    category_id: fieldError("category_id"),
    description: fieldError("description"),
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
        headingId="tx-error-summary"
      />

      <fieldset>
        <legend className="text-sm font-medium text-fg">Type</legend>
        <div className="mt-1 flex gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg-muted">
            <input
              type="radio"
              name="tx-type"
              value="income"
              checked={type === "income"}
              onChange={() => {
                setType("income");
                setCategoryId("");
              }}
            />
            Income
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg-muted">
            <input
              type="radio"
              name="tx-type"
              value="expense"
              checked={type === "expense"}
              onChange={() => {
                setType("expense");
                setCategoryId("");
              }}
            />
            Expense
          </label>
        </div>
      </fieldset>

      <FormField
        id="tx-amount"
        errorId="tx-amount-error"
        label="Amount"
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
        id="tx-category"
        errorId="tx-category-error"
        label="Category"
        hint={
          selectedCategory
            ? `Schedule E Line ${selectedCategory.schedule_e_line}`
            : undefined
        }
        error={fieldError("category_id")}
      >
        {(control) => (
          <CategorySelect
            id={control.id}
            categories={categories}
            value={categoryId}
            kind={type}
            onChange={setCategoryId}
            invalid={control.invalid}
            describedBy={control["aria-describedby"]}
          />
        )}
      </FormField>

      {showItemizedHint ? (
        <p id="tx-itemized-hint" className="text-sm text-fg-muted">
          This year has itemized {selectedCategory?.label.toLowerCase()}{" "}
          entries. The new transaction becomes the entered total and replaces
          the itemized sum on line {selectedCategory?.schedule_e_line}.
        </p>
      ) : null}

      <FormField
        id="tx-description"
        errorId="tx-description-error"
        label={`Description${descriptionRequired ? " (required)" : " (optional)"}`}
        error={fieldError("description")}
      >
        {(control) => (
          <Textarea
            {...control}
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            className="block w-full"
          />
        )}
      </FormField>

      <ModalFormActions>
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? "Save changes" : "Add transaction"}
        </Button>
      </ModalFormActions>
    </form>
  );
}
