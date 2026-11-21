import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { DASHBOARD_SUMMARY } from "../src/test/fixtures";
import { expect, prepare, test, type ApiHandler, type Theme } from "./fixtures";

const THEMES: Theme[] = ["light", "dark"];
const CHORD = process.platform === "darwin" ? "Meta+K" : "Control+K";

/** One property and no transactions, so the guide shows "Next" on step two. */
const newAccount: ApiHandler = ({ method, path }) =>
  method === "GET" && path === "/dashboard/trends" ? { body: { years: [] } } : undefined;

/** No properties: the dashboard shows its empty state instead of the guide. */
const emptyAccount: ApiHandler = ({ method, path }) => {
  if (method !== "GET") return undefined;
  if (path === "/properties") return { body: [] };
  if (path === "/dashboard") {
    return {
      body: {
        ...DASHBOARD_SUMMARY,
        has_properties: false,
        total_income: "0.00",
        total_expenses: "0.00",
        net: "0.00",
        properties: [],
        empty_state_prompt: null,
      },
    };
  }
  if (path === "/dashboard/properties") return { body: [] };
  return newAccount({ method, path } as Parameters<ApiHandler>[0]);
};

const guide = (page: Page) => page.getByRole("region", { name: "Get set up" });

async function load(page: Page, theme: Theme = "light", handler = newAccount): Promise<void> {
  await prepare(page, theme, { handler });
  await page.goto("/");
  await expect(page.locator("main h1")).toHaveCount(1);
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

test.describe("onboarding", () => {
  test("the guide marks the next step with a text label and a reason", async ({ page }) => {
    await load(page);
    await expect(guide(page)).toBeVisible();
    await expect(guide(page).getByText("Next", { exact: true })).toBeVisible();
    await expect(guide(page).getByRole("link", { name: "Record a transaction" })).toBeVisible();
    await expect(guide(page)).toContainText("1 of 4 done");
    // The sample data link is offered only to an account with no property.
    await expect(guide(page).getByRole("link", { name: "Explore with sample data" })).toHaveCount(0);
  });

  test("an account with no property sees the empty state and the sample data link", async ({ page }) => {
    await load(page, "light", emptyAccount);
    const link = page.getByRole("link", { name: "Explore with sample data" });
    await expect(link).toHaveAttribute("href", "/profile?focus=backup");
    await expect(page.getByRole("link", { name: "Add your first property" })).toBeVisible();
  });

  test("collapse and expand by keyboard", async ({ page }) => {
    await load(page);
    await expect(guide(page)).toBeVisible();
    const toggle = guide(page).getByRole("button", { name: "Collapse" });
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(toggle).toHaveAttribute("aria-controls", "checklist-steps");
    await toggle.focus();
    await page.keyboard.press("Enter");

    const expand = guide(page).getByRole("button", { name: "Expand" });
    await expect(expand).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("#checklist-steps")).toBeHidden();
    await expect(expand).toBeFocused();

    // Collapsed state persists across a reload.
    await page.reload();
    await expect(guide(page).getByRole("button", { name: "Expand" })).toBeVisible();
    await expect(page.locator("#checklist-steps")).toBeHidden();

    await guide(page).getByRole("button", { name: "Expand" }).focus();
    await page.keyboard.press("Space");
    await expect(guide(page).getByRole("button", { name: "Collapse" })).toBeFocused();
    await expect(page.locator("#checklist-steps")).toBeVisible();
  });

  test("dismiss persists, and the account menu brings the guide back", async ({ page }) => {
    await load(page);
    await expect(guide(page)).toBeVisible();
    await guide(page).getByRole("button", { name: "Dismiss setup checklist" }).click();
    await expect(guide(page)).toHaveCount(0);

    await page.reload();
    await expect(page.locator("main h1")).toHaveCount(1);
    await expect(guide(page)).toHaveCount(0);

    await page.getByRole("button", { name: /Open account menu/ }).click();
    await page.getByRole("menuitem", { name: "Show setup guide" }).click();
    await expect(guide(page)).toBeVisible();
    await expect(page.locator("#checklist-heading")).toBeFocused();

    // The restored state survives a reload.
    await page.reload();
    await expect(guide(page)).toBeVisible();
  });

  test("the palette action brings the guide back from another page", async ({ page }) => {
    await load(page);
    await expect(guide(page)).toBeVisible();
    await guide(page).getByRole("button", { name: "Dismiss setup checklist" }).click();
    await expect(guide(page)).toHaveCount(0);

    await page.goto("/carryforward");
    await expect(page.locator("main h1")).toHaveCount(1);
    await page.keyboard.press(CHORD);
    const input = page.getByRole("combobox", { name: "Search or run a command" });
    await expect(input).toBeFocused();
    await input.fill("setup guide");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/\/$/);
    await expect(guide(page)).toBeVisible();
    await expect(page.locator("#checklist-heading")).toBeFocused();
  });

  test("empty pages guide the user and offer the sample data link", async ({ page }) => {
    await load(page, "light", emptyAccount);
    await page.goto("/properties");
    await expect(page.getByText("No properties yet")).toBeVisible();
    await expect(page.getByRole("link", { name: "Explore with sample data" })).toBeVisible();
  });

  test("reduced motion: the guide has no animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await load(page);
    await expect(guide(page)).toBeVisible();
    await guide(page).getByRole("button", { name: "Collapse" }).click();
    await expect(page.locator("#checklist-steps")).toBeHidden();
    await expect(guide(page).locator('[class*="animate-"]')).toHaveCount(0);
    const names = await guide(page).evaluate((el) =>
      [el, ...Array.from(el.querySelectorAll("*"))].map((n) => getComputedStyle(n).animationName),
    );
    expect(names.every((n) => n === "none")).toBe(true);
  });

  for (const theme of THEMES) {
    test(`guide and empty pages have no axe violations (${theme})`, async ({ page }) => {
      await load(page, theme);
      await expect(guide(page)).toBeVisible();
      for (const step of ["expanded", "collapsed", "properties"] as const) {
        if (step === "collapsed") {
          await guide(page).getByRole("button", { name: "Collapse" }).click();
          await expect(page.locator("#checklist-steps")).toBeHidden();
        }
        if (step === "properties") {
          await page.unrouteAll({ behavior: "ignoreErrors" });
          await prepare(page, theme, { handler: emptyAccount });
          await page.goto("/properties");
          await expect(page.getByText("No properties yet")).toBeVisible();
        }
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        const summary = results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
        }));
        expect(summary, `${step}: ${JSON.stringify(summary, null, 2)}`).toEqual([]);
      }
    });
  }
});
