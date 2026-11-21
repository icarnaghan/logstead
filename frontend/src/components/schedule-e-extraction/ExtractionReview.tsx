import { useMemo } from "react";
import { ScheduleEImportForm } from "../schedule-e-import/ScheduleEImportForm";
import type { EntryVerifyHints } from "../schedule-e-import/PropertyEntryCard";
import {
  importScheduleE,
  type ImportOutcome,
  type ImportSubmission,
} from "../../api/scheduleEImport";
import { listProperties, type Property } from "../../api/properties";
import type { ReviewDraft } from "../../api/scheduleEExtraction";
import { reviewDraftToSeed } from "./reviewDraftSeed";

export interface ExtractionReviewProps {
  /** The pre-filled draft produced by a `complete`/`draft` extraction job. */
  reviewDraft: ReviewDraft;
  /**
   * Test seam forwarded to {@link ScheduleEImportForm}. Defaults to the real
   * layer-1 `importScheduleE` so the confirm hand-off uses the unchanged
   * write path (Req 9.2); tests inject a fake to assert the submitted
   * {@link ImportSubmission}.
   */
  submit?: (submission: ImportSubmission) => Promise<ImportOutcome>;
  /** Test seam forwarded to {@link ScheduleEImportForm} for the property list. */
  loadProperties?: (signal?: AbortSignal) => Promise<Property[]>;
}

/**
 * Extraction review screen (tasks 12.2–12.4).
 *
 * On a `complete`/`draft` extraction job, this renders the **existing** layer-1
 * {@link ScheduleEImportForm} seeded from the {@link ReviewDraft}: one property
 * card per extracted column, with pre-filled, editable line amounts and the
 * fuzzy-matched property suggestion *shown but never auto-applied* (Req 7.2,
 * 8.1, 8.2). Low-confidence / unreadable values carry an accessible "please
 * verify" badge, and the tax year carries one when it was not confidently
 * detected (Req 8.3, 6.2). Line 18 is never rendered — that is inherited
 * directly from the layer-1 form (Req 8.4).
 *
 * Confirm hands the edited draft straight to the unchanged `importScheduleE`
 * (`POST /imports/schedule-e`): layer-1 validation / not-owned errors route
 * back onto the form via its existing structured-field routing, and nothing is
 * persisted on failure (Req 9.2, 9.3, 9.4, 11.3). Extraction writes nothing on
 * its own; only this confirm persists.
 */
export function ExtractionReview({
  reviewDraft,
  submit = importScheduleE,
  loadProperties = listProperties,
}: ExtractionReviewProps) {
  // Map the draft to the layer-1 seed once per draft identity so the form's
  // one-shot lazy initializers see stable seed entries (and stable ids).
  const seed = useMemo(() => reviewDraftToSeed(reviewDraft), [reviewDraft]);

  const verifyByEntryId = useMemo(() => {
    const map: Record<string, EntryVerifyHints> = {};
    for (const meta of seed.verifyMeta) {
      map[meta.entryId] = {
        lines: meta.verifyLines,
        suggestedPropertyName: meta.suggestedPropertyName,
        mappingConfidence: meta.mappingConfidence,
      };
    }
    return map;
  }, [seed]);

  const columnCount = reviewDraft.columns.length;

  return (
    <section aria-labelledby="extraction-review-heading" className="space-y-4">
      <div
        className="rounded-md border border-success-subtle bg-success-subtle px-4 py-3"
        data-testid="extraction-review"
        data-column-count={columnCount}
      >
        <h2
          id="extraction-review-heading"
          className="text-base font-semibold text-success"
        >
          Review your extracted Schedule E
        </h2>
        <p className="mt-1 text-sm text-fg-muted">
          We read {columnCount}{" "}
          {columnCount === 1 ? "property" : "properties"} and pre-filled the
          form below. Check anything marked{" "}
          <span className="font-medium">Verify</span>, confirm each property
          mapping, and submit to import. Nothing is saved until you submit.
        </p>
      </div>

      {seed.taxYearNeedsVerification ? (
        <p
          role="status"
          className="rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
          data-testid="tax-year-verify"
        >
          We couldn't confidently detect the tax year — please set it before
          importing.
        </p>
      ) : null}

      <ScheduleEImportForm
        submit={submit}
        loadProperties={loadProperties}
        initialTaxYear={seed.initialTaxYear}
        initialEntries={seed.initialEntries}
        verifyByEntryId={verifyByEntryId}
      />
    </section>
  );
}

export default ExtractionReview;
