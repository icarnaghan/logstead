import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import { YearlyRollupTable } from "./YearlyRollupTable";
import type { LoanSchedule, YearlyRollup } from "../../api/loans";

/**
 * Component tests for the yearly rollup table (task 16.7, Requirements 9.10,
 * 9.20).
 */

function year(overrides: Partial<YearlyRollup> = {}): YearlyRollup {
  return {
    tax_year: 2023,
    payments: 2,
    interest: "1000.00",
    estimated_interest: "1000.00",
    interest_override: null,
    variance: null,
    principal: "500.00",
    total_paid: "1500.00",
    ending_balance: "99500.00",
    ...overrides,
  };
}

function schedule(yearly: YearlyRollup[]): LoanSchedule {
  return {
    loan_id: "L1",
    estimate: true,
    payoff_balance: null,
    yearly,
    payments: [
      {
        number: 1,
        date: "2023-02-01",
        payment: "750.00",
        interest: "500.00",
        principal: "250.00",
        balance: "99750.00",
      },
      {
        number: 2,
        date: "2023-03-01",
        payment: "750.00",
        interest: "500.00",
        principal: "250.00",
        balance: "99500.00",
      },
      {
        number: 3,
        date: "2024-01-01",
        payment: "750.00",
        interest: "400.00",
        principal: "350.00",
        balance: "99150.00",
      },
    ],
  };
}

/** The top-level table (nested payments tables live in detail rows). */
function outerTable(): HTMLElement {
  return screen.getAllByRole("table")[0];
}

describe("YearlyRollupTable", () => {
  it("expands and collapses a year with aria-expanded", async () => {
    const user = userEvent.setup();
    render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year(), year({ tax_year: 2024 })])}
      />,
    );
    const button = within(outerTable()).getByRole("button", {
      name: /show payments for 2023/i,
    });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("$99,750.00")).not.toBeInTheDocument();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveTextContent(/hide payments for 2023/i);
    expect(
      within(
        screen.getByRole("table", { name: /payments for 2023/i }),
      ).getByText("$99,750.00"),
    ).toBeInTheDocument();
    // Other years stay collapsed and only this year's payments show.
    expect(screen.queryByText("$99,150.00")).not.toBeInTheDocument();
    expect(
      within(outerTable()).getByRole("button", {
        name: /show payments for 2024/i,
      }),
    ).toHaveAttribute("aria-expanded", "false");

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("$99,750.00")).not.toBeInTheDocument();
  });

  it("links the toggle to its panel via aria-controls", () => {
    const { container } = render(
      <YearlyRollupTable caption="Loan" schedule={schedule([year()])} />,
    );
    const button = within(outerTable()).getByRole("button");
    const id = button.getAttribute("aria-controls");
    expect(id).toBeTruthy();
    expect(container.querySelector(`#${id}`)).not.toBeNull();
  });

  it("toggles with Enter and Space from the keyboard", async () => {
    const user = userEvent.setup();
    render(<YearlyRollupTable caption="Loan" schedule={schedule([year()])} />);
    const button = within(outerTable()).getByRole("button");
    await user.tab();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a Filed value marker and variance in words for an override", () => {
    render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([
          year({
            interest: "880.00",
            interest_override: "880.00",
            variance: "-120.00",
          }),
          year({
            tax_year: 2024,
            interest: "1050.00",
            interest_override: "1050.00",
            variance: "50.00",
          }),
        ])}
      />,
    );
    const table = within(outerTable());
    expect(table.getAllByText("Filed value")).toHaveLength(2);
    expect(
      table.getByText("$120.00 lower than the estimate"),
    ).toBeInTheDocument();
    expect(
      table.getByText("$50.00 higher than the estimate"),
    ).toBeInTheDocument();
  });

  it("renders override-only rows with text dashes and no expand control", () => {
    render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([
          year({
            tax_year: 2022,
            payments: 0,
            interest: "20650.12",
            estimated_interest: "0.00",
            interest_override: "20650.12",
            variance: "20650.12",
            principal: "0.00",
            total_paid: "0.00",
            ending_balance: null,
          }),
          year({ tax_year: 2023 }),
        ])}
      />,
    );
    const table = within(outerTable());
    expect(table.getByText("Override only")).toBeInTheDocument();
    expect(table.getByText("$20,650")).toBeInTheDocument();
    const row = table.getByRole("rowheader", { name: /2022/ }).closest("tr")!;
    expect(within(row).getAllByText("\u2014")).toHaveLength(3);
    expect(within(row).queryByRole("button")).toBeNull();
    expect(
      table.queryByRole("button", { name: /payments for 2022/i }),
    ).not.toBeInTheDocument();
    expect(
      table.getByRole("button", { name: /show payments for 2023/i }),
    ).toBeInTheDocument();
  });

  it("labels the anchor-year row with payments after the anchor date", () => {
    render(
      <YearlyRollupTable
        caption="Loan"
        anchorDate="2023-06-01"
        schedule={schedule([year({ tax_year: 2023 }), year({ tax_year: 2024 })])}
      />,
    );
    expect(
      within(outerTable()).getAllByText(/payments after 2023-06-01 only/i),
    ).toHaveLength(1);
  });

  it("omits the marker without an override and lists years ascending", () => {
    render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year({ tax_year: 2024 }), year()])}
      />,
    );
    expect(screen.queryByText("Filed value")).not.toBeInTheDocument();
    const rowHeaders = within(outerTable())
      .getAllByRole("rowheader")
      .map((h) => h.textContent);
    expect(rowHeaders).toEqual(["2023", "2024"]);
    expect(within(outerTable()).getAllByText("$1,500")).toHaveLength(2);
  });

  it("renders row headers with scope=row and right-aligned numeric columns", () => {
    render(<YearlyRollupTable caption="Loan" schedule={schedule([year()])} />);
    const table = within(outerTable());
    expect(table.getByRole("rowheader", { name: "2023" })).toHaveAttribute(
      "scope",
      "row",
    );
    for (const name of ["Interest", "Principal", "Total paid", "Ending balance"]) {
      expect(table.getByRole("columnheader", { name })).toHaveClass(
        "text-right",
        "tabular-nums",
      );
    }
    expect(table.getByText("$1,500")).toHaveClass("text-right");
  });

  it("labels each cell with its column header for the stacked layout", () => {
    const { container } = render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year(), year({ tax_year: 2024 })])}
      />,
    );
    expect(container.querySelector("ul")).toBeNull();
    const rowheaders = within(outerTable()).getAllByRole("rowheader");
    expect(rowheaders.length).toBeGreaterThanOrEqual(2);
    for (const th of rowheaders.slice(0, 2)) {
      expect(th).toHaveAttribute("data-label", "Tax year");
    }
  });

  it("keeps the detail row hidden until expanded and wires aria-controls to it", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <YearlyRollupTable caption="Loan" schedule={schedule([year()])} />,
    );
    const button = within(outerTable()).getByRole("button");
    const detail = container.querySelector(
      `#${button.getAttribute("aria-controls")}`,
    ) as HTMLElement;
    expect(detail.tagName).toBe("TR");
    expect(detail).toHaveAttribute("hidden");
    await user.click(button);
    expect(detail).not.toHaveAttribute("hidden");
    expect(within(detail).getAllByRole("rowheader").length).toBeGreaterThan(0);
    await user.click(button);
    expect(detail).toHaveAttribute("hidden");
  });

  it("has unique ids, including with override controls and expanded rows", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year(), year({ tax_year: 2024 })])}
        renderOverrideControl={(y) => (
          <input aria-label={`Interest override for ${y.tax_year}`} />
        )}
      />,
    );
    await user.click(
      within(outerTable()).getByRole("button", { name: /show payments for 2023/i }),
    );
    const ids = Array.from(container.querySelectorAll("[id]")).map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("shows the override column only with renderOverrideControl and keeps the control working", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <YearlyRollupTable caption="Loan" schedule={schedule([year()])} />,
    );
    expect(
      within(outerTable()).queryByRole("columnheader", {
        name: "Interest override",
      }),
    ).toBeNull();

    const onClick = vi.fn();
    rerender(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year()])}
        renderOverrideControl={(y) => (
          <button type="button" onClick={onClick}>
            Override {y.tax_year}
          </button>
        )}
      />,
    );
    expect(
      within(outerTable()).getByRole("columnheader", {
        name: "Interest override",
      }),
    ).toBeInTheDocument();
    await user.click(
      within(outerTable()).getByRole("button", { name: "Override 2023" }),
    );
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <YearlyRollupTable
        caption="Loan"
        schedule={schedule([year(), year({ tax_year: 2024 })])}
      />,
    );
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results).toHaveNoViolations();
  });
});
