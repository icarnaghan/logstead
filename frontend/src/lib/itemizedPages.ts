/**
 * Frontend definitions for itemized-expense pages (Requirements 11.5, 11.6).
 *
 * The generic `ItemizedExpensesPage` takes one of these definitions, so a later
 * category reuses the same page with a different entry. Only `repairs` exists
 * in this release; no other category gets a page or tab.
 */
export interface ItemizedPageDefinition {
  /** Category id sent to the itemized API, e.g. "repairs". */
  categoryId: string;
  /** Tab / page title, e.g. "Repairs". */
  tabLabel: string;
  /** Schedule E line the category feeds, e.g. 14. */
  line: number;
  /** Singular noun for one entry, e.g. "repair". */
  entryNoun: string;
  /** Page intro text. */
  description: string;
  /** Show the note linking to Assets for capital improvements. */
  capitalImprovementNote: boolean;
}

export const ITEMIZED_PAGES = {
  repairs: {
    categoryId: "repairs",
    tabLabel: "Repairs",
    line: 14,
    entryNoun: "repair",
    description:
      "Record the year's repairs total, or list individual repairs. Schedule E line 14 uses the entered total when one exists, and the sum of your itemized repairs otherwise.",
    capitalImprovementNote: true,
  },
} as const satisfies Record<string, ItemizedPageDefinition>;
