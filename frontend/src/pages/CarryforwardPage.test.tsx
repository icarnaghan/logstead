import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CarryforwardPage from "./CarryforwardPage";
import type {
  CarryforwardApi,
  ReconciledYear,
  ReconciliationSummary,
} from "../api/carryforward";
import { ApiError } from "../lib/apiClient";
import { formatMoneyWholeDollars } from "../lib/money";

/**
 * RTL coverage for the passive-loss carryforward page (task 7.4).
 *
 * The page accepts an injectable `api` prop, so every test builds a plain fake
 * `CarryforwardApi` (vitest mock fns cast to the type) and renders the page
 * under a `MemoryRouter` — the page has no charts, so no `ThemeProvider` hook
 * is required. The fake mirrors `DashboardPage.test.tsx`'s `makeApi` style.
 */

function year(overrides: Partial<ReconciledYear> = {}): ReconciledYear {
  return {
    tax_year: 2021,
    schedule_e_net: "1000.00",
    // Carry-in: balance expected to enter the year (what the reported Form
    // 8582 "Prior years unallowed losses" figure is compared with).
    expected_carry_in: "0.00",
    // Carry-out: balance expected to leave the year.
    expected_carryforward: "0.00",
    reported_carryforward: null,
    // The real backend always sends these; absent/"0.00"/false means "none
    // allowed", which reproduces pre-feature behavior. Defaulting them here
    // keeps the allowed-loss Clear button from rendering on loss rows unless a
    // fixture opts in via allowed_loss.
    allowed_loss: "0.00",
    fully_allowed: false,
    status: "unreported",
    drift: null,
    carried_from_year: null,
    ...overrides,
  };
}

const POPULATED: ReconciliationSummary = {
  opening_balance: "0.00",
  has_data: true,
  next_year: 2024,
  next_year_expected_carry_in: "200.00",
  status_tolerance: "2.00",
  years: [
    // A loss year: schedule_e_net negative, expected balance grows.
    year({
      tax_year: 2021,
      schedule_e_net: "-500.00",
      expected_carry_in: "0.00",
      expected_carryforward: "500.00",
      reported_carryforward: "0.00",
      drift: "0.00",
      status: "ok",
    }),
    // A mismatch year: reported diverges from expected carry-in (500).
    year({
      tax_year: 2022,
      schedule_e_net: "200.00",
      expected_carry_in: "500.00",
      expected_carryforward: "300.00",
      reported_carryforward: "999.00",
      drift: "499.00",
      status: "mismatch",
    }),
    // An unreported year.
    year({
      tax_year: 2023,
      schedule_e_net: "100.00",
      expected_carry_in: "300.00",
      expected_carryforward: "200.00",
      reported_carryforward: null,
      status: "unreported",
    }),
  ],
};

const EMPTY: ReconciliationSummary = {
  opening_balance: "0.00",
  has_data: false,
  next_year: null,
  next_year_expected_carry_in: "0.00",
  status_tolerance: "2.00",
  years: [],
};

function makeApi(overrides: Partial<CarryforwardApi> = {}): CarryforwardApi {
  return {
    getReconciliation: vi.fn().mockResolvedValue(POPULATED),
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

/** The <tr> for a given tax year — located via its leading year cell. */
async function findRow(taxYear: number): Promise<HTMLElement> {
  const cell = await screen.findByText(String(taxYear));
  const row = cell.closest("tr");
  if (!row) throw new Error(`No row found for year ${taxYear}`);
  return row as HTMLElement;
}

describe("CarryforwardPage — table rendering (Req 4.5, 4.6, 5.1, 5.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders one row per year in ascending order with all columns", async () => {
    renderPage(makeApi());

    const table = await screen.findByRole("table");
    // Data rows carry a leading year cell; read them top-to-bottom.
    const bodyRows = within(table).getAllByRole("row").slice(1); // skip header
    const yearsInOrder = bodyRows.map(
      (r) => within(r).getAllByRole("cell")[0].textContent,
    );
    expect(yearsInOrder).toEqual(["2021", "2022", "2023"]);

    // Row 2022: year, schedule_e_net, expected, status label all present.
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.4
    // The carryforward net and expected columns round to whole dollars:
    // "200.00" → "$200", "300.00" → "$300".
    const row2022 = await findRow(2022);
    expect(row2022).toHaveTextContent("2022");
    expect(row2022).toHaveTextContent("$200"); // schedule_e_net
    expect(row2022).toHaveTextContent("$300"); // expected_carryforward
    expect(row2022).toHaveTextContent(/needs review/i); // mismatch status label

    // The ok row reads its textual status label (its own text node, so it is
    // not conflated with the adjacent Save/Clear button labels).
    const row2021 = await findRow(2021);
    expect(within(row2021).getByText("OK")).toBeInTheDocument();

    // Eight headers, and every row has as many cells (Year, net, expected
    // entering year, prior years' unallowed losses, drift, allowed, expected
    // to carry out, status).
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "Year",
      "Schedule E net",
      "Expected entering year",
      "Prior years' unallowed losses (Form 8582)",
      "Drift",
      "Allowed loss",
      "Expected to carry out",
      "Status",
    ]);
    for (const r of bodyRows) {
      expect(within(r).getAllByRole("cell")).toHaveLength(8);
    }
    // Entering-year (index 2) and carry-out (index 6) figures.
    const cellText = (r: HTMLElement, i: number) =>
      within(r).getAllByRole("cell")[i].textContent;
    expect(cellText(row2022, 2)).toBe("$500");
    expect(cellText(row2022, 6)).toBe("$300");
    // An unreported row still shows its expected carry-in.
    const row2023 = await findRow(2023);
    expect(cellText(row2023, 2)).toBe("$300");
    // Drift column (index 4): over, zero, and unreported (em dash).
    expect(cellText(row2022, 4)).toBe("+$499 over");
    expect(cellText(row2021, 4)).toBe("$0");
    expect(cellText(row2023, 4)).toBe("—");
  });

  it("renders the heading, introduction, helper text and next-year line", async () => {
    renderPage(makeApi());

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /passive loss carryforward/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/expected to enter that year from earlier years/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/"Prior years unallowed losses" line from each year's Form 8582/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Expected to carry into 2024: $200")).toBeInTheDocument();
    // Allowed-loss helper copy appears on loss rows.
    expect(
      screen.getAllByText(
        /changes the amount expected to carry into the next year/i,
      ).length,
    ).toBeGreaterThan(0);
  });

  it("renders mismatch hints for the first row, an unreported prior year, and a reported prior year", async () => {
    const summary: ReconciliationSummary = {
      ...POPULATED,
      years: [
        year({
          tax_year: 2020,
          schedule_e_net: "-100.00",
          expected_carry_in: "0.00",
          expected_carryforward: "100.00",
          reported_carryforward: "50.00",
          drift: "50.00",
          status: "mismatch",
        }),
        year({
          tax_year: 2021,
          schedule_e_net: "-100.00",
          expected_carry_in: "100.00",
          expected_carryforward: "200.00",
          reported_carryforward: "500.00",
          drift: "400.00",
          status: "mismatch",
        }),
        year({
          tax_year: 2022,
          schedule_e_net: "100.00",
          expected_carry_in: "200.00",
          expected_carryforward: "100.00",
          reported_carryforward: null,
          status: "unreported",
        }),
        year({
          tax_year: 2023,
          schedule_e_net: "100.00",
          expected_carry_in: "100.00",
          expected_carryforward: "0.00",
          reported_carryforward: "7.00",
          drift: "-93.00",
          status: "mismatch",
        }),
      ],
    };
    renderPage(
      makeApi({ getReconciliation: vi.fn().mockResolvedValue(summary) }),
    );

    expect(await findRow(2020)).toHaveTextContent(
      "Compared with your opening balance.",
    );
    // Hint values come from this fixture: the 2020 row's expected carry-out
    // and the 2021 row's reported line, both rounded to whole dollars.
    const priorCarryOut = formatMoneyWholeDollars("100.00");
    const reported2021 = formatMoneyWholeDollars("500.00");
    expect(await findRow(2021)).toHaveTextContent(
      `The 2020 return carried out about ${priorCarryOut}, but this return's line shows ${reported2021}. Check this year's Form 8582 line and the 2020 return's carry-out.`,
    );
    expect(await findRow(2023)).toHaveTextContent(
      "The 2022 return is not reported, so this was compared with the expected figure only.",
    );
  });

  it("renders negative drift as under and a carried status with its root year", async () => {
    const carried: ReconciliationSummary = {
      ...POPULATED,
      years: [
        year({
          tax_year: 2022,
          schedule_e_net: "200.00",
          expected_carry_in: "500.00",
          expected_carryforward: "300.00",
          reported_carryforward: "300.00",
          drift: "-200.00",
          status: "mismatch",
        }),
        year({
          tax_year: 2023,
          schedule_e_net: "100.00",
          expected_carry_in: "300.00",
          expected_carryforward: "200.00",
          reported_carryforward: "100.00",
          drift: "-200.00",
          carried_from_year: 2022,
          status: "carried",
        }),
      ],
    };
    renderPage(makeApi({ getReconciliation: vi.fn().mockResolvedValue(carried) }));

    const row2022 = await findRow(2022);
    expect(within(row2022).getAllByRole("cell")[4].textContent).toBe(
      "-$200 under",
    );
    const row2023 = await findRow(2023);
    expect(within(row2023).getAllByRole("cell")[7]).toHaveTextContent(
      "Carried from 2022",
    );
  });

  it("shows the unreported status label for a year with no reported value", async () => {
    renderPage(makeApi());

    const row2023 = await findRow(2023);
    expect(row2023).toHaveTextContent(/not reported/i);
    // Its inline editor input starts empty (nothing entered yet).
    const input = within(row2023).getByLabelText(
      /prior years' unallowed losses for 2023/i,
    );
    expect(input).toHaveValue("");
  });
});

describe("CarryforwardPage — mismatch highlight (Req 4.5, 5.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("labels a mismatch row textually and shows both expected and reported", async () => {
    renderPage(makeApi());

    const row2022 = await findRow(2022);
    // Textual label — the distinction does not rest on color alone.
    expect(row2022).toHaveTextContent(/needs review/i);
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.4
    // The expected figure rounds to whole dollars ("300.00" → "$300"). The
    // reported value lives in an editable input and keeps its raw two-decimal
    // string "999.00" — it is a data-entry field, not a rounded display cell.
    expect(row2022).toHaveTextContent("$300");
    const reportedInput = within(row2022).getByLabelText(
      /prior years' unallowed losses for 2022/i,
    );
    expect(reportedInput).toHaveValue("999.00");
  });
});

describe("CarryforwardPage — loss styling (Req 5.4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a negative schedule_e_net with the loss cue", async () => {
    renderPage(makeApi());

    const row2021 = await findRow(2021);
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.4
    // The negative net rounds the magnitude and keeps the sign:
    // "-500.00" → "-$500". The "(loss)" cue below stays unchanged.
    expect(row2021).toHaveTextContent("-$500");
    // Textual "(loss)" cue, not color alone.
    const cue = within(row2021).getByText(/\(loss\)/i);
    expect(cue).toHaveClass("text-danger");
  });
});

describe("CarryforwardPage — inline reported editor (Req 3.3, 5.5, 5.6)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves a reported amount then re-fetches and shows the updated value", async () => {
    const user = userEvent.setup();
    // First fetch returns POPULATED; after save, return a summary where 2023
    // is now reported as 200.00 / ok so we can assert the refresh took effect.
    const refreshed: ReconciliationSummary = {
      ...POPULATED,
      years: POPULATED.years.map((y) =>
        y.tax_year === 2023
          ? { ...y, reported_carryforward: "200.00", status: "ok" }
          : y,
      ),
    };
    const getReconciliation = vi
      .fn()
      .mockResolvedValueOnce(POPULATED)
      .mockResolvedValue(refreshed);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const row2023 = await findRow(2023);
    const input = within(row2023).getByLabelText(
      /prior years' unallowed losses for 2023/i,
    );
    await user.type(input, "200.00");
    await user.click(within(row2023).getByRole("button", { name: /save/i }));

    expect(api.setReported).toHaveBeenCalledWith(2023, "200.00");
    // Re-fetch happened (initial mount + after save).
    await waitFor(() =>
      expect(getReconciliation).toHaveBeenCalledTimes(2),
    );
    // The updated value is reflected and the year now reads ok.
    const updatedRow = await findRow(2023);
    expect(
      within(updatedRow).getByLabelText(/prior years' unallowed losses for 2023/i),
    ).toHaveValue("200.00");
    expect(within(updatedRow).getByText("OK")).toBeInTheDocument();
  });

  it("clears a reported amount then re-fetches and reverts to not reported", async () => {
    const user = userEvent.setup();
    const refreshed: ReconciliationSummary = {
      ...POPULATED,
      years: POPULATED.years.map((y) =>
        y.tax_year === 2021
          ? { ...y, reported_carryforward: null, status: "unreported" }
          : y,
      ),
    };
    const getReconciliation = vi
      .fn()
      .mockResolvedValueOnce(POPULATED)
      .mockResolvedValue(refreshed);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const row2021 = await findRow(2021);
    await user.click(within(row2021).getByRole("button", { name: /clear/i }));

    expect(api.clearReported).toHaveBeenCalledWith(2021);
    await waitFor(() =>
      expect(getReconciliation).toHaveBeenCalledTimes(2),
    );
    const updatedRow = await findRow(2021);
    expect(updatedRow).toHaveTextContent(/not reported/i);
    expect(
      within(updatedRow).getByLabelText(/prior years' unallowed losses for 2021/i),
    ).toHaveValue("");
  });

  it("surfaces a server validation error inline near the row (role=alert)", async () => {
    const user = userEvent.setup();
    // ApiError constructor: (status, message, body). Body carries field+message.
    const serverError = new ApiError(400, "Bad request", {
      field: "amount",
      message: "Amount must have at most two decimals.",
    });
    const api = makeApi({
      setReported: vi.fn().mockRejectedValue(serverError),
    });

    renderPage(api);

    const row2023 = await findRow(2023);
    await user.type(
      within(row2023).getByLabelText(/prior years' unallowed losses for 2023/i),
      "150.00",
    );
    await user.click(within(row2023).getByRole("button", { name: /save/i }));

    // The server's field message is surfaced inline and announced.
    const alert = await within(row2023).findByRole("alert");
    expect(alert).toHaveTextContent(/at most two decimals/i);
    // The series is not refreshed on a failed save.
    expect(api.getReconciliation).toHaveBeenCalledTimes(1);
  });
});

describe("CarryforwardPage — opening balance control (Req 7.1, 7.3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves the opening balance then re-fetches", async () => {
    const user = userEvent.setup();
    const getReconciliation = vi.fn().mockResolvedValue(POPULATED);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const input = await screen.findByLabelText(/opening balance/i);
    await user.clear(input);
    await user.type(input, "1000.00");
    // Scope the Save click to the opening-balance control, not a table row.
    const control = input.closest("div")?.parentElement as HTMLElement;
    await user.click(within(control).getByRole("button", { name: /save/i }));

    expect(api.setOpeningBalance).toHaveBeenCalledWith("1000.00");
    await waitFor(() =>
      expect(getReconciliation).toHaveBeenCalledTimes(2),
    );
  });
});

describe("CarryforwardPage — empty state (Req 6.1, 6.2)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the empty-state message, no table, no error, but keeps the opening-balance control", async () => {
    renderPage(makeApi({ getReconciliation: vi.fn().mockResolvedValue(EMPTY) }));

    expect(
      await screen.findByText(/nothing to reconcile yet/i),
    ).toBeInTheDocument();
    // No reconciliation table.
    expect(screen.queryByRole("table")).toBeNull();
    // Not an error state.
    expect(screen.queryByRole("alert")).toBeNull();
    // The opening-balance control is still present.
    expect(screen.getByLabelText(/opening balance/i)).toBeInTheDocument();
  });
});

describe("CarryforwardPage — disclaimer (Req 8.1, 8.3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the persistent non-advice notice with an expandable explanation", async () => {
    const user = userEvent.setup();
    renderPage(makeApi());

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/not tax advice/i);
    expect(note).toHaveTextContent(/§469/);
    expect(note).toHaveTextContent(/Form 8582/);

    // The "What is this?" disclosure is collapsed by default and expandable.
    const details = within(note).getByText(/what is this\?/i).closest("details");
    expect(details).not.toBeNull();
    expect((details as HTMLDetailsElement).open).toBe(false);
    await user.click(within(note).getByText(/what is this\?/i));
    expect((details as HTMLDetailsElement).open).toBe(true);
    expect(note).toHaveTextContent(/suspended passive loss carryforward/i);
  });

  it("keeps the disclaimer visible in the empty state", async () => {
    renderPage(makeApi({ getReconciliation: vi.fn().mockResolvedValue(EMPTY) }));

    await screen.findByText(/nothing to reconcile yet/i);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/not tax advice/i);
  });
});

describe("CarryforwardPage — load error", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a role=alert error when the fetch fails", async () => {
    renderPage(
      makeApi({
        getReconciliation: vi.fn().mockRejectedValue(new Error("boom")),
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not load the carryforward reconciliation/i,
    );
    // No table on a load error.
    expect(screen.queryByRole("table")).toBeNull();
    // The disclaimer is not wiped out by the error.
    expect(screen.getByRole("note")).toBeInTheDocument();
  });
});

// Feature: carryforward-allowed-loss, Req 6.x
describe("CarryforwardPage — allowed-loss control (Req 6.1-6.6)", () => {
  beforeEach(() => vi.clearAllMocks());

  // Feature: carryforward-allowed-loss, Req 6.1, 6.2
  it("renders the allowed control on a loss row and not on a gain/break-even row", async () => {
    renderPage(makeApi());

    // 2021 is a loss year (schedule_e_net "-500.00").
    const lossRow = await findRow(2021);
    expect(
      within(lossRow).getByRole("checkbox", { name: /fully allowed/i }),
    ).toBeInTheDocument();
    expect(
      within(lossRow).getByLabelText(/allowed loss for 2021/i),
    ).toBeInTheDocument();

    // 2022 is a gain year (schedule_e_net "200.00") — no allowed control.
    const gainRow = await findRow(2022);
    expect(
      within(gainRow).queryByRole("checkbox", { name: /fully allowed/i }),
    ).toBeNull();
    expect(
      within(gainRow).queryByLabelText(/allowed loss for 2022/i),
    ).toBeNull();

    // A break-even (zero-net) year is a Non_Loss_Year too — no allowed control.
    const breakEven: ReconciliationSummary = {
      ...POPULATED,
      years: [
        year({
          tax_year: 2024,
          schedule_e_net: "0.00",
          expected_carryforward: "0.00",
          reported_carryforward: null,
          status: "unreported",
        }),
      ],
    };
    renderPage(makeApi({ getReconciliation: vi.fn().mockResolvedValue(breakEven) }));
    const evenRow = await findRow(2024);
    expect(
      within(evenRow).queryByRole("checkbox", { name: /fully allowed/i }),
    ).toBeNull();
    expect(
      within(evenRow).queryByLabelText(/allowed loss for 2024/i),
    ).toBeNull();
  });

  // Feature: carryforward-allowed-loss, Req 6.3
  it("makes the allowed amount input moot (disabled) while fully allowed is on", async () => {
    const fullyAllowed: ReconciliationSummary = {
      ...POPULATED,
      years: [
        year({
          tax_year: 2021,
          schedule_e_net: "-500.00",
          expected_carryforward: "0.00",
          reported_carryforward: null,
          allowed_loss: "0.00",
          fully_allowed: true,
          status: "unreported",
        }),
      ],
    };
    renderPage(
      makeApi({ getReconciliation: vi.fn().mockResolvedValue(fullyAllowed) }),
    );

    const row = await findRow(2021);
    const toggle = within(row).getByRole("checkbox", { name: /fully allowed/i });
    expect(toggle).toBeChecked();
    // While fully-allowed is on, the explicit amount input is disabled (moot).
    expect(within(row).getByLabelText(/allowed loss for 2021/i)).toBeDisabled();
  });

  // Feature: carryforward-allowed-loss, Req 6.4
  it("saves an allowed amount then reloads the series", async () => {
    const user = userEvent.setup();
    const getReconciliation = vi.fn().mockResolvedValue(POPULATED);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const row = await findRow(2021);
    const input = within(row).getByLabelText(/allowed loss for 2021/i);
    await user.type(input, "500.00");
    // Row 2021 has a reported value, so both the reported editor and the
    // allowed control render a Save button. Scope to the allowed control (the
    // allowed input's input-row, which holds its own Save/Clear).
    const allowedControls = input.closest("div") as HTMLElement;
    await user.click(
      within(allowedControls).getByRole("button", { name: /save/i }),
    );

    expect(api.setAllowedLoss).toHaveBeenCalledWith(2021, "500.00");
    // Re-fetch happened (initial mount + after save).
    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(2));
  });

  // Feature: carryforward-allowed-loss, Req 6.4
  it("clears a recorded allowed amount then reloads the series", async () => {
    const user = userEvent.setup();
    // A loss row that already has an allowed amount recorded, so the allowed
    // Clear button renders. The reported editor has no value, so its Clear is
    // absent — the only Clear on the row is the allowed control's.
    const withAllowed: ReconciliationSummary = {
      ...POPULATED,
      years: [
        year({
          tax_year: 2021,
          schedule_e_net: "-500.00",
          expected_carryforward: "0.00",
          reported_carryforward: null,
          allowed_loss: "300.00",
          fully_allowed: false,
          status: "unreported",
        }),
      ],
    };
    const getReconciliation = vi.fn().mockResolvedValue(withAllowed);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const row = await findRow(2021);
    await user.click(within(row).getByRole("button", { name: /clear/i }));

    expect(api.clearAllowedLoss).toHaveBeenCalledWith(2021);
    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(2));
  });

  // Feature: carryforward-allowed-loss, Req 6.4
  it("toggles fully allowed on then off, calling setFullyAllowed and reloading each time", async () => {
    const user = userEvent.setup();
    // The checkbox's checked state reflects year.fully_allowed, which the page
    // re-reads from getReconciliation after each toggle. Model the backend:
    // the first reload (after turning it on) reports 2021 as fully allowed, so
    // the second click toggles it back off.
    const withFullyAllowed: ReconciliationSummary = {
      ...POPULATED,
      years: POPULATED.years.map((y) =>
        y.tax_year === 2021 ? { ...y, fully_allowed: true } : y,
      ),
    };
    const getReconciliation = vi
      .fn()
      .mockResolvedValueOnce(POPULATED)
      .mockResolvedValue(withFullyAllowed);
    const api = makeApi({ getReconciliation });

    renderPage(api);

    const row = await findRow(2021);
    const toggle = within(row).getByRole("checkbox", { name: /fully allowed/i });
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    expect(api.setFullyAllowed).toHaveBeenCalledWith(2021, true);
    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(2));
    // After the reload the checkbox reflects the stored fully-allowed state
    // (same element, re-rendered checked).
    await waitFor(() => expect(toggle).toBeChecked());

    await user.click(toggle);
    expect(api.setFullyAllowed).toHaveBeenNthCalledWith(2, 2021, false);
    await waitFor(() => expect(getReconciliation).toHaveBeenCalledTimes(3));
  });

  // Feature: carryforward-allowed-loss, Req 6.5
  it("surfaces a 400 allowed-loss validation error inline and leaves the reconciliation unchanged", async () => {
    const user = userEvent.setup();
    // ApiError constructor: (status, message, body). The backend reports the
    // offending field as `allowedLoss` with a message.
    const serverError = new ApiError(400, "Bad request", {
      field: "allowedLoss",
      message: "Allowed loss cannot exceed the year's loss.",
    });
    const api = makeApi({
      setAllowedLoss: vi.fn().mockRejectedValue(serverError),
    });

    renderPage(api);

    const row = await findRow(2021);
    const input = within(row).getByLabelText(/allowed loss for 2021/i);
    await user.type(input, "900.00");
    // Scope the Save click to the allowed control (row 2021 also has a reported
    // editor with its own Save button).
    const allowedControls = input.closest("div") as HTMLElement;
    await user.click(
      within(allowedControls).getByRole("button", { name: /save/i }),
    );

    // The server's field message is surfaced inline and announced.
    const alert = await within(row).findByRole("alert");
    expect(alert).toHaveTextContent(/cannot exceed the year's loss/i);
    // The series is not refreshed on a failed save.
    expect(api.getReconciliation).toHaveBeenCalledTimes(1);
  });

  // Feature: carryforward-allowed-loss, Req 6.6
  it("keeps the existing reported editor, status labels, opening balance, disclaimer, and empty state intact", async () => {
    renderPage(makeApi());

    // Reported editor still present on an existing row.
    const row2022 = await findRow(2022);
    expect(
      within(row2022).getByLabelText(/prior years' unallowed losses for 2022/i),
    ).toBeInTheDocument();
    // Status labels still render.
    expect(row2022).toHaveTextContent(/needs review/i);
    const row2021 = await findRow(2021);
    expect(within(row2021).getByText("OK")).toBeInTheDocument();
    // Opening-balance control and disclaimer still render.
    expect(screen.getByLabelText(/opening balance/i)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/not tax advice/i);
  });
});
