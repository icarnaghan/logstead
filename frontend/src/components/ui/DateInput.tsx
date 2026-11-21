import { forwardRef, useCallback, useRef } from "react";
import { cn } from "../../lib/cn";
import { todayLocal } from "../../lib/dateInput";
import { Button } from "./Button";
import { Input, type InputProps } from "./Input";

export interface DateInputProps extends Omit<InputProps, "type"> {
  /** Called with a "YYYY-MM-DD" string (or "" when cleared). */
  onValueChange: (value: string) => void;
  /** Show the "Today" shortcut button. Defaults to true. */
  showToday?: boolean;
}

/**
 * `Input type="date"` with a ghost "Today" button beside it. Activating the
 * button sets the local calendar date and moves focus to the input
 * (Requirements 12.8, 12.9). FormField control props (id, invalid, aria-*)
 * are forwarded to the input.
 */
export const DateInput = forwardRef<HTMLInputElement, DateInputProps>(
  function DateInput(
    { onValueChange, showToday = true, onChange, className, ...props },
    ref,
  ) {
    const inputRef = useRef<HTMLInputElement | null>(null);

    const setRefs = useCallback(
      (node: HTMLInputElement | null) => {
        inputRef.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      },
      [ref],
    );

    const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange?.(event);
      onValueChange(event.target.value);
    };

    const handleToday = () => {
      onValueChange(todayLocal());
      inputRef.current?.focus();
    };

    return (
      <div className="flex items-center gap-2">
        <Input
          {...props}
          ref={setRefs}
          type="date"
          onChange={handleChange}
          className={cn("min-w-0 flex-1", className)}
        />
        {showToday && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleToday}
            disabled={props.disabled || props.readOnly}
          >
            Today
          </Button>
        )}
      </div>
    );
  },
);
