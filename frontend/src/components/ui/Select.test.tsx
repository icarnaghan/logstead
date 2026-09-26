import { render, screen } from "@testing-library/react";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { Select } from "./Select";

/**
 * Unit + axe tests for the shared Select primitive
 * (task 3.4, Requirements 1.3, 8.5).
 */

describe("Select — base styling (Req 1.3, 8.5)", () => {
  it("applies token-only base classes and the focus ring", () => {
    render(
      <Select aria-label="Tax year">
        <option value="2024">2024</option>
      </Select>,
    );
    const select = screen.getByLabelText("Tax year");
    expect(select).toHaveClass("rounded-md");
    expect(select).toHaveClass("border-border");
    expect(select).toHaveClass("bg-surface");
    expect(select).toHaveClass("text-fg");
    expect(select).toHaveClass("focus-visible:outline-accent");
  });

  it("renders option children", () => {
    render(
      <Select aria-label="Tax year">
        <option value="2023">2023</option>
        <option value="2024">2024</option>
      </Select>,
    );
    expect(screen.getByRole("option", { name: "2023" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "2024" })).toBeInTheDocument();
  });

  it("forwards native props", () => {
    render(
      <Select aria-label="Tax year" defaultValue="2024">
        <option value="2023">2023</option>
        <option value="2024">2024</option>
      </Select>,
    );
    expect(screen.getByLabelText("Tax year")).toHaveValue("2024");
  });
});

describe("Select — invalid state (Req 8.5)", () => {
  it("sets aria-invalid and a danger border when invalid", () => {
    render(
      <Select aria-label="Tax year" invalid>
        <option value="2024">2024</option>
      </Select>,
    );
    const select = screen.getByLabelText("Tax year");
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(select).toHaveClass("border-danger");
  });

  it("does not set aria-invalid when valid", () => {
    render(
      <Select aria-label="Tax year">
        <option value="2024">2024</option>
      </Select>,
    );
    expect(screen.getByLabelText("Tax year")).not.toHaveAttribute(
      "aria-invalid",
    );
  });
});

describe("Select — accessibility", () => {
  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <label htmlFor="tax-year">Tax year</label>
        <Select id="tax-year">
          <option value="2023">2023</option>
          <option value="2024">2024</option>
        </Select>
      </div>,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
