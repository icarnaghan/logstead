import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";
import CombinedReportsPage from "./CombinedReportsPage";
import { ThemeProvider } from "../theme/ThemeProvider";
import type {
  CombinedScheduleEReport,
  ScheduleEReport,
} from "../api/reports";

/**
 * Component tests for the routed portfolio combined Schedule E report page
 * (tasks 13.3 / 13.4 / 13.5, Requirements 10.1-10.4, 16.2). The combined-report
 * loader is fully mocked, so these exercise the page behaviour (idle empty
 * state → year selection → fetch → render of portfolio totals + each property's
 * report) with no network access.
 */

function makePropertyReport(
  overrides: Partial<ScheduleEReport> = {},
): ScheduleEReport {
  return {
    header: {
      property_id: "prop-1",
      property_name: "Maple Duplex",
      address: "123 Maple St, Springfield",
      property_type: "Multi-Family",
      tax_year: 2024,
      fair_rental_days: 300,
      personal_use_days: 5,
    },
    lines: [
      { line: 3, label: "Rents received", kind: "income", total: "24000.00" },
      { line: 14, label: "Repairs", kind: "expense", total: "1200.00" },
      { line: 18, label: "Depreciation", kind: "expense", total: "5833.33" },
      { line: 19, label: "Other", kind: "expense", total: "142.00" },
    ],
    other_items: [{ description: "HOA dues", amount: "100.00" }],
    totals: {
      total_income: "24000.00",
      total_expenses: "7175.33",
      net: "16824.67",
    },
    ...overrides,
  };
}

function makeCombined(
  overrides: Partial<CombinedScheduleEReport> = {},
): CombinedScheduleEReport {
  return {
    tax_year: 2024,
    properties: [
      makePropertyReport(),
      makePropertyReport({
        header: {
          property_id: "prop-2",
          property_name: "Oak Cottage",
          address: "9 Oak Ln",
          property_type: "Single-Family",
          tax_year: 2024,
          fair_rental_days: 200,
          personal_use_days: 0,
        },
        totals: {
          total_income: "12000.00",
          total_expenses: "4000.00",
          net: "8000.00",
        },
      }),
    ],
    totals: {
      total_income: "36000.00",
      total_expenses: "11175.33",
      net: "24824.67",
    },
    ...overrides,
  };
}

const YEARS = [2024, 2023, 2022] as const;

function renderPage(
  loadCombined: (taxYear: number) => Promise<CombinedScheduleEReport>,
) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={["/reports"]}>
        <CombinedReportsPage loadCombined={loadCombined} years={YEARS} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("CombinedReportsPage — idle + loading + error states", () => {
  it("shows an idle empty state before a year is chosen", () => {
    const loadCombined = vi.fn().mockResolvedValue(makeCombined());
    renderPage(loadCombined);

    expect(
      screen.getByRole("heading", { name: /no report yet/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/choose a tax year above/i),
    ).toBeInTheDocument();
    expect(loadCombined).not.toHaveBeenCalled();
  });

  it("shows a role=status loading state while the report is fetching", async () => {
    const user = userEvent.setup();
    let resolve: (report: CombinedScheduleEReport) => void = () => {};
    const loadCombined = vi.fn().mockImplementation(
      () =>
        new Promise<CombinedScheduleEReport>((r) => {
          resolve = r;
        }),
    );
    renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByRole("status")).toHaveTextContent(
      /loading combined report/i,
    );

    resolve(makeCombined());
    await screen.findByText("Portfolio totals");
  });

  it("surfaces an error alert when the fetch fails", async () => {
    const user = userEvent.setup();
    const loadCombined = vi.fn().mockRejectedValue(new Error("boom"));
    renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /unable to load the combined schedule e report/i,
    );
  });
});

describe("CombinedReportsPage — year selection fetches and renders (Req 10.1-10.4, 16.2)", () => {
  it("fetches the combined report and renders portfolio totals with an emphasized net", async () => {
    const user = userEvent.setup();
    const loadCombined = vi.fn().mockResolvedValue(makeCombined());
    renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByText("Portfolio totals")).toBeInTheDocument();
    expect(loadCombined).toHaveBeenCalledWith(2024);

    const totalsSection = screen
      .getByRole("heading", { name: /portfolio totals/i })
      .closest("section") as HTMLElement;
    expect(within(totalsSection).getByText("$36,000.00")).toBeInTheDocument();
    expect(within(totalsSection).getByText("$11,175.33")).toBeInTheDocument();

    // Net is labelled as income (text cue, not color alone) and emphasized.
    const netLabel = within(totalsSection).getByText(/net income/i);
    const netValue = within(totalsSection).getByText("$24,824.67");
    expect(netLabel.className).toMatch(/font-bold/);
    expect(netValue.className).toMatch(/font-bold/);
    expect(netValue.className).toMatch(/text-xl/);
  });

  it("renders each property's report (property names appear)", async () => {
    const user = userEvent.setup();
    const loadCombined = vi.fn().mockResolvedValue(makeCombined());
    renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Portfolio totals");

    // Each property surfaces its name (as a section heading + within its
    // composed ReportView) and its own report content.
    expect(screen.getAllByText("Maple Duplex").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Oak Cottage").length).toBeGreaterThan(0);
    expect(screen.getByText("123 Maple St, Springfield")).toBeInTheDocument();
    expect(screen.getByText("9 Oak Ln")).toBeInTheDocument();

    // Per-property totals are composed via ReportView (multiple Totals sections).
    expect(
      screen.getAllByRole("heading", { name: /^totals$/i }).length,
    ).toBe(2);
  });

  it("labels a negative portfolio net as a loss", async () => {
    const user = userEvent.setup();
    const loadCombined = vi.fn().mockResolvedValue(
      makeCombined({
        totals: {
          total_income: "1000.00",
          total_expenses: "1500.00",
          net: "-500.00",
        },
      }),
    );
    renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Portfolio totals");

    const totalsSection = screen
      .getByRole("heading", { name: /portfolio totals/i })
      .closest("section") as HTMLElement;
    expect(within(totalsSection).getByText(/net loss/i)).toBeInTheDocument();
    expect(within(totalsSection).getByText("-$500.00")).toBeInTheDocument();
  });

  it("hides the tax-year controls from print output", () => {
    const loadCombined = vi.fn().mockResolvedValue(makeCombined());
    renderPage(loadCombined);

    const controls = screen
      .getByRole("heading", { name: /report controls/i })
      .closest("section") as HTMLElement;
    expect(controls.className).toContain("print:hidden");
  });
});

describe("CombinedReportsPage — accessibility", () => {
  it("has no automatically detectable a11y violations after rendering a report", async () => {
    const user = userEvent.setup();
    const loadCombined = vi.fn().mockResolvedValue(makeCombined());
    const { container } = renderPage(loadCombined);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Portfolio totals");

    expect(await axe(container)).toHaveNoViolations();
  });
});
