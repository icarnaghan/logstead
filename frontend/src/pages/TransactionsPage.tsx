import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useParams } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { PROPERTY_NAV, propertyPath } from "../components/navConfig";
import {
  transactionsApi as sharedApi,
  fieldErrorFrom,
  type ApiFieldError,
  type Category,
  type ReceiptDocument,
  type Transaction,
  type TransactionInput,
  type TransactionsApi,
} from "../api/transactions";
import { ApiError } from "../lib/apiClient";
import { TransactionForm } from "../components/transactions/TransactionForm";
import { TransactionList } from "../components/transactions/TransactionList";
import { TaxYearFilter } from "../components/transactions/TaxYearFilter";
import { ReceiptList } from "../components/transactions/ReceiptList";

interface TransactionsPageProps {
  /** Injectable API for tests; defaults to the shared singleton. */
  api?: TransactionsApi;
}

function recentYears(count = 6): number[] {
  const current = new Date().getFullYear();
  return Array.from({ length: count }, (_, index) => current - index);
}

/**
 * Per-property transactions page (Requirements 5.1–5.8, 7.3, 7.4).
 *
 * Renders the per-property sub-navigation and heading (mirroring
 * `PropertySection`), then a tax-year filter, a date-descending transaction
 * table, an add/edit dialog form with Schedule E category selection and
 * Other-requires-description enforcement, delete, and per-transaction receipt
 * attach/list/delete via pre-signed URL.
 */
export default function TransactionsPage({
  api = sharedApi,
}: TransactionsPageProps) {
  const { propertyId = "" } = useParams();

  const [categories, setCategories] = useState<Category[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [taxYear, setTaxYear] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  // Add/edit dialog state.
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<ApiFieldError | null>(null);

  // Receipts state, keyed by the currently expanded transaction.
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ReceiptDocument[]>([]);

  const years = useMemo(() => recentYears(), []);

  const loadTransactions = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setListError(null);
      try {
        const rows = await api.listTransactions(
          propertyId,
          taxYear ?? undefined,
          signal,
        );
        setTransactions(rows);
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setListError("Could not load transactions.");
      } finally {
        setLoading(false);
      }
    },
    [api, propertyId, taxYear],
  );

  // Load the category catalog once.
  useEffect(() => {
    const controller = new AbortController();
    api
      .listCategories(controller.signal)
      .then(setCategories)
      .catch(() => {
        /* categories are optional to render the list; form will be empty */
      });
    return () => controller.abort();
  }, [api]);

  // (Re)load transactions when property or tax-year filter changes
  // (Requirement 5.5 re-queries on filter change).
  useEffect(() => {
    const controller = new AbortController();
    void loadTransactions(controller.signal);
    return () => controller.abort();
  }, [loadTransactions]);

  const refreshReceipts = useCallback(
    async (transactionId: string) => {
      try {
        const docs = await api.listReceipts(propertyId, transactionId);
        setReceipts(docs);
      } catch {
        setReceipts([]);
      }
    },
    [api, propertyId],
  );

  function openCreate() {
    setEditing(null);
    setFormError(null);
    setDialogOpen(true);
  }

  function openEdit(transaction: Transaction) {
    setEditing(transaction);
    setFormError(null);
    setDialogOpen(true);
  }

  async function handleSubmit(input: TransactionInput) {
    setSubmitting(true);
    setFormError(null);
    try {
      if (editing) {
        await api.updateTransaction(propertyId, editing.id, input);
      } else {
        await api.createTransaction(propertyId, input);
      }
      setDialogOpen(false);
      setEditing(null);
      await loadTransactions();
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        setFormError(
          fieldErrorFrom(error.body) ?? { message: error.message },
        );
      } else {
        setFormError({ message: "Could not save the transaction." });
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(transaction: Transaction) {
    try {
      await api.deleteTransaction(propertyId, transaction.id);
      if (expandedId === transaction.id) {
        setExpandedId(null);
        setReceipts([]);
      }
      await loadTransactions();
    } catch {
      setListError("Could not delete the transaction.");
    }
  }

  function handleToggleReceipts(transaction: Transaction) {
    if (expandedId === transaction.id) {
      setExpandedId(null);
      setReceipts([]);
      return;
    }
    setExpandedId(transaction.id);
    setReceipts([]);
    void refreshReceipts(transaction.id);
  }

  const closeButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <section aria-labelledby="page-heading">
      <h1 id="page-heading" className="text-2xl font-semibold text-fg">
        Transactions
      </h1>
      <p className="mt-1 text-sm text-fg-subtle">Property: {propertyId}</p>

      <nav aria-label="Property sections" className="mt-4">
        <ul className="flex flex-wrap gap-2">
          {PROPERTY_NAV.map((item) => (
            <li key={item.segment}>
              <NavLink
                to={propertyPath(propertyId, item.segment)}
                className={({ isActive }) =>
                  [
                    "inline-block rounded-md px-3 py-1.5 text-sm font-medium",
                    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    isActive
                      ? "bg-accent text-accent-fg"
                      : "text-fg-muted hover:bg-surface-muted",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <TaxYearFilter value={taxYear} years={years} onChange={setTaxYear} />

        <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}>
          <Dialog.Trigger asChild>
            <button
              type="button"
              onClick={openCreate}
              className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Add transaction
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 bg-slate-900/40" />
            <Dialog.Content className="fixed left-1/2 top-1/2 w-[min(32rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-surface p-6 shadow-xl focus:outline-none">
              <Dialog.Title className="text-lg font-semibold text-fg">
                {editing ? "Edit transaction" : "Add transaction"}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-fg-subtle">
                Categorize the amount to a Schedule E line. The Other category
                (Line 19) requires a description.
              </Dialog.Description>
              <div className="mt-4">
                <TransactionForm
                  categories={categories}
                  taxYear={taxYear ?? new Date().getFullYear()}
                  initial={editing ?? undefined}
                  serverError={formError}
                  submitting={submitting}
                  onSubmit={handleSubmit}
                  onCancel={() => setDialogOpen(false)}
                />
              </div>
              <Dialog.Close asChild>
                <button
                  ref={closeButtonRef}
                  type="button"
                  aria-label="Close"
                  className="absolute right-3 top-3 rounded p-1 text-fg-subtle hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  ×
                </button>
              </Dialog.Close>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>

      {listError ? (
        <p role="alert" className="mt-4 text-sm text-danger">
          {listError}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-4 text-fg-muted">Loading transactions…</p>
      ) : (
        <TransactionList
          transactions={transactions}
          categories={categories}
          expandedId={expandedId}
          onEdit={openEdit}
          onDelete={handleDelete}
          onToggleReceipts={handleToggleReceipts}
          renderReceipts={(transaction) => (
            <ReceiptList
              api={api}
              propertyId={propertyId}
              transactionId={transaction.id}
              receipts={receipts}
              onChanged={() => void refreshReceipts(transaction.id)}
            />
          )}
        />
      )}
    </section>
  );
}
