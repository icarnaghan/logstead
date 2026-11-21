/**
 * Pure helpers for Undo of safe deletes (Requirements 13.1, 13.3, 13.7, 13.8).
 *
 * Classifiers decide whether a delete is a Safe_Delete (restorable with a
 * single create call). Mappers convert a retained record into the payload of
 * the matching create API, ignoring `id`, `property_id` and server timestamps.
 */

import type { CreateAssetInput, DepreciableAsset } from "../api/assets";
import type { ItemizedEntryInput } from "../api/itemized";
import type { Loan, LoanInput } from "../api/loans";
import type { Transaction, TransactionInput } from "../api/transactions";

/**
 * A transaction delete is a Safe_Delete only when the row is not itemized, was not imported
 * (the create API cannot set that flag) and is known to have zero receipts.
 * An unknown count (`null`) is never safe.
 */
export function isTransactionSafeDelete(
  t: Transaction,
  receiptCount: number | null,
): boolean {
  return t.itemized !== true && t.imported !== true && receiptCount === 0;
}

/**
 * An itemized entry delete is a Safe_Delete only when the receipt count is a
 * known zero. An unknown count (`null`) is never safe.
 */
export function isItemizedEntrySafeDelete(
  _entry: Transaction,
  receiptCount: number | null,
): boolean {
  return receiptCount === 0;
}

/** Maps a retained itemized entry to its create-entry payload. */
export function itemizedEntryToInput(entry: Transaction): ItemizedEntryInput {
  const input: ItemizedEntryInput = {
    date: entry.date,
    amount: entry.amount,
    description: entry.description ?? "",
  };
  if (entry.notes != null && entry.notes !== "") input.notes = entry.notes;
  return input;
}

/**
 * A loan delete is a Safe_Delete only when it has no yearly interest
 * overrides, since those child rollups are removed by the delete and cannot be
 * restored with one create call.
 */
export function isLoanSafeDelete(l: Loan): boolean {
  return Object.keys(l.interest_overrides ?? {}).length === 0;
}

/** Maps a retained transaction to its create payload. */
export function transactionToInput(t: Transaction): TransactionInput {
  const input: TransactionInput = {
    date: t.date,
    amount: t.amount,
    type: t.type,
    category_id: t.category_id,
  };
  if (t.description != null) input.description = t.description;
  return input;
}

/** Maps a retained asset to its create payload (including overrides). */
export function assetToInput(a: DepreciableAsset): CreateAssetInput {
  const input: CreateAssetInput = {
    description: a.description,
    cost_basis: a.cost_basis,
    placed_in_service_date: a.placed_in_service_date,
    recovery_period_years: a.recovery_period_years,
  };
  if (a.depreciation_overrides !== undefined) {
    input.depreciation_overrides = { ...a.depreciation_overrides };
  }
  return input;
}

/** Maps a retained loan to its create payload (input keys only). */
export function loanToInput(l: Loan): LoanInput {
  return {
    description: l.description,
    annual_interest_rate: l.annual_interest_rate,
    monthly_payment: l.monthly_payment,
    anchor_balance: l.anchor_balance,
    anchor_date: l.anchor_date,
    extra_principal: l.extra_principal,
    payoff_date: l.payoff_date,
    original_principal: l.original_principal,
    closing_date: l.closing_date,
    include_in_report: l.include_in_report,
  };
}
