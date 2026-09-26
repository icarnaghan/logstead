import { useMemo } from "react";
import type { Category, TransactionType } from "../../api/transactions";
import { Select } from "../ui";

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
    <Select
      id={id}
      value={value}
      invalid={invalid}
      aria-describedby={describedBy}
      onChange={(event) => onChange(event.target.value)}
      className="mt-1 block w-full"
    >
      <option value="">Select a category…</option>
      {options.map((category) => (
        <option key={category.id} value={category.id}>
          {category.label} (Line {category.schedule_e_line})
        </option>
      ))}
    </Select>
  );
}
