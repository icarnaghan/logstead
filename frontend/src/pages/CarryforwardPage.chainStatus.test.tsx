import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import { formatMoneyWholeDollars } from "../lib/money";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";

/**
 * RTL examples for the carryforward chain-status UI (task 6.3): the Drift
 * column, the `carried` status label, and the mismatch-only danger highlight.
 */

function year(overrides: Partial<ReconciledYear> = {}): ReconciledYear {
  return {
    tax_year: 2021,
    schedule_e_net: "1000.00",
    expected_carry_in: "0.00",
    expected_carryforward: "0.00",
    reported_carryforward: null,
    allowed_loss: "0.00",
    fully_allowed: false,
    status: "unreported",
    drift: null,
    carried_from_year: null,
    ...overrides,
  };
}

function summary(years: ReconciledYear[]): ReconciliationSummary {
  return {
    opening_balance: "0.00",
    status_tolerance: "2.00",
    has_data: true,
    years,
    next_year: 2019,
    next_year_expected_carry_in: "13400.00",
  };
}

function makeApi(
  initial: ReconciliationSummary,
  overrides: Partial<CarryforwardApi> = {},
): CarryforwardApi {
  return {
    getReconciliation: vi.fn().mockResolvedValue(initial),
    setReported: vi.fn().mockResolvedValue(undefined),
    clearReported: vi.fn().mockResolvedValue(undefined),
    setOpeningBalance: vi.fn().mockResolvedValue(undefined),
    setYear: vi.fn().mockResolvedValue(undefined),
    setAllowedLoss: vi.fn().mockResolvedValue(undefined),
    clearAllowedLoss: vi.fn().mockResolvedValue(undefined),
    setFullyAllowed: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as CarryforwardApi;
}

function renderPage(api: CarryforwardApi) {
  return render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={api} />
    </MemoryRouter>,
  );
}

async function findRow(taxYear: number): Promise<HTMLElement> {
  const cell = await screen.findByText(String(taxYear));
  const row = cell.closest("tr");
  if (!row) throw new Error(`No row found for year ${taxYear}`);
  return row as HTMLElement;
}

const STATUS_CELL = 7;
const DRIFT_CELL = 4;

const CHAIN: ReconciliationSummary = summary([
  year({
    tax_year: 2015,
    schedule_e_net: "-2000.00",
    expected_carry_in: "10000.00",
    expected_carryforward: "12000.00",
    reported_carryforward: "7000.00",
    drift: "-3000.00",
    status: "mismatch",
  }),
  year({
    tax_year: 2016,
    schedule_e_net: "-1000.00",
    expected_carry_in: "12000.00",
    expected_carryforward: "13000.00",
    reported_carryforward: "9000.00",
    drift: "-3000.00",
    status: "carried",
    carried_from_year: 2015,
  }),
  year({
    tax_year: 2017,
    schedule_e_net: "-500.00",
    expected_carry_in: "13000.00",
    expected_carryforward: "13500.00",
    reported_carryforward: "10000.00",
    drift: "-3000.00",
    status: "carried",
    carried_from_year: null,
  }),
  year({
    tax_year: 2018,
    schedule_e_net: "100.00",
    expected_carry_in: "13500.00",
    expected_carryforward: "13400.00",
    reported_carryforward: null,
    status: "unreported",
  }),
]);

describe("CarryforwardPage — chain status (Req 7, 8)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a Drift column header", async () => {
    renderPage(makeApi(CHAIN));
    expect(
      await screen.findByRole("columnheader", { name: "Drift" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Expected entering year" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", {
        name: "Prior years' unallowed losses (Form 8582)",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Expected to carry out" }),
    ).toBeInTheDocument();
  });

  it("shows an em dash for null drift", async () => {
    renderPage(makeApi(CHAIN));
    const row = await findRow(2018);
    expect(within(row).getAllByRole("cell")[DRIFT_CELL].textContent).toBe("—");
  });

  it("labels a carried year with its root cause and no danger highlight", async () => {
    renderPage(makeApi(CHAIN));
    const row = await findRow(2016);
    expect(
      within(row).getAllByRole("cell")[STATUS_CELL],
    ).toHaveTextContent("Carried from 2015");
    expect(within(row).getAllByRole("cell")[DRIFT_CELL].textContent).toBe(
      "-$3,000 under",
    );
    expect(row.className).not.toContain("bg-danger-subtle");
    expect(within(row).getByText("Carried from 2015").className).not.toContain(
      "text-danger",
    );
  });

  it("uses the generic label when carried_from_year is null", async () => {
    renderPage(makeApi(CHAIN));
    const row = await findRow(2017);
    expect(
      within(row).getAllByRole("cell")[STATUS_CELL],
    ).toHaveTextContent("Carried from earlier year");
    expect(row.className).not.toContain("bg-danger-subtle");
  });

  it("keeps Needs review and the danger highlight on a mismatch row", async () => {
    renderPage(makeApi(CHAIN));
    const row = await findRow(2015);
    expect(within(row).getByText("Needs review")).toBeInTheDocument();
    expect(
      within(row).getByText("Compared with your opening balance."),
    ).toBeInTheDocument();
    expect(row.className).toContain("bg-danger-subtle");
    expect(within(row).getByText("Needs review").className).toContain(
      "text-danger",
    );
  });

  it("updates labels after a save reloads the series", async () => {
    const before = summary([
      year({
        tax_year: 2015,
        schedule_e_net: "-2000.00",
        expected_carry_in: "10000.00",
        expected_carryforward: "12000.00",
        reported_carryforward: "7000.00",
        drift: "-3000.00",
        status: "mismatch",
      }),
      year({
        tax_year: 2016,
        schedule_e_net: "-1000.00",
        expected_carry_in: "12000.00",
        expected_carryforward: "13000.00",
        reported_carryforward: "9500.00",
        drift: "-2500.00",
        status: "mismatch",
      }),
    ]);
    const after = summary([
      before.years[0],
      year({
        tax_year: 2016,
        schedule_e_net: "-1000.00",
        expected_carry_in: "12000.00",
        expected_carryforward: "13000.00",
        reported_carryforward: "9000.00",
        drift: "-3000.00",
        status: "carried",
        carried_from_year: 2015,
      }),
    ]);
    const api = makeApi(before, {
      getReconciliation: vi
        .fn()
        .mockResolvedValueOnce(before)
        .mockResolvedValue(after),
    });
    const user = userEvent.setup();
    renderPage(api);

    const row = await findRow(2016);
    expect(within(row).getAllByRole("cell")[STATUS_CELL]).toHaveTextContent(
      "Needs review",
    );
    expect(row.className).toContain("bg-danger-subtle");
    expect(
      within(row).getByText(
        `The 2015 return carried out about ${formatMoneyWholeDollars(
          before.years[0].expected_carryforward,
        )}, but this return's line shows ${formatMoneyWholeDollars(
          before.years[1].reported_carryforward,
        )}. Check this year's Form 8582 line and the 2015 return's carry-out.`,
      ),
    ).toBeInTheDocument();

    const input = within(row).getByLabelText(
      /prior years' unallowed losses for 2016/i,
    );
    // Replace the whole value in one step: a separate clear() can lose its
    // selection under heavy parallel load, so typing would append instead.
    await user.type(input, "9000.00", {
      initialSelectionStart: 0,
      initialSelectionEnd: (input as HTMLInputElement).value.length,
    });
    await waitFor(() =>
      expect((input as HTMLInputElement).value).toBe("9000.00"),
    );
    // Loss rows also have an allowed-loss Save; the reported editor's comes first.
    await user.click(within(row).getAllByRole("button", { name: "Save" })[0]);

    await waitFor(async () => {
      const updated = await findRow(2016);
      expect(within(updated).getAllByRole("cell")[STATUS_CELL]).toHaveTextContent(
        "Carried from 2015",
      );
      expect(updated.className).not.toContain("bg-danger-subtle");
      expect(within(updated).getAllByRole("cell")[DRIFT_CELL].textContent).toBe(
        "-$3,000 under",
      );
    });
    expect(api.setReported).toHaveBeenCalledWith(2016, "9000.00");
  });
});
