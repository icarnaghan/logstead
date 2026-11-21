import { useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { PropertySection } from "../components/PropertySection";
import { propertyPath } from "../components/navConfig";
import {
  itemizedApi as sharedApi,
  type ItemizedApi,
  type ItemizedEntryInput,
} from "../api/itemized";
import {
  transactionsApi as sharedTransactionsApi,
  fieldErrorFrom,
  type ApiFieldError,
  type ReceiptDocument,
  type Transaction,
  type TransactionsApi,
} from "../api/transactions";
import { ApiError } from "../lib/apiClient";
import { latestCompletedTaxYear } from "../lib/taxYears";
import { usePropertyYearRange } from "../lib/usePropertyYearRange";
import { formatMoney } from "../lib/money";
import { syncLabel, syncVisible } from "../lib/itemizedMath";
import {
  isItemizedEntrySafeDelete,
  itemizedEntryToInput,
} from "../lib/undoMappers";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { useNewParam } from "../lib/useNewParam";
import { useFocusParam } from "../lib/useFocusParam";
import { EMPTY_COPY } from "../lib/emptyCopy";
import type { ItemizedPageDefinition } from "../lib/itemizedPages";
import { ReceiptList } from "../components/transactions/ReceiptList";
import { EnteredTotalCard } from "../components/itemized/EnteredTotalCard";
import { ItemizedEntryForm } from "../components/itemized/ItemizedEntryForm";
import { ItemizedEntryList } from "../components/itemized/ItemizedEntryList";
import { ItemizedSummaryPanel } from "../components/itemized/ItemizedSummaryPanel";
import { SyncTotalDialog } from "../components/itemized/SyncTotalDialog";
import { TotalForm } from "../components/itemized/TotalForm";
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyGuide,
  LoadingRegion,
  RecordModal,
  RefreshingIndicator,
  Select,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
  useRecordModal,
  useToast,
  useUndoableDelete,
} from "../components/ui";

const NO_ROWS: Transaction[] = [];

interface ItemizedExpensesPageProps {
  definition: ItemizedPageDefinition;
  /** Injectable itemized API for tests; defaults to the shared singleton. */
  api?: ItemizedApi;
  /** Injectable receipts API (receipts reuse the transactions routes). */
  receiptsApi?: TransactionsApi;
}

function parseYear(raw: string | null): number | null {
  if (raw === null || !/^\d{4}$/.test(raw)) return null;
  return Number(raw);
}

function errorToField(error: unknown, fallback: string): ApiFieldError {
  if (error instanceof ApiError && error.status === 400) {
    return fieldErrorFrom(error.body) ?? { message: error.message };
  }
  return { message: fallback };
}

/**
 * Generic itemized-expenses page (Requirements 1.2-1.5, 1.7-1.9, 2.1, 2.7,
 * 7.11, 8.2, 8.4, 8.5, 8.8, 8.9, 9.5-9.8, 15.1-15.3, 15.5, 16.4).
 *
 * The year summary is the single source of figures; every mutation reloads it.
 * The document title ("Repairs - {property name}") is set by PropertySection.
 */
export default function ItemizedExpensesPage({
  definition,
  api = sharedApi,
  receiptsApi = sharedTransactionsApi,
}: ItemizedExpensesPageProps) {
  const { propertyId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { notify } = useToast();
  const { categoryId, tabLabel, line, entryNoun } = definition;

  const [taxYear, setTaxYear] = useState<number>(
    () => parseYear(searchParams.get("year")) ?? latestCompletedTaxYear(),
  );
  const yearRange = usePropertyYearRange(propertyId, []);
  const years = useMemo(
    () =>
      yearRange.includes(taxYear)
        ? yearRange
        : [...yearRange, taxYear].sort((a, b) => b - a),
    [yearRange, taxYear],
  );

  const {
    data: loaded,
    error: loadError,
    status,
    reload,
  } = useAsyncResource(
    (signal) => api.getSummary(propertyId, categoryId, taxYear, signal),
    {
      resetKeys: [propertyId],
      deps: [taxYear],
      describeError: () => `Could not load ${tabLabel.toLowerCase()}.`,
    },
  );
  const summary = loaded && loaded.tax_year === taxYear ? loaded : null;
  const view = useFirstLoad({
    loading: isAsyncLoading(status),
    error: loadError,
    resetKey: propertyId,
  });
  const entries = summary?.entries ?? NO_ROWS;
  const totalRows = summary?.entered_total_rows ?? NO_ROWS;

  const toolbarRef = useRef<HTMLDivElement>(null);
  const entryModal = useRecordModal(entries, { fallbackFocusRef: toolbarRef });
  const totalModal = useRecordModal(totalRows, {
    fallbackFocusRef: toolbarRef,
  });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<ApiFieldError | null>(null);
  const [totalError, setTotalError] = useState<ApiFieldError | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<ReceiptDocument[]>([]);

  const [pendingDelete, setPendingDelete] = useState<Transaction | null>(null);
  const [pendingRemoveTotal, setPendingRemoveTotal] =
    useState<Transaction | null>(null);
  const [pendingReceiptCount, setPendingReceiptCount] = useState<number | null>(
    null,
  );
  const [confirming, setConfirming] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);

  function changeYear(next: number) {
    setTaxYear(next);
    setExpandedId(null);
    setReceipts([]);
    setSearchParams({ year: String(next) }, { replace: true });
  }

  async function refreshSummary() {
    try {
      await reload();
    } catch {
      // The StateBlock reports a failed load; do not break the flow.
    }
  }

  async function refreshReceipts(id: string) {
    try {
      setReceipts(await receiptsApi.listReceipts(propertyId, id));
    } catch {
      setReceipts([]);
    }
  }

  function toggleDocuments(row: Transaction) {
    if (expandedId === row.id) {
      setExpandedId(null);
      setReceipts([]);
      return;
    }
    setExpandedId(row.id);
    setReceipts([]);
    void refreshReceipts(row.id);
  }

  function collapseIf(id: string) {
    if (expandedId === id) {
      setExpandedId(null);
      setReceipts([]);
    }
  }

  async function receiptCount(id: string): Promise<number | null> {
    try {
      return (await receiptsApi.listReceipts(propertyId, id)).length;
    } catch {
      return null;
    }
  }

  // ---- Entries ----

  function openAddEntry() {
    setFormError(null);
    entryModal.openAdd();
  }
  useNewParam(openAddEntry, view.showContent);
  useFocusParam(entries, view.showContent);

  function openEditEntry(entry: Transaction) {
    setFormError(null);
    entryModal.openEdit(entry);
  }

  async function handleEntrySubmit(input: ItemizedEntryInput) {
    setSubmitting(true);
    setFormError(null);
    const editing = entryModal.editing;
    try {
      if (editing) {
        await api.updateEntry(propertyId, categoryId, editing.id, input);
      } else {
        await api.createEntry(propertyId, categoryId, input);
      }
      entryModal.close();
      await refreshSummary();
      notify({
        variant: "success",
        title: editing ? "Entry updated" : "Entry added",
      });
    } catch (error) {
      setFormError(errorToField(error, `Could not save the ${entryNoun}.`));
      if (!(error instanceof ApiError && error.status === 400)) {
        notify({ variant: "error", title: `Could not save ${entryNoun}` });
      }
      await refreshSummary();
    } finally {
      setSubmitting(false);
    }
  }

  const undoableEntryDelete = useUndoableDelete<Transaction>({
    remove: async (entry) => {
      await api.deleteEntry(propertyId, categoryId, entry.id);
      collapseIf(entry.id);
      entryModal.onRecordDeleted(entry.id);
    },
    restore: (entry) =>
      api.createEntry(propertyId, categoryId, itemizedEntryToInput(entry)),
    refresh: () => reload(),
    deletedTitle: () => "Entry deleted",
    restoredTitle: "Entry restored",
    restoreFailedTitle: `Could not restore the ${entryNoun}`,
    deleteFailedTitle: `Could not delete ${entryNoun}`,
  });

  async function requestEntryDelete(entry: Transaction) {
    const count = await receiptCount(entry.id);
    if (isItemizedEntrySafeDelete(entry, count)) {
      await undoableEntryDelete(entry);
      return;
    }
    setPendingReceiptCount(count);
    setPendingDelete(entry);
  }

  async function confirmEntryDelete() {
    const entry = pendingDelete;
    if (!entry) return;
    setConfirming(true);
    try {
      await api.deleteEntry(propertyId, categoryId, entry.id);
      collapseIf(entry.id);
      entryModal.onRecordDeleted(entry.id);
      setPendingDelete(null);
      await refreshSummary();
      notify({ variant: "success", title: "Entry deleted" });
    } catch {
      setPendingDelete(null);
      notify({ variant: "error", title: `Could not delete ${entryNoun}` });
      await refreshSummary();
    } finally {
      setConfirming(false);
    }
  }

  // ---- Entered total ----

  function openSetTotal() {
    setTotalError(null);
    totalModal.openAdd();
  }

  function openEditTotal(row: Transaction) {
    setTotalError(null);
    totalModal.openEdit(row);
  }

  async function handleTotalSubmit(amount: string) {
    setSubmitting(true);
    setTotalError(null);
    const editing = totalModal.editing;
    const previous = editing?.amount ?? null;
    const year = taxYear;
    try {
      await api.setTotal(propertyId, categoryId, year, amount);
      totalModal.close();
      await refreshSummary();
      notify({
        variant: "success",
        title: editing
          ? `${tabLabel} total updated to ${formatMoney(amount)}`
          : `${tabLabel} total set to ${formatMoney(amount)}`,
        action: {
          label: "Undo",
          onClick: () => {
            void (async () => {
              try {
                if (previous !== null) {
                  await api.setTotal(propertyId, categoryId, year, previous);
                } else {
                  await api.removeTotal(propertyId, categoryId, year);
                }
                notify({ variant: "success", title: "Change undone" });
              } catch {
                notify({ variant: "error", title: "Could not undo the change" });
              }
              await refreshSummary();
            })();
          },
        },
      });
    } catch (error) {
      setTotalError(errorToField(error, "Could not save the total."));
      if (!(error instanceof ApiError && error.status === 400)) {
        notify({ variant: "error", title: "Could not save total" });
      }
      await refreshSummary();
    } finally {
      setSubmitting(false);
    }
  }

  const undoableTotalRemove = useUndoableDelete<Transaction>({
    remove: async (row) => {
      await api.removeTotal(propertyId, categoryId, taxYear);
      collapseIf(row.id);
      totalModal.onRecordDeleted(row.id);
    },
    restore: (row) =>
      api.setTotal(propertyId, categoryId, taxYear, row.amount),
    refresh: () => reload(),
    deletedTitle: () => `${tabLabel} total removed`,
    restoredTitle: `${tabLabel} total restored`,
    restoreFailedTitle: `Could not restore the ${tabLabel.toLowerCase()} total`,
    deleteFailedTitle: `Could not remove ${tabLabel.toLowerCase()} total`,
  });

  async function requestRemoveTotal(row: Transaction) {
    const count = await receiptCount(row.id);
    if (row.imported !== true && count === 0) {
      await undoableTotalRemove(row);
      return;
    }
    setPendingReceiptCount(count);
    setPendingRemoveTotal(row);
  }

  async function confirmRemoveTotal() {
    const row = pendingRemoveTotal;
    if (!row) return;
    setConfirming(true);
    try {
      await api.removeTotal(propertyId, categoryId, taxYear);
      collapseIf(row.id);
      setPendingRemoveTotal(null);
      await refreshSummary();
      notify({ variant: "success", title: `${tabLabel} total removed` });
    } catch {
      setPendingRemoveTotal(null);
      notify({
        variant: "error",
        title: `Could not remove ${tabLabel.toLowerCase()} total`,
      });
      await refreshSummary();
    } finally {
      setConfirming(false);
    }
  }

  // ---- Sync ----

  async function confirmSync() {
    if (!summary || summary.entered_total === null) return;
    const previous = summary.entered_total;
    const target = summary.itemized_sum;
    const year = summary.tax_year;
    setConfirming(true);
    try {
      await api.setTotal(propertyId, categoryId, year, target);
      setSyncOpen(false);
      await refreshSummary();
      notify({
        variant: "success",
        title: `${tabLabel} total updated to ${formatMoney(target)}`,
        action: {
          label: "Undo",
          onClick: () => {
            void (async () => {
              try {
                await api.setTotal(propertyId, categoryId, year, previous);
                notify({
                  variant: "success",
                  title: `${tabLabel} total restored to ${formatMoney(previous)}`,
                });
              } catch {
                notify({ variant: "error", title: "Could not undo the update" });
              }
              await refreshSummary();
            })();
          },
        },
      });
    } catch {
      setSyncOpen(false);
      notify({
        variant: "error",
        title: `Could not update ${tabLabel.toLowerCase()} total`,
      });
      await refreshSummary();
    } finally {
      setConfirming(false);
    }
  }

  const receiptsFor = (row: Transaction) => (
    <ReceiptList
      api={receiptsApi}
      propertyId={propertyId}
      transactionId={row.id}
      receipts={receipts}
      onChanged={() => void refreshReceipts(row.id)}
    />
  );

  const showSync =
    summary !== null &&
    summary.entered_total_rows.length === 1 &&
    syncVisible(
      summary.entered_total,
      summary.itemized_sum,
      summary.itemized_count,
    );
  const countNote = pendingReceiptCount
    ? ` Its ${pendingReceiptCount === 1 ? "receipt" : `${pendingReceiptCount} receipts`} will also be deleted.`
    : "";

  return (
    <>
      <PropertySection
        propertyId={propertyId}
        title={tabLabel}
        description={definition.description}
      />

      <div
        ref={toolbarRef}
        tabIndex={-1}
        className="mt-6 flex flex-wrap items-center justify-between gap-3 focus:outline-none"
      >
        <div className="flex flex-wrap items-center gap-2">
          <label
            htmlFor="itemized-tax-year"
            className="text-sm font-medium text-fg-muted"
          >
            Tax year
          </label>
          <Select
            id="itemized-tax-year"
            value={String(taxYear)}
            onChange={(event) => changeYear(Number(event.target.value))}
          >
            {years.map((year) => (
              <option key={year} value={year}>
                {year}
              </option>
            ))}
          </Select>
        </div>
        <Button type="button" variant="primary" onClick={openAddEntry}>
          Add {entryNoun}
        </Button>
      </div>

      <RecordModal
        open={entryModal.open}
        onOpenChange={(next) => {
          if (!next) entryModal.requestClose();
        }}
        discard={entryModal.discard}
        title={entryModal.editing ? `Edit ${entryNoun}` : `Add ${entryNoun}`}
        description={`Itemized entries for ${taxYear}. Adding an entry never changes your entered total.`}
        dismissible={!submitting}
        onCloseAutoFocus={entryModal.handleCloseAutoFocus}
      >
        <ItemizedEntryForm
          key={entryModal.editing?.id ?? "new"}
          taxYear={taxYear}
          entryNoun={entryNoun}
          initial={entryModal.editing ?? undefined}
          serverError={formError}
          submitting={submitting}
          onSubmit={(input) => void handleEntrySubmit(input)}
          onCancel={entryModal.requestClose}
          onDirtyChange={entryModal.setDirty}
        />
      </RecordModal>

      <RecordModal
        open={totalModal.open}
        onOpenChange={(next) => {
          if (!next) totalModal.requestClose();
        }}
        discard={totalModal.discard}
        title={totalModal.editing ? "Edit total" : "Set total"}
        description={`The ${tabLabel.toLowerCase()} total for ${taxYear} (Schedule E line ${line}).`}
        dismissible={!submitting}
        onCloseAutoFocus={totalModal.handleCloseAutoFocus}
      >
        <TotalForm
          key={totalModal.editing?.id ?? "new"}
          label={tabLabel}
          taxYear={taxYear}
          initialAmount={totalModal.editing?.amount}
          serverError={totalError}
          submitting={submitting}
          onSubmit={(amount) => void handleTotalSubmit(amount)}
          onCancel={totalModal.requestClose}
          onDirtyChange={totalModal.setDirty}
        />
      </RecordModal>

      {view.showSkeleton ? (
        <div className="mt-4">
          <LoadingRegion label={`Loading ${tabLabel.toLowerCase()}`}>
            <TableSkeleton columns={5} />
          </LoadingRegion>
        </div>
      ) : null}

      {view.showError ? (
        <div className={view.errorIsStale ? "mt-4 mb-4" : "mt-4"}>
          <StateBlock
            kind="error"
            compact={view.errorIsStale}
            title={`Could not load ${tabLabel.toLowerCase()}`}
            description={loadError ?? undefined}
            onRetry={() => void refreshSummary()}
          />
        </div>
      ) : null}

      {view.refreshing ? <RefreshingIndicator className="mt-4 mb-4" /> : null}

      {view.showContent && summary ? (
        <div className="mt-4 space-y-4">
          <ItemizedSummaryPanel summary={summary} line={line} />

          <EnteredTotalCard
            propertyId={propertyId}
            taxYear={taxYear}
            label={tabLabel}
            line={line}
            rows={totalRows}
            documentsExpanded={
              totalRows.length === 1 && expandedId === totalRows[0].id
            }
            onSet={openSetTotal}
            onEdit={openEditTotal}
            onRemove={(row) => void requestRemoveTotal(row)}
            onToggleDocuments={toggleDocuments}
            renderReceipts={receiptsFor}
          />

          {showSync ? (
            <div>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setSyncOpen(true)}
              >
                {syncLabel(summary.itemized_sum)}
              </Button>
            </div>
          ) : null}

          {definition.capitalImprovementNote ? (
            <Card className="p-card">
              <p className="text-fg-muted">
                Capital improvements are not repairs. Record them as{" "}
                <Link
                  to={propertyPath(propertyId, "assets")}
                  className="text-accent underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  depreciable assets
                </Link>{" "}
                instead.
              </p>
            </Card>
          ) : null}

          <section aria-labelledby="itemized-entries-heading">
            <h2
              id="itemized-entries-heading"
              className="text-sm font-medium text-fg-subtle"
            >
              Itemized entries
            </h2>
            {entries.length === 0 && definition.categoryId === "repairs" ? (
              <div className="mt-4">
                <EmptyGuide
                  title={EMPTY_COPY.repairs.title}
                  description={EMPTY_COPY.repairs.description}
                  primary={{
                    label: EMPTY_COPY.repairs.primaryLabel,
                    onClick: openAddEntry,
                  }}
                />
              </div>
            ) : (
            <ItemizedEntryList
              entries={entries}
              entryNoun={entryNoun}
              expandedId={expandedId}
              onEdit={openEditEntry}
              onDelete={(entry) => void requestEntryDelete(entry)}
              onToggleDocuments={toggleDocuments}
              renderReceipts={receiptsFor}
            />
            )}
          </section>
        </div>
      ) : null}

      {summary ? (
        <SyncTotalDialog
          open={syncOpen && summary.entered_total !== null}
          onOpenChange={setSyncOpen}
          onConfirm={confirmSync}
          pending={confirming}
          label={tabLabel}
          line={line}
          taxYear={summary.tax_year}
          enteredTotal={summary.entered_total ?? "0.00"}
          itemizedSum={summary.itemized_sum}
          itemizedCount={summary.itemized_count}
        />
      ) : null}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={`Delete ${entryNoun}`}
        description={
          pendingDelete
            ? `Delete the ${formatMoney(pendingDelete.amount)} ${entryNoun} from ${pendingDelete.date}?${countNote} This cannot be undone.`
            : ""
        }
        confirmLabel="Delete"
        onConfirm={confirmEntryDelete}
        pending={confirming}
      />

      <ConfirmDialog
        open={pendingRemoveTotal !== null}
        onOpenChange={(open) => {
          if (!open) setPendingRemoveTotal(null);
        }}
        title={`Remove ${tabLabel.toLowerCase()} total`}
        description={
          pendingRemoveTotal
            ? `Remove the ${formatMoney(pendingRemoveTotal.amount)} ${tabLabel.toLowerCase()} total for ${taxYear}?${pendingRemoveTotal.imported ? " It came from a Schedule E import." : ""}${countNote} Line ${line} will then follow your itemized entries. This cannot be undone.`
            : ""
        }
        confirmLabel="Remove total"
        onConfirm={confirmRemoveTotal}
        pending={confirming}
      />
    </>
  );
}
