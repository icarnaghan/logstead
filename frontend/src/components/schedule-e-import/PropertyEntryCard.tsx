import { Badge, Card } from "../ui";
import type { Property } from "../../api/properties";
import {
  EXPENSE_LINES,
  INCOME_LINES,
  OTHER_LINE,
  type ScheduleELineDef,
} from "./scheduleELines";

/**
 * Optional, additive extraction-review hints for one entry (task 12.3).
 *
 * Purely informational: when an extraction `ReviewDraft` seeds this card, these
 * surface which pre-filled values the user should double-check and the
 * fuzzy-matched property suggestion. Everything here is defaulted/undefined for
 * the layer-1 manual mount, so that mount renders exactly as before — no verify
 * badge, no suggestion note.
 */
export interface EntryVerifyHints {
  /** Line numbers whose pre-filled amount was flagged `needs_verification`. */
  lines?: number[];
  /** Suggested property display name from the fuzzy match, when present. */
  suggestedPropertyName?: string | null;
  /** Suggested-mapping confidence (0-1), when a suggestion exists. */
  mappingConfidence?: number | null;
}

const inputClass =
  "mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const invalidClass = "border-danger";
const labelClass = "block text-sm font-medium text-fg-muted";

/**
 * The editable state for one Property_Entry (one Schedule E Part I column).
 *
 * `mapping` chooses between an existing owned property (`property_id`) and an
 * inline-created property (`new_property`, carried as separate name/address
 * fields so the backend creates it during the write phase). `amounts` holds the
 * raw money string typed for each line keyed by line number; blank is treated
 * as zero by the backend. `otherDescription` is the free-text for Line 19.
 */
export interface EntryState {
  /** Stable client id so React keys and remove targeting stay correct. */
  id: string;
  mapping: "existing" | "new";
  propertyId: string;
  newPropertyName: string;
  newPropertyAddress: string;
  /** Raw money strings keyed by Schedule E line number. */
  amounts: Record<number, string>;
  otherDescription: string;
}

/**
 * Server/client validation errors for one entry, keyed to the structured dotted
 * field path the backend emits. `entry` is an entry-level message (all-zero
 * entry, not-found/duplicate property); `lines[<line>]` is a per-line amount
 * message; `newProperty.<field>` is an inline-create field message.
 */
export interface EntryErrors {
  /** Entry-level message (`entries[i]`). */
  entry?: string;
  /** Per-line amount messages keyed by line number (`entries[i].lines[n]`). */
  lines?: Record<number, string>;
  /** Inline-create field messages (`entries[i].new_property.<field>`). */
  newProperty?: { name?: string; address_text?: string };
}

interface PropertyEntryCardProps {
  /** 1-based column number shown to the user (Column A/B/C analog). */
  index: number;
  entry: EntryState;
  errors?: EntryErrors;
  /** The user's existing properties for the mapping select. */
  properties: Property[];
  /** True while properties are still loading (disables the select). */
  loadingProperties: boolean;
  onChange: (next: EntryState) => void;
  /** Remove this entry. Omitted/disabled when only one entry remains. */
  onRemove?: () => void;
  /** True when removal is allowed (more than one entry present). */
  canRemove: boolean;
  /**
   * Optional extraction-review hints (task 12.3). Defaulted/undefined for the
   * layer-1 manual mount so that mount is unchanged.
   */
  verify?: EntryVerifyHints;
}

/** Build the per-line money input + error slot. */
function LineInput({
  idPrefix,
  def,
  value,
  error,
  verify,
  onChange,
}: {
  idPrefix: string;
  def: ScheduleELineDef;
  value: string;
  error?: string;
  /**
   * True when this pre-filled value was flagged `needs_verification` by
   * extraction (task 12.3). Renders an informational "verify" badge — distinct
   * from the error slot — so screen-reader users hear which values to review.
   */
  verify?: boolean;
  onChange: (value: string) => void;
}) {
  const inputId = `${idPrefix}-line-${def.line}`;
  const errorId = `${inputId}-error`;
  const verifyId = `${inputId}-verify`;
  // The input describes its error (if any) and its verify hint (if any). A
  // flagged value is informational, never `aria-invalid`.
  const describedBy =
    [error ? errorId : null, verify ? verifyId : null]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={inputId} className={labelClass}>
          Line {def.line}: {def.label}
        </label>
        {verify ? (
          <Badge
            label="please verify"
            className="border-warning-subtle bg-warning-subtle text-warning"
          >
            <span id={verifyId}>Verify</span>
          </Badge>
        ) : null}
      </div>
      <input
        id={inputId}
        type="text"
        inputMode="decimal"
        value={value}
        placeholder="0.00"
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={describedBy}
        className={`${inputClass} ${error ? invalidClass : ""}`}
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * One Property_Entry card (Requirements 1.3, 1.4, 2.1, 2.2, 4.1, 5.2).
 *
 * Renders the per-column property mapping — either a select of the user's
 * existing properties or an inline-create (name + address) that the backend
 * materializes during import — plus a money input for each importable Schedule E
 * line (income 3-4, expense 5-17, and Line 19 "Other" with a description). There
 * is deliberately **no** Line 18 field (depreciation is never imported). Each
 * input owns an error slot wired via `aria-describedby`/`role="alert"`, so a
 * structured server error routes to the exact line/field.
 */
export function PropertyEntryCard({
  index,
  entry,
  errors,
  properties,
  loadingProperties,
  onChange,
  onRemove,
  canRemove,
  verify,
}: PropertyEntryCardProps) {
  const idPrefix = `entry-${entry.id}`;
  const headingId = `${idPrefix}-heading`;
  const mappingName = `${idPrefix}-mapping`;

  function setAmount(line: number, value: string) {
    onChange({ ...entry, amounts: { ...entry.amounts, [line]: value } });
  }

  const entryError = errors?.entry;
  const nameError = errors?.newProperty?.name;
  const addressError = errors?.newProperty?.address_text;

  const verifyLines = new Set(verify?.lines ?? []);
  const suggestedName = verify?.suggestedPropertyName ?? null;
  const mappingConfidence = verify?.mappingConfidence ?? null;

  return (
    <Card as="section" aria-labelledby={headingId} className="p-4">
      <div className="flex items-center justify-between">
        <h2 id={headingId} className="text-base font-semibold text-fg">
          Property column {index}
        </h2>
        {canRemove && onRemove ? (
          <button
            type="button"
            onClick={onRemove}
            className="relative rounded-md border border-border px-2 py-1 text-sm text-fg-muted before:absolute before:-inset-2 before:content-[''] hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Remove column {index}
          </button>
        ) : null}
      </div>

      {entryError ? (
        <p
          role="alert"
          className="mt-3 rounded-md bg-danger-subtle px-3 py-2 text-sm text-danger"
        >
          {entryError}
        </p>
      ) : null}

      {/* Property mapping: existing select vs inline create. */}
      <fieldset className="mt-4">
        <legend className={labelClass}>Property</legend>
        <div className="mt-1 flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg max-md:min-h-11">
            <input
              type="radio"
              name={mappingName}
              value="existing"
              checked={entry.mapping === "existing"}
              onChange={() => onChange({ ...entry, mapping: "existing" })}
            />
            Use an existing property
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg max-md:min-h-11">
            <input
              type="radio"
              name={mappingName}
              value="new"
              checked={entry.mapping === "new"}
              onChange={() => onChange({ ...entry, mapping: "new" })}
            />
            Create a new property
          </label>
        </div>

        {suggestedName ? (
          <p className="mt-2 flex items-center gap-2 text-sm text-fg-muted">
            <Badge
              label="suggested property mapping, please verify"
              className="border-warning-subtle bg-warning-subtle text-warning"
            >
              Suggested
            </Badge>
            <span>
              We matched this column to{" "}
              <span className="font-medium text-fg">{suggestedName}</span>
              {mappingConfidence != null
                ? ` (${Math.round(mappingConfidence * 100)}% confidence)`
                : ""}
              . Confirm or change the selection below.
            </span>
          </p>
        ) : null}

        {entry.mapping === "existing" ? (
          <div className="mt-3">
            <label htmlFor={`${idPrefix}-property`} className={labelClass}>
              Existing property
            </label>
            <select
              id={`${idPrefix}-property`}
              value={entry.propertyId}
              disabled={loadingProperties}
              onChange={(e) => onChange({ ...entry, propertyId: e.target.value })}
              className={inputClass}
            >
              <option value="">
                {loadingProperties ? "Loading properties…" : "Select a property"}
              </option>
              {properties.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.name} — {property.address_text}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <div>
              <label htmlFor={`${idPrefix}-new-name`} className={labelClass}>
                New property name
              </label>
              <input
                id={`${idPrefix}-new-name`}
                type="text"
                value={entry.newPropertyName}
                onChange={(e) =>
                  onChange({ ...entry, newPropertyName: e.target.value })
                }
                aria-invalid={Boolean(nameError) || undefined}
                aria-describedby={nameError ? `${idPrefix}-new-name-error` : undefined}
                className={`${inputClass} ${nameError ? invalidClass : ""}`}
              />
              {nameError ? (
                <p
                  id={`${idPrefix}-new-name-error`}
                  role="alert"
                  className="mt-1 text-sm text-danger"
                >
                  {nameError}
                </p>
              ) : null}
            </div>
            <div>
              <label htmlFor={`${idPrefix}-new-address`} className={labelClass}>
                New property address
              </label>
              <input
                id={`${idPrefix}-new-address`}
                type="text"
                value={entry.newPropertyAddress}
                onChange={(e) =>
                  onChange({ ...entry, newPropertyAddress: e.target.value })
                }
                aria-invalid={Boolean(addressError) || undefined}
                aria-describedby={
                  addressError ? `${idPrefix}-new-address-error` : undefined
                }
                className={`${inputClass} ${addressError ? invalidClass : ""}`}
              />
              {addressError ? (
                <p
                  id={`${idPrefix}-new-address-error`}
                  role="alert"
                  className="mt-1 text-sm text-danger"
                >
                  {addressError}
                </p>
              ) : null}
            </div>
          </div>
        )}
      </fieldset>

      {/* Income lines 3-4. */}
      <fieldset className="mt-6">
        <legend className="text-sm font-semibold text-fg">Income</legend>
        <div className="mt-2 grid gap-4 sm:grid-cols-2">
          {INCOME_LINES.map((def) => (
            <LineInput
              key={def.line}
              idPrefix={idPrefix}
              def={def}
              value={entry.amounts[def.line] ?? ""}
              error={errors?.lines?.[def.line]}
              verify={verifyLines.has(def.line)}
              onChange={(v) => setAmount(def.line, v)}
            />
          ))}
        </div>
      </fieldset>

      {/* Expense lines 5-17 and Line 19 "Other" (no Line 18). */}
      <fieldset className="mt-6">
        <legend className="text-sm font-semibold text-fg">Expenses</legend>
        <div className="mt-2 grid gap-4 sm:grid-cols-2">
          {EXPENSE_LINES.map((def) => (
            <LineInput
              key={def.line}
              idPrefix={idPrefix}
              def={def}
              value={entry.amounts[def.line] ?? ""}
              error={errors?.lines?.[def.line]}
              verify={verifyLines.has(def.line)}
              onChange={(v) => setAmount(def.line, v)}
            />
          ))}
        </div>

        {/* Line 19 "Other" requires a free-text description. */}
        <div className="mt-4">
          <label htmlFor={`${idPrefix}-other-description`} className={labelClass}>
            Line {OTHER_LINE.line} description{" "}
            <span className="text-fg-subtle">(optional)</span>
          </label>
          <input
            id={`${idPrefix}-other-description`}
            type="text"
            value={entry.otherDescription}
            placeholder="Imported Schedule E Other"
            onChange={(e) =>
              onChange({ ...entry, otherDescription: e.target.value })
            }
            className={inputClass}
          />
        </div>
      </fieldset>
    </Card>
  );
}
