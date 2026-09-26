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

## Parameters

| Parameter | Default | Purpose |
| --- | --- | --- |
| `DomainName` | (empty) | SPA custom domain (CloudFront alias + Cognito URLs) |
| `CertificateArn` | (empty) | ACM cert ARN in us-east-1 covering the domain |
| `UseCustomDomain` | `false` | Attach the domain + cert to CloudFront |
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
    running) - no local 3.12 needed. This is what the `deploy:infra` npm script
    uses by default.
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

`make deploy-infra`/`make build` automatically clear iCloud `* 2.*` duplicate
files and the backend venv first (both otherwise break `sam build`).

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

`infra/deploy-spa.sh` (invoked by `npm run deploy:spa`) reads the stack outputs,
writes `frontend/.env.production`, builds the SPA, syncs `dist/` to the SPA
bucket, and invalidates CloudFront. To do it by hand, read the outputs:

```bash
aws cloudformation describe-stacks --stack-name logstead --region us-east-1 \
  --query "Stacks[0].Outputs" --output table
```

Use `ApiBaseUrl`, `UserPoolClientId`, and `CognitoHostedUiDomain` for the
`VITE_*` values (see [Developer guide](developer-guide.md)). If you deploy
without a custom domain, use the `CloudFrontDomain` output as the app origin and
make sure the Cognito app client callback/logout URLs match.

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

Address lookup uses Amazon Location Service (`geo-places`) via the Lambda's IAM
role - no API key. The template grants both `geo-places:Autocomplete` (candidate
buildings as the user types) and `geo-places:Geocode` (a selected building's
secondary addresses / units, via the `SecondaryAddresses` feature).

`AWS_REGION` is provided by the Lambda runtime automatically.
