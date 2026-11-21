/**
 * Persistent non-advice notice for the Accountant package page, in the style
 * of the carryforward `DisclaimerNotice`. Shown in every page state.
 */
export function PackageDisclaimer() {
  return (
    <div
      role="note"
      className="mt-4 rounded-md border border-border bg-surface-muted px-4 py-3 text-sm text-fg-muted"
    >
      <p>
        This package is an organizing aid built from your own records, not tax
        advice. It does not tell you what to report. Your accountant decides how
        the figures are used.
      </p>
    </div>
  );
}
