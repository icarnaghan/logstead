import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  importScheduleE,
  removeScheduleEImport,
  resetScheduleEImportClient,
  setScheduleEImportClient,
  type ImportSubmission,
} from "./scheduleEImport";

/**
 * Unit tests for the Schedule E Import API module (task 7.2).
 *
 * Each helper is exercised through the injectable client seam
 * (`setScheduleEImportClient`) backed by an injected `fetch`, so no network is
 * touched; we assert the method, path, and snake_case body sent to the backend.
 *
 * Design: Testing Strategy → frontend api.
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

afterEach(() => {
  resetScheduleEImportClient();
});

describe("scheduleEImport api", () => {
  it("importScheduleE posts the snake_case submission body to /imports/schedule-e", async () => {
    const outcome = {
      tax_year: 2023,
      entries: [
        {
          property_id: "p1",
          created_transaction_ids: ["t1", "t2"],
          deleted_prior_count: 0,
          created_inline_property: false,
        },
      ],
    };
    const { client, fetchImpl } = clientReturning(outcome, 201);
    setScheduleEImportClient(client);

    const submission: ImportSubmission = {
      tax_year: 2023,
      entries: [
        {
          property_id: "p1",
          lines: [
            { schedule_e_line: 3, amount: "24000.00" },
            { schedule_e_line: 14, amount: "1875.50" },
            { schedule_e_line: 19, amount: "320.00", description: "HOA dues" },
          ],
        },
        {
          new_property: { name: "Maple Duplex B", address_text: "12 Maple St" },
          lines: [{ schedule_e_line: 3, amount: "18000.00" }],
        },
      ],
    };

    const result = await importScheduleE(submission);

    expect(result).toEqual(outcome);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("https://api.test/imports/schedule-e");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      tax_year: 2023,
      entries: [
        {
          property_id: "p1",
          lines: [
            { schedule_e_line: 3, amount: "24000.00" },
            { schedule_e_line: 14, amount: "1875.50" },
            { schedule_e_line: 19, amount: "320.00", description: "HOA dues" },
          ],
        },
        {
          new_property: { name: "Maple Duplex B", address_text: "12 Maple St" },
          lines: [{ schedule_e_line: 3, amount: "18000.00" }],
        },
      ],
    });
  });

  it("removeScheduleEImport issues a DELETE to the encoded property/taxYear URL", async () => {
    const outcome = {
      property_id: "p 1",
      tax_year: 2023,
      deleted_count: 3,
    };
    const { client, fetchImpl } = clientReturning(outcome);
    setScheduleEImportClient(client);

    const result = await removeScheduleEImport("p 1", 2023);

    expect(result).toEqual(outcome);
    const [url, init] = fetchImpl.mock.calls[0];
    // Property id is percent-encoded and the tax year sits in the path.
    expect(url).toBe("https://api.test/imports/schedule-e/p%201/2023");
    expect(init?.method).toBe("DELETE");
  });
});
