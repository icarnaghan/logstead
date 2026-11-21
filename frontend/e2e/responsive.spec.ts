import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { PROPERTY_ID } from "../src/test/fixtures";
import { expect, prepare, test, type Theme } from "./fixtures";

const P = `/properties/${PROPERTY_ID}`;
const THEMES: Theme[] = ["light", "dark"];
const VIEWPORTS = [
  { width: 320, height: 640 },
  { width: 375, height: 800 },
  { width: 768, height: 1024 },
  { width: 1023, height: 768 },
  { width: 1280, height: 800 },
] as const;
const ROUTES: ReadonlyArray<readonly [string, string]> = [
  ["dashboard", "/"],
  ["properties list", "/properties"],
  ["property overview", P],
  ["transactions", `${P}/transactions`],
  ["assets", `${P}/assets`],
  ["loans", `${P}/loans`],
  ["property report", `${P}/reports`],
  ["combined reports", "/reports"],
  ["profile", "/profile"],
];
const SEVEN_TABS = 7;

async function settle(page: Page): Promise<void> {
  await expect(page.locator("main h1")).toHaveCount(1);
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

/** Number of distinct visual rows the tab links occupy. */
async function tabRows(page: Page): Promise<number> {
  return page
    .locator('nav[aria-label="Property sections"] li')
    .evaluateAll((items) => new Set(items.map((li) => Math.round(li.getBoundingClientRect().top))).size);
}

for (const viewport of VIEWPORTS) {
  for (const theme of THEMES) {
    test.describe(`${viewport.width}px, ${theme} theme`, () => {
      test.use({ viewport });

      for (const [name, path] of ROUTES) {
        test(`${name} has no horizontal scroll and no axe violations`, async ({ page }) => {
          await prepare(page, theme);
          await page.goto(path);
          await settle(page);
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
          ).toBe(true);
          const results = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
            .analyze();
          const summary = results.violations.map((v) => ({
            id: v.id,
            nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
          }));
          expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
        });
      }
    });
  }
}

test.describe("property tabs", () => {
  for (const width of [375, 768, 1023]) {
    test.describe(`${width}px`, () => {
      test.use({ viewport: { width, height: 900 } });

      test("disclosure opens by keyboard, chooses a section, closes on Escape", async ({ page }) => {
        await prepare(page, "light");
        await page.goto(`${P}/transactions`);
        await settle(page);
        const nav = page.getByRole("navigation", { name: "Property sections" });
        await expect(nav).toHaveCount(1);
        const button = nav.getByRole("button", { name: /^Property sections:/ });
        const list = nav.getByRole("list");

        if (!(await button.isVisible())) {
          // Wide enough for the wrapping row: the links show and the button is hidden.
          await expect(list).toBeVisible();
          await expect(nav.getByRole("link", { name: "Transactions" })).toHaveAttribute(
            "aria-current",
            "page",
          );
          return;
        }

        await expect(button).toHaveText(/Transactions/);
        await expect(button).toHaveAttribute("aria-expanded", "false");
        await expect(list).toBeHidden();

        await button.focus();
        await page.keyboard.press("Enter");
        await expect(button).toHaveAttribute("aria-expanded", "true");
        await expect(list).toBeVisible();
        await expect(nav.getByRole("link", { name: "Transactions" })).toHaveAttribute(
          "aria-current",
          "page",
        );

        // Escape closes and returns focus to the button.
        await nav.getByRole("link", { name: "Repairs" }).focus();
        await page.keyboard.press("Escape");
        await expect(button).toHaveAttribute("aria-expanded", "false");
        await expect(button).toBeFocused();

        // Choosing a link navigates, closes the list and updates the label.
        await page.keyboard.press("Enter");
        await nav.getByRole("link", { name: "Loans" }).click();
        await expect(page).toHaveURL(new RegExp(`${P}/loans$`));
        await expect(button).toHaveAttribute("aria-expanded", "false");
        await expect(button).toHaveText(/Loans/);
      });

      test("seven tabs fit in at most two rows when the row is shown", async ({ page }) => {
        await prepare(page, "light");
        await page.goto(`${P}/transactions`);
        await settle(page);
        const nav = page.getByRole("navigation", { name: "Property sections" });
        if (await nav.getByRole("button", { name: /^Property sections:/ }).isVisible()) {
          test.skip(true, "Disclosure shown at this width; no wrapping row to measure.");
        }
        // Simulate the year-end-checklist tab: top up to the seven-tab set.
        await page.evaluate((target) => {
          const ul = document.querySelector('nav[aria-label="Property sections"] ul');
          const items = ul?.querySelectorAll("li");
          if (!ul || !items?.length) return;
          for (let i = items.length; i < target; i += 1) {
            ul.appendChild(items[items.length - 1].cloneNode(true));
          }
        }, SEVEN_TABS);
        await expect(nav.locator("li")).toHaveCount(SEVEN_TABS);
        expect(await tabRows(page)).toBeLessThanOrEqual(2);
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        ).toBe(true);
      });
    });
  }
});

test.describe("add-transaction modal at 320px", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("keeps Save inside the viewport and inputs at 16px", async ({ page }) => {
    await prepare(page, "light");
    await page.goto(`${P}/transactions`);
    await settle(page);
    await page.getByRole("button", { name: "Add transaction" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Add transaction" });
    await expect(dialog).toBeVisible();

    const save = dialog.getByRole("button", { name: "Add transaction" });
    await expect(save).toBeVisible();
    const box = await save.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(640);
    expect(box!.x + box!.width).toBeLessThanOrEqual(320);

    const dialogBox = await dialog.boundingBox();
    expect(dialogBox!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.x + dialogBox!.width).toBeLessThanOrEqual(320);

    const sizes = await dialog
      .locator("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea")
      .evaluateAll((els) => els.map((el) => parseFloat(getComputedStyle(el).fontSize)));
    expect(sizes.length).toBeGreaterThan(0);
    for (const size of sizes) expect(size).toBeGreaterThanOrEqual(16);
  });
});
