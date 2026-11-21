import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { ItemizedApi } from "./itemized";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function setup(status = 200, body: unknown = {}) {
  const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(status, body));
  const client = new ApiClient({
    baseUrl: "https://api.example.com",
    getAuthToken: () => "t",
    fetchImpl,
  });
  return { api: new ItemizedApi(client), fetchImpl };
}

const BASE = "https://api.example.com/properties/p1/itemized/repairs";

describe("ItemizedApi", () => {
  it("gets the summary with the taxYear query", async () => {
    const { api, fetchImpl } = setup();
    await api.getSummary("p1", "repairs", 2023);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}?taxYear=2023`);
    expect(init.method).toBe("GET");
  });

  it("posts a new entry to the entries path", async () => {
    const { api, fetchImpl } = setup(201, { id: "e1" });
    const input = {
      date: "2023-09-02",
      amount: "620.00",
      description: "Plumber",
      notes: "Invoice 1182",
    };
    await api.createEntry("p1", "repairs", input);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/entries`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual(input);
  });

  it("puts entry edits to the entry path", async () => {
    const { api, fetchImpl } = setup();
    const input = { date: "2023-09-02", amount: "10.00", description: "x" };
    await api.updateEntry("p1", "repairs", "e 1", input);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/entries/e%201`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual(input);
  });

  it("deletes an entry", async () => {
    const { api, fetchImpl } = setup(200, null);
    await api.deleteEntry("p1", "repairs", "e1");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/entries/e1`);
    expect(init.method).toBe("DELETE");
  });

  it("sets the total with tax_year and amount in the body", async () => {
    const { api, fetchImpl } = setup();
    await api.setTotal("p1", "repairs", 2023, "4200.00");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/total`);
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({
      tax_year: 2023,
      amount: "4200.00",
    });
  });

  it("removes the total with the taxYear query", async () => {
    const { api, fetchImpl } = setup();
    await api.removeTotal("p1", "repairs", 2023);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/total?taxYear=2023`);
    expect(init.method).toBe("DELETE");
  });
});
