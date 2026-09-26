import { useState } from "react";
import type {
  Category,
  DraftChanges,
  DraftTransaction,
  TransactionType,
} from "../../api/imports";
import { Button } from "../ui";

interface DraftRowProps {
  draft: DraftTransaction;
  categories: Category[];
  /** Save edits to this draft; resolves once `missing_fields` is recomputed. */
  onSave: (draftId: string, changes: DraftChanges) => Promise<void>;
  /** Remove this draft from the review set. */
  onRemove: (draftId: string) => Promise<void>;
  /** Disable controls while a session-wide action (e.g. confirm) is running. */
  disabled?: boolean;
}

/** Human-friendly labels for the flaggable missing fields (Requirement 6.9). */
const FIELD_LABELS: Record<string, string> = {
  date: "Date",
  amount: "Amount",
  category_id: "Category",
  description: "Description",
  type: "Type",
};

function labelFor(field: string): string {
  return FIELD_LABELS[field] ?? field;
}

/**
 * A single reviewable draft transaction.
 *
 * Shows the parsed date/amount/description/category with inline edit controls
 * so the user can complete missing fields (Requirement 6.7). Any
 * `missing_fields` are surfaced as an accessible alert and the corresponding
 * inputs are marked `aria-invalid` (Requirement 6.9). A remove action drops the
 * draft (Requirement 6.8).
 */
export function DraftRow({
  draft,
  categories,
  onSave,
  onRemove,
  disabled = false,
}: DraftRowProps) {
  const [date, setDate] = useState(draft.date ?? "");
  const [amount, setAmount] = useState(draft.amount ?? "");
  const [description, setDescription] = useState(draft.description ?? "");
  const [type, setType] = useState<TransactionType | "">(draft.type ?? "");
  const [categoryId, setCategoryId] = useState(draft.category_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const missing = draft.missing_fields ?? [];
  const isMissing = (field: string) => missing.includes(field);

  const selectedCategory = categories.find((c) => c.id === categoryId);
  // Line 19 ("Other") requires a description (Requirement 7.4).
  const descriptionRequired = selectedCategory?.requires_description ?? false;

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      const changes: DraftChanges = {
        date: date === "" ? null : date,
        amount: amount === "" ? null : amount,
        description: description === "" ? null : description,
        type: type === "" ? null : type,
        category_id: categoryId === "" ? null : categoryId,
      };
      await onSave(draft.id, changes);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save this draft.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove() {
    setBusy(true);
    setError(null);
    try {
      await onRemove(draft.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not remove this draft.");
    } finally {
      setBusy(false);
    }
  }

  const controlsDisabled = disabled || busy;
  const dateId = `draft-${draft.id}-date`;
  const amountId = `draft-${draft.id}-amount`;
  const typeId = `draft-${draft.id}-type`;
  const categoryId_ = `draft-${draft.id}-category`;
  const descId = `draft-${draft.id}-description`;

  return (
    <li
      className="rounded-md border border-border p-4"
      aria-label="Draft transaction"
    >
      {missing.length > 0 && (
        <p
          role="alert"
          className="mb-3 rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
        >
          Missing before confirming: {missing.map(labelFor).join(", ")}
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="flex flex-col">
          <label htmlFor={dateId} className="text-sm font-medium text-fg-muted">
            Date
          </label>
          <input
            id={dateId}
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            disabled={controlsDisabled}
            aria-invalid={isMissing("date") || undefined}
            className="mt-1 rounded-md border border-border px-2 py-1.5 text-sm"
          />
        </div>

        <div className="flex flex-col">
          <label
            htmlFor={amountId}
            className="text-sm font-medium text-fg-muted"
          >
            Amount
          </label>
          <input
            id={amountId}
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            disabled={controlsDisabled}
            aria-invalid={isMissing("amount") || undefined}
            className="mt-1 rounded-md border border-border px-2 py-1.5 text-sm"
          />
        </div>

        <div className="flex flex-col">
          <label htmlFor={typeId} className="text-sm font-medium text-fg-muted">
            Type
          </label>
          <select
            id={typeId}
            value={type}
            onChange={(e) => setType(e.target.value as TransactionType | "")}
            disabled={controlsDisabled}
            aria-invalid={isMissing("type") || undefined}
            className="mt-1 rounded-md border border-border px-2 py-1.5 text-sm"
          >
            <option value="">Select a type</option>
            <option value="income">Income</option>
            <option value="expense">Expense</option>
          </select>
        </div>

        <div className="flex flex-col">
          <label
            htmlFor={categoryId_}
            className="text-sm font-medium text-fg-muted"
          >
            Category
          </label>
          <select
            id={categoryId_}
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            disabled={controlsDisabled}
            aria-invalid={isMissing("category_id") || undefined}
            className="mt-1 rounded-md border border-border px-2 py-1.5 text-sm"
          >
            <option value="">Select a category</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col md:col-span-2">
          <label htmlFor={descId} className="text-sm font-medium text-fg-muted">
            Description{descriptionRequired ? " (required)" : ""}
          </label>
          <input
            id={descId}
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={controlsDisabled}
            aria-invalid={
              (isMissing("description") ||
                (descriptionRequired && description === "")) ||
              undefined
            }
            className="mt-1 rounded-md border border-border px-2 py-1.5 text-sm"
          />
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={handleSave}
          disabled={controlsDisabled}
        >
          Save draft
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={handleRemove}
          disabled={controlsDisabled}
        >
          Remove
        </Button>
      </div>
    </li>
  );
}
