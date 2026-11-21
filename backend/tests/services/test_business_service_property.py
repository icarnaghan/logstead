"""Property-based test for Business create -> get round-trip (task 2.2).

Design Property 4 (Requirements 1.1, 1.3, 1.6): *for any* valid
:class:`BusinessInput` (non-blank ``legal_name``, enum ``entity_type``, arbitrary
optional fields), creating a business and then getting it by id returns a
:class:`Business` whose stored fields equal the submitted values, with
``tax_year_end`` defaulting to ``"12-31"`` exactly when it was omitted
(``None``/blank) and ``ein`` stored byte-for-byte as entered.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) so every example runs against a clean store; per-example
table provisioning is not instantaneous, so the deadline is disabled while the
example count is held at 100.
"""

from __future__ import annotations

import contextlib

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.business import ENTITY_TYPES, BusinessInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService

TABLE_NAME = "Logstead"
USER_ID = "user-1"


@contextlib.contextmanager
def _moto_table():
    """Provision an isolated moto single-table DynamoDB (base + GSI1 + GSI2)."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
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
        yield DynamoRepository(ddb, TABLE_NAME)


def _is_blank(value: str | None) -> bool:
    """Mirror the service's blank check: ``None`` or whitespace-only is blank."""
    return value is None or value.strip() == ""


# A non-blank legal_name after stripping (the service stores the stripped form).
_non_blank_name = st.text(min_size=1, max_size=60).filter(
    lambda s: s.strip() != ""
)
# Arbitrary optional free text, including None and blank/whitespace-only.
_optional_text = st.one_of(
    st.none(),
    st.just(""),
    st.text(
        alphabet=st.sampled_from([" ", "\t", "\n"]), min_size=1, max_size=4
    ),
    st.text(max_size=40),
)


# Feature: business-entities, Property 4: Business create → get round-trip preserves fields
@settings(deadline=None, max_examples=100)
@given(
    legal_name=_non_blank_name,
    entity_type=st.sampled_from(sorted(ENTITY_TYPES)),
    ein=_optional_text,
    formation_state=_optional_text,
    formation_date=_optional_text,
    business_address=_optional_text,
    tax_year_end=_optional_text,
    note=_optional_text,
)
def test_create_get_round_trip_preserves_fields(
    legal_name: str,
    entity_type: str,
    ein: str | None,
    formation_state: str | None,
    formation_date: str | None,
    business_address: str | None,
    tax_year_end: str | None,
    note: str | None,
) -> None:
    """create -> get returns a Business whose fields equal the submitted values.

    Validates: Requirements 1.1, 1.3, 1.6
    """
    data = BusinessInput(
        legal_name=legal_name,
        entity_type=entity_type,
        ein=ein,
        formation_state=formation_state,
        formation_date=formation_date,
        business_address=business_address,
        tax_year_end=tax_year_end,
        note=note,
    )

    with _moto_table() as repo:
        service = BusinessService(repo, UserContext(user_id=USER_ID))

        created = service.create(data)
        assert created.is_ok

        fetched = service.get(created.value.id)
        assert fetched.is_ok
        biz = fetched.value

        # Identity + ownership.
        assert biz.id == created.value.id
        assert biz.user_id == USER_ID

        # legal_name is stored stripped; entity_type verbatim.
        assert biz.legal_name == legal_name.strip()
        assert biz.entity_type == entity_type

        # ein stored byte-for-byte (None stays None); no format applied (Req 1.6).
        assert biz.ein == ein

        # tax_year_end defaults to "12-31" exactly when omitted (None/blank),
        # otherwise the submitted value is preserved verbatim (Req 1.3).
        if _is_blank(tax_year_end):
            assert biz.tax_year_end == "12-31"
        else:
            assert biz.tax_year_end == tax_year_end

        # Remaining optional fields round-trip verbatim.
        assert biz.formation_state == formation_state
        assert biz.formation_date == formation_date
        assert biz.business_address == business_address
        assert biz.note == note
