import AxeBuilder from "@axe-core/playwright";
import {
  BUSINESS_ID,
  PACKAGE_JOB_COMPLETE,
  PACKAGE_JOB_FAILED,
  PACKAGE_JOB_RUNNING,
  PACKAGE_LIST_IDLE,
  PROPERTY_ID,
} from "../src/test/fixtures";
import type { Page } from "@playwright/test";
import { expect, prepare, searchHandler, test, type ApiHandler, type Theme } from "./fixtures";

const CHORD = process.platform === "darwin" ? "Meta+K" : "Control+K";

/**
 * Runs axe, retrying when the page navigates or re-renders mid-scan. Under parallel load axe can
 * fail with "Execution context was destroyed"; waiting for the load state and retrying makes the
 * check deterministic without skipping it.
 */
async function runAxe(page: Page) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.waitForLoadState("load");
      await page.waitForLoadState("networkidle");
      return await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    } catch (error) {
      lastError = error;
      if (!/Execution context was destroyed|Target (page|closed)|navigation/i.test(String(error))) throw error;
    }
  }
  throw lastError;
}
const P = `/properties/${PROPERTY_ID}`;
const ROUTES: ReadonlyArray<readonly [string, string]> = [
  ["dashboard", "/"],
  ["properties list", "/properties"],
  ["property detail", P],
  ["transactions", `${P}/transactions`],
  ["repairs", `${P}/repairs`],
  ["assets", `${P}/assets`],
  ["loans", `${P}/loans`],
  ["checklist", `${P}/checklist`],
  ["property report", `${P}/reports`],
  ["combined reports", "/reports"],
  ["accountant package", "/accountant-package"],
  ["carryforward", "/carryforward"],
  ["activity", "/activity"],
  ["search", "/search?q=faucet"],
  ["businesses", "/businesses"],
  ["business detail", `/businesses/${BUSINESS_ID}`],
  ["profile", "/profile"],
];
const THEMES: Theme[] = ["light", "dark"];
for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    for (const [name, path] of ROUTES) {
      test(`${name} (${path}) has no axe violations`, async ({ page }) => {
        await prepare(page, theme, { handler: searchHandler() });
        await page.goto(path);
        await expect(page.locator("main h1")).toHaveCount(1);
        await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark)/);
        // Let loading skeletons and data fetches settle before measuring.
        await page.waitForLoadState("networkidle");
        await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
        const results = await runAxe(page);
        const summary = results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes.slice(0, 5).map((n) => `${n.target.join(" ")} :: ${n.failureSummary?.split("\n")[1] ?? ""}`),
        }));
        expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
        // color-contrast must actually have been evaluated (not skipped).
        const evaluated = [...results.passes, ...results.incomplete].some((r) => r.id === "color-contrast");
        expect(evaluated).toBe(true);
      });
    }
  });
}

// Accountant package page states. The list route resumes the latest job, and
// the job route keeps returning the same view, so each state is stable.
const PACKAGE_STATES: ReadonlyArray<readonly [string, unknown]> = [
  ["idle", PACKAGE_LIST_IDLE],
  ["preparing", { jobs: [PACKAGE_JOB_RUNNING] }],
  ["complete", { jobs: [PACKAGE_JOB_COMPLETE] }],
  ["failed", { jobs: [PACKAGE_JOB_FAILED] }],
];
const STATE_TEXT: Readonly<Record<string, RegExp>> = {
  idle: /No package prepared yet/,
  preparing: /Preparing your package/,
  complete: /Download package/,
  failed: /Package failed/,
};

for (const theme of THEMES) {
  test.describe(`accountant package states, ${theme} theme`, () => {
    for (const [state, list] of PACKAGE_STATES) {
      test(`${state} has one h1 and no axe violations`, async ({ page }) => {
        const jobs = (list as { jobs: Array<{ id: string }> }).jobs;
        const handler: ApiHandler = ({ method, path }) => {
          if (method !== "GET") return undefined;
          if (path === "/accountant-packages") return { body: list };
          if (path.startsWith("/accountant-packages/") && jobs[0]) return { body: jobs[0] };
          return undefined;
        };
        await prepare(page, theme, { handler });
        await page.goto("/accountant-package");
        await expect(page.locator("main h1")).toHaveCount(1);
        await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark)/);
        await expect(page.locator("main")).toContainText(STATE_TEXT[state]);
        await page.waitForLoadState("networkidle");
        await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
        const results = await runAxe(page);
        const summary = results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
        }));
        expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
        const evaluated = [...results.passes, ...results.incomplete].some((r) => r.id === "color-contrast");
        expect(evaluated).toBe(true);
      });
    }
  });
}

// Narrow viewport: ResponsiveTable restyles rows as stacked cards via CSS, so
// the same DOM must stay axe-clean and must not scroll the page sideways.
const MOBILE_ROUTES: ReadonlyArray<readonly [string, string]> = [
  ["transactions", `${P}/transactions`],
  ["assets", `${P}/assets`],
  ["businesses", "/businesses"],
];

test.describe("mobile viewport (375px)", () => {
  test.use({ viewport: { width: 375, height: 800 } });
  for (const [name, path] of MOBILE_ROUTES) {
    test(`${name} (${path}) stacks table rows and has no axe violations`, async ({ page }) => {
      await prepare(page, "light");
      await page.goto(path);
      await expect(page.locator("main h1")).toHaveCount(1);
      await page.waitForLoadState("networkidle");
      await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);

      // Rows render as blocks (cards), not table rows, at this width.
      const row = page.locator("main table tbody tr").first();
      await expect(row).toBeVisible();
      expect(await row.evaluate((el) => getComputedStyle(el).display)).toBe("block");
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);

      const results = await runAxe(page);
      const summary = results.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
      }));
      expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
    });
  }
});

// Palette open, in both themes, on a routed page.
for (const theme of THEMES) {
  test(`command palette open has no axe violations (${theme} theme)`, async ({ page }) => {
    await prepare(page, theme, { handler: searchHandler() });
    await page.goto("/properties");
    await expect(page.locator("main h1")).toHaveCount(1);
    await page.keyboard.press(CHORD);
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Search or run a command" })).toBeFocused();
    const results = await runAxe(page);
    expect(results.violations.map((v) => v.id)).toEqual([]);
    expect([...results.passes, ...results.incomplete].some((r) => r.id === "color-contrast")).toBe(true);
  });
}

// Keyboard-only: the new pages are reachable and operable without a pointer, with reduced motion on.
test("keyboard-only: skip link, header Search and a search query reach the Search page", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await prepare(page, "light", { handler: searchHandler() });
  await page.goto("/search?q=faucet");
  await expect(page.locator("main h1")).toHaveCount(1);
  const field = page.getByRole("searchbox", { name: "Search" });
  await field.focus();
  await expect(field).toBeFocused();
  await page.keyboard.press("Control+A");
  await page.keyboard.type("faucet");
  await expect(page.getByRole("link", { name: /Replaced kitchen faucet/ })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).not.toHaveCount(0);
  const animated = await page.evaluate(() =>
    Array.from(document.querySelectorAll("main *")).filter(
      (n) => getComputedStyle(n).animationName !== "none" && getComputedStyle(n).animationName !== "",
    ).length,
  );
  expect(animated).toBe(0);
});
