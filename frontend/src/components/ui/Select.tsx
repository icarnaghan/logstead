import { forwardRef } from "react";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  /** Marks the field as invalid: sets aria-invalid and a danger border. */
  invalid?: boolean;
}

const BASE_CLASSES =
  "rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg";

/**
 * Shared styled native `<select>` primitive with token-only styling and the
 * canonical focus ring, consistent with the Input primitive (Requirements 1.3,
 * 8.5). Native keeps the platform keyboard/assistive-technology behavior,
 * matching the deliberate choice already documented in CategorySelect.
 * `invalid` sets aria-invalid and a danger border.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select({ invalid = false, className, ...props }, ref) {
    return (
      <select
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
