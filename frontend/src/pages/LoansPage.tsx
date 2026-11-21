import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { PageContainer } from "../components/PageContainer";
import { PropertySection } from "../components/PropertySection";
import { AnchorYearNotice } from "../components/loans/AnchorYearNotice";
import { PastYearOverrideForm } from "../components/loans/PastYearOverrideForm";
import { EstimateNotice } from "../components/loans/EstimateNotice";
import { InterestOverrideControl } from "../components/loans/InterestOverrideControl";
import { LoanForm } from "../components/loans/LoanForm";
import { LoanList } from "../components/loans/LoanList";
import { SupersededInterestNotice } from "../components/loans/SupersededInterestNotice";
import { YearlyRollupTable } from "../components/loans/YearlyRollupTable";
import { useLine12Impact } from "../components/loans/useLine12Impact";
import { useLoanSchedule } from "../components/loans/useLoanSchedule";
import { useLoans } from "../components/loans/useLoans";
import {
  Button,
  ConfirmDialog,
  LoadingRegion,
  RecordModal,
  RefreshingIndicator,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
  useRecordModal,
  useToast,
  useUndoableDelete,
} from "../components/ui";
import * as loansApiDefault from "../api/loans";
import type { Loan, LoanInput } from "../api/loans";
import { useNewParam } from "../lib/useNewParam";
import { useFocusParam } from "../lib/useFocusParam";
import { isLoanSafeDelete, loanToInput } from "../lib/undoMappers";

/**
 * Subset of the loans API this page depends on. Injectable so tests can supply
 * a mocked implementation with no network access.
 */
export type LoansApi = Pick<
  typeof loansApiDefault,
  | "listLoans"
  | "createLoan"
  | "updateLoan"
  | "deleteLoan"
  | "getLoanSchedule"
  | "setInterestOverride"
  | "clearInterestOverride"
  | "getLine12Impact"
>;

interface LoansPageProps {
  /** Injectable API layer; defaults to the real module. */
  api?: LoansApi;
}

/**
 * Per-property Loans page (Requirement 9). Lists a property's mortgage Loans,
 * provides an add/edit form, supports deletion (with Undo when safe, otherwise confirmation), and shows
 * the yearly rollup (with per-year interest overrides) for the selected Loan.
 *
 * Interest overrides are saved by `InterestOverrideControl` itself (it calls
 * the API); the page only refreshes the schedule from its `onChange`.
 */
export default function LoansPage({ api }: LoansPageProps = {}) {
  const { propertyId = "" } = useParams();
  const loansApi: LoansApi = api ?? loansApiDefault;
  const { notify } = useToast();

  const loansState = useLoans(propertyId, loansApi);
  const {
    loans,
    loading,
    loadError,
    submitting,
    deleting,
    errors,
    deleteError,
  } = loansState;
  const impact = useLine12Impact(propertyId, loansApi);
  const view = useFirstLoad({
    loading,
    error: loadError,
    resetKey: propertyId,
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Loan | null>(null);

  const scheduleState = useLoanSchedule(propertyId, selectedId, loansApi);
  const selectedLoan = loans.find((l) => l.id === selectedId) ?? null;

  // Focus targets: headings are programmatically focusable (tabIndex -1).
  const scheduleHeadingRef = useRef<HTMLHeadingElement>(null);
  const listHeadingRef = useRef<HTMLHeadingElement>(null);
  const [focusTarget, setFocusTarget] = useState<"schedule" | "list" | null>(
    null,
  );
  const modal = useRecordModal(loans, { fallbackFocusRef: listHeadingRef });

  // Read notify through a ref so the toast effect does not re-run on its identity.
  const notifyRef = useRef(notify);
  useEffect(() => {
    notifyRef.current = notify;
  }, [notify]);

  // Non-field save failure: errors.form is the only error key (Req 5.3).
  useEffect(() => {
    const keys = Object.keys(errors);
    if (keys.length === 1 && errors.form) {
      notifyRef.current({ variant: "error", title: "Could not save the loan" });
    }
  }, [errors]);

  useEffect(() => {
    if (focusTarget === null) return;
    const el =
      focusTarget === "schedule"
        ? scheduleHeadingRef.current
        : listHeadingRef.current;
    if (el) {
      el.focus();
      setFocusTarget(null);
    }
  }, [focusTarget, selectedLoan]);

  async function handleSubmit(input: LoanInput) {
    const editingLoan = modal.editing;
    const wasEditing = editingLoan !== null;
    const saved = editingLoan
      ? await loansState.updateLoan(editingLoan.id, input)
      : await loansState.createLoan(input);
    if (!saved) return; // errors are shown in the form; entered values kept
    modal.close();
    void impact.refresh();
    if (saved.id === selectedId) void scheduleState.refresh();
    notify({
      variant: "success",
      title: wasEditing ? "Loan updated" : "Loan added",
    });
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const loan = pendingDelete;
    const ok = await loansState.deleteLoan(loan.id);
    if (!ok) {
      notify({ variant: "error", title: "Could not delete the loan" });
      return; // keep the dialog open and the Loan in the list
    }
    if (selectedId === loan.id) setSelectedId(null);
    modal.onRecordDeleted(loan.id);
    setPendingDelete(null);
    void impact.refresh();
    setFocusTarget("list");
    notify({ variant: "success", title: "Loan deleted" });
  }

  // Safe_Delete (no interest overrides): delete immediately with an Undo toast
  // that re-creates the loan from the retained record (Requirements 13.1-13.4).
  const undoableDelete = useUndoableDelete<Loan>({
    remove: async (loan) => {
      await loansApi.deleteLoan(propertyId, loan.id);
      // The restored loan gets a new id, so clear anything keyed to the old one.
      setSelectedId((cur) => (cur === loan.id ? null : cur));
      modal.onRecordDeleted(loan.id);
      setFocusTarget("list");
    },
    restore: (loan) => loansApi.createLoan(propertyId, loanToInput(loan)),
    refresh: async () => {
      await loansState.reload();
      void impact.refresh();
    },
    deletedTitle: () => "Loan deleted",
    restoredTitle: "Loan restored",
    restoreFailedTitle: "Could not restore the loan",
    deleteFailedTitle: "Could not delete the loan",
  });

  function handleDelete(loan: Loan) {
    loansState.clearErrors();
    if (isLoanSafeDelete(loan)) {
      void undoableDelete(loan);
    } else {
      setPendingDelete(loan);
    }
  }

  const { schedule } = scheduleState;

  function openAdd() {
    loansState.clearErrors();
    modal.openAdd();
  }
  useNewParam(openAdd, view.showContent);
  useFocusParam(loans, view.showContent);


  // After an override is set or cleared the schedule is reloaded so an
  // override-only row appears or disappears, and Line 12 impact is rechecked.
  function refreshAfterOverride() {
    void scheduleState.refresh();
    void impact.refresh();
  }

  return (
    <PageContainer>
      <PropertySection
        propertyId={propertyId}
        title="Loans"
        description="Track mortgage loans for this property and review each loan's amortization schedule and yearly mortgage interest."
      />
      <div className="mt-8 space-y-8">
        <EstimateNotice />
        {!impact.failed && impact.impact.length > 0 && (
          <SupersededInterestNotice years={impact.impact} />
        )}

        <section aria-labelledby="loan-list-heading">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              id="loan-list-heading"
              ref={listHeadingRef}
              tabIndex={-1}
              className="text-lg font-semibold text-fg"
            >
              All loans
            </h2>
            {view.showContent && loans.length > 0 && (
              <Button type="button" onClick={openAdd}>
                Add loan
              </Button>
            )}
          </div>
          {deleteError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {deleteError}
            </p>
          )}
          <div className="mt-3">
            {view.showSkeleton ? (
              <LoadingRegion label="Loading loans">
                <TableSkeleton columns={4} />
              </LoadingRegion>
            ) : null}
            {view.showError ? (
              <div className={view.errorIsStale ? "mb-4" : undefined}>
                <StateBlock
                  kind="error"
                  compact={view.errorIsStale}
                  title="Could not load your loans"
                  description={loadError ?? undefined}
                  onRetry={() => void loansState.reload()}
                />
              </div>
            ) : null}
            {view.refreshing ? <RefreshingIndicator className="mb-4" /> : null}
            {view.showContent ? (
              <LoanList
                loans={loans}
                selectedLoanId={selectedId}
                onSelect={(loan) => {
                  setSelectedId(loan.id);
                  setFocusTarget("schedule");
                }}
                onEdit={(loan) => {
                  loansState.clearErrors();
                  modal.openEdit(loan);
                }}
                onDelete={handleDelete}
                onCreate={openAdd}
              />
            ) : null}
          </div>
        </section>

        {selectedLoan && (
          <section
            aria-labelledby="loan-schedule-heading"
            className="rounded-lg border border-border bg-surface p-4 shadow-card"
          >
            <h2
              id="loan-schedule-heading"
              ref={scheduleHeadingRef}
              tabIndex={-1}
              className="text-lg font-semibold text-fg"
            >
              Yearly schedule: {selectedLoan.description}
            </h2>
            {scheduleState.loading && !schedule ? (
              <StateBlock kind="loading" title="Loading schedule…" />
            ) : scheduleState.loadError ? (
              <div className="mt-2">
                <StateBlock
                  kind="error"
                  compact
                  title={scheduleState.loadError}
                  onRetry={() => scheduleState.refresh()}
                />
              </div>
            ) : schedule ? (
              <div className="mt-2 space-y-4">
                <AnchorYearNotice anchorDate={selectedLoan.anchor_date} />
                <YearlyRollupTable
                  anchorDate={selectedLoan.anchor_date}
                  caption={`Yearly amortization schedule for ${selectedLoan.description}`}
                  schedule={schedule}
                  renderOverrideControl={(rollup) => (
                    <InterestOverrideControl
                      propertyId={propertyId}
                      loanId={selectedLoan.id}
                      rollup={rollup}
                      onChange={refreshAfterOverride}
                    />
                  )}
                />
                <PastYearOverrideForm
                  propertyId={propertyId}
                  loanId={selectedLoan.id}
                  anchorYear={Number(selectedLoan.anchor_date.slice(0, 4))}
                  yearsWithPayments={schedule.yearly
                    .filter((y) => y.payments > 0)
                    .map((y) => y.tax_year)}
                  onSaved={refreshAfterOverride}
                />
              </div>
            ) : null}
          </section>
        )}
      </div>

      <RecordModal
        open={modal.open}
        onOpenChange={(next) => {
          if (!next) modal.requestClose();
        }}
        discard={modal.discard}
        title={modal.editing ? "Edit loan" : "Add loan"}
        description="Enter the loan terms. The preview updates as you type."
        dismissible={!submitting}
        onCloseAutoFocus={modal.handleCloseAutoFocus}
      >
        <LoanForm
          key={modal.editing?.id ?? "new"}
          loan={modal.editing ?? undefined}
          serverErrors={errors}
          submitting={submitting}
          onSubmit={(input) => void handleSubmit(input)}
          onCancel={modal.requestClose}
          onDirtyChange={modal.setDirty}
        />
      </RecordModal>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Delete loan"
        description={
          pendingDelete ? (
            <>
              Delete &quot;{pendingDelete.description}&quot;? This permanently
              removes the loan and its amortization schedule.
            </>
          ) : null
        }
        confirmLabel="Delete"
        onConfirm={() => void confirmDelete()}
        pending={deleting}
      />
    </PageContainer>
  );
}
