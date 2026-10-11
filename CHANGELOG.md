# Changelog

All notable changes to Logstead are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Released
versions correspond to git tags.

## [1.1.0] - 2026-10-10

A minor release adding data portability (backup, restore, clear, and sample
data) on the existing Lambda / DynamoDB / S3 architecture, with no new
infrastructure.

### Added

- **Backup export** - `GET /backup` returns a full JSON backup of the
  authenticated user's Schedule E data (properties, details, notes, usage years,
  transactions, assets). Money is serialized as two-decimal strings, and the
  document carries a `schema_version` and `exported_at`.
- **Restore** - `POST /backup/restore` validates the document first, then
  performs a replace-all that preserves original ids and timestamps;
  depreciation schedules are recomputed rather than trusted from the document.
- **Clear** - `POST /backup/clear` deletes all of the user's DynamoDB records and
  their S3 binaries (property photos and transaction receipts), S3-first and
  best-effort.
- **Profile "Backup & restore" section** with four flows - download a JSON
  backup, restore from a backup file, clear all data, and load sample data (no
  new nav entry).
- **Bundled sample dataset** (`frontend/src/data/sample-backup.json`) - two
  properties with five years of Schedule E data, powering "Load sample data".
- Full property-based (Hypothesis / fast-check), integration, and UI test
  coverage for the new feature.

### Changed

- `make deploy-infra` now runs `sam deploy` non-interactively
  (`--no-confirm-changeset --no-fail-on-empty-changeset`) so `make deploy` runs
  unattended.
- Documentation updated across the README and `docs/` (API reference,
  architecture, data model, and developer guide).

## [1.0.0] - 2026-09-26

The initial public release.

### Added

- Serverless AWS application for preparing an IRS Schedule E (Form 1040) rental
  tax return: a React + Vite + TypeScript SPA (S3 + CloudFront) and a single
  Python 3.12 Lambda behind API Gateway with a Cognito JWT authorizer, over a
  single-table DynamoDB design with binary files in S3.
- Properties, transactions (year-end Schedule E totals), depreciable assets with
  straight-line depreciation schedules, usage days, receipts / supporting
  documents, and per-property plus combined Schedule E reports.
- RentCast property enrichment (optional, persisted) and Amazon Location Service
  address autocomplete.
- UX polish and data visualizations; light / dark / system theming.

[1.1.0]: https://gitlab.com/carnaghan/logstead/-/compare/v1.0.0...v1.1.0
[1.0.0]: https://gitlab.com/carnaghan/logstead/-/tags/v1.0.0
