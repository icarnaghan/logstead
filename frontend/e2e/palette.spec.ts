import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { PROPERTY_ID, TRANSACTION } from "../src/test/fixtures";
import { expect, prepare, SEARCH_RESPONSE, searchHandler, test, type Theme } from "./fixtures";

const P = `/properties/${PROPERTY_ID}`;
const THEMES: Theme[] = ["light", "dark"];
const CHORD = process.platform === "darwin" ? "Meta+K" : "Control+K";

const palette = (page: Page) => page.getByRole("dialog", { name: "Command palette" });
const paletteInput = (page: Page) => page.getByRole("combobox", { name: "Search or run a command" });
const searchButton = (page: Page) => page.getByRole("button", { name: "Search", exact: true });

async function load(page: Page, path: string, theme: Theme = "light"): Promise<void> {
  await prepare(page, theme);
  await page.goto(path);
  await expect(page.locator("main h1")).toHaveCount(1);
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

test.describe("command palette", () => {
  test("opens with the chord and the header button, and Escape returns focus", async ({ page }) => {
    await load(page, "/properties");

    await page.keyboard.press(CHORD);
    await expect(palette(page)).toBeVisible();
    await expect(paletteInput(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(palette(page)).toBeHidden();

    await searchButton(page).focus();
    await searchButton(page).click();
    await expect(palette(page)).toBeVisible();
    await expect(paletteInput(page)).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(palette(page)).toBeHidden();
    await expect(searchButton(page)).toBeFocused();
  });

  test("typing filters and arrows with Enter navigate", async ({ page }) => {
    await load(page, "/properties");
    await page.keyboard.press(CHORD);
    await expect(paletteInput(page)).toBeFocused();

    await paletteInput(page).fill("carry");
    const options = palette(page).getByRole("option");
    await expect(options.first()).toContainText("Carryforward");
    await expect(options.first()).toHaveAttribute("aria-selected", "true");

    // Arrow keys wrap and move aria-activedescendant.
    await paletteInput(page).fill("");
    const count = await options.count();
    expect(count).toBeGreaterThan(1);
    await page.keyboard.press("ArrowUp");
    await expect(options.nth(count - 1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("ArrowDown");
    await expect(options.first()).toHaveAttribute("aria-selected", "true");

    await paletteInput(page).fill("carry");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/carryforward$/);
    await expect(palette(page)).toBeHidden();
    await expect(page.locator("main h1")).toHaveCount(1);
  });

  test("g sequences navigate", async ({ page }) => {
    await load(page, "/properties");
    await page.keyboard.press("g");
    await page.keyboard.press("r");
    await expect(page).toHaveURL(/\/reports$/);
    await page.keyboard.press("g");
    await page.keyboard.press("d");
    await expect(page).toHaveURL(/\/$/);
    await page.keyboard.press("g");
    await page.keyboard.press("c");
    await expect(page).toHaveURL(/\/carryforward$/);
  });

  test("shortcuts are ignored in a field and with an open RecordModal", async ({ page }) => {
    await load(page, `${P}/transactions`);
    const url = page.url();

    const field = page.getByRole("searchbox", { name: "Search transactions" });
    await field.click();
    await page.keyboard.type("gd?");
    await expect(field).toHaveValue("gd?");
    await expect(page).toHaveURL(url);
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);

    await page.getByRole("button", { name: "Add transaction" }).first().click();
    const modal = page.getByRole("dialog", { name: "Add transaction" });
    await expect(modal).toBeVisible();
    await modal.focus().catch(() => undefined);
    await page.keyboard.press("g");
    await page.keyboard.press("d");
    await page.keyboard.press("?");
    await expect(page).toHaveURL(url);
    await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toHaveCount(0);
    await expect(modal).toBeVisible();
  });

  test("? opens the help dialog and Escape closes it", async ({ page }) => {
    await load(page, "/properties");
    await page.keyboard.press("?");
    const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
    await expect(help).toBeVisible();
    await expect(help.locator("kbd").first()).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(help).toBeHidden();
  });

  test("a dirty Imports form shows the discard confirm", async ({ page }) => {
    await load(page, "/imports/schedule-e");
    await page.getByRole("button", { name: "Add property column" }).click();

    await page.keyboard.press("g");
    await page.keyboard.press("d");
    const confirm = page.getByRole("dialog", { name: "Discard changes?" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "Keep editing" }).click();
    await expect(confirm).toBeHidden();
    await expect(page).toHaveURL(/\/imports\/schedule-e$/);

    await page.keyboard.press("g");
    await page.keyboard.press("d");
    await page.getByRole("dialog", { name: "Discard changes?" }).getByRole("button", { name: "Discard" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("reduced motion: opens with no animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await load(page, "/properties");
    await page.keyboard.press(CHORD);
    await expect(palette(page)).toBeVisible();
    const animation = await palette(page).evaluate((el) => getComputedStyle(el).animationName);
    expect(animation).toBe("none");
  });

  for (const theme of THEMES) {
    test(`palette and help dialog have no axe violations (${theme})`, async ({ page }) => {
      await load(page, "/properties", theme);
      for (const open of [
        async () => {
          await page.keyboard.press(CHORD);
          await paletteInput(page).fill("re");
          await expect(palette(page).getByRole("option").first()).toBeVisible();
        },
        async () => {
          await page.keyboard.press("?");
          await expect(page.getByRole("dialog", { name: "Keyboard shortcuts" })).toBeVisible();
        },
      ]) {
        await open();
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        const summary = results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
        }));
        expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).toHaveCount(0);
      }
    });
  }

  test.describe("global search", () => {
    const options = (page: Page) => palette(page).getByRole("option");

    async function openAndType(page: Page, text: string): Promise<void> {
      await page.keyboard.press(CHORD);
      await expect(paletteInput(page)).toBeFocused();
      await paletteInput(page).fill(text);
    }

    test("shows grouped hits and Enter on a hit lands on the focused row", async ({ page }) => {
      await prepare(page, "light", { handler: searchHandler() });
      await page.goto("/properties");
      await expect(page.locator("main h1")).toHaveCount(1);
      await openAndType(page, "faucet");

      const transactions = palette(page).getByRole("group", { name: "Transactions" });
      await expect(transactions).toBeVisible();
      await expect(palette(page).getByRole("group", { name: "Properties" })).toBeVisible();
      const hitOption = transactions.getByRole("option", { name: /Replaced kitchen faucet/ });
      await expect(hitOption).toBeVisible();

      await hitOption.hover();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`${P}/transactions\\?focus=${TRANSACTION.id}$`));
      await expect(palette(page)).toBeHidden();
      await expect(page.locator(`[id="row-${TRANSACTION.id}"]`)).toBeFocused();
    });

    test("an unknown focus id is ignored", async ({ page }) => {
      await load(page, `${P}/transactions?focus=does-not-exist`);
      await expect(page.locator('[id^="row-"]:focus')).toHaveCount(0);
    });

    test("See all results opens the Search page with the query", async ({ page }) => {
      await prepare(page, "light", {
        handler: searchHandler({
          ...SEARCH_RESPONSE,
          groups: SEARCH_RESPONSE.groups.map((g) =>
            g.kind === "transaction" ? { ...g, total: 12 } : g,
          ),
        }),
      });
      await page.goto("/properties");
      await expect(page.locator("main h1")).toHaveCount(1);
      await openAndType(page, "faucet");

      const seeAll = options(page).filter({ hasText: "See all 12 results" });
      await expect(seeAll).toBeVisible();
      await seeAll.click();
      await expect(page).toHaveURL(/\/search\?q=faucet$/);
      await expect(page.getByRole("searchbox", { name: "Search" })).toHaveValue("faucet");
      await expect(page.locator("main h1")).toHaveText("Search");
    });

    test("a failing search shows an error with Retry", async ({ page }) => {
      let fail = true;
      await prepare(page, "light", {
        handler: (req) =>
          req.path === "/search" && fail ? { status: 500, body: { message: "boom" } } : searchHandler()(req),
      });
      await page.goto("/properties");
      await expect(page.locator("main h1")).toHaveCount(1);
      await openAndType(page, "faucet");
      await expect(palette(page).getByRole("button", { name: "Retry" })).toBeVisible();
      fail = false;
      await palette(page).getByRole("button", { name: "Retry" }).click();
      await expect(palette(page).getByRole("group", { name: "Transactions" })).toBeVisible();
    });

    for (const theme of THEMES) {
      test(`palette results and the Search page have no axe violations (${theme})`, async ({ page }) => {
        await prepare(page, theme, { handler: searchHandler() });
        await page.goto("/properties");
        await expect(page.locator("main h1")).toHaveCount(1);
        await openAndType(page, "faucet");
        await expect(options(page).first()).toBeVisible();
        await expect(palette(page).getByRole("group", { name: "Transactions" })).toBeVisible();
        const inPalette = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        expect(inPalette.violations.map((v) => v.id)).toEqual([]);
        await page.keyboard.press("Escape");

        await page.goto("/search?q=faucet");
        await expect(page.locator("main h1")).toHaveCount(1);
        await expect(page.getByRole("link", { name: /Replaced kitchen faucet/ })).toBeVisible();
        await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
        const onPage = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        const summary = onPage.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
        }));
        expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
      });
    }
  });

  test.describe("320px viewport", () => {
    test.use({ viewport: { width: 320, height: 640 } });
    test("palette fits the viewport and has no axe violations", async ({ page }) => {
      await load(page, "/properties");
      await searchButton(page).click();
      await expect(palette(page)).toBeVisible();
      await paletteInput(page).fill("re");
      const box = await palette(page).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(320);
      expect(box!.y + box!.height).toBeLessThanOrEqual(640);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBe(true);
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(results.violations.map((v) => v.id)).toEqual([]);
    });
  });
});
