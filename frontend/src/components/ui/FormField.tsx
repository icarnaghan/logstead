import { useId } from "react";
import { cn } from "../../lib/cn";

/** Props a FormField hands to its control via the render-prop. */
export interface FieldControlProps {
  id: string;
  /** Consumed by Input, Select, Textarea, MoneyInput, DateInput. */
  invalid?: boolean;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  "aria-required"?: true;
}

export interface FormFieldProps {
  label: React.ReactNode;
  children: (control: FieldControlProps) => React.ReactNode;
  hint?: React.ReactNode;
  error?: string | null;
  required?: boolean;
  /** Generated with useId when omitted. */
  id?: string;
  hintId?: string;
  errorId?: string;
  className?: string;
}

/**
 * Label + control + hint + error wrapper that wires htmlFor, aria-describedby,
 * aria-required and aria-invalid (Requirements 6.1-6.6). aria-invalid is set
 * only while an error exists.
 */
export function FormField({
  label,
  children,
  hint,
  error,
  required = false,
  id,
  hintId,
  errorId,
  className,
}: FormFieldProps) {
  const generated = useId();
  const controlId = id ?? `${generated}-control`;
  const resolvedHintId = hintId ?? `${generated}-hint`;
  const resolvedErrorId = errorId ?? `${generated}-error`;

  const hasHint = hint !== undefined && hint !== null && hint !== false && hint !== "";
  const hasError = typeof error === "string" && error.length > 0;

  const describedBy =
    [hasHint ? resolvedHintId : null, hasError ? resolvedErrorId : null]
      .filter((v): v is string => v !== null)
      .join(" ") || undefined;

  const control: FieldControlProps = {
    id: controlId,
    "aria-describedby": describedBy,
    ...(required ? { "aria-required": true as const } : {}),
    ...(hasError ? { "aria-invalid": true as const, invalid: true } : {}),
  };

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label htmlFor={controlId} className="text-sm font-medium text-fg">
        {label}
        {required ? (
          <span aria-hidden="true" className="text-danger">
            {" *"}
          </span>
        ) : null}
      </label>
      {hasHint ? (
        <p id={resolvedHintId} className="text-small text-fg-muted">
          {hint}
        </p>
      ) : null}
      {children(control)}
      {hasError ? (
        <p id={resolvedErrorId} role="alert" className="text-small text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
