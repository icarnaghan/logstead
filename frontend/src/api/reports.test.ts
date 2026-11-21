import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  createCombinedReportPdf,
  createReportPdf,
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
    line12: {
      source: "transaction-entered",
      superseded_manual_interest: { amount: "0.00", count: 0 },
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
    line12: {
      total: "0.00",
      superseded_manual_interest: { amount: "0.00", count: 0 },
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

describe("Line 12 export rows (Requirement 6.10, Property 24)", () => {
  const loanLine12: ScheduleEReport["line12"] = {
    source: "loan-generated",
    superseded_manual_interest: { amount: "1234.00", count: 3 },
  };

  it("writes the three Line 12 rows directly after the line table", () => {
    const csv = reportToCsv(makeReport({ line12: loanLine12 }));
    const rows = csv.split("\n");

    const last = rows.indexOf("19,Other,expense,142.00");
    expect(rows.slice(last + 1, last + 5)).toEqual([
      "Line 12 Source,loan-generated",
      "Line 12 Superseded Manual Interest,1234.00",
      "Line 12 Superseded Transaction Count,3",
      "",
    ]);
  });

  it("writes transaction-entered detail with zero superseded values", () => {
    const csv = reportToCsv(makeReport());
    expect(csv).toContain("Line 12 Source,transaction-entered");
    expect(csv).toContain("Line 12 Superseded Manual Interest,0.00");
    expect(csv).toContain("Line 12 Superseded Transaction Count,0");
  });

  it("omits the Line 12 rows when line12 is absent", () => {
    const csv = reportToCsv(makeReport({ line12: undefined }));
    expect(csv).not.toContain("Line 12");
  });

  it("carries line12 verbatim, with money strings, in the JSON export", () => {
    const report = makeReport({ line12: loanLine12 });
    const json = reportToJson(report);
    expect(JSON.parse(json).line12).toEqual(loanLine12);
    expect(json).toContain('"amount": "1234.00"');
  });

  it("does not add a line12 key to JSON when absent", () => {
    const json = reportToJson(makeReport({ line12: undefined }));
    expect(JSON.parse(json)).not.toHaveProperty("line12");
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

const PDF_RESPONSE = {
  download_url: "https://files.example.com/a.pdf",
  filename: "schedule-e-maple-2024.pdf",
  content_type: "application/pdf",
  size_bytes: 1234,
  expires_in_seconds: 900,
};

describe("createReportPdf", () => {
  it("POSTs to the property PDF route with the taxYear query", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, PDF_RESPONSE));

    const pdf = await createReportPdf("a/b", 2024, clientWith(fetchImpl));

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/properties/a%2Fb/report/pdf?taxYear=2024",
    );
    expect(init.method).toBe("POST");
    expect(pdf.filename).toBe("schedule-e-maple-2024.pdf");
  });
});

describe("createCombinedReportPdf", () => {
  it("POSTs with only taxYear when no property ids are given", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, PDF_RESPONSE));

    await createCombinedReportPdf(2024, undefined, clientWith(fetchImpl));

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/reports/combined/pdf?taxYear=2024");
    expect(init.method).toBe("POST");
  });

  it("sends property ids as a comma-separated query value", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, PDF_RESPONSE));

    await createCombinedReportPdf(2024, ["p1", "p2"], clientWith(fetchImpl));

    const [url] = fetchImpl.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/reports/combined/pdf");
    expect(parsed.searchParams.get("propertyIds")).toBe("p1,p2");
  });
});
