"""Property-based test for the at-most-one-link invariant (Task 5.2).

# Feature: business-entities, Property 3: A property links to at most one business, consistent both ways

Validates: Requirements 9.1, 9.2, 9.3, 9.4, 10

For any property owned by the user and any finite sequence of set / change /
clear link operations (each target business owned by the user), after the
sequence:

* the property's ``business_id`` reflects exactly the last successful operation
  — absent after a clear, otherwise the last set/changed business id;
* the property is never linked to more than one business (last-write-wins, a
  change is a plain overwrite); and
* the two viewing directions agree — the property reports that single business
  id, and for every owned business ``linked_properties`` includes the property
  iff the property's current ``business_id`` equals that business.

Each example runs against a fresh moto-backed single-table DynamoDB (base table
+ GSI1), with the Business and Property services wired *router-style* so
``set_business`` can validate ownership via ``BusinessService.owns`` and
``linked_properties`` can filter the user's properties by ``business_id``.

A random op sequence is generated over a small fixed set of owned businesses:
each op is either ``clear`` (business_id None) or ``set`` to one of those
businesses. A reference model tracks the expected current link by replaying the
ops (every generated op targets an owned business or a clear, so every op is a
successful operation and simple last-write-wins applies).
"""

from __future__ import annotations

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.models.business import BusinessInput
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
USER_ID = "user-1"

# A small fixed pool of owned businesses the ops draw their targets from. Index
# ``i`` in a "set" op maps to the i-th created business; ``None`` is a clear.
_BUSINESS_COUNT = 3


def _create_table(ddb) -> None:
    """Provision the single-table Logstead schema (base table + GSI1)."""
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


# Each op is either None (clear) or an index 0.._BUSINESS_COUNT-1 (set to that
# owned business). A non-trivial sequence length keeps set/change/clear
# transitions frequent across the run.
_ops = st.lists(
    st.one_of(st.none(), st.integers(min_value=0, max_value=_BUSINESS_COUNT - 1)),
    min_size=0,
    max_size=12,
)


# Deadline disabled: each example provisions a fresh moto table whose setup time
# varies run-to-run and is unrelated to the link invariant under test.
@settings(deadline=None)
@given(ops=_ops)
# Feature: business-entities, Property 3: A property links to at most one business, consistent both ways
def test_property_links_to_at_most_one_business_consistent_both_ways(
    ops: list[int | None],
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        repo = DynamoRepository(ddb, TABLE_NAME)

        # Router-style wiring so set_business/owns and linked_properties resolve.
        user = UserContext(user_id=USER_ID)
        biz = BusinessService(repo, user, files=None)
        prop = PropertyService(repo, user, business_service=biz)
        biz._property_service = prop

        # A small pool of owned businesses the ops target.
        business_ids: list[str] = []
        for i in range(_BUSINESS_COUNT):
            created = biz.create(
                BusinessInput(legal_name=f"Entity {i} LLC", entity_type="llc")
            )
            assert created.is_ok
            business_ids.append(created.value.id)

        p = prop.create(
            PropertyInput(name="Subject Property", address_text="1 Maple St")
        ).value

        # Replay the ops against the service and a reference model in lockstep.
        expected: str | None = None  # last successful link; None after a clear
        for op in ops:
            target = None if op is None else business_ids[op]
            result = prop.set_business(p.id, target)
            # Every generated op is a clear or a set to an owned business, so
            # every op is a successful operation (Req 9.1-9.3).
            assert result.is_ok
            expected = target

        # 1) The property's business_id equals the last successful op.
        fetched = prop.get(p.id)
        assert fetched.is_ok
        assert fetched.value.business_id == expected

        # 2) It is never linked to more than one business: business_id is a
        #    single scalar (or None), so "at most one" holds by construction;
        #    assert it is None or exactly one of the owned ids.
        current = fetched.value.business_id
        assert current is None or current in business_ids
        if current is not None:
            matches = [b for b in business_ids if b == current]
            assert len(matches) == 1

        # 3) Both directions agree: for every owned business, linked_properties
        #    includes the property iff the property's current business_id equals
        #    that business (Req 10, both-sides consistency).
        for business_id in business_ids:
            linked = biz.linked_properties(business_id)
            assert linked.is_ok
            linked_ids = {ref.id for ref in linked.value}
            if current == business_id:
                assert p.id in linked_ids
            else:
                assert p.id not in linked_ids
