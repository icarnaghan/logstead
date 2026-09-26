import { useMemo } from "react";
import type { Category, TransactionType } from "../../api/transactions";

interface CategorySelectProps {
  id: string;
  /** Full category catalog from GET /categories. */
  categories: readonly Category[];
  /** Currently selected category id ("" when none). */
  value: string;
  /** Only categories of this kind are offered (income vs. expense). */
  kind: TransactionType;
  onChange: (categoryId: string) => void;
  /** Associates the field with an error message for screen readers. */
  describedBy?: string;
  invalid?: boolean;
}

/**
 * A native `<select>` populated from the Schedule E category catalog
 * (Requirement 7.1, 7.2). Options are filtered to the chosen transaction kind
 * and grouped so the Schedule E line is visible in each label (Requirement
 * 7.3). A native select is used for reliable keyboard/screen-reader support
 * (Requirement 14.4).
 */
export function CategorySelect({
  id,
  categories,
  value,
  kind,
  onChange,
  describedBy,
  invalid,
}: CategorySelectProps) {
  const options = useMemo(
    () => categories.filter((c) => c.kind === kind),
    [categories, kind],
  );

  return (
    <select
      id={id}
      value={value}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(event) => onChange(event.target.value)}
      className="mt-1 block w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <option value="">Select a category…</option>
      {options.map((category) => (
        <option key={category.id} value={category.id}>
          {category.label} (Line {category.schedule_e_line})
        </option>
      ))}
    </select>
  );
}
