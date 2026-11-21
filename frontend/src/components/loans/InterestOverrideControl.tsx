import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";
import {
  clearInterestOverride,
  setInterestOverride,
  type YearlyRollup,
} from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { formatMoney, formatMoneyWholeDollars } from "../../lib/money";
import { Button, Input } from "../ui";

export interface InterestOverrideControlProps {
  propertyId: string;
  loanId: string;
  /** The year's current rollup (estimated interest, override, variance). */
  rollup: YearlyRollup;
  /**
   * Called after a successful save (the updated rollup) or clear (the updated
   * rollup, or `null` when the server returns none). The host refreshes its
   * schedule from this.
   */
  onChange?: (rollup: YearlyRollup | null) => void;
  /** Disables the controls (e.g. while the host is busy). */
  disabled?: boolean;
}

/** Non-negative decimal with at most two decimal places. */
const MONEY_PATTERN = /^\d+(\.\d{1,2})?$/;

/** Variance in words, e.g. "$120 lower than the estimate". Null when absent or zero. */
export function varianceText(variance: string | null): string | null {
  if (variance === null || variance === "") return null;
  const negative = variance.trim().startsWith("-");
  const magnitude = negative ? variance.trim().slice(1) : variance.trim();
  if (!/^\d+(\.\d+)?$/.test(magnitude)) return null;
  const amount = formatMoneyWholeDollars(magnitude);
  if (/^\$0$/.test(amount) && !/[1-9]/.test(magnitude)) {
    return "Same as the estimate";
  }
  return `${amount} ${negative ? "lower" : "higher"} than the estimate`;
}

/**
 * Per-year interest override input. Money stays a string end to end. Saves
 * only on the Save button or Enter (never on blur); a negative, non-numeric or
 * more-than-two-decimal value is rejected inline and never sent (9.14).
 * Server errors for `interest_overrides.<year>` show next to this year (9.14).
 * Clear removes the override and the variance text (9.13).
 */
export function InterestOverrideControl({
  propertyId,
  loanId,
  rollup,
  onChange,
  disabled = false,
}: InterestOverrideControlProps) {
  const year = rollup.tax_year;
  const baseId = useId();
  const inputId = `${baseId}-input`;
  const errorId = `${baseId}-error`;
  const varianceId = `${baseId}-variance`;

  const [draft, setDraft] = useState(rollup.interest_override ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Resync when the persisted override changes underneath us.
  useEffect(() => {
    setDraft(rollup.interest_override ?? "");
    setError(null);
  }, [rollup.interest_override]);

  const hasOverride = rollup.interest_override !== null;
  const variance = hasOverride ? varianceText(rollup.variance) : null;

  function messageFrom(err: unknown): string {
    if (err instanceof ApiError) {
      const body = err.body as { field?: string; message?: string } | null;
      if (body?.message && (!body.field || body.field === `interest_overrides.${year}`)) {
        return body.message;
      }
    }
    return "Could not update the interest override. Try again.";
  }

  async function save() {
    const value = draft.trim();
    if (!MONEY_PATTERN.test(value)) {
      setError(
        "Enter a non-negative amount with at most two decimal places, for example 7010.12.",
      );
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const updated = await setInterestOverride(propertyId, loanId, year, value);
      onChange?.(updated);
    } catch (err) {
      setError(messageFrom(err));
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setError(null);
    setBusy(true);
    try {
      const updated = await clearInterestOverride(propertyId, loanId, year);
      setDraft("");
      onChange?.(updated);
    } catch (err) {
      setError(messageFrom(err));
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void save();
  }

  const describedBy =
    [error ? errorId : null, variance ? varianceId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <form className="flex flex-col gap-1" onSubmit={handleSubmit} noValidate>
      <div className="flex items-center gap-2">
        <label htmlFor={inputId} className="sr-only">
          Interest override for {year}
        </label>
        <Input
          id={inputId}
          type="text"
          inputMode="decimal"
          className="w-28 text-right tabular-nums"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={rollup.estimated_interest}
          invalid={error !== null}
          aria-describedby={describedBy}
          disabled={disabled || busy}
        />
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={disabled || busy}
          aria-label={`Save interest override for ${year}`}
        >
          Save
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={() => void clear()}
          disabled={disabled || busy || !hasOverride}
          aria-label={`Clear interest override for ${year}`}
        >
          Clear
        </Button>
      </div>
      <p className="text-xs text-fg-subtle">
        Estimated interest: {formatMoney(rollup.estimated_interest)}
      </p>
      {variance ? (
        <p id={varianceId} className="text-xs text-fg-muted">
          {variance}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </form>
  );
}
