import { defineConfig, devices } from "@playwright/test";
/**
 * Browser a11y and smoke checks (review.md R8, S10, R11). Runs the Vite dev server with the API
 * base URL pointed at a non-routable host; every request to it is answered by
 * `page.route` in `e2e/fixtures.ts`, so no real AWS endpoint is ever called.
 */
const PORT = 4173;
export const API_BASE_URL = "https://api.e2e.invalid";
/** Test Cognito values for the sign-in smoke spec. Nothing resolves this host. */
export const COGNITO_DOMAIN = "https://auth.e2e.invalid";
export const COGNITO_CLIENT_ID = "e2e-client-id";
export const COGNITO_REDIRECT_URI = `http://localhost:${PORT}/auth/callback`;
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  // The Vite dev server compiles on first hit; 5s is too tight under parallel load.
  expect: { timeout: 15_000 },
  forbidOnly: !!process.env.CI,
  // One retry locally too: axe scans can lose their execution context under parallel load.
  retries: process.env.CI ? 2 : 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    trace: "retain-on-failure",
    serviceWorkers: "block",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      VITE_API_BASE_URL: API_BASE_URL,
      VITE_COGNITO_DOMAIN: COGNITO_DOMAIN,
      VITE_COGNITO_CLIENT_ID: COGNITO_CLIENT_ID,
      VITE_COGNITO_REDIRECT_URI: COGNITO_REDIRECT_URI,
    },
  },
});
