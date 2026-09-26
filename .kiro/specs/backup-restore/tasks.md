# Implementation Plan: Backup, Restore, Clear & Sample Data

## Overview

This plan implements the four data-portability capabilities (Export, Restore, Clear, Load Sample Data) on top of Logstead's existing single-Lambda / single-DynamoDB-table / single-S3-bucket architecture, adding **no new infrastructure**. It follows the design's guiding principle: reuse the existing key scheme (`repository/keys.py`) and item shapes (each service's `_to_item` / `_to_rows` helpers) so a restored dataset is byte-for-byte identical to hand-entered data.

The sequence is strictly incremental and bottom-up so every step compiles and tests green before the next:

1. **Backend**: model + pure validation → promote reusable item-mapping builders → `export` → `clear` → `restore` → round-trip property → routes + wiring.
2. **Frontend**: `api/backup.ts` → sample fixture → ProfilePage **Backup & restore** section with all four flows.

Backend uses **pytest + moto + Hypothesis** (property tests ≥ 100 examples). Frontend uses **vitest + RTL + vitest-axe + fast-check** (property tests numRuns 100). Two confirmed nits are baked in: backup filename `logstead-backup-<YYYY-MM-DD>.json`, and the UI is a section on the existing `ProfilePage` (no new nav entry).

### Environment quirks (read before running suites)
- **iCloud `* 2.*` duplicate cleanup**: iCloud sometimes creates `... 2.py` / `... 2.ts` duplicate files that break imports and test collection. Delete any `* 2.*` duplicates before running suites.
- **venv rebuild**: if backend imports fail unexpectedly, rebuild the virtualenv before debugging test logic.
- **Backend suite**: from `backend/`, run `.venv/bin/python -m pytest -q`.
- **Frontend suite**: `make test-frontend` (or `cd frontend && npm test`); build check with `cd frontend && npm run build`.

## Tasks

- [x] 1. Backup document model + pure validation
  - [x] 1.1 Define typed backup structures and schema version
    - Create the backup module(s) per the design (`backend/src/logstead/models/backup.py` for the dataclasses and/or `backend/src/logstead/services/backup.py`; split following the design's placement).
    - Define frozen dataclasses `BackupDocument`, `BackupProperty` (nesting details/note/usage/transactions/assets), and the `RestoreSummary` / `ClearSummary` summaries; money and coordinate fields modeled as exact `Decimal` after parsing.
    - Define `SCHEMA_VERSION = "1"`.
    - _Requirements: 1.11, 5.3, 13.1, 13.2_

  - [x] 1.2 Implement pure `validate_document(raw) -> Result[BackupDocument]`
    - Side-effect-free validation, in validation order: JSON-object shape → schema version present + supported → per-entity required fields (property `id`/`name`/`address_text`; transaction `id`/`property_id`/`date`/`amount`/`type`/`category_id`; asset `id`/`property_id`/`description`/`cost_basis`/`placed_in_service_date`) → two-decimal money via `to_money` (never float) → coordinate decimals → `category_id` membership in `CATEGORY_CATALOG` → cross-reference `property_id` sanity.
    - On failure return `Result.failure("validation", <message naming entity/field/value/version>, field=...)` and perform NO read/write. On success return a fully-parsed typed `BackupDocument`.
    - _Requirements: 3.1, 3.2, 3.4, 4.1, 4.2, 4.3, 5.1, 5.2, 5.3, 13.2_

  - [x]* 1.3 Unit tests for each validation rule
    - Cover version present/supported, each required-field omission (message identifies entity + field), bad money string, bad coordinate, unknown `category_id`, missing `category_id` (identifies transaction), cross-reference mismatch; assert exact error `field`/message.
    - _Requirements: 3.1, 3.2, 3.4, 4.1, 4.2, 5.1, 5.2_

  - [x]* 1.4 Property test: invalid-in-exactly-one-way documents are rejected without mutation
    - Take a valid document, apply exactly one generated invalidity (parameterized flavor); assert a `validation` `Result` naming the location and a byte-for-byte unchanged store; spy that `clear`/`put_item`/`transact_write` were never called.
    - `# Feature: backup-restore, Property 3: An invalid document is rejected without mutating the store`
    - Hypothesis `@settings(max_examples>=100)`.
    - **Property 3** — **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 4.1, 5.1, 5.2**

- [x] 2. Promote reusable id/timestamp-accepting item-mapping builders
  - [x] 2.1 Promote/confirm module-level builders for restore reuse
    - Ensure importable, id/timestamp-accepting builders exist for: property list row + META mirror + GSI1 keys (via `keys.py`); details row (`details_from_dict` → `details_to_json`); note row; usage row; transaction `_to_item` (base SK + GSI2 tax-year keys); asset `_to_item` (money_attrs `{costBasis}`); schedule-row builder for `compute_schedule_rows` output (with GSI2 keys).
    - Where the design promotes instance methods (property `_to_rows`, asset `_to_item`/`_schedule_row_item`) to module-level importable helpers that depend only on `user_id`, perform that refactor.
    - _Requirements: 2.2, 2.3, 2.4, 2.5_

  - [x]* 2.2 Keep existing service tests green after promotion
    - Run the transaction/asset/property/details service test modules to confirm the refactor changed no behavior.
    - _Requirements: 2.2, 2.3, 2.4_

- [x] 3. BackupService.export
  - [x] 3.1 Implement `BackupService.__init__` and `export()`
    - Construct from `repo: DynamoRepository`, `files: S3FileAdapter`, `user`. `export()` drives off `PropertyService.list()` then per-property reads: `get` (fields + attached details), `get_note`, a private `_list_usage(property_id)` (raw `USAGE#` prefix query), `TransactionService.list_for_property`, `DepreciationService.list_assets`. Assemble `BackupDocument` with money as strings, details via `details_to_dict`, `schema_version="1"`, `exported_at` set.
    - Exclude photo/receipt metadata, import sessions, PDF drafts, schedule rows, and the category catalog.
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 11.1, 11.3, 13.1, 13.3_

  - [x]* 3.2 moto unit/example tests for export
    - Seed a property with details/note/usage/transactions/assets; assert the document includes all fields, money as two-decimal strings, coordinates full-precision; assert catalog NOT embedded, schedule rows NOT embedded, photo/receipt metadata absent, version marker present.
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.10, 1.11, 13.1, 13.3_

- [x] 4. BackupService.clear
  - [x] 4.1 Implement `clear()`
    - Enumerate owned properties via `PropertyService.list()`. Per property partition, `query` child rows and bucket into receipt rows (`#DOC#`), photo rows (`PHOTO#`), and all other rows. S3-purge first via `files.delete_object` per `s3Key`, wrapped in try/except recording failures in `ClearSummary.failed_s3_keys` and continuing. Then delete rows bottom-up (children before property META + `USER#/PROP#` list row) in `transact_write` batches of ≤ 100.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 8.4, 8.5, 11.1, 11.3, 12.3_

  - [x]* 4.2 Property test: clear empties the user's store
    - Seed an arbitrary dataset, clear, assert zero rows across every prefix in user + property partitions.
    - `# Feature: backup-restore, Property 5: Clear empties the user's store`
    - **Property 5** — **Validates: Requirements 7.1, 7.2, 7.3, 7.4**

  - [x]* 4.3 Property test: clear removes every S3 binary with its metadata row
    - Seed photos + receipts against a recording S3 fake; assert `delete_object` called for each `s3Key` and no `PHOTO#`/`#DOC#` rows remain.
    - `# Feature: backup-restore, Property 6: Clear removes every S3 binary together with its metadata row`
    - **Property 6** — **Validates: Requirements 8.1, 8.2**

  - [x]* 4.4 Property test: clear continues past S3 delete failures and reports them
    - S3 fake raises for a random subset of keys; assert all metadata rows still deleted and `failed_s3_keys` lists exactly the failing subset.
    - `# Feature: backup-restore, Property 7: Clear continues past individual S3 delete failures and reports them`
    - **Property 7** — **Validates: Requirements 8.4**

  - [x]* 4.5 Example tests for clear ordering
    - Recording-fake assertions: S3 `delete_object` happens before metadata-row delete (8.3); children deleted before parent property row (8.5).
    - _Requirements: 8.3, 8.5_

- [x] 5. BackupService.restore
  - [x] 5.1 Implement `restore(raw_document)`
    - `validate_document` → on failure return the validation `Result` with NO read/write → on success `clear()` → id/timestamp-preserving writes grouped by `money_attrs` set (property/details/note/usage; transactions `amount`; assets `{costBasis}`; recomputed schedule rows `{amount, remainingBasis}`), one `transact_write` per money-attr group per batch of ≤ 100. Recompute schedules via `compute_schedule_rows` (never read from document). Re-resolve `schedule_e_line` from `category_id`. On a write-phase repository failure, catch and return a retryable error `Result`. Empty-properties document → clear then empty summary. Return `RestoreSummary`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.3, 11.1, 12.1, 12.2, 12.3, 13.2_

  - [x]* 5.2 Property test: restore is replace-all with no leftovers
    - Seed dataset A, restore independently generated valid document B; assert store == B and no A-only id survives.
    - `# Feature: backup-restore, Property 2: Restore is replace-all with no leftovers`
    - **Property 2** — **Validates: Requirements 2.1, 12.1**

  - [x]* 5.3 Property test: restore recomputes each asset's depreciation schedule
    - After restore, assert stored SCHED rows equal `compute_schedule_rows(restored_asset)` per asset; assert no schedule data taken from the document.
    - `# Feature: backup-restore, Property 4: Restore recomputes each asset's depreciation schedule`
    - **Property 4** — **Validates: Requirements 2.5**

  - [x]* 5.4 Property test: mid-restore failure after clear surfaces a retryable error
    - Inject a repo failure on the Nth write batch; assert `restore` returns an error result signaling incompleteness/retry.
    - `# Feature: backup-restore, Property 9: A mid-restore failure after clear surfaces a retryable error`
    - **Property 9** — **Validates: Requirements 12.2**

  - [x]* 5.5 Property test: restore batches documents exceeding the atomic-write cap
    - Build a document with > 100 total entities (e.g. 150 transactions); restore; assert every entity present and store == document (exercises batch chunking).
    - `# Feature: backup-restore, Property 10: Restore batches documents that exceed the atomic-write cap and still reaches store == document`
    - **Property 10** — **Validates: Requirements 12.3**

  - [x]* 5.6 Example test: empty-document restore
    - Restore a document with no properties; assert existing data cleared and empty summary returned.
    - _Requirements: 2.6_

- [x] 6. Round-trip property test (export → restore → re-export)
  - [x]* 6.1 Property test: backup round-trip preserves ids, timestamps, money, coordinates, structure
    - Generate an arbitrary valid dataset (sparse details reusing the existing `PropertyDetails` strategy, catalog-category transactions with two-decimal amounts, assets with positive cost basis, usage years); export → restore → export; assert canonical deep-equality with string-identical money and coordinates and identical ids/timestamps/cross-references.
    - `# Feature: backup-restore, Property 1: Backup round-trip preserves ids, timestamps, money, coordinates, and structure`
    - **Property 1** — **Validates: Requirements 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.2, 2.3, 2.4, 13.1, 13.2, 13.3, 13.4**

- [x] 7. Backend checkpoint — service layer green
  - Ensure all backend tests pass (from `backend/`: `.venv/bin/python -m pytest -q`; clean any iCloud `* 2.*` dups and rebuild the venv if imports fail). Ask the user if questions arise.

- [x] 8. Routes + wiring
  - [x] 8.1 Add routes, `_backup_service` constructor, and thin handlers
    - Add to `_ROUTES` (all `public=False`): `("GET", "/backup", _export_backup)`, `("POST", "/backup/restore", _restore_backup)`, `("POST", "/backup/clear", _clear_backup)`. Add `_backup_service(wiring, user)` using `_require_files(wiring)` (503 when bucket absent). Handlers: `_export_backup` → `_response(200, service.export())`; `_restore_backup` → `_result_response(service.restore(body))` (validation → 400); `_clear_backup` → `_result_response(service.clear())`. Every handler resolves `user = current_user(event)`; no route accepts a user parameter.
    - _Requirements: 1.12, 3.1, 6 (server side), 8 (server side), 11.1, 11.4_

  - [x]* 8.2 Handler/integration tests
    - GET/POST routing, validation → 400 with field message, 503-when-no-bucket path for restore/clear, and user-scoping (operations as A never touch B's rows).
    - Include the user-scoping property: `# Feature: backup-restore, Property 8: All operations are scoped to the authenticated user`.
    - **Property 8** — **Validates: Requirements 11.1, 11.2, 11.3**; _Requirements: 1.12, 3.1, 11.4_

  - [x]* 8.3 Sample-fixture backend acceptance test
    - Load `frontend/src/data/sample-backup.json` as a test resource through `validate_document` + a full restore; assert acceptance, exactly 2 properties, 5 tax years with income + expense across multiple categories, ≥ 1 asset per property. (Depends on task 9's fixture.)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 9. Backend checkpoint — routes green
  - Ensure all backend tests pass (`.venv/bin/python -m pytest -q` from `backend/`). Ask the user if questions arise.

- [x] 10. Frontend API module
  - [x] 10.1 Implement `frontend/src/api/backup.ts`
    - Following the `api/properties.ts` injectable-client singleton pattern: TS types `BackupDocument`, `BackupProperty`, `RestoreSummary`, `ClearSummary` (all money and coordinate fields typed `string`); `fetchBackup(signal?)` (GET `/backup`), `restoreBackup(doc, signal?)` (POST `/backup/restore`), `clearData(signal?)` (POST `/backup/clear`). Surface `ApiError` with status + parsed message.
    - _Requirements: 1.12, 2.1, 7.1, 13.1_

  - [x]* 10.2 Unit tests for `api/backup.ts`
    - With a fake client, assert each function hits the right method/path and returns typed data.
    - _Requirements: 1.12, 2.1, 7.1_

  - [x]* 10.3 Property test: money fields never coerced to number
    - fast-check (numRuns 100), mirroring `money.property.test.ts`: for any generated document, money/coordinate fields consumed/produced by `api/backup.ts` stay `string`.
    - `// Feature: backup-restore, Property 1 (money exactness): round-trip through api/backup.ts keeps money as string`
    - **Validates: Requirements 13.1, 13.2**

- [x] 11. Sample fixture
  - [x] 11.1 Create `frontend/src/data/sample-backup.json`
    - `schema_version "1"`, exactly 2 properties, 5 tax years of income + expense transactions across multiple valid `CATEGORY_CATALOG` slugs (`rents-received`, `repairs`, `insurance`, `taxes`, `utilities`, `management-fees`, …), ≥ 1 asset per property, uuid ids, all amounts two-decimal strings, `exported_at` set.
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x]* 11.2 Unit test: fixture is a structurally valid BackupDocument
    - Assert the imported fixture matches the `BackupDocument` shape and the invariants the backend validator expects (2 properties, 5 tax years, ≥ 1 asset each, money as two-decimal strings).
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 12. ProfilePage Backup & restore section
  - [x] 12.1 Add the Backup & restore section with all four flows
    - In `frontend/src/pages/ProfilePage.tsx`, add a `Card` section (using shared `Button`/`ConfirmDialog`/`useToast`/`StateBlock`) with:
      - **Download backup**: `fetchBackup` → client-side Blob download reusing the ReportsPage `downloadFile` pattern → filename `logstead-backup-<YYYY-MM-DD>.json`, MIME `application/json`; error toast.
      - **Restore from file**: hidden `<input type="file" accept="application/json">` → read + `JSON.parse` (parse error → toast, no request) → destructive `ConfirmDialog` (explains replace-all) → `restoreBackup` → success/error toast (surface 400 message); cancel = no request.
      - **Clear all data**: destructive `ConfirmDialog` → `clearData` → toast; cancel = no request.
      - **Load sample data**: import the bundled fixture → same restore `ConfirmDialog` → `restoreBackup(fixture)` → toast.
    - No new nav entry.
    - _Requirements: 1.12, 6.1, 6.2, 7.1, 9.1, 9.2, 10.5, 10.6_

  - [x]* 12.2 RTL + vitest-axe tests for the four flows
    - Wrap in `ToastProvider` (ConfirmDialog is portalled). Download: spy `URL.createObjectURL` + anchor click, assert filename. Restore: file select opens dialog, confirm POSTs parsed doc + success toast, cancel makes no request, malformed file toasts parse error with no request. Clear: confirm POSTs + toast, cancel makes no request. Load sample: same dialog then POST bundled fixture. Run `vitest-axe` on the section and dialogs. Update `ProfilePage.test.tsx`.
    - _Requirements: 1.12, 6.1, 6.2, 9.1, 9.2, 10.5, 10.6_

- [x] 13. Final checkpoint — full suite + build
  - Ensure the full backend suite passes (`.venv/bin/python -m pytest -q` from `backend/`) and the frontend suite + build pass (`make test-frontend` or `cd frontend && npm test`, then `cd frontend && npm run build`). Clean any iCloud `* 2.*` dups and rebuild the venv if needed. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Property-based tests: Hypothesis on the backend (`@settings(max_examples>=100)`), fast-check on the frontend (numRuns 100). Each is tagged `Feature: backup-restore, Property N: <text>`.
- Each correctness property is realized by exactly one property-based test; edge/example cases use focused unit tests.
- Backend writes go through the generic repository (`put_item`/`transact_write`) with shared key builders to preserve ids/timestamps — never through `create()`.
- Checkpoints (7, 9, 13) validate the layer built so far before moving on; the environment quirks note applies at every checkpoint.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "10.1", "11.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "3.1", "10.2", "10.3", "11.2"] },
    { "id": 3, "tasks": ["3.2", "4.1", "12.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "5.1", "12.2"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6"] },
    { "id": 6, "tasks": ["6.1", "8.1"] },
    { "id": 7, "tasks": ["8.2", "8.3"] }
  ]
}
```
