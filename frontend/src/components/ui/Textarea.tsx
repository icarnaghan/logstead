import { forwardRef } from "react";
import { cn } from "../../lib/cn";
import { FOCUS_RING } from "./focusRing";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** Marks the field as invalid: sets aria-invalid and a danger border. */
  invalid?: boolean;
}

const BASE_CLASSES =
  "rounded-md border border-border-strong bg-surface px-3 py-2 text-sm max-md:text-base text-fg max-md:min-h-11";

/**
 * Shared multi-line text primitive mirroring Input: token-only styling, the
 * canonical focus ring, and a 44px minimum touch target on small viewports
 * (Requirements 6.1, 6.4, 6.7). `invalid` sets aria-invalid and a danger border.
 */
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea({ invalid = false, className, ...props }, ref) {
    return (
      <textarea
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
