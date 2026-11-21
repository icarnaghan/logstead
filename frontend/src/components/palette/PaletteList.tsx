import { cn } from "../../lib/cn";
import { HighlightedText } from "../search/HighlightedText";

/** One selectable row of the palette listbox. */
export interface PaletteRow {
  /** Stable key, unique within the list. */
  key: string;
  group: string;
  label: string;
  /** Shortcut hint or unavailable reason, rendered as text. */
  hint?: string;
  /** Unavailable rows stay in the list but do nothing when chosen. */
  disabled?: boolean;
  /** When set, the label is rendered with matches in `mark` elements. */
  highlight?: readonly string[];
  /** Marks a "See all results" row (not counted as a result). */
  seeAll?: boolean;
}

export interface PaletteListProps {
  rows: readonly PaletteRow[];
  /** Index of the highlighted row, or -1 for none. */
  activeIndex: number;
  /** Id prefix that keeps option and group ids unique per palette. */
  idPrefix: string;
  listboxId: string;
  /** Sets `aria-busy` while a search request is in flight. */
  busy?: boolean;
  onHighlight: (index: number) => void;
  onRun: (index: number) => void;
}

/** DOM id of the option at `index` (used for `aria-activedescendant`). */
export function optionId(idPrefix: string, index: number): string {
  return `${idPrefix}-option-${index}`;
}

/**
 * Grouped `listbox` of `option` rows (ui-polish Requirements 4.2, 4.3, 4.10).
 * Rows must already be ordered so each group is contiguous.
 */
export function PaletteList({
  rows,
  activeIndex,
  idPrefix,
  listboxId,
  busy = false,
  onHighlight,
  onRun,
}: PaletteListProps) {
  const groups: { label: string; start: number; count: number }[] = [];
  rows.forEach((row, index) => {
    const last = groups[groups.length - 1];
    if (last && last.label === row.group) last.count += 1;
    else groups.push({ label: row.group, start: index, count: 1 });
  });

  return (
    <div
      id={listboxId}
      role="listbox"
      aria-label="Results"
      aria-busy={busy}
      className="max-h-[50dvh] overflow-y-auto py-1"
    >
      {groups.map((group, g) => {
        const labelId = `${idPrefix}-group-${g}`;
        return (
          <div key={`${g}:${group.label}`} role="group" aria-labelledby={labelId}>
            <div
              id={labelId}
              className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-fg-muted"
            >
              {group.label}
            </div>
            {rows.slice(group.start, group.start + group.count).map((row, i) => {
              const index = group.start + i;
              const active = index === activeIndex;
              return (
                // Options are not focusable by design: DOM focus stays on the
                // combobox and the keyboard is handled there (WAI-ARIA combobox).
                // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/interactive-supports-focus
                <div
                  key={row.key}
                  id={optionId(idPrefix, index)}
                  role="option"
                  aria-selected={active}
                  aria-disabled={row.disabled ? true : undefined}
                  onMouseMove={() => {
                    if (!active) onHighlight(index);
                  }}
                  // Keep DOM focus on the search field.
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => onRun(index)}
                  className={cn(
                    "mx-1 flex cursor-pointer items-center justify-between gap-3 rounded-md px-2 py-2 text-sm",
                    active ? "bg-surface-muted text-fg" : "text-fg",
                    row.disabled && "cursor-not-allowed text-fg-muted",
                  )}
                >
                  <span className="min-w-0 truncate">
                    {row.highlight ? (
                      <HighlightedText text={row.label} tokens={row.highlight} />
                    ) : (
                      row.label
                    )}
                  </span>
                  {row.hint ? (
                    <span className="shrink-0 text-xs text-fg-muted">
                      {row.hint}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
