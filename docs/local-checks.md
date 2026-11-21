# Local checks

The project has no hosted CI, to stay off paid GitLab compute minutes. Run these
checks on your machine before merging. Nothing here deploys.

## One-time setup

```sh
make install                      # backend/.venv (with dev extras) + frontend npm deps
cd frontend && npm run e2e:install   # Chromium for Playwright (only for browser checks)
pipx install cfn-lint pip-audit   # or: python3 -m pip install --user cfn-lint pip-audit
```

`make build` (and so `make deploy` and `make deploy-preview`) deletes
`backend/.venv`, a workaround for iCloud corrupting it when the repo sits in a
synced folder. Run `make install-backend` again before the backend checks after
a deploy. `make deploy` also reinstalls `frontend/node_modules` with `npm ci`.

For cfn-guard, download the 3.2.1 release binary for your platform from
[cloudformation-guard releases](https://github.com/aws-cloudformation/cloudformation-guard/releases)
(macOS Apple silicon: `cfn-guard-v3-aarch64-macos-latest.tar.gz`), extract it and
put `cfn-guard` on your `PATH`.

## Before every merge

Run from the repository root.

| Area | Command | Time (M-series Mac) |
| --- | --- | --- |
| Frontend types | `cd frontend && npx tsc -b` | < 1 min |
| Frontend lint | `cd frontend && npm run lint` | < 1 min |
| Frontend tests | `cd frontend && npx vitest run` | about 1.5 min |
| Frontend build | `cd frontend && npm run build` | < 1 min |
| Backend tests (quick) | `cd backend && HYPOTHESIS_PROFILE=quick HYPOTHESIS_MAX_EXAMPLES=15 .venv/bin/python -m pytest -q -n auto` | about 3 min |
| Infra lint | `cfn-lint infra/template.yaml` | seconds |
| Infra policy | `cfn-guard validate -d infra/template.yaml -r infra/guard/rules.guard --show-summary fail` | seconds |

The quick backend run caps every property test at 15 deterministic examples
(see `backend/tests/conftest.py`), so it catches regressions fast without the
full search.

## Before merging backend changes, and about weekly

```sh
cd backend && .venv/bin/python -m pytest -q -n auto      # full example counts, about 15 min
```

Hypothesis keeps failing examples in `backend/.hypothesis/` and replays them on
the next run. The two long-standing intermittent failures (the loan payoff
round trip and the Schedule E extraction money test) were generator bugs and
are fixed, so the full run is expected to pass. Treat any failure as new. If
one only reproduces from a stored example, `make clean` removes `.hypothesis/`.

## Dependency audits (weekly, and before a deploy)

```sh
cd frontend && npm audit --omit=dev --audit-level=high
pip-audit -r backend/requirements.txt
```

## Browser checks (before UI changes merge)

```sh
cd frontend && npm run e2e
```

Playwright starts a local Vite server with the API mocked. The specs are
`a11y.spec.ts` (axe on every route in light and dark, with real colour
contrast), `responsive.spec.ts` (320 to 1280px), `palette.spec.ts` (palette,
shortcuts and search), `sidebar-guard.spec.ts`, `onboarding.spec.ts`,
`activity.spec.ts`, and `smoke.spec.ts` (PKCE sign-in, create property, add
transaction, delete with Undo, restore from Activity, accountant package). No
AWS calls are made. Each test retries once locally (twice with `CI` set), so a
test that passes on retry is reported as flaky rather than failed. Look into
any test that is flaky on every run.

## Before a deploy

```sh
make deploy-preview     # builds (Docker required) and prints the change set without applying it
```

Check the change set for `Replacement: True` and for `UserPoolClient` changes
(see the `IdentityProviders` parameter in `infra/template.yaml`), then
`make deploy`.

## Infrastructure policy rules (cfn-guard)

`infra/guard/rules.guard` encodes the template hardening decisions: S3 buckets
block public access and are encrypted; bucket CORS has no `"*"` origin or
header; IAM statements have no Action `"*"` and no Resource `"*"` (except the
documented Textract exception, which has no resource types); the Lambda has
reserved concurrency; CloudFront behaviors use a response headers policy and
HTTPS-only viewers; log groups have retention. The rules run on the raw SAM
template, so they target `AWS::Serverless::Function` `Policies` as well as
native resource types. See the comments in the rules file for details.

If you change the template in a way that breaks a rule on purpose, update the
rule and document the exception in the rules file and in
`.kiro/specs/security-and-refactor-backlog/review.md`.

## Dependency update merge requests

If Renovate is installed, its merge requests are not tested automatically.
Check out the branch and run the "Before every merge" checks (plus the audits)
before merging.

## Restoring hosted CI

A GitLab pipeline that ran these same checks was removed in favour of local
runs. It is in git history (`git log --all -- .gitlab-ci.yml`) if you want it
back, for example on a self-hosted runner, which does not use GitLab compute
minutes.
