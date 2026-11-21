# Dependency policy

## Python (backend)

- `backend/requirements.txt` (runtime): direct dependencies are pinned exactly with `==`. Transitive dependencies are not locked; no lock file is kept, to keep the repo light.
- `backend/requirements-dev.txt` (test tooling): unpinned, with `-r requirements.txt` so tests run against the pinned runtime versions.
- Upgrading: bump the pin, run `cd backend && pytest -q`, then audit.
- Audit: in a throwaway venv, `pip install -r backend/requirements-dev.txt pip-audit && pip-audit -r backend/requirements-dev.txt`. Fix any finding by raising the pin to the minimum safe version.
- Last audit: no known vulnerabilities (pins: boto3 1.44.3, pdfplumber 0.11.10, pypdf 7.1.0, reportlab 5.1.0). `pip-audit -r backend/requirements.txt` reported "No known vulnerabilities found" after adding `reportlab`.
- `reportlab==5.1.0` (BSD license) renders the Schedule E PDF and the accountant package. Its dependencies, `pillow` and `charset-normalizer`, are already installed through `pdfplumber` (`pillow` directly, `charset-normalizer` through `pdfminer.six`), so the dry-run install adds only `reportlab` as a new package.
- `backend/requirements.txt` (exact pin) and `backend/pyproject.toml` (unpinned `reportlab`, which the SAM makefile build installs from) must change together. Adding or bumping a dependency in one file without the other is a defect.
- Measured size (also recorded in `docs/deployment.md`): unzipped install target for the Lambda runtime dependencies (`pip install --target`, manylinux2014 x86_64, Python 3.12) was 98,212 KiB (95.9 MiB) before and 107,304 KiB (104.8 MiB) after adding `reportlab`, an increase of about 8.9 MiB, well under the 250 MB unzipped Lambda limit. The figure excludes the application source.

## npm (frontend)

- Versions are locked by the committed `package-lock.json`; install with `npm ci` for a clean, lock-exact install. `make deploy` (through `infra/deploy-spa.sh`) always uses `npm ci`. `make install-frontend` uses `npm install`, which can leave extra folders in `node_modules`; run `npm ci` if the build reports unexpected type definitions.
- Audit runtime dependencies with `npm audit --omit=dev`.
- Upgrade deliberately and commit the lock file change with the `package.json` change.
- Lint with `npm run lint` (ESLint 9 flat config in `frontend/eslint.config.js`: typescript-eslint, react-hooks, jsx-a11y, plus security rules `no-eval`, `no-implied-eval`, `no-new-func`, `react/no-danger`, `react/jsx-no-target-blank`). Type-check separately with `npm run typecheck`. ESLint packages are pinned exactly.
## Version-range policy
- Python runtime (`backend/requirements.txt`): exact `==` pins. Python dev tooling (`backend/requirements-dev.txt`): unpinned; Renovate ignores that file.
- npm (`frontend/package.json`): exact versions for both `dependencies` and `devDependencies` (no `^` or `~`). Exact pins plus the committed lock file make installs reproducible and make every upgrade a reviewable PR. Several entries still carry `^` ranges; Renovate's `rangeStrategy: "pin"` converts them to exact versions in its first grouped PR.
- Upgrades arrive through Renovate (`renovate.json`): weekly (before 6am Monday), minor and patch grouped per ecosystem, each major in its own PR, vulnerability alerts raised immediately, automerge off. There is no hosted CI, so run the
  [local checks](local-checks.md) on a Renovate branch before merging it.

## Enabling Renovate on GitLab (manual step)
`renovate.json` does nothing until a Renovate runner is set up. Choose one:
1. **Mend Renovate app**: install it for the `carnaghan/logstead` project from the Mend Renovate GitLab integration (the hosted option; no pipeline to maintain).
2. **Self-hosted**: add a project access token (scopes `api`, `write_repository`) as the CI/CD variable `RENOVATE_TOKEN`, optionally a GitHub token as `GITHUB_COM_TOKEN` to avoid API rate limits, and create a pipeline schedule that runs the `renovate/renovate` image with `RENOVATE_PLATFORM=gitlab` and `RENOVATE_REPOSITORIES=carnaghan/logstead`. Alternatively use the official Renovate GitLab CI include. Run it at least weekly.

The `github` mirror remote is not used by Renovate. Validate config changes with `npx --yes --package renovate renovate-config-validator`.
