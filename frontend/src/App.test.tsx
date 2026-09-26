import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "./App";
import { ToastProvider } from "./components/ui";

/**
 * Smoke test for the app shell and routing.
 *
 * Broader accessibility/component tests (axe, breakpoint snapshot, keyboard
 * navigation) are task 19.3. This test only proves the shell renders its
 * navigation landmarks and that routes render their stub content.
 */
function renderAt(path: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </ToastProvider>,
  );
}

describe("App shell", () => {
  it("renders the primary navigation landmark and the app name", () => {
    renderAt("/");
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/logstead/i)).toBeInTheDocument();
  });

  it("renders the Dashboard stub at the index route", () => {
    renderAt("/");
    expect(
      screen.getByRole("heading", { name: /dashboard/i }),
    ).toBeInTheDocument();
  });

  it("renders the Properties stub at /properties", () => {
    renderAt("/properties");
    expect(
      screen.getByRole("heading", { name: /properties/i }),
    ).toBeInTheDocument();
  });

  it("renders a per-property section stub with sub-navigation", () => {
    renderAt("/properties/abc-123/transactions");
    expect(
      screen.getByRole("heading", { name: /transactions/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: /property sections/i }),
    ).toBeInTheDocument();
  });

  it("provides a skip-to-main-content link", () => {
    renderAt("/");
    expect(
      screen.getByRole("link", { name: /skip to main content/i }),
    ).toBeInTheDocument();
  });
});
