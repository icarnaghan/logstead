import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { activityApi, ActivityApi, type ActivityEvent } from "../api/activity";
import { TransactionsApi, type Transaction } from "../api/transactions";
import { ShellPropertiesProvider } from "../components/ShellPropertiesContext";
import { ToastProvider } from "../components/ui";
import { ApiClient } from "../lib/apiClient";
import ActivityPage from "./ActivityPage";
import TransactionsPage from "./TransactionsPage";

/**
 * Toast Undo stays client-side (Requirements 17.14, 23.6): it re-creates the
 * record through the create route, never the restore route, and the history
 * then shows an ordinary `create` event beside the `delete` event, unlinked.
 */

vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));
vi.mock("../api/assets", () => ({
  listAssets: vi.fn().mockResolvedValue([]),
}));

const ORIGINAL: Transaction = {
  id: "t-old",
  property_id: "p1",
  date: "2024-03-10",
  amount: "250.00",
  type: "expense",
  category_id: "repairs",
  description: "Replaced faucet",
};

/** Stateful in-memory API recording every request, like the real routes do. */
function createFakeServer() {
  let rows: Transaction[] = [{ ...ORIGINAL }];
  let events: ActivityEvent[] = [];
  let seq = 0;
  const calls: Array<{ method: string; path: string }> = [];
  const record = (action: "create" | "delete", t: Transaction) => {
    events = [
      {
        id: `e${++seq}`,
        at: new Date(2024, 2, 10, 12, seq).toISOString(),
        action,
        entity: "transaction",
        record_id: t.id,
        property_id: "p1",
        property_name: "Oak House",
        summary: `${action === "create" ? "Added" : "Deleted"} ${t.description}`,
        before: action === "delete" ? { amount: t.amount } : null,
        after: action === "create" ? { amount: t.amount } : null,
        truncated: false,
        restorable: action === "delete",
        restored_as: null,
      },
      ...events,
    ];
  };
  const json = (status: number, body: unknown) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  const fetchImpl: typeof fetch = async (input, init) => {
    const method = init?.method ?? "GET";
    const path = new URL(String(input), "http://x.invalid").pathname;
    calls.push({ method, path });
    if (path === "/categories")
      return json(200, [
        {
          id: "repairs",
          kind: "expense",
          label: "Repairs",
          schedule_e_line: "14",
          requires_description: false,
        },
      ]);
    if (/\/transactions\/[^/]+\/(documents|receipts)$/.test(path))
      return json(200, []);
    if (path === "/properties/p1/transactions") {
      if (method === "POST") {
        const input = JSON.parse(String(init?.body)) as Omit<Transaction, "id">;
        const created = { ...input, id: "t-new", property_id: "p1" } as Transaction;
        rows = [created];
        record("create", created);
        return json(201, created);
      }
      return json(200, rows);
    }
    if (path === "/properties/p1/transactions/t-old" && method === "DELETE") {
      record("delete", rows[0]);
      rows = [];
      return json(204, null);
    }
    if (path === "/activity" || path === "/properties/p1/activity")
      return json(200, { events, next_cursor: null });
    return json(404, { message: "Not found" });
  };
  return { fetchImpl, calls };
}

afterEach(() => vi.restoreAllMocks());

describe("toast Undo and the activity history", () => {
  it("re-creates through the create route, never restore, and logs create beside delete", async () => {
    const server = createFakeServer();
    const client = new ApiClient({
      baseUrl: "http://api.invalid",
      getAuthToken: () => "t",
      fetchImpl: server.fetchImpl,
    });
    const transactions = new TransactionsApi(client, server.fetchImpl);
    const history = new ActivityApi(client);
    vi.spyOn(activityApi, "list").mockImplementation((p) => history.list(p));
    vi.spyOn(activityApi, "restore");

    const user = userEvent.setup();
    const { unmount } = render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/properties/p1/transactions"]}>
          <Routes>
            <Route
              path="/properties/:propertyId/transactions"
              element={<TransactionsPage api={transactions} />}
            />
          </Routes>
        </MemoryRouter>
      </ToastProvider>,
    );
    await user.click(
      await screen.findByRole("button", { name: /^delete/i }),
    );
    await screen.findByText(/transaction deleted/i);
    await user.click(screen.getByRole("button", { name: /undo/i }));
    await screen.findByText(/transaction restored/i);

    const sent = server.calls.filter((c) => c.method !== "GET");
    expect(sent).toEqual([
      { method: "DELETE", path: "/properties/p1/transactions/t-old" },
      { method: "POST", path: "/properties/p1/transactions" },
    ]);
    expect(server.calls.some((c) => /\/restore$/.test(c.path))).toBe(false);
    expect(activityApi.restore).not.toHaveBeenCalled();
    unmount();

    render(
      <ToastProvider>
        <MemoryRouter initialEntries={["/activity"]}>
          <ShellPropertiesProvider
            load={() => Promise.resolve([{ id: "p1", name: "Oak House" }] as never)}
          >
            <ActivityPage />
          </ShellPropertiesProvider>
        </MemoryRouter>
      </ToastProvider>,
    );
    const list = await screen.findByRole("list", { name: "Activity events" });
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(2));
    const [created, deleted] = within(list).getAllByRole("listitem");
    expect(within(created).getByText("Created")).toBeInTheDocument();
    expect(within(deleted).getByText("Deleted")).toBeInTheDocument();
    // No link between the two events and no "Restored" marker on the delete.
    expect(within(deleted).queryByText("Restored")).not.toBeInTheDocument();
    expect(within(deleted).queryByRole("link")).not.toBeInTheDocument();
    expect(created.querySelector("a")?.getAttribute("href")).toContain("focus=t-new");
  });
});
