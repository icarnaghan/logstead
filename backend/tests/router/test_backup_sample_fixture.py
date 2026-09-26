"""Task 8.3: sample-fixture backend acceptance test (Requirement 10).

Loads the bundled frontend fixture ``frontend/src/data/sample-backup.json`` as a
test resource (path computed relative to the repo root), runs it through the
pure ``validate_document`` pass **and** a full ``BackupService.restore`` against
a ``moto``-backed DynamoDB table + S3 bucket, then asserts the sample dataset
lands as advertised:

* the document is accepted (validates, and restore succeeds), and
* the restored store holds exactly **2 properties**, each with **5 tax years**
  carrying both income and expense across multiple categories, and **≥ 1 asset
  per property**.

This proves the sample the "Load sample data" flow ships is a real, restorable
backup — not just structurally shaped JSON (Requirements 10.1–10.4).
"""

from __future__ import annotations

import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.backup import BackupService, validate_document
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-sample-fixture"
REGION = "us-east-1"
USER_ID = "user-sample-fixture"


# --- fixture resource --------------------------------------------------------


def _repo_root() -> Path:
    """The repository root: this file lives at backend/tests/router/."""
    return Path(__file__).resolve().parents[3]


def _load_sample_document() -> dict:
    """Load the bundled frontend sample fixture as parsed JSON."""
    fixture_path = _repo_root() / "frontend" / "src" / "data" / "sample-backup.json"
    assert fixture_path.exists(), f"sample fixture not found at {fixture_path}"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


# --- moto wiring -------------------------------------------------------------


@pytest.fixture
def aws():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        yield ddb, s3


@pytest.fixture
def repo(aws):
    ddb, _ = aws
    return DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def files(aws):
    _, s3 = aws
    return S3FileAdapter(s3, BUCKET)


@pytest.fixture
def backup_service(repo, files):
    return BackupService(repo, files, USER_ID)


# ============================================================================
# Acceptance: validate + full restore of the shipped sample fixture
# ============================================================================


def test_sample_fixture_validates():
    """The shipped sample document passes the pure validator (accepted)."""
    document = _load_sample_document()
    result = validate_document(document)
    assert result.is_ok, (
        result.error.message if result.error else "validation failed"
    )
    parsed = result.value
    assert parsed.schema_version == "1"
    assert len(parsed.properties) == 2


def test_sample_fixture_restores_and_lands_as_advertised(backup_service, repo):
    """A full restore of the sample fixture lands the advertised dataset.

    Asserts acceptance (restore succeeds) then inspects the restored store:
    exactly 2 properties; per property 5 tax years each carrying income + expense
    across multiple categories; ≥ 1 asset per property.
    """
    document = _load_sample_document()

    # Acceptance: validate + full restore succeed.
    restore_result = backup_service.restore(document)
    assert restore_result.is_ok, (
        restore_result.error.message if restore_result.error else "restore failed"
    )
    summary = restore_result.value
    assert summary.properties == 2

    # --- Inspect the restored store via the read services (user-scoped). ----
    property_service = PropertyService(repo, USER_ID)
    transaction_service = TransactionService(repo, backup_service._files)
    depreciation_service = DepreciationService(repo)

    properties = property_service.list()
    assert len(properties) == 2, "exactly two properties restored"

    for prop in properties:
        txn_result = transaction_service.list_for_property(prop.id)
        assert txn_result.is_ok
        transactions = txn_result.value

        # 5 distinct tax years, derived from the transaction dates.
        tax_years = {txn.date[:4] for txn in transactions}
        assert len(tax_years) == 5, (
            f"{prop.name}: expected 5 tax years, saw {sorted(tax_years)}"
        )

        # Both income and expense are present.
        types = {txn.type for txn in transactions}
        assert {"income", "expense"} <= types, (
            f"{prop.name}: expected income + expense, saw {sorted(types)}"
        )

        # Income and expense each span multiple categories.
        income_cats = {t.category_id for t in transactions if t.type == "income"}
        expense_cats = {t.category_id for t in transactions if t.type == "expense"}
        all_cats = income_cats | expense_cats
        assert len(all_cats) >= 2, (
            f"{prop.name}: expected multiple categories, saw {sorted(all_cats)}"
        )
        assert expense_cats, f"{prop.name}: expected at least one expense category"

        # At least one asset per property.
        assets = depreciation_service.list_assets(prop.id)
        assert len(assets) >= 1, f"{prop.name}: expected >= 1 asset"


def test_sample_fixture_five_tax_years_have_income_and_expense(backup_service, repo):
    """Each of the 5 tax years (per property) carries both income and expense.

    A stronger read of Requirement 10.3 than the aggregate check above: every one
    of the five years should have at least one income and one expense row.
    """
    document = _load_sample_document()
    assert backup_service.restore(document).is_ok

    property_service = PropertyService(repo, USER_ID)
    transaction_service = TransactionService(repo, backup_service._files)

    for prop in property_service.list():
        transactions = transaction_service.list_for_property(prop.id).value
        by_year: dict[str, set[str]] = {}
        for txn in transactions:
            by_year.setdefault(txn.date[:4], set()).add(txn.type)
        assert len(by_year) == 5, f"{prop.name}: expected 5 tax years"
        for year, types in by_year.items():
            assert {"income", "expense"} <= types, (
                f"{prop.name} {year}: expected income + expense, saw {sorted(types)}"
            )
