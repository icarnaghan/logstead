import { forwardRef, useState } from "react";
import { cn } from "../../lib/cn";
import {
  formatMoneyDisplay,
  parseMoneyDisplay,
  sanitizeMoneyInput,
} from "../../lib/moneyInput";
import { Input, type InputProps } from "./Input";

export interface MoneyInputProps
  extends Omit<InputProps, "value" | "onChange" | "type" | "inputMode"> {
  /** Canonical text, e.g. "1250.50" or "1250.5" while typing. */
  value: string;
  /** Always receives sanitized canonical text. */
  onValueChange: (value: string) => void;
  allowNegative?: boolean;
}

/**
 * Currency text field: `$` prefix, decimal keypad on touch devices, input
 * sanitized on change/paste. Shows canonical text while focused and a
 * two-decimal formatted value on blur (Requirement 12).
 */
export const MoneyInput = forwardRef<HTMLInputElement, MoneyInputProps>(
  function MoneyInput(
    {
      value,
      onValueChange,
      allowNegative = false,
      className,
      onFocus,
      onBlur,
      ...props
    },
    ref,
  ) {
    const [focused, setFocused] = useState(false);
    const opts = { allowNegative };
    const display = focused ? value : formatMoneyDisplay(value);

    return (
      <div className="relative">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-fg-muted"
        >
          $
        </span>
        <Input
          {...props}
          ref={ref}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          className={cn("w-full pl-7", className)}
          value={display}
          onChange={(e) =>
            onValueChange(sanitizeMoneyInput(e.target.value, opts))
          }
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            const next = parseMoneyDisplay(formatMoneyDisplay(value), opts);
            if (next !== value) onValueChange(next);
            onBlur?.(e);
          }}
        />
      </div>
    );
  },
);
