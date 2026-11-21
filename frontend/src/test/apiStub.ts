import {
  ASSET,
  ASSET_SCHEDULE,
  BUSINESS,
  BUSINESS_WITH_LINKS,
  CATEGORIES,
  COMBINED_REPORT,
  DASHBOARD_SUMMARY,
  ITEMIZED_SUMMARY,
  LOAN,
  LOAN_SCHEDULE,
  PACKAGE_JOB_COMPLETE,
  PACKAGE_LIST_IDLE,
  PROPERTY,
  PROPERTY_SUMMARY,
  RECONCILIATION,
  SCHEDULE_E_REPORT,
  TRANSACTION,
  TRENDS,
  YEAR_END_CHECKLIST,
  YEAR_END_PORTFOLIO_SUMMARY,
  YEAR_END_PROPERTY_SUMMARY,
} from "./fixtures";

/**
 * Fetch stub for the Axe_Suite.
 *
 * `ApiClient` binds `globalThis.fetch` when it is constructed (at module load),
 * so the stub installs itself as soon as this module is evaluated. Import it
 * before any module that reaches `apiClient`.
 *
 * Paths are matched against the URL pathname. The first matching pattern wins,
 * so list specific patterns before general ones. A path with no pattern returns
 * an empty array, which pages render as an empty state rather than crashing.
 */

const ID = "[^/]+";

export interface StubRoute {
  readonly pattern: RegExp;
  readonly body: unknown;
}

export const STUB_ROUTES: readonly StubRoute[] = [
  { pattern: /^\/categories$/, body: CATEGORIES },
  { pattern: /^\/properties$/, body: [PROPERTY] },
  { pattern: new RegExp(`^/properties/${ID}$`), body: PROPERTY },
  { pattern: new RegExp(`^/properties/${ID}/notes$`), body: { text: "" } },
  {
    pattern: new RegExp(`^/properties/${ID}/earliest-year$`),
    body: { earliest_year: 2022 },
  },
  {
    pattern: new RegExp(`^/properties/${ID}/transactions$`),
    body: [TRANSACTION],
  },
  {
    pattern: new RegExp(`^/properties/${ID}/itemized/${ID}$`),
    body: ITEMIZED_SUMMARY,
  },
  { pattern: new RegExp(`^/properties/${ID}/assets$`), body: [ASSET] },
  {
    pattern: new RegExp(`^/properties/${ID}/assets/${ID}/schedule$`),
    body: ASSET_SCHEDULE,
  },
  { pattern: new RegExp(`^/properties/${ID}/loans$`), body: [LOAN] },
  {
    pattern: new RegExp(`^/properties/${ID}/loans/${ID}/schedule$`),
    body: LOAN_SCHEDULE,
  },
  { pattern: new RegExp(`^/properties/${ID}/report$`), body: SCHEDULE_E_REPORT },
  { pattern: /^\/businesses$/, body: [BUSINESS] },
  { pattern: new RegExp(`^/businesses/${ID}$`), body: BUSINESS_WITH_LINKS },
  { pattern: /^\/dashboard$/, body: DASHBOARD_SUMMARY },
  { pattern: /^\/dashboard\/properties$/, body: [PROPERTY_SUMMARY] },
  { pattern: /^\/dashboard\/trends$/, body: TRENDS },
  { pattern: /^\/reports\/combined$/, body: COMBINED_REPORT },
  { pattern: /^\/carryforward$/, body: RECONCILIATION },
  { pattern: /^\/accountant-packages$/, body: PACKAGE_LIST_IDLE },
  {
    pattern: new RegExp(`^/accountant-packages/${ID}$`),
    body: PACKAGE_JOB_COMPLETE,
  },
  {
    pattern: new RegExp(`^/properties/${ID}/checklist$`),
    body: YEAR_END_CHECKLIST,
  },
  {
    pattern: new RegExp(`^/properties/${ID}/checklist/summary$`),
    body: YEAR_END_PROPERTY_SUMMARY,
  },
  { pattern: /^\/activity$/, body: { events: [], next_cursor: null } },
  {
    pattern: new RegExp(`^/properties/${ID}/activity$`),
    body: { events: [], next_cursor: null },
  },
  {
    pattern: /^\/search$/,
    body: {
      query: "oak",
      truncated: false,
      scanned: 1,
      groups: [
        {
          kind: "property",
          total: 1,
          hits: [
            {
              kind: "property",
              id: PROPERTY.id,
              property_id: PROPERTY.id,
              title: "Oak Street Duplex",
              subtitle: PROPERTY.address_text,
              matched_field: "name",
              link: `/properties/${PROPERTY.id}`,
              amount: null,
              date: null,
            },
          ],
        },
      ],
    },
  },
  { pattern: /^\/checklist\/summary$/, body: YEAR_END_PORTFOLIO_SUMMARY },
];

export function resolveStubBody(pathname: string): unknown {
  for (const route of STUB_ROUTES) {
    if (route.pattern.test(pathname)) return route.body;
  }
  return [];
}

function pathnameOf(input: RequestInfo | URL): string {
  const raw =
    typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
  return new URL(raw, "http://localhost").pathname;
}

export const stubFetch: typeof fetch = async (input) => {
  const body = resolveStubBody(pathnameOf(input));
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
};

let original: typeof fetch | undefined;

export function installApiStub(): void {
  if (original === undefined) original = globalThis.fetch;
  globalThis.fetch = stubFetch;
}

export function uninstallApiStub(): void {
  if (original !== undefined) globalThis.fetch = original;
  original = undefined;
}

installApiStub();
