import { Card } from "../ui";

/**
 * Notice that loan schedules are estimates (Requirement 11.8). Rendered as a
 * labelled note so assistive technology announces it as supplementary
 * information rather than an alert.
 */
export function EstimateNotice() {
  return (
    <Card role="note" className="p-3 text-sm text-fg-muted">
      <p>
        <strong className="font-medium text-fg">This schedule is an estimate.</strong>{" "}
        It is projected forward from your anchor balance and date. Reconcile
        the interest figures with your lender&apos;s Form 1098 before filing.
      </p>
    </Card>
  );
}
