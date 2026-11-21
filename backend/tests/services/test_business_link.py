"""Moto example/edge tests for the property↔business link (Tasks 4.1, 5.1).

Covers two collaborating surfaces of the Business Entities feature:

* ``PropertyService.set_business`` (Task 4.1, Requirement 9) — set / change /
  clear a property's owning business, with validation of the target business's
  ownership and of the property's existence.
* ``BusinessService.linked_properties`` (Task 5.1, Requirement 10) — the
  filtered-property-list view of which properties are linked to a business, by
  human-readable name, including the fail-safe when the collaborator is unwired.

Both services run against a real moto-backed single-table DynamoDB (base table
+ GSI1, mirroring ``test_backup_export``). The two services are wired
*router-style* per the design's constructor contract (design.md "Mutual
dependency / wiring"; services/business.py docstring)::

    biz = BusinessService(repo, user, files=None)
    prop = PropertyService(repo, user, business_service=biz)
    biz._property_service = prop

so ``set_business`` can call ``BusinessService.owns`` and ``linked_properties``
can list the user's properties and filter by ``business_id``.

This module deliberately does NOT touch ``test_business_service.py`` /
``test_business_service_property.py`` (entity-CRUD coverage owned elsewhere); it
exercises only the link direction and the both-sides view.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.models.business import BusinessInput
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService, LinkedPropertyRef
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
USER_ID = "user-1"
OTHER_USER_ID = "user-2"


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


@pytest.fixture
def aws():
    """A moto context with the single table (base + GSI1)."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        yield ddb


@pytest.fixture
def repo(aws):
    return DynamoRepository(aws, TABLE_NAME)


def _wire(repo: DynamoRepository, user_id: str = USER_ID):
    """Wire a Business/Property service pair router-style for one user.

    Mirrors the design's per-request wiring: build the business service, build
    the property service with the business service injected, then back-fill the
    property-service reference onto the business service so both collaborators
    resolve (no import cycle; neither touches the other at construction time).
    """
    user = UserContext(user_id=user_id)
    biz = BusinessService(repo, user, files=None)
    prop = PropertyService(repo, user, business_service=biz)
    biz._property_service = prop
    return biz, prop


def _make_business(biz: BusinessService, legal_name: str):
    """Create an owned LLC business and return the stored record."""
    result = biz.create(
        BusinessInput(legal_name=legal_name, entity_type="llc")
    )
    assert result.is_ok
    return result.value


def _make_property(prop: PropertyService, name: str):
    """Create an owned property and return the stored record."""
    result = prop.create(PropertyInput(name=name, address_text="1 Maple St"))
    assert result.is_ok
    return result.value


# =============================================================================
# Task 4.1 — PropertyService.set_business: set / change / clear + errors
# =============================================================================


def test_set_business_links_owned_business_on_both_rows(repo):
    """Setting a property's business stores businessId and is readable via get."""
    biz, prop = _wire(repo)
    business = _make_business(biz, "Acme Holdings LLC")
    p = _make_property(prop, "Maple Duplex")

    result = prop.set_business(p.id, business.id)

    assert result.is_ok
    assert result.value.business_id == business.id
    # Readable back via get (which reads the META mirror row).
    fetched = prop.get(p.id)
    assert fetched.is_ok
    assert fetched.value.business_id == business.id
    # Both rows carry businessId: the list-view row reflects it too.
    listed = {item.id: item for item in prop.list()}
    assert listed[p.id].business_id == business.id


def test_set_business_change_overwrites_to_single_link(repo):
    """Changing to a different owned business overwrites (exactly one link)."""
    biz, prop = _wire(repo)
    business_a = _make_business(biz, "Alpha LLC")
    business_b = _make_business(biz, "Beta LLC")
    p = _make_property(prop, "Oak Cottage")

    assert prop.set_business(p.id, business_a.id).is_ok
    changed = prop.set_business(p.id, business_b.id)

    assert changed.is_ok
    assert changed.value.business_id == business_b.id
    # The property reports exactly the new business, never both.
    fetched = prop.get(p.id)
    assert fetched.is_ok
    assert fetched.value.business_id == business_b.id
    # linked_properties agrees: A no longer lists it, B does.
    linked_a = biz.linked_properties(business_a.id)
    linked_b = biz.linked_properties(business_b.id)
    assert linked_a.is_ok and [r.id for r in linked_a.value] == []
    assert linked_b.is_ok and [r.id for r in linked_b.value] == [p.id]


def test_set_business_clear_removes_attribute(repo):
    """Clearing (business_id=None) removes the attribute; property stays valid."""
    biz, prop = _wire(repo)
    business = _make_business(biz, "Gamma LLC")
    p = _make_property(prop, "Pine Flat")

    assert prop.set_business(p.id, business.id).is_ok
    cleared = prop.set_business(p.id, None)

    assert cleared.is_ok
    assert cleared.value.business_id is None
    # The attribute is gone from storage, read back as None.
    fetched = prop.get(p.id)
    assert fetched.is_ok
    assert fetched.value.business_id is None
    # The property is otherwise unchanged and still valid.
    assert fetched.value.name == "Pine Flat"
    assert fetched.value.address_text == "1 Maple St"


def test_set_business_unknown_business_returns_not_found_field(repo):
    """Linking to a non-owned/unknown business id → not_found (field business_id).

    With a wired BusinessService, ``set_business`` validates the target via
    ``owns``; an unknown or non-owned id fails ownership and the implementation
    returns a ``not_found`` ``Result`` identifying ``business_id`` (design.md
    Error Handling → "Link validation (Req 9.5)").
    """
    biz, prop = _wire(repo)
    p = _make_property(prop, "Birch Bungalow")

    result = prop.set_business(p.id, "does-not-exist")

    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"
    # Nothing was linked.
    assert prop.get(p.id).value.business_id is None


def test_set_business_non_owned_business_returns_not_found(repo):
    """A business owned by another user is not linkable → not_found."""
    biz, prop = _wire(repo)
    # A business owned by a DIFFERENT user.
    other_biz, _ = _wire(repo, user_id=OTHER_USER_ID)
    foreign = _make_business(other_biz, "Foreign LLC")
    p = _make_property(prop, "Cedar Court")

    result = prop.set_business(p.id, foreign.id)

    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"
    assert prop.get(p.id).value.business_id is None


def test_set_business_unknown_property_returns_not_found(repo):
    """set_business on an unknown property → not_found."""
    biz, prop = _wire(repo)
    business = _make_business(biz, "Delta LLC")

    result = prop.set_business("no-such-property", business.id)

    assert not result.is_ok
    assert result.error.kind == "not_found"


def test_unlinked_property_reads_none_and_behaves_normally(repo):
    """An unlinked property reads business_id None and lists/gets normally (Req 9.4)."""
    biz, prop = _wire(repo)
    p = _make_property(prop, "Elm Estate")

    fetched = prop.get(p.id)
    assert fetched.is_ok
    assert fetched.value.business_id is None
    # Appears in the list unchanged, with no link.
    listed = {item.id: item for item in prop.list()}
    assert p.id in listed
    assert listed[p.id].business_id is None
    # Update still works and does not introduce a link.
    updated = prop.update(
        p.id, PropertyInput(name="Elm Estate II", address_text="2 Elm St")
    )
    assert updated.is_ok
    assert updated.value.business_id is None


# =============================================================================
# Task 5.1 — BusinessService.linked_properties: both-sides view + fail-safe
# =============================================================================


def test_linked_properties_returns_only_linked_by_name(repo):
    """Linking 2 of 3 to A and 1 to B → each business lists exactly its own."""
    biz, prop = _wire(repo)
    business_a = _make_business(biz, "Harbor LLC")
    business_b = _make_business(biz, "Summit LLC")
    p1 = _make_property(prop, "Dockside")
    p2 = _make_property(prop, "Wharf House")
    p3 = _make_property(prop, "Ridgeline")

    assert prop.set_business(p1.id, business_a.id).is_ok
    assert prop.set_business(p2.id, business_a.id).is_ok
    assert prop.set_business(p3.id, business_b.id).is_ok

    linked_a = biz.linked_properties(business_a.id)
    linked_b = biz.linked_properties(business_b.id)

    assert linked_a.is_ok
    assert linked_b.is_ok
    # Returned as LinkedPropertyRef(id, name) with correct human names.
    assert {(r.id, r.name) for r in linked_a.value} == {
        (p1.id, "Dockside"),
        (p2.id, "Wharf House"),
    }
    assert [(r.id, r.name) for r in linked_b.value] == [(p3.id, "Ridgeline")]
    assert all(isinstance(r, LinkedPropertyRef) for r in linked_a.value)


def test_linked_properties_empty_for_business_with_none(repo):
    """A business with no linked properties returns an empty list."""
    biz, prop = _wire(repo)
    business = _make_business(biz, "Lonely LLC")
    # A property exists but is linked elsewhere / not at all.
    _make_property(prop, "Unrelated")

    linked = biz.linked_properties(business.id)

    assert linked.is_ok
    assert linked.value == []


def test_linked_properties_drops_property_after_clear(repo):
    """After clearing a link the property drops out of linked_properties."""
    biz, prop = _wire(repo)
    business = _make_business(biz, "Transient LLC")
    p = _make_property(prop, "Here Then Gone")

    assert prop.set_business(p.id, business.id).is_ok
    assert [r.id for r in biz.linked_properties(business.id).value] == [p.id]

    assert prop.set_business(p.id, None).is_ok
    linked = biz.linked_properties(business.id)
    assert linked.is_ok
    assert linked.value == []


def test_linked_properties_unknown_business_returns_not_found(repo):
    """An unknown business id → not_found (field business_id)."""
    biz, _ = _wire(repo)

    linked = biz.linked_properties("no-such-business")

    assert not linked.is_ok
    assert linked.error.kind == "not_found"
    assert linked.error.field == "business_id"


def test_linked_properties_cross_user_business_returns_not_found(repo):
    """A business owned by another user → not_found for this user."""
    biz, _ = _wire(repo)
    other_biz, _ = _wire(repo, user_id=OTHER_USER_ID)
    foreign = _make_business(other_biz, "Foreign Co LLC")

    linked = biz.linked_properties(foreign.id)

    assert not linked.is_ok
    assert linked.error.kind == "not_found"
    assert linked.error.field == "business_id"


def test_linked_properties_unavailable_when_property_service_unwired(repo):
    """Without a wired property_service, linked_properties fails `unavailable`.

    This confirms the fail-safe: the delete-guard relies on this method as the
    authority on the linked set, so an unwired collaborator must NOT be reported
    as "no links" ([]) — it returns an ``unavailable`` failure instead
    (services/business.py docstring; design.md fail-safe note).
    """
    user = UserContext(user_id=USER_ID)
    # Wire a pair only to CREATE an owned business, so the not_found guard
    # passes and we reach the collaborator check.
    biz_wired, _ = _wire(repo)
    business = _make_business(biz_wired, "Safe LLC")

    # A business service with NO property_service collaborator.
    biz_unwired = BusinessService(repo, user, files=None, property_service=None)
    linked = biz_unwired.linked_properties(business.id)

    assert not linked.is_ok
    assert linked.error.kind == "unavailable"
    # Explicitly: it is NOT a silently-wrong empty success.
    assert linked.ok is None
