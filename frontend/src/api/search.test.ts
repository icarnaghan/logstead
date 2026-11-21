import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { SearchApi } from "./search";

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
  return new SearchApi(client);
}

const EMPTY = { query: "x", groups: [], truncated: false, scanned: 0 };

describe("SearchApi", () => {
  it("gets /search with only q when no options are given", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, EMPTY));
    await apiWith(fetchImpl).search("water");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/search?q=water");
    expect(init.method).toBe("GET");
  });

  it("encodes q and appends limit and propertyId", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, EMPTY));
    await apiWith(fetchImpl).search("a&b c", { limit: 5, propertyId: "p1" });
    const [url] = fetchImpl.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/search");
    expect(parsed.searchParams.get("q")).toBe("a&b c");
    expect(parsed.searchParams.get("limit")).toBe("5");
    expect(parsed.searchParams.get("propertyId")).toBe("p1");
  });

  it("passes the AbortSignal through to fetch", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, EMPTY));
    const controller = new AbortController();
    await apiWith(fetchImpl).search("x", { signal: controller.signal });
    const [, init] = fetchImpl.mock.calls[0];
    expect(init.signal).toBe(controller.signal);
  });

  it("returns the parsed response", async () => {
    const payload = {
      query: "water",
      truncated: true,
      scanned: 3,
      groups: [
        {
          kind: "transaction",
          total: 1,
          hits: [
            {
              kind: "transaction",
              id: "t1",
              property_id: "p1",
              title: "Water bill",
              subtitle: null,
              matched_field: "description",
              link: "/properties/p1/transactions?year=2024",
              amount: "125.00",
              date: "2024-03-07",
            },
          ],
        },
      ],
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, payload));
    expect(await apiWith(fetchImpl).search("water")).toEqual(payload);
  });
});
