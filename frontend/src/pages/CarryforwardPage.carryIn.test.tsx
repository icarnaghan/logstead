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
 * RTL examples for the carry-in semantics UI (task 5.6): the new column
 * headers, helper copy, mismatch hints, unreported expected carry-in, the
 * next-year line, and the reload after a save.
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

function summary(
  years: ReconciledYear[],
  overrides: Partial<ReconciliationSummary> = {},
): ReconciliationSummary {
  return {
    opening_balance: "0.00",
    status_tolerance: "2.00",
    has_data: true,
    years,
    next_year: 2021,
    next_year_expected_carry_in: "3252.00",
    ...overrides,
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

const ENTERING_CELL = 2;
const CARRY_OUT_CELL = 6;

// Shape of the design's worked example: 2015 ok, 2016 blank, 2019 mismatch
// after a blank year, 2020 carried from 2019.
const SERIES: ReconciliationSummary = summary([
  year({
    tax_year: 2014,
    schedule_e_net: "-837.00",
    expected_carry_in: "0.00",
    expected_carryforward: "837.00",
    reported_carryforward: "5.00",
    drift: "5.00",
    status: "mismatch",
  }),
  year({
    tax_year: 2015,
    schedule_e_net: "-1615.00",
    expected_carry_in: "837.00",
    expected_carryforward: "2452.00",
    reported_carryforward: "837.00",
    drift: "0.00",
    status: "ok",
  }),
  year({
    tax_year: 2016,
    schedule_e_net: "300.00",
    expected_carry_in: "2452.00",
    expected_carryforward: "2152.00",
    reported_carryforward: null,
    status: "unreported",
  }),
  year({
    tax_year: 2017,
    schedule_e_net: "-600.00",
    expected_carry_in: "2152.00",
    expected_carryforward: "2752.00",
    reported_carryforward: "100.00",
    drift: "-2052.00",
    status: "mismatch",
  }),
  year({
    tax_year: 2018,
    schedule_e_net: "-200.00",
    expected_carry_in: "2752.00",
    expected_carryforward: "2952.00",
    reported_carryforward: "1.00",
    drift: "-2751.00",
    status: "mismatch",
  }),
  year({
    tax_year: 2019,
    schedule_e_net: "300.00",
    expected_carry_in: "2952.00",
    expected_carryforward: "2652.00",
    reported_carryforward: null,
    status: "unreported",
  }),
]);

describe("CarryforwardPage — carry-in semantics", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the carry-in column headers and Form 8582 helper text", async () => {
    renderPage(makeApi(SERIES));
    for (const name of [
      "Expected entering year",
      "Prior years' unallowed losses (Form 8582)",
      "Expected to carry out",
    ]) {
      expect(
        await screen.findByRole("columnheader", { name }),
      ).toBeInTheDocument();
    }
    expect(screen.getAllByRole("columnheader")).toHaveLength(8);
    expect(
      screen.getByText(/"Prior years unallowed losses" line from each year's Form 8582/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/loss balance carried into that year from earlier years/),
    ).toBeInTheDocument();
  });

  it("shows entering and carry-out figures in their own cells", async () => {
    renderPage(makeApi(SERIES));
    const row = await findRow(2015);
    const cells = within(row).getAllByRole("cell");
    expect(cells).toHaveLength(8);
    expect(cells[ENTERING_CELL]).toHaveTextContent("$837");
    expect(cells[CARRY_OUT_CELL]).toHaveTextContent("$2,452");
  });

  it("still shows the expected carry-in on an unreported row", async () => {
    renderPage(makeApi(SERIES));
    const row = await findRow(2016);
    const cells = within(row).getAllByRole("cell");
    expect(cells).toHaveLength(8);
    expect(cells[ENTERING_CELL]).toHaveTextContent("$2,452");
    expect(cells[CARRY_OUT_CELL]).toHaveTextContent("$2,152");
    expect(within(row).getByText("Not reported")).toBeInTheDocument();
  });

  it("hints 'opening balance' on a first-year mismatch", async () => {
    renderPage(makeApi(SERIES));
    const row = await findRow(2014);
    expect(within(row).getByText("Needs review")).toBeInTheDocument();
    expect(
      within(row).getByText("Compared with your opening balance."),
    ).toBeInTheDocument();
  });

  it("hints that the prior return is not reported when the previous row is blank", async () => {
    renderPage(makeApi(SERIES));
    const row = await findRow(2017);
    expect(
      within(row).getByText(
        "The 2016 return is not reported, so this was compared with the expected figure only.",
      ),
    ).toBeInTheDocument();
  });

  it("hints to review the prior return when the previous row is reported", async () => {
    renderPage(makeApi(SERIES));
    const row = await findRow(2018);
    expect(
      within(row).getByText(
        `The 2017 return carried out about ${formatMoneyWholeDollars(
          SERIES.years[3].expected_carryforward,
        )}, but this return's line shows ${formatMoneyWholeDollars(
          SERIES.years[4].reported_carryforward,
        )}. Check this year's Form 8582 line and the 2017 return's carry-out.`,
      ),
    ).toBeInTheDocument();
  });

  it("shows no hint on ok and unreported rows", async () => {
    renderPage(makeApi(SERIES));
    for (const y of [2015, 2016, 2019]) {
      const row = await findRow(y);
      expect(within(row).queryByText(/Compared with|carried out about|not reported, so/)).toBeNull();
    }
  });

  it("shows the next-year line with the formatted value", async () => {
    renderPage(makeApi(SERIES));
    expect(
      await screen.findByText("Expected to carry into 2021: $3,252"),
    ).toBeInTheDocument();
  });

  it("uses 'the next year' wording when next_year is null", async () => {
    renderPage(
      makeApi(
        summary([year({ tax_year: 2020 })], {
          next_year: null,
          next_year_expected_carry_in: "1500.00",
        }),
      ),
    );
    expect(
      await screen.findByText("Expected to carry into the next year: $1,500"),
    ).toBeInTheDocument();
  });

  it("explains the allowed-loss effect on loss rows only", async () => {
    renderPage(makeApi(SERIES));
    await findRow(2015);
    const helper = "Changes the amount expected to carry into the next year.";
    // Loss years in SERIES: 2014, 2015, 2017, 2018.
    expect(screen.getAllByText(helper)).toHaveLength(4);
    expect(within(await findRow(2016)).queryByText(helper)).toBeNull();
  });

  it("labels the reported editor with the prior-years wording", async () => {
    renderPage(makeApi(SERIES));
    await findRow(2015);
    expect(
      screen.getByLabelText("Prior years' unallowed losses for 2015"),
    ).toBeInTheDocument();
  });

  it("updates the next-year line after a save reloads the series", async () => {
    const before = summary([year({ tax_year: 2020, schedule_e_net: "-300.00",
      expected_carry_in: "2952.00", expected_carryforward: "3252.00" })]);
    const after = summary(
      [
        year({
          tax_year: 2020,
          schedule_e_net: "-300.00",
          expected_carry_in: "2952.00",
          expected_carryforward: "3252.00",
          reported_carryforward: "2952.00",
          drift: "0.00",
          status: "ok",
        }),
      ],
      { next_year_expected_carry_in: "9999.00" },
    );
    const api = makeApi(before, {
      getReconciliation: vi
        .fn()
        .mockResolvedValueOnce(before)
        .mockResolvedValue(after),
    });
    const user = userEvent.setup();
    renderPage(api);

    expect(
      await screen.findByText("Expected to carry into 2021: $3,252"),
    ).toBeInTheDocument();
    const row = await findRow(2020);
    const input = within(row).getByLabelText(
      "Prior years' unallowed losses for 2020",
    );
    await user.type(input, "2952.00");
    await user.click(within(row).getAllByRole("button", { name: "Save" })[0]);

    await waitFor(() =>
      expect(
        screen.getByText("Expected to carry into 2021: $9,999"),
      ).toBeInTheDocument(),
    );
    expect(api.setReported).toHaveBeenCalledWith(2020, "2952.00");
    expect(within(await findRow(2020)).getByText("OK")).toBeInTheDocument();
  });
});
