# Implementation Plan: Security and Refactor Backlog

Source: review.md in this folder. Ordered by priority. Each task names the finding it addresses.

## Overview

Backlog from the security and best-practices review in review.md. Items marked P0 should land before the next production deploy. Section 4 is an audit of code the review did not cover, so its results may add tasks.

## Tasks

- [x] 1. P0 - Browser hardening
  - [x] 1.1 Add a CloudFront response headers policy
    - CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors none.
    - The theme bootstrap script in index.html is inline; give it a hash or move it to a file.
    - _Addresses: S1_
  - [x] 1.2 Stop persisting the refresh token and decide on renewal
    - Remove refresh token storage from session.ts and auth.ts unless renewal is implemented deliberately; test that no refresh token reaches storage.
    - _Addresses: S2, S3_
  - [x] 1.3 Audit apiClient for token leakage
    - Ignore or reject absolute URLs, send the bearer only to the configured API origin, add tests.
    - _Addresses: R12_

- [x] 2. P0 - API abuse and cost controls
  - [x] 2.1 Add API throttling
    - Stage default plus stricter per-route limits on autocomplete, enrichment and extraction.
    - _Addresses: S4_
  - [x] 2.2 Review public /categories access
    - Keep public only if intended; add caching headers and throttling.
    - _Addresses: S4_
  - [x] 2.3 Add budget and usage alarms for RentCast, Location and Textract
    - _Addresses: S4_
  - [x] 2.4 Write a decision note on AWS WAF for CloudFront and the API
    - _Addresses: S4_

- [x] 3. P1 - Infrastructure least privilege
  - [x] 3.1 Scope IAM actions and resources in infra/template.yaml
    - Re-check each wildcard resource (textract, geo-places) and tighten where the service allows.
    - _Addresses: S5_
  - [x] 3.2 Remove the wildcard S3 CORS fallback for production
    - Require DomainName for non-dev deploys and narrow AllowedHeaders.
    - _Addresses: S6_
  - [x] 3.3 Run cfn-lint and cfn-guard against the template in CI
    - _Addresses: S5, S6_

- [x] 4. P1 - Backend audit (not yet reviewed)
  - [x] 4.1 Audit authorization on every route
    - Confirm each handler scopes data by the JWT subject and rejects cross-user IDs; add tests per resource type.
  - [x] 4.2 Audit input validation and error responses
    - Money, dates, string lengths, enums; no internals in error bodies.
  - [x] 4.3 Audit presigned upload creation
    - Pin content type, size limit and per-user key prefix; sanitize filenames.
    - _Addresses: S8_
  - [x] 4.4 Audit logging for sensitive data
    - No tokens, full financial payloads or addresses in logs.
  - [x] 4.5 Run pip-audit and settle a pinning policy for requirements files
    - _Addresses: R2_

- [x] 5. P1 - Tooling and CI
  - [x] 5.1 Add ESLint (typescript-eslint, react-hooks, jsx-a11y, a security plugin)
    - Ban dangerouslySetInnerHTML, eval and new Function; require rel noopener noreferrer with target blank.
    - _Addresses: R1, S7_
  - [x] 5.2 Add CI steps: install, tsc -b, lint, test, build, npm audit --omit=dev
    - _Addresses: R1, R2_
  - [x] 5.3 Add Dependabot or Renovate and a version-range policy
    - _Addresses: R2_
  - [x] 5.4 Move shared jsdom polyfills and storage stubs into the vitest setup file
    - _Addresses: R7_
  - [x] 5.5 Confirm .gitignore covers .hypothesis, .pytest_cache, .aws-sam, dist and tsbuildinfo files; purge any duplicate files with " 2" in the name
    - _Addresses: R9_

- [x] 6. P2 - Frontend refactors
  - [x] 6.1 Extract useAsyncResource and migrate pages off hand-rolled load state
    - Abort, retry, refreshing and reset keys built in; migrate Properties, Businesses, Transactions, Assets, Loans, Reports, Carryforward and detail pages.
    - _Addresses: R3_
  - [x] 6.2 Split CarryforwardPage into a feature folder
    - _Addresses: R4_
  - [x] 6.3 Split PropertyDetailPage and AssetsPage the same way
    - _Addresses: R4_
  - [x] 6.4 Rework ResponsiveTable to render a single layout
    - Remove duplicated DOM and the useId workarounds; update table tests.
    - _Addresses: R5_
  - [x] 6.5 Add a top-level error boundary with safe messaging
    - _Addresses: R10_
  - [x] 6.6 Document and test Undo ID changes (links, imports, receipts)
    - _Addresses: R11_

- [x] 7. P2 - Test quality
  - [x] 7.1 Add Playwright and axe checks for key routes in both themes (real contrast)
    - _Addresses: R8_
  - [x] 7.2 Replace source-scan class-contract tests with rendered assertions or lint rules where feasible
    - _Addresses: R6_
  - [x] 7.3 Add an e2e smoke test: sign-in callback, create property, add transaction, delete with Undo
    - _Addresses: S10, R11_

- [x] 8. Checkpoint - re-run the review
  - Update finding statuses, run the full suite, npm audit, build, and a manual response-header check.

## Notes

- Review scope was targeted, not exhaustive. See review.md for what was and was not read.
- No finding here was confirmed as exploited; they are hardening and hygiene items.
- Task 1.1 (CSP) can break the app if inline scripts or third-party origins are missed; test in a staging deploy first.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "2.4", "3.1", "3.2", "4.1", "4.2", "4.3", "4.4", "4.5", "5.1", "5.4", "5.5"] },
    { "id": 1, "tasks": ["3.3", "5.2", "5.3", "6.1", "6.5", "7.2"] },
    { "id": 2, "tasks": ["6.2", "6.3", "6.4", "6.6", "7.1"] },
    { "id": 3, "tasks": ["7.3"] },
    { "id": 4, "tasks": ["8"] }
  ]
}
```
