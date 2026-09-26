#!/usr/bin/env bash
# Build the SPA and publish it to the Logstead SPA bucket, then invalidate
# CloudFront. Reads bucket/distribution details from the deployed stack outputs.
#
# Usage:  infra/deploy-spa.sh [stack-name] [region]
# Prereqs: stack already deployed (sam deploy); aws CLI configured; node + npm.
set -euo pipefail

STACK_NAME="${1:-logstead}"
REGION="${2:-us-east-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Reading stack outputs from ${STACK_NAME} (${REGION})..."
outputs=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" --region "${REGION}" \
  --query "Stacks[0].Outputs" --output json)

get_output() {
  echo "${outputs}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((o[\"OutputValue\"] for o in d if o[\"OutputKey\"]==sys.argv[1]), \"\"))" "$1"
}

SPA_BUCKET="$(get_output SpaBucketName)"
API_BASE_URL="$(get_output ApiBaseUrl)"
COGNITO_DOMAIN="$(get_output CognitoHostedUiDomain)"
CLIENT_ID="$(get_output UserPoolClientId)"
CLOUDFRONT_DOMAIN="$(get_output CloudFrontDomain)"

if [ -z "${SPA_BUCKET}" ]; then
  echo "ERROR: could not read SpaBucketName from stack outputs." >&2
  exit 1
fi

# Resolve the CloudFront distribution id from its domain name.
DIST_ID="$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?DomainName==\`${CLOUDFRONT_DOMAIN}\`].Id | [0]" \
  --output text)"

echo "SPA bucket:        ${SPA_BUCKET}"
echo "API base URL:      ${API_BASE_URL}"
echo "CloudFront domain: ${CLOUDFRONT_DOMAIN} (dist ${DIST_ID})"

# App origin: prefer the custom domain if wired, else the CloudFront domain.
APP_ORIGIN="${APP_ORIGIN:-https://${CLOUDFRONT_DOMAIN}}"

echo "Writing frontend/.env.production ..."
cat > "${REPO_ROOT}/frontend/.env.production" <<ENV
VITE_API_BASE_URL=${API_BASE_URL}
VITE_COGNITO_DOMAIN=${COGNITO_DOMAIN}
VITE_COGNITO_CLIENT_ID=${CLIENT_ID}
VITE_COGNITO_REDIRECT_URI=${APP_ORIGIN}/auth/callback
VITE_COGNITO_SCOPES=openid email profile
VITE_COGNITO_LOGOUT_URI=${APP_ORIGIN}/
ENV

echo "Building SPA ..."
( cd "${REPO_ROOT}/frontend" && npm ci && npm run build )

echo "Syncing dist/ to s3://${SPA_BUCKET} ..."
aws s3 sync "${REPO_ROOT}/frontend/dist/" "s3://${SPA_BUCKET}/" --delete --region "${REGION}"

if [ -n "${DIST_ID}" ] && [ "${DIST_ID}" != "None" ]; then
  echo "Invalidating CloudFront distribution ${DIST_ID} ..."
  aws cloudfront create-invalidation --distribution-id "${DIST_ID}" --paths "/*" >/dev/null
fi

echo "SPA deploy complete. App: ${APP_ORIGIN}"
