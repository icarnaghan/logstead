// Pure sort helpers for ResponsiveTable (Requirement 20).

export type SortDirection = "asc" | "desc";
export type SortState = { key: string; direction: SortDirection } | null;
export type SortType = "text" | "number" | "date";

type SortValue = string | number | null | undefined;

/** Cycle: other key -> asc, asc -> desc, desc -> none. */
export function nextSortState(current: SortState, key: string): SortState {
  if (!current || current.key !== key) return { key, direction: "asc" };
  if (current.direction === "asc") return { key, direction: "desc" };
  return null;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;

function isMissing(value: SortValue): boolean {
  return value === null || value === undefined || (typeof value === "number" && Number.isNaN(value));
}

function compareValues(a: string | number, b: string | number, type: SortType): number {
  if (type === "number") {
    const na = typeof a === "number" ? a : Number(a);
    const nb = typeof b === "number" ? b : Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return na < nb ? -1 : na > nb ? 1 : 0;
  } else if (type === "date") {
    const sa = String(a);
    const sb = String(b);
    if (ISO_DATE.test(sa) && ISO_DATE.test(sb)) return sa < sb ? -1 : sa > sb ? 1 : 0;
    const da = Date.parse(sa);
    const db = Date.parse(sb);
    if (!Number.isNaN(da) && !Number.isNaN(db)) return da < db ? -1 : da > db ? 1 : 0;
  }
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/**
 * Stable sort by the state's column. Returns a new array. A null state keeps
 * the input order. Missing values sort last in both directions; ties keep
 * their original relative order (index-decorated, engine independent).
 */
export function sortRows<R>(
  rows: readonly R[],
  state: SortState,
  get: (row: R, key: string) => SortValue,
  type: (key: string) => SortType,
): R[] {
  if (!state) return rows.slice();
  const { key, direction } = state;
  const sortType = type(key);
  const sign = direction === "desc" ? -1 : 1;

  const decorated = rows.map((row, index) => ({ row, index, value: get(row, key) }));
  decorated.sort((x, y) => {
    const xm = isMissing(x.value);
    const ym = isMissing(y.value);
    if (xm || ym) {
      if (xm && ym) return x.index - y.index;
      return xm ? 1 : -1;
    }
    const c = compareValues(x.value as string | number, y.value as string | number, sortType);
    return c !== 0 ? sign * c : x.index - y.index;
  });
  return decorated.map((d) => d.row);
}
