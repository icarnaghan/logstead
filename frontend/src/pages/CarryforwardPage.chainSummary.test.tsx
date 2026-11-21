import { cleanup, render, screen, within } from "@testing-library/react";
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
  const getReconciliation = vi.fn().mockResolvedValue(summary);
  const api = {
    getReconciliation,
    setReported: vi.fn(),
    clearReported: vi.fn(),
    setOpeningBalance: vi.fn(),
    setYear: vi.fn(),
    setAllowedLoss: vi.fn(),
    clearAllowedLoss: vi.fn(),
    setFullyAllowed: vi.fn(),
  } as unknown as CarryforwardApi;
  render(
    <MemoryRouter initialEntries={["/carryforward"]}>
      <CarryforwardPage api={api} />
    </MemoryRouter>,
  );
  return { getReconciliation };
}

/** Real-data shape: 2016-2018 mismatch, 2021 mismatch, carried in between. */
function realSeries(): ReconciledYear[] {
  return [
    year(2015, { expected_carryforward: "2452.00", reported_carryforward: "2452.00" }),
    year(2016, {
      expected_carry_in: "2452.00",
      reported_carryforward: "0.00",
      status: "mismatch",
      drift: "-2452.00",
    }),
    year(2017, {
      expected_carry_in: "2710.00",
      reported_carryforward: "0.00",
      status: "mismatch",
      drift: "-2710.00",
    }),
    year(2018, {
      expected_carry_in: "3422.00",
      reported_carryforward: "0.00",
      status: "mismatch",
      drift: "-3422.00",
    }),
    year(2019, { status: "carried", drift: "-3422.00", carried_from_year: 2018 }),
    year(2020, { status: "carried", drift: "-3422.00", carried_from_year: 2018 }),
    year(2021, {
      expected_carry_in: "9000.00",
      reported_carryforward: "4676.00",
      status: "mismatch",
      drift: "-4324.00",
    }),
    year(2022, { status: "carried", drift: "-4323.00", carried_from_year: 2021 }),
    year(2023, { status: "carried", drift: "-4323.00", carried_from_year: 2021 }),
    year(2024, { status: "carried", drift: "-4323.00", carried_from_year: 2021 }),
    year(2025, { status: "carried", drift: "-4323.00", carried_from_year: 2021 }),
  ];
}

const REGION_NAME = "Where the chain breaks";

async function findRegion() {
  return screen.findByRole("region", { name: REGION_NAME });
}

function rowOf(taxYear: number): HTMLElement {
  const cell = screen.getByText(String(taxYear), { selector: "td" });
  return cell.closest("tr") as HTMLElement;
}

describe("CarryforwardPage chain summary (real-data fixture)", () => {
  afterEach(() => cleanup());

  it("renders the region with the first-break sentence", async () => {
    renderPage(summaryOf(realSeries()));
    const region = await findRegion();
    expect(
      within(region).getByText(
        "The chain first breaks in 2016: the 2015 return carried out about $2,452, but the 2016 line shows $0.",
      ),
    ).toBeInTheDocument();
  });

  it("states the continuation through 2018", async () => {
    renderPage(summaryOf(realSeries()));
    const region = await findRegion();
    expect(
      within(region).getByText(
        "The mismatch continues through 2018, where about $3,422 appears dropped in total.",
      ),
    ).toBeInTheDocument();
  });

  it("lists the 2021 further break", async () => {
    renderPage(summaryOf(realSeries()));
    const region = await findRegion();
    const items = within(region).getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("2021: about $902 dropped.");
  });

  it("states the total gap for 2025 as under", async () => {
    renderPage(summaryOf(realSeries()));
    const region = await findRegion();
    expect(
      within(region).getByText(
        "As of 2025, the reported line is about $4,323 under the expected carry-in.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the carried hint on 2019 (break 2018, first broke 2016)", async () => {
    renderPage(summaryOf(realSeries()));
    await findRegion();
    expect(
      within(rowOf(2019)).getByText(
        "Inherits the 2018 break: this line is about $3,422 under the expected carry-in. The chain first broke in 2016.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the carried hint on 2022 (break 2021)", async () => {
    renderPage(summaryOf(realSeries()));
    await findRegion();
    expect(
      within(rowOf(2022)).getByText(
        "Inherits the 2021 break: this line is about $4,323 under the expected carry-in. The chain first broke in 2016.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the Carried from label, the disclaimer and the mismatch hint", async () => {
    renderPage(summaryOf(realSeries()));
    await findRegion();
    expect(within(rowOf(2019)).getByText("Carried from 2018")).toBeInTheDocument();
    expect(within(rowOf(2022)).getByText("Carried from 2021")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(
      "This is a reconciliation aid, not tax advice.",
    );
    expect(
      within(rowOf(2016)).getByText(
        /The 2015 return carried out about \$2,452, but this return's line shows \$0\./,
      ),
    ).toBeInTheDocument();
  });

  it("makes a single API request", async () => {
    const { getReconciliation } = renderPage(summaryOf(realSeries()));
    await findRegion();
    expect(getReconciliation).toHaveBeenCalledTimes(1);
  });
});

describe("CarryforwardPage chain summary (absence)", () => {
  afterEach(() => cleanup());

  it("renders no region for an all-ok series", async () => {
    renderPage(summaryOf([year(2020), year(2021)]));
    await screen.findByRole("table");
    expect(screen.queryByRole("region", { name: REGION_NAME })).not.toBeInTheDocument();
    expect(screen.queryByText(REGION_NAME)).not.toBeInTheDocument();
  });

  it("renders no region for a carried-only series", async () => {
    renderPage(
      summaryOf([
        year(2020, { status: "carried", drift: "-5.00", carried_from_year: 2019 }),
        year(2021, { status: "carried", drift: "-5.00", carried_from_year: 2019 }),
      ]),
    );
    await screen.findByRole("table");
    expect(screen.queryByRole("region", { name: REGION_NAME })).not.toBeInTheDocument();
  });

  it("renders no region in the empty state", async () => {
    renderPage(summaryOf([], "2.00", false));
    expect(await screen.findByText("Nothing to reconcile yet")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: REGION_NAME })).not.toBeInTheDocument();
  });
});

describe("CarryforwardPage chain summary (variants)", () => {
  afterEach(() => cleanup());

  it("uses the first-row variant of the first-break sentence", async () => {
    renderPage(
      summaryOf([
        year(2020, {
          expected_carry_in: "500.00",
          reported_carryforward: "100.00",
          status: "mismatch",
          drift: "-400.00",
        }),
      ]),
    );
    const region = await findRegion();
    expect(
      within(region).getByText(
        "The chain first breaks in 2020: the 2020 line shows $100, where about $500 was expected.",
      ),
    ).toBeInTheDocument();
  });

  it("uses the unreported-prior variant of the first-break sentence", async () => {
    renderPage(
      summaryOf([
        year(2020, { reported_carryforward: null, status: "unreported", drift: null }),
        year(2021, {
          expected_carry_in: "500.00",
          reported_carryforward: "100.00",
          status: "mismatch",
          drift: "-400.00",
        }),
      ]),
    );
    const region = await findRegion();
    expect(
      within(region).getByText(
        "The chain first breaks in 2021: the 2021 line shows $100, where about $500 was expected.",
      ),
    ).toBeInTheDocument();
  });

  it("reads within tolerance when the gap equals the tolerance", async () => {
    renderPage(
      summaryOf([year(2020, { status: "mismatch", drift: "-2.00" })], "2.00"),
    );
    const region = await findRegion();
    expect(
      within(region).getByText(
        "As of 2020, the reported line is within $2 of the expected carry-in.",
      ),
    ).toBeInTheDocument();
    expect(within(region).queryByText(/under the expected carry-in/)).not.toBeInTheDocument();
  });

  it("reads under when the gap is one cent above the tolerance", async () => {
    renderPage(
      summaryOf([year(2020, { status: "mismatch", drift: "-2.01" })], "2.00"),
    );
    const region = await findRegion();
    expect(
      within(region).getByText(
        "As of 2020, the reported line is about $2 under the expected carry-in.",
      ),
    ).toBeInTheDocument();
    expect(within(region).queryByText(/within \$2/)).not.toBeInTheDocument();
  });

  it("uses extra and over for positive drift", async () => {
    renderPage(
      summaryOf([
        year(2020),
        year(2021, { status: "mismatch", drift: "300.00" }),
        year(2022, { status: "mismatch", drift: "400.00" }),
      ]),
    );
    const region = await findRegion();
    expect(
      within(region).getByText(
        "The mismatch continues through 2022, where about $400 appears extra in total.",
      ),
    ).toBeInTheDocument();
    expect(
      within(region).getByText(
        "As of 2022, the reported line is about $400 over the expected carry-in.",
      ),
    ).toBeInTheDocument();
  });

  it("renders no list or continuation for a single run of one year", async () => {
    renderPage(
      summaryOf([
        year(2020),
        year(2021, { status: "mismatch", drift: "-50.00" }),
      ]),
    );
    const region = await findRegion();
    expect(within(region).queryByRole("list")).not.toBeInTheDocument();
    expect(within(region).queryByText("Further breaks:")).not.toBeInTheDocument();
    expect(within(region).queryByText(/The mismatch continues/)).not.toBeInTheDocument();
  });
});
