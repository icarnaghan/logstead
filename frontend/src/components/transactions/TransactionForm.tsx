import { useMemo, useState } from "react";
import type {
  ApiFieldError,
  Category,
  Transaction,
  TransactionInput,
  TransactionType,
} from "../../api/transactions";
import { CategorySelect } from "./CategorySelect";
import { Button } from "../ui";
import { isPositiveAmount, toMoneyString } from "../../lib/money";

interface TransactionFormProps {
  categories: readonly Category[];
  /**
   * The tax year new entries belong to. Entries are year-end totals, so the
   * date field is hidden and the stored date defaults to Dec 31 of this year.
   */
  taxYear: number;
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
}

type FieldErrors = Partial<
  Record<"date" | "amount" | "category_id" | "description", string>
>;

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
  initial,
  serverError,
  submitting = false,
  onSubmit,
  onCancel,
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
  const [errors, setErrors] = useState<FieldErrors>({});

  const selectedCategory = useMemo(
    () => categories.find((c) => c.id === categoryId),
    [categories, categoryId],
  );
  const descriptionRequired = selectedCategory?.requires_description ?? false;

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
    if (Object.keys(found).length > 0) return;

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

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      {generalServerError ? (
        <p role="alert" className="text-sm text-danger">
          {generalServerError}
        </p>
      ) : null}

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

      <div>
        <label
          htmlFor="tx-amount"
          className="text-sm font-medium text-fg"
        >
          Amount
        </label>
        <input
          id="tx-amount"
          type="text"
          inputMode="decimal"
          placeholder="0.00"
          value={amount}
          aria-invalid={fieldError("amount") ? true : undefined}
          aria-describedby={
            fieldError("amount") ? "tx-amount-error" : undefined
          }
          onChange={(event) => setAmount(event.target.value)}
          className="mt-1 block w-full rounded-md border border-border px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
        {fieldError("amount") ? (
          <p
            id="tx-amount-error"
            role="alert"
            className="mt-1 text-sm text-danger"
          >
            {fieldError("amount")}
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor="tx-category"
          className="text-sm font-medium text-fg"
        >
          Category
        </label>
        <CategorySelect
          id="tx-category"
          categories={categories}
          value={categoryId}
          kind={type}
          onChange={setCategoryId}
          invalid={fieldError("category_id") ? true : undefined}
          describedBy={
            fieldError("category_id") ? "tx-category-error" : undefined
          }
        />
        {selectedCategory ? (
          <p className="mt-1 text-xs text-fg-subtle">
            Schedule E Line {selectedCategory.schedule_e_line}
          </p>
        ) : null}
        {fieldError("category_id") ? (
          <p
            id="tx-category-error"
            role="alert"
            className="mt-1 text-sm text-danger"
          >
            {fieldError("category_id")}
          </p>
        ) : null}
      </div>

      <div>
        <label
          htmlFor="tx-description"
          className="text-sm font-medium text-fg"
        >
          Description{descriptionRequired ? " (required)" : " (optional)"}
        </label>
        <textarea
          id="tx-description"
          rows={2}
          value={description}
          aria-invalid={fieldError("description") ? true : undefined}
          aria-describedby={
            fieldError("description") ? "tx-description-error" : undefined
          }
          onChange={(event) => setDescription(event.target.value)}
          className="mt-1 block w-full rounded-md border border-border px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        />
        {fieldError("description") ? (
          <p
            id="tx-description-error"
            role="alert"
            className="mt-1 text-sm text-danger"
          >
            {fieldError("description")}
          </p>
        ) : null}
      </div>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {initial ? "Save changes" : "Add transaction"}
        </Button>
      </div>
    </form>
  );
}
