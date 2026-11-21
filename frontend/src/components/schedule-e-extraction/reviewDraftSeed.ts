/**
 * Map an extraction {@link ReviewDraft} into the seed shape the existing
 * layer-1 {@link ScheduleEImportForm} accepts (task 12.2).
 *
 * The governing principle is **extraction proposes, the human confirms, layer 1
 * persists**: this mapper only pre-fills the editable form. It produces one
 * {@link EntryState} per {@link ExtractedColumn} with:
 *
 * - `amounts` keyed by `schedule_e_line` from the column's extracted lines
 *   (two-decimal money strings, "0.00" when unreadable). Line 18 never appears
 *   because the backend never emits it (Req 4.5, 8.4).
 * - `propertyId` pre-selected to `suggested_property_id` when present, so the
 *   fuzzy-match suggestion is *shown* in the existing-property select — but it
 *   is **never auto-applied as a confirmed mapping**; the user must still submit
 *   the form, and the suggestion is only a default the user can change (Req 7.2).
 * - `mapping` is always `"existing"` so the suggestion lands in the existing
 *   select; the user can switch to inline-create per column as usual.
 * - `otherDescription` seeded from the Line 19 extracted line's presence (the
 *   backend carries no description text, so this stays blank and the form's
 *   default description applies on submit).
 *
 * It also derives, per entry, the verify metadata the review screen surfaces as
 * accessible "please verify" badges (task 12.3): which line numbers were flagged
 * `needs_verification`, and the suggested mapping name + confidence to display.
 * This metadata is kept **separate** from `EntryState` so the layer-1 form's
 * manual-entry mount is entirely unaffected — it is passed to the form via an
 * additive, defaulted prop.
 */
import type { EntryState } from "../schedule-e-import/PropertyEntryCard";
import type { ExtractedColumn, ReviewDraft } from "../../api/scheduleEExtraction";

/** Line 19 ("Other"), the only line carrying a free-text description. */
const OTHER_LINE = 19;

/**
 * Per-entry verify / suggestion metadata derived from one {@link ExtractedColumn}.
 * Keyed to the seeded entry by its stable `id` so the review screen can surface
 * it beside the right card without threading it through the layer-1 state shape.
 */
export interface EntryVerifyMeta {
  /** The seeded {@link EntryState.id} this metadata belongs to. */
  entryId: string;
  /** Line numbers whose extracted amount is flagged `needs_verification`. */
  verifyLines: number[];
  /** Suggested property display name, when the fuzzy match produced one. */
  suggestedPropertyName: string | null;
  /** Suggested-mapping confidence (0-1), when a suggestion exists. */
  mappingConfidence: number | null;
  /** The extracted physical-address text, when read. */
  addressText: string | null;
  /** True when the address itself was flagged low-confidence. */
  addressNeedsVerification: boolean;
}

/** The seed the {@link ScheduleEImportForm} consumes, plus verify metadata. */
export interface ReviewDraftSeed {
  /** Seeds {@link ScheduleEImportForm}'s `initialTaxYear` (null → form default). */
  initialTaxYear: number | null;
  /** Seeds {@link ScheduleEImportForm}'s `initialEntries` (one per column). */
  initialEntries: EntryState[];
  /** Per-entry verify metadata, aligned to `initialEntries` by `id`. */
  verifyMeta: EntryVerifyMeta[];
  /** True when the detected tax year itself needs verification (Req 6.2). */
  taxYearNeedsVerification: boolean;
}

let seedSeq = 0;
/** A stable, collision-free entry id for a seeded column. */
function nextEntryId(): string {
  seedSeq += 1;
  return `seed-${seedSeq}`;
}

/** Build one seeded {@link EntryState} + its verify metadata from a column. */
function columnToEntry(column: ExtractedColumn): {
  entry: EntryState;
  meta: EntryVerifyMeta;
} {
  const id = nextEntryId();
  const amounts: Record<number, string> = {};
  const verifyLines: number[] = [];
  let hasOther = false;

  for (const line of column.lines) {
    // Pre-fill every extracted line amount as a two-decimal money string.
    amounts[line.schedule_e_line] = line.amount;
    if (line.needs_verification) verifyLines.push(line.schedule_e_line);
    if (line.schedule_e_line === OTHER_LINE) hasOther = true;
  }

  const entry: EntryState = {
    id,
    // The suggestion lands in the existing-property select; the user confirms.
    mapping: "existing",
    propertyId: column.suggested_property_id ?? "",
    newPropertyName: "",
    // Seed the inline-create address with the extracted text so a user who
    // switches to "create new" keeps the read address as a starting point.
    newPropertyAddress: column.address_text ?? "",
    amounts,
    // The backend carries no Line 19 description text; leave blank so the
    // form's default description applies on submit. `hasOther` only informs
    // whether an Other amount was pre-filled.
    otherDescription: "",
  };

  const meta: EntryVerifyMeta = {
    entryId: id,
    verifyLines,
    suggestedPropertyName: column.suggested_property_name,
    mappingConfidence: column.mapping_confidence,
    addressText: column.address_text,
    // The address is flagged for review when it was unreadable (no text). The
    // backend already flags unreadable line amounts per line; an absent address
    // is the address-box analog.
    addressNeedsVerification: column.address_text == null,
  };

  // `hasOther` is intentionally not surfaced further; referencing it keeps the
  // intent explicit without affecting the seed.
  void hasOther;

  return { entry, meta };
}

/**
 * Map a {@link ReviewDraft} into the {@link ReviewDraftSeed} the review screen
 * feeds to the existing layer-1 form. Pure and deterministic given a draft
 * (modulo the monotonic entry ids, which only need to be stable within a mount).
 */
export function reviewDraftToSeed(draft: ReviewDraft): ReviewDraftSeed {
  const initialEntries: EntryState[] = [];
  const verifyMeta: EntryVerifyMeta[] = [];

  for (const column of draft.columns) {
    const { entry, meta } = columnToEntry(column);
    initialEntries.push(entry);
    verifyMeta.push(meta);
  }

  return {
    initialTaxYear: draft.tax_year,
    initialEntries,
    verifyMeta,
    taxYearNeedsVerification: draft.tax_year_needs_verification,
  };
}
