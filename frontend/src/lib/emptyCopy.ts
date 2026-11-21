/**
 * Empty-state copy, one entry per page (ui-polish Requirements 25.1, 25.6).
 *
 * Each description says what the page records and how it reaches Schedule E.
 * It gives no tax advice and never says what the user should report.
 */
export interface EmptyCopyEntry {
  title: string;
  description: string;
  /** Label of the primary action (the page decides what it does). */
  primaryLabel: string;
}

export type EmptyCopyKey =
  | "transactions"
  | "repairs"
  | "assets"
  | "loans"
  | "properties"
  | "reports"
  | "combinedReports";

export const EMPTY_COPY: Record<EmptyCopyKey, EmptyCopyEntry> = {
  transactions: {
    title: "No transactions yet",
    description:
      "Transactions record the income and expenses for this property. Logstead sorts them by Schedule E line and totals them in your reports.",
    primaryLabel: "Add transaction",
  },
  repairs: {
    title: "No repairs yet",
    description:
      "Repairs record itemized work on this property, such as a parts and labor list. Logstead adds each repair to the Schedule E repairs total.",
    primaryLabel: "Add repair",
  },
  assets: {
    title: "No assets yet",
    description:
      "Assets record larger items with a cost, a date placed in service and a recovery period. Logstead calculates the yearly depreciation amount and carries it to Schedule E.",
    primaryLabel: "Add asset",
  },
  loans: {
    title: "No loans yet",
    description:
      "Loans record the balance, rate and payments on a property loan. Logstead splits each payment into principal and interest and carries the interest to Schedule E.",
    primaryLabel: "Add loan",
  },
  properties: {
    title: "No properties yet",
    description:
      "Each property records its own transactions, repairs, assets and loans. Logstead builds a separate Schedule E report for each one.",
    primaryLabel: "Add property",
  },
  reports: {
    title: "No data for this year",
    description:
      "Reports are built from the transactions, assets and loans recorded for the selected year. Add records or import a Schedule E to fill this page.",
    primaryLabel: "Go to Transactions",
  },
  combinedReports: {
    title: "No data for this year",
    description:
      "Combined reports add up the Schedule E figures recorded across your properties for the selected year. Add records or import a Schedule E to fill this page.",
    primaryLabel: "Go to Transactions",
  },
};

/** Secondary link label shared by the Reports pages. */
export const IMPORT_LINK_LABEL = "Import a Schedule E";

/** Secondary link label shown only while the user owns no property. */
export const SAMPLE_DATA_LINK_LABEL = "Explore with sample data";
