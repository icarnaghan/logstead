/**
 * Persistent non-advice notice for the Year-end checklist, in the style of the
 * carryforward `DisclaimerNotice`. Shown in every page state.
 */
export function YearEndDisclaimer() {
  return (
    <div
      role="note"
      className="mt-4 rounded-md border border-border bg-surface-muted px-4 py-3 text-sm text-fg-muted"
    >
      <p>
        This checklist is a reminder aid, not tax advice. It checks that your
        records in Logstead are complete and consistent. It does not tell you
        what to report.
      </p>
    </div>
  );
}
