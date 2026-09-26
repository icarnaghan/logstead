import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  getCombinedReport,
  getReport,
  reportToCsv,
  reportToJson,
  reportFilename,
  type CombinedScheduleEReport,
  type ScheduleEReport,
} from "./reports";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function clientWith(fetchImpl: typeof fetch): ApiClient {
  return new ApiClient({
    baseUrl: "https://api.example.com",
    getAuthToken: () => "t",
    fetchImpl,
  });
}

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

describe("getReport", () => {
  it("requests the per-property report with the taxYear query", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, makeReport()));
    const client = clientWith(fetchImpl);

    const report = await getReport("prop-1", 2024, client);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/properties/prop-1/report?taxYear=2024",
    );
    expect(report.header.property_name).toBe("Maple Duplex");
    expect(report.lines).toHaveLength(4);
  });

  it("encodes the property id in the path", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, makeReport()));
    const client = clientWith(fetchImpl);

    await getReport("a/b", 2023, client);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/properties/a%2Fb/report?taxYear=2023",
    );
  });
});

function makeCombined(
  overrides: Partial<CombinedScheduleEReport> = {},
): CombinedScheduleEReport {
  return {
    tax_year: 2024,
    properties: [makeReport()],
    totals: {
      total_income: "24000.00",
      total_expenses: "7175.33",
      net: "16824.67",
    },
    ...overrides,
  };
}

describe("getCombinedReport", () => {
  it("requests the combined report with the taxYear query", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, makeCombined()));
    const client = clientWith(fetchImpl);

    const combined = await getCombinedReport(2024, client);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/reports/combined?taxYear=2024");
    expect(combined.tax_year).toBe(2024);
    expect(combined.properties).toHaveLength(1);
    expect(combined.totals.net).toBe("16824.67");
  });

  it("parses multiple property reports preserving money strings", async () => {
    const body = makeCombined({
      properties: [
        makeReport(),
        makeReport({
          header: { ...makeReport().header, property_name: "Oak Cottage" },
        }),
      ],
    });
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, body));
    const client = clientWith(fetchImpl);

    const combined = await getCombinedReport(2024, client);

    expect(combined.properties).toHaveLength(2);
    expect(combined.properties[1].header.property_name).toBe("Oak Cottage");
    expect(combined.totals.total_income).toBe("24000.00");
  });
});

describe("reportToJson", () => {
  it("round-trips the report preserving money strings verbatim", () => {
    const report = makeReport();
    const json = reportToJson(report);
    expect(JSON.parse(json)).toEqual(report);
    // Money is preserved as a two-decimal string, not a number.
    expect(json).toContain('"net": "16824.67"');
  });
});

describe("reportToCsv", () => {
  it("serializes the header, lines, Line 19 itemization, and totals", () => {
    const csv = reportToCsv(makeReport());

    expect(csv).toContain("Property,Maple Duplex");
    expect(csv).toContain("Tax Year,2024");
    expect(csv).toContain("Fair Rental Days,300");
    expect(csv).toContain("Personal Use Days,5");
    expect(csv).toContain("Line,Label,Kind,Amount");
    expect(csv).toContain("3,Rents received,income,24000.00");
    expect(csv).toContain("18,Depreciation,expense,5833.33");
    expect(csv).toContain("HOA dues,100.00");
    expect(csv).toContain("Total Income,24000.00");
    expect(csv).toContain("Total Expenses,7175.33");
    expect(csv).toContain("Net,16824.67");
  });

  it("quotes fields containing commas", () => {
    const csv = reportToCsv(
      makeReport({
        other_items: [{ description: "Fees, misc", amount: "10.00" }],
      }),
    );
    expect(csv).toContain('"Fees, misc",10.00');
  });

  it("serializes a net loss as a negative total", () => {
    const csv = reportToCsv(
      makeReport({
        totals: {
          total_income: "1000.00",
          total_expenses: "1500.00",
          net: "-500.00",
        },
      }),
    );
    expect(csv).toContain("Net,-500.00");
  });
});

describe("reportFilename", () => {
  it("builds a slugged filename with the tax year and format", () => {
    const report = makeReport();
    expect(reportFilename(report, "csv")).toBe(
      "schedule-e-maple-duplex-2024.csv",
    );
    expect(reportFilename(report, "json")).toBe(
      "schedule-e-maple-duplex-2024.json",
    );
  });

  it("falls back to 'property' when the name has no slug characters", () => {
    const report = makeReport({
      header: { ...makeReport().header, property_name: "***" },
    });
    expect(reportFilename(report, "csv")).toBe("schedule-e-property-2024.csv");
  });
});
