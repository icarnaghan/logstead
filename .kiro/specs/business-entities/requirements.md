# Requirements Document

## Introduction

Logstead is a single-user (per-authenticated-Cognito-user) serverless application for preparing an IRS Schedule E rental tax return. This feature adds a **Business entities** capability: the ability for a user to record the business entities (such as LLCs) under which they hold rental property, attach supporting documents to each entity, and optionally associate each property with the business entity that owns it.

The feature has four parts:

1. **Business entities** — a user-scoped collection of business entities with full create / list / get / update / delete behavior.
2. **Business documents** — per-entity file uploads (articles of formation, operating agreement, EIN letter, and similar), reusing Logstead's existing receipts/photos S3 upload pattern.
3. **Property ↔ business link** — an optional association letting a property name its owning business entity, viewable from both sides. The link is stored and displayed only; it does not drive report output in this feature.
4. **UI** — a dedicated "Business" section (a new primary-nav entry and page(s)) that reuses existing shared UI primitives and interaction patterns.

Every operation in this feature is scoped to the authenticated user's Cognito `sub`, exactly as all existing Logstead domain data is. This feature introduces no change to authentication, identity, tenancy, or report output.

### Non-Goals (Out of Scope)

The following are explicitly out of scope for this feature and MUST NOT be implemented:

- **Multi-user / multi-tenant product changes** — sign-up for multiple collaborators, roles, sharing, or billing. The feature remains per-authenticated-user like all existing Logstead data.
- **Per-entity Schedule E report / export integration** — using the Property–Business Link to drive per-entity reports, exports, or any change to report output. The link is stored and displayed only. The design MUST NOT preclude future per-entity reporting, but this feature does not implement it.
- **Storing SSNs** — the system stores business-level EINs only and never stores a Social Security Number.
- **Cross-user sharing** of business entities.
- **Backend authentication or identity changes.**
- **Strict EIN format enforcement** — EIN is stored as entered (recorded as an Open Question below).

## Glossary

- **Logstead**: The single-user serverless application for preparing an IRS Schedule E rental tax return.
- **Authenticated_User**: The person identified by a Cognito `sub`. All data in this feature is scoped to this user.
- **Business_Entity**: A record of a legal business entity (e.g., an LLC) owned by the Authenticated_User, under which rental property may be held. A user owns a collection of these, not a single one.
- **Entity_Type**: A classification of a Business_Entity drawn from a fixed supported set (see Open Questions for the exact list), which includes LLC among other options such as Sole proprietorship, Partnership, S-corporation, C-corporation, and Individual/Other.
- **EIN**: Employer Identification Number — a business-level identifier. Stored as free text. The system never stores an SSN in this field or any other.
- **Business_Document**: A binary file (e.g., articles of formation, operating agreement, EIN letter) uploaded and associated with a single Business_Entity, stored in S3 with a metadata row in DynamoDB. "Business document" is a general category, not a fixed set of named document types.
- **Property**: An existing Logstead rental property record owned by the Authenticated_User.
- **Property_Business_Link**: An optional association from a Property to at most one Business_Entity (its owning entity). One Business_Entity may be the owner of many Properties.
- **S3_File_Adapter**: The existing Logstead component that issues presigned PUT upload URLs, presigned GET download URLs, and deletes objects from the shared S3 bucket.
- **Business_Service**: The backend service component (to be created) that performs user-scoped CRUD and document operations for Business_Entity records.
- **Business_Section**: The new top-level UI section (primary-nav entry and page(s)) for managing Business_Entity records, their documents, and property associations.
- **Delete_Guard**: The rule that blocks deletion of a Business_Entity while one or more Properties are linked to it, returning a 409 conflict.

## Requirements

### Requirement 1: Create a business entity

**User Story:** As a Logstead user, I want to create a business entity record, so that I can track the legal entities under which I hold rental property.

#### Acceptance Criteria

1. WHEN the Authenticated_User submits a create request with a non-empty legal_name and a supported entity_type, THE Business_Service SHALL create a Business_Entity scoped to the Authenticated_User and return the created record.
2. THE Business_Service SHALL accept the following optional fields on create: ein, formation_state, formation_date, business_address, tax_year_end, and note.
3. WHERE tax_year_end is omitted on create, THE Business_Service SHALL default tax_year_end to "12-31".
4. IF a create request omits legal_name or provides a legal_name that is empty or only whitespace, THEN THE Business_Service SHALL reject the request with a validation error identifying legal_name.
5. IF a create request omits entity_type or provides an entity_type that is not in the supported set, THEN THE Business_Service SHALL reject the request with a validation error identifying entity_type.
6. THE Business_Service SHALL store the ein value exactly as entered without applying a required format.
7. THE Business_Service SHALL NOT store a Social Security Number in any field of a Business_Entity.

### Requirement 2: List business entities

**User Story:** As a Logstead user, I want to list my business entities, so that I can see every entity I have recorded.

#### Acceptance Criteria

1. WHEN the Authenticated_User requests the business entity list, THE Business_Service SHALL return every Business_Entity owned by the Authenticated_User.
2. THE Business_Service SHALL return only Business_Entity records scoped to the Authenticated_User and SHALL exclude any Business_Entity owned by a different Cognito `sub`.
3. WHERE the Authenticated_User owns no Business_Entity records, THE Business_Service SHALL return an empty list.

### Requirement 3: Get a single business entity

**User Story:** As a Logstead user, I want to retrieve one business entity, so that I can view its full details.

#### Acceptance Criteria

1. WHEN the Authenticated_User requests a Business_Entity the Authenticated_User owns by its identifier, THE Business_Service SHALL return that Business_Entity.
2. IF the Authenticated_User requests a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL return a not-found error.
3. IF the requested Business_Entity exists but is owned by a different Cognito `sub`, THEN THE Business_Service SHALL return a not-found error.

### Requirement 4: Update a business entity

**User Story:** As a Logstead user, I want to edit a business entity, so that I can keep its details current.

#### Acceptance Criteria

1. WHEN the Authenticated_User submits an update to a Business_Entity the Authenticated_User owns, THE Business_Service SHALL apply the submitted changes and return the updated record.
2. IF an update sets legal_name to empty or whitespace-only, THEN THE Business_Service SHALL reject the update with a validation error identifying legal_name.
3. IF an update sets entity_type to a value outside the supported set, THEN THE Business_Service SHALL reject the update with a validation error identifying entity_type.
4. IF the Authenticated_User submits an update for a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL return a not-found error.
5. THE Business_Service SHALL store an updated ein value exactly as entered without applying a required format.

### Requirement 5: Delete a business entity (guarded)

**User Story:** As a Logstead user, I want to delete a business entity I no longer need, so that my list stays accurate, while being prevented from deleting one that still owns properties.

#### Acceptance Criteria

1. WHEN the Authenticated_User deletes a Business_Entity that has no linked Properties, THE Business_Service SHALL remove the Business_Entity and SHALL remove every Business_Document associated with that Business_Entity.
2. IF the Authenticated_User attempts to delete a Business_Entity that has one or more linked Properties, THEN THE Business_Service SHALL reject the deletion with a 409 conflict error instructing the Authenticated_User to reassign or unlink those Properties first.
3. IF the Authenticated_User attempts to delete a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL return a not-found error.
4. WHEN a Business_Entity is deleted, THE Business_Service SHALL remove each associated Business_Document's metadata row and SHALL attempt best-effort removal of each associated S3 object.

### Requirement 6: Request a business document upload

**User Story:** As a Logstead user, I want to upload a document to a business entity, so that I can keep its formation and tax paperwork together.

#### Acceptance Criteria

1. WHEN the Authenticated_User requests an upload for a Business_Entity the Authenticated_User owns, providing a filename and content type, THE Business_Service SHALL store a Business_Document metadata row scoped to that Business_Entity and SHALL return a presigned PUT upload URL from the S3_File_Adapter.
2. THE Business_Document metadata row SHALL record the original filename, the content type, the S3 object key, and an uploaded-at timestamp.
3. IF the Authenticated_User requests an upload for a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL return a not-found error.
4. THE Business_Service SHALL scope each Business_Document to the Authenticated_User and to its Business_Entity so documents of one entity are never returned for another.

### Requirement 7: List business documents

**User Story:** As a Logstead user, I want to list a business entity's documents, so that I can see and retrieve what I have uploaded.

#### Acceptance Criteria

1. WHEN the Authenticated_User lists the documents of a Business_Entity the Authenticated_User owns, THE Business_Service SHALL return every Business_Document associated with that Business_Entity.
2. WHEN the Authenticated_User lists the documents of a Business_Entity, THE Business_Service SHALL include a presigned GET download URL for each returned Business_Document.
3. WHERE a Business_Entity has no documents, THE Business_Service SHALL return an empty list.
4. IF the Authenticated_User lists documents for a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL return a not-found error.

### Requirement 8: Delete a business document

**User Story:** As a Logstead user, I want to delete a business document, so that I can remove paperwork I no longer need.

#### Acceptance Criteria

1. WHEN the Authenticated_User deletes a Business_Document from a Business_Entity the Authenticated_User owns, THE Business_Service SHALL remove the Business_Document metadata row and SHALL remove its S3 object.
2. IF the Authenticated_User deletes a Business_Document identifier that does not exist for the given Business_Entity, THEN THE Business_Service SHALL return a not-found error.

### Requirement 9: Associate a property with a business entity

**User Story:** As a Logstead user, I want to set, change, or clear the business entity that owns a property, so that I can record which entity holds each rental.

#### Acceptance Criteria

1. WHEN the Authenticated_User sets a Property's business to a Business_Entity the Authenticated_User owns, THE Business_Service SHALL record a Property_Business_Link from that Property to that Business_Entity.
2. WHEN the Authenticated_User changes a Property's business to a different owned Business_Entity, THE Business_Service SHALL replace the existing Property_Business_Link so the Property is linked to at most one Business_Entity.
3. WHEN the Authenticated_User clears a Property's business, THE Business_Service SHALL remove the Property_Business_Link so the Property has no owning Business_Entity.
4. WHERE a Property has no Property_Business_Link, THE Property SHALL remain valid and all existing Property behavior SHALL continue unchanged.
5. IF the Authenticated_User attempts to link a Property to a Business_Entity identifier that does not exist for the Authenticated_User, THEN THE Business_Service SHALL reject the request with a validation or not-found error.

### Requirement 10: View the property–business association from both sides

**User Story:** As a Logstead user, I want to see a property's business entity and a business entity's linked properties, so that I understand my ownership structure.

#### Acceptance Criteria

1. WHEN the Authenticated_User views a Property that has a Property_Business_Link, THE Business_Section SHALL display the human-readable legal_name of the linked Business_Entity.
2. WHEN the Authenticated_User views a Business_Entity, THE Business_Section SHALL display the list of Properties linked to that Business_Entity by their human-readable names.
3. THE Business_Section SHALL NOT surface a raw Business_Entity identifier or a raw Property identifier as user-facing content where a human-readable name exists.

### Requirement 11: Business section navigation and management UI

**User Story:** As a Logstead user, I want a dedicated Business section in the app, so that I can manage my entities, their documents, and property associations in one place.

#### Acceptance Criteria

1. THE Business_Section SHALL add a new primary-navigation entry alongside the existing Dashboard, Properties, and Reports entries.
2. WHEN the Authenticated_User opens the Business_Section, THE Business_Section SHALL list the Authenticated_User's Business_Entity records with their legal_name and entity_type.
3. THE Business_Section SHALL provide controls to create, edit, and delete a Business_Entity, reusing the application's established add/edit dialog pattern and ConfirmDialog delete pattern.
4. THE Business_Section SHALL provide controls to upload, list, download, and delete a Business_Entity's documents, reusing the application's established receipts/photos upload UI pattern.
5. THE Business_Section SHALL provide a control to set, change, or clear a Property's associated Business_Entity.
6. WHEN a delete is rejected by the Delete_Guard with a 409 conflict, THE Business_Section SHALL surface the conflict message to the Authenticated_User through the ConfirmDialog delete-guard pattern.

### Requirement 12: Accessibility of the business section UI

**User Story:** As a Logstead user who relies on assistive technology, I want the Business section to be accessible, so that I can manage entities, documents, and associations using a keyboard and a screen reader.

#### Acceptance Criteria

1. THE Business_Section forms, dialogs, and document-upload controls SHALL use semantic markup with programmatically associated labels for every input control.
2. THE Business_Section SHALL expose every interactive control (buttons, form fields, dialogs, upload and delete actions) to keyboard operation.
3. WHEN a Business_Section dialog is open, THE Business_Section SHALL manage focus so keyboard focus is contained within the open dialog.
4. THE Business_Section views, forms, dialogs, and upload UI SHALL pass automated accessibility assertions with no violations.

### Requirement 13: User scoping and data-handling invariants

**User Story:** As a Logstead user, I want my business data isolated to my account and consistent with the app's conventions, so that my information stays private and correctly formatted.

#### Acceptance Criteria

1. THE Business_Service SHALL scope every Business_Entity, Business_Document, and Property_Business_Link read and write to the Authenticated_User's Cognito `sub`.
2. THE Business_Service SHALL represent any money value as a two-decimal string, consistent with existing Logstead conventions.
3. THE Business_Service SHALL NOT drive Schedule E report output or export from the Property_Business_Link in this feature.

## Open Questions

The following decisions remain genuinely open and should be resolved during design rather than invented here:

1. **EIN format**: EIN is currently specified as stored exactly as entered (no required format). Should the UI apply a light display formatting hint (e.g., `NN-NNNNNNN`) without rejecting other input, or remain entirely free text? No strict validation is in scope unless a required format is explicitly agreed.
2. **Entity_type option list**: The supported set includes LLC, Sole proprietorship, Partnership, S-corporation, C-corporation, and Individual/Other. The exact final list and labels should be confirmed in design.
3. **tax_year_end representation**: Should tax_year_end be a free-text/`MM-DD` field defaulting to "12-31", or a constrained date/month-day picker? Defaulting to "12-31" is agreed; the exact input representation is open.
4. **formation_date and formation_state representation**: formation_date is an optional date and formation_state is an optional US state. The exact input representation (free text vs. picker/date control) should be confirmed in design.

> Note: The user-scoping of Business_Entity records and Business_Documents (Requirements 2.2, 3.3, 6.4, 13.1) and the Delete_Guard behavior (Requirement 5.2) are correctness-relevant and should be covered by property-based tests during design and implementation, consistent with the rest of the codebase.
