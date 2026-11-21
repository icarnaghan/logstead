import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { DashboardSummary, TrendsSeries } from "../../api/dashboard";
import { listAssets } from "../../api/assets";
import { listLoans } from "../../api/loans";
import { getUserProfile } from "../../lib/auth";
import { checklistKeys, readFlag } from "../../lib/checklistStorage";
import { readSetupState, writeSetupState } from "../../lib/onboardingStorage";
import { useSetupGuide } from "../../lib/setupGuide";
import {
  Button,
  Card,
  CheckIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  TileSkeleton,
  XIcon,
} from "../ui";
import {
  checklistProgressText,
  computeChecklist,
  hasDepreciationData,
  hasTransactionData,
  nextStep,
  stepReason,
  type StepId,
} from "./checklist";

/** At most this many properties are probed for loans and assets (design D14). */
const MAX_PROBED_PROPERTIES = 5;

export interface ChecklistCardProps {
  summary: DashboardSummary | null;
  trends: TrendsSeries | null;
  /** True while either data source has not loaded for the first time. */
  loading: boolean;
  /** True when either data source failed its first load. */
  error: boolean;
}

const LINK_CLASS =
  "font-medium text-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const LABELS: Record<StepId, string> = {
  property: "Add your first property",
  transactions: "Record a transaction",
  loanOrAsset: "Add a loan or a depreciable asset",
  report: "View a Schedule E report",
};

/**
 * Setup checklist (Requirement 24). Derives step completion from the already
 * loaded summary and trends, falls back to listing loans and assets for the
 * first few properties, and persists dismissal locally per user.
 */
export function ChecklistCard({
  summary,
  trends,
  loading,
  error,
}: ChecklistCardProps) {
  const userId = getUserProfile()?.sub;
  const keys = useMemo(() => checklistKeys(userId), [userId]);
  const [setup, setSetup] = useState(() => readSetupState(userId));
  const { dismissed, collapsed } = setup;
  const [announcement, setAnnouncement] = useState("");
  const [knownDone, setKnownDone] = useState<StepId[] | null>(null);
  // "Show setup guide" clears the stored state; re-read it when the signal changes.
  const resetSignal = useSetupGuide()?.resetSignal ?? 0;
  const [seenReset, setSeenReset] = useState(resetSignal);
  if (seenReset !== resetSignal) {
    setSeenReset(resetSignal);
    setSetup(readSetupState(userId));
  }
  const [visitedReport] = useState(() => readFlag(keys.visited));
  const [probed, setProbed] = useState(false);

  const hasProperty = summary?.has_properties ?? false;
  const hasTransactions = trends ? hasTransactionData(trends) : false;
  const hasDepreciation = trends ? hasDepreciationData(trends) : false;

  const latest =
    trends && trends.years.length > 0
      ? trends.years[trends.years.length - 1]
      : null;
  const propertyIds = useMemo(
    () =>
      (latest?.properties ?? [])
        .slice(0, MAX_PROBED_PROPERTIES)
        .map((p) => p.property_id),
    [latest],
  );
  const idsKey = propertyIds.join(",");

  const needsProbe =
    !loading &&
    !error &&
    !dismissed &&
    hasProperty &&
    !hasDepreciation &&
    propertyIds.length > 0;

  useEffect(() => {
    if (!needsProbe) return;
    let cancelled = false;
    const ids = idsKey.split(",");
    Promise.all(
      ids.map((id) => Promise.all([listLoans(id), listAssets(id)])),
    )
      .then((results) => {
        if (cancelled) return;
        setProbed(results.some(([loans, assets]) => loans.length > 0 || assets.length > 0));
      })
      .catch(() => {
        // Failure is treated as "not done" without surfacing an error.
        if (!cancelled) setProbed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [needsProbe, idsKey]);

  const view = computeChecklist(
    {
      hasProperty,
      hasTransactions,
      hasLoanOrAsset: hasDepreciation || probed,
      visitedReport,
    },
    dismissed,
  );

  // Announce a step that became complete after the first loaded render.
  if (!loading && !error) {
    const doneIds = view.steps.filter((x) => x.done).map((x) => x.id);
    if (knownDone === null) {
      setKnownDone(doneIds);
    } else {
      const added = doneIds.filter((id) => !knownDone.includes(id));
      if (added.length > 0 || doneIds.length !== knownDone.length) {
        setKnownDone(doneIds);
        if (added.length > 0) {
          setAnnouncement(
            `${LABELS[added[0]]} done. ${checklistProgressText(view)}.`,
          );
        }
      }
    }
  }

  if (error) return null;
  if (loading) return <TileSkeleton className="sm:col-span-2 lg:col-span-3" />;
  if (dismissed) return null;
  const allDone = view.completed === view.total;
  const next = nextStep(view);

  const firstId = propertyIds[0] ?? latest?.properties[0]?.property_id;
  const base = firstId ? `/properties/${firstId}` : null;
  const targets: Record<StepId, string> = {
    property: "/properties",
    transactions: base ? `${base}/transactions` : "/properties",
    loanOrAsset: base ? `${base}/assets` : "/properties",
    report: "/reports",
  };

  const dismiss = () => {
    writeSetupState(userId, { dismissed: true });
    setSetup((prev) => ({ ...prev, dismissed: true }));
  };
  const toggleCollapsed = () => {
    writeSetupState(userId, { collapsed: !collapsed });
    setSetup((prev) => ({ ...prev, collapsed: !prev.collapsed }));
  };

  return (
    <Card
      as="section"
      aria-labelledby="checklist-heading"
      className="p-4 sm:col-span-2 lg:col-span-3"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2
            id="checklist-heading"
            tabIndex={-1}
            className="text-base font-semibold text-fg"
          >
            Get set up
          </h2>
          <p className="mt-1 text-sm text-fg-muted">
            {allDone ? "You're set up" : checklistProgressText(view)}
          </p>
        </div>
        {allDone ? (
          <Button variant="secondary" size="sm" onClick={dismiss}>
            Dismiss
          </Button>
        ) : (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={!collapsed}
              aria-controls="checklist-steps"
              onClick={toggleCollapsed}
            >
              {collapsed ? (
                <ChevronDownIcon className="mr-1 h-4 w-4" aria-hidden="true" />
              ) : (
                <ChevronUpIcon className="mr-1 h-4 w-4" aria-hidden="true" />
              )}
              {collapsed ? "Expand" : "Collapse"}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Dismiss setup checklist"
              onClick={dismiss}
            >
              <XIcon className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        )}
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
      <div id="checklist-steps" hidden={collapsed || allDone}>
        <ol className="mt-3 space-y-2">
          {view.steps.map((step) => (
            <li key={step.id} className="text-sm">
              <div className="flex items-center gap-2">
                {step.done ? (
                  <>
                    <CheckIcon
                      className="h-4 w-4 text-success"
                      aria-hidden="true"
                    />
                    <span className="text-fg-muted line-through">
                      {LABELS[step.id]}
                    </span>
                    <span className="sr-only">Completed</span>
                  </>
                ) : (
                  <>
                    <Link to={targets[step.id]} className={LINK_CLASS}>
                      {LABELS[step.id]}
                    </Link>
                    {step.id === next && (
                      <span className="rounded border border-accent px-1.5 text-xs font-medium text-accent">
                        Next
                      </span>
                    )}
                  </>
                )}
              </div>
              {step.id === next && (
                <p className="mt-0.5 pl-6 text-fg-muted">
                  {stepReason(step.id)}
                </p>
              )}
            </li>
          ))}
        </ol>
        {!hasProperty && (
          <p className="mt-3 text-sm text-fg-muted">
            <Link to="/profile?focus=backup" className={LINK_CLASS}>
              Explore with sample data
            </Link>
            . Sample data replaces all current data.
          </p>
        )}
      </div>
    </Card>
  );
}
