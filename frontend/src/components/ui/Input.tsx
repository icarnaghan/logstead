import { forwardRef } from "react";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Marks the field as invalid: sets aria-invalid and a danger border. */
  invalid?: boolean;
}

const BASE_CLASSES =
  "rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg";

/**
 * Shared text-input primitive with token-only styling and the canonical focus
 * ring, mirroring the existing form-field styling in TransactionForm/AssetForm
 * (Requirements 1.3, 8.1). `invalid` sets aria-invalid and a danger border.
 */
export const Input = forwardRef<HTMLInputElement, InputProps>(
  function Input({ invalid = false, className, ...props }, ref) {
    return (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          BASE_CLASSES,
          invalid && "border-danger",
          FOCUS_RING,
          className,
        )}
        {...props}
      />
    );
  },
);
