# Implementation Plan: Schedule E Import

## Overview

Convert the Schedule E Import design into incremental, independently-schedulable
coding tasks. The backend lands first (backward-compatible `imported` marker on
the transaction model → report surfacing fields → service-layer models → the new
`ImportService` built up as discrete leaves: line→category index + synthesis,
all-or-nothing validation, inline property create, replace-on-reimport,
remove-imported-set → routes + per-request wiring), then the six Hypothesis
correctness properties, then the frontend (typed `api/` module → guided
multi-property form page/components → marker surfacing in listings and reports).

Every implementation step is its own decimal **leaf** so the DAG queue can
dispatch it independently; parent headings (`1.`, `4.`, ...) carry **no code**
and only group. Optional (`*`) test leaves sit beside the leaf they cover.

The guiding principle from the design holds throughout: a `Summary_Transaction`
is an **ordinary, marked transaction** stored under the existing per-property /
per-tax-year keys and consumed by the existing `ReportingService` with **zero
change to report aggregation math** — the only reporting change is surfacing the
imported marker. The existing `/imports` PDF-expense feature
(`ExpenseImportService`, its `IMPORT#`/`DRAFT#` scaffolding, and its routes) is
**left exactly as-is**: Schedule E Import mounts under the distinct path
`/imports/schedule-e`, uses the distinct class name `ImportService`, and adds a
new `_schedule_e_import_service` constructor. Non-Goals are respected: no PDF/OCR
extraction, no depreciation / Line 18 ever written, no itemization beyond one
summary transaction per non-zero line, no CSV upload, no identity/tenancy change.

Conventions: backend `pytest` + `moto` + `Hypothesis` (property tests at
`@settings(max_examples=100)`, tagged
`# Feature: schedule-e-import, Property N: <text>`); money as a two-decimal
`Decimal`/string through `util/money` (`to_money`, `money_to_str`). Frontend
`vitest` + React Testing Library + `vitest-axe`, UI driven through an injectable
`api/` layer; money and ids carried as strings over the wire, snake_case bodies.
Backend verify: `cd backend && .venv/bin/python -m pytest -q`. Frontend verify:
`cd frontend && npm test -- --run` and `npm run build`.

## Tasks

- [x] 1. Backend foundation: imported marker and report surfacing

  - [x] 1.1 Add the backward-compatible `imported` field to the transaction models
    - In `models/transaction.py`, add a trailing, defaulted `imported: bool =
      False` to **both** `TransactionInput` and `Transaction`. The field is
      trailing with a default so existing positional constructions still pass and
      every pre-existing stored row reads back `imported=False`.
    - _Design: Data Models → `Transaction`/`TransactionInput` imported marker;
      Req 7.1, 7.2_

  - [x] 1.2 Thread `imported` through `TransactionService` and item serialization
    - In `services/transaction.py`: carry `data.imported` onto the built
      `Transaction` in `TransactionService.create` and onto the `replace`d
      `Transaction` in `update` (so editing a marked txn preserves the marker);
      add `"imported": txn.imported` to the emitted item in `transaction_to_item`;
      read `bool(item.get("imported", False))` in `_from_item` so legacy items
      without the attribute default to `False`.
    - _Design: Data Models → round-trip through the serialization boundary;
      Req 7.1, 7.2, 7.5_

  - [x]* 1.3 Unit test the imported round-trip and legacy default
    - Assert `_from_item(transaction_to_item(txn)).imported == txn.imported` for
      both `True` and `False`; assert an item with `imported` absent reads back
      `False`; assert an ordinary `create` yields `imported=False`. Protects
      backward compatibility with every pre-existing stored transaction.
    - _Design: Testing Strategy → serialization unit test; Req 7.2, 7.5_

  - [x] 1.4 Add additive report-surfacing fields without changing aggregation math
    - In `services/report.py`, add `includes_imported: bool` (default `False`) to
      `ReportLine` and `imported: bool` (default `False`) to `OtherItem`, both
      frozen-dataclass fields with defaults. During the existing single pass over
      `list_for_property`, OR `t.imported` into the line's flag as transactions
      accumulate per line, and set each `OtherItem.imported` from its source
      transaction. Change **no** total / `net` math — purely surfacing.
    - _Design: Data Models → Report surfacing of the marker; Req 7.4_

  - [x]* 1.5 Unit test report marker surfacing
    - A line fed only by user-tracked transactions reports
      `includes_imported=False`; a line with any imported contribution reports
      `True`; each `OtherItem.imported` reflects its transaction; all line totals
      and `net` are unchanged versus the pre-feature computation (mixed
      user+imported fixture).
    - _Design: Testing Strategy → mixed user+imported report; Req 7.4_

- [x] 2. Backend: service-layer import models

  - [x] 2.1 Create `models/schedule_e_import.py`
    - Add the dataclasses from the design: `LineAmountInput` (`schedule_e_line:
      int`, `amount: str | Decimal | None`, `description: str | None = None`),
      `PropertyEntryInput` (`property_id`/`new_property: PropertyInput | None`,
      `lines: list[LineAmountInput]`), `ImportSubmission` (`tax_year: int | None`,
      `entries: list[PropertyEntryInput]`), and the outcome shapes `EntryOutcome`,
      `ImportOutcome`, `RemoveOutcome`. Reuse `models/property.PropertyInput` for
      inline creation. No money is parsed here (strings pass through to the
      service's `util/money` boundary).
    - _Design: Components/Interfaces → Input/output shapes; Req 1.3, 1.5, 4.1_

  - [x]* 2.2 Unit test the import model defaults and shape
    - Assert field defaults (`LineAmountInput.description` None,
      `PropertyEntryInput` mapping fields optional, `ImportSubmission.tax_year`
      optional) and that outcomes carry the documented fields.
    - _Design: Components/Interfaces → Input/output shapes_

- [x] 3. Backend: `ImportService` building blocks in `services/schedule_e_import.py`

  - [x] 3.1 Create `ImportService` shell + line→category index and synthesis mapping
    - New module `services/schedule_e_import.py` with
      `class ImportService` and `__init__(self, repo, user)` holding the user id
      and constructing user-scoped `PropertyService` and a `TransactionService`
      collaborator. Build a `{schedule_e_line: ScheduleECategory}` index once from
      `CATEGORY_CATALOG` (Line 18 is intentionally absent). Implement the pure
      per-line synthesis mapping used by `import_schedule_e`: for a non-zero line,
      compose `TransactionService.create(TransactionInput(...))` with
      `date = YYYY-12-31` of the tax year, `amount = to_money(entered)`,
      `type`/`category_id` from the catalog category for that line,
      `schedule_e_line` recorded by `create`, `imported=True`, and for Line 19 the
      entry's description or the default `"Imported Schedule E Other"`.
    - _Design: Components/Interfaces → `ImportService`; Data Models → Synthesis
      mapping / Dec 31 date / compose-create decision; Req 3.1, 3.3, 4.3, 6.3,
      6.4, 6.5, 6.6, 6.7, 7.1, 11.1, 11.2_

  - [x] 3.2 Implement all-or-nothing submission validation with structured field paths
    - Validate the **entire** submission before any write and perform no
      create/delete/modify unless every check passes. Rules & structured dotted
      `field`: tax year present and `1000 ≤ tax_year ≤ 9999` else
      `validation` `field="tax_year"`; at least one entry else `validation`
      `field="entries"`; per entry — exactly one of `property_id`/`new_property`;
      duplicate resolved-property mapping across entries →
      `validation` `field="entries[i]"`; inline `new_property` missing required
      fields → `validation` `field="entries[i].new_property.<field>"`; each
      provided amount parses as money to two decimals via `to_money` and is
      non-negative else `validation` `field="entries[i].lines[<line>]"`; any
      `schedule_e_line == 18` or a line not in {3,4,5..17,19} → `validation`;
      at-least-one non-zero line per entry else `validation` `field="entries[i]"`.
      Blank/absent amount is treated as `0.00`, not an error. Messages name the
      column and line in words. (Ownership/not-found resolution is 3.3.)
    - _Design: Data Models → All-or-nothing validation; Components/Interfaces →
      Validation error shape; Req 1.6, 1.7, 2.4, 2.5, 3.2, 4.2, 5.1, 9.1, 9.2,
      9.3, 9.4, 9.5, 9.6_

  - [x] 3.3 Implement per-entry property resolution and inline create in the write phase
    - Resolve each entry's property scoped to the user: for `property_id`, confirm
      ownership via `PropertyService.get` → else `not_found` `field="entries[i]"`
      (whole submission rejected, nothing written); for `new_property`, defer
      creation to the write phase and call `PropertyService.create(new_property)`,
      using the returned fresh id as that entry's mapping. Inline-created ids are
      fresh UUIDs so two inline creates are inherently distinct and cannot collide
      with another entry's existing `property_id`.
    - _Design: Data Models → Inline property create per entry; Validation
      (deferred create); Req 2.1, 2.2, 2.3, 10.1, 10.3_

  - [x] 3.4 Implement `import_schedule_e` replace-on-reimport write phase
    - Add `import_schedule_e(self, submission) -> Result[ImportOutcome]` tying
      3.1–3.3 together: after validation passes, for **each** entry (and only
      those entries): resolve/inline-create the property, load
      `prior = TransactionService.list_for_property(property_id, tax_year)`, select
      `imported_prior = [t for t in prior if t.imported]` (never user-tracked
      rows), delete those by `(pk, sk)` where `pk = property_scoped_pk(property_id)`
      and `sk = transaction_sk(parse(t.date), t.id)`, then write one
      `Summary_Transaction` per non-zero line. Order is **delete-then-write per
      `(Property, Tax_Year)` pair** so a line dropped to zero leaves no surviving
      imported row and pairs absent from the submission are never queried or
      touched. Use `repo.transact_write` as a single atomic unit per pair when
      `deleted + new ≤ 100` actions; otherwise fall back to batched deletes (≤100)
      then batched writes, preserving delete-then-write. Return per-entry
      `EntryOutcome`s in an `ImportOutcome`.
    - _Design: Data Models → Replace-on-reimport mechanism / Atomicity & txn
      limits; Architecture → request flow; Req 1.5, 6.1, 6.2, 8.1, 8.2, 8.3, 8.4,
      8.5, 8.6, 10.2_

  - [x] 3.5 Implement `remove_imported_set` undo
    - Add `remove_imported_set(self, property_id, tax_year) -> Result[RemoveOutcome]`:
      ownership check via `PropertyService` (`not_found` when missing/not owned),
      select only imported rows from `list_for_property(property_id, tax_year)`,
      delete exactly those by `(pk, sk)` batched by ≤100, and return
      `RemoveOutcome(deleted_count=...)`. User-tracked rows are never selected or
      deleted.
    - _Design: Data Models → Remove-imported-data capability; Req 8.3, 8.4, 10.1,
      10.3_

  - [x]* 3.6 Write moto example/edge tests for `ImportService`
    - synthesis of one summary txn per non-zero line (and none for zero/blank);
      Dec 31 dating lands rows in the tax-year GSI2 partition; Line 19 default
      description applied; empty entries → `validation` `field="entries"`; missing
      tax_year and invalid four-digit-year boundaries → `validation`
      `field="tax_year"`; duplicate property mapping → `validation`
      `field="entries[i]"`; all-zero entry → `validation` `field="entries[i]"`;
      `schedule_e_line==18` rejected; the structured `field` dotted-path shapes;
      not-owned property → `not_found`; replace-on-reimport removes the prior
      imported set for an included pair while leaving omitted pairs and
      user-tracked rows untouched; `remove_imported_set` happy path + `not_found`.
    - _Design: Testing Strategy → example/edge; Req 1.6, 1.7, 2.5, 3.2, 5.1, 8,
      9.4, 9.6_

- [x] 4. Backend: routes and per-request wiring in `router/handler.py`

  - [x] 4.1 Add `_schedule_e_import_service` constructor and request parsing
    - Add a per-request constructor `_schedule_e_import_service(wiring, user)` that
      builds `ImportService(wiring.repo, user)` with a user-scoped
      `PropertyService` and a `TransactionService` (constructed like the existing
      `_transaction_service`; the S3 adapter is only for receipts, never used by
      synthesis). Add a body→`ImportSubmission` parser with dual snake/camel
      tolerance (like `_transaction_input`): `tax_year`/`taxYear`, per-entry
      `property_id`/`propertyId` or `new_property`/`newProperty`, and
      `lines[].schedule_e_line`/`scheduleELine`, `amount`, `description`; money
      stays a string passed to the service. Leave the existing `_import_service`
      (PDF feature) wiring untouched.
    - _Design: Components/Interfaces → Route surface + wiring; Req 1.5_

  - [x] 4.2 Add the two thin route handlers and register them in `_ROUTES`
    - Add `_import_schedule_e` (calls `import_schedule_e`, returns
      `_result_response(result, success_status=201)`) and
      `_remove_schedule_e_import` (parses `{taxYear}` via `_int_param`, calls
      `remove_imported_set`, returns `_result_response(result)` → 200). Register
      `("POST", "/imports/schedule-e", _import_schedule_e, False)` and
      `("DELETE", "/imports/schedule-e/{propertyId}/{taxYear}",
      _remove_schedule_e_import, False)` **before** the existing
      `("GET", "/imports/{sessionId}", ...)` sibling entries so the literal
      `schedule-e` segment and distinct segment counts disambiguate under
      `_match_path`. Handlers stay thin (parse + wire + `Result→HTTP`,
      `validation→400` with the structured field, `not_found→404`); no business
      rules.
    - _Design: Components/Interfaces → Route surface + wiring; Error Handling;
      Req 1.5, 2.3, 8, 9.6, 10.3_

  - [x]* 4.3 Write handler/integration tests for the routes
    - `POST /imports/schedule-e` → 201 with per-entry outcome; a validation body
      → 400 carrying the structured `field`; a not-owned property → 404;
      `DELETE /imports/schedule-e/{propertyId}/{taxYear}` → 200 with
      `deleted_count`; a non-integer `taxYear` segment → 400 via the router shape
      guard; dual snake/camel body tolerance; the new routes do not shadow the
      existing `/imports/{sessionId}` PDF routes.
    - _Design: Error Handling; Testing Strategy → backend; Req 1.5, 8, 9.6_

- [x] 5. Backend: Hypothesis correctness property tests

  - [x]* 5.1 Property 1 — per-user scoping isolation
    - **Property 1: per-user scoping isolation** — two distinct users; a
      submission by A mapping to B's (or a non-existent) property is rejected
      `not_found` and nothing changes in either scope (full-table snapshot before
      == after). `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 1: per-user scoping isolation`.
    - **Validates: Requirements 2.3, 10.1, 10.3**

  - [x]* 5.2 Property 2 — round-trip reconciliation (no precision drift)
    - **Property 2: round-trip reconciliation — entered lines reproduce report
      line totals with no drift** — after `import_schedule_e`, each
      `(Property, Tax_Year)` report line total equals the two-decimal-quantized
      entered amount and portfolio totals equal the exact sum of per-property
      totals. `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 2: round-trip reconciliation — entered lines reproduce report line totals with no drift`.
    - **Validates: Requirements 1.5, 3.1, 3.3, 10.2, 11.1, 11.2, 11.3**

  - [x]* 5.3 Property 3 — replace-on-reimport is scoped and residue-free
    - **Property 3: replace-on-reimport is scoped and residue-free** — a two-phase
      strategy snapshots the table before a re-import and asserts included pairs
      equal exactly the re-import's non-zero lines (zeroed lines leave no imported
      row), while omitted pairs and every user-tracked transaction are byte-for-byte
      unchanged. `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 3: replace-on-reimport is scoped and residue-free`.
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

  - [x]* 5.4 Property 4 — all-or-nothing validation performs no mutation
    - **Property 4: all-or-nothing validation performs no mutation on any invalid
      submission** — a submission with any invalid element (negative amount,
      non-monetary amount, all-zero entry, missing/not-owned property, duplicate
      mapping, or invalid tax year) returns a failure identifying the offending
      entry/field and the full-table snapshot is identical before and after (no
      txn created/deleted/modified and no inline property created).
      `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 4: all-or-nothing validation performs no mutation on any invalid submission`.
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.5, 10.3**

  - [x]* 5.5 Property 5 — depreciation / Line 18 is never written
    - **Property 5: depreciation / Line 18 is never written** — for any submission
      (including one attempting a Line 18 amount), no transaction on Line 18 and no
      depreciation data is persisted, so the derived report's Line 18 for each
      imported pair comes solely from depreciation schedules (zero when none).
      `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 5: depreciation / Line 18 is never written`.
    - **Validates: Requirements 5.1, 5.3**

  - [ ]* 5.6 Property 6 — synthesis structure (one correctly-mapped, marked txn per non-zero line)
    - **Property 6: synthesis structure — one correctly-mapped, marked transaction
      per non-zero line** — exactly one summary txn per non-zero line and none for
      zero/blank; each carries `imported=True`, the catalog category and
      `schedule_e_line`, the catalog income/expense kind, a non-blank Line 19
      description (provided or default), the marker survives
      `_from_item(transaction_to_item(txn))`, and an ordinary-create txn carries
      `imported=False`. `@settings(max_examples=100)`, tagged
      `# Feature: schedule-e-import, Property 6: synthesis structure — one correctly-mapped, marked transaction per non-zero line`.
    - **Validates: Requirements 4.2, 4.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 7.1, 7.2, 7.5**

- [x] 6. Backend checkpoint
  - Run `cd backend && .venv/bin/python -m pytest -q` and ensure the full suite
    (examples + Properties 1-6) passes. **Regression guard:** confirm the existing
    `/imports` PDF-expense feature still passes unchanged — `ExpenseImportService`
    and its `POST /imports`, `GET /imports/{sessionId}`, `.../drafts`,
    `.../confirm` route tests must be green and this feature must not alter the PDF
    feature's behavior, keys, or models. Ask the user if questions arise.

- [x] 7. Frontend: typed import api module

  - [x] 7.1 Create `api/scheduleEImport.ts`
    - Typed, injectable module mirroring `api/transactions.ts` / `api/imports.ts`:
      `importScheduleE(submission)` → `POST /imports/schedule-e`,
      `removeScheduleEImport(propertyId, taxYear)` →
      `DELETE /imports/schedule-e/{propertyId}/{taxYear}`. Wire shapes use
      snake_case (`tax_year`, `property_id`/`new_property`, `schedule_e_line`);
      money and ids are strings; accept an injectable `ApiClient` for tests.
    - _Design: Frontend Components / Testing Strategy → `api/scheduleEImport.ts`_

  - [x]* 7.2 Unit test `api/scheduleEImport.ts`
    - Assert the submit function posts the snake_case body shape to
      `/imports/schedule-e` and the remove function targets the correct DELETE URL,
      against an injected fake client (following `api/imports.test.ts`).
    - _Design: Testing Strategy → frontend api_

- [x] 8. Frontend: guided multi-property import form

  - [x] 8.1 Create `pages/ScheduleEImportPage.tsx` shell + route and nav entry
    - Add the page shell named distinctly from `pages/ImportReviewPage.tsx` (PDF
      feature); wire its route in `App.tsx` and add a nav entry in
      `components/navConfig.ts`. The page hosts the form and selects the
      `Tax_Year` once at the top before entering line amounts.
    - _Design: Frontend Components → `pages/ScheduleEImportPage.tsx`; Req 1.1, 1.2_

  - [x] 8.2 Build `components/schedule-e-import/ScheduleEImportForm.tsx`
    - Select the `Tax_Year` once at the top; render a list of `PropertyEntryCard`s
      with add/remove controls (one or more entries); show the
      depreciation-not-imported notice prominently; submit one `ImportSubmission`
      via `api/scheduleEImport.ts`.
    - _Design: Frontend Components → `ScheduleEImportForm.tsx`; Req 1.2, 1.3, 5.2_

  - [x] 8.3 Build `components/schedule-e-import/PropertyEntryCard.tsx`
    - One `Property_Entry`: a property-mapping control (existing-property select
      **or** inline-create reusing the `AddPropertyDialog` pattern) plus money
      inputs for income lines 3-4, expense lines 5-17, and Line 19 Other (with a
      description field for Line 19), and **no** Line 18 field. Per-line error
      slots mirror the existing per-field error rendering.
    - _Design: Frontend Components → `PropertyEntryCard.tsx`; Req 1.4, 2.1, 2.2,
      4.1, 5.2_

  - [x] 8.4 Wire submit + structured server-error routing in the form
    - On submit, call `importScheduleE` and report the per-entry outcome; on a
      `validation`/`not_found` failure, parse the structured dotted `field`
      (`tax_year`, `entries`, `entries[i]`, `entries[i].lines[<line>]`,
      `entries[i].new_property.<field>`) and route each message to the right entry
      card / line input (split on the first bracket).
    - _Design: Components/Interfaces → Validation error shape; Frontend Components;
      Req 1.6, 1.7, 2.5, 9.6_

  - [x]* 8.5 Write RTL + vitest-axe tests for the guided form
    - Tax_Year selected once; add/remove entry cards; existing-select vs inline
      create per entry; line inputs for 3-4, 5-17, 19 with **no** Line 18 field;
      the depreciation-not-imported notice is shown; a server 400 with a dotted
      `field` renders beside the right card/line; focus containment; no axe
      violations.
    - _Design: Testing Strategy → frontend; Req 1.4, 1.6, 1.7, 2.5, 5.2, 9.6_

- [x] 9. Frontend: surface the imported marker

  - [x] 9.1 Show the imported badge in the transactions list and report views
    - In `pages/TransactionsPage.tsx`, render an "Imported" badge when
      `transaction.imported` is true; in the report views (`ReportsPage.tsx` /
      `CombinedReportsPage.tsx` and their report-line/`OtherItem` components),
      render an imported indicator on a line whose `includes_imported` is true and
      on each imported `OtherItem`. Additive reads of the new backend fields.
    - _Design: Frontend Components → Marker surfacing; Req 7.3, 7.4_

  - [x]* 9.2 Write RTL + vitest-axe tests for marker surfacing
    - A `transaction.imported` row shows the "Imported" badge (and a non-imported
      row does not); a report line with `includes_imported` and an imported
      `OtherItem` show the indicator; no axe violations on the badge/indicator.
    - _Design: Testing Strategy → frontend; Req 7.3, 7.4_

- [x] 10. Final checkpoint
  - Run the full backend suite (`cd backend && .venv/bin/python -m pytest -q`) and
    the frontend `cd frontend && npm test -- --run` plus `npm run build`; ensure
    all pass, including the existing `/imports` PDF-feature regression guard. Ask
    the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster
  MVP; core implementation leaves are never optional.
- Parent headings (`1.`, `3.`, `4.`, ...) carry no code — every implementation
  step is its own decimal leaf so the DAG queue can auto-dispatch it
  independently; optional test leaves sit beside the leaf they cover.
- Each implementation task cites the requirement(s) and/or design element it
  satisfies for traceability.
- The six Hypothesis properties run `@settings(max_examples=100)` and are tagged
  `# Feature: schedule-e-import, Property N: <text>`.
- Non-Goals are respected throughout: no PDF/OCR extraction, no depreciation /
  Line 18 ever written, no itemization beyond one summary transaction per
  non-zero line, no CSV upload, and no change to report aggregation beyond
  surfacing the imported marker. The existing `/imports` PDF feature is left
  untouched.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4", "2.1", "7.1"] },
    { "id": 1, "tasks": ["1.2", "1.5", "2.2", "7.2", "8.1"] },
    { "id": 2, "tasks": ["1.3", "3.1", "8.2", "9.1"] },
    { "id": 3, "tasks": ["3.2", "8.3", "9.2"] },
    { "id": 4, "tasks": ["3.3", "8.4"] },
    { "id": 5, "tasks": ["3.4", "8.5"] },
    { "id": 6, "tasks": ["3.5"] },
    { "id": 7, "tasks": ["3.6", "4.1"] },
    { "id": 8, "tasks": ["4.2"] },
    { "id": 9, "tasks": ["4.3", "5.1", "5.2", "5.3", "5.4", "5.5", "5.6"] }
  ]
}
```
