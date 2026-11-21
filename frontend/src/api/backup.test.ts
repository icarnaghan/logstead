import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "../lib/apiClient";
import {
  clearData,
  fetchBackup,
  resetBackupClient,
  restoreBackup,
  setBackupClient,
  type BackupDocument,
  type BackupLoan,
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

  it("keeps loan money and rate as strings through fetch", async () => {
    const doc = sampleDocument();
    const loan: BackupLoan = {
      id: "loan-1",
      property_id: "prop-1",
      description: "Primary mortgage",
      annual_interest_rate: "6.125000",
      monthly_payment: "1900.00",
      anchor_balance: "214500.00",
      anchor_date: "2025-06-01",
      extra_principal: "50.00",
      original_principal: "300000.00",
      closing_date: "2023-01-15",
      payoff_date: null,
      include_in_report: true,
      interest_overrides: { "2023": "5400.25" },
    };
    doc.properties[0].loans = [loan];
    const fetchImpl = makeFetch(() => jsonResponse(200, doc));
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await fetchBackup();
    const got = result.properties[0].loans?.[0];
    expect(got).toEqual(loan);
    expect(typeof got?.original_principal).toBe("string");
    expect(typeof got?.annual_interest_rate).toBe("string");
    expect(typeof got?.monthly_payment).toBe("string");
    expect(typeof got?.anchor_balance).toBe("string");
    expect(typeof got?.anchor_date).toBe("string");
    expect(got).not.toHaveProperty("term_months");
    expect(got).not.toHaveProperty("first_payment_date");
    expect(got).not.toHaveProperty("payment_override");
    expect(typeof got?.extra_principal).toBe("string");
    expect(typeof got?.interest_overrides?.["2023"]).toBe("string");
  });

  it("restores a document with loans verbatim and returns a loans count", async () => {
    const doc = sampleDocument();
    doc.properties[0].loans = [
      {
        id: "loan-1",
        property_id: "prop-1",
        description: "Primary mortgage",
        annual_interest_rate: "6.125000",
        monthly_payment: "1900.00",
        anchor_balance: "214500.00",
        anchor_date: "2025-06-01",
        original_principal: "300000.00",
      },
    ];
    const summary: RestoreSummary = {
      properties: 1,
      transactions: 1,
      assets: 1,
      usage_years: 1,
      loans: 1,
    };
    const fetchImpl = makeFetch((_url, init) => {
      const sent = JSON.parse(String(init.body)) as BackupDocument;
      expect(sent).toEqual(doc);
      expect(sent.properties[0].loans?.[0].original_principal).toBe("300000.00");
      expect(sent.properties[0].loans?.[0].annual_interest_rate).toBe("6.125000");
      expect(sent.properties[0].loans?.[0].anchor_balance).toBe("214500.00");
      return jsonResponse(200, summary);
    });
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await restoreBackup(doc);
    expect(result.loans).toBe(1);
    expect(result).toEqual(summary);
  });

  it("returns a loans count on the clear summary", async () => {
    const summary: ClearSummary = {
      properties: 1,
      transactions: 0,
      assets: 0,
      photos: 0,
      receipts: 0,
      loans: 2,
      failed_s3_keys: [],
    };
    const fetchImpl = makeFetch(() => jsonResponse(200, summary));
    setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));

    const result = await clearData();
    expect(result.loans).toBe(2);
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
