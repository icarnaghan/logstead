import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { DashboardApi } from "./dashboard";

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
});
