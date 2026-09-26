import { render, screen } from "@testing-library/react";
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
