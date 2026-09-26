"""Property-based test: property creation rejects blank name or address.

Design Property 2 (Requirements 2.1, 2.2): *for any* property submission whose
name or address is empty or whitespace-only, creation is rejected and the
validation message identifies the offending field; when both are non-blank
creation is accepted.

:class:`PropertyService.create` validates ``name`` first, then ``address_text``
(``services/property.py``), returning ``Result.failure("validation", ...,
field="name"|"address_text")`` for the *first* offending field. This test drives
that invariant universally: each of ``name`` and ``address_text`` is drawn
independently as one of four shapes -- a non-blank string, the empty string, a
whitespace-only string, or "absent" (modeled as the empty string, since
``PropertyInput`` types both fields as required ``str``). Creation must succeed
*iff* both fields are non-blank after stripping; otherwise it must fail with kind
``"validation"`` and ``error.field`` naming the first missing field in the
service's check order (name before address_text).

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(with the GSI1 index the service relies on), following the fixture pattern in
``test_property_service_smoke.py``. Because per-example table provisioning is not
instantaneous, the deadline is disabled; the example count is held at >= 100.
"""

from __future__ import annotations

import contextlib

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@contextlib.contextmanager
def _moto_table():
    """Provision an isolated moto single-table DynamoDB with GSI1.

    Yields a :class:`DynamoRepository` bound to a freshly created table so each
    Hypothesis example runs against a clean store.
    """
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
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
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoRepository(ddb, TABLE_NAME)


def _is_blank(value: str) -> bool:
    """Mirror the service's blank check: whitespace-only (or empty) is blank."""
    return value.strip() == ""


# A field value is one of four shapes. "Absent" is modeled as the empty string
# because PropertyInput types name/address_text as required (non-optional) str,
# so an omitted field surfaces as "" at this boundary.
_non_blank = st.text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")
_empty = st.just("")
_whitespace_only = st.text(
    alphabet=st.sampled_from([" ", "\t", "\n", "\r", "\f", "\v"]),
    min_size=1,
    max_size=8,
)
_field_values = st.one_of(_non_blank, _empty, _whitespace_only)


# Feature: logstead, Property 2: Property creation rejects blank name or address
@settings(deadline=None, max_examples=150)
@given(
    name=_field_values,
    address=_field_values,
    property_type=st.one_of(st.none(), st.text(max_size=20)),
)
def test_property_creation_rejects_blank_name_or_address(
    name: str, address: str, property_type: str | None
) -> None:
    """Creation succeeds iff both name and address are non-blank; else validation.

    Validates: Requirements 2.1, 2.2
    """
    name_blank = _is_blank(name)
    address_blank = _is_blank(address)

    with _moto_table() as repo:
        service = PropertyService(repo, UserContext(user_id="user-1"))
        result = service.create(
            PropertyInput(name=name, address_text=address, property_type=property_type)
        )

        if not name_blank and not address_blank:
            # Both present -> creation is accepted and persists a scoped property.
            assert result.is_ok
            prop = result.value
            assert prop.id
            assert prop.user_id == "user-1"
            # Stored values are the stripped inputs.
            assert prop.name == name.strip()
            assert prop.address_text == address.strip()
            assert [p.id for p in service.list()] == [prop.id]
        else:
            # At least one field is blank -> creation is rejected with a
            # validation error naming the FIRST offending field. The service
            # checks name before address_text.
            assert not result.is_ok
            assert result.error.kind == "validation"
            expected_field = "name" if name_blank else "address_text"
            assert result.error.field == expected_field
            assert result.error.message  # a human-readable message is present
            # No property was persisted on the rejected path.
            assert service.list() == []
