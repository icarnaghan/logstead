import { test as base, expect, type Page } from "@playwright/test";
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
} from "../src/test/fixtures";
import type { ActivityEvent, ActivityValues } from "../src/api/activity";
import type { Property } from "../src/api/properties";
import type { Transaction } from "../src/api/transactions";
import { API_BASE_URL } from "../playwright.config";
/** Canned history for the default `/activity` routes: a create and a restorable delete. */
export const ACTIVITY_EVENTS: ActivityEvent[] = [
  {
    id: "act-2",
    at: "2024-03-12T15:04:00Z",
    action: "delete",
    entity: "transaction",
    record_id: TRANSACTION.id,
    property_id: PROPERTY.id,
    property_name: PROPERTY.name,
    summary: "Deleted expense: Replaced kitchen faucet",
    before: { amount: TRANSACTION.amount, description: TRANSACTION.description ?? null },
    after: null,
    truncated: false,
    restorable: true,
    restored_as: null,
  },
  {
    id: "act-1",
    at: "2024-03-10T12:00:00Z",
    action: "create",
    entity: "transaction",
    record_id: TRANSACTION.id,
    property_id: PROPERTY.id,
    property_name: PROPERTY.name,
    summary: "Added expense: Replaced kitchen faucet",
    before: null,
    after: { amount: TRANSACTION.amount, description: TRANSACTION.description ?? null },
    truncated: false,
    restorable: false,
    restored_as: null,
  },
];

/** Canned API responses; first matching pattern wins. Unknown paths return []. */
const ID = "[^/]+";
const API_ROUTES: ReadonlyArray<readonly [RegExp, unknown]> = [
  [/^\/categories$/, CATEGORIES],
  [/^\/properties$/, [PROPERTY]],
  [new RegExp(`^/properties/${ID}$`), PROPERTY],
  [new RegExp(`^/properties/${ID}/notes$`), { text: "" }],
  [new RegExp(`^/properties/${ID}/earliest-year$`), { earliest_year: 2022 }],
  [new RegExp(`^/properties/${ID}/transactions$`), [TRANSACTION]],
  [new RegExp(`^/properties/${ID}/itemized/${ID}$`), ITEMIZED_SUMMARY],
  [new RegExp(`^/properties/${ID}/assets$`), [ASSET]],
  [new RegExp(`^/properties/${ID}/assets/${ID}/schedule$`), ASSET_SCHEDULE],
  [new RegExp(`^/properties/${ID}/loans$`), [LOAN]],
  [new RegExp(`^/properties/${ID}/loans/${ID}/schedule$`), LOAN_SCHEDULE],
  [new RegExp(`^/properties/${ID}/report$`), SCHEDULE_E_REPORT],
  [/^\/businesses$/, [BUSINESS]],
  [new RegExp(`^/businesses/${ID}$`), BUSINESS_WITH_LINKS],
  [/^\/dashboard$/, DASHBOARD_SUMMARY],
  [/^\/dashboard\/properties$/, [PROPERTY_SUMMARY]],
  [/^\/dashboard\/trends$/, TRENDS],
  [/^\/reports\/combined$/, COMBINED_REPORT],
  [/^\/carryforward$/, RECONCILIATION],
  [/^\/accountant-packages$/, PACKAGE_LIST_IDLE],
  [new RegExp(`^/accountant-packages/${ID}$`), PACKAGE_JOB_COMPLETE],
  [new RegExp(`^/properties/${ID}/checklist$`), YEAR_END_CHECKLIST],
  [new RegExp(`^/properties/${ID}/checklist/summary$`), YEAR_END_PROPERTY_SUMMARY],
  [/^\/checklist\/summary$/, YEAR_END_PORTFOLIO_SUMMARY],
  [/^\/search$/, { groups: [], truncated: false }],
  [/^\/activity$/, { events: ACTIVITY_EVENTS, next_cursor: null }],
  [new RegExp(`^/properties/${ID}/activity$`), { events: ACTIVITY_EVENTS, next_cursor: null }],
];
export type Theme = "light" | "dark";

/** A request to the mocked API origin, as seen by a {@link ApiHandler}. */
export interface ApiRequest {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
  authorization: string | undefined;
}

/** Return a response to override the canned data, or `undefined` to fall through. */
export type ApiHandler = (req: ApiRequest) => { status?: number; body?: unknown } | undefined;

export interface PrepareOptions {
  /** Seed placeholder session tokens (default true). False starts signed out. */
  authenticated?: boolean;
  /** Stateful override consulted before the canned `API_ROUTES`. */
  handler?: ApiHandler;
}

const CORS_HEADERS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "*",
  "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS",
};

/**
 * Test-only auth bypass: seeds the sessionStorage keys `src/lib/session.ts`
 * reads with placeholder tokens that expire in an hour. The API is mocked, so
 * the tokens are never verified. Production code is untouched.
 */
export async function prepare(
  page: Page,
  theme: Theme,
  { authenticated = true, handler }: PrepareOptions = {},
): Promise<void> {
  await page.addInitScript(
    ([t, seed]) => {
      if (seed) {
        sessionStorage.setItem("logstead.idToken", "e2e-fake-id-token");
        sessionStorage.setItem("logstead.accessToken", "e2e-fake-access-token");
        sessionStorage.setItem("logstead.expiresAt", String(Date.now() + 3_600_000));
      }
      localStorage.setItem("logstead.theme", t);
    },
    [theme, authenticated] as const,
  );
  // Safety net: nothing may leave localhost except the mocked API origin.
  await page.route(
    (url) => url.hostname !== "localhost",
    async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.origin !== API_BASE_URL) {
        await route.abort();
        return;
      }
      if (request.method() === "OPTIONS") {
        await route.fulfill({ status: 204, headers: CORS_HEADERS });
        return;
      }
      const raw = request.postData();
      const override = handler?.({
        method: request.method(),
        path: url.pathname,
        query: url.searchParams,
        body: raw ? (JSON.parse(raw) as unknown) : undefined,
        authorization: request.headers()["authorization"],
      });
      if (override) {
        const status = override.status ?? 200;
        await route.fulfill({
          status,
          contentType: "application/json",
          headers: CORS_HEADERS,
          body: status === 204 ? undefined : JSON.stringify(override.body ?? null),
        });
        return;
      }
      const hit = API_ROUTES.find(([re]) => re.test(url.pathname));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS_HEADERS,
        body: JSON.stringify(hit ? hit[1] : []),
      });
    },
  );
}

/**
 * In-memory stand-in for the properties and transactions endpoints. Like the
 * real API it assigns ids on create, so an Undo (re-create) gets a new id.
 */
export function createStatefulApi(seed: { properties?: Property[]; transactions?: Transaction[] } = {}) {
  const properties: Property[] = [...(seed.properties ?? [])];
  const transactions = new Map<string, Transaction[]>(
    properties.map((p) => [p.id, (seed.transactions ?? []).filter((t) => t.property_id === p.id)]),
  );
  /** Recorded history, newest first, as the activity routes return it. */
  const events: ActivityEvent[] = [];
  let tick = 0;
  const record = (
    action: ActivityEvent["action"],
    t: Transaction,
    extra: Partial<ActivityEvent> = {},
  ): ActivityEvent => {
    const values = (): ActivityValues => ({ amount: t.amount, description: t.description ?? null });
    const label = `${t.type}: ${t.description ?? "Transaction"}`;
    const event: ActivityEvent = {
      id: `evt-${String(++tick).padStart(4, "0")}`,
      at: new Date(Date.UTC(2024, 2, 1, 12, tick)).toISOString(),
      action,
      entity: "transaction",
      record_id: t.id,
      property_id: t.property_id,
      property_name: properties.find((p) => p.id === t.property_id)?.name ?? null,
      summary: `${action === "delete" ? "Deleted" : action === "restore" ? "Restored" : "Added"} ${label}`,
      before: action === "delete" ? values() : null,
      after: action === "delete" ? null : values(),
      truncated: false,
      restorable: action === "delete",
      restored_as: null,
      ...extra,
    };
    events.unshift(event);
    return event;
  };
  /** Every mutating request received, in order (bodies as sent). */
  const writes: Array<{ method: string; path: string; body: unknown }> = [];
  let seq = 0;
  const nextId = () => `00000000-0000-4000-8000-${String(++seq).padStart(12, "0")}`;
  const stamp = "2024-01-15T12:00:00Z";

  const handler: ApiHandler = ({ method, path, query, body }) => {
    if (method !== "GET") writes.push({ method, path, body });
    const activity = /^\/properties\/([^/]+)\/activity$/.exec(path);
    if ((path === "/activity" || activity) && method === "GET") {
      const scope = activity?.[1] ?? query.get("propertyId");
      const rows = events.filter(
        (e) =>
          (!scope || e.property_id === scope) &&
          (!query.get("entity") || e.entity === query.get("entity")) &&
          (!query.get("action") || e.action === query.get("action")),
      );
      return { body: { events: rows, next_cursor: null } };
    }
    const restore = /^\/properties\/([^/]+)\/activity\/([^/]+)\/restore$/.exec(path);
    if (restore && method === "POST") {
      const source = events.find((e) => e.id === restore[2] && e.property_id === restore[1]);
      if (!source) return { status: 404, body: { message: "Not found" } };
      if (source.restored_as) return { status: 409, body: { message: "This event was already restored." } };
      const rows = transactions.get(restore[1]);
      if (!rows) return { status: 404, body: { message: "Not found" } };
      const created: Transaction = {
        id: nextId(),
        property_id: restore[1],
        date: "2024-03-10",
        amount: String(source.before?.amount ?? "0.00"),
        type: "expense",
        category_id: "cat-repairs",
        description: (source.before?.description as string | null) ?? null,
      };
      rows.push(created);
      const at = record("restore", created).at;
      const index = events.findIndex((e) => e.id === source.id);
      events[index] = { ...source, restored_as: created.id };
      return { status: 201, body: { record_id: created.id, event_id: source.id, restored_at: at } };
    }
    if (path === "/properties") {
      if (method === "GET") return { body: properties };
      if (method === "POST") {
        const input = body as { name: string; address_text: string; property_type: string | null };
        const created: Property = {
          id: nextId(),
          user_id: "e2e-user",
          name: input.name,
          address_text: input.address_text,
          property_type: input.property_type,
          created_at: stamp,
          updated_at: stamp,
        };
        properties.push(created);
        transactions.set(created.id, []);
        return { status: 201, body: created };
      }
    }
    const property = /^\/properties\/([^/]+)$/.exec(path);
    if (property && method === "GET") {
      const found = properties.find((p) => p.id === property[1]);
      return found ? { body: found } : { status: 404, body: { message: "Not found" } };
    }
    const list = /^\/properties\/([^/]+)\/transactions$/.exec(path);
    if (list && transactions.has(list[1])) {
      const rows = transactions.get(list[1])!;
      if (method === "GET") return { body: rows };
      if (method === "POST") {
        const input = body as Omit<Transaction, "id" | "property_id">;
        const created: Transaction = { ...input, id: nextId(), property_id: list[1] };
        rows.push(created);
        record("create", created);
        return { status: 201, body: created };
      }
    }
    const one = /^\/properties\/([^/]+)\/transactions\/([^/]+)$/.exec(path);
    if (one && method === "DELETE" && transactions.has(one[1])) {
      const rows = transactions.get(one[1])!;
      const i = rows.findIndex((t) => t.id === one[2]);
      if (i < 0) return { status: 404, body: { message: "Not found" } };
      const [removed] = rows.splice(i, 1);
      record("delete", removed);
      return { status: 204 };
    }
    return undefined;
  };

  return { handler, properties, transactions, writes, events };
}

/** Realistic `GET /search` hits: one transaction (the canned row) and one property. */
export const SEARCH_RESPONSE = {
  query: "faucet",
  truncated: false,
  scanned: 2,
  groups: [
    {
      kind: "property",
      total: 1,
      hits: [
        {
          kind: "property",
          id: PROPERTY.id,
          property_id: PROPERTY.id,
          title: "Faucet Lane Duplex",
          subtitle: PROPERTY.address_text,
          matched_field: "name",
          link: `/properties/${PROPERTY.id}`,
          amount: null,
          date: null,
        },
      ],
    },
    {
      kind: "transaction",
      total: 1,
      hits: [
        {
          kind: "transaction",
          id: TRANSACTION.id,
          property_id: PROPERTY.id,
          title: TRANSACTION.description,
          subtitle: PROPERTY.name,
          matched_field: "description",
          link: `/properties/${PROPERTY.id}/transactions?focus=${TRANSACTION.id}`,
          amount: TRANSACTION.amount,
          date: TRANSACTION.date,
        },
      ],
    },
  ],
};

/** Handler override that answers `GET /search` with {@link SEARCH_RESPONSE} (or `body`). */
export const searchHandler =
  (body: unknown = SEARCH_RESPONSE): ApiHandler =>
  ({ method, path }) =>
    method === "GET" && path === "/search" ? { body } : undefined;

export const test = base;
export { expect };
