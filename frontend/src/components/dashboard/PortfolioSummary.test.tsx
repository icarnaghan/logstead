import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";
import { PortfolioSummary } from "./PortfolioSummary";
import type { DashboardSummary } from "../../api/dashboard";

/**
 * Component tests for {@link PortfolioSummary} (task 24.3, Requirement 11.1).
 *
 * Verifies the portfolio-level total income / expenses / net render with money
 * formatted (including negatives), that the net is labelled "Net income" for a
 * positive figure and "Net loss" for a negative one with a visible loss cue
 * (not sign/colour alone), and that the summary is numbers-only — no chart,
 * canvas, or svg. Includes an axe check (dashboard-area accessibility).
 */

function makeSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    tax_year: 2024,
    has_properties: true,
    total_income: "24000.00",
    total_expenses: "7175.33",
    net: "16824.67",
    properties: [],
    empty_state_prompt: null,
    ...overrides,
  };
}

describe("PortfolioSummary — totals (Req 11.1)", () => {
  it("renders total income, total expenses, and net formatted as money", () => {
    render(<PortfolioSummary summary={makeSummary()} />);

    const region = screen.getByRole("region", {
      name: /portfolio totals for 2024/i,
    });
    const incomeLabel = within(region).getByText("Total income");
    expect(incomeLabel.nextElementSibling).toHaveTextContent("$24,000.00");
    const expensesLabel = within(region).getByText("Total expenses");
    expect(expensesLabel.nextElementSibling).toHaveTextContent("$7,175.33");
    expect(within(region).getByText("$16,824.67")).toBeInTheDocument();
  });

  it("labels a positive net 'Net income'", () => {
    render(<PortfolioSummary summary={makeSummary()} />);

    expect(screen.getByText("Net income")).toBeInTheDocument();
    expect(screen.queryByText("Net loss")).not.toBeInTheDocument();
  });
});

describe("PortfolioSummary — net loss (Req 11.1, 14.4)", () => {
  it("labels a negative net 'Net loss', formats the negative amount, and shows a loss cue", () => {
    render(
      <PortfolioSummary
        summary={makeSummary({
          total_income: "1000.00",
          total_expenses: "1500.00",
          net: "-500.00",
        })}
      />,
    );

    expect(screen.getByText("Net loss")).toBeInTheDocument();
    expect(screen.queryByText("Net income")).not.toBeInTheDocument();
    expect(screen.getByText("-$500.00")).toBeInTheDocument();
    // A textual "Loss" cue is present so a loss is not conveyed by sign alone.
    expect(screen.getByText("Loss")).toBeInTheDocument();
  });
});

describe("PortfolioSummary — numbers-only (Req 11)", () => {
  it("renders no chart, canvas, or svg element", () => {
    const { container } = render(<PortfolioSummary summary={makeSummary()} />);

    expect(container.querySelector("canvas")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("PortfolioSummary — accessibility", () => {
  it("has no automatically detectable a11y violations", async () => {
    const { container } = render(<PortfolioSummary summary={makeSummary()} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
