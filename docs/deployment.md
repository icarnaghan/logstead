# Deployment

Logstead deploys to AWS with an **AWS SAM** template. All infrastructure lives
in the **`infra/`** directory:

```
infra/
  template.yaml            SAM template for the whole stack
  samconfig.toml.example   Deploy-config template (copy to samconfig.toml)
  samconfig.toml           Your deploy config - gitignored (account id, cert, domain)
  deploy-spa.sh            Build + publish the SPA and invalidate CloudFront
  seed-categories.sh       Seed the Schedule E category catalog
```

`samconfig.toml` is **gitignored** because it holds account-specific values
(AWS account id, ACM certificate ARN, custom domain). Copy the checked-in
template and fill in your own values before the first deploy:

```bash
cp infra/samconfig.toml.example infra/samconfig.toml
# then edit infra/samconfig.toml (or drop the domain overrides for a
# default, no-custom-domain deploy)
```

Target region: **us-east-1**.

## What the template provisions

`infra/template.yaml` defines:

- **DynamoDB** table `Logstead` (single-table design), pay-per-request, with
  **GSI1** and **GSI2** (keyed on `GSI1PK/GSI1SK` and `GSI2PK/GSI2SK`), matching
  the key scheme in `backend/src/logstead/repository/keys.py`.
- **S3 files bucket** (photos, receipts, uploaded PDFs, exports) with CORS and
  lifecycle rules; private, encrypted, accessed via pre-signed URLs.
- **S3 SPA bucket** + **CloudFront** distribution, with 403/404 responses
  rewritten to `/index.html` for client-side routing, served via an Origin
  Access Control (the bucket stays private).
- **Cognito** User Pool + Hosted UI app client (Authorization Code + PKCE,
  Cognito domain, SPA callback/logout URLs). Admin-create-only (single-user app).
- **API Gateway HTTP API** with a **native Cognito JWT authorizer**. All routes
  use the authorizer except `GET /categories`, which is explicitly public.
- **Python 3.12 Lambda** (`logstead.router.handler.handler`) with env config and
  least-privilege DynamoDB + S3 policies.
- **Package worker Lambda** (`logstead-package-worker`) that builds accountant
  package ZIPs. See [Accountant package worker](#accountant-package-worker).
- A **CloudWatch alarm** (`logstead-package-worker-errors`) on the worker's
  `Errors` metric.
- **Route throttles** on the HTTP API stage: a default rate plus tighter limits
  on expensive routes, including `POST /accountant-packages` (rate 1), the two
  report PDF routes (rate 2) and `GET /search` (rate 2, burst 5). See
  `RouteSettings` in `infra/template.yaml`.
- **Reserved concurrency** of 10 on the API function and 2 on the worker.

## Parameters

| Parameter | Default | Purpose |
| --- | --- | --- |
| `DomainName` | (empty) | SPA custom domain (CloudFront alias + Cognito URLs) |
| `CertificateArn` | (empty) | ACM cert ARN in us-east-1 covering the domain |
| `UseCustomDomain` | `false` | Attach the domain + cert to CloudFront |
| `AllowedSpaOrigin` | (empty) | Origin allowed by the files-bucket CORS when `UseCustomDomain=false` (e.g. `https://d111111abcdef8.cloudfront.net`). Blank allows only `http://localhost:5173` |
| `CognitoDomainPrefix` | `logstead-auth` | Globally-unique Hosted UI domain prefix |
| `RentCastApiKeyParam` | `/logstead/rentcast-api-key` | Name of an SSM SecureString holding the RentCast key (optional; enrichment 503s if unset) |

Defaults live in `infra/samconfig.toml`, so `sam deploy` needs no flags for a
basic (no-custom-domain) deploy.

> Custom domain note: the custom domain on CloudFront requires an **ACM certificate
> in us-east-1** for the domain and a DNS record (Route 53 alias or CNAME)
> pointing the domain at the CloudFront distribution. Request/validate the cert
> first, then deploy with `UseCustomDomain=true` and `CertificateArn=<arn>`, then
> create the DNS record from the `CloudFrontDomain` output.

## Prerequisites

- AWS CLI configured for the target account (`aws configure`), region us-east-1.
- AWS SAM CLI (`sam --version`).
- **A build path for Python 3.12** (the Lambda runtime). Either:
  - install Python 3.12 locally (e.g. `mise install python@3.12` or Homebrew)
    and build natively, **or**
  - build in a container with `sam build --use-container` (requires Docker
    running) - no local 3.12 needed. This is what `make deploy` and the
    `deploy:infra` npm script use.
- Node 18+ for the SPA.

## One-command deploy (Makefile)

The top-level `Makefile` wraps the whole flow (run `make help` for everything):

```bash
make deploy         # build + deploy infra (SAM), then build + publish the SPA
# or the halves:
make deploy-infra   # sam build --use-container + sam deploy
make deploy-spa     # build SPA, sync to S3, invalidate CloudFront
make validate       # sam validate --lint
make outputs        # show stack outputs
make seed           # seed the category catalog
make create-user EMAIL=you@example.com
```

`make deploy-infra`/`make build` first delete iCloud `* 2.*` duplicate files
(outside `node_modules`) and the backend venv, which break `sam build` when the
repo sits in an iCloud-synced folder. Both steps are harmless elsewhere. Because
the venv is deleted, run `make install-backend` before backend tests after a
deploy.

`make deploy-spa` runs `infra/deploy-spa.sh`, which installs the frontend with
`npm ci` and then runs `npm run build`. `npm ci` deletes `node_modules` and
reinstalls exactly what `package-lock.json` lists, so every deploy builds from
a clean dependency tree. `make install-frontend` runs `npm install`, which keeps
any extra folders already in `node_modules`.

## One-command deploy (from frontend/)

npm scripts wrap the whole flow:

```bash
cd frontend
npm run deploy          # infra (sam build --use-container + deploy) then SPA
# or run the halves separately:
npm run deploy:infra    # sam build --use-container + sam deploy
npm run deploy:spa      # build SPA, sync to S3, invalidate CloudFront
```

## Manual deploy (from infra/)

```bash
cd infra
sam validate --lint --region us-east-1     # optional sanity check
sam build --use-container                  # or plain: sam build (needs local py3.12)
sam deploy                                 # uses samconfig.toml defaults
```

For a custom domain, override the parameters:

```bash
sam deploy --parameter-overrides \
  UseCustomDomain=true \
  DomainName=app.example.com \
  CertificateArn=arn:aws:acm:us-east-1:<acct>:certificate/<id> \
  CognitoDomainPrefix=logstead-auth
```

### RentCast API key (secret handling)

The RentCast key is a secret, so it is **not** a template parameter or a
plaintext Lambda env var. Store it once in an SSM SecureString parameter; the
Lambda reads and decrypts it at runtime, and deploys only pass the parameter
*name* (`RentCastApiKeyParam`, already set in `infra/samconfig.toml`):

```bash
aws ssm put-parameter --name /logstead/rentcast-api-key --type SecureString \
  --value "<your-rentcast-key>" --region us-east-1
```

To rotate the key, `put-parameter ... --overwrite` — no redeploy needed (the
Lambda reads the current value per container). Leave `RentCastApiKeyParam` empty
to run without enrichment. Address autocomplete needs no key (Amazon Location
via the Lambda's IAM role).

## Deploy the frontend

`infra/deploy-spa.sh` (invoked by `make deploy-spa` and `npm run deploy:spa`)
reads the stack outputs, writes `frontend/.env.production`, runs `npm ci` and
`npm run build`, syncs `dist/` to the SPA
bucket, and invalidates CloudFront. To do it by hand, read the outputs:

```bash
aws cloudformation describe-stacks --stack-name logstead --region us-east-1 \
  --query "Stacks[0].Outputs" --output table
```

Use `ApiBaseUrl`, `UserPoolClientId`, and `CognitoHostedUiDomain` for the
`VITE_*` values (see [Developer guide](developer-guide.md)). If you deploy
without a custom domain, use the `CloudFrontDomain` output as the app origin and
make sure the Cognito app client callback/logout URLs match.

### Files-bucket CORS (two-step first deploy without a custom domain)

The files bucket never allows `*`. It allows only `Content-Type` and the
`GET/PUT/HEAD` methods, from one origin: `https://<DomainName>` when
`UseCustomDomain=true`, otherwise `AllowedSpaOrigin`, otherwise
`http://localhost:5173`. The CloudFront domain cannot be referenced from the
bucket (circular dependency through the CSP policy), so:

1. Run `sam deploy` with `AllowedSpaOrigin` unset.
2. Read the `CloudFrontDomain` output, add
   `AllowedSpaOrigin=\"https://<id>.cloudfront.net\"` to `parameter_overrides`
   in `infra/samconfig.toml`, and run `sam deploy` again.

Until step 2, photo/receipt uploads from the deployed SPA fail the CORS check.
With a custom domain, set `DomainName` and no second step is needed.

## Accountant package worker

`PackageWorkerFunction` (`logstead-package-worker`) builds the accountant
package ZIP outside the API's 30 second integration limit and 6 MB response
limit. It uses the same source as the API function (`CodeUri: ../backend/`) and
the same makefile build (`build-PackageWorkerFunction` in `backend/Makefile`),
with handler `logstead.worker.package_worker.handler`. The API function starts
it with an asynchronous invoke; its name reaches the API through the
`PACKAGE_WORKER_FUNCTION` environment variable.

| Setting | Value |
| --- | --- |
| Timeout | 600 seconds |
| Memory | 1024 MB |
| Ephemeral storage | 1024 MB |
| Reserved concurrency | 2 |
| Async retries | 0 (`MaximumRetryAttempts: 0`), max event age 300 seconds |
| Environment | `TABLE_NAME`, `FILES_BUCKET` |

There are no retries because a failed build marks the job failed and the user
starts a new one, so a retry would only repeat the failure.

### IAM

Worker role (inline statements in the template):

- `TableReadJobWrite`: `dynamodb:GetItem`, `Query`, `PutItem` on the table and
  its indexes. No delete, update, scan, or batch actions.
- `ReadReceipts`: `s3:GetObject` on `receipts/*`. There is no `ListBucket`, so
  a missing receipt is a skipped entry, not an error.
- `WritePackage`: `s3:PutObject` and `s3:AbortMultipartUpload` on
  `exports/packages/*`.

API function additions:

- `InvokePackageWorker`: `lambda:InvokeFunction` on the worker only.
- `s3:DeleteObject` on `exports/packages/*` and `exports/pdf/*`, so a user can
  delete a finished package and the generated PDFs beside it.

### Lifecycle rules

The files bucket is versioned. Two rules were added to the existing ones:

| Rule | Prefix | Current version | Noncurrent version |
| --- | --- | --- | --- |
| `ExpireAccountantPackages` | `exports/packages/` | expires after 1 day | expires after 1 day |
| `ExpireGeneratedPdfs` | `exports/pdf/` | expires after 1 day | expires after 1 day |

Download links last 15 minutes. These prefixes also match the existing 30-day
`ExpireExports` rule; the shorter expiry governs. The older rules are
unchanged (see [Future improvements](future-improvements.md)).

### Package size

The unzipped Lambda runtime dependencies (`pip install --target`, manylinux2014
x86_64, Python 3.12, application source excluded) measured 98,212 KiB
(95.9 MiB) before and 107,304 KiB (104.8 MiB) after adding `reportlab==5.1.0`,
an increase of about 8.9 MiB. This is well under the 250 MB unzipped Lambda
limit. See [Dependency policy](dependency-policy.md).

### Deploy-time notes

- **Concurrency quota.** The worker's reserved concurrency of 2 counts against
  the account's unreserved Lambda concurrency pool (the API function reserves
  10 more). Lambda always keeps 100 executions unreserved, so a new or
  low-limit account (default limit 10 on some accounts) can fail the deploy on
  the reservation. If a deployment is blocked by the account's Lambda
  concurrency limit, request a Lambda concurrency quota increase through
  Service Quotas. Do not lower the reservation to work around it.
- **Order of resources.** `sam build` builds both functions; the API function
  references the worker, so CloudFormation creates the worker first.
- **Alarm.** `logstead-package-worker-errors` fires on worker function errors.

## Seed reference data (categories)

The Schedule E **category catalog** is reference data the app reads via
`GET /categories`. A freshly deployed table is empty, so this must be seeded
once per environment or the category dropdowns will be blank. It is idempotent
(categories use fixed IDs), so re-running it is safe.

```bash
cd frontend
npm run seed:categories        # wraps infra/seed-categories.sh
# or directly:
infra/seed-categories.sh logstead us-east-1
```

Re-seed whenever the table is recreated (e.g. a fresh environment or after
deleting the DynamoDB table).

## Create the first user

Sign-up is admin-only:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId output> \
  --username you@example.com \
  --region us-east-1
```

## Verify after deploy

- `GET <ApiBaseUrl>/categories` responds **without** auth and returns the
  seeded catalog (16 entries). An empty `[]` means categories were not seeded.
- Any other route returns **401** without a valid token.
- Sign in through the Hosted UI, then create a property, add a transaction, and
  generate a report to exercise the DynamoDB and S3 paths end to end.

## Runtime configuration reference

Lambda environment variables (set by the template):

| Variable | Source |
| --- | --- |
| `TABLE_NAME` | `Logstead` table ref |
| `FILES_BUCKET` | files bucket ref |
| `RENTCAST_API_KEY_PARAM` | `RentCastApiKeyParam` (SSM SecureString name; value read + decrypted at runtime) |
| `PACKAGE_WORKER_FUNCTION` | Package worker function name (API function only) |

Address lookup uses Amazon Location Service (`geo-places`) via the Lambda's IAM
role - no API key. The template grants both `geo-places:Autocomplete` (candidate
buildings as the user types) and `geo-places:Geocode` (a selected building's
secondary addresses / units, via the `SecondaryAddresses` feature).

`AWS_REGION` is provided by the Lambda runtime automatically.
