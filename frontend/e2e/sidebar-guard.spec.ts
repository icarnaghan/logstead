import { expect, prepare, test } from "./fixtures";

/** A dirty Imports form makes a sidebar click ask before leaving (Requirement 30). */
test.describe("sidebar navigation guard", () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("dirty Imports form: Keep editing stays, Discard navigates", async ({ page }) => {
    await prepare(page, "light");
    await page.goto("/imports/schedule-e");
    const taxYear = page.getByLabel("Tax year");
    await expect(taxYear).toBeVisible();
    await taxYear.fill("2001");

    const nav = page.getByRole("navigation", { name: "Primary" });
    await nav.getByRole("link", { name: "Properties" }).click();
    const dialog = page.getByRole("dialog", { name: "Discard changes?" });
    await expect(dialog.getByText("Discard changes?")).toBeVisible();

    await dialog.getByRole("button", { name: "Keep editing" }).click();
    await expect(page).toHaveURL(/\/imports\/schedule-e$/);
    await expect(taxYear).toHaveValue("2001");

    await nav.getByRole("link", { name: "Properties" }).click();
    await page.getByRole("dialog", { name: "Discard changes?" }).getByRole("button", { name: "Discard" }).click();
    await expect(page).toHaveURL(/\/properties$/);
  });
});
