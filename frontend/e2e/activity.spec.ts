import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { PROPERTY, PROPERTY_ID, TRANSACTION } from "../src/test/fixtures";
import type { ActivityEvent } from "../src/api/activity";
import { ACTIVITY_EVENTS, createStatefulApi, expect, prepare, test, type ApiHandler, type Theme } from "./fixtures";

const THEMES: Theme[] = ["light", "dark"];
const eventList = (page: Page) => page.getByRole("list", { name: "Activity events" });

/** Two pages of history; the second is served only for `cursor=page-2`. */
const SECOND_PAGE: ActivityEvent[] = [
  {
    ...ACTIVITY_EVENTS[1],
    id: "act-0",
    at: "2024-03-01T09:00:00Z",
    action: "update",
    summary: "Updated expense: Older change",
    before: { amount: "10.00" },
    after: { amount: "20.00" },
  },
];

const pagedHandler =
  (requests: URLSearchParams[]): ApiHandler =>
  ({ method, path, query }) => {
    if (method !== "GET" || path !== "/activity") return undefined;
    requests.push(query);
    return query.get("cursor") === "page-2"
      ? { body: { events: SECOND_PAGE, next_cursor: null } }
      : { body: { events: ACTIVITY_EVENTS, next_cursor: "page-2" } };
  };

test.describe("activity page", () => {
  test("filters send entity, action and property to the API", async ({ page }) => {
    const requests: URLSearchParams[] = [];
    await prepare(page, "light", {
      handler: ({ method, path, query }) => {
        if (method === "GET" && path === "/activity") requests.push(query);
        return undefined;
      },
    });
    await page.goto("/activity");
    await expect(eventList(page).getByRole("listitem")).toHaveCount(2);

    await page.getByLabel("Record type").selectOption({ label: "Transaction" });
    await expect.poll(() => requests.at(-1)?.get("entity")).toBe("transaction");
    await page.getByLabel("Action").selectOption({ label: "Deleted" });
    await expect.poll(() => requests.at(-1)?.get("action")).toBe("delete");
    await page.getByLabel("Property", { exact: true }).selectOption(PROPERTY_ID);
    await expect(page).toHaveURL(new RegExp(`/activity\\?property=${PROPERTY_ID}`));
  });

  test("Load more appends the next page and then disappears", async ({ page }) => {
    const requests: URLSearchParams[] = [];
    await prepare(page, "light", { handler: pagedHandler(requests) });
    await page.goto("/activity");
    await expect(eventList(page).getByRole("listitem")).toHaveCount(2);

    await page.getByRole("button", { name: "Load more" }).click();
    await expect(eventList(page).getByRole("listitem")).toHaveCount(3);
    await expect(page.getByRole("button", { name: "Load more" })).toHaveCount(0);
    // The dev server runs StrictMode, which may repeat the first request.
    const cursors = requests.map((q) => q.get("cursor"));
    expect(cursors.at(-1)).toBe("page-2");
    expect(cursors.filter((c) => c === "page-2")).toHaveLength(1);
  });

  test("Details disclosure shows before and after values", async ({ page }) => {
    await prepare(page, "light");
    await page.goto("/activity");
    const item = eventList(page).getByRole("listitem").filter({ hasText: "Deleted expense" });
    const details = item.locator("details");
    await expect(details).not.toHaveAttribute("open", "");
    await item.getByText("Details", { exact: true }).click();
    await expect(details).toHaveAttribute("open", "");
    await expect(details.getByText("Before")).toBeVisible();
    await expect(details.getByText("$250.00")).toBeVisible();
  });

  test("Restore asks for confirmation, can be cancelled, then restores with a toast", async ({ page }) => {
    const api = createStatefulApi({ properties: [PROPERTY], transactions: [TRANSACTION] });
    await prepare(page, "light", { handler: api.handler });
    await page.goto(`/properties/${PROPERTY_ID}/transactions`);
    await page.getByRole("row", { name: /Replaced kitchen faucet/ }).getByRole("button", { name: /^Delete/ }).click();
    await expect(page.getByRole("row", { name: /Replaced kitchen faucet/ })).toHaveCount(0);

    await page.goto("/activity");
    const item = eventList(page).getByRole("listitem").filter({ hasText: "Deleted expense" });
    const confirm = page.getByRole("dialog", { name: "Restore this record?" });

    await item.getByRole("button", { name: "Restore" }).click();
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Cancel" }).click();
    await expect(confirm).toBeHidden();
    expect(api.writes.some((w) => w.path.endsWith("/restore"))).toBe(false);

    await item.getByRole("button", { name: "Restore" }).click();
    await confirm.getByRole("button", { name: "Restore" }).click();
    await expect(confirm).toBeHidden();
    await expect(page.getByText("Record restored", { exact: true })).toBeVisible();
    await expect(item.getByText("Restored", { exact: true })).toBeVisible();
    await expect(item.getByRole("button", { name: "Restore" })).toHaveCount(0);
    expect(api.transactions.get(PROPERTY_ID)).toHaveLength(1);
    // The toast links to the restored record under its new id.
    await page.getByRole("button", { name: "View record" }).click();
    await expect(page).toHaveURL(new RegExp(`/properties/${PROPERTY_ID}/transactions\\?focus=`));
  });

  test("a 409 on restore shows the server message and keeps the page usable", async ({ page }) => {
    await prepare(page, "light", {
      handler: ({ method, path }) =>
        method === "POST" && path.endsWith("/restore")
          ? { status: 409, body: { message: "This record cannot be restored." } }
          : undefined,
    });
    await page.goto("/activity");
    const item = eventList(page).getByRole("listitem").filter({ hasText: "Deleted expense" });
    await item.getByRole("button", { name: "Restore" }).click();
    await page.getByRole("dialog", { name: "Restore this record?" }).getByRole("button", { name: "Restore" }).click();
    await expect(item.getByRole("alert")).toContainText("cannot be restored");
  });

  test("g a opens Activity", async ({ page }) => {
    await prepare(page, "light");
    await page.goto("/properties");
    await expect(page.locator("main h1")).toHaveCount(1);
    await page.keyboard.press("g");
    await page.keyboard.press("a");
    await expect(page).toHaveURL(/\/activity$/);
    await expect(page.getByRole("heading", { name: "Activity", level: 1 })).toBeVisible();
  });
});

test.describe("property Overview recent activity", () => {
  test("lists recent events and links to the filtered Activity page", async ({ page }) => {
    await prepare(page, "light");
    await page.goto(`/properties/${PROPERTY_ID}`);
    const panel = page.getByRole("region", { name: "Recent activity" });
    await expect(panel.getByRole("list", { name: "Recent activity events" }).getByRole("listitem")).toHaveCount(2);
    await panel.getByRole("link", { name: "View all activity" }).click();
    await expect(page).toHaveURL(new RegExp(`/activity\\?property=${PROPERTY_ID}$`));
    await expect(page.getByLabel("Property", { exact: true })).toHaveValue(PROPERTY_ID);
  });

  test("a failing activity route leaves the rest of the Overview usable", async ({ page }) => {
    await prepare(page, "light", {
      handler: ({ path }) => (path.endsWith("/activity") ? { status: 500, body: { message: "boom" } } : undefined),
    });
    await page.goto(`/properties/${PROPERTY_ID}`);
    await expect(page.getByRole("heading", { name: "Could not load recent activity" })).toBeVisible();
    await expect(page.locator("main h1")).toHaveCount(1);
  });
});

for (const theme of THEMES) {
  test.describe(`activity axe, ${theme} theme`, () => {
    test("list with an open Details disclosure and the restore dialog has no violations", async ({ page }) => {
      await prepare(page, theme);
      await page.goto("/activity");
      await expect(eventList(page).getByRole("listitem")).toHaveCount(2);
      await page.getByText("Details", { exact: true }).first().click();
      await page.getByRole("button", { name: "Restore" }).click();
      await expect(page.getByRole("dialog", { name: "Restore this record?" })).toBeVisible();
      await page.waitForLoadState("networkidle");
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const summary = results.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      }));
      expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
    });
  });
}
