interface TaxYearFilterProps {
  /** Selected tax year, or null for "All years". */
  value: number | null;
  /** Candidate years to offer (typically recent years). */
  years: readonly number[];
  onChange: (taxYear: number | null) => void;
}

/**
 * Tax-year filter for the transaction list (Requirement 5.5). Selecting a year
 * restricts the list to transactions in that year; "All years" clears the
 * filter. Rendered as a labelled native select for keyboard/AT support.
 */
export function TaxYearFilter({ value, years, onChange }: TaxYearFilterProps) {
  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="tax-year-filter"
        className="text-sm font-medium text-fg-muted"
      >
        Tax year
      </label>
      <select
        id="tax-year-filter"
        value={value === null ? "all" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === "all" ? null : Number(raw));
        }}
        className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <option value="all">All years</option>
        {years.map((year) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
      </select>
    </div>
  );
}
