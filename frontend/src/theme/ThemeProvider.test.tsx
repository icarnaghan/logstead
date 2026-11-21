import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeProvider";
import { ThemeToggle } from "../components/ThemeToggle";

/**
 * Tests for the theme system: system default, explicit preference persistence,
 * and applying the `.dark` class to <html>.
 */

function setSystemDark(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
}

function Probe() {
  const { preference, resolved } = useTheme();
  return (
    <div>
      <span data-testid="pref">{preference}</span>
      <span data-testid="resolved">{resolved}</span>
    </div>
  );
}

beforeEach(() => {
  document.documentElement.classList.remove("dark");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ThemeProvider", () => {
  it("defaults to system preference and resolves dark when the OS prefers dark", () => {
    setSystemDark(true);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("pref").textContent).toBe("system");
    expect(screen.getByTestId("resolved").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("resolves light when the OS prefers light", () => {
    setSystemDark(false);
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("resolved").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("persists an explicit dark choice and applies the class", async () => {
    setSystemDark(false);
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
        <Probe />
      </ThemeProvider>,
    );

    await user.click(screen.getByRole("radio", { name: "Dark" }));

    expect(screen.getByTestId("pref").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("logstead.theme")).toBe("dark");
  });

  it("reads a persisted preference on load", () => {
    setSystemDark(false);
    localStorage.setItem("logstead.theme", "dark");
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("pref").textContent).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("clears storage when switching back to system", async () => {
    setSystemDark(false);
    localStorage.setItem("logstead.theme", "dark");
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole("radio", { name: "System" }));
    expect(localStorage.getItem("logstead.theme")).toBeNull();
  });
});
