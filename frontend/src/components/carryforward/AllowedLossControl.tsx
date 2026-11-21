import { useEffect, useId, useState } from "react";
import type { ReconciledYear } from "../../api/carryforward";
import { formatMoneyWholeDollars } from "../../lib/money";
import { Button, Input } from "../ui";
import { fieldErrorMessage, isNonNegativeAmount } from "./carryforwardText";

/**
 * The inline allowed-loss control for one loss row (Requirements 6.1, 6.3, 6.4,
 * 6.5). Rendered only on loss years by {@link ReconciliationRow}. It holds two
 * pieces:
 *
 *   - A **fully-allowed toggle** (a checkbox with a visible, associated label)
 *     bound to `year.fully_allowed`. Toggling it calls
 *     `onSetFullyAllowed(year, checked)` and refreshes the series in place.
 *     While on, the whole loss is treated as allowed, so the explicit amount
 *     input is made **moot** — disabled, with a hint that the whole loss is
 *     allowed — and no amount is required (Req 6.3).
 *   - An **allowed-amount input** + Save, plus a Clear button once an amount is
 *     recorded (`year.allowed_loss !== "0.00"`). Saving calls
 *     `onSetAllowed(year, amount)`; clearing calls `onClearAllowed(year)`.
 *
 * Client-side validation is minimal (non-negative two-decimal via
 * {@link isNonNegativeAmount}); the authoritative check is the server's, whose
 * 400 `allowed_loss`/`allowedLoss` (or `fully_allowed`/`fullyAllowed`) field
 * error is surfaced inline, announced via `role="alert"` and tied to the input
 * with `aria-describedby`. The amount input echoes the stored two-decimal
 * string (`"0.00"` shows as empty) and is kept in sync via a `useEffect` on the
 * year's allowed state, mirroring {@link ReportedEditor}.
 */
export function AllowedLossControl({
  year,
  onSetAllowed,
  onClearAllowed,
  onSetFullyAllowed,
}: {
  year: ReconciledYear;
  onSetAllowed: (taxYear: number, amount: string) => Promise<void>;
  onClearAllowed: (taxYear: number) => Promise<void>;
  onSetFullyAllowed: (taxYear: number, on: boolean) => Promise<void>;
}) {
  const fullyAllowed = year.fully_allowed;
  const hasAllowed = year.allowed_loss !== "0.00";
  const [value, setValue] = useState(hasAllowed ? year.allowed_loss : "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();
  const toggleId = useId();

  // Keep the field in sync when the series refreshes (e.g. after toggling
  // fully-allowed, or after another row's save) and this row's allowed state
  // changes underneath us. "0.00" (none recorded) echoes as an empty field.
  useEffect(() => {
    setValue(year.allowed_loss !== "0.00" ? year.allowed_loss : "");
    setError(null);
  }, [year.allowed_loss, year.fully_allowed]);

  const allowedFields = ["allowed_loss", "allowedLoss"];
  const toggleFields = ["fully_allowed", "fullyAllowed"];

  async function handleToggle(checked: boolean) {
    setError(null);
    setBusy(true);
    try {
      await onSetFullyAllowed(year.tax_year, checked);
    } catch (err) {
      setError(
        fieldErrorMessage(
          err,
          toggleFields,
          "Could not update the fully-allowed setting.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    if (!isNonNegativeAmount(value)) {
      setError("Enter a non-negative amount with up to two decimals.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onSetAllowed(year.tax_year, value.trim());
    } catch (err) {
      setError(
        fieldErrorMessage(err, allowedFields, "Could not save the allowed loss."),
      );
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    setError(null);
    setBusy(true);
    try {
      await onClearAllowed(year.tax_year);
    } catch (err) {
      setError(
        fieldErrorMessage(
          err,
          allowedFields,
          "Could not clear the allowed loss.",
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  // The loss magnitude (positive) for the "whole loss allowed" hint shown when
  // fully-allowed is on. schedule_e_net is negative on a loss row.
  const lossMagnitude = formatMoneyWholeDollars(
    year.schedule_e_net.startsWith("-")
      ? year.schedule_e_net.slice(1)
      : year.schedule_e_net,
  );

  return (
    <div className="flex flex-col items-end gap-1">
      <label
        htmlFor={toggleId}
        className="flex items-center gap-2 text-sm text-fg-muted max-md:min-h-11"
      >
        <input
          id={toggleId}
          type="checkbox"
          checked={fullyAllowed}
          onChange={(e) => void handleToggle(e.target.checked)}
          disabled={busy}
          aria-describedby={error ? errorId : undefined}
        />
        Fully allowed
      </label>
      <p className="text-xs text-fg-muted">
        Changes the amount expected to carry into the next year.
      </p>
      <div className="flex items-center justify-end gap-2">
        <label htmlFor={inputId} className="sr-only">
          Allowed loss for {year.tax_year}
        </label>
        {fullyAllowed ? (
          <span className="text-sm text-fg-muted tabular-nums">
            Whole loss allowed ({lossMagnitude})
          </span>
        ) : null}
        <Input
          id={inputId}
          inputMode="decimal"
          value={fullyAllowed ? "" : value}
          onChange={(e) => setValue(e.target.value)}
          invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          disabled={busy || fullyAllowed}
          placeholder={fullyAllowed ? "—" : undefined}
          className="w-28 text-right tabular-nums"
        />
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={() => void handleSave()}
          disabled={busy || fullyAllowed}
        >
          {busy ? "Saving…" : "Save"}
        </Button>
        {hasAllowed ? (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => void handleClear()}
            disabled={busy || fullyAllowed}
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
