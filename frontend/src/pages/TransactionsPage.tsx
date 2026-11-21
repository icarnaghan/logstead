import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { PropertySection } from "../components/PropertySection";
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
import { listAssets, type DepreciableAsset } from "../api/assets";
import { latestCompletedTaxYear, parseYearParam } from "../lib/taxYears";
import { usePropertyYearRange } from "../lib/usePropertyYearRange";
import { TransactionForm } from "../components/transactions/TransactionForm";
import { TransactionList } from "../components/transactions/TransactionList";
import { TaxYearFilter } from "../components/transactions/TaxYearFilter";
import { ReceiptList } from "../components/transactions/ReceiptList";
import {
  Button,
  ConfirmDialog,
  EmptyGuide,
  Input,
  LoadingRegion,
  RecordModal,
  RefreshingIndicator,
  SearchIcon,
  Select,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
  useRecordModal,
  useToast,
  useUndoableDelete,
} from "../components/ui";
import { isTransactionSafeDelete, transactionToInput } from "../lib/undoMappers";
import { formatMoney } from "../lib/money";
import { filterTransactions } from "../lib/transactionFilter";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { useNewParam } from "../lib/useNewParam";
import { useFocusParam } from "../lib/useFocusParam";
import { EMPTY_COPY } from "../lib/emptyCopy";

/** Stable empty list so memoised derivations do not churn before first load. */
const NO_TRANSACTIONS: Transaction[] = [];

interface TransactionsPageProps {
  /** Injectable API for tests; defaults to the shared singleton. */
  api?: TransactionsApi;
}

/**
 * Per-property transactions page (Requirements 5.1–5.8, 7.3, 7.4).
 *
 * Renders the shared `PropertySection` (breadcrumb, property-name heading, and
 * per-property sub-navigation), then a tax-year filter, a date-descending
 * transaction
 * table, an add/edit dialog form with Schedule E category selection and
 * Other-requires-description enforcement, delete, and per-transaction receipt
 * attach/list/delete via pre-signed URL.
 */
export default function TransactionsPage({
  api = sharedApi,
}: TransactionsPageProps) {
  const { propertyId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const { notify } = useToast();

  const [categories, setCategories] = useState<Category[]>([]);
  // Default the filter to the latest completed tax year on load (the current
  // year cannot be filed yet); "All years" remains selectable.
  const [taxYear, setTaxYear] = useState<number | null>(
    () => parseYearParam(searchParams.get("year")) ?? latestCompletedTaxYear(),
  );
  // Delete failures are not list-load failures; they keep their own inline alert.
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // A property switch resets the resource (skeleton, no stale rows); a tax-year
  // change only refreshes, so rows stay mounted during that load.
  const {
    data: loadedTransactions,
    error: listError,
    status,
    reload: loadTransactions,
  } = useAsyncResource(
    (signal) => api.listTransactions(propertyId, taxYear ?? undefined, signal),
    {
      resetKeys: [propertyId],
      deps: [taxYear],
      describeError: () => "Could not load transactions.",
    },
  );
  const transactions = loadedTransactions ?? NO_TRANSACTIONS;
  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error: listError,
    resetKey: propertyId,
  });
  // Add/edit dialog state (open/edit/dirty tracked by useRecordModal).
  const toolbarRef = useRef<HTMLDivElement>(null);
  const modal = useRecordModal(transactions, { fallbackFocusRef: toolbarRef });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<ApiFieldError | null>(null);

  // Receipts state, keyed by the currently expanded transaction.
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ReceiptDocument[]>([]);

  // The transaction awaiting delete confirmation, if any (ConfirmDialog is
  // controlled). Clicking Delete on a row opens the dialog; only confirming
  // performs the deletion (Requirements 4.1–4.3).
  const [pendingDelete, setPendingDelete] = useState<Transaction | null>(null);
  const [pendingReceiptCount, setPendingReceiptCount] = useState<
    number | null
  >(null);
  const [deleting, setDeleting] = useState(false);

  // The property's depreciable assets drive the selectable-year range: from
  // the earliest in-service year through the latest completed tax year (the
  // current year cannot be filed yet). Loaded with an active-flag guard like
  // the property detail page.
  const [assets, setAssets] = useState<DepreciableAsset[]>([]);
  const years = usePropertyYearRange(propertyId, assets);

  // Client-side search and category filter over the loaded list
  // (Requirements 21.2–21.6, 21.10). Local state, no extra API calls.
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const presentCategories = useMemo(() => {
    const ids = new Set(transactions.map((t) => t.category_id));
    return categories.filter((c) => ids.has(c.id));
  }, [transactions, categories]);
  // Itemized entries in the loaded list (Requirements 10.3, 10.4). Keys are
  // `categoryId:year`, matching what TransactionForm looks up.
  const itemizedYears = useMemo(
    () =>
      new Set(
        transactions
          .filter((t) => t.itemized)
          .map((t) => `${t.category_id}:${t.date.slice(0, 4)}`),
      ),
    [transactions],
  );
  // A selection that left the loaded list (for example after a tax-year
  // change) no longer filters anything.
  const activeCategoryId =
    categoryId !== null && presentCategories.some((c) => c.id === categoryId)
      ? categoryId
      : null;
  const filterActive = query.trim() !== "" || activeCategoryId !== null;
  const visibleTransactions = useMemo(
    () =>
      filterTransactions(transactions, categories, {
        query,
        categoryId: activeCategoryId,
      }),
    [transactions, categories, query, activeCategoryId],
  );
  function clearFilters() {
    setQuery("");
    setCategoryId(null);
  }

  // Load the property's depreciable assets to size the tax-year range
  // (earliest in-service year → latest completed tax year). Degrades to an
  // empty list (recent-years fallback) on failure.
  useEffect(() => {
    if (!propertyId) return;
    let active = true;
    listAssets(propertyId)
      .then((loaded) => {
        if (active) setAssets(loaded);
      })
      .catch(() => {
        if (active) setAssets([]);
      });
    return () => {
      active = false;
    };
  }, [propertyId]);

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
    setFormError(null);
    modal.openAdd();
  }
  useNewParam(openCreate, view.showContent);
  useFocusParam(visibleTransactions, view.showContent);

  function openEdit(transaction: Transaction) {
    setFormError(null);
    modal.openEdit(transaction);
  }

  async function handleSubmit(input: TransactionInput) {
    setSubmitting(true);
    setFormError(null);
    try {
      const editingTx = modal.editing;
      const isEdit = editingTx !== null;
      if (editingTx) {
        await api.updateTransaction(propertyId, editingTx.id, input);
      } else {
        await api.createTransaction(propertyId, input);
      }
      modal.close();
      await loadTransactions();
      notify({
        variant: "success",
        title: isEdit ? "Transaction updated" : "Transaction added",
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 400) {
        // Validation errors stay in the form next to the field.
        setFormError(
          fieldErrorFrom(error.body) ?? { message: error.message },
        );
      } else {
        // Non-field failures also surface as an error toast (Requirement 5.4).
        setFormError({ message: "Could not save the transaction." });
        notify({
          variant: "error",
          title: "Could not save transaction",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  // Safe_Delete path (Requirements 13.1, 13.7): Undo re-creates the
  // transaction through createTransaction with the retained fields.
  const undoableDelete = useUndoableDelete<Transaction>({
    remove: async (transaction) => {
      await api.deleteTransaction(propertyId, transaction.id);
      if (expandedId === transaction.id) {
        setExpandedId(null);
        setReceipts([]);
      }
      modal.onRecordDeleted(transaction.id);
    },
    restore: (transaction) =>
      api.createTransaction(propertyId, transactionToInput(transaction)),
    refresh: () => loadTransactions(),
    deletedTitle: () => "Transaction deleted",
    restoredTitle: "Transaction restored",
    restoreFailedTitle: "Could not restore the transaction",
    deleteFailedTitle: "Could not delete transaction",
  });

  async function requestDelete(transaction: Transaction) {
    // Look up receipts first. A failed lookup is "unknown", never safe.
    let count: number | null = null;
    try {
      count = (await api.listReceipts(propertyId, transaction.id)).length;
    } catch {
      count = null;
    }
    if (isTransactionSafeDelete(transaction, count)) {
      setDeleteError(null);
      await undoableDelete(transaction);
      return;
    }
    setPendingReceiptCount(count);
    setPendingDelete(transaction);
  }

  async function confirmDelete() {
    const transaction = pendingDelete;
    if (!transaction) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteTransaction(propertyId, transaction.id);
      if (expandedId === transaction.id) {
        setExpandedId(null);
        setReceipts([]);
      }
      modal.onRecordDeleted(transaction.id);
      setPendingDelete(null);
      await loadTransactions();
      notify({ variant: "success", title: "Transaction deleted" });
    } catch {
      setDeleteError("Could not delete the transaction.");
      notify({
        variant: "error",
        title: "Could not delete transaction",
      });
      setPendingDelete(null);
    } finally {
      setDeleting(false);
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

  return (
    <>
      <PropertySection
        propertyId={propertyId}
        title="Transactions"
        description="Record income and expenses for this property, categorize each to a Schedule E line, and attach supporting documents."
      />

      <div
        ref={toolbarRef}
        tabIndex={-1}
        className="mt-6 flex flex-wrap items-center justify-between gap-3 focus:outline-none"
      >
        <div className="flex flex-wrap items-center gap-3">
          <TaxYearFilter value={taxYear} years={years} onChange={setTaxYear} />

          <div className="relative">
            <SearchIcon
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted"
            />
            <Input
              type="search"
              aria-label="Search transactions"
              placeholder="Search transactions"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-9"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor="transaction-category-filter"
              className="text-sm font-medium text-fg-muted"
            >
              Category
            </label>
            <Select
              id="transaction-category-filter"
              value={activeCategoryId ?? "all"}
              onChange={(event) =>
                setCategoryId(
                  event.target.value === "all" ? null : event.target.value,
                )
              }
            >
              <option value="all">All categories</option>
              {presentCategories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.label}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <Button type="button" variant="primary" onClick={openCreate}>
          Add transaction
        </Button>
      </div>

      <RecordModal
        open={modal.open}
        onOpenChange={(next) => {
          if (!next) modal.requestClose();
        }}
        discard={modal.discard}
        title={modal.editing ? "Edit transaction" : "Add transaction"}
        description="Categorize the amount to a Schedule E line. The Other category (Line 19) requires a description."
        dismissible={!submitting}
        onCloseAutoFocus={modal.handleCloseAutoFocus}
      >
        <TransactionForm
          key={modal.editing?.id ?? "new"}
          categories={categories}
          taxYear={taxYear ?? latestCompletedTaxYear()}
          itemizedYears={itemizedYears}
          initial={modal.editing ?? undefined}
          serverError={formError}
          submitting={submitting}
          onSubmit={handleSubmit}
          onCancel={modal.requestClose}
          onDirtyChange={modal.setDirty}
        />
      </RecordModal>

      {deleteError ? (
        <p role="alert" className="mt-4 text-sm text-danger">
          {deleteError}
        </p>
      ) : null}

      {view.showSkeleton ? (
        <div className="mt-4">
          <LoadingRegion label="Loading transactions">
            <TableSkeleton columns={5} />
          </LoadingRegion>
        </div>
      ) : null}

      {view.showError ? (
        <div className={view.errorIsStale ? "mt-4 mb-4" : "mt-4"}>
          <StateBlock
            kind="error"
            compact={view.errorIsStale}
            title="Could not load transactions"
            description={listError ?? undefined}
            onRetry={() => void loadTransactions()}
          />
        </div>
      ) : null}

      {view.refreshing ? <RefreshingIndicator className="mt-4 mb-4" /> : null}

      {/* Count shown only while a filter is active (21.9). */}
      {view.showContent && transactions.length > 0 && filterActive ? (
        <p
          role="status"
          aria-live="polite"
          className="mt-4 text-sm text-fg-muted"
        >
          Showing {visibleTransactions.length} of {transactions.length}{" "}
          transactions
        </p>
      ) : null}

      {view.showContent && itemizedYears.size > 0 ? (
        <p className="mt-4 text-sm text-fg-muted">
          Itemized entries are supporting detail. Line 14 uses the entered
          total when one exists.
        </p>
      ) : null}

      {!view.showContent ? null : transactions.length === 0 ? (
        <EmptyGuide
          title={EMPTY_COPY.transactions.title}
          description={EMPTY_COPY.transactions.description}
          primary={{
            label: EMPTY_COPY.transactions.primaryLabel,
            onClick: openCreate,
          }}
        />
      ) : visibleTransactions.length === 0 ? (
        <StateBlock
          kind="empty"
          title="No transactions match your filters"
          action={{ label: "Clear filters", onClick: clearFilters }}
        />
      ) : (
        <TransactionList
          transactions={visibleTransactions}
          categories={categories}
          expandedId={expandedId}
          onEdit={openEdit}
          onDelete={(t) => void requestDelete(t)}
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

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Delete transaction"
        description={
          pendingDelete
            ? `Delete the ${formatMoney(pendingDelete.amount)} transaction from ${pendingDelete.date}?${
                pendingReceiptCount
                  ? ` Its ${pendingReceiptCount === 1 ? "receipt" : `${pendingReceiptCount} receipts`} will also be deleted.`
                  : ""
              } This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        pending={deleting}
      />
    </>
  );
}
