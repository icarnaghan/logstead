# Decision: AWS WAF for CloudFront and the API

Status: Proposed
Source: `.kiro/specs/security-and-refactor-backlog/review.md` S4, task 2.4

## Context

- Logstead is a single-user app. Cognito sign-up is admin-only, so no one can self-register.
- The API is an API Gateway **HTTP API** (`HttpApi` in `infra/template.yaml`). The browser calls its `execute-api` URL directly. CloudFront (`SpaDistribution`) serves only the static SPA.
- A Cognito JWT authorizer protects every route except `GET /categories` (public reference data) and `OPTIONS` (CORS preflight).
- Authenticated requests can trigger paid third-party calls, so abusive volume costs money. Unauthenticated callers can only reach `GET /categories`, preflight, and the authorizer's 401 path.
- Existing controls: CloudWatch alarms for Lambda errors, Lambda throttles, and API 5xx.

## Constraint: WAF and HTTP APIs

AWS WAF cannot be attached directly to an API Gateway HTTP API. AWS documents the protected resource types as CloudFront distributions, API Gateway **REST** APIs, Application Load Balancers, AppSync GraphQL APIs, Cognito user pools, App Runner services, Amplify applications, and Verified Access instances ([AWS WAF API reference](https://docs.aws.amazon.com/waf/latest/APIReference/Welcome.html)). AWS's own guidance states that WAF supports only API Gateway REST APIs ([AWS re:Post knowledge center](https://www.repost.aws/ja/knowledge-center/configure-api-gateway-rest-api)). An AWS re:Post answer says the same for HTTP APIs and gives the workaround of putting CloudFront in front ([re:Post](https://repost.aws/questions/QU0KcwRPu5RtSRacksUblkKA/protect-and-secure-http-api-gw)).

Some 2026 third-party posts claim WAF now works on HTTP APIs. I did not find this in the AWS documentation, so this note treats it as unconfirmed. Re-check before relying on either claim.

A CloudFront web ACL must be created in us-east-1 ([AWS WAF developer guide](https://docs.aws.amazon.com/waf/latest/developerguide/how-aws-waf-works-resources.html)).

So "WAF on both" means one of two things:

1. Migrate the API from HTTP API to REST API, then attach a regional web ACL. This is a larger change and gives up the cheaper HTTP API pricing.
2. Put the API behind CloudFront (a second origin or a second distribution), attach the CloudFront web ACL, and lock the HTTP API to CloudFront traffic. The `execute-api` URL stays public unless a secret origin header is checked, which the JWT authorizer does not do. Without that check, WAF can be bypassed.

## Options

### A. No WAF, API Gateway throttling plus alarms

- Set default stage throttling (rate and burst) on the HTTP API, and per-route limits on any route that triggers paid calls.
- Cap Lambda reserved concurrency so a flood cannot run up unbounded cost.
- Add a request-count alarm on `AWS/ApiGateway` `Count`, and an AWS Budgets alert.
- Covers: cost and availability abuse. Does not cover: IP reputation, managed rule groups, or per-IP rate limits (throttling is per account/stage/route, not per client).

### B. WAF on CloudFront only

- Protects the SPA distribution. The SPA is static and public by design, so there is little to attack. The API is not covered, because the browser calls it directly.
- Adds cost and a us-east-1 resource for little risk reduction.

### C. WAF on CloudFront and the API

- Gives per-IP rate-based rules and managed rule groups on both surfaces.
- Requires option 1 or 2 above, plus an origin-lock mechanism, plus CORS, CSP `connect-src`, and Cognito callback URL changes (the CSP currently uses a wildcard on `execute-api`).
- Largest change and highest ongoing cost, for a single-user app.

## Rough monthly cost

Prices from the [AWS WAF pricing page](https://aws.amazon.com/waf/pricing/). The page did not render in my fetch, so the figures below come from secondary sources that quote it: $5 per web ACL per month, $1 per rule per month, and $0.60 per million requests inspected, all prorated hourly ([example](https://hykell.com/knowledge-base/aws-waf-pricing-and-cost-management/)). Managed rule groups and Bot Control cost extra. Confirm against the pricing page before committing.

Assuming a single user, well under 1 million requests per month, and about 3 rules (one rate-based rule, two managed rule groups at their listed price, which varies):

| Option | Estimate | Notes |
| --- | --- | --- |
| A. Throttling and alarms | about $0 | CloudWatch alarms and a Budgets alert fall in or near the free tier. |
| B. WAF on CloudFront | about $8 | $5 ACL, about $3 rules, under $1 requests. |
| C. WAF on both | about $16 plus migration | Two ACLs. Option 2 may avoid a second ACL (one ACL on the shared distribution, about $8) but adds a CloudFront origin for the API. |

For comparison, the app's own running cost for one user is likely a few dollars per month, so WAF would at least double it.

## Recommendation

Choose **A: no WAF now**. Implement:

1. Stage-level default throttling on `HttpApi`, with lower per-route limits on routes that call paid third-party services.
2. Reserved concurrency on the API Lambda.
3. A request-count alarm and an AWS Budgets alert, alongside the existing error, throttle, and 5xx alarms.

Rationale: the attack surface is small (admin-only sign-up, JWT on nearly every route), the unauthenticated surface is one cheap read, and WAF cannot protect the HTTP API without either an API migration or a CloudFront front with origin locking. Option B costs money without covering the API.

Revisit and move to the CloudFront-fronted API (option C, variant 2) if any of these happen: public sign-up is enabled, more public routes are added, the app serves multiple users, or alarms show abusive traffic.

## Follow-ups

- Implemented (task 2.3), see "Budget and usage alarms" below.
- Throttling, reserved concurrency, and budget alarms are infra changes tracked outside this note (`infra/template.yaml`).

## Budget and usage alarms (task 2.3)

Defined in `infra/template.yaml`:

- Parameters `AlertEmail` (default empty) and `BudgetMonthlyUsd` (default 20). When `AlertEmail` is empty, the SNS topic (`AlertTopic`) and the budget are not created and the alarms have no actions.
- `MonthlyCostBudget`: account-wide monthly cost budget that emails at 80% actual and 100% forecasted spend. It covers Amazon Location and Textract costs. It is not scoped to those services, so it also reflects other spend.
- `PaidRoute*UsageAlarm` (5 alarms): `AWS/ApiGateway` `Count` per route over 5 minutes for `GET /addresses` (300), `GET /addresses/units` (100), `POST /properties/enrich` (20), `POST /imports/schedule-e/extractions` (10) and `.../{jobId}/start` (10). The stage now sets `DetailedMetricsEnabled`, which is required for the `Route` dimension and adds CloudWatch metric cost (small).
- RentCast is a third-party API, so AWS Budgets cannot see its spend. The `POST /properties/enrich` count is the proxy; compare it with your RentCast plan quota and tune the threshold.
- Throttled (429) requests are counted too, so a flood that API Gateway throttles still trips the alarm.
- The existing error, throttle, 5xx and 4xx alarms were left without actions.
- After deploy, confirm the SNS subscription email. AWS Budgets emails need no confirmation.
