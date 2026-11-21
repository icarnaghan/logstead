import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, Link } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppErrorBoundary } from "./AppErrorBoundary";

const SECRET = "secret-id-123 at /internal/path";
let shouldThrow = true;

function Bomb() {
  if (shouldThrow) throw new Error(SECRET);
  return <p>Recovered content</p>;
}

describe("AppErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = true;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders a safe fallback without leaking the error text", () => {
    const { container } = render(
      <AppErrorBoundary>
        <Bomb />
      </AppErrorBoundary>,
    );
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: /something went wrong/i })).toHaveFocus();
    expect(container.textContent).not.toContain("secret-id-123");
    expect(container.textContent).not.toMatch(/internal\/path|at Bomb|Error:/);
    expect(screen.getByRole("link", { name: /go to dashboard/i })).toHaveAttribute("href", "/");
  });

  it("Try again re-renders the children", () => {
    render(
      <AppErrorBoundary>
        <Bomb />
      </AppErrorBoundary>,
    );
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("Recovered content")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("route-scoped boundary keyed by path resets on navigation and keeps the shell", () => {
    function Shell() {
      return (
        <div>
          <nav>
            <Link to="/ok">ok</Link>
          </nav>
          <Routes>
            <Route path="/bad" element={<AppErrorBoundary key="bad" scope="route"><Bomb /></AppErrorBoundary>} />
            <Route path="/ok" element={<AppErrorBoundary key="ok" scope="route"><p>Fine page</p></AppErrorBoundary>} />
          </Routes>
        </div>
      );
    }
    render(
      <MemoryRouter initialEntries={["/bad"]}>
        <Shell />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "ok" }));
    expect(screen.getByText("Fine page")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
