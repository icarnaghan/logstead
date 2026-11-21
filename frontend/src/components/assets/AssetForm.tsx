import { useId, useState, type FormEvent } from "react";
import {
  DEFAULT_RECOVERY_PERIOD_YEARS,
  type CreateAssetInput,
  type DepreciableAsset,
} from "../../api/assets";
import { useDirtyReporter } from "../../lib/dirty";
import { useDismissibleErrors } from "../../lib/useDismissibleErrors";
import { Button, ErrorSummary, DateInput, FormField, Input, MoneyInput, useFocusFirstInvalid, ModalFormActions } from "../ui";
import { orderedErrors, type ErrorSummaryItem } from "../../lib/formErrors";

/** The shape submitted upward; recovery period is already resolved to a number. */
export interface AssetFormValues {
  description: string;
  cost_basis: string;
  placed_in_service_date: string;
  recovery_period_years: number;
}

interface AssetFormProps {
  /** When present, the form is in edit mode and pre-populates from this asset. */
  asset?: DepreciableAsset;
  /**
   * Field-specific validation errors keyed by field name (e.g. from a 400
   * response's `field`). Rendered inline next to the offending control.
   */
  fieldErrors?: Partial<Record<keyof CreateAssetInput, string>>;
  /** Form-level error (no specific field), shown above the first field. */
  formError?: string;
  /** Disables inputs while a submit is in flight. */
  submitting?: boolean;
  onSubmit: (values: AssetFormValues) => void;
  onCancel?: () => void;
  /** Reports whether the entered values differ from the initial values. */
  onDirtyChange?: (dirty: boolean) => void;
}

const FIELD_ORDER = [
  "description",
  "cost_basis",
  "placed_in_service_date",
  "recovery_period_years",
] as const;

/**
 * Create / edit form for a depreciable asset (Requirements 8.1–8.5).
 *
 * The recovery period defaults to 27.5 years for residential rental buildings:
 * when the field is left blank the form submits {@link
 * DEFAULT_RECOVERY_PERIOD_YEARS} (Requirement 8.4). The default is shown to the
 * user via the input placeholder and helper text so the behaviour is explicit.
 *
 * Cost-basis and other field validation is enforced by the backend (which
 * rejects `cost_basis <= 0` with a 400 carrying a `field`); those messages are
 * surfaced through {@link fieldErrors} next to the relevant control
 * (Requirements 8.2, 8.3).
 */
export function AssetForm({
  asset,
  fieldErrors,
  formError,
  submitting = false,
  onSubmit,
  onCancel,
  onDirtyChange,
}: AssetFormProps) {
  const { errors: visibleErrors, dismiss } = useDismissibleErrors<
    keyof CreateAssetInput
  >(fieldErrors);
  const baseId = useId();
  const descId = `${baseId}-description`;
  const costId = `${baseId}-cost-basis`;
  const dateId = `${baseId}-placed-in-service`;
  const recoveryId = `${baseId}-recovery-period`;

  const [description, setDescription] = useState(asset?.description ?? "");
  const [costBasis, setCostBasis] = useState(asset?.cost_basis ?? "");
  const [placedInService, setPlacedInService] = useState(
    asset?.placed_in_service_date ?? "",
  );
  const [recoveryPeriod, setRecoveryPeriod] = useState(
    asset ? String(asset.recovery_period_years) : "",
  );

  const [initial] = useState(() => ({
    description: asset?.description ?? "",
    costBasis: asset?.cost_basis ?? "",
    placedInService: asset?.placed_in_service_date ?? "",
    recoveryPeriod: asset ? String(asset.recovery_period_years) : "",
  }));
  useDirtyReporter(
    initial,
    { description, costBasis, placedInService, recoveryPeriod },
    onDirtyChange,
  );

  const [attempt, setAttempt] = useState(0);
  const [prevFieldErrors, setPrevFieldErrors] = useState(fieldErrors);
  if (prevFieldErrors !== fieldErrors) {
    setPrevFieldErrors(fieldErrors);
    if (orderedErrors(fieldErrors ?? {}, FIELD_ORDER).length > 0) {
      setAttempt((n) => n + 1);
    }
  }
  const idFor = (field: string) =>
    ({
      description: descId,
      cost_basis: costId,
      placed_in_service_date: dateId,
      recovery_period_years: recoveryId,
    })[field as (typeof FIELD_ORDER)[number]] ?? field;
  useFocusFirstInvalid({
    errors: visibleErrors,
    order: FIELD_ORDER,
    idFor,
    attempt,
  });
  const summaryItems: ErrorSummaryItem[] = [
    ...orderedErrors(visibleErrors, FIELD_ORDER),
    ...(formError ? [{ message: formError }] : []),
  ];

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedRecovery = recoveryPeriod.trim();
    const resolvedRecovery =
      trimmedRecovery === ""
        ? DEFAULT_RECOVERY_PERIOD_YEARS
        : Number(trimmedRecovery);

    onSubmit({
      description: description.trim(),
      cost_basis: costBasis.trim(),
      placed_in_service_date: placedInService,
      recovery_period_years: resolvedRecovery,
    });
  }

  function errorFor(field: keyof CreateAssetInput): string | undefined {
    return visibleErrors[field];
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      <ErrorSummary
        items={summaryItems}
        idFor={idFor}
        headingId={`${baseId}-error-summary`}
      />
      <FormField
        id={descId}
        label="Description"
        required
        error={errorFor("description")}
      >
        {(control) => (
          <Input
            {...control}
            name="description"
            type="text"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              dismiss("description");
            }}
            disabled={submitting}
            required
            className="block w-full"
          />
        )}
      </FormField>

      <FormField
        id={costId}
        label="Cost basis"
        required
        error={errorFor("cost_basis")}
      >
        {(control) => (
          <MoneyInput
            {...control}
            name="cost_basis"
            value={costBasis}
            onValueChange={(v) => {
              setCostBasis(v);
              dismiss("cost_basis");
            }}
            disabled={submitting}
            required
            className="block w-full"
          />
        )}
      </FormField>

      <FormField
        id={dateId}
        label="Placed in service"
        required
        error={errorFor("placed_in_service_date")}
      >
        {(control) => (
          <DateInput
            {...control}
            name="placed_in_service_date"
            value={placedInService}
            onValueChange={(v) => {
              setPlacedInService(v);
              dismiss("placed_in_service_date");
            }}
            disabled={submitting}
            required
            className="block w-full"
          />
        )}
      </FormField>

      <FormField
        id={recoveryId}
        label="Recovery period (years)"
        hint={`Leave blank to use the residential rental default of ${DEFAULT_RECOVERY_PERIOD_YEARS} years.`}
        error={errorFor("recovery_period_years")}
      >
        {(control) => (
          <Input
            {...control}
            name="recovery_period_years"
            type="number"
            step="0.5"
            min="0"
            value={recoveryPeriod}
            onChange={(e) => {
              setRecoveryPeriod(e.target.value);
              dismiss("recovery_period_years");
            }}
            disabled={submitting}
            placeholder={String(DEFAULT_RECOVERY_PERIOD_YEARS)}
            className="block w-full"
          />
        )}
      </FormField>

      <ModalFormActions>
        <Button type="submit" variant="primary" size="sm" disabled={submitting}>
          {asset ? "Save changes" : "Add asset"}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </Button>
        )}
      </ModalFormActions>
    </form>
  );
}
