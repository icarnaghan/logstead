import type { ChangeEvent, FormEvent, ReactNode } from "react";
import { useEffect, useState } from "react";
import type { DepreciationOverrides, ScheduleRow } from "../../api/assets";
import { formatMoneyWholeDollars, toMoneyString } from "../../lib/money";
import { Input } from "../ui/Input";
import { ResponsiveTable } from "../ui/ResponsiveTable";
import type {
  ResponsiveTableColumn,
  ResponsiveTableRow,
} from "../ui/ResponsiveTable";

interface ScheduleTableProps {
  /** Accessible caption / heading describing which asset this schedule is for. */
  caption: string;
  rows: ScheduleRow[];
  /**
   * The current per-year override map, used to MARK which tax years are pinned
   * to a filed value rather than the computed one (Requirement 7.1). Keys are
   * tax-year strings; values are two-decimal money strings. Absent/empty means
   * no overrides, and the table renders exactly as today (Requirement 7.3).
   */
  overrides?: DepreciationOverrides;
  /**
   * Called when the user submits a new override for a tax year (`amount` is a
   * two-decimal money string) or clears it (`amount` is `null`). The hosting
   * page owns persistence via the asset update path (Requirement 6.2, 6.3).
   */
  onOverrideChange?: (taxYear: number, amount: string | null) => void;
  /**
   * Inline validation messages keyed by tax-year string, surfaced next to the
   * offending year's control when the service rejects an override
   * (Requirement 6.4).
   */
  overrideErrors?: Record<string, string>;
  /**
   * When `false` or absent, the table renders exactly as today (read-only). When
   * `true`, each row gains an override input and a Clear control (Requirement 6.1).
   */
  editable?: boolean;
}

/**
 * Renders a depreciable asset's year-by-year straight-line / mid-month
 * depreciation schedule as an accessible numeric table (Requirement 9.4), and
 * — when {@link ScheduleTableProps.editable} — lets the single user pin a
 * tax year to a value from a filed return (Requirements 6, 7).
 *
 * This is deliberately a data table (year, depreciation amount, remaining
 * basis) and never a chart: the initial release is numbers-and-forms only.
 *
 * Because the depreciation schedule mirrors a filed Form 4562, the displayed
 * per-year amount and remaining-basis figures render through
 * {@link formatMoneyWholeDollars} (Requirement 11.2) with `tabular-nums`
 * alignment (Requirement 10.1). The override INPUT, by contrast, shows and
 * accepts cent precision (the raw two-decimal string from the overrides map),
 * because the user is entering an exact filed amount — it is never rounded.
 * All override amounts are handled as money strings through
 * {@link toMoneyString}; no floating-point arithmetic is introduced
 * (Requirement 6.5).
 */
export function ScheduleTable({
  caption,
  rows,
  overrides,
  onOverrideChange,
  overrideErrors,
  editable = false,
}: ScheduleTableProps) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-fg-subtle">
        No depreciation schedule is available for this asset.
      </p>
    );
  }

  const overrideMap = overrides ?? {};
  const errorMap = overrideErrors ?? {};

  const columns: ResponsiveTableColumn[] = [
    { key: "tax_year", header: "Tax year", rowHeader: true },
    { key: "amount", header: "Depreciation amount", numeric: true },
    { key: "remaining_basis", header: "Remaining basis", numeric: true },
    ...(editable ? [{ key: "override", header: "Override" }] : []),
  ];

  const tableRows: ResponsiveTableRow[] = rows.map((row) => {
    const yearKey = String(row.tax_year);
    const overrideValue = overrideMap[yearKey];
    const isOverridden = overrideValue !== undefined;
    const cells: Record<string, ReactNode> = {
      tax_year: row.tax_year,
      amount: (
        <>
          {formatMoneyWholeDollars(row.amount)}
          {isOverridden ? <OverrideMarker taxYear={row.tax_year} /> : null}
        </>
      ),
      remaining_basis: formatMoneyWholeDollars(row.remaining_basis),
    };
    if (editable) {
      cells.override = (
        <OverrideControl
          taxYear={row.tax_year}
          value={overrideValue}
          error={errorMap[yearKey]}
          onOverrideChange={onOverrideChange}
        />
      );
    }
    return { id: yearKey, cells };
  });

  return <ResponsiveTable caption={caption} columns={columns} rows={tableRows} />;
}

/**
 * The textual {@link OverrideMarker} (Requirement 7.1) plus its one-line note
 * (Requirement 7.2). The marker is a visible text badge — never color alone —
 * so a screen-reader user and a sighted reader both learn the year is pinned.
 */
function OverrideMarker({ taxYear }: { taxYear: number }) {
  return (
    <div className="mt-1 text-right">
      <span className="inline-block rounded border border-border px-1.5 py-0.5 text-xs font-medium text-fg-muted">
        Filed value
      </span>
      <p className="mt-0.5 text-xs font-normal text-fg-subtle">
        {taxYear} is pinned to reproduce the amount from a filed return rather
        than the computed value.
      </p>
    </div>
  );
}

/**
 * Per-year override entry for the editable schedule (Requirement 6.1, 6.3). The
 * input is a money STRING field (cent precision, not rounded), submitted on
 * blur / Enter via {@link ScheduleTableProps.onOverrideChange}. The Clear
 * control sends `null` to revert the year to its computed value.
 *
 * Validation messages from the service are rendered inline (Requirement 6.4).
 */
function OverrideControl({
  taxYear,
  value,
  error,
  onOverrideChange,
}: {
  taxYear: number;
  value: string | undefined;
  error: string | undefined;
  onOverrideChange?: (taxYear: number, amount: string | null) => void;
}) {
  // The input echoes the exact two-decimal filed amount at cent precision; it is
  // deliberately NOT rounded through the whole-dollar formatter.
  const [draft, setDraft] = useState<string>(value ?? "");
  const baseId = `schedule-${taxYear}`;
  const inputId = `${baseId}-override`;
  const errorId = `${baseId}-override-error`;
  const hasOverride = value !== undefined;

  // Keep the field in sync when the persisted override changes underneath us
  // (e.g. after the page reloads the schedule following a save or clear).
  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  function submit() {
    const trimmed = draft.trim();
    const next = trimmed === "" ? null : toMoneyString(trimmed);
    onOverrideChange?.(taxYear, next);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setDraft(event.target.value);
  }

  function handleClear() {
    setDraft("");
    onOverrideChange?.(taxYear, null);
  }

  return (
    <form className="flex flex-col gap-1" onSubmit={handleSubmit}>
      <div className="flex items-center gap-2">
        <label htmlFor={inputId} className="sr-only">
          Depreciation override for {taxYear}
        </label>
        <Input
          id={inputId}
          type="text"
          inputMode="decimal"
          className="w-28 text-right tabular-nums"
          value={draft}
          onChange={handleChange}
          onBlur={submit}
          placeholder="0.00"
          invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
        />
        <button
          type="button"
          className="relative rounded border border-border px-2 py-1 text-xs text-fg-muted before:absolute before:-inset-2 before:content-[''] disabled:opacity-50"
          onClick={handleClear}
          disabled={!hasOverride && draft.trim() === ""}
          aria-label={`Clear depreciation override for ${taxYear}`}
        >
          Clear
        </button>
      </div>
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </form>
  );
}
