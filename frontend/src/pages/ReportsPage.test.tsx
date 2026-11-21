import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import ReportsPage, { type ReportsApi } from "./ReportsPage";
import { ThemeProvider } from "../theme/ThemeProvider";
import { ToastProvider } from "../components/ui";
import { startDownload } from "../lib/packageJob";
import type { ScheduleEReport } from "../api/reports";
import { latestCompletedTaxYear } from "../lib/taxYears";

// The page loads the property's depreciable assets to size the tax-year range
// via the module-level `listAssets`. With an injected `years` prop the asset
// range is overridden, but the fetch still fires on mount, so stub it to an
// empty list (no network in jsdom).
vi.mock("../lib/packageJob", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/packageJob")>()),
  startDownload: vi.fn(),
}));

vi.mock("../api/assets", () => ({
  listAssets: vi.fn().mockResolvedValue([]),
}));

// The year-range hook fetches the earliest data year; resolve null (no
// activity) so no network is hit. Other exports stay real.
vi.mock("../api/properties", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/properties")>()),
  getEarliestDataYear: vi.fn().mockResolvedValue(null),
}));

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
    line12: {
      source: "transaction-entered",
      superseded_manual_interest: { amount: "0.00", count: 0 },
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

// Candidate years offered to the selector: the latest completed tax year (the
// default the page auto-loads) down through 2024, so both the mount default and
// an explicit "2024" selection are valid options regardless of the actual
// calendar year.
const LATEST_YEAR = latestCompletedTaxYear();
const YEARS = Array.from(
  { length: LATEST_YEAR - 2024 + 1 },
  (_, i) => LATEST_YEAR - i,
);

function renderPage(api: ReportsApi, search = "") {
  return render(
    <ThemeProvider>
      <ToastProvider>
      <MemoryRouter initialEntries={[`/properties/prop-1/reports${search}`]}>
        <Routes>
          <Route
            path="/properties/:propertyId/reports"
            element={<ReportsPage api={api} years={YEARS} />}
          />
        </Routes>
      </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
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
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Report line figures render as whole dollars: "24000.00" → "$24,000".
    expect(within(incomeSection).getByText("$24,000")).toBeInTheDocument();
    // "Repairs" now appears both in the expense line table and the chart's
    // always-present data table, so scope the assertion to the expense section.
    const expenseSection = screen
      .getByRole("heading", { name: /^expenses$/i })
      .closest("section") as HTMLElement;
    expect(within(expenseSection).getByText("Repairs")).toBeInTheDocument();

    // Line 18 depreciation total is shown.
    const depSection = screen
      .getByRole("heading", { name: /depreciation \(line 18\)/i })
      .closest("section") as HTMLElement;
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Line 18 rounds to whole dollars: "5833.33" → "$5,833".
    expect(within(depSection).getByText("$5,833")).toBeInTheDocument();

    // Line 19 itemization lists each description + amount (Req 10.5).
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // Line 19 item amounts round: "100.00" → "$100", "42.00" → "$42".
    expect(screen.getByText("HOA dues")).toBeInTheDocument();
    expect(screen.getByText("$100")).toBeInTheDocument();
    expect(screen.getByText("Bank fees")).toBeInTheDocument();
    expect(screen.getByText("$42")).toBeInTheDocument();
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
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // The net rounds half-up by magnitude: "16824.67" → "$16,825".
    expect(
      within(totalsSection).getByText("$16,825"),
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
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // The negative net rounds the magnitude and keeps the leading minus:
    // "-500.00" → "-$500". The "net loss" label above carries the loss cue.
    expect(within(totalsSection).getByText("-$500")).toBeInTheDocument();
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

describe("ReportsPage — empty/loading states (Req 9.1, 9.2, 9.3)", () => {
  it("auto-loads the latest completed year's report on mount (defaults to the latest filable year)", async () => {
    const api = makeApi();
    renderPage(api);

    // The page lands on the latest completed tax year and fetches it
    // immediately, rather than starting on an empty prompt.
    expect(await screen.findByText("Maple Duplex")).toBeInTheDocument();
    expect(api.getReport).toHaveBeenCalledWith("prop-1", LATEST_YEAR);
    expect(
      (screen.getByLabelText(/tax year/i) as HTMLSelectElement).value,
    ).toBe(String(LATEST_YEAR));
  });

  it("initializes the year from a valid ?year= and ignores an invalid one", async () => {
    const api = makeApi();
    const first = renderPage(api, "?year=2024");
    await screen.findByText("Maple Duplex");
    expect(api.getReport).toHaveBeenCalledWith("prop-1", 2024);
    first.unmount();
    const api2 = makeApi();
    renderPage(api2, "?year=02024");
    await screen.findByText("Maple Duplex");
    expect(api2.getReport).toHaveBeenCalledWith("prop-1", LATEST_YEAR);
  });
  it("returns to the empty state when the year is cleared", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await screen.findByText("Maple Duplex");

    // Choosing the placeholder clears the selection and the report.
    await user.selectOptions(screen.getByLabelText(/tax year/i), "");

    expect(
      await screen.findByRole("heading", { name: /no data for this year/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/reports are built from/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /go to transactions/i }),
    ).toHaveAttribute("href", expect.stringMatching(/\/transactions$/));
    expect(
      screen.getByRole("link", { name: /import a schedule e/i }),
    ).toHaveAttribute("href", "/imports/schedule-e");
  });

  it("shows a role=status loading state while the report is fetching", async () => {
    const user = userEvent.setup();
    let resolve: (report: ScheduleEReport) => void = () => {};
    const api = makeApi({
      getReport: vi.fn().mockImplementation(
        () =>
          new Promise<ScheduleEReport>((r) => {
            resolve = r;
          }),
      ),
    });
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");

    expect(
      await screen.findByRole("status", { name: /loading report/i }),
    ).toBeInTheDocument();

    resolve(makeReport());
    await screen.findByText("Maple Duplex");
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

describe("ReportsPage — hand-off document + print styling (Req 10.1-10.3)", () => {
  it("groups income, expenses, depreciation, other, and totals into sections", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    // Each report grouping is a delineated section with its own heading.
    for (const name of [
      /^income$/i,
      /^expenses$/i,
      /depreciation \(line 18\)/i,
      /other expenses \(line 19\)/i,
      /^totals$/i,
    ]) {
      const heading = screen.getByRole("heading", { name });
      expect(heading.closest("section")).not.toBeNull();
    }
  });

  it("emphasizes the net and labels it as income (not color alone)", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    const totalsSection = screen
      .getByRole("heading", { name: /^totals$/i })
      .closest("section") as HTMLElement;

    // Textual cue distinguishes income vs loss without relying on color.
    // Feature: depreciation-override-and-whole-dollar-display, Req 11.1
    // The emphasized net reads as whole dollars: "16824.67" → "$16,825"; the
    // font-bold/text-xl emphasis below is unchanged by the rounding.
    const netLabel = within(totalsSection).getByText(/net income/i);
    const netValue = within(totalsSection).getByText("$16,825");

    // The net is visually emphasized (larger + bolder than the sub-totals).
    expect(netLabel.className).toMatch(/font-bold/);
    expect(netValue.className).toMatch(/font-bold/);
    expect(netValue.className).toMatch(/text-xl/);
  });

  it("labels a negative net as a loss with the same emphasis", async () => {
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
    const netLabel = within(totalsSection).getByText(/net loss/i);
    expect(netLabel.className).toMatch(/font-bold/);
  });

  it("hides the report controls and download buttons from print output", async () => {
    const user = userEvent.setup();
    const api = makeApi();
    renderPage(api);

    // The controls region (tax-year selector) is hidden when printing.
    const controls = screen
      .getByRole("heading", { name: /report controls/i })
      .closest("section") as HTMLElement;
    expect(controls.className).toContain("print:hidden");

    await user.selectOptions(screen.getByLabelText(/tax year/i), "2024");
    await screen.findByText("Maple Duplex");

    // The download-button group is also excluded from print output.
    const downloadGroup = screen
      .getByRole("button", { name: /download csv/i })
      .closest("div") as HTMLElement;
    expect(downloadGroup.className).toContain("print:hidden");
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

describe("ReportsPage — Download PDF (Req 18.1, 18.3, 18.4)", () => {
  const pdf = {
    download_url: "https://s3.example/report.pdf",
    filename: "report.pdf",
    content_type: "application/pdf",
    size_bytes: 10,
    expires_in_seconds: 900,
  };

  beforeEach(() => {
    vi.mocked(startDownload).mockClear();
  });

  it("builds the PDF, shows a busy state, and starts the download", async () => {
    const user = userEvent.setup();
    let resolve!: (v: typeof pdf) => void;
    const createReportPdf = vi.fn(
      () => new Promise<typeof pdf>((r) => (resolve = r)),
    );
    renderPage(makeApi({ createReportPdf }));

    const button = await screen.findByRole("button", { name: /download pdf/i });
    await user.click(button);
    expect(createReportPdf).toHaveBeenCalledWith("prop-1", 2024);
    expect(button).toHaveAttribute("aria-busy", "true");

    resolve(pdf);
    await vi.waitFor(() =>
      expect(startDownload).toHaveBeenCalledWith(pdf.download_url),
    );
    await vi.waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
  });

  it("shows an error toast and re-enables the button on failure", async () => {
    const user = userEvent.setup();
    const createReportPdf = vi.fn().mockRejectedValue(new Error("PDF failed"));
    renderPage(makeApi({ createReportPdf }));

    const button = await screen.findByRole("button", { name: /download pdf/i });
    await user.click(button);

    expect(await screen.findByText("PDF failed")).toBeInTheDocument();
    expect(startDownload).not.toHaveBeenCalled();
    expect(button).toBeEnabled();
  });

  it("hides the PDF button from print", async () => {
    renderPage(makeApi());
    const button = await screen.findByRole("button", { name: /download pdf/i });
    expect(button.parentElement).toHaveClass("print:hidden");
  });
});
