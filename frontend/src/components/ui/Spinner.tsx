import { cn } from "../../lib/cn";

export interface SpinnerProps {
  className?: string;
}

/**
 * Decorative spinner (Requirement 3.1). Always hidden from assistive tech, so
 * pair it with a text or `aria-busy` cue. Inherits color from `currentColor`.
 */
export function Spinner({ className }: SpinnerProps) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 24 24"
      fill="none"
      className={cn("h-4 w-4 animate-spin", className)}
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="3"
        className="opacity-25"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}
