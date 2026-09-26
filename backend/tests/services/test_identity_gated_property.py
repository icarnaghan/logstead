"""Property-based test: data access is always identity-gated (Requirements 1.5, 1.6).

Logstead delegates authentication entirely to Cognito and authorizes API access
using the verified token (Requirements 1.5, 1.6). The concrete consequence at the
service layer is that **every** data operation is scoped to the authenticated
user id (the Cognito ``sub`` resolved by :func:`current_user` and surfaced via
:func:`user_id_of`). One user must never be able to read, mutate, or even observe
another user's records.

This module verifies that identity gate as a universal property: for any pair of
*distinct* user identities A and B, a :class:`PropertyService` scoped to B cannot
reach a property created by a service scoped to A — ``get``/``update``/``delete``
all report ``not_found`` and ``list`` never surfaces it — while A retains full
access to its own record. The authenticated-identity → scope path is exercised by
constructing B's context through :func:`current_user` on a simulated API Gateway
request context, mirroring how the router resolves identity in production.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB (with
the GSI1 index the service relies on), following the fixture pattern in
``test_property_service_smoke.py``. Because table provisioning per example is not
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
from logstead.services.auth import current_user, user_id_of
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@contextlib.contextmanager
def _moto_table():
    """Provision an isolated moto single-table DynamoDB with GSI1.

    Yields a :class:`DynamoRepository` bound to a freshly created table. The
    table is torn down when the moto context exits, so each Hypothesis example
    runs against a clean store.
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


def _http_api_event(sub: str) -> dict:
    """Build a minimal API Gateway HTTP API event carrying a verified ``sub``.

    This mirrors the shape the native Cognito JWT authorizer places on the
    request context, so ``current_user`` resolves the identity exactly as it
    would in production.
    """
    return {
        "requestContext": {
            "authorizer": {"jwt": {"claims": {"sub": sub}}}
        }
    }


# Cognito ``sub`` values are UUID-like, but the scope key is treated as an opaque
# string. Generate non-empty, non-whitespace identifiers over a broad character
# set so the property holds across arbitrary identities, not just UUIDs.
_user_ids = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=0x2FFF),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

# Distinct pairs of identities: A (owner) and B (intruder).
_distinct_user_pairs = st.tuples(_user_ids, _user_ids).filter(lambda p: p[0] != p[1])

_field_text = st.text(min_size=1, max_size=60).filter(lambda s: s.strip() != "")


# Feature: logstead, Property 1: Data access is always identity-gated
@settings(deadline=None, max_examples=120)
@given(
    users=_distinct_user_pairs,
    name=_field_text,
    address=_field_text,
)
def test_data_access_is_always_identity_gated(
    users: tuple[str, str], name: str, address: str
) -> None:
    """One user can never access another user's property; the owner always can.

    Validates: Requirements 1.5, 1.6
    """
    owner_id, intruder_id = users

    with _moto_table() as repo:
        # Owner A is scoped from a UserContext; intruder B's identity flows
        # through the same current_user -> user_id_of path the router uses, so
        # the authenticated identity is what drives B's scope.
        owner = PropertyService(repo, UserContext(user_id=owner_id))

        intruder_ctx = current_user(_http_api_event(intruder_id))
        assert user_id_of(intruder_ctx) == intruder_id
        intruder = PropertyService(repo, intruder_ctx)

        created = owner.create(PropertyInput(name=name, address_text=address))
        assert created.is_ok
        prop = created.value
        assert prop.user_id == owner_id
        # Capture what the owner actually stored (the service normalizes text,
        # e.g. trimming surrounding whitespace) so the no-side-effects check
        # below compares against the persisted values, not the raw input.
        stored_name = prop.name
        stored_address = prop.address_text

        # --- The owner can access its own record -----------------------------
        assert owner.get(prop.id).is_ok
        assert [p.id for p in owner.list()] == [prop.id]

        # --- The intruder is fully gated out of A's record -------------------
        intruder_get = intruder.get(prop.id)
        assert not intruder_get.is_ok
        assert intruder_get.error.kind == "not_found"

        intruder_update = intruder.update(
            prop.id, PropertyInput(name="hijacked", address_text="hijacked")
        )
        assert not intruder_update.is_ok
        assert intruder_update.error.kind == "not_found"

        intruder_delete = intruder.delete(prop.id)
        assert not intruder_delete.is_ok
        assert intruder_delete.error.kind == "not_found"

        # The intruder never sees A's property in their own listing.
        assert prop.id not in [p.id for p in intruder.list()]

        # --- The intruder's failed attempts had no side effects on A ---------
        still_owned = owner.get(prop.id)
        assert still_owned.is_ok
        assert still_owned.value.name == stored_name
        assert still_owned.value.address_text == stored_address
        assert [p.id for p in owner.list()] == [prop.id]
