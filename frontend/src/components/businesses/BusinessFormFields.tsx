import { DateInput, FormField, Input, Select, Textarea } from "../ui";
import {
  ENTITY_TYPE_OPTIONS,
  MONTH_OPTIONS,
  US_STATES,
  type BusinessFieldErrors,
} from "./businessForm";

/** The editable form state shared by the Add and Edit business dialogs. */
export interface BusinessFormState {
  legalName: string;
  entityType: string;
  ein: string;
  formationState: string;
  formationDate: string;
  businessAddress: string;
  taxYearEndMonth: string;
  taxYearEndDay: string;
  note: string;
}

interface BusinessFormFieldsProps {
  /** A short unique prefix for input ids (so Add and Edit never collide). */
  idPrefix: string;
  fields: BusinessFormState;
  errors: BusinessFieldErrors;
  onChange: <K extends keyof BusinessFormState>(
    key: K,
    value: BusinessFormState[K],
  ) => void;
}

/**
 * The shared set of business fields rendered inside both the Add and Edit
 * dialogs (Requirements 1, 4, 11.3). Kept as a presentational component so each
 * dialog owns its own submit/validation flow while the field markup — the
 * entity-type select (explicit selection required, no default), the non-blocking
 * EIN hint, the 50-states + DC dropdown, the native date input, and the
 * month/day `tax_year_end` control — stays in one place and renders identically.
 */
export function BusinessFormFields({
  idPrefix,
  fields,
  errors,
  onChange,
}: BusinessFormFieldsProps) {
  const legalNameId = `${idPrefix}-legal-name`;
  const entityTypeId = `${idPrefix}-entity-type`;
  const einId = `${idPrefix}-ein`;
  const stateId = `${idPrefix}-formation-state`;
  const dateId = `${idPrefix}-formation-date`;
  const monthId = `${idPrefix}-tax-year-end-month`;
  const dayId = `${idPrefix}-tax-year-end-day`;
  const addressId = `${idPrefix}-business-address`;
  const noteId = `${idPrefix}-note`;
  const optional = <span className="text-fg-subtle">(optional)</span>;

  return (
    <>
      <FormField
        id={legalNameId}
        label="Legal name"
        required
        error={errors.legal_name}
      >
        {(control) => (
          <Input
            {...control}
            type="text"
            value={fields.legalName}
            onChange={(e) => onChange("legalName", e.target.value)}
          />
        )}
      </FormField>

      <FormField
        id={entityTypeId}
        label="Entity type"
        required
        error={errors.entity_type}
      >
        {(control) => (
          <Select
            {...control}
            value={fields.entityType}
            onChange={(e) => onChange("entityType", e.target.value)}
          >
            {/* Placeholder is not a valid submit value — the user must choose. */}
            <option value="">Select an entity type</option>
            {ENTITY_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
      </FormField>

      <FormField id={einId} label={<>EIN {optional}</>}>
        {(control) => (
          <Input
            {...control}
            type="text"
            value={fields.ein}
            onChange={(e) => onChange("ein", e.target.value)}
            placeholder="NN-NNNNNNN"
          />
        )}
      </FormField>

      <FormField id={stateId} label={<>Formation state {optional}</>}>
        {(control) => (
          <Select
            {...control}
            value={fields.formationState}
            onChange={(e) => onChange("formationState", e.target.value)}
          >
            <option value="">Not specified</option>
            {US_STATES.map((state) => (
              <option key={state.code} value={state.code}>
                {state.name} ({state.code})
              </option>
            ))}
          </Select>
        )}
      </FormField>

      <FormField id={dateId} label={<>Formation date {optional}</>}>
        {(control) => (
          <DateInput
            {...control}
            value={fields.formationDate}
            onValueChange={(value) => onChange("formationDate", value)}
          />
        )}
      </FormField>

      <fieldset>
        <legend className="text-sm font-medium text-fg">Tax year end</legend>
        <div className="mt-1 flex gap-2">
          <div className="flex-1">
            <label htmlFor={monthId} className="sr-only">
              Tax year end month
            </label>
            <Select
              id={monthId}
              value={fields.taxYearEndMonth}
              onChange={(e) => onChange("taxYearEndMonth", e.target.value)}
              className="w-full"
            >
              {MONTH_OPTIONS.map((month) => (
                <option key={month.value} value={month.value}>
                  {month.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="w-24">
            <label htmlFor={dayId} className="sr-only">
              Tax year end day
            </label>
            <Input
              id={dayId}
              type="number"
              min={1}
              max={31}
              value={fields.taxYearEndDay}
              onChange={(e) => onChange("taxYearEndDay", e.target.value)}
              className="w-full"
            />
          </div>
        </div>
      </fieldset>

      <FormField id={addressId} label={<>Business address {optional}</>}>
        {(control) => (
          <Input
            {...control}
            type="text"
            value={fields.businessAddress}
            onChange={(e) => onChange("businessAddress", e.target.value)}
          />
        )}
      </FormField>

      <FormField id={noteId} label={<>Note {optional}</>}>
        {(control) => (
          <Textarea
            {...control}
            value={fields.note}
            onChange={(e) => onChange("note", e.target.value)}
            rows={3}
          />
        )}
      </FormField>
    </>
  );
}
