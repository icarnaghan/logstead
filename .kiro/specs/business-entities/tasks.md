# Implementation Plan: Business Entities

## Overview

Convert the Business Entities design into incremental, independently-schedulable
coding tasks. The backend lands first (key scheme → model → service CRUD →
documents → property link → guarded delete → routes), then the frontend (typed
api module → nav/list → dialogs → delete UI → documents UI → link selector).
After the key helpers and model land, the two tiers and the three sections
(entity CRUD, documents, property↔business link) are largely independent, so the
plan is a flat list of leaf implementation tasks — each one its own queueable
leaf — with optional (`*`) test leaves attached as its direct children. Parent
headings (1., 9.) carry no code; all code lives in decimal leaves.

All work respects the Non-Goals: no multi-tenant/multi-user changes, no
per-entity Schedule E report/export integration, no SSN storage, no auth/identity
changes. The feature introduces no money fields, so the two-decimal-string money
invariant (Req 13.2) is trivially preserved; the identity invariant (Req 10.3)
is upheld by always resolving names before rendering.

Conventions: backend `pytest` + `moto` + `Hypothesis` (property tests at
`@settings(max_examples=100)` or more, tagged
`# Feature: business-entities, Property N: <text>`); frontend `vitest` + React
Testing Library + `vitest-axe`, UI driven through an injectable `api/` layer.
Money and ids are carried as strings over the wire.

## Tasks

- [x] 1. Backend foundation: keys, S3 key helper, and model

  - [x] 1.1 Add `business_*` key helpers to `repository/keys.py`
    - Add `BUSINESS_PREFIX = "BUSINESS#"` and helpers `business_scoped_pk`,
      `business_meta_sk`, `business_user_sk`, `business_list_prefix`,
      `business_document_sk`, `business_document_list_prefix`, reusing the
      existing `META_SK` and `DOC_PREFIX` constants (standard-library only, no
      raw keys in services).
    - _Design: Components/Interfaces → `repository/keys.py` business_* helpers_

  - [ ]* 1.2 Unit test the key helpers
    - Assert each helper's exact string shape (meta mirror SK, user list SK,
      list prefix, document SK/list prefix) so services can rely on them.
    - _Design: `repository/keys.py` business_* helpers_

  - [x] 1.3 Add `business_doc_key` to `adapters/s3_files.py`
    - Add `BUSINESS_DOC_PREFIX = "business-docs"` and
      `business_doc_key(business_id, filename)` built via the existing
      `build_key`, alongside `photo_key`/`receipt_key`. The service namespaces
      the filename segment by document id (`<docId>/<name>`) so uploads never
      collide.
    - _Design: Components/Interfaces → `adapters/s3_files.py` business_doc_key_

  - [ ]* 1.4 Unit test `business_doc_key`
    - Assert the `business-docs/<businessId>/<filename>` key shape.
    - _Design: `adapters/s3_files.py` business_doc_key_

  - [x] 1.5 Create `models/business.py`
    - Add `ENTITY_TYPES` frozenset (six values: `llc`,
      `sole_proprietorship`, `partnership`, `s_corporation`, `c_corporation`,
      `individual_other`), `DEFAULT_TAX_YEAR_END = "12-31"`, and the
      `BusinessInput`, `Business`, and `BusinessDocument` dataclasses with the
      fields and defaults from the design (`Business.tax_year_end` defaults to
      `"12-31"`; optional fields default to `None`). No money fields.
    - _Design: Data Models → `models/business.py`; Req 1.2, 1.3_

  - [ ]* 1.6 Unit test the business model
    - Assert dataclass defaults (`tax_year_end == "12-31"`, optionals `None`)
      and that `ENTITY_TYPES` contains exactly the six documented values.
    - _Design: Data Models_

- [x] 2. Implement `BusinessService` entity CRUD in `services/business.py`
  - Create `BusinessService` with `__init__(self, repo, user, files=None,
    property_service=None)`, scoping every operation to the user's Cognito `sub`.
  - `create`: validate `legal_name` non-blank (Req 1.4) and `entity_type in
    ENTITY_TYPES` (Req 1.5); default `tax_year_end` to `"12-31"` when omitted
    (Req 1.3); store `ein` verbatim (Req 1.6); never store an SSN (Req 1.7);
    write the user-view list row + meta mirror together via `transact_write`
    (Req 2.2, 13.1).
  - `list`: return every business for the user via `begins_with` on
    `business_list_prefix()`; empty list when none (Req 2.1, 2.3).
  - `get`/`update`: resolve the owned meta row first; `not_found` when missing or
    owned by another `sub` (Req 3.1-3.3, 4.1, 4.4); `update` re-validates
    `legal_name`/`entity_type` (Req 4.2, 4.3) and stores `ein` verbatim
    (Req 4.5), rewriting both rows via `transact_write`.
  - `owns(business_id)`: boolean owned-meta check for `PropertyService` to call.
  - _Design: `services/business.py` BusinessService; Req 1, 2, 3, 4, 13.1_

  - [x]* 2.1 Write moto example/edge tests for entity CRUD
    - create happy path; blank/whitespace `legal_name` → `validation`(field
      `legal_name`); missing/invalid `entity_type` → `validation`(field
      `entity_type`); `tax_year_end` default `"12-31"`; `ein` stored verbatim;
      list empty + populated; cross-user `get`/`update` → `not_found`.
    - _Design: Testing Strategy → example/edge; Req 1, 2, 3, 4_

  - [x]* 2.2 Write property test: create → get round-trip
    - **Property 4: Business create → get round-trip preserves fields** —
      `@settings(max_examples=100)`, tagged
      `# Feature: business-entities, Property 4: ...`.
    - **Validates: Requirements 1.1, 1.3, 1.6**

- [x] 3. Implement `BusinessService` document operations
  - Add `ALLOWED_DOCUMENT_TYPES` frozenset (broader than photos:
    `application/pdf`, `image/jpeg`, `image/png`, `image/webp`, `image/heic`,
    `image/heif`).
  - `request_document_upload(business_id, filename, content_type)`: resolve owned
    business (`not_found` otherwise, Req 6.3); reject unsupported `content_type`
    with `validation`(field `content_type`) **before** issuing any S3 URL or
    writing metadata — mirror `PhotoService.request_upload` ordering; then write
    the `BusinessDocument` metadata row (original filename, content type, s3 key,
    uploaded-at) scoped to user+business and return a presigned PUT URL
    (Req 6.1, 6.2, 6.4).
  - `list_documents(business_id)`: owned-business check (`not_found`, Req 7.4);
    return every doc with a presigned GET URL; empty list when none
    (Req 7.1-7.3).
  - `delete_document(business_id, document_id)`: delete the S3 object then the
    metadata row; `not_found` when the doc is absent for the business
    (Req 8.1, 8.2).
  - _Design: `services/business.py` document methods; Error Handling allow-list;
    Req 6, 7, 8_

  - [x]* 3.1 Write moto S3 example tests for documents
    - upload → list (presigned GET present) → delete; unsupported `content_type`
      rejected before any S3 URL/metadata; cross-user/unknown business →
      `not_found`; unknown document id → `not_found`.
    - _Design: Testing Strategy → documents; Req 6, 7, 8_

- [x] 4. Add the property↔business link attribute and `PropertyService.set_business`
  - In `services/property.py`, carry an optional `businessId` on **both**
    property rows in `property_to_rows` (verbatim, like other fields) so it
    survives update/restore and is readable from the META mirror (Req 10.1).
  - Add `set_business(property_id, business_id | None)`: confirm property
    ownership (`not_found` otherwise); when `business_id` is given, validate it
    is owned via the injected `BusinessService.owns` (else not-found/validation,
    Req 9.5); rewrite both property rows atomically with `businessId` set
    (set/change) or removed (clear), refreshing `updated_at`. A change is a plain
    overwrite, so a property links to at most one business (Req 9.1-9.4).
  - _Design: `services/property.py` set_business; link decisions; Req 9, 10.1_

  - [x]* 4.1 Write moto tests for `set_business`
    - set / change (overwrite) / clear (attribute removed); linking to a
      non-owned/unknown business → not-found/validation; unknown property →
      `not_found`; unlinked property remains valid (Req 9.4).
    - _Design: Testing Strategy → link set/change/clear; Req 9_

- [x] 5. Implement `BusinessService.linked_properties` and wire the link to `PropertyService`
  - Add `linked_properties(business_id)`: owned-business check; list the user's
    `PROP#` rows (cheap `begins_with` on the user partition) and filter by
    `businessId`, returning linked-property refs (id + legal/display name) for
    both the business→properties view (Req 10.2) and the delete-guard (Req 5.2).
  - Wire `PropertyService` with an injected `BusinessService` (and vice versa as
    the design's constructor allows) so `set_business` can call `owns` and the
    business `get` response can carry linked property names (Req 10.3 — never a
    raw id where a name exists).
  - _Design: Architecture → filtered property-list mechanism; `linked_properties`;
    Req 10_

  - [x]* 5.1 Write moto tests for `linked_properties` and both-side consistency
    - after set/change/clear, the business lists exactly the properties whose
      current `businessId` equals it; names (not raw ids) are returned.
    - _Design: Testing Strategy → both-direction viewing; Req 10_

  - [x]* 5.2 Write property test: at-most-one link, consistent both ways
    - **Property 3: A property links to at most one business, consistent both
      ways** — random sequences of set/change/clear; assert last-write-wins and
      bidirectional agreement. `@settings(max_examples=100)`, tagged
      `# Feature: business-entities, Property 3: ...`.
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 10**

- [x] 6. Implement guarded delete + document cascade in `BusinessService.delete`
  - `delete(business_id)`: resolve owned business (`not_found` otherwise,
    Req 5.3); compute `linked_properties`; if any exist, return
    `Result.failure("conflict", <reassign-or-unlink-first message>)` and mutate
    nothing (Req 5.2). When none exist, list the business's documents,
    best-effort delete each S3 object, then remove the document metadata rows and
    the business's two rows (Req 5.1, 5.4).
  - _Design: `services/business.py` delete; Error Handling → conflict; Req 5_

  - [x]* 6.1 Write moto tests for the delete-guard and cascade
    - delete with ≥1 linked property → `conflict` with the reassign message,
      nothing mutated; delete after unlinking succeeds; cascade removes all
      document metadata rows and attempts S3 object deletion; cross-user/unknown
      → `not_found`.
    - _Design: Testing Strategy → delete-guard/cascade; Req 5_

  - [x]* 6.2 Write property test: guarded delete all-or-nothing with cascade
    - **Property 2: Guarded delete is all-or-nothing with cascade** —
      `@settings(max_examples=100)`, tagged
      `# Feature: business-entities, Property 2: ...`.
    - **Validates: Requirements 5.1, 5.2, 5.4**

- [x] 7. Add business + link routes and per-request wiring in `router/handler.py`
  - Add `_business_service(wiring, user)` constructor (document routes pass
    `_require_files(wiring)` so they return 503 when no bucket is configured).
  - Register `_ROUTES` entries (all `public=False`), document paths before the
    single-id path for segment-count disambiguation: `POST`/`GET /businesses`,
    `GET`/`PUT`/`DELETE /businesses/{businessId}`, `POST`/`GET
    /businesses/{businessId}/documents`, `DELETE
    /businesses/{businessId}/documents/{documentId}`, and `PUT
    /properties/{propertyId}/business` (body `{ "business_id": "<id>" | null }`
    → `PropertyService.set_business`).
  - Thin handlers only: resolve `current_user(event)`, call the service, map via
    `_result_response`/`_response` (`validation`→400, `not_found`→404,
    `conflict`→409, `unavailable`→503); the `GET /businesses/{businessId}`
    response includes linked property names (Req 10.2/10.3). No business rules in
    the router.
  - _Design: `router/handler.py` routes + link route decision; Req 1.*, 5, 6, 7,
    8, 9, 11.1_

  - [x]* 7.1 Write handler/integration tests for the routes
    - status-code mapping per method (201/200/404/409); document routes → 503
      when files unavailable; the set/clear link route; the `GET` single response
      carries linked property names, not raw ids.
    - _Design: Error Handling; Testing Strategy_

  - [x]* 7.2 Write property test: user scoping isolates all business data
    - **Property 1: User scoping isolates all business data** — two distinct
      users; B's reads/mutations against A's ids return `not_found`/exclude A's
      records and never change A's data. `@settings(max_examples=100)`, tagged
      `# Feature: business-entities, Property 1: ...`. Placed at the
      service/handler level where it exercises the full user-scoping path.
    - **Validates: Requirements 2.2, 3.3, 6.4, 13.1**

- [x] 8. Backend checkpoint
  - Run `cd backend && .venv/bin/python -m pytest -q` and ensure the full suite
    (examples + Properties 1-4) passes. If iCloud has materialized `* 2.*`
    duplicate files or the venv is stale, clean the duplicates and rebuild the
    venv before rerunning. Ask the user if questions arise.

- [x] 9. Frontend: typed api module and Business section UI

  - [x] 9.1 Create `api/businesses.ts`
    - Typed, injectable module mirroring `api/properties.ts` and `api/photos.ts`:
      `listBusinesses`, `createBusiness`, `getBusiness`, `updateBusiness`,
      `deleteBusiness`; document functions `listDocuments`,
      `requestDocumentUpload`, `deleteDocument`, `uploadToPresignedUrl`; and
      `setPropertyBusiness(propertyId, businessId | null)`. Wire shapes use the
      backend snake_case names; money and ids are strings.
    - _Design: Frontend components → `api/businesses.ts`_

  - [ ]* 9.2 Unit test `api/businesses.ts`
    - Assert each function calls the right method/path/body against an injected
      fake client (including the `{ business_id: null }` clear payload).
    - _Design: Frontend_

- [x] 10. Add nav entry, Business list page, and route wiring
  - Add `{ to: "/businesses", label: "Businesses" }` to `PRIMARY_NAV` in
    `components/navConfig.ts` (Req 11.1); create `BusinessListPage` listing each
    business's `legal_name` + `entity_type` with an empty state (Req 11.2); wire
    the `/businesses` route in `App.tsx`.
  - _Design: Frontend components; Req 11.1, 11.2_

  - [x]* 10.1 Write RTL + vitest-axe tests for the list page and nav
    - renders legal_name + entity_type rows and an empty state when none; nav
      entry present; no axe violations (Req 12.4).
    - _Design: Testing Strategy → frontend; Req 11.2_

- [x] 11. Build Add/Edit business dialogs
  - `AddBusinessDialog`/`EditBusinessDialog` (Radix Dialog) mirroring
    `AddPropertyDialog`/`EditPropertyDialog`: `entity_type` `<select>` requiring
    explicit selection (no default), EIN placeholder hint (`NN-NNNNNNN`,
    non-blocking), `formation_state` 50-states+DC dropdown, native
    `<input type="date">` for `formation_date`, month/day input for
    `tax_year_end`; surface server 400 field errors adjacent to the field.
  - _Design: Frontend components + Resolved Decisions; Req 1, 4, 11.3_

  - [x]* 11.1 Write RTL + vitest-axe tests for the dialogs
    - entity_type requires explicit selection; EIN hint present but non-blocking;
      state/date/month-day controls; a server 400 renders beside its field;
      focus is contained in the open dialog; no axe violations (Req 12.1-12.4).
    - _Design: Testing Strategy → frontend; Req 1, 4, 11.3_

- [x] 12. Build the delete-business UI with 409 surfacing
  - A `DeleteBusinessConfirm` using the shared `ConfirmDialog` that triggers
    `deleteBusiness` and, on a 409 conflict, surfaces the backend conflict
    message through the delete-guard pattern.
  - _Design: Frontend components; Req 5.2, 11.3, 11.6_

  - [x]* 12.1 Write RTL + vitest-axe tests for delete UI
    - confirm → delete happy path; a 409 response renders the backend conflict
      message; no axe violations.
    - _Design: Testing Strategy → frontend; Req 11.6_

- [x] 13. Build the business documents UI
  - `BusinessDocuments`: upload / list / download / delete reusing the
    photos/receipts upload UI, with a client-side content-type check against the
    broader allow-list (`application/pdf` + the image types) and an empty state.
  - _Design: Frontend components; Req 11.4_

  - [x]* 13.1 Write RTL + vitest-axe tests for documents UI
    - upload (client-side type check rejects unsupported, accepts pdf/images),
      list with download links, delete, empty state; no axe violations.
    - _Design: Testing Strategy → frontend; Req 11.4_

- [x] 14. Build the property↔business selector (both sides)
  - A `PropertyBusinessSelector` on the property edit/detail UI that shows and
    sets/changes/clears the owning business via `setPropertyBusiness`, displaying
    the linked business's `legal_name` (Req 10.1); and the business detail page
    listing linked property names (Req 10.2). Never surface a raw business or
    property id where a human-readable name exists (Req 10.3).
  - _Design: Frontend components; Req 9, 10, 10.3, 11.5_

  - [x]* 14.1 Write RTL + vitest-axe tests for the selector and both-side views
    - selecting/clearing a business calls `setPropertyBusiness`; property view
      shows the business name; business view lists property names; no raw ids
      shown; no axe violations.
    - _Design: Testing Strategy → frontend; Req 9, 10, 11.5_

- [x] 15. Final checkpoint
  - Run the full backend suite (`cd backend && .venv/bin/python -m pytest -q`)
    and the frontend `npm test` plus `npm run build`; ensure all pass. Apply the
    iCloud `* 2.*` cleanup and venv-rebuild steps if needed. Ask the user if
    questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster
  MVP; core implementation leaves are never optional.
- Parent headings `1.` and `9.` carry no code — every implementation step is its
  own decimal leaf so the DAG queue can auto-dispatch it independently; optional
  test leaves sit beside the leaf they cover.
- Each implementation task cites the requirement(s) and/or design element it
  satisfies for traceability.
- The four Hypothesis properties run `@settings(max_examples=100)` or more and
  are tagged `# Feature: business-entities, Property N: <text>`.
- Non-Goals are respected throughout: no multi-tenant changes, no per-entity
  report/export integration, no SSN storage, no auth/identity changes.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "1.5"] },
    { "id": 1, "tasks": ["1.2", "1.4", "1.6", "2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "3", "4"] },
    { "id": 3, "tasks": ["3.1", "4.1", "5", "9.1"] },
    { "id": 4, "tasks": ["5.1", "5.2", "6", "9.2", "10"] },
    { "id": 5, "tasks": ["6.1", "6.2", "7", "10.1", "11", "13"] },
    { "id": 6, "tasks": ["7.1", "7.2", "11.1", "12", "13.1", "14"] },
    { "id": 7, "tasks": ["12.1", "14.1"] }
  ]
}
```
