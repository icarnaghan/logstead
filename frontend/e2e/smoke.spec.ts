import { createHash } from "node:crypto";
import type { Page } from "@playwright/test";
import { COGNITO_CLIENT_ID, COGNITO_DOMAIN, COGNITO_REDIRECT_URI } from "../playwright.config";
import {
  PROPERTY,
  PACKAGE_JOB_COMPLETE,
  PACKAGE_JOB_ID,
  PACKAGE_JOB_RUNNING,
  PACKAGE_LIST_IDLE,
  TRANSACTION,
} from "../src/test/fixtures";
import { createStatefulApi, expect, prepare, test } from "./fixtures";

/**
 * Smoke test of the flows the unit tests cannot prove end to end (review.md
 * S10, R11): the Cognito PKCE sign-in callback, then creating a property,
 * adding a transaction, and deleting it with Undo. Cognito and the API are
 * both mocked with `page.route`; nothing leaves the machine.
 */

const TOKEN_URL = `${COGNITO_DOMAIN}/oauth2/token`;
const REFRESH_TOKEN = "e2e-refresh-token-must-not-be-stored";
const BLANK_PAGE = new URL("/__e2e_blank__", COGNITO_REDIRECT_URI).href;

interface Handshake {
  authorizeUrl: URL;
  tokenRequests: URLSearchParams[];
  /** PKCE verifier and state the app had stored when it redirected. */
  stored: { verifier: string | null; state: string | null };
}

/**
 * Starts signed out, loads the app, and captures the redirect to the Cognito
 * authorize endpoint (fulfilled with a stub page, since the host does not resolve). Also mocks
 * the token endpoint and records the form bodies posted to it.
 *
 * React StrictMode (dev server) runs the sign-in effect twice, so the app may
 * redirect twice and the second call overwrites the stored verifier and state.
 * The authorize URL returned is the one whose state matches what is stored.
 * Storage is read from a same-origin blank page, since the page is then on
 * the stubbed Cognito origin.
 */
async function startSignIn(page: Page): Promise<Handshake> {
  await prepare(page, "light", { authenticated: false });
  const tokenRequests: URLSearchParams[] = [];
  const authorizeUrls: URL[] = [];
  await page.route(`${COGNITO_DOMAIN}/oauth2/authorize*`, async (route) => {
    authorizeUrls.push(new URL(route.request().url()));
    // Fulfil rather than abort: an aborted navigation lands on chrome-error,
    // which can interrupt the next page.goto.
    await route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>cognito</title>" });
  });
  // A same-origin page that does not run the app, used to read sessionStorage
  // after the aborted redirect without starting another sign-in.
  await page.route(`${BLANK_PAGE}`, (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><title>blank</title>" }),
  );
  await page.route(TOKEN_URL, async (route) => {
    tokenRequests.push(new URLSearchParams(route.request().postData() ?? ""));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        id_token: "e2e-id-token",
        access_token: "e2e-access-token",
        refresh_token: REFRESH_TOKEN,
        expires_in: 3600,
        token_type: "Bearer",
      }),
    });
  });
  await page.goto("/");
  await expect.poll(() => authorizeUrls.length).toBeGreaterThan(0);
  // StrictMode may redirect a second time; wait for the attempts to settle.
  let seen = -1;
  await expect
    .poll(
      async () => {
        const settled = authorizeUrls.length === seen;
        seen = authorizeUrls.length;
        if (!settled) await page.waitForTimeout(300);
        return settled;
      },
      { timeout: 10_000 },
    )
    .toBe(true);
  await page.waitForLoadState("load");
  await page.goto(BLANK_PAGE);
  const stored = await page.evaluate(() => ({
    verifier: sessionStorage.getItem("logstead.pkce.verifier"),
    state: sessionStorage.getItem("logstead.oauth.state"),
  }));
  const authorizeUrl = authorizeUrls.find((u) => u.searchParams.get("state") === stored.state);
  if (!authorizeUrl) throw new Error(`no authorize request carried the stored state ${stored.state}`);
  return { authorizeUrl, tokenRequests, stored };
}

/** Every key and value held in session and local storage, as one string. */
function storageDump(page: Page): Promise<string> {
  return page.evaluate(() =>
    JSON.stringify([
      Object.entries(sessionStorage),
      Object.entries(localStorage),
    ]),
  );
}

test.describe("sign-in callback", () => {
  test("redirects to Cognito with PKCE, exchanges the code and lands on the dashboard", async ({ page }) => {
    const { authorizeUrl, tokenRequests, stored } = await startSignIn(page);

    const q = authorizeUrl.searchParams;
    expect(authorizeUrl.origin + authorizeUrl.pathname).toBe(`${COGNITO_DOMAIN}/oauth2/authorize`);
    expect(q.get("response_type")).toBe("code");
    expect(q.get("client_id")).toBe(COGNITO_CLIENT_ID);
    expect(q.get("redirect_uri")).toBe(COGNITO_REDIRECT_URI);
    expect(q.get("code_challenge_method")).toBe("S256");
    const state = q.get("state");
    expect(state).toBeTruthy();
    const challenge = q.get("code_challenge");
    expect(challenge).toBeTruthy();

    // The challenge must be the S256 hash of the verifier the app kept.
    const verifier = stored.verifier;
    expect(verifier).toBeTruthy();
    expect(createHash("sha256").update(verifier!).digest("base64url")).toBe(challenge);
    expect(stored.state).toBe(state);

    // Simulate Cognito sending the browser back with a code and the saved state.
    await page.goto(`/auth/callback?code=e2e-code&state=${encodeURIComponent(state!)}`);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator("main h1")).toHaveCount(1);

    expect(tokenRequests).toHaveLength(1);
    expect(Object.fromEntries(tokenRequests[0])).toMatchObject({
      grant_type: "authorization_code",
      client_id: COGNITO_CLIENT_ID,
      code: "e2e-code",
      redirect_uri: COGNITO_REDIRECT_URI,
      code_verifier: verifier,
    });

    // Tokens are stored; the refresh token is never persisted (review.md S2/S3).
    expect(await page.evaluate(() => sessionStorage.getItem("logstead.accessToken"))).toBe("e2e-access-token");
    const dump = await storageDump(page);
    expect(dump).not.toContain(REFRESH_TOKEN);
    expect(dump.toLowerCase()).not.toContain("refresh");
    // The one-time PKCE values are cleaned up after the exchange.
    expect(await page.evaluate(() => sessionStorage.getItem("logstead.pkce.verifier"))).toBeNull();
    expect(await page.evaluate(() => sessionStorage.getItem("logstead.oauth.state"))).toBeNull();
  });

  test("rejects a callback whose state does not match and stores no tokens", async ({ page }) => {
    const { tokenRequests } = await startSignIn(page);

    await page.goto("/auth/callback?code=e2e-code&state=not-the-saved-state");
    await expect(page.getByRole("alert")).toContainText("Sign-in failed");
    await expect(page.getByRole("button", { name: "Try signing in again" })).toBeVisible();

    expect(tokenRequests).toHaveLength(0);
    const dump = await storageDump(page);
    expect(dump).not.toContain("logstead.idToken");
    expect(dump).not.toContain("logstead.accessToken");
    expect(dump).not.toContain(REFRESH_TOKEN);
  });
});

test("create a property, add a transaction, delete it and Undo", async ({ page }) => {
  const api = createStatefulApi();
  const authorizations = new Set<string | undefined>();
  await prepare(page, "light", {
    handler: (req) => {
      authorizations.add(req.authorization);
      return api.handler(req);
    },
  });

  // Create the property through the form.
  await page.goto("/properties");
  await expect(page.getByRole("heading", { name: "No properties yet" })).toBeVisible();
  await page.getByRole("button", { name: "Add property" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a property" });
  await dialog.getByRole("combobox", { name: "Address" }).fill("42 Smoke Test Lane, Springfield, IL 62701");
  await dialog.getByRole("textbox", { name: "Name" }).fill("Smoke Test Duplex");
  await dialog.getByRole("button", { name: "Save property" }).click();
  await expect(dialog).toBeHidden();
  const propertyLink = page.getByRole("link", { name: "Smoke Test Duplex" }).first();
  await expect(propertyLink).toBeVisible();
  expect(api.properties.map((p) => p.name)).toEqual(["Smoke Test Duplex"]);

  // Add a transaction to it.
  await propertyLink.click();
  await page.getByRole("link", { name: "Transactions" }).first().click();
  await expect(page.getByRole("heading", { name: "Transactions", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "Add transaction" }).first().click();
  const form = page.getByRole("dialog");
  await form.getByLabel("Amount").fill("125.50");
  await form.getByLabel("Category").selectOption({ label: "Repairs (Line 14)" });
  await form.getByLabel(/^Description/).fill("Smoke test faucet");
  await form.getByRole("button", { name: "Add transaction" }).click();
  await expect(form).toBeHidden();
  const row = page.getByRole("row", { name: /Smoke test faucet/ });
  await expect(row).toBeVisible();
  const propertyId = api.properties[0].id;
  const [original] = api.transactions.get(propertyId)!;
  expect(original).toMatchObject({ amount: "125.50", category_id: "cat-repairs", type: "expense" });

  // Delete it (no receipts, so it is a safe delete with an Undo toast).
  await row.getByRole("button", { name: /^Delete/ }).click();
  await expect(page.getByRole("row", { name: /Smoke test faucet/ })).toHaveCount(0);
  expect(api.transactions.get(propertyId)).toHaveLength(0);

  // Undo re-creates the record: it reappears under a new id (review.md R11).
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByRole("row", { name: /Smoke test faucet/ })).toBeVisible();
  const restored = api.transactions.get(propertyId)!;
  expect(restored).toHaveLength(1);
  expect(restored[0].id).not.toBe(original.id);
  expect(restored[0]).toMatchObject({ amount: "125.50", description: "Smoke test faucet" });

  const creates = api.writes.filter((w) => w.method === "POST" && w.path.endsWith("/transactions"));
  expect(creates).toHaveLength(2);
  expect(creates[1].body).not.toHaveProperty("id");

  // Every API call carried the bearer token from the seeded session.
  expect(authorizations).toEqual(new Set(["Bearer e2e-fake-access-token"]));
});

test("prepare an accountant package and get the download link", async ({ page }) => {
  const created: unknown[] = [];
  let polls = 0;
  await prepare(page, "light", {
    handler: ({ method, path, body }) => {
      if (path === "/accountant-packages" && method === "GET") return { body: PACKAGE_LIST_IDLE };
      if (path === "/accountant-packages" && method === "POST") {
        created.push(body);
        return { status: 202, body: { ...PACKAGE_JOB_RUNNING, status: "queued" } };
      }
      if (path === `/accountant-packages/${PACKAGE_JOB_ID}` && method === "GET") {
        polls += 1;
        return { body: PACKAGE_JOB_COMPLETE };
      }
      return undefined;
    },
  });
  await page.goto("/accountant-package");
  await expect(page.getByText("No package prepared yet.")).toBeVisible();
  await page.getByRole("button", { name: "Prepare package" }).click();
  const link = page.getByRole("link", { name: "Download package" });
  await expect(link).toBeVisible({ timeout: 15_000 });
  await expect(link).toHaveAttribute("href", PACKAGE_JOB_COMPLETE.download_url!);
  expect(created).toHaveLength(1);
  expect(created[0]).toMatchObject({ tax_year: expect.any(Number) });
  expect(polls).toBeGreaterThan(0);
});

test("delete a transaction, open Activity and restore it", async ({ page }) => {
  const api = createStatefulApi({ properties: [PROPERTY], transactions: [TRANSACTION] });
  await prepare(page, "light", { handler: api.handler });

  await page.goto(`/properties/${PROPERTY.id}/transactions`);
  const row = page.getByRole("row", { name: /Replaced kitchen faucet/ });
  await row.getByRole("button", { name: /^Delete/ }).click();
  await expect(page.getByRole("row", { name: /Replaced kitchen faucet/ })).toHaveCount(0);
  expect(api.transactions.get(PROPERTY.id)).toHaveLength(0);

  // Open Activity from the navigation; the delete is listed and restorable.
  await page.getByRole("link", { name: "Activity", exact: true }).first().click();
  await expect(page).toHaveURL(/\/activity$/);
  const item = page.getByRole("listitem").filter({ hasText: "Deleted expense" });
  await expect(item).toBeVisible();
  await item.getByRole("button", { name: "Restore" }).click();

  // The confirm names the consequence; nothing is sent until it is accepted.
  const confirm = page.getByRole("dialog", { name: "Restore this record?" });
  await expect(confirm).toContainText("new id");
  expect(api.writes.some((w) => w.path.endsWith("/restore"))).toBe(false);
  await confirm.getByRole("button", { name: "Restore" }).click();

  await expect(page.getByText("Record restored", { exact: true })).toBeVisible();
  await expect(item.getByText("Restored", { exact: true })).toBeVisible();
  await expect(item.getByRole("button", { name: "Restore" })).toHaveCount(0);
  const restored = api.transactions.get(PROPERTY.id)!;
  expect(restored).toHaveLength(1);
  expect(restored[0].id).not.toBe(TRANSACTION.id);
  expect(restored[0]).toMatchObject({ amount: TRANSACTION.amount, description: TRANSACTION.description });
  expect(api.writes.filter((w) => w.path.endsWith("/restore"))).toHaveLength(1);
});
