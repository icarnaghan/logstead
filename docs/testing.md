# Testing Guide

Logstead has test suites for both the backend and the frontend. All tests run
locally with no AWS account: external services and AWS resources are faked.

## Backend

Backend tests use **pytest** with **Hypothesis** (property-based testing),
**moto** (mocked AWS), and **pytest-xdist** (parallel execution).

### Running

```bash
cd backend
source .venv/bin/activate
pytest -q -n auto            # parallel; -n auto uses all cores
```

To run a subset, target a directory or file:

```bash
pytest -q tests/services
pytest -q tests/router/test_handler.py
```

### Layout

Tests under `backend/tests/` mirror the package layers:

| Directory | Focus |
| --- | --- |
| `services/` | Business-logic unit and property-based tests |
| `adapters/` | External integrations (RentCast, autocomplete, S3 files) |
| `repository/` | DynamoDB single-table access and the key scheme |
| `router/` | HTTP routing, request parsing, and result -> HTTP mapping |
| `integration/` | End-to-end flows across layers |
| `util/` | Shared helpers |

### Test styles

- **Unit tests** exercise a single service or function with fakes injected via
  the router `configure(...)` / `reset_wiring()` seams.
- **Property-based tests (Hypothesis)** assert invariants across generated
  inputs - for example, that money round-trips exactly as two-decimal strings,
  that depreciation schedules sum correctly, and that reports are reproducible
  from persisted data.
- **Integration tests** wire the layers together (with moto-backed DynamoDB/S3)
  to check whole flows such as import -> draft -> confirm -> report.

### What the tests protect

The suites encode the core invariants:

- Money stays exact (`decimal.Decimal`, two-decimal strings; no floats/Number).
- Reports are reproducible from persisted records.
- Property creation succeeds even when RentCast is unavailable.
- Drafts remain separate from transactions until confirmed.
- Result-to-HTTP status mapping is correct (see [API reference](api.md)).

## Frontend

Frontend tests use **vitest** with the React Testing Library setup under
`frontend/src/test/`.

### Running

```bash
cd frontend
npm test          # vitest run
npm run build     # tsc -b + vite build; must exit 0
npm run lint      # tsc --noEmit type-check
```

Component and page tests live alongside the code they cover (for example
`App.test.tsx`, `components/AppLayout.test.tsx`). The production build
(`npm run build`) doubles as a type-check gate and must exit cleanly; remove the
generated `dist/` directory afterward if you are only verifying.

## Adding tests with changes

When you change behavior, add or update tests in the same layer. Prefer a
property-based test when asserting an invariant over many inputs, and an
integration test when a change spans multiple layers.
