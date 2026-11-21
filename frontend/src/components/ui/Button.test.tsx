import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

describe("Button — loading, ghost, icon (Req 3.1-3.8)", () => {
  it("sets aria-busy, shows a spinner, and keeps the label readable", () => {
    const { container } = render(<Button loading>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(button).toHaveTextContent("Save");
  });

  it("does not set aria-busy when not loading", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy");
  });

  it("keeps width: label stays in flow (invisible), spinner is overlaid", () => {
    const { container } = render(<Button loading>Save</Button>);
    const button = screen.getByRole("button");
    expect(button).toHaveClass("relative");
    expect(screen.getByText("Save")).toHaveClass("opacity-0");
    const svg = container.querySelector("svg")!;
    expect(svg.parentElement).toHaveClass("absolute", "inset-0");
  });

  it("ignores clicks while loading", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Save
      </Button>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("calls onClick when not loading", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("blocks form submission while loading and allows it otherwise", async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const { rerender } = render(
      <form onSubmit={onSubmit}>
        <Button type="submit" loading>
          Save
        </Button>
      </form>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onSubmit).not.toHaveBeenCalled();

    rerender(
      <form onSubmit={onSubmit}>
        <Button type="submit">Save</Button>
      </form>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("renders the ghost variant with token classes", () => {
    render(<Button variant="ghost">Ghost</Button>);
    const button = screen.getByRole("button", { name: "Ghost" });
    expect(button).toHaveClass("bg-transparent", "text-fg-muted");
    expect(button).toHaveClass("hover:bg-accent-subtle", "hover:text-accent");
  });

  it("applies icon size classes", () => {
    render(<Button size="icon" aria-label="Close" />);
    const button = screen.getByRole("button", { name: "Close" });
    expect(button).toHaveClass("h-9", "w-9", "p-0");
    expect(button).toHaveClass("max-md:h-11", "max-md:w-11");
  });

  describe("dev warning", () => {
    let warn: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    });
    afterEach(() => warn.mockRestore());

    it("warns once per mount for an unnamed icon button", () => {
      const { rerender } = render(<Button size="icon" />);
      rerender(<Button size="icon" className="x" />);
      expect(warn).toHaveBeenCalledTimes(1);
    });

    it.each([
      ["aria-label", { "aria-label": "Close" }],
      ["aria-labelledby", { "aria-labelledby": "lbl" }],
      ["title", { title: "Close" }],
    ])("is silent when an accessible name is given via %s", (_n, attrs) => {
      render(<Button size="icon" {...attrs} />);
      expect(warn).not.toHaveBeenCalled();
    });

    it("is silent for non-icon buttons", () => {
      render(<Button>Text</Button>);
      expect(warn).not.toHaveBeenCalled();
    });
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
