import { useEffect, useId, useState } from "react";
import type { ReconciledYear } from "../../api/carryforward";
import { Button, Input } from "../ui";
import { amountErrorMessage, isNonNegativeAmount } from "./carryforwardText";

/**
 * The inline reported-value editor for one reconciliation row (Requirements
 * 3.3, 5.5, 5.6). An amount input plus a Save button, and — when the year
 * already has a reported value — a Clear button. Saving calls
 * `setReported(year, amount)`; clearing calls `clearReported(year)`; either way
 * the parent refreshes the whole series in place afterward (no full reload) so
 * expected/reported/status update together.
 *
 * Client-side validation is minimal (non-empty, non-negative two-decimal); the
 * authoritative check is the server's, whose 400 `amount` error is surfaced
 * inline next to this control, announced via `role="alert"` and tied to the
 * input with `aria-describedby`. The input has an associated (visually hidden)
 * label naming the year so the control is accessible.
 */
export function ReportedEditor({
  year,
  onSave,
  onClear,
}: {
  year: ReconciledYear;
  onSave: (taxYear: number, amount: string) => Promise<void>;
  onClear: (taxYear: number) => Promise<void>;
}) {
  const hasReported = year.reported_carryforward !== null;
  const [value, setValue] = useState(year.reported_carryforward ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();

  // Keep the field in sync when the series refreshes (e.g. after another row's
  // save) and this row's reported value changes underneath us.
  useEffect(() => {
    setValue(year.reported_carryforward ?? "");
    setError(null);
  }, [year.reported_carryforward]);

  async function handleSave() {
    if (!isNonNegativeAmount(value)) {
      setError("Enter a non-negative amount with up to two decimals.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onSave(year.tax_year, value.trim());
    } catch (err) {
      setError(
        amountErrorMessage(
          err,
          "Could not save the prior years' unallowed losses.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setError(null);
    setBusy(true);
    try {
      await onClear(year.tax_year);
    } catch (err) {
      setError(
        amountErrorMessage(
          err,
          "Could not clear the prior years' unallowed losses.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center justify-end gap-2">
        <label htmlFor={inputId} className="sr-only">
          Prior years' unallowed losses for {year.tax_year}
        </label>
        <Input
          id={inputId}
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          disabled={busy}
          className="w-28 text-right tabular-nums"
        />
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={() => void handleSave()}
          disabled={busy}
        >
          {busy ? "Saving…" : "Save"}
        </Button>
        {hasReported ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void handleClear()}
            disabled={busy}
          >
            Clear
          </Button>
        ) : null}
      </div>
      {error ? (
        <p id={errorId} role="alert" className="text-right text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
