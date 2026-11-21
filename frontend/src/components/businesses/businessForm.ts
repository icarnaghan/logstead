import { ENTITY_TYPES } from "../../api/businesses";

/**
 * Shared constants and helpers for the Add/Edit business dialogs.
 *
 * The entity-type labels mirror the stored snake_case tokens to human-readable
 * strings (the same mapping the BusinessesPage uses for its list); the UI never
 * surfaces the raw token where a label exists. The US-states list backs the
 * optional `formation_state` dropdown (two-letter uppercase codes, Resolved
 * Decision 4). Everything here is plain data so both dialogs and their tests can
 * share one source of truth.
 */

/** Human-readable labels for each stored `entity_type` token. */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  llc: "LLC",
  sole_proprietorship: "Sole proprietorship",
  partnership: "Partnership",
  s_corporation: "S corporation",
  c_corporation: "C corporation",
  individual_other: "Individual / other",
};

/** Render a stored `entity_type` token as a human-readable label. */
export function entityTypeLabel(entityType: string): string {
  const known = ENTITY_TYPE_LABELS[entityType];
  if (known) return known;
  const spaced = entityType.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : entityType;
}

/** The entity-type options rendered in the `<select>`, in a stable order. */
export const ENTITY_TYPE_OPTIONS = ENTITY_TYPES.map((value) => ({
  value,
  label: entityTypeLabel(value),
}));

/**
 * The 50 US states plus the District of Columbia, as `{ code, name }` pairs for
 * the optional `formation_state` dropdown. Codes are two-letter uppercase and
 * are what gets stored on the wire (Resolved Decision 4).
 */
export const US_STATES: ReadonlyArray<{ code: string; name: string }> = [
  { code: "AL", name: "Alabama" },
  { code: "AK", name: "Alaska" },
  { code: "AZ", name: "Arizona" },
  { code: "AR", name: "Arkansas" },
  { code: "CA", name: "California" },
  { code: "CO", name: "Colorado" },
  { code: "CT", name: "Connecticut" },
  { code: "DE", name: "Delaware" },
  { code: "DC", name: "District of Columbia" },
  { code: "FL", name: "Florida" },
  { code: "GA", name: "Georgia" },
  { code: "HI", name: "Hawaii" },
  { code: "ID", name: "Idaho" },
  { code: "IL", name: "Illinois" },
  { code: "IN", name: "Indiana" },
  { code: "IA", name: "Iowa" },
  { code: "KS", name: "Kansas" },
  { code: "KY", name: "Kentucky" },
  { code: "LA", name: "Louisiana" },
  { code: "ME", name: "Maine" },
  { code: "MD", name: "Maryland" },
  { code: "MA", name: "Massachusetts" },
  { code: "MI", name: "Michigan" },
  { code: "MN", name: "Minnesota" },
  { code: "MS", name: "Mississippi" },
  { code: "MO", name: "Missouri" },
  { code: "MT", name: "Montana" },
  { code: "NE", name: "Nebraska" },
  { code: "NV", name: "Nevada" },
  { code: "NH", name: "New Hampshire" },
  { code: "NJ", name: "New Jersey" },
  { code: "NM", name: "New Mexico" },
  { code: "NY", name: "New York" },
  { code: "NC", name: "North Carolina" },
  { code: "ND", name: "North Dakota" },
  { code: "OH", name: "Ohio" },
  { code: "OK", name: "Oklahoma" },
  { code: "OR", name: "Oregon" },
  { code: "PA", name: "Pennsylvania" },
  { code: "RI", name: "Rhode Island" },
  { code: "SC", name: "South Carolina" },
  { code: "SD", name: "South Dakota" },
  { code: "TN", name: "Tennessee" },
  { code: "TX", name: "Texas" },
  { code: "UT", name: "Utah" },
  { code: "VT", name: "Vermont" },
  { code: "VA", name: "Virginia" },
  { code: "WA", name: "Washington" },
  { code: "WV", name: "West Virginia" },
  { code: "WI", name: "Wisconsin" },
  { code: "WY", name: "Wyoming" },
];

/** Default `tax_year_end` (MM-DD) applied when the user leaves it untouched. */
export const DEFAULT_TAX_YEAR_END = "12-31";

/** The twelve month options for the month/day `tax_year_end` control. */
export const MONTH_OPTIONS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "01", label: "January" },
  { value: "02", label: "February" },
  { value: "03", label: "March" },
  { value: "04", label: "April" },
  { value: "05", label: "May" },
  { value: "06", label: "June" },
  { value: "07", label: "July" },
  { value: "08", label: "August" },
  { value: "09", label: "September" },
  { value: "10", label: "October" },
  { value: "11", label: "November" },
  { value: "12", label: "December" },
];

/**
 * Field-level validation errors keyed by the input they belong to, plus an
 * optional form-level message. Mirrors the shape used by the property dialogs.
 */
export interface BusinessFieldErrors {
  legal_name?: string;
  entity_type?: string;
  form?: string;
}

/**
 * Map a server 400 `{ field, message }` body onto {@link BusinessFieldErrors}.
 * Known fields (`legal_name`, `entity_type`) render adjacent to their input;
 * anything else becomes a form-level error. Mirrors AddPropertyDialog's handler.
 */
export function fieldErrorsFromBody(
  body: { field?: string; message?: string } | null,
): BusinessFieldErrors {
  const field = body?.field;
  const message = body?.message ?? "Please correct the highlighted field.";
  if (field === "legal_name" || field === "entity_type") {
    return { [field]: message };
  }
  return { form: message };
}

/**
 * Build the `BusinessInput` payload from the current form state, trimming text
 * and omitting optional fields that are blank (sent as `null`). `tax_year_end`
 * is always included and defaults to {@link DEFAULT_TAX_YEAR_END}.
 */
export function buildBusinessInput(fields: {
  legalName: string;
  entityType: string;
  ein: string;
  formationState: string;
  formationDate: string;
  businessAddress: string;
  taxYearEnd: string;
  note: string;
}) {
  const orNull = (value: string) => (value.trim() ? value.trim() : null);
  return {
    legal_name: fields.legalName.trim(),
    entity_type: fields.entityType,
    ein: orNull(fields.ein),
    formation_state: orNull(fields.formationState),
    formation_date: orNull(fields.formationDate),
    business_address: orNull(fields.businessAddress),
    tax_year_end: fields.taxYearEnd.trim() || DEFAULT_TAX_YEAR_END,
    note: orNull(fields.note),
  };
}

/** Split a stored `MM-DD` string into month/day parts for the UI controls. */
export function splitTaxYearEnd(value: string | null | undefined): {
  month: string;
  day: string;
} {
  const source = value && value.trim() ? value.trim() : DEFAULT_TAX_YEAR_END;
  const [month = "12", day = "31"] = source.split("-");
  return { month, day };
}

/**
 * Join month/day parts back into a stored `MM-DD` string, zero-padding the day
 * so a day entered as "1" is stored as "01". Falls back to the default parts
 * when a value is blank.
 */
export function joinTaxYearEnd(month: string, day: string): string {
  const [defMonth, defDay] = DEFAULT_TAX_YEAR_END.split("-");
  const mm = (month.trim() || defMonth).padStart(2, "0");
  const dd = (day.trim() || defDay).padStart(2, "0");
  return `${mm}-${dd}`;
}
