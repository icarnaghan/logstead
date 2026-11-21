import { useId, useState } from "react";
import type { FormEvent } from "react";
import { setInterestOverride, type YearlyRollup } from "../../api/loans";
import { ApiError } from "../../lib/apiClient";
import { Button, Input } from "../ui";

export interface PastYearOverrideFormProps {
  propertyId: string;
  loanId: string;
  /** Calendar year of the loan's anchor date; the latest year this form accepts. */
  anchorYear: number;
  /** Tax years that have generated payments; those use the row's own control. */
  yearsWithPayments: ReadonlyArray<number>;
  /** Called with the saved yearly object so the host can refresh its schedule. */
  onSaved?: (rollup: YearlyRollup) => void;
  disabled?: boolean;
}

export const MIN_OVERRIDE_YEAR = 1900;

const YEAR_PATTERN = /^\d{4}$/;
/** Non-negative decimal with at most two decimal places. */
const MONEY_PATTERN = /^\d+(\.\d{1,2})?$/;

/**
 * Adds an interest override for a year that has no generated payments
 * (1900 through the anchor year). Client rules fail inline and never call the
 * API. A year that has payments is pointed to that row's own control. Server
 * `interest_overrides.<year>` errors show next to the year field.
 */
export function PastYearOverrideForm({
  propertyId,
  loanId,
  anchorYear,
  yearsWithPayments,
  onSaved,
  disabled = false,
}: PastYearOverrideFormProps) {
  const baseId = useId();
  const yearId = `${baseId}-year`;
  const yearErrorId = `${baseId}-year-error`;
  const amountId = `${baseId}-amount`;
  const amountErrorId = `${baseId}-amount-error`;

  const [year, setYear] = useState("");
  const [amount, setAmount] = useState("");
  const [yearError, setYearError] = useState<string | null>(null);
  const [amountError, setAmountError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save() {
    const yearText = year.trim();
    const amountText = amount.trim();
    let nextYearError: string | null = null;
    let nextAmountError: string | null = null;

    const yearValue = Number(yearText);
    if (
      !YEAR_PATTERN.test(yearText) ||
      yearValue < MIN_OVERRIDE_YEAR ||
      yearValue > anchorYear
    ) {
      nextYearError = `Enter a year from ${MIN_OVERRIDE_YEAR} to ${anchorYear}.`;
    } else if (yearsWithPayments.includes(yearValue)) {
      nextYearError = `${yearValue} has payments. Use the interest override control on its row in the table.`;
    }
    if (!MONEY_PATTERN.test(amountText)) {
      nextAmountError =
        "Enter a non-negative amount with at most two decimal places, for example 7010.12.";
    }

    setYearError(nextYearError);
    setAmountError(nextAmountError);
    setFormError(null);
    if (nextYearError || nextAmountError) return;

    setBusy(true);
    try {
      const saved = await setInterestOverride(propertyId, loanId, yearValue, amountText);
      setYear("");
      setAmount("");
      if (saved) onSaved?.(saved);
    } catch (err) {
      const body = err instanceof ApiError
        ? (err.body as { field?: string; message?: string } | null)
        : null;
      if (body?.message && body.field === `interest_overrides.${yearValue}`) {
        setYearError(body.message);
      } else if (body?.message && body.field === undefined) {
        setFormError(body.message);
      } else {
        setFormError("Could not save the interest override. Try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void save();
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={handleSubmit}
      noValidate
      aria-label="Add interest override for a past year"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor={yearId} className="text-sm font-medium text-fg">
            Tax year
          </label>
          <Input
            id={yearId}
            type="text"
            inputMode="numeric"
            className="w-24 tabular-nums"
            value={year}
            onChange={(e) => setYear(e.target.value)}
            invalid={yearError !== null}
            aria-describedby={yearError ? yearErrorId : undefined}
            disabled={disabled || busy}
          />
          {yearError ? (
            <p id={yearErrorId} role="alert" className="text-xs text-danger">
              {yearError}
            </p>
          ) : null}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={amountId} className="text-sm font-medium text-fg">
            Form 1098 interest
          </label>
          <Input
            id={amountId}
            type="text"
            inputMode="decimal"
            className="w-32 text-right tabular-nums"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            invalid={amountError !== null}
            aria-describedby={amountError ? amountErrorId : undefined}
            disabled={disabled || busy}
          />
          {amountError ? (
            <p id={amountErrorId} role="alert" className="text-xs text-danger">
              {amountError}
            </p>
          ) : null}
        </div>
        <Button
          type="submit"
          variant="primary"
          size="sm"
          className="mt-6"
          disabled={disabled || busy}
        >
          Add override
        </Button>
      </div>
      {formError ? (
        <p role="alert" className="text-xs text-danger">
          {formError}
        </p>
      ) : null}
    </form>
  );
}
