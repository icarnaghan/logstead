// @vitest-environment jsdom
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { axe } from "vitest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Property } from "../../api/properties";
import { NavigationGuardProvider } from "../../lib/navigationGuard";
import { SetupGuideProvider } from "../../lib/setupGuide";
import { ThemeProvider } from "../../theme/ThemeProvider";
import { ShellPropertiesProvider } from "../ShellPropertiesContext";
import { ShortcutsProvider } from "../shortcuts/ShortcutsProvider";
import { PaletteProvider } from "./PaletteProvider";

function prop(id: string, name: string): Property {
  return { id, name } as Property;
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

interface Options {
  path?: string;
  properties?: Property[];
  load?: () => Promise<Property[]>;
  setupGuide?: () => void;
}

function renderPalette({
  path = "/",
  properties = [prop("p1", "Maple House")],
  load,
  setupGuide,
}: Options = {}) {
  const loader = load ?? (() => Promise.resolve(properties));
  let tree: ReactNode = (
    <PaletteProvider
      loadProperties={() => Promise.resolve([])}
      loadEarliest={() => Promise.resolve(null)}
      search={() =>
        Promise.resolve({ query: "", groups: [], truncated: false, scanned: 0 })
      }
    >
      <button type="button">Opener</button>
      <h1 id="page-heading" tabIndex={-1}>
        Page
      </h1>
      <Where />
    </PaletteProvider>
  );
  if (setupGuide) {
    tree = (
      <SetupGuideProvider showSetupGuide={setupGuide} resetSignal={0}>
        {tree}
      </SetupGuideProvider>
    );
  }
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ThemeProvider>
        <ShellPropertiesProvider load={loader}>
          <NavigationGuardProvider>
            <ShortcutsProvider>
              <Routes>
                <Route path="*" element={tree} />
              </Routes>
            </ShortcutsProvider>
          </NavigationGuardProvider>
        </ShellPropertiesProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

async function openWithChord(user: ReturnType<typeof userEvent.setup>) {
  // Let the shell property list resolve before opening.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await user.keyboard("{Control>}k{/Control}");
  return screen.findByRole("combobox");
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
  window.localStorage.clear();
});

describe("CommandPalette", () => {
  it("opens with the chord, closes with the chord and Escape, and returns focus", async () => {
    const user = userEvent.setup();
    renderPalette();
    screen.getByRole("button", { name: "Opener" }).focus();

    const input = await openWithChord(user);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toHaveAttribute(
      "data-palette",
    );
    expect(input).toHaveFocus();

    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Opener" })).toHaveFocus();

    await openWithChord(user);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Opener" })).toHaveFocus();
  });

  it("exposes combobox, listbox, group and option semantics for the empty query", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    renderPalette();
    const input = await openWithChord(user);

    const listbox = screen.getByRole("listbox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", listbox.id);
    expect(screen.getAllByRole("group").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("option", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Add property/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Download backup/ })).toBeInTheDocument();
    // Empty query lists pages and actions only, and makes no request.
    expect(screen.queryByRole("option", { name: /Tax year/ })).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(/\d+ results/);
  });

  it("moves the highlight with wrapped arrows, Home and End and runs with Enter", async () => {
    const user = userEvent.setup();
    renderPalette();
    const input = await openWithChord(user);
    const options = screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);

    await user.keyboard("{ArrowUp}");
    expect(input).toHaveAttribute("aria-activedescendant", options[options.length - 1].id);
    expect(input).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    await user.keyboard("{End}");
    expect(input).toHaveAttribute("aria-activedescendant", options[options.length - 1].id);
    await user.keyboard("{Home}");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/properties");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("filters by query, announces the count and shows No results", async () => {
    const user = userEvent.setup();
    renderPalette();
    await openWithChord(user);

    await user.keyboard("maple");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("1 result");

    await user.keyboard("zzzz");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("No results"),
    );
  });

  it("navigates to a destination and leaves focus to the route", async () => {
    const user = userEvent.setup();
    renderPalette();
    screen.getByRole("button", { name: "Opener" }).focus();
    await openWithChord(user);
    await user.keyboard("reports");
    await user.click(screen.getByRole("option", { name: "Reports" }));

    expect(screen.getByTestId("where")).toHaveTextContent("/reports");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Opener" })).not.toHaveFocus();
  });

  it("uses the active property for property-scoped actions", async () => {
    const user = userEvent.setup();
    renderPalette({ path: "/properties/p1/loans", properties: [prop("p1", "Maple House"), prop("p2", "Oak")] });
    await openWithChord(user);
    await user.keyboard("add transaction{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/properties/p1/transactions?new=1",
    );
  });

  it("shows a property picker for several properties and returns with Escape", async () => {
    const user = userEvent.setup();
    renderPalette({ properties: [prop("p1", "Maple House"), prop("p2", "Oak Cottage")] });
    await openWithChord(user);
    await user.keyboard("add repair{Enter}");

    expect(screen.getByRole("combobox")).toHaveAccessibleName("Choose a property");
    expect(screen.getAllByRole("option")).toHaveLength(2);

    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveAccessibleName("Search or run a command");

    await user.keyboard("add repair{Enter}");
    await user.keyboard("{ArrowDown}{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/properties/p2/repairs?new=1");
  });

  it("goes back from the picker with Backspace on an empty field", async () => {
    const user = userEvent.setup();
    renderPalette({ properties: [prop("p1", "A"), prop("p2", "B")] });
    await openWithChord(user);
    await user.keyboard("add loan{Enter}");
    expect(screen.getByRole("combobox")).toHaveAccessibleName("Choose a property");
    await user.keyboard("{Backspace}");
    expect(screen.getByRole("combobox")).toHaveAccessibleName("Search or run a command");
  });

  it("shows property-scoped actions as unavailable with the reason and does not navigate", async () => {
    const user = userEvent.setup();
    renderPalette({ properties: [] });
    await openWithChord(user);
    const option = screen.getByRole("option", { name: /Add loan/ });
    expect(option).toHaveAttribute("aria-disabled", "true");
    expect(option).toHaveTextContent("Add a property first");
    await user.click(option);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/);
  });

  it("notes that properties are loading or failed to load", async () => {
    const user = userEvent.setup();
    renderPalette({ load: () => Promise.reject(new Error("boom")) });
    await openWithChord(user);
    expect(await screen.findByText("Properties could not be loaded.")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("toggles the theme and keeps the palette closed", async () => {
    const user = userEvent.setup();
    renderPalette();
    await openWithChord(user);
    await user.keyboard("switch theme{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.localStorage.getItem("logstead.theme")).not.toBeNull();
  });

  it("goes to the profile backup focus target for Download backup", async () => {
    const user = userEvent.setup();
    renderPalette();
    await openWithChord(user);
    await user.keyboard("download backup{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/profile?focus=backup");
  });

  it("opens the shortcuts help from the action", async () => {
    const user = userEvent.setup();
    renderPalette();
    screen.getByRole("button", { name: "Opener" }).focus();
    await openWithChord(user);
    await user.keyboard("keyboard shortcuts{Enter}");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("lists Show setup guide only when a handler is provided and calls it", async () => {
    const user = userEvent.setup();
    const first = renderPalette();
    await openWithChord(user);
    expect(screen.queryByRole("option", { name: /Show setup guide/ })).toBeNull();
    first.unmount();

    const handler = vi.fn();
    renderPalette({ setupGuide: handler });
    await openWithChord(user);
    await user.keyboard("setup guide{Enter}");
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("opens through the registered handlers with an initial query", async () => {
    renderPalette();
    // Same entry point the header button will use.
    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "/", bubbles: true }),
      );
    });
    expect(await screen.findByRole("combobox")).toHaveValue("");
  });

  it.each(["light", "dark"] as const)("has no axe violations in the %s theme", async (theme) => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    const user = userEvent.setup();
    renderPalette();
    await openWithChord(user);
    const options = { rules: { "color-contrast": { enabled: false } } };
    expect(await axe(document.body, options)).toHaveNoViolations();
    await user.keyboard("maple");
    expect(await axe(document.body, options)).toHaveNoViolations();
  });
});
