import { useContext, useEffect, useState } from "react";
import { Button } from "../ui";
import { useDirtyReporter } from "../../lib/dirty";
import { ImportsDirtyContext } from "../../lib/importsDirty";
import {
  importScheduleE,
  ApiError,
  type ImportOutcome,
  type ImportSubmission,
  type PropertyEntryInput,
  type LineAmountInput,
} from "../../api/scheduleEImport";
import { listProperties, type Property } from "../../api/properties";
import {
  PropertyEntryCard,
  type EntryErrors,
  type EntryState,
  type EntryVerifyHints,
} from "./PropertyEntryCard";
import { ALL_LINES, OTHER_LINE } from "./scheduleELines";

interface ScheduleEImportFormProps {
  /** Test seam: submit call. Defaults to the real `importScheduleE`. */
  submit?: (submission: ImportSubmission) => Promise<ImportOutcome>;
  /** Test seam: property loader. Defaults to the real `listProperties`. */
  loadProperties?: (signal?: AbortSignal) => Promise<Property[]>;
  /**
   * Optional seed for the Tax_Year input, used when an extraction `ReviewDraft`
   * pre-fills the form. When provided and non-null it sets the initial value
   * once on mount; otherwise the form keeps its manual-entry default
   * (`currentYear - 1`). The user can edit freely afterward (Req 8.1, 8.2).
   */
  initialTaxYear?: number | null;
  /**
   * Optional seed for the property columns, used when an extraction
   * `ReviewDraft` pre-fills the form (one {@link EntryState} per extracted
   * column). When provided it initializes the entries once on mount; otherwise
   * the form keeps its manual-entry default (a single blank entry). Purely
   * additive — the user can edit, add, and remove columns afterward
   * (Req 8.1, 8.2).
   */
  initialEntries?: EntryState[];
  /**
   * Optional extraction-review verify hints keyed by {@link EntryState.id}
   * (task 12.3). When an extraction `ReviewDraft` seeds the form, this surfaces
   * the per-line "please verify" badges and the suggested-mapping note on the
   * matching card. Defaulted/undefined for the layer-1 manual mount, which
   * therefore renders exactly as before (no verify affordances).
   */
  verifyByEntryId?: Record<string, EntryVerifyHints>;
}

/** Submission-level errors shown at the top (tax_year, entries-collection). */
interface SubmissionErrors {
  taxYear?: string;
  entries?: string;
  /** Any non-field server/transport error. */
  form?: string;
}

let entrySeq = 0;
function newEntry(): EntryState {
  entrySeq += 1;
  return {
    id: `e${entrySeq}`,
    mapping: "existing",
    propertyId: "",
    newPropertyName: "",
    newPropertyAddress: "",
    amounts: {},
    otherDescription: "",
  };
}

/** Parse one amount string: blank → omitted; otherwise trimmed string. */
function normalizedAmount(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  const trimmed = raw.trim();
  return trimmed === "" ? null : trimmed;
}

/** Build the wire `PropertyEntryInput` from one card's editable state. */
function toEntryInput(entry: EntryState): PropertyEntryInput {
  const lines: LineAmountInput[] = [];
  for (const def of ALL_LINES) {
    const amount = normalizedAmount(entry.amounts[def.line]);
    if (amount === null) continue;
    const line: LineAmountInput = { schedule_e_line: def.line, amount };
    if (def.line === OTHER_LINE.line && entry.otherDescription.trim()) {
      line.description = entry.otherDescription.trim();
    }
    lines.push(line);
  }

  if (entry.mapping === "new") {
    return {
      new_property: {
        name: entry.newPropertyName.trim(),
        address_text: entry.newPropertyAddress.trim(),
      },
      lines,
    };
  }
  return { property_id: entry.propertyId, lines };
}

/**
 * Route one structured dotted `field` path + message onto the right place.
 *
 * The backend emits `tax_year`, `entries`, `entries[i]`, `entries[i].lines[n]`,
 * and `entries[i].new_property.<field>`. We split on the first bracket to find
 * the entry index, then interpret the remainder (Req 1.6, 1.7, 2.5, 9.6).
 */
function routeFieldError(
  field: string,
  message: string,
  submission: SubmissionErrors,
  perEntry: EntryErrors[],
) {
  if (field === "tax_year") {
    submission.taxYear = message;
    return;
  }
  if (field === "entries") {
    submission.entries = message;
    return;
  }

  // entries[i]... — split on the first bracket.
  const match = /^entries\[(\d+)\]\.?(.*)$/.exec(field);
  if (!match) {
    submission.form = message;
    return;
  }
  const i = Number(match[1]);
  const rest = match[2];
  const target = perEntry[i];
  if (!target) {
    submission.form = message;
    return;
  }

  if (rest === "") {
    target.entry = message;
    return;
  }

  const lineMatch = /^lines\[(\d+)\]$/.exec(rest);
  if (lineMatch) {
    const line = Number(lineMatch[1]);
    target.lines = { ...(target.lines ?? {}), [line]: message };
    return;
  }

  const newPropMatch = /^new_property\.(\w+)$/.exec(rest);
  if (newPropMatch) {
    const subField = newPropMatch[1];
    const current = target.newProperty ?? {};
    if (subField === "name") current.name = message;
    else if (subField === "address_text") current.address_text = message;
    else target.entry = message;
    target.newProperty = current;
    return;
  }

  // Unknown remainder — surface at the entry level so it is not lost.
  target.entry = message;
}

/**
 * Guided multi-property Schedule E import form (Requirements 1.2, 1.3, 5.2).
 *
 * The user selects the Tax_Year once at the top, then adds one or more
 * {@link PropertyEntryCard}s (starting with one). Submitting builds a single
 * {@link ImportSubmission} and posts it via {@link importScheduleE}. On success
 * the per-entry outcome is summarized; on a structured validation/not-found
 * failure each message is routed to the right entry card / line input via the
 * dotted `field` path. The depreciation-not-imported reminder is shown
 * prominently (the page shows the primary notice; this restates it in the form).
 */
export function ScheduleEImportForm({
  submit = importScheduleE,
  loadProperties = listProperties,
  initialTaxYear,
  initialEntries,
  verifyByEntryId,
}: ScheduleEImportFormProps) {
  const currentYear = new Date().getFullYear();
  // Lazy initializers so any seed from an extraction ReviewDraft is applied
  // exactly once on mount; the user then edits freely (no re-seed on render).
  const [taxYear, setTaxYear] = useState<string>(() =>
    initialTaxYear != null ? String(initialTaxYear) : String(currentYear - 1),
  );
  const [entries, setEntries] = useState<EntryState[]>(() =>
    initialEntries && initialEntries.length > 0 ? initialEntries : [newEntry()],
  );
  // Dirty tracking against a snapshot of { taxYear, entries } taken at mount.
  const { setDirty } = useContext(ImportsDirtyContext);
  const [initialSnapshot] = useState(() => JSON.stringify({ taxYear, entries }));
  useDirtyReporter(
    { snapshot: initialSnapshot },
    { snapshot: JSON.stringify({ taxYear, entries }) },
    setDirty,
  );
  const [properties, setProperties] = useState<Property[]>([]);
  const [loadingProperties, setLoadingProperties] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submissionErrors, setSubmissionErrors] = useState<SubmissionErrors>({});
  const [entryErrors, setEntryErrors] = useState<EntryErrors[]>([]);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingProperties(true);
    loadProperties(controller.signal)
      .then((found) => setProperties(Array.isArray(found) ? found : []))
      .catch(() => setProperties([]))
      .finally(() => setLoadingProperties(false));
    return () => controller.abort();
  }, [loadProperties]);

  function updateEntry(id: string, next: EntryState) {
    setEntries((prev) => prev.map((e) => (e.id === id ? next : e)));
  }

  function addEntry() {
    setEntries((prev) => [...prev, newEntry()]);
  }

  function removeEntry(id: string) {
    setEntries((prev) => (prev.length > 1 ? prev.filter((e) => e.id !== id) : prev));
    setEntryErrors([]);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmissionErrors({});
    setEntryErrors([]);
    setOutcome(null);

    const yearNum = Number(taxYear);
    const submission: ImportSubmission = {
      tax_year: Number.isNaN(yearNum) ? 0 : yearNum,
      entries: entries.map(toEntryInput),
    };

    setSubmitting(true);
    try {
      const result = await submit(submission);
      setOutcome(result);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 404)) {
        const body = err.body as { field?: string; message?: string } | null;
        const message = body?.message ?? "Please correct the highlighted field.";
        const nextSubmission: SubmissionErrors = {};
        const nextEntries: EntryErrors[] = entries.map(() => ({}));
        if (body?.field) {
          routeFieldError(body.field, message, nextSubmission, nextEntries);
        } else {
          nextSubmission.form = message;
        }
        setSubmissionErrors(nextSubmission);
        setEntryErrors(nextEntries);
      } else {
        setSubmissionErrors({
          form:
            err instanceof ApiError
              ? err.message
              : "Something went wrong while importing. Please try again.",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="space-y-6" onSubmit={handleSubmit} noValidate>
      {submissionErrors.form ? (
        <p
          role="alert"
          className="rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          {submissionErrors.form}
        </p>
      ) : null}
      {submissionErrors.entries ? (
        <p
          role="alert"
          className="rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          {submissionErrors.entries}
        </p>
      ) : null}

      {outcome ? (
        <div
          role="status"
          className="rounded-md bg-success-subtle px-3 py-2 text-sm text-success"
        >
          <p className="font-medium">
            Imported Schedule E for tax year {outcome.tax_year}.
          </p>
          <ul className="mt-1 list-inside list-disc">
            {outcome.entries.map((e, i) => (
              <li key={e.property_id || i}>
                Column {i + 1}: {e.created_transaction_ids.length} transaction
                {e.created_transaction_ids.length === 1 ? "" : "s"} created
                {e.deleted_prior_count > 0
                  ? `, ${e.deleted_prior_count} prior imported replaced`
                  : ""}
                {e.created_inline_property ? ", new property created" : ""}.
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <label htmlFor="import-tax-year" className="block text-sm font-medium text-fg-muted">
          Tax year
        </label>
        <input
          id="import-tax-year"
          type="number"
          inputMode="numeric"
          min={1000}
          max={9999}
          value={taxYear}
          onChange={(e) => setTaxYear(e.target.value)}
          aria-invalid={Boolean(submissionErrors.taxYear) || undefined}
          aria-describedby={submissionErrors.taxYear ? "import-tax-year-error" : undefined}
          className={`mt-1 w-40 rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
            submissionErrors.taxYear ? "border-danger" : ""
          }`}
        />
        <p className="mt-1 text-sm text-fg-subtle">
          Every property column below is imported for this one tax year.
        </p>
        {submissionErrors.taxYear ? (
          <p id="import-tax-year-error" role="alert" className="mt-1 text-sm text-danger">
            {submissionErrors.taxYear}
          </p>
        ) : null}
      </div>

      <p
        role="note"
        className="rounded-md bg-warning-subtle px-3 py-2 text-sm text-warning"
      >
        Reminder: depreciation (Line 18) is not imported for any property in this
        submission. Add a depreciation schedule for each property and this tax
        year to populate Line 18.
      </p>

      <div className="space-y-6">
        {entries.map((entry, i) => (
          <PropertyEntryCard
            key={entry.id}
            index={i + 1}
            entry={entry}
            errors={entryErrors[i]}
            properties={properties}
            loadingProperties={loadingProperties}
            onChange={(next) => updateEntry(entry.id, next)}
            onRemove={() => removeEntry(entry.id)}
            canRemove={entries.length > 1}
            verify={verifyByEntryId?.[entry.id]}
          />
        ))}
      </div>

      <div className="flex items-center justify-between gap-2">
        <Button type="button" variant="secondary" onClick={addEntry}>
          Add property column
        </Button>
        <Button type="submit" variant="primary" disabled={submitting}>
          {submitting ? "Importing…" : "Import Schedule E"}
        </Button>
      </div>
    </form>
  );
}
