/**
 * Schedule E Import page shell (Requirements 1.1, 1.2).
 *
 * This page is the "Schedule E" tab of the Imports section: it is rendered
 * inside {@link ./ImportsLayout}, which owns the page heading and tab bar, so
 * the page itself renders no `<h1>`.
 *
 * The landing surface for importing a prior year's Schedule E for one or more
 * properties in a single pass. "Importing a Schedule E" synthesizes the backing
 * transactions that reproduce the line totals the user enters, so this page
 * hosts a guided, multi-property form: the user picks one Tax_Year, then adds
 * one or more property entries with their own Schedule E line amounts.
 *
 * It renders the intro copy, and the depreciation-not-imported
 * notice (Req 5.2), and mounts the guided multi-property
 * {@link ../components/schedule-e-import/ScheduleEImportForm} in the form slot:
 * the user picks one Tax_Year, then adds one or more property entries with their
 * own Schedule E line amounts.
 *
 * Named and routed distinctly from the existing {@link ./ImportReviewPage} (the
 * PDF expense-import feature, which lives under the per-property
 * `/properties/:propertyId/import` route) so the two import experiences never
 * collide: this page mounts at `/imports/schedule-e`.
 */
import { ScheduleEImportForm } from "../components/schedule-e-import/ScheduleEImportForm";

export default function ScheduleEImportPage() {
  return (
    <div>
      <p className="text-fg-muted">
        Backfill a prior year's Schedule E for one or more properties in a single
        pass. Pick a tax year, then add a property entry for each column of your
        return and enter its line amounts. Logstead creates one summary
        transaction per non-zero line so your historical reports populate, each
        marked as imported so it stays distinct from the transactions you track
        going forward.
      </p>

      <p
        role="note"
        className="mt-4 rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
      >
        Depreciation (Line 18) is never imported. An imported year shows $0
        depreciation for a property until you add a depreciation schedule for
        that property and year.
      </p>

      {/* The guided multi-property form mounts here. */}
      <div className="mt-6" data-testid="schedule-e-import-form-slot">
        <ScheduleEImportForm />
      </div>
    </div>
  );
}
