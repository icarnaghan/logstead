import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  clearData,
  fetchBackup,
  resetBackupClient,
  restoreBackup,
  setBackupClient,
  type BackupDocument,
  type ClearSummary,
  type RestoreSummary,
} from "./backup";

/**
 * Tests for the feature-scoped Backup API module.
 *
 * These inject an {@link ApiClient} backed by a fake `fetch` so the real
 * request-building / JSON-parsing path is exercised without hitting the
 * network (never any live calls).
 */

function makeFetch(handler: (url: string, init: RequestInit) => Response) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    Promise.resolve(handler(String(input), init ?? {})),
  );
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** A small but complete document with money/coords as strings. */
function sampleDocument(): BackupDocument {
  return {
    schema_version: "1",
    exported_at: "2024-01-02T03:04:05Z",
    properties: [
      {
        id: "prop-1",
        name: "Maple Duplex",
        address_text: "1 Maple St",
        property_type: "single_family",
        created_at: "2023-01-01T00:00:00Z",
        updated_at: "2023-06-01T00:00:00Z",
        details: {
          latitude: "37.7749295",
          longitude: "-122.4194155",
          last_sale_price: "525000.00",
          bathrooms: "2.5",
        },
        note: "Roof replaced 2023",
        usage: [{ tax_year: 2023, fair_rental_days: 300, personal_use_days: 10 }],
        transactions: [
          {
            id: "txn-1",
            property_id: "prop-1",
            date: "2023-05-01",
            amount: "1250.00",
            type: "income",
            category_id: "rents-received",
            schedule_e_line: 3,
            description: "May rent",
          },
        ],
        assets: [
          {
            id: "asset-1",
            property_id: "prop-1",
            description: "Refrigerator",
            cost_basis: "1800.00",
            placed_in_service_date: "2023-02-01",
            recovery_period_years: "5",
          },
        ],
      },
    ],
  };
}

afterEach(() => {
  resetBackupClient();
  vi.restoreAllMocks();
});

describe("backup api module", () => {
  it("fetches a backup via GET /backup and returns the typed document", async () => {
    const doc = sampleDocument();
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/backup$/);
      expect(init.method ?? "GET").toBe("GET");
      return jsonResponse(200, doc);
    });
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await fetchBackup();
    expect(result).toEqual(doc);
    // Money/coordinate fields survive as strings, never coerced to number.
    expect(typeof result.properties[0].transactions[0].amount).toBe("string");
    expect(typeof result.properties[0].assets[0].cost_basis).toBe("string");
    expect(typeof result.properties[0].details?.latitude).toBe("string");
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("restores via POST /backup/restore sending the document as the JSON body", async () => {
    const doc = sampleDocument();
    const summary: RestoreSummary = {
      properties: 1,
      transactions: 1,
      assets: 1,
      usage_years: 1,
    };
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/backup\/restore$/);
      expect(init.method).toBe("POST");
      // The whole document is sent verbatim as the request body.
      expect(JSON.parse(String(init.body))).toEqual(doc);
      return jsonResponse(200, summary);
    });
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await restoreBackup(doc);
    expect(result).toEqual(summary);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("clears data via POST /backup/clear and returns the summary", async () => {
    const summary: ClearSummary = {
      properties: 2,
      transactions: 10,
      assets: 3,
      photos: 4,
      receipts: 5,
      failed_s3_keys: [],
    };
    const fetchImpl = makeFetch((url, init) => {
      expect(url).toMatch(/\/backup\/clear$/);
      expect(init.method).toBe("POST");
      return jsonResponse(200, summary);
    });
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await clearData();
    expect(result).toEqual(summary);
    expect(fetchImpl).toHaveBeenCalledOnce();
  });

  it("surfaces a 400 restore validation failure as an ApiError with status + message", async () => {
    const doc = sampleDocument();
    const fetchImpl = makeFetch(() =>
      jsonResponse(400, {
        error: "validation",
        message: "transaction txn-1: amount must have two decimals",
      }),
    );
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    await expect(restoreBackup(doc)).rejects.toMatchObject({
      status: 400,
      message: "transaction txn-1: amount must have two decimals",
    });
  });
});
