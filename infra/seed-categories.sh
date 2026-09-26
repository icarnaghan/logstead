#!/usr/bin/env bash
# Seed the fixed Schedule E category catalog into the deployed DynamoDB table.
# The categories are reference data the app reads via GET /categories; without
# this step the table comes up empty and category dropdowns are blank.
#
# Idempotent: categories use fixed IDs, so re-running overwrites the same items.
#
# Usage:  infra/seed-categories.sh [stack-name] [region]
# Prereqs: stack deployed; aws CLI configured; python3 available.
set -euo pipefail

STACK_NAME="${1:-logstead}"
REGION="${2:-us-east-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The template names the table "Logstead" (a fixed TableName). Confirm it exists.
TABLE_NAME="Logstead"
aws dynamodb describe-table --table-name "${TABLE_NAME}" --region "${REGION}" \
  --query "Table.TableName" --output text >/dev/null

echo "Seeding categories into DynamoDB table '${TABLE_NAME}' (${REGION})..."

# Use a throwaway venv so the logstead package + boto3 are importable. The venv
# is created outside the SAM CodeUri to avoid interfering with sam build.
VENV_DIR="$(mktemp -d)/venv"
python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install -q -e "${REPO_ROOT}/backend"

AWS_REGION="${REGION}" TABLE_NAME="${TABLE_NAME}" "${VENV_DIR}/bin/python" - <<PY
import os, boto3
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.category import seed_categories, list_categories

ddb = boto3.client("dynamodb", region_name=os.environ["AWS_REGION"])
repo = DynamoRepository(ddb, os.environ["TABLE_NAME"])
seeded = seed_categories(repo)
back = list_categories(repo)
print(f"seeded {len(seeded)} categories; read back {len(back)}")
PY

rm -rf "$(dirname "${VENV_DIR}")"
echo "Done."
