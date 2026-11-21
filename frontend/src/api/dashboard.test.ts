import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { DashboardApi, type TrendsSeries } from "./dashboard";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiWith(fetchImpl: typeof fetch) {
  const client = new ApiClient({
    baseUrl: "https://api.example.com",
    getAuthToken: () => "t",
    fetchImpl,
  });
  return new DashboardApi(client);
}

describe("DashboardApi", () => {
  it("gets the dashboard without a tax year (backend defaults to current)", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { has_properties: false }));
    const api = apiWith(fetchImpl);

    await api.getDashboard();

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/dashboard");
  });

  it("appends the tax-year query when a year is supplied", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { has_properties: false }));
    const api = apiWith(fetchImpl);

    await api.getDashboard(2024);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/dashboard?taxYear=2024");
  });

  it("gets the per-property summaries with a tax year", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, []));
    const api = apiWith(fetchImpl);

    await api.getPropertySummaries(2023);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/dashboard/properties?taxYear=2023",
    );
  });

  it("gets the trends series from /dashboard/trends with no tax-year query", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [] }));
    const api = apiWith(fetchImpl);

    await api.getTrends();

    const [url] = fetchImpl.mock.calls[0];
    // The trends span is the full set of Data_Years; no taxYear is sent.
    expect(url).toBe("https://api.example.com/dashboard/trends");
  });

  it("passes the AbortSignal through to fetch for the trends request", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { years: [] }));
    const api = apiWith(fetchImpl);
    const controller = new AbortController();

    await api.getTrends(controller.signal);

    const [, init] = fetchImpl.mock.calls[0];
    expect(init.signal).toBe(controller.signal);
  });

  it("returns the trends series, with money fields typed as strings", async () => {
    const payload: TrendsSeries = {
      years: [
        {
          tax_year: 2023,
          total_income: "1500.00",
          total_expenses: "250.00",
          net: "1250.00",
          depreciation_total: "300.00",
          properties: [
            {
              property_id: "p1",
              property_name: "Maple St",
              total_income: "1500.00",
              total_expenses: "250.00",
              net: "1250.00",
            },
          ],
        },
      ],
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, payload));
    const api = apiWith(fetchImpl);

    const result = await api.getTrends();

    expect(result).toEqual(payload);

    // Type-level: money fields are declared as `string`. These assignments
    // only compile if the interfaces type them as strings, and the runtime
    // checks confirm the values arrive as strings.
    const year = result.years[0];
    const portfolioNet: string = year.net;
    const portfolioIncome: string = year.total_income;
    const portfolioExpenses: string = year.total_expenses;
    const depreciation: string = year.depreciation_total;
    const propertyNet: string = year.properties[0].net;
    expect(typeof portfolioNet).toBe("string");
    expect(typeof portfolioIncome).toBe("string");
    expect(typeof portfolioExpenses).toBe("string");
    expect(typeof depreciation).toBe("string");
    expect(typeof propertyNet).toBe("string");
    // `tax_year` stays a number — the one non-string field on a TrendYear.
    expect(typeof year.tax_year).toBe("number");
  });
});
