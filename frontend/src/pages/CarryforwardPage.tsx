import { useMemo } from "react";
import {
  carryforwardApi as sharedApi,
  type CarryforwardApi,
} from "../api/carryforward";
import { PageContainer } from "../components/PageContainer";
import {
  DisclaimerNotice,
  EmptyState,
} from "../components/carryforward/CarryforwardNotices";
import {
  ChainSummaryBlock,
  ToleranceNote,
} from "../components/carryforward/ChainSummaryBlock";
import { OpeningBalanceControl } from "../components/carryforward/OpeningBalanceControl";
import { ReconciliationTable } from "../components/carryforward/ReconciliationTable";
import { useCarryforwardActions } from "../components/carryforward/useCarryforwardActions";
import {
  LoadingRegion,
  PageHeader,
  RefreshingIndicator,
  StateBlock,
  TableSkeleton,
  useFirstLoad,
} from "../components/ui";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { isAsyncLoading, useAsyncResource } from "../lib/useAsyncResource";
import { summarizeChainBreaks } from "../lib/carryforwardChain";
import { formatMoneyWholeDollars } from "../lib/money";

interface CarryforwardPageProps {
  /** Injectable carryforward API for tests; defaults to the shared singleton. */
  api?: CarryforwardApi;
}

/**
 * Passive loss carryforward reconciliation page.
 *
 * Fetches the reconciliation series once on mount (an abort during unmount is
 * ignored; any other failure surfaces the page's `role="alert"` error
 * indication). It renders the four-digit year, the Schedule E net (with the
 * app's loss convention), the Expected_Carryforward, an inline editor for the
 * Reported_Carryforward, and a textual status — one row per Data_Year ascending
 * — with `mismatch` years highlighted distinctly by a textual label, never
 * color alone (Requirements 4.5, 4.6, 5.1-5.6).
 *
 * The inline reported-value editor and the editable opening-balance control
 * (task 7.2) save through the API and then refresh the series in place (no full
 * reload) so expected/reported/status update together; server validation errors
 * are surfaced inline next to the offending control.
 *
 * A persistent, plain-language {@link DisclaimerNotice} sits near the top in
 * every state (Requirements 8.1-8.4), framing the Expected_Carryforward as a
 * reconciliation aid that never applies the §469 limitation and is not tax
 * advice. When the series has no data (`has_data` false) the page shows the
 * calm {@link EmptyState} instead of a zero-row table — never an error — while
 * keeping the opening-balance control visible so the user can seed a pre-data
 * balance (Requirements 6.1, 6.2).
 *
 * The table, editors, notices and pure text helpers live in
 * `components/carryforward/`.
 */
export default function CarryforwardPage({
  api = sharedApi,
}: CarryforwardPageProps) {
  useDocumentTitle("Passive loss carryforward");
  // Refreshes (including post-save reloads) never clear `summary`, so content
  // stays mounted (Requirements 14.2, 14.3). An abort during unmount is
  // ignored; any other failure shows the page's error indication.
  const {
    data: summary,
    error,
    status,
    reload: load,
  } = useAsyncResource((signal) => api.getReconciliation(signal), {
    describeError: () => "Could not load the carryforward reconciliation.",
  });
  const view = useFirstLoad({ loading: isAsyncLoading(status), error });
  const actions = useCarryforwardActions(api, load);

  const chain = useMemo(
    () => (summary ? summarizeChainBreaks(summary.years) : null),
    [summary],
  );

  return (
    <PageContainer>
      <section aria-labelledby="page-heading">
        <PageHeader
          title="Passive loss carryforward"
          description="For each year, this page shows the suspended passive loss balance expected to enter that year from earlier years, and compares it with the Form 8582 line you reported."
        />

        <DisclaimerNotice />

        {view.showSkeleton ? (
          <LoadingRegion label="Loading reconciliation" className="mt-6">
            <TableSkeleton columns={6} />
          </LoadingRegion>
        ) : null}

        {view.showError ? (
          <div className="mt-4">
            <StateBlock
              kind="error"
              compact={view.errorIsStale}
              title="Could not load the carryforward reconciliation"
              onRetry={() => void load()}
            />
          </div>
        ) : null}

        {view.refreshing ? <RefreshingIndicator className="mt-4" /> : null}

        {view.showContent && summary ? (
          <div className="mt-6 space-y-6">
            <OpeningBalanceControl
              openingBalance={summary.opening_balance}
              onSave={actions.handleSaveOpeningBalance}
            />

            {summary.has_data ? (
              <div className="space-y-3">
                <p className="text-sm text-fg-muted">
                  Enter the "Prior years unallowed losses" line from each
                  year's Form 8582. That is the loss balance carried into that
                  year from earlier years.
                </p>
                <ToleranceNote tolerance={summary.status_tolerance} />
                {chain ? (
                  <ChainSummaryBlock
                    summary={chain}
                    tolerance={summary.status_tolerance}
                  />
                ) : null}
                <ReconciliationTable
                  years={summary.years}
                  chain={chain}
                  onSave={actions.handleSaveReported}
                  onClear={actions.handleClearReported}
                  onSetAllowed={actions.handleSetAllowed}
                  onClearAllowed={actions.handleClearAllowed}
                  onSetFullyAllowed={actions.handleSetFullyAllowed}
                />
                <p className="text-sm font-medium text-fg tabular-nums">
                  {summary.next_year !== null
                    ? `Expected to carry into ${summary.next_year}`
                    : "Expected to carry into the next year"}
                  : {formatMoneyWholeDollars(summary.next_year_expected_carry_in)}
                </p>
              </div>
            ) : (
              <EmptyState />
            )}
          </div>
        ) : null}
      </section>
    </PageContainer>
  );
}
