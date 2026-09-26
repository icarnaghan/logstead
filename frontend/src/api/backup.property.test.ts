import { afterEach, describe, expect, it, vi } from "vitest";
import fc from "fast-check";
import { ApiClient } from "../lib/apiClient";
import {
  fetchBackup,
  resetBackupClient,
  restoreBackup,
  setBackupClient,
  type BackupDocument,
} from "./backup";

/**
 * Property-based test for the Backup API module (task 10.3).
 *
 * Complements the example-based unit tests in `backup.test.ts` by asserting,
 * across many generated documents, that money and coordinate fields consumed
 * and produced by `api/backup.ts` remain typed and valued as `string` — never
 * silently coerced to `number` — when round-tripped through a fake client.
 *
 * Style mirrors `lib/money.property.test.ts` (fast-check, numRuns 100).
 */

/**
 * Arbitrary two-decimal money string of the shape `(-)?<digits>.<2 digits>`,
 * e.g. "0.00", "1250.00", "-42.99". Constrained to the money input space.
 */
const moneyString: fc.Arbitrary<string> = fc
  .tuple(fc.boolean(), fc.nat({ max: 99_999_999 }), fc.integer({ min: 0, max: 99 }))
  .map(([negative, dollars, cents]) => {
    const sign = negative && (dollars > 0 || cents > 0) ? "-" : "";
    return `${sign}${dollars}.${String(cents).padStart(2, "0")}`;
  });

/** Arbitrary full-precision coordinate string, e.g. "-122.4194155". */
const coordinateString: fc.Arbitrary<string> = fc
  .tuple(fc.boolean(), fc.integer({ min: 0, max: 180 }), fc.nat({ max: 9_999_999 }))
  .map(([negative, whole, frac]) => {
    const sign = negative ? "-" : "";
    return `${sign}${whole}.${String(frac).padStart(7, "0")}`;
  });

/** Arbitrary integer-valued recovery period expressed as a string. */
const recoveryString: fc.Arbitrary<string> = fc
  .integer({ min: 1, max: 40 })
  .map((n) => String(n));

const uuidish: fc.Arbitrary<string> = fc
  .array(fc.integer({ min: 0, max: 15 }), { minLength: 8, maxLength: 12 })
  .map((digits) => digits.map((d) => d.toString(16)).join(""));

const backupDocument: fc.Arbitrary<BackupDocument> = fc.record({
  schema_version: fc.constant("1"),
  exported_at: fc.constant("2024-01-01T00:00:00Z"),
  properties: fc.array(
    fc.record({
      id: uuidish,
      name: fc.string({ minLength: 1, maxLength: 20 }),
      address_text: fc.string({ minLength: 1, maxLength: 40 }),
      details: fc.record({
        latitude: coordinateString,
        longitude: coordinateString,
        last_sale_price: moneyString,
        bathrooms: moneyString,
      }),
      note: fc.constant(null),
      usage: fc.array(
        fc.record({
          tax_year: fc.integer({ min: 2000, max: 2100 }),
          fair_rental_days: fc.integer({ min: 0, max: 365 }),
          personal_use_days: fc.integer({ min: 0, max: 365 }),
        }),
        { maxLength: 3 },
      ),
      transactions: fc.array(
        fc.record({
          id: uuidish,
          property_id: uuidish,
          date: fc.constant("2023-05-01"),
          amount: moneyString,
          type: fc.constantFrom("income" as const, "expense" as const),
          category_id: fc.constantFrom("rents-received", "repairs", "insurance"),
        }),
        { maxLength: 4 },
      ),
      assets: fc.array(
        fc.record({
          id: uuidish,
          property_id: uuidish,
          description: fc.string({ minLength: 1, maxLength: 20 }),
          cost_basis: moneyString,
          placed_in_service_date: fc.constant("2023-02-01"),
          recovery_period_years: recoveryString,
        }),
        { maxLength: 3 },
      ),
    }),
    { maxLength: 3 },
  ),
});

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** Assert every money/coordinate field in a document is a string. */
function assertMoneyStrings(doc: BackupDocument): void {
  expect(typeof doc.schema_version).toBe("string");
  for (const property of doc.properties) {
    const details = property.details;
    if (details) {
      for (const key of ["latitude", "longitude", "last_sale_price", "bathrooms"] as const) {
        const value = details[key];
        if (value !== undefined && value !== null) {
          expect(typeof value).toBe("string");
        }
      }
    }
    for (const txn of property.transactions) {
      expect(typeof txn.amount).toBe("string");
    }
    for (const asset of property.assets) {
      expect(typeof asset.cost_basis).toBe("string");
      expect(typeof asset.recovery_period_years).toBe("string");
    }
  }
}

afterEach(() => {
  resetBackupClient();
  vi.restoreAllMocks();
});

// Feature: backup-restore, Property 1 (money exactness): round-trip through api/backup.ts keeps money as string
describe("Property 1 (money exactness): round-trip through api/backup.ts keeps money as string", () => {
  it("preserves money/coordinate fields as string on both fetch and restore paths", async () => {
    await fc.assert(
      fc.asyncProperty(backupDocument, async (doc) => {
        // Every generated field is already a string; sanity-check the input.
        assertMoneyStrings(doc);

        // fetchBackup: the document returned by the server is parsed by the
        // real client path and must keep money/coords as string.
        const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(200, doc)));
        setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl }));
        const fetched = await fetchBackup();
        assertMoneyStrings(fetched);
        expect(fetched).toEqual(doc);

        // restoreBackup: the document sent as the JSON body must serialize the
        // money/coordinate fields as strings (no numeric coercion in transit).
        let capturedBody: BackupDocument | undefined;
        const restoreFetch = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
          capturedBody = JSON.parse(String(init?.body)) as BackupDocument;
          return Promise.resolve(
            jsonResponse(200, {
              properties: doc.properties.length,
              transactions: 0,
              assets: 0,
              usage_years: 0,
            }),
          );
        });
        setBackupClient(new ApiClient({ baseUrl: "https://api.test", fetchImpl: restoreFetch }));
        await restoreBackup(doc);
        expect(capturedBody).toBeDefined();
        assertMoneyStrings(capturedBody as BackupDocument);
        expect(capturedBody).toEqual(doc);
      }),
      { numRuns: 100 },
    );
  });
});
