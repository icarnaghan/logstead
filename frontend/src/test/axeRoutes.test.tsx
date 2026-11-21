// The fetch stub must be evaluated before any module that constructs
// `ApiClient` (which binds `globalThis.fetch` at construction).
import "./apiStub";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ToastProvider } from "../components/ui";
import { APP_ROUTES, leafPaths } from "../routes";
import { ThemeProvider } from "../theme/ThemeProvider";
import { BUSINESS, BUSINESS_ID, PROPERTY, PROPERTY_ID } from "./fixtures";

/**
 * Axe_Suite (Requirements 25.6, 25.7, 4.6): every routed page, in both themes,
 * has exactly one `h1` and no axe violations. `color-contrast` is disabled
 * because jsdom cannot resolve the stylesheet; contrast is covered by the token
 * test instead.
 */

const SAMPLE_PARAMS: Readonly<Record<string, string>> = {
  propertyId: PROPERTY_ID,
  businessId: BUSINESS_ID,
};

/** Pages rendered inside `ImportsLayout`, which owns their `h1`. */
const NO_OWN_H1 = new Set(["/imports/schedule-e", "/imports/schedule-e/extract"]);

const THEMES = ["light", "dark"] as const;

function concretePath(route: string): string {
  if (route === "/*") return "/no-such-page";
  return route.replace(/:([A-Za-z0-9_]+)/g, (_match, name: string) => {
    const sample = SAMPLE_PARAMS[name];
    if (sample === undefined) {
      throw new Error(
        `Axe_Suite: route "${route}" has parameter ":${name}" with no entry in SAMPLE_PARAMS`,
      );
    }
    return sample;
  });
}

function setTheme(theme: (typeof THEMES)[number]): void {
  // ThemeProvider follows the system preference by default and re-applies the
  // `dark` class from it, so drive matchMedia as well as the class itself.
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: theme === "dark",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
  document.documentElement.classList.toggle("dark", theme === "dark");
}

const ROUTES = leafPaths(APP_ROUTES);

/**
 * Routed pages that need a query string to show their populated state, and
 * overlays opened over a page (Requirements 28.2-28.5). Each runs in both
 * themes with one `h1` and no axe violations.
 */
interface OverlayCase {
  readonly name: string;
  readonly path: string;
  /** Drives the page until the state under test is shown. */
  readonly open: (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  /** When true the check runs on `document.body` (portals) instead of the container. */
  readonly portal: boolean;
}

const OVERLAY_CASES: readonly OverlayCase[] = [
  {
    name: "search page with a query",
    path: "/search?q=oak",
    portal: false,
    open: async () => {
      await screen.findByRole("link", { name: /Oak Street Duplex/ });
    },
  },
  {
    name: "activity page",
    path: "/activity",
    portal: false,
    open: async () => undefined,
  },
  {
    name: "command palette open",
    path: "/properties",
    portal: true,
    open: async (user) => {
      await user.click(await screen.findByRole("button", { name: "Search" }));
      await screen.findByRole("dialog", { name: "Command palette" });
    },
  },
  {
    name: "shortcuts help open",
    path: "/properties",
    portal: true,
    open: async (user) => {
      await user.keyboard("?");
      await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    },
  },
  {
    name: "setup guide on the dashboard",
    path: "/",
    portal: false,
    open: async () => {
      await screen.findByRole("region", { name: "Get set up" });
    },
  },
];

describe("Axe_Suite overlay and query states", () => {
  describe.each(OVERLAY_CASES)("$name", (overlay) => {
    describe.each(THEMES)("%s theme", (theme) => {
      beforeEach(() => setTheme(theme));
      afterEach(() => {
        vi.unstubAllGlobals();
        document.documentElement.classList.remove("dark");
      });

      it("has one h1 and no axe violations", async () => {
        const user = userEvent.setup();
        const { container } = render(
          <ToastProvider>
            <ThemeProvider>
              <MemoryRouter initialEntries={[overlay.path]}>
                <App />
              </MemoryRouter>
            </ThemeProvider>
          </ToastProvider>,
        );
        await waitFor(() =>
          expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThan(0),
        );
        // Modal overlays hide the page from the accessibility tree, so check the h1 first.
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
        await overlay.open(user);
        const results = await axe(overlay.portal ? document.body : container, {
          rules: { "color-contrast": { enabled: false } },
        });
        expect(results).toHaveNoViolations();
      });
    });
  });
});

describe("Axe_Suite", () => {
  it("covers every route with a sample for each parameter", () => {
    expect(ROUTES.length).toBeGreaterThan(0);
    for (const route of ROUTES) {
      expect(() => concretePath(route)).not.toThrow();
    }
  });

  describe.each(ROUTES)("route %s", (route) => {
    describe.each(THEMES)("%s theme", (theme) => {
      beforeEach(() => setTheme(theme));
      afterEach(() => {
        vi.unstubAllGlobals();
        document.documentElement.classList.remove("dark");
      });

      it("has one h1 and no axe violations", async () => {
        const path = concretePath(route);
        const { container } = render(
          <ToastProvider>
            <ThemeProvider>
              <MemoryRouter initialEntries={[path]}>
                <App />
              </MemoryRouter>
            </ThemeProvider>
          </ToastProvider>,
        );

        await waitFor(() =>
          expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThan(0),
        );
        // Let the page's data settle so axe sees the loaded state.
        await waitFor(
          () =>
            expect(document.querySelector('[aria-busy="true"]')).toBeNull(),
          { timeout: 3000 },
        ).catch(() => undefined);

        if (!NO_OWN_H1.has(route)) {
          expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
        }
        expect(document.documentElement.classList.contains("dark")).toBe(
          theme === "dark",
        );

        const results = await axe(container, {
          rules: { "color-contrast": { enabled: false } },
        });
        expect(results).toHaveNoViolations();
      });
    });
  });
});

/**
 * Dialog states (Requirements 25.6, 25.7, 25.8): every migrated record dialog,
 * the discard confirmation and the mobile drawer, opened in both themes, has
 * no axe violations. Axe runs on `document.body` because dialogs render in a
 * portal outside the render container.
 */
interface DialogCase {
  readonly name: string;
  readonly path: string;
  /** Drives the page until the dialog under test is open. */
  readonly open: (user: ReturnType<typeof userEvent.setup>) => Promise<void>;
  /** Accessible name of the dialog that must be present. */
  readonly dialog: string | RegExp;
}

const clickButton = async (
  user: ReturnType<typeof userEvent.setup>,
  name: string | RegExp,
) => {
  await user.click(await screen.findByRole("button", { name }));
};

const addDialog = (
  name: string,
  path: string,
  button: string | RegExp,
  dialog: string | RegExp,
): DialogCase => ({
  name,
  path,
  dialog,
  open: (user) => clickButton(user, button),
});

const propertyBase = `/properties/${PROPERTY_ID}`;

const DIALOG_CASES: readonly DialogCase[] = [
  addDialog("Add transaction", `${propertyBase}/transactions`, "Add transaction", "Add transaction"),
  addDialog("Add loan", `${propertyBase}/loans`, "Add loan", "Add loan"),
  addDialog("Add asset", `${propertyBase}/assets`, "Add asset", "Add asset"),
  addDialog("Add property", "/properties", "Add property", "Add a property"),
  addDialog("Add business", "/businesses", "Add business", "Add a business"),
  {
    name: "Edit property",
    path: "/properties",
    dialog: "Edit property",
    open: async (user) => {
      await clickButton(user, `More actions for ${PROPERTY.name}`);
      await user.click(await screen.findByRole("menuitem", { name: /edit/i }));
    },
  },
  {
    name: "Edit business",
    path: `/businesses/${BUSINESS_ID}`,
    dialog: "Edit business",
    open: async (user) => {
      await waitFor(() =>
        expect(screen.getByRole("heading", { level: 1, name: BUSINESS.legal_name })).toBeTruthy(),
      );
      await clickButton(user, "Edit");
    },
  },
  {
    name: "Discard confirmation",
    path: `${propertyBase}/transactions`,
    dialog: "Discard changes?",
    open: async (user) => {
      await clickButton(user, "Add transaction");
      const dialog = await screen.findByRole("dialog", { name: "Add transaction" });
      await user.type(await screen.findByLabelText(/^Description/), "unsaved note");
      expect(dialog).toBeTruthy();
      await user.keyboard("{Escape}");
    },
  },
  {
    name: "Mobile drawer",
    path: "/properties",
    dialog: "Menu",
    open: (user) => clickButton(user, "Open navigation menu"),
  },
];

describe("Axe_Suite dialog states", () => {
  describe.each(DIALOG_CASES)("$name", (dialogCase) => {
    describe.each(THEMES)("%s theme", (theme) => {
      beforeEach(() => setTheme(theme));
      afterEach(() => {
        vi.unstubAllGlobals();
        document.documentElement.classList.remove("dark");
      });

      it("has no axe violations while open", async () => {
        const user = userEvent.setup();
        render(
          <ToastProvider>
            <ThemeProvider>
              <MemoryRouter initialEntries={[dialogCase.path]}>
                <App />
              </MemoryRouter>
            </ThemeProvider>
          </ToastProvider>,
        );
        await waitFor(() =>
          expect(screen.getAllByRole("heading", { level: 1 }).length).toBeGreaterThan(0),
        );
        await dialogCase.open(user);
        const dialog =
          (await screen.findByRole("dialog", { name: dialogCase.dialog }).catch(() => null)) ??
          (await screen.findByRole("alertdialog", { name: dialogCase.dialog }));
        expect(dialog).toBeTruthy();
        expect(document.documentElement.classList.contains("dark")).toBe(
          theme === "dark",
        );
        const results = await axe(document.body, {
          rules: { "color-contrast": { enabled: false } },
        });
        expect(results).toHaveNoViolations();
      });
    });
  });
});
