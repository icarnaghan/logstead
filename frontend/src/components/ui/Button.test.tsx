import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Button } from "./Button";

/**
 * Unit + axe tests for the shared Button primitive
 * (task 3.2, Requirements 1.1, 1.2, 1.6, 8.5).
 */

describe("Button — variants (Req 1.1)", () => {
  it("renders the primary variant with accent token classes", () => {
    render(<Button variant="primary">Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveClass("bg-accent");
    expect(button).toHaveClass("text-accent-fg");
    expect(button).toHaveClass("hover:bg-accent-hover");
  });

  it("renders the secondary variant with surface/border token classes", () => {
    render(<Button variant="secondary">Cancel</Button>);
    const button = screen.getByRole("button", { name: "Cancel" });
    expect(button).toHaveClass("border-border");
    expect(button).toHaveClass("bg-surface");
    expect(button).toHaveClass("text-fg-muted");
    expect(button).toHaveClass("hover:bg-surface-muted");
  });

  it("defaults to the secondary variant", () => {
    render(<Button>Default</Button>);
    const button = screen.getByRole("button", { name: "Default" });
    expect(button).toHaveClass("bg-surface");
    expect(button).toHaveClass("text-fg-muted");
  });

  it("renders the danger variant with danger token classes", () => {
    render(<Button variant="danger">Delete</Button>);
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toHaveClass("border-danger");
    expect(button).toHaveClass("text-danger");
    expect(button).toHaveClass("hover:bg-danger-subtle");
  });
});

describe("Button — focus ring + sizes (Req 1.2, 8.5)", () => {
  it("applies the canonical focus ring", () => {
    render(<Button>Focus</Button>);
    expect(screen.getByRole("button", { name: "Focus" })).toHaveClass(
      "focus-visible:outline-accent",
    );
  });

  it("applies size classes", () => {
    const { rerender } = render(<Button size="sm">Small</Button>);
    expect(screen.getByRole("button", { name: "Small" })).toHaveClass("py-1.5");
    rerender(<Button size="md">Medium</Button>);
    expect(screen.getByRole("button", { name: "Medium" })).toHaveClass("py-2");
  });
});

describe("Button — asChild + disabled (Req 8.5)", () => {
  it("renders the child element when asChild is set", () => {
    render(
      <Button asChild variant="primary">
        <a href="/properties">All properties</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "All properties" });
    expect(link).toHaveAttribute("href", "/properties");
    // The child inherits the button styling.
    expect(link).toHaveClass("bg-accent");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reflects the disabled state", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button", { name: "Disabled" })).toBeDisabled();
  });
});

describe("Button — accessibility", () => {
  it("has no axe violations across variants", async () => {
    const { container } = render(
      <div>
        <Button variant="primary">Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="danger">Danger</Button>
      </div>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
