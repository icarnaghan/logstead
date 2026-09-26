# Requirements Document

## Introduction

Logstead lets a single authenticated user track Schedule E rental data (properties, transactions, depreciable assets, per-year usage days, property notes, and RentCast-enriched property details). This feature adds **Backup, Restore, Clear, and Sample Data** capabilities so the user can move a portable copy of that data in and out of the system and reset it.

Four capabilities are in scope:

1. **Export** — download all of the authenticated user's data as a single JSON backup document.
2. **Restore** — upload a backup document and rebuild the user's data from it, using **replace-all** semantics that **preserve the original ids and timestamps** so cross-references (transaction → property, asset → property, usage → property) remain intact.
3. **Clear** — delete all of the authenticated user's currently entered data, including the associated S3 binaries (property photos and receipt files), leaving no orphaned storage.
4. **Sample Data** — a committed sample backup fixture (2 fictional properties, 5 years of Schedule E data) and a UI action that loads it via the restore path.

The backup document deliberately **excludes binaries (photos, receipts) and their metadata**, staging data (import sessions / PDF-import drafts), and the fixed category catalog. Money is represented end-to-end as exact two-decimal strings, never floats. Depreciation schedule rows are computed from assets and are not stored in the backup; they are recomputed on restore.

This document defines the requirements only. The design phase decides the exact write path (id/timestamp preservation), route surface, batching mechanism, and UI placement.

## Glossary

- **Backup_System**: The end-to-end capability (backend service plus frontend UI) that performs export, restore, clear, and sample-data load.
- **Export_Service**: The component that gathers the authenticated user's data and produces a Backup_Document.
- **Restore_Service**: The component that validates a Backup_Document and rebuilds the user's data from it.
- **Clear_Service**: The component that deletes all of the authenticated user's data, including S3 binaries.
- **Backup_Document**: A single JSON document containing the exported data plus a schema version marker.
- **Schema_Version**: A version marker embedded in the Backup_Document identifying its format.
- **Sample_Fixture**: A committed JSON file (a Backup_Document) containing 2 fictional properties and 5 years of Schedule E data.
- **User**: The authenticated account, identified by its Cognito `sub`. All data is scoped to this identity.
- **Property**: A rental property owned by the User: `id`, `name`, `address_text`, `property_type`, `created_at`, `updated_at`.
- **Property_Details**: The optional sparse RentCast-enriched tree attached to a Property (address/geo/structure fields, parcel/legal, last sale, nested features map, HOA, owner, and year-keyed tax assessments / property taxes / sale history).
- **Property_Note**: A single free-text note per Property.
- **Property_Usage_Year**: Per-Property, per-tax-year `fair_rental_days` and `personal_use_days`.
- **Transaction**: An income or expense record: `id`, `property_id`, `date`, `amount`, `type`, `category_id`, `schedule_e_line`, `description`, `created_at`, `updated_at`.
- **Depreciable_Asset**: A depreciable asset: `id`, `property_id`, `description`, `cost_basis`, `placed_in_service_date`, `recovery_period_years`, `created_at`, `updated_at`.
- **Depreciation_Schedule_Row**: A computed per-year depreciation row derived from a Depreciable_Asset. Not stored in the Backup_Document.
- **Category_Catalog**: The fixed, seeded set of Schedule E categories referenced by Transactions via a stable slug id (e.g. `rents-received`, `repairs`). Reference data, not backed up.
- **S3_Binary**: A photo or receipt file stored in Amazon S3 and referenced by DynamoDB metadata.
- **Confirmation**: An explicit user acknowledgement (matching Logstead's existing destructive-action confirmation pattern) required before a destructive operation proceeds.

## Requirements

### Requirement 1: Export the user's data as a JSON backup document

**User Story:** As the authenticated user, I want to download all of my data as a single JSON file, so that I have a portable, restorable copy of my Schedule E records.

#### Acceptance Criteria

1. WHEN the User requests an export, THE Export_Service SHALL produce a single Backup_Document containing every Property owned by the User.
2. WHEN the Export_Service produces a Backup_Document, THE Export_Service SHALL include, for each Property, the Property fields `id`, `name`, `address_text`, `property_type`, `created_at`, and `updated_at`.
3. WHERE a Property has stored Property_Details, THE Export_Service SHALL include the full nested Property_Details tree in the Backup_Document.
4. WHERE a Property has a Property_Note, THE Export_Service SHALL include the Property_Note text in the Backup_Document.
5. WHERE a Property has one or more Property_Usage_Year records, THE Export_Service SHALL include each `tax_year` with its `fair_rental_days` and `personal_use_days` in the Backup_Document.
6. WHEN the Export_Service produces a Backup_Document, THE Export_Service SHALL include every Transaction of each owned Property with the fields `id`, `property_id`, `date`, `amount`, `type`, `category_id`, `schedule_e_line`, `description`, `created_at`, and `updated_at`.
7. WHEN the Export_Service produces a Backup_Document, THE Export_Service SHALL include every Depreciable_Asset of each owned Property with the fields `id`, `property_id`, `description`, `cost_basis`, `placed_in_service_date`, `recovery_period_years`, `created_at`, and `updated_at`.
8. THE Export_Service SHALL reference each Transaction's category by the Category_Catalog stable slug id and SHALL NOT embed the Category_Catalog itself in the Backup_Document.
9. THE Export_Service SHALL exclude property photo metadata, receipt document metadata, import sessions, and PDF-import drafts from the Backup_Document.
10. THE Export_Service SHALL exclude Depreciation_Schedule_Rows from the Backup_Document.
11. WHEN the Export_Service produces a Backup_Document, THE Export_Service SHALL embed a Schema_Version marker identifying the document format.
12. WHEN the User completes an export, THE Backup_System SHALL deliver the Backup_Document to the User as a downloadable file.

### Requirement 2: Restore rebuilds the user's data with replace-all and preserved ids

**User Story:** As the authenticated user, I want to upload a previously exported backup and have my data rebuilt exactly as it was, so that a restore is a true recovery in which all cross-references still resolve.

#### Acceptance Criteria

1. WHEN the User submits a valid Backup_Document for restore, THE Restore_Service SHALL first remove all of the User's existing data before writing any data from the Backup_Document.
2. WHEN the Restore_Service writes an entity from a valid Backup_Document, THE Restore_Service SHALL recreate that entity using the `id` recorded in the Backup_Document rather than generating a new id.
3. WHEN the Restore_Service writes an entity that carries `created_at` and `updated_at` in the Backup_Document, THE Restore_Service SHALL persist those original timestamp values.
4. WHEN the Restore_Service recreates Properties, Transactions, Depreciable_Assets, and Property_Usage_Year records, THE Restore_Service SHALL preserve each `property_id` cross-reference so every child entity resolves to its original Property.
5. WHEN the Restore_Service completes a successful restore, THE Restore_Service SHALL recompute each Depreciable_Asset's Depreciation_Schedule_Rows from the restored asset data.
6. IF a Backup_Document contains no Properties, THEN THE Restore_Service SHALL clear the User's existing data and complete with an empty result.

### Requirement 3: Restore validates the document before making changes

**User Story:** As the authenticated user, I want a malformed or incompatible backup to be rejected cleanly, so that a bad upload never leaves my data half-wiped or inconsistent.

#### Acceptance Criteria

1. IF a submitted Backup_Document is not valid JSON or does not conform to the expected structure, THEN THE Restore_Service SHALL reject the request with a validation error and SHALL NOT delete or modify any of the User's existing data.
2. IF a submitted Backup_Document is missing a required field for any entity it contains, THEN THE Restore_Service SHALL reject the request with a validation error identifying the offending entity and field, and SHALL NOT delete or modify any of the User's existing data.
3. WHEN the Restore_Service validates a Backup_Document, THE Restore_Service SHALL complete all structural and content validation before performing the replace-all clear described in Requirement 2.1.
4. IF a monetary value in a submitted Backup_Document is not a valid two-decimal string, THEN THE Restore_Service SHALL reject the request with a validation error identifying the offending value, and SHALL NOT delete or modify any of the User's existing data.

### Requirement 4: Restore enforces category integrity

**User Story:** As the authenticated user, I want restored transactions to reference valid Schedule E categories, so that my imported data stays consistent with the fixed category catalog.

#### Acceptance Criteria

1. IF a Transaction in a submitted Backup_Document has a `category_id` that does not match any Category_Catalog entry, THEN THE Restore_Service SHALL reject the Backup_Document with a validation error identifying the offending `category_id`, and SHALL NOT delete or modify any of the User's existing data.
2. IF a Transaction in a submitted Backup_Document is missing its `category_id`, THEN THE Restore_Service SHALL reject the Backup_Document with a validation error identifying the offending Transaction, and SHALL NOT delete or modify any of the User's existing data.
3. WHEN the Restore_Service encounters an unknown or absent `category_id`, THE Restore_Service SHALL NOT silently drop the Transaction and SHALL NOT reassign it to a different category.

### Requirement 5: Restore validates the schema version

**User Story:** As the authenticated user, I want the system to detect an incompatible backup format, so that a document from an unsupported version fails with a clear message instead of corrupting my data.

#### Acceptance Criteria

1. IF a submitted Backup_Document is missing its Schema_Version marker, THEN THE Restore_Service SHALL reject the request with a validation error and SHALL NOT delete or modify any of the User's existing data.
2. IF a submitted Backup_Document carries a Schema_Version that the Restore_Service does not support, THEN THE Restore_Service SHALL reject the request with a message identifying the unsupported version, and SHALL NOT delete or modify any of the User's existing data.
3. WHEN a submitted Backup_Document carries a supported Schema_Version, THE Restore_Service SHALL proceed with validation and restore.

### Requirement 6: Restore requires explicit confirmation

**User Story:** As the authenticated user, I want to confirm before a restore overwrites my data, so that I do not destroy my current records by accident.

#### Acceptance Criteria

1. WHEN the User initiates a restore in the UI, THE Backup_System SHALL require an explicit Confirmation before the Restore_Service removes any existing data.
2. IF the User cancels the restore Confirmation, THEN THE Backup_System SHALL abort the restore and SHALL leave the User's existing data unchanged.

### Requirement 7: Clear deletes all of the user's data

**User Story:** As the authenticated user, I want to wipe all of my entered data in one action, so that I can start over from an empty state.

#### Acceptance Criteria

1. WHEN the User confirms a clear, THE Clear_Service SHALL delete every Property owned by the User along with each Property's Property_Details, Property_Note, and Property_Usage_Year records.
2. WHEN the User confirms a clear, THE Clear_Service SHALL delete every Transaction of each owned Property.
3. WHEN the User confirms a clear, THE Clear_Service SHALL delete every Depreciable_Asset of each owned Property.
4. WHEN the Clear_Service completes, THE Clear_Service SHALL leave the User with no remaining Properties, Transactions, Depreciable_Assets, Property_Details, Property_Notes, or Property_Usage_Year records.

### Requirement 8: Clear removes S3 binaries and orders deletes safely

**User Story:** As the authenticated user, I want a clear to also remove my stored photos and receipt files, so that no orphaned storage remains after I wipe my data.

#### Acceptance Criteria

1. WHEN the Clear_Service deletes a property photo, THE Clear_Service SHALL delete both the photo's S3_Binary and the photo's metadata row.
2. WHEN the Clear_Service deletes a transaction receipt, THE Clear_Service SHALL delete both the receipt's S3_Binary and the receipt's metadata row.
3. WHEN the Clear_Service removes an S3-backed record, THE Clear_Service SHALL delete the S3_Binary before deleting its metadata row.
4. IF an individual S3_Binary deletion fails, THEN THE Clear_Service SHALL record the failure and continue deleting the remaining records rather than aborting the clear.
5. WHEN the Clear_Service deletes a Property's records, THE Clear_Service SHALL delete that Property's Transactions and Depreciable_Assets before deleting the Property row, so the Property deletion is not blocked by its associated records.

### Requirement 9: Clear requires explicit confirmation

**User Story:** As the authenticated user, I want to confirm before clearing everything, so that I do not lose all my data by accident.

#### Acceptance Criteria

1. WHEN the User initiates a clear in the UI, THE Backup_System SHALL require an explicit Confirmation before the Clear_Service deletes any data.
2. IF the User cancels the clear Confirmation, THEN THE Backup_System SHALL abort the clear and SHALL leave the User's data unchanged.

### Requirement 10: Sample data fixture and load action

**User Story:** As the authenticated user, I want to load a realistic sample dataset with one action, so that I can explore Schedule E features without hand-entering data.

#### Acceptance Criteria

1. THE Backup_System SHALL ship a committed Sample_Fixture that is a valid Backup_Document.
2. THE Sample_Fixture SHALL contain exactly 2 fictional Properties.
3. THE Sample_Fixture SHALL contain 5 tax years of Schedule E data, including income Transactions and expense Transactions spanning multiple Schedule E categories.
4. THE Sample_Fixture SHALL contain at least one Depreciable_Asset per Property so that depreciation (Schedule E Line 18) is exercised.
5. WHEN the User activates the load-sample-data action, THE Backup_System SHALL ingest the Sample_Fixture through the restore path defined in Requirements 2 through 6.
6. WHEN the User activates the load-sample-data action, THE Backup_System SHALL require the same restore Confirmation described in Requirement 6.1 before replacing existing data.

### Requirement 11: All operations are scoped to the authenticated user

**User Story:** As the authenticated user, I want backup, restore, and clear to only ever touch my own data, so that no other user's records are exposed or altered.

#### Acceptance Criteria

1. WHEN the Export_Service, Restore_Service, or Clear_Service runs, THE Backup_System SHALL scope all reads and writes to the authenticated User's Cognito `sub`.
2. WHEN a service needs to reach a Property's child records (Transactions, Depreciable_Assets, Property_Usage_Year, Property_Note, photos, receipts), THE Backup_System SHALL first confirm the parent Property is owned by the authenticated User.
3. THE Backup_System SHALL derive the set of Properties to export, restore, or clear from the authenticated User's owned-property list, and SHALL NOT read or mutate a Property not owned by the authenticated User.
4. THE Backup_System SHALL NOT provide any cross-user, multi-user, or administrative backup, restore, or clear operation.

### Requirement 12: Restore leaves data in a consistent state

**User Story:** As the authenticated user, I want a restore to either fully succeed or leave my data usable, so that a failure partway through does not strand me with a mixture of old and new records.

#### Acceptance Criteria

1. WHEN the Restore_Service applies a validated Backup_Document, THE Restore_Service SHALL ensure that on successful completion the User's stored data matches the Backup_Document contents with no records left over from before the restore.
2. IF the Restore_Service fails after the replace-all clear has begun, THEN THE Restore_Service SHALL surface an error that informs the User the restore did not complete, so the User can retry the restore.
3. WHEN a Backup_Document contains more entities than a single atomic write can accommodate, THE Restore_Service SHALL apply the writes in batches while preserving the consistency guarantee of Requirement 12.1.

### Requirement 13: Money is represented exactly as two-decimal strings

**User Story:** As the authenticated user, I want monetary amounts to survive a backup-and-restore round trip without rounding error, so that my Schedule E figures stay exact.

#### Acceptance Criteria

1. WHEN the Export_Service writes any monetary amount to a Backup_Document, THE Export_Service SHALL render the amount as an exact two-decimal string and SHALL NOT render it as a floating-point number.
2. WHEN the Restore_Service reads a monetary amount from a Backup_Document, THE Restore_Service SHALL parse it as an exact decimal and SHALL NOT convert it through a floating-point representation.
3. WHEN a Property_Details geographic coordinate (latitude or longitude) is exported, THE Export_Service SHALL render it as a full-precision decimal string.
4. FOR ALL Backup_Documents produced by the Export_Service, restoring the document and re-exporting SHALL produce an equivalent Backup_Document with identical monetary and coordinate values (round-trip consistency).

## Non-Goals

- **Photos and receipts are not backed up or restored.** Property photos and transaction receipt files (binaries) and their metadata are out of scope for the Backup_Document. Clear does delete their S3 objects to avoid orphaned storage, but that is cleanup, not backup.
- **The Category_Catalog is not backed up.** It is fixed reference data, re-seeded at deploy time; Transactions reference categories by stable slug id only.
- **Depreciation schedule rows are not backed up.** They are computed from Depreciable_Assets and are recomputed on restore.
- **Import sessions and PDF-import drafts (staging data) are not backed up.**
- **No cross-user or administrative backup.** The feature is single-user only, scoped to the authenticated user's Cognito `sub`.
- **No scheduled or automatic backups.** All export, restore, and clear operations are user-initiated.
- **Restore is not a merge.** It is replace-all; it does not combine an uploaded document with existing data, and it does not generate new ids.
