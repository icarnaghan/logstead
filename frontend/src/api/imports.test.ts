import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  confirmImport,
  createImport,
  fileToBase64,
  getImport,
  listCategories,
  listDrafts,
  removeDraft,
  updateDraft,
  type Base64Reader,
} from "./imports";

/**
 * Unit tests for the expense-import API module (task 22.2 / 22.3).
 *
 * Each helper is exercised with an injected `fetch` so no network is touched;
 * we assert the method, path, and body sent to the backend.
 *
 * Validates: Requirements 6.1, 6.7, 6.8, 6.10
 */

/**
 * Build an `ApiClient` whose `fetch` returns the given JSON payload, and a spy
 * we can inspect for the request URL/method/body.
 */
function clientReturning(payload: unknown, status = 200) {
  const fetchImpl = vi.fn(
    async (_input: RequestInfo | URL, _init?: RequestInit) => {
      const body = payload === null ? null : JSON.stringify(payload);
      return new Response(body, {
        status,
        headers: { "content-type": "application/json" },
      });
    },
  );
  const client = new ApiClient({
    baseUrl: "https://api.test",
    getAuthToken: () => null,
    fetchImpl: fetchImpl as unknown as typeof fetch,
  });
  return { client, fetchImpl };
}

describe("imports api", () => {
  it("createImport posts snake_case body with pdf_base64", async () => {
    const session = {
      id: "s1",
      property_id: "p1",
      tax_year: 2023,
      status: "review",
    };
    const { client, fetchImpl } = clientReturning(session);

    const result = await createImport(
      "p1",
      2023,
      { pdfBase64: "QUJD", contentType: "application/pdf" },
      client,
    );

    expect(result).toEqual(session);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.test/imports");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      property_id: "p1",
      tax_year: 2023,
      content_type: "application/pdf",
      pdf_base64: "QUJD",
    });
  });

  it("createImport uses pdf_s3_key when provided", async () => {
    const { client, fetchImpl } = clientReturning({ id: "s1" });
    await createImport(
      "p1",
      2023,
      { pdfS3Key: "uploads/x.pdf", contentType: "application/pdf" },
      client,
    );
    const body = JSON.parse(fetchImpl.mock.calls[0][1]?.body as string);
    expect(body.pdf_s3_key).toBe("uploads/x.pdf");
    expect(body.pdf_base64).toBeUndefined();
  });

  it("getImport reads the session by id", async () => {
    const { client, fetchImpl } = clientReturning({ id: "s1", status: "review" });
    await getImport("s1", client);
    expect(fetchImpl.mock.calls[0][0]).toBe("https://api.test/imports/s1");
    expect(fetchImpl.mock.calls[0][1]?.method).toBe("GET");
  });

  it("listDrafts requests the drafts collection", async () => {
    const { client, fetchImpl } = clientReturning([]);
    await listDrafts("s1", client);
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "https://api.test/imports/s1/drafts",
    );
  });

  it("updateDraft PUTs editable fields", async () => {
    const { client, fetchImpl } = clientReturning({
      id: "d1",
      missing_fields: [],
    });
    await updateDraft("s1", "d1", { amount: "12.00" }, client);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.test/imports/s1/drafts/d1");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({ amount: "12.00" });
  });

  it("removeDraft issues a DELETE", async () => {
    const { client, fetchImpl } = clientReturning(null, 200);
    await removeDraft("s1", "d1", client);
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "https://api.test/imports/s1/drafts/d1",
    );
    expect(fetchImpl.mock.calls[0][1]?.method).toBe("DELETE");
  });

  it("confirmImport posts to the confirm endpoint", async () => {
    const outcome = {
      created_ids: ["t1"],
      rejected: [],
      converted_count: 1,
      remaining_incomplete: 0,
      session: { id: "s1", property_id: "p1", tax_year: 2023, status: "confirmed" },
    };
    const { client, fetchImpl } = clientReturning(outcome);
    const result = await confirmImport("s1", client);
    expect(result).toEqual(outcome);
    expect(fetchImpl.mock.calls[0][0]).toBe(
      "https://api.test/imports/s1/confirm",
    );
    expect(fetchImpl.mock.calls[0][1]?.method).toBe("POST");
  });

  it("listCategories reads the categories catalog", async () => {
    const { client, fetchImpl } = clientReturning([]);
    await listCategories(client);
    expect(fetchImpl.mock.calls[0][0]).toBe("https://api.test/categories");
  });
});

describe("fileToBase64", () => {
  it("strips the data-url prefix and returns the payload", async () => {
    // A fake reader that mimics FileReader's data-URL result.
    const reader: Base64Reader = {
      onload: null,
      onerror: null,
      result: null,
      readAsDataURL() {
        this.result = "data:application/pdf;base64,SGVsbG8=";
        this.onload?.();
      },
    };
    const value = await fileToBase64(new Blob(["x"]), () => reader);
    expect(value).toBe("SGVsbG8=");
  });

  it("rejects when the reader errors", async () => {
    const reader: Base64Reader = {
      onload: null,
      onerror: null,
      result: null,
      error: new Error("boom"),
      readAsDataURL() {
        this.onerror?.();
      },
    };
    await expect(fileToBase64(new Blob(["x"]), () => reader)).rejects.toThrow(
      "boom",
    );
  });
});
