import { FOCUS_RING } from "../ui/focusRing";
import { cn } from "../../lib/cn";

/**
 * The persistent, plain-language non-advice notice (Requirements 8.1, 8.2, 8.3,
 * 8.4). It is always rendered near the top of the page — in both the empty and
 * the populated states — so the user can never read the Expected_Carryforward
 * without the caveat that frames it. The short line states, in plain language,
 * that the figure is a reconciliation aid derived from Schedule E net only,
 * that it does NOT apply the IRC §469 passive-loss limitation (the $25,000
 * special allowance, its income phase-out, or real-estate-professional status —
 * the parts Form 8582 handles), and that it is not tax advice.
 *
 * Beneath the line sits a collapsed-by-default "What is this?" disclosure,
 * mirroring {@link ChartCard}'s native `<details className="group">`/`<summary>`
 * pattern (a real, focus-ringed control; `group-open:` toggles the label). It
 * explains, in plain language, what a suspended passive loss carryforward is,
 * why the app does not compute the §469 limitation, and that the figure is only
 * meant to help the user and their tax professional spot years to review.
 * Nothing here frames the expected figure or any status as a definitive tax
 * figure or a filing instruction.
 */
export function DisclaimerNotice() {
  return (
    <div
      role="note"
      className="mt-4 rounded-md border border-border bg-surface-muted px-4 py-3 text-sm text-fg-muted"
    >
      <p>
        This is a reconciliation aid, not tax advice. The expected carry-in and
        carry-out figures are derived from your Schedule E net alone. They do{" "}
        <strong>not</strong>{" "}
        apply the IRC §469 passive-loss limitation — the $25,000 special
        allowance, its income phase-out, or real-estate-professional status, the
        parts Form 8582 handles. Use it to spot years worth a closer look, not
        as a figure to file.
      </p>

      <details className="group mt-2">
        <summary
          className={cn(
            "cursor-pointer list-none rounded text-sm font-medium text-accent",
            FOCUS_RING,
          )}
        >
          <span className="group-open:hidden">What is this?</span>
          <span className="hidden group-open:inline">Hide explanation</span>
        </summary>
        <div className="mt-2 space-y-2 text-fg-muted">
          <p>
            A suspended passive loss carryforward is the rental losses that get
            parked rather than deducted right away. Because renting is a passive
            activity, a year whose rental expenses exceed its income generally
            cannot deduct the loss that year — the loss is carried forward and
            waits until a later year of rental profit, or a sale, uses it up.
          </p>
          <p>
            This page rolls those losses forward year to year from your Schedule
            E net to show what the balance would be if nothing were missed. It
            deliberately does not compute the §469 limitation, because the app
            does not collect the whole-return income and participation facts
            those rules require (your total income for the phase-out, whether you
            actively participated, or whether you qualify as a real-estate
            professional).
          </p>
          <p>
            Treat the expected carry-in as a prompt for you and your tax
            professional to review the years where it diverges from what you
            reported — not as a determination of what belongs on a return.
          </p>
        </div>
      </details>
    </div>
  );
}

/**
 * The Empty_State guidance (Requirements 6.1, 6.2). Shown when `has_data` is
 * false — the user has no Data_Years and no opening balance — so there is
 * nothing to reconcile yet. It is a calm message, never a zero-row table and
 * never an error. The editable opening-balance control stays visible alongside
 * it (rendered by the caller) so the user can seed a pre-data balance before
 * any Schedule E data exists.
 */
export function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border p-8 text-center">
      <h2 className="text-lg font-medium text-fg">Nothing to reconcile yet</h2>
      <p className="mx-auto mt-2 max-w-prose text-sm text-fg-muted">
        Once you record income, expenses, or depreciation for a tax year — or
        set an opening balance below — your year-by-year reconciliation will
        appear here.
      </p>
    </div>
  );
}
