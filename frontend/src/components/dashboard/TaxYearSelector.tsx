import { useId } from "react";
import { Select } from "../ui";

interface TaxYearSelectorProps {
  /** The currently selected tax year. */
  value: number;
  /** Selectable years, newest first. */
  years: readonly number[];
  /** Called with the newly selected year (Requirement 11.3). */
  onChange: (year: number) => void;
}

/**
 * Tax-year selector for the dashboard (Requirement 11.3).
 *
 * A labelled native `<select>` so it is keyboard- and screen-reader-accessible
 * (Requirement 14.4). Changing the year re-derives every dashboard figure for
 * that year.
 */
export function TaxYearSelector({ value, years, onChange }: TaxYearSelectorProps) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor={id} className="text-sm font-medium text-fg-muted">
        Tax year
      </label>
      <Select
        id={id}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      >
        {years.map((year) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
      </Select>
    </div>
  );
}
