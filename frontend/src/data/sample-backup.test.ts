import { describe, expect, it } from "vitest";
import type {
  BackupDocument,
  BackupProperty,
  BackupTransaction,
} from "../api/backup";
import sampleBackupJson from "./sample-backup.json";

/**
 * Fixture integrity test for `sample-backup.json` (Task 11.2).
 *
 * The fixture is bundled and imported directly so it is type-checked against
 * {@link BackupDocument} at build time. This test guards against fixture rot by
 * asserting the runtime shape and the invariants the backend `validate_document`
 * accepts: `schema_version === "1"`, exactly 2 properties, 5 distinct tax years
 * with both income and expense per property, >= 1 asset per property, money
 * fields as two-decimal strings, coordinates as numeric strings, non-empty ids,
 * and cross-references that resolve within the document.
 *
 * The JSON import widens the `type` literal union to `string`, so we cast to
 * {@link BackupDocument} for typed access.
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.4
 */

const backup = sampleBackupJson as BackupDocument;

/** Two-decimal money string, e.g. "18000.00" or "-1250.00". */
const MONEY_RE = /^-?\d+\.\d{2}$/;
/** A numeric string (integer or decimal, optionally signed), e.g. "39.78173". */
const NUMERIC_STRING_RE = /^-?\d+(\.\d+)?$/;

function isNonEmptyString(value: unknown): boolean {
  return typeof value === "string" && value.length > 0;
}

describe("sample-backup.json fixture", () => {
  it("has schema_version '1' and a non-empty exported_at", () => {
    expect(backup.schema_version).toBe("1");
    expect(isNonEmptyString(backup.exported_at)).toBe(true);
  });

  it("contains exactly 2 properties", () => {
    expect(Array.isArray(backup.properties)).toBe(true);
    expect(backup.properties).toHaveLength(2);
  });

  it("gives every property a non-empty id and required string fields", () => {
    for (const property of backup.properties) {
      expect(isNonEmptyString(property.id)).toBe(true);
      expect(isNonEmptyString(property.name)).toBe(true);
      expect(isNonEmptyString(property.address_text)).toBe(true);
      expect(Array.isArray(property.transactions)).toBe(true);
      expect(Array.isArray(property.assets)).toBe(true);
    }
  });

  it("represents 5 distinct tax years with income + expense per property", () => {
    for (const property of backup.properties) {
      const income = property.transactions.filter((t) => t.type === "income");
      const expense = property.transactions.filter((t) => t.type === "expense");

      expect(income.length).toBeGreaterThan(0);
      expect(expense.length).toBeGreaterThan(0);

      const taxYears = new Set(
        property.transactions.map((t) => t.date.slice(0, 4)),
      );
      expect(taxYears.size).toBe(5);
    }
  });

  it("gives every property at least one asset", () => {
    for (const property of backup.properties) {
      expect(property.assets.length).toBeGreaterThanOrEqual(1);
    }
  });

  it("uses two-decimal money strings for every transaction amount", () => {
    for (const property of backup.properties) {
      for (const txn of property.transactions) {
        expect(txn.amount).toMatch(MONEY_RE);
      }
    }
  });

  it("uses two-decimal money strings for every asset cost_basis", () => {
    for (const property of backup.properties) {
      for (const asset of property.assets) {
        expect(asset.cost_basis).toMatch(MONEY_RE);
      }
    }
  });

  it("uses two-decimal money strings for any nested details money", () => {
    for (const property of backup.properties) {
      const details = property.details;
      if (!details) continue;

      if (details.hoa?.fee != null) {
        expect(details.hoa.fee).toMatch(MONEY_RE);
      }
      if (details.last_sale_price != null) {
        expect(details.last_sale_price).toMatch(MONEY_RE);
      }
      for (const assessment of details.tax_assessments ?? []) {
        if (assessment.value != null) expect(assessment.value).toMatch(MONEY_RE);
        if (assessment.land != null) expect(assessment.land).toMatch(MONEY_RE);
        if (assessment.improvements != null) {
          expect(assessment.improvements).toMatch(MONEY_RE);
        }
      }
      for (const tax of details.property_taxes ?? []) {
        if (tax.total != null) expect(tax.total).toMatch(MONEY_RE);
      }
      for (const sale of details.sale_history ?? []) {
        if (sale.price != null) expect(sale.price).toMatch(MONEY_RE);
      }
    }
  });

  it("uses numeric strings for coordinates when present", () => {
    for (const property of backup.properties) {
      const details = property.details;
      if (!details) continue;
      if (details.latitude != null) {
        expect(details.latitude).toMatch(NUMERIC_STRING_RE);
      }
      if (details.longitude != null) {
        expect(details.longitude).toMatch(NUMERIC_STRING_RE);
      }
    }
  });

  it("gives every transaction and asset a non-empty id", () => {
    for (const property of backup.properties) {
      for (const txn of property.transactions) {
        expect(isNonEmptyString(txn.id)).toBe(true);
      }
      for (const asset of property.assets) {
        expect(isNonEmptyString(asset.id)).toBe(true);
      }
    }
  });

  it("resolves every transaction.property_id and asset.property_id to a property in the document", () => {
    const propertyIds = new Set(backup.properties.map((p) => p.id));
    for (const property of backup.properties) {
      for (const txn of property.transactions) {
        expect(isNonEmptyString(txn.property_id)).toBe(true);
        expect(propertyIds.has(txn.property_id)).toBe(true);
      }
      for (const asset of property.assets) {
        expect(isNonEmptyString(asset.property_id)).toBe(true);
        expect(propertyIds.has(asset.property_id)).toBe(true);
      }
    }
  });

  it("assigns each property's transactions and assets to that same property", () => {
    // Stronger than mere membership: the child's property_id equals its parent.
    const assertOwnership = (
      property: BackupProperty,
      children: Array<BackupTransaction | { property_id: string }>,
    ) => {
      for (const child of children) {
        expect(child.property_id).toBe(property.id);
      }
    };
    for (const property of backup.properties) {
      assertOwnership(property, property.transactions);
      assertOwnership(property, property.assets);
    }
  });
});
