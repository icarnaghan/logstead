import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { StateBlock } from "./StateBlock";
import { FOCUS_RING } from "./focusRing";

/**
 * Unit + axe tests for the shared StateBlock primitive
 * (task 3.8, Requirements 9.1, 9.2).
 */

describe("StateBlock — loading (Req 9.1)", () => {
  it("renders a role=status region with the title", () => {
    render(<StateBlock kind="loading" title="Loading transactions…" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Loading transactions…");
  });
});

describe("StateBlock — empty (Req 9.2)", () => {
  it("renders a heading and description", () => {
    render(
      <MemoryRouter>
        <StateBlock
          kind="empty"
          title="No transactions yet"
          description="Add your first transaction to start tracking income and expenses."
        />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "No transactions yet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Add your first transaction/),
    ).toBeInTheDocument();
  });

  it("renders the action as a react-router link when `to` is set", () => {
    render(
      <MemoryRouter>
        <StateBlock
          kind="empty"
          title="No transactions yet"
          action={{ label: "Add transaction", to: "/properties/p1/transactions/new" }}
        />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "Add transaction" });
    expect(link).toHaveAttribute("href", "/properties/p1/transactions/new");
    // The action carries the canonical focus ring.
    for (const cls of FOCUS_RING.split(" ")) {
      expect(link).toHaveClass(cls);
    }
  });

  it("renders the action as a button when `onClick` is set", async () => {
    const onClick = vi.fn();
    render(
      <MemoryRouter>
        <StateBlock
          kind="empty"
          title="No assets yet"
          action={{ label: "Add asset", onClick }}
        />
      </MemoryRouter>,
    );
    const button = screen.getByRole("button", { name: "Add asset" });
    for (const cls of FOCUS_RING.split(" ")) {
      expect(button).toHaveClass(cls);
    }
    await userEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders no action when none is provided", () => {
    render(
      <MemoryRouter>
        <StateBlock kind="empty" title="No reports yet" />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("StateBlock — error (Req 7.1-7.6)", () => {
  it("renders role=alert with title, message and danger tokens", () => {
    render(<StateBlock kind="error" title="Couldn't load" description="Try again." />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load");
    expect(alert).toHaveTextContent("Try again.");
    expect(alert).toHaveClass("border-danger", "bg-danger-subtle");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("calls onRetry and shows loading until the promise resolves", async () => {
    let resolve!: () => void;
    const onRetry = vi.fn(
      () => new Promise<void>((r) => { resolve = r; }),
    );
    render(<StateBlock kind="error" title="Failed" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    resolve();
    await waitFor(() =>
      expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy"),
    );
  });

  it("clears loading when onRetry rejects", async () => {
    const onRetry = vi.fn(() => Promise.reject(new Error("x")));
    render(<StateBlock kind="error" title="Failed" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy"),
    );
  });

  it("shows loading while `retrying` is true", () => {
    render(<StateBlock kind="error" title="Failed" onRetry={() => {}} retrying />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
  });

  it("renders a single-row banner when compact", () => {
    render(<StateBlock kind="error" title="Failed" compact />);
    expect(screen.getByRole("alert")).toHaveClass(
      "flex", "items-center", "gap-3", "rounded-md", "border",
    );
  });

  it("compact error keeps the Retry button and calls onRetry", async () => {
    const onRetry = vi.fn();
    render(<StateBlock kind="error" title="Failed" compact onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("has no axe violations for the compact error", async () => {
    const { container } = render(
      <StateBlock kind="error" title="Failed" description="Oops" compact onRetry={() => {}} />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("loading shows a spinner alongside the title", () => {
    const { container } = render(<StateBlock kind="loading" title="Loading…" />);
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <StateBlock kind="error" title="Failed" description="Oops" onRetry={() => {}} />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});

describe("StateBlock — accessibility", () => {
  it("has no axe violations for the loading state", async () => {
    const { container } = render(
      <StateBlock kind="loading" title="Loading transactions…" />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });

  it("has no axe violations for the empty state with an action link", async () => {
    const { container } = render(
      <MemoryRouter>
        <StateBlock
          kind="empty"
          title="No transactions yet"
          description="Add your first transaction."
          action={{ label: "Add transaction", to: "/properties/p1/transactions/new" }}
        />
      </MemoryRouter>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
