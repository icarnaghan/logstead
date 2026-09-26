import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import ReportsPage, { type ReportsApi } from "./ReportsPage";
import type { ScheduleEReport } from "../api/reports";

/**
 * Component tests for the per-property Schedule E report page (task 24.1,
 * Requirement 10). The reports API is fully mocked, so these tests exercise the
 * UI behaviour (year selection → fetch → render, net-loss display, and the
 * client-side CSV/JSON download) without any network access.
 */

function makeReport(overrides: Partial<ScheduleEReport> = {}): ScheduleEReport {
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
    other_items: [
      { description: "HOA dues", amount: "100.00" },
      { description: "Bank fees", amount: "42.00" },
    ],
    totals: {
      total_income: "24000.00",
      total_expenses: "7175.33",
      net: "16824.67",
    },
    ...overrides,
  };
}

function makeApi(overrides: Partial<ReportsApi> = {}): ReportsApi {
  return {
    getReport: vi.fn().mockResolvedValue(makeReport()),
    ...overrides,
  };
}

const YEARS = [2024, 2023, 2022] as const;

function renderPage(api: ReportsApi) {
  return render(
    <MemoryRouter initialEntries={["/properties/prop-1/reports"]}>
      <Routes>
        <Route
          path="/properties/:propertyId/reports"
          element={<ReportsPage api={api} years={YEARS} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportsPage — year selection fetches and renders (Req 10.1-10.5)", () => {
  it("fetches the report for the selected year and renders the header", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByText("Maple Duplex")).toBeInTheDocument();
    expect(api.getReport).toHaveBeenCalledWith("prop-1", 2024);

    // Header includes address, property type, and the usage days (Req 10.2).
    expect(
      screen.getByText("123 Maple St, Springfield"),
    ).toBeInTheDocument();
    expect(screen.getByText("Multi-Family")).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders per-line totals, Line 18 depreciation, and Line 19 itemization", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    // Income and expense line totals (formatted from the two-decimal strings).
    const incomeSection = screen
      .getByRole("heading", { name: /^income$/i })
      .closest("section") as HTMLElement;
    expect(within(incomeSection).getByText("Rents received")).toBeInTheDocument();
    expect(within(incomeSection).getByText("$24,000.00")).toBeInTheDocument();
    expect(screen.getByText("Repairs")).toBeInTheDocument();

    // Line 18 depreciation total is shown.
    const depSection = screen
      .getByRole("heading", { name: /depreciation \(line 18\)/i })
      .closest("section") as HTMLElement;
    expect(within(depSection).getByText("$5,833.33")).toBeInTheDocument();

    // Line 19 itemization lists each description + amount (Req 10.5).
    expect(screen.getByText("HOA dues")).toBeInTheDocument();
    expect(screen.getByText("$100.00")).toBeInTheDocument();
    expect(screen.getByText("Bank fees")).toBeInTheDocument();
    expect(screen.getByText("$42.00")).toBeInTheDocument();
  });

  it("renders total income, total expenses, and a positive net (Req 10.4)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    const totalsSection = screen
      .getByRole("heading", { name: /^totals$/i })
      .closest("section") as HTMLElement;
    expect(within(totalsSection).getByText(/net income/i)).toBeInTheDocument();
    expect(
      within(totalsSection).getByText("$16,824.67"),
    ).toBeInTheDocument();
  });

  it("shows a net loss when net is negative", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      getReport: vi.fn().mockResolvedValue(
        makeReport({
          totals: {
            total_income: "1000.00",
            total_expenses: "1500.00",
            net: "-500.00",
          },
        }),
      ),
    });
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    const totalsSection = screen
      .getByRole("heading", { name: /^totals$/i })
      .closest("section") as HTMLElement;
    expect(within(totalsSection).getByText(/net loss/i)).toBeInTheDocument();
    // toLocaleString currency renders a negative amount as -$500.00.
    expect(within(totalsSection).getByText("-$500.00")).toBeInTheDocument();
  });

  it("surfaces an error message when the fetch fails", async () => {
    const user = userEvent.setup();
    const api = makeApi({
      getReport: vi.fn().mockRejectedValue(new Error("boom")),
    });
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /unable to load the schedule e report/i,
    );
  });
});

describe("ReportsPage — client-side export (Req 10.7)", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;
  let clickSpy: ReturnType<typeof vi.spyOn>;
  let blobSpy: ReturnType<typeof vi.spyOn>;
  let captured: { type: string; content: string }[];

  beforeEach(() => {
    captured = [];
    const RealBlob = globalThis.Blob;
    // jsdom's Blob does not expose .text(), so record the string parts and MIME
    // type at construction time to assert the serialized download content.
    blobSpy = vi
      .spyOn(globalThis, "Blob")
      .mockImplementation(
        (parts?: BlobPart[], options?: BlobPropertyBag) => {
          captured.push({
            type: options?.type ?? "",
            content: (parts ?? []).map((part) => String(part)).join(""),
          });
          return new RealBlob(parts, options);
        },
      ) as unknown as ReturnType<typeof vi.spyOn>;
    createObjectURL = vi.fn(() => {
      return "blob:mock-url";
    });
    revokeObjectURL = vi.fn();
    // jsdom does not implement the object-URL APIs.
    (
      URL as unknown as { createObjectURL: unknown }
    ).createObjectURL = createObjectURL;
    (
      URL as unknown as { revokeObjectURL: unknown }
    ).revokeObjectURL = revokeObjectURL;
    // Prevent jsdom "navigation not implemented" noise from the anchor click.
    clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
  });

  afterEach(() => {
    clickSpy.mockRestore();
    blobSpy.mockRestore();
  });

  it("downloads the fetched report serialized as CSV", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    await user.click(screen.getByRole("button", { name: /download csv/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const [entry] = captured;
    expect(entry.type).toBe("text/csv");
    expect(entry.content).toContain("Property,Maple Duplex");
    expect(entry.content).toContain("18,Depreciation,expense,5833.33");
    expect(entry.content).toContain("Net,16824.67");
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });

  it("downloads the fetched report serialized as JSON", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    await user.click(screen.getByRole("button", { name: /download json/i }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const [entry] = captured;
    expect(entry.type).toBe("application/json");
    expect(JSON.parse(entry.content)).toEqual(makeReport());
  });
});

describe("ReportsPage — accessibility", () => {
  it("has no automatically detectable a11y violations after rendering a report", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    const { container } = renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    expect(await axe(container)).toHaveNoViolations();
  });
});
