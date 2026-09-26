import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Card, Tile } from "./Card";

/**
 * Unit + axe tests for the shared Card + Tile primitives
 * (task 3.4, Requirements 1.3, 8.1, 8.4).
 */

describe("Card — base styling (Req 1.3, 8.1, 8.4)", () => {
  it("applies token-only elevation base classes", () => {
    render(<Card data-testid="card">Body</Card>);
    const card = screen.getByTestId("card");
    expect(card).toHaveClass("rounded-lg");
    expect(card).toHaveClass("border-border");
    expect(card).toHaveClass("bg-surface");
    expect(card).toHaveClass("shadow-card");
  });

  it("renders as a div by default", () => {
    render(<Card data-testid="card">Body</Card>);
    expect(screen.getByTestId("card").tagName).toBe("DIV");
  });

  it("renders as a section when as='section'", () => {
    render(
      <Card as="section" data-testid="card">
        Body
      </Card>,
    );
    expect(screen.getByTestId("card").tagName).toBe("SECTION");
  });

  it("merges the caller-supplied className", () => {
    render(
      <Card className="p-6" data-testid="card">
        Body
      </Card>,
    );
    const card = screen.getByTestId("card");
    expect(card).toHaveClass("p-6");
    expect(card).toHaveClass("shadow-card");
  });
});

describe("Tile — labelled heading (Req 1.3, 8.4)", () => {
  it("renders a section labelled by the heading id", () => {
    render(
      <Tile title="Summary" headingId="tile-summary">
        <p>Content</p>
      </Tile>,
    );
    const section = screen.getByRole("region", { name: "Summary" });
    expect(section.tagName).toBe("SECTION");
    expect(section).toHaveAttribute("aria-labelledby", "tile-summary");
  });

  it("renders the heading text with the matching id", () => {
    render(
      <Tile title="Summary" headingId="tile-summary">
        <p>Content</p>
      </Tile>,
    );
    const heading = screen.getByRole("heading", { name: "Summary" });
    expect(heading).toHaveAttribute("id", "tile-summary");
  });

  it("renders its children below the heading", () => {
    render(
      <Tile title="Summary" headingId="tile-summary">
        <p>Content</p>
      </Tile>,
    );
    expect(screen.getByText("Content")).toBeInTheDocument();
  });
});

describe("Card + Tile — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <Card>Elevated surface</Card>
        <Tile title="Summary" headingId="tile-summary">
          <p>Content</p>
        </Tile>
      </div>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
