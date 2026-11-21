import type { Property } from "../api/properties";
import type { PackageJobList, PackageJobView } from "../api/accountantPackage";
import type { Business, BusinessWithLinks } from "../api/businesses";
import type { Category, Transaction } from "../api/transactions";
import type { DepreciableAsset, ScheduleRow } from "../api/assets";
import type { ItemizedSummary } from "../api/itemized";
import type { Loan, LoanSchedule } from "../api/loans";
import type {
  DashboardSummary,
  TrendsSeries,
  PropertySummary,
} from "../api/dashboard";
import type {
  CombinedScheduleEReport,
  ScheduleEReport,
} from "../api/reports";
import type { ReconciliationSummary } from "../api/carryforward";
import type {
  PortfolioChecklistSummary,
  PropertyChecklistSummary,
  YearEndChecklist,
} from "../api/yearEndChecklist";

/**
 * Canned API responses for the Axe_Suite (`axeRoutes.test.tsx`). Shapes follow
 * the interfaces in `src/api/*`. Ids match `SAMPLE_PARAMS` in the suite.
 */

export const PROPERTY_ID = "11111111-1111-4111-8111-111111111111";
export const BUSINESS_ID = "22222222-2222-4222-8222-222222222222";
const TRANSACTION_ID = "33333333-3333-4333-8333-333333333333";
const ASSET_ID = "44444444-4444-4444-8444-444444444444";
const LOAN_ID = "55555555-5555-4555-8555-555555555555";
const USER_ID = "user-1";
const STAMP = "2024-01-15T12:00:00Z";

export const PROPERTY: Property = {
  id: PROPERTY_ID,
  user_id: USER_ID,
  name: "Maple Street Duplex",
  address_text: "123 Maple Street, Springfield, IL 62701",
  property_type: "Multi-Family",
  created_at: STAMP,
  updated_at: STAMP,
  business_id: BUSINESS_ID,
  details: {
    formatted_address: "123 Maple Street, Springfield, IL 62701",
    city: "Springfield",
    state: "IL",
    zip_code: "62701",
    bedrooms: 4,
    bathrooms: "2",
    living_area_sqft: 2000,
    year_built: 1985,
  },
};

export const BUSINESS: Business = {
  id: BUSINESS_ID,
  user_id: USER_ID,
  legal_name: "Maple Holdings LLC",
  entity_type: "llc",
  ein: "12-3456789",
  formation_state: "IL",
  formation_date: "2020-03-01",
  business_address: "1 Main Street, Springfield, IL 62701",
  tax_year_end: "12-31",
  note: null,
  created_at: STAMP,
  updated_at: STAMP,
};

export const BUSINESS_WITH_LINKS: BusinessWithLinks = {
  ...BUSINESS,
  linked_properties: [{ id: PROPERTY_ID, name: PROPERTY.name }],
};

export const CATEGORIES: Category[] = [
  {
    id: "cat-rent",
    kind: "income",
    label: "Rents received",
    schedule_e_line: "3",
    requires_description: false,
  },
  {
    id: "cat-repairs",
    kind: "expense",
    label: "Repairs",
    schedule_e_line: "14",
    requires_description: false,
  },
  {
    id: "cat-other",
    kind: "expense",
    label: "Other",
    schedule_e_line: "19",
    requires_description: true,
  },
];

export const TRANSACTION: Transaction = {
  id: TRANSACTION_ID,
  property_id: PROPERTY_ID,
  date: "2024-03-10",
  amount: "250.00",
  type: "expense",
  category_id: "cat-repairs",
  description: "Replaced kitchen faucet",
  imported: false,
};

/** Itemized summary for the Repairs page (`/properties/:id/itemized/:categoryId`). */
export const ITEMIZED_SUMMARY: ItemizedSummary = {
  category_id: "cat-repairs",
  label: "Repairs",
  schedule_e_line: 14,
  tax_year: 2024,
  entered_total: "500.00",
  entered_total_rows: [],
  itemized_sum: "250.00",
  itemized_count: 1,
  entries: [{ ...TRANSACTION, itemized: true, notes: null }],
  remainder: "250.00",
  line_total: "500.00",
  line_source: "entered_total",
  total_differs_from_itemized: false,
};

export const ASSET: DepreciableAsset = {
  id: ASSET_ID,
  description: "Roof replacement",
  cost_basis: "12000.00",
  placed_in_service_date: "2023-06-01",
  recovery_period_years: 27.5,
  depreciation_overrides: {},
  created_at: STAMP,
  updated_at: STAMP,
};

export const ASSET_SCHEDULE: ScheduleRow[] = [
  {
    tax_year: 2023,
    amount: "254.55",
    remaining_basis: "11745.45",
    method: "SL",
    convention: "MM",
  },
  {
    tax_year: 2024,
    amount: "436.36",
    remaining_basis: "11309.09",
    method: "SL",
    convention: "MM",
  },
];

export const LOAN: Loan = {
  id: LOAN_ID,
  property_id: PROPERTY_ID,
  description: "Primary mortgage",
  annual_interest_rate: "6.5",
  monthly_payment: "1200.00",
  anchor_balance: "180000.00",
  anchor_date: "2024-01-01",
  extra_principal: "0.00",
  payoff_date: null,
  original_principal: "200000.00",
  closing_date: "2022-01-01",
  include_in_report: true,
  interest_overrides: {},
  remaining_payments: 240,
  next_payment_date: "2024-02-01",
  projected_payoff_date: "2044-01-01",
  payoff_balance: null,
  status: "active",
  created_at: STAMP,
  updated_at: STAMP,
};

export const LOAN_SCHEDULE: LoanSchedule = {
  loan_id: LOAN_ID,
  estimate: false,
  payoff_balance: null,
  payments: [
    {
      number: 1,
      date: "2024-02-01",
      payment: "1200.00",
      interest: "975.00",
      principal: "225.00",
      balance: "179775.00",
    },
    {
      number: 2,
      date: "2024-03-01",
      payment: "1200.00",
      interest: "973.78",
      principal: "226.22",
      balance: "179548.78",
    },
  ],
  yearly: [
    {
      tax_year: 2024,
      payments: 2,
      interest: "1948.78",
      estimated_interest: "1948.78",
      interest_override: null,
      variance: null,
      principal: "451.22",
      total_paid: "2400.00",
      ending_balance: "179548.78",
    },
  ],
};

const PROPERTY_SUMMARY: PropertySummary = {
  property_id: PROPERTY_ID,
  property_name: PROPERTY.name,
  total_income: "24000.00",
  total_expenses: "9000.00",
  net: "15000.00",
};

export const DASHBOARD_SUMMARY: DashboardSummary = {
  tax_year: 2024,
  has_properties: true,
  total_income: "24000.00",
  total_expenses: "9000.00",
  net: "15000.00",
  properties: [PROPERTY_SUMMARY],
  empty_state_prompt: null,
};

export const TRENDS: TrendsSeries = {
  years: [2022, 2023, 2024].map((year, i) => ({
    tax_year: year,
    total_income: `${20000 + i * 2000}.00`,
    total_expenses: `${8000 + i * 500}.00`,
    net: `${12000 + i * 1500}.00`,
    depreciation_total: "436.36",
    properties: [
      {
        property_id: PROPERTY_ID,
        property_name: PROPERTY.name,
        total_income: `${20000 + i * 2000}.00`,
        total_expenses: `${8000 + i * 500}.00`,
        net: `${12000 + i * 1500}.00`,
      },
    ],
  })),
};

export const SCHEDULE_E_REPORT: ScheduleEReport = {
  header: {
    property_id: PROPERTY_ID,
    property_name: PROPERTY.name,
    address: PROPERTY.address_text,
    property_type: "Multi-Family",
    tax_year: 2024,
    fair_rental_days: 365,
    personal_use_days: 0,
  },
  lines: [
    { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
    { line: 14, label: "Repairs", kind: "expense", total: "250.00" },
    { line: 18, label: "Depreciation", kind: "expense", total: "436.36" },
    { line: 19, label: "Other", kind: "expense", total: "100.00" },
  ],
  other_items: [{ description: "Lawn care", amount: "100.00" }],
  totals: {
    total_income: "24000.00",
    total_expenses: "786.36",
    net: "23213.64",
  },
};

export const COMBINED_REPORT: CombinedScheduleEReport = {
  tax_year: 2024,
  properties: [SCHEDULE_E_REPORT],
  totals: SCHEDULE_E_REPORT.totals,
};

export const RECONCILIATION: ReconciliationSummary = {
  years: [
    {
      tax_year: 2023,
      schedule_e_net: "-5000.00",
      expected_carryforward: "5000.00",
      reported_carryforward: "5000.00",
      expected_carry_in: "0.00",
      allowed_loss: "0.00",
      fully_allowed: false,
      status: "ok",
      drift: null,
      carried_from_year: null,
    },
    {
      tax_year: 2024,
      schedule_e_net: "-1000.00",
      expected_carryforward: "6000.00",
      reported_carryforward: null,
      expected_carry_in: "5000.00",
      allowed_loss: "0.00",
      fully_allowed: false,
      status: "unreported",
      drift: null,
      carried_from_year: null,
    },
  ],
  opening_balance: "0.00",
  has_data: true,
  next_year: 2025,
  next_year_expected_carry_in: "6000.00",
  status_tolerance: "1.00",
};

export { PROPERTY_SUMMARY };

const CHECKLIST_COUNTS = { done: 1, needs_attention: 1, not_applicable: 1, total: 3 };

export const YEAR_END_CHECKLIST: YearEndChecklist = {
  property_id: PROPERTY_ID,
  tax_year: 2024,
  thresholds: {
    large_entry_amount: "250.00",
    capital_candidate_amount: "2500.00",
    swing_percent: 50,
    swing_minimum_amount: "500.00",
    anchor_max_age_months: 12,
    summary_year_count: 5,
  },
  counts: CHECKLIST_COUNTS,
  items: [
    {
      id: "income_entered",
      title: "Income entered",
      status: "done",
      reason: "Rents received total 24000.00 for 2024.",
      link: `/properties/${PROPERTY_ID}/transactions?year=2024`,
      details: null,
    },
    {
      id: "depreciation_present",
      title: "Depreciation present",
      status: "needs_attention",
      reason: "No depreciation is recorded for 2024. Review your assets.",
      link: `/properties/${PROPERTY_ID}/assets`,
      details: null,
    },
    {
      id: "loan_interest_confirmed",
      title: "Loan interest confirmed",
      status: "not_applicable",
      reason: "Line 12 is not generated from loans.",
      link: `/properties/${PROPERTY_ID}/loans`,
      details: null,
    },
  ],
};

export const YEAR_END_PROPERTY_SUMMARY: PropertyChecklistSummary = {
  property_id: PROPERTY_ID,
  years: [
    { tax_year: 2024, counts: CHECKLIST_COUNTS },
    { tax_year: 2023, counts: { done: 3, needs_attention: 0, not_applicable: 0, total: 3 } },
  ],
};

export const YEAR_END_PORTFOLIO_SUMMARY: PortfolioChecklistSummary = {
  tax_year: 2024,
  properties: [
    { property_id: PROPERTY_ID, property_name: PROPERTY.name, counts: CHECKLIST_COUNTS },
  ],
};

export const PACKAGE_JOB_ID = "00000000-0000-4000-8000-0000000000f1";

const PACKAGE_JOB_BASE: PackageJobView = {
  id: PACKAGE_JOB_ID,
  status: "queued",
  tax_year: 2024,
  property_ids: [PROPERTY_ID],
  created_at: "2025-01-15T12:00:00Z",
  finished_at: null,
  message: null,
  size_bytes: null,
  sha256: null,
  file_count: null,
  receipt_count: null,
  skipped_receipt_count: null,
  download_url: null,
  download_expires_in_seconds: null,
};

/** A job that is still being prepared. */
export const PACKAGE_JOB_RUNNING: PackageJobView = {
  ...PACKAGE_JOB_BASE,
  status: "running",
};

/** A finished job with a download link and one skipped receipt. */
export const PACKAGE_JOB_COMPLETE: PackageJobView = {
  ...PACKAGE_JOB_BASE,
  status: "complete",
  finished_at: "2025-01-15T12:01:00Z",
  size_bytes: 2_621_440,
  sha256: "a".repeat(64),
  file_count: 9,
  receipt_count: 3,
  skipped_receipt_count: 1,
  download_url: "https://files.example.test/exports/packages/logstead-accountant-package-2024.zip",
  download_expires_in_seconds: 900,
};

/** A job that failed with a fixed, user-safe message. */
export const PACKAGE_JOB_FAILED: PackageJobView = {
  ...PACKAGE_JOB_BASE,
  status: "failed",
  finished_at: "2025-01-15T12:01:00Z",
  message: "The package could not be prepared. Please try again.",
};

/** No packages prepared yet (the idle state). */
export const PACKAGE_LIST_IDLE: PackageJobList = { jobs: [] };
