/**
 * Schedule E Part I line definitions for the guided import form.
 *
 * The import form presents one money input per importable Schedule E Part I
 * line: income lines 3-4, expense lines 5-17, and Line 19 ("Other"). Line 18
 * (Depreciation) is intentionally absent — depreciation is never imported, so
 * the form never offers a field for it (Req 1.4, 5.1).
 *
 * No shared line-label map exists on the frontend (reports carry server-sent
 * labels, and the category catalog lives on the backend), so the human-readable
 * labels are defined here, mirroring the IRS Schedule E Part I line names.
 */

/** One importable Schedule E Part I line: its number and human-readable label. */
export interface ScheduleELineDef {
  /** Schedule E Part I line number (3-4 income, 5-17 + 19 expense). */
  line: number;
  /** Human-readable line label shown beside the money input. */
  label: string;
  /** Whether this line is income (3-4) or an expense (5-17, 19). */
  kind: "income" | "expense";
  /** True for Line 19 ("Other"), which carries a free-text description. */
  isOther?: boolean;
}

/** Income lines 3-4. */
export const INCOME_LINES: ScheduleELineDef[] = [
  { line: 3, label: "Rents received", kind: "income" },
  { line: 4, label: "Royalties", kind: "income" },
];

/** Expense lines 5-17 plus Line 19 "Other" (Line 18 Depreciation is omitted). */
export const EXPENSE_LINES: ScheduleELineDef[] = [
  { line: 5, label: "Advertising", kind: "expense" },
  { line: 6, label: "Auto and travel", kind: "expense" },
  { line: 7, label: "Cleaning and maintenance", kind: "expense" },
  { line: 8, label: "Commissions", kind: "expense" },
  { line: 9, label: "Insurance", kind: "expense" },
  { line: 10, label: "Legal and professional fees", kind: "expense" },
  { line: 11, label: "Management fees", kind: "expense" },
  { line: 12, label: "Mortgage interest", kind: "expense" },
  { line: 13, label: "Other interest", kind: "expense" },
  { line: 14, label: "Repairs", kind: "expense" },
  { line: 15, label: "Supplies", kind: "expense" },
  { line: 16, label: "Taxes", kind: "expense" },
  { line: 17, label: "Utilities", kind: "expense" },
  { line: 19, label: "Other", kind: "expense", isOther: true },
];

/** Every importable line in form order (income first, then expenses). */
export const ALL_LINES: ScheduleELineDef[] = [...INCOME_LINES, ...EXPENSE_LINES];

/** The Line 19 ("Other") definition, which requires a description. */
export const OTHER_LINE = EXPENSE_LINES.find((l) => l.isOther)!;
