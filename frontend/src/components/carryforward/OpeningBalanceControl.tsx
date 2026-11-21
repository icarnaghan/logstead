import { useEffect, useId, useState } from "react";
import { Button, Input } from "../ui";
import { amountErrorMessage, isNonNegativeAmount } from "./carryforwardText";

/**
 * The editable opening-balance control (Requirements 7.1, 7.3). An amount input
 * plus a Save button that calls `setOpeningBalance(amount)` and refreshes the
 * series in place. Validated client-side as a non-negative two-decimal amount;
 * the server's 400 `amount` error is surfaced inline, announced via
 * `role="alert"` and tied to the input with `aria-describedby`.
 */
export function OpeningBalanceControl({
  openingBalance,
  onSave,
}: {
  openingBalance: string;
  onSave: (amount: string) => Promise<void>;
}) {
  const [value, setValue] = useState(openingBalance);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputId = useId();
  const errorId = useId();

  // Reflect the persisted opening balance when the series refreshes.
  useEffect(() => {
    setValue(openingBalance);
    setError(null);
  }, [openingBalance]);

  async function handleSave() {
    if (!isNonNegativeAmount(value)) {
      setError("Enter a non-negative amount with up to two decimals.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await onSave(value.trim());
    } catch (err) {
      setError(amountErrorMessage(err, "Could not save the opening balance."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={inputId} className="text-sm font-medium text-fg-muted">
          Opening balance
        </label>
        <Input
          id={inputId}
          inputMode="decimal"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          disabled={busy}
          className="w-32 text-right tabular-nums"
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
      </div>
      {error ? (
        <p id={errorId} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
