"""Property test for user-scoped combined export keys (accountant-package task 1.12).

Feature: accountant-package, Property 16: Combined export keys are user-scoped

**Validates: Requirements 24.1, 24.2, 24.4**
"""

from __future__ import annotations

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"


def _create_table(ddb) -> None:
    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": n, "AttributeType": "S"}
            for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": name,
                "KeySchema": [
                    {"AttributeName": f"{name}PK", "KeyType": "HASH"},
                    {"AttributeName": f"{name}SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name in ("GSI1", "GSI2")
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _service_for(user_id: str, ddb, s3) -> ReportingService:
    repo = DynamoRepository(ddb, TABLE_NAME)
    files = S3FileAdapter(s3, BUCKET)
    properties = PropertyService(repo, user_id)
    created = properties.create(
        PropertyInput(name="Prop", address_text="1 Main St", property_type="single_family")
    )
    assert created.is_ok
    return ReportingService(
        TransactionService(repo, files), DepreciationService(repo), properties, files
    )


# Not purely numeric, so a user id can never look like a tax year segment.
_user_ids = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12
).filter(lambda s: not s.isdigit())


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    users=st.lists(_user_ids, min_size=2, max_size=2, unique=True),
    tax_year=st.integers(min_value=2000, max_value=2100),
    fmt=st.sampled_from(["csv", "json"]),
)
def test_combined_export_keys_are_user_scoped(users, tax_year, fmt):
    user_a, user_b = users
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        keys = {}
        for user_id in (user_a, user_b):
            result = _service_for(user_id, ddb, s3).export_combined_report(
                None, tax_year, fmt
            )
            assert result.is_ok, result.error
            keys[user_id] = result.value.key

        assert keys[user_a] != keys[user_b]
        for user_id, key in keys.items():
            assert key.startswith(f"exports/combined/{user_id}/{tax_year}/")

        stored = [
            o["Key"]
            for o in s3.list_objects_v2(Bucket=BUCKET, Prefix="exports/combined/").get(
                "Contents", []
            )
        ]
        assert sorted(stored) == sorted(keys.values())
        # Legacy unscoped shape exports/combined/<tax_year>/... must not exist.
        assert not any(k.startswith(f"exports/combined/{tax_year}/") for k in stored)
