import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import { TransactionsApi, fieldErrorFrom } from "./transactions";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function apiWith(fetchImpl: typeof fetch, uploadFetch?: typeof fetch) {
  const client = new ApiClient({
    baseUrl: "https://api.example.com",
    getAuthToken: () => "t",
    fetchImpl,
  });
  return new TransactionsApi(client, uploadFetch ?? fetchImpl);
}

describe("TransactionsApi", () => {
  it("lists transactions without a tax year (all years)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, []));
    const api = apiWith(fetchImpl);

    await api.listTransactions("p1");

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/properties/p1/transactions");
  });

  it("appends the tax-year query when filtering", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, []));
    const api = apiWith(fetchImpl);

    await api.listTransactions("p1", 2024);

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe(
      "https://api.example.com/properties/p1/transactions?taxYear=2024",
    );
  });

  it("posts the create body to the property transactions path", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse(201, { id: "t1" }));
    const api = apiWith(fetchImpl);

    await api.createTransaction("p1", {
      date: "2024-03-01",
      amount: "125.00",
      type: "expense",
      category_id: "repairs",
    });

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.example.com/properties/p1/transactions");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      date: "2024-03-01",
      amount: "125.00",
      type: "expense",
      category_id: "repairs",
    });
  });

  it("attaches a receipt then PUTs bytes to the pre-signed URL", async () => {
    const apiFetch = vi.fn().mockResolvedValue(
      jsonResponse(201, {
        upload_url: "https://s3.example.com/put?sig=abc",
        document: { id: "d1", filename: "r.pdf", content_type: "application/pdf" },
      }),
    );
    const uploadFetch = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    const api = apiWith(apiFetch, uploadFetch);

    const result = await api.attachReceipt(
      "p1",
      "t1",
      "r.pdf",
      "application/pdf",
    );
    expect(result.upload_url).toContain("s3.example.com");

    const [attachUrl, attachInit] = apiFetch.mock.calls[0];
    expect(attachUrl).toBe(
      "https://api.example.com/properties/p1/transactions/t1/receipts",
    );
    expect(JSON.parse(attachInit.body as string)).toEqual({
      filename: "r.pdf",
      content_type: "application/pdf",
    });

    const blob = new Blob(["bytes"], { type: "application/pdf" });
    await api.uploadToPresignedUrl(result.upload_url, blob, "application/pdf");

    const [putUrl, putInit] = uploadFetch.mock.calls[0];
    expect(putUrl).toBe("https://s3.example.com/put?sig=abc");
    expect(putInit.method).toBe("PUT");
  });
});

describe("fieldErrorFrom", () => {
  it("extracts a field + message from a 400 body", () => {
    expect(
      fieldErrorFrom({ field: "description", message: "required" }),
    ).toEqual({ field: "description", message: "required" });
  });

  it("returns null for a body with neither field nor message", () => {
    expect(fieldErrorFrom({ other: 1 })).toBeNull();
    expect(fieldErrorFrom(null)).toBeNull();
  });
});
