import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";

function year(
  taxYear: number,
  overrides: Partial<ReconciledYear> = {},
): ReconciledYear {
  return {
    tax_year: taxYear,
    schedule_e_net: "0.00",
    expected_carry_in: "0.00",
    expected_carryforward: "9000.00",
    reported_carryforward: "9000.00",
    allowed_loss: "0.00",
    fully_allowed: false,
    status: "ok",
    drift: "0.00",
    carried_from_year: null,
    ...overrides,
  };
}

function makeApi(summary: ReconciliationSummary): CarryforwardApi {
  return {
    getReconciliation: vi.fn().mockResolvedValue(summary),
    setReported: vi.fn(),
    clearReported: vi.fn(),
    setOpeningBalance: vi.fn(),
    setYear: vi.fn(),
    setAllowedLoss: vi.fn(),
    clearAllowedLoss: vi.fn(),
    setFullyAllowed: vi.fn(),
  } as unknown as CarryforwardApi;
}

function summaryOf(
  years: ReconciledYear[],
  tolerance = "2.00",
  hasData = true,
): ReconciliationSummary {
  return {
    opening_balance: "0.00",
    status_tolerance: tolerance,
    has_data: hasData,
    next_year: 2030,
    next_year_expected_carry_in: "0.00",
    years,
  };
}

function renderPage(summary: ReconciliationSummary) {
  render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={makeApi(summary)} />
    </MemoryRouter>,
  );
}

describe("CarryforwardPage tolerance sentence and hints", () => {
  afterEach(() => cleanup());

  it('shows "$2" for status_tolerance "2.00"', async () => {
    renderPage(summaryOf([year(2020)], "2.00"));
    expect(
      await screen.findByText(
        "Matches within $2 count as OK because returns are filed in whole dollars.",
      ),
    ).toBeInTheDocument();
  });

  it('shows "$10" for status_tolerance "10.00"', async () => {
    renderPage(summaryOf([year(2020)], "10.00"));
    expect(
      await screen.findByText(
        "Matches within $10 count as OK because returns are filed in whole dollars.",
      ),
    ).toBeInTheDocument();
  });

  it("appears together with the table", async () => {
    renderPage(summaryOf([year(2020)]));
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText(/Matches within \$2 count as OK/)).toBeInTheDocument();
  });

  it("is absent in the empty state", async () => {
    renderPage(summaryOf([], "2.00", false));
    expect(await screen.findByText("Nothing to reconcile yet")).toBeInTheDocument();
    expect(screen.queryByText(/Matches within/)).not.toBeInTheDocument();
  });

  it("keeps the first-row hint text", async () => {
    renderPage(summaryOf([year(2020, { status: "mismatch" })]));
    expect(
      await screen.findByText("Compared with your opening balance."),
    ).toBeInTheDocument();
  });

  it("keeps the unreported-previous hint text", async () => {
    renderPage(
      summaryOf([
        year(2020, { reported_carryforward: null, status: "unreported", drift: null }),
        year(2021, { status: "mismatch", reported_carryforward: "100.00" }),
      ]),
    );
    expect(
      await screen.findByText(
        "The 2020 return is not reported, so this was compared with the expected figure only.",
      ),
    ).toBeInTheDocument();
  });
});
