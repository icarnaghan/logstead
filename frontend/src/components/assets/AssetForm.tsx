import { useId, useState, type FormEvent } from "react";
import {
  DEFAULT_RECOVERY_PERIOD_YEARS,
  type CreateAssetInput,
  type DepreciableAsset,
} from "../../api/assets";

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
  /** Disables inputs while a submit is in flight. */
  submitting?: boolean;
  onSubmit: (values: AssetFormValues) => void;
  onCancel?: () => void;
}

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
  submitting = false,
  onSubmit,
  onCancel,
}: AssetFormProps) {
  const baseId = useId();
  const descId = `${baseId}-description`;
  const costId = `${baseId}-cost-basis`;
  const dateId = `${baseId}-placed-in-service`;
  const recoveryId = `${baseId}-recovery-period`;
  const recoveryHelpId = `${baseId}-recovery-help`;

  const [description, setDescription] = useState(asset?.description ?? "");
  const [costBasis, setCostBasis] = useState(asset?.cost_basis ?? "");
  const [placedInService, setPlacedInService] = useState(
    asset?.placed_in_service_date ?? "",
  );
  const [recoveryPeriod, setRecoveryPeriod] = useState(
    asset ? String(asset.recovery_period_years) : "",
  );

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
    return fieldErrors?.[field];
  }

  const inputClass =
    "mt-1 block w-full rounded-md border border-border px-3 py-1.5 text-sm " +
    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      <div>
        <label htmlFor={descId} className="text-sm font-medium text-fg-muted">
          Description
        </label>
        <input
          id={descId}
          name="description"
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={submitting}
          required
          aria-invalid={errorFor("description") ? true : undefined}
          aria-describedby={
            errorFor("description") ? `${descId}-error` : undefined
          }
          className={inputClass}
        />
        {errorFor("description") && (
          <p id={`${descId}-error`} role="alert" className="mt-1 text-sm text-danger">
            {errorFor("description")}
          </p>
        )}
      </div>

      <div>
        <label htmlFor={costId} className="text-sm font-medium text-fg-muted">
          Cost basis
        </label>
        <input
          id={costId}
          name="cost_basis"
          type="text"
          inputMode="decimal"
          value={costBasis}
          onChange={(e) => setCostBasis(e.target.value)}
          disabled={submitting}
          required
          aria-invalid={errorFor("cost_basis") ? true : undefined}
          aria-describedby={
            errorFor("cost_basis") ? `${costId}-error` : undefined
          }
          className={inputClass}
        />
        {errorFor("cost_basis") && (
          <p id={`${costId}-error`} role="alert" className="mt-1 text-sm text-danger">
            {errorFor("cost_basis")}
          </p>
        )}
      </div>

      <div>
        <label htmlFor={dateId} className="text-sm font-medium text-fg-muted">
          Placed in service
        </label>
        <input
          id={dateId}
          name="placed_in_service_date"
          type="date"
          value={placedInService}
          onChange={(e) => setPlacedInService(e.target.value)}
          disabled={submitting}
          required
          aria-invalid={errorFor("placed_in_service_date") ? true : undefined}
          aria-describedby={
            errorFor("placed_in_service_date")
              ? `${dateId}-error`
              : undefined
          }
          className={inputClass}
        />
        {errorFor("placed_in_service_date") && (
          <p id={`${dateId}-error`} role="alert" className="mt-1 text-sm text-danger">
            {errorFor("placed_in_service_date")}
          </p>
        )}
      </div>

      <div>
        <label
          htmlFor={recoveryId}
          className="text-sm font-medium text-fg-muted"
        >
          Recovery period (years)
        </label>
        <input
          id={recoveryId}
          name="recovery_period_years"
          type="number"
          step="0.5"
          min="0"
          value={recoveryPeriod}
          onChange={(e) => setRecoveryPeriod(e.target.value)}
          disabled={submitting}
          placeholder={String(DEFAULT_RECOVERY_PERIOD_YEARS)}
          aria-invalid={errorFor("recovery_period_years") ? true : undefined}
          aria-describedby={
            errorFor("recovery_period_years")
              ? `${recoveryId}-error ${recoveryHelpId}`
              : recoveryHelpId
          }
          className={inputClass}
        />
        <p id={recoveryHelpId} className="mt-1 text-sm text-fg-subtle">
          Leave blank to use the residential rental default of{" "}
          {DEFAULT_RECOVERY_PERIOD_YEARS} years.
        </p>
        {errorFor("recovery_period_years") && (
          <p
            id={`${recoveryId}-error`}
            role="alert"
            className="mt-1 text-sm text-danger"
          >
            {errorFor("recovery_period_years")}
          </p>
        )}
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
        >
          {asset ? "Save changes" : "Add asset"}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-fg-muted hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
