"""Task 6.5: PropertyService CRUD happy-path and owner-scoping unit tests.

Focused example-based coverage of the property CRUD happy paths and per-user
ownership scoping. These complement (and intentionally do not duplicate) the
smoke test in ``test_property_service_smoke.py`` and the property-based tests
(tasks 6.2-6.4), which are out of scope here.

Covers:
  * create returns a Property with id + timestamps and persists BOTH the
    ``USER#/PROP#`` list row and the ``PROPERTY#/META`` mirror (Requirement 2.1);
  * list returns the user's properties, empty for a fresh user (Requirement 2.3);
  * get returns an owned property; not_found for unknown (Requirement 2.3 read path);
  * update changes name/address/property_type, preserves created_at, refreshes
    updated_at, visible via get and list (Requirement 2.4);
  * owner scoping: a second user cannot get/update/delete or list another user's
    property (per-user data isolation — design "data scoped to the authenticated
    user"; corresponds to the task's Req 2.10 owner-scoping intent);
  * property_type is optional on create.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from decimal import Decimal

from logstead.models.property import (
    HoaDetails,
    PropertyDetails,
    PropertyFeatures,
    PropertyInput,
    PropertyOwner,
    PropertyTax,
    SaleEvent,
    TaxAssessment,
)
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"


@pytest.fixture
def client():
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
        yield ddb


@pytest.fixture
def repo(client):
    return DynamoRepository(client, TABLE_NAME)


@pytest.fixture
def service(repo):
    return PropertyService(repo, UserContext(user_id="user-1"))


# --- create ------------------------------------------------------------------


def test_create_returns_property_with_id_and_timestamps(service):
    result = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", property_type="sfr")
    )

    assert result.is_ok
    prop = result.value
    assert prop.id
    assert prop.user_id == "user-1"
    assert prop.name == "Maple St"
    assert prop.address_text == "1 Maple St"
    assert prop.property_type == "sfr"
    # Timestamps are stamped and identical on a fresh create.
    assert prop.created_at is not None
    assert prop.updated_at is not None
    assert prop.created_at == prop.updated_at


def test_create_persists_both_list_row_and_meta_mirror(service, repo):
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", property_type="sfr")
    ).value

    # USER#/PROP# list row is readable.
    list_row = repo.get_item(
        keys.user_pk("user-1"), keys.property_user_sk(prop.id)
    )
    assert list_row is not None
    assert list_row["id"] == prop.id
    assert list_row["name"] == "Maple St"

    # PROPERTY#/META mirror is readable.
    meta_row = repo.get_item(
        keys.property_scoped_pk(prop.id), keys.property_meta_sk()
    )
    assert meta_row is not None
    assert meta_row["id"] == prop.id
    assert meta_row["name"] == "Maple St"

    # Both rows carry matching GSI1 reverse-lookup keys.
    gsi1_pk, gsi1_sk = keys.gsi1_property_keys("user-1", prop.id)
    assert list_row["GSI1PK"] == gsi1_pk and list_row["GSI1SK"] == gsi1_sk
    assert meta_row["GSI1PK"] == gsi1_pk and meta_row["GSI1SK"] == gsi1_sk


def test_create_allows_optional_property_type(service):
    result = service.create(PropertyInput(name="No Type", address_text="2 Oak Ave"))

    assert result.is_ok
    assert result.value.property_type is None
    # Still fully retrievable with the type left unset.
    got = service.get(result.value.id)
    assert got.is_ok and got.value.property_type is None


# --- list --------------------------------------------------------------------


def test_list_is_empty_for_fresh_user(service):
    assert service.list() == []


def test_list_returns_multiple_owned_properties(service):
    a = service.create(PropertyInput(name="A", address_text="1 A St")).value
    b = service.create(PropertyInput(name="B", address_text="2 B St")).value
    c = service.create(PropertyInput(name="C", address_text="3 C St")).value

    listed = service.list()
    assert {p.id for p in listed} == {a.id, b.id, c.id}
    assert {p.name for p in listed} == {"A", "B", "C"}


# --- get ---------------------------------------------------------------------


def test_get_returns_owned_property(service):
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", property_type="sfr")
    ).value

    got = service.get(prop.id)
    assert got.is_ok
    assert got.value.id == prop.id
    assert got.value.name == "Maple St"
    assert got.value.address_text == "1 Maple St"
    assert got.value.property_type == "sfr"


def test_get_unknown_property_returns_not_found(service):
    got = service.get("does-not-exist")
    assert not got.is_ok
    assert got.error.kind == "not_found"


# --- update ------------------------------------------------------------------


def test_update_changes_fields_preserves_created_refreshes_updated(service):
    created = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", property_type="sfr")
    ).value

    updated = service.update(
        created.id,
        PropertyInput(
            name="Maple Street",
            address_text="10 Maple Street",
            property_type="condo",
        ),
    )

    assert updated.is_ok
    result = updated.value
    assert result.id == created.id
    assert result.name == "Maple Street"
    assert result.address_text == "10 Maple Street"
    assert result.property_type == "condo"
    # created_at preserved; updated_at moved forward.
    assert result.created_at == created.created_at
    assert result.updated_at != created.created_at


def test_update_is_visible_via_get_and_list(service):
    created = service.create(
        PropertyInput(name="Old", address_text="1 Old St", property_type="sfr")
    ).value

    service.update(
        created.id,
        PropertyInput(name="New", address_text="2 New St", property_type="duplex"),
    )

    got = service.get(created.id)
    assert got.is_ok and got.value.name == "New"
    assert got.value.address_text == "2 New St"
    assert got.value.property_type == "duplex"

    listed = service.list()
    assert len(listed) == 1
    assert listed[0].name == "New"
    assert listed[0].address_text == "2 New St"


def test_update_unknown_property_returns_not_found(service):
    result = service.update(
        "does-not-exist", PropertyInput(name="X", address_text="Y")
    )
    assert not result.is_ok
    assert result.error.kind == "not_found"


# --- owner scoping -----------------------------------------------------------


def test_second_user_cannot_read_or_mutate_another_users_property(repo):
    owner = PropertyService(repo, UserContext(user_id="owner"))
    intruder = PropertyService(repo, UserContext(user_id="intruder"))

    prop = owner.create(
        PropertyInput(name="Owned", address_text="1 Owned St", property_type="sfr")
    ).value

    # Owner sees it; intruder does not.
    assert owner.get(prop.id).is_ok
    assert owner.list() and owner.list()[0].id == prop.id
    assert intruder.list() == []

    # get is scoped to the owner.
    intruder_get = intruder.get(prop.id)
    assert not intruder_get.is_ok and intruder_get.error.kind == "not_found"

    # update is scoped to the owner and leaves the property untouched.
    intruder_update = intruder.update(
        prop.id, PropertyInput(name="Hijacked", address_text="666 Evil St")
    )
    assert not intruder_update.is_ok and intruder_update.error.kind == "not_found"
    assert owner.get(prop.id).value.name == "Owned"

    # delete is scoped to the owner and leaves the property in place.
    intruder_delete = intruder.delete(prop.id)
    assert not intruder_delete.is_ok and intruder_delete.error.kind == "not_found"
    assert owner.get(prop.id).is_ok


# --- details persistence -----------------------------------------------------


def _sample_details() -> PropertyDetails:
    return PropertyDetails(
        formatted_address="1 Maple St, Austin, TX 78701",
        city="Austin",
        state="TX",
        zip_code="78701",
        latitude=Decimal("30.26715012345"),
        longitude=Decimal("-97.74310098765"),
        property_type="Single Family",
        bedrooms=3,
        bathrooms=Decimal("2.5"),
        year_built=1995,
        zoning="R1",
        subdivision="Sunset",
        last_sale_date="2019-06-15",
        last_sale_price=Decimal("415000.00"),
        features=PropertyFeatures(
            heating=True,
            heating_type="Forced Air",
            garage=True,
            garage_spaces=2,
            roof_type="Shingle",
        ),
        hoa=HoaDetails(fee=Decimal("150.00")),
        owner=PropertyOwner(names=["Jane Doe"], type="Individual", occupied=True),
        tax_assessments=[TaxAssessment(year=2022, value=Decimal("400000.00"))],
        property_taxes=[PropertyTax(year=2022, total=Decimal("6500.00"))],
        sale_history=[
            SaleEvent(date="2019-06-15", price=Decimal("415000.00"), event="Sale")
        ],
    )


def test_create_with_details_persists_details_row(service, repo):
    details = _sample_details()
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", details=details)
    ).value

    # A DETAILS row is written alongside the list/META rows.
    row = repo.get_item(
        keys.property_scoped_pk(prop.id), keys.property_details_sk()
    )
    assert row is not None
    assert row["userId"] == "user-1"
    assert "detailsJson" in row


def test_create_without_details_writes_no_details_row(service, repo):
    prop = service.create(
        PropertyInput(name="No Details", address_text="2 Oak Ave")
    ).value
    row = repo.get_item(
        keys.property_scoped_pk(prop.id), keys.property_details_sk()
    )
    assert row is None


def test_get_returns_parsed_details_round_trip_through_dynamo(service):
    details = _sample_details()
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", details=details)
    ).value

    got = service.get(prop.id)
    assert got.is_ok
    # Details survive the round-trip through moto-backed DynamoDB exactly, with
    # money as two-decimal Decimals and lat/long at full precision.
    assert got.value.details == details


def test_get_details_returns_stored_details(service):
    details = _sample_details()
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", details=details)
    ).value

    result = service.get_details(prop.id)
    assert result.is_ok
    assert result.value == details


def test_get_details_not_found_when_absent(service):
    prop = service.create(
        PropertyInput(name="Bare", address_text="3 Pine St")
    ).value
    result = service.get_details(prop.id)
    assert not result.is_ok
    assert result.error.kind == "not_found"


def test_get_omits_details_when_none_persisted(service):
    prop = service.create(
        PropertyInput(name="Bare", address_text="3 Pine St")
    ).value
    got = service.get(prop.id)
    assert got.is_ok
    assert got.value.details is None


def test_delete_removes_details_row(service, repo):
    prop = service.create(
        PropertyInput(name="Maple St", address_text="1 Maple St", details=_sample_details())
    ).value
    assert (
        repo.get_item(keys.property_scoped_pk(prop.id), keys.property_details_sk())
        is not None
    )

    assert service.delete(prop.id).is_ok
    # The DETAILS row is gone along with the property.
    assert (
        repo.get_item(keys.property_scoped_pk(prop.id), keys.property_details_sk())
        is None
    )
    assert service.get(prop.id).error.kind == "not_found"


def test_details_scoped_to_owner(repo):
    owner = PropertyService(repo, UserContext(user_id="owner"))
    intruder = PropertyService(repo, UserContext(user_id="intruder"))
    prop = owner.create(
        PropertyInput(name="Owned", address_text="1 Owned St", details=_sample_details())
    ).value

    # Intruder cannot read details for a property they do not own.
    assert intruder.get_details(prop.id).error.kind == "not_found"
    # Owner can.
    assert owner.get_details(prop.id).is_ok


def test_owner_scoping_isolates_each_users_list(repo):
    alice = PropertyService(repo, UserContext(user_id="alice"))
    bob = PropertyService(repo, UserContext(user_id="bob"))

    alice.create(PropertyInput(name="Alice-1", address_text="1 A St"))
    alice.create(PropertyInput(name="Alice-2", address_text="2 A St"))
    bob.create(PropertyInput(name="Bob-1", address_text="1 B St"))

    alice_listed = alice.list()
    bob_listed = bob.list()

    assert {p.name for p in alice_listed} == {"Alice-1", "Alice-2"}
    assert {p.name for p in bob_listed} == {"Bob-1"}
    assert all(p.user_id == "alice" for p in alice_listed)
    assert all(p.user_id == "bob" for p in bob_listed)


# --- Notes ---------------------------------------------------------------


def test_get_note_defaults_to_empty_when_unset(service):
    prop = service.create(
        PropertyInput(name="Noteless", address_text="1 Quiet St")
    ).value
    got = service.get_note(prop.id)
    assert got.is_ok
    assert got.value == ""


def test_set_then_get_note_round_trips(service):
    prop = service.create(
        PropertyInput(name="Noted", address_text="2 Memo Ln")
    ).value

    saved = service.set_note(prop.id, "  Tenant renews in June; roof under warranty.  ")
    assert saved.is_ok
    # Stored trimmed.
    assert saved.value == "Tenant renews in June; roof under warranty."

    got = service.get_note(prop.id)
    assert got.is_ok
    assert got.value == "Tenant renews in June; roof under warranty."


def test_set_note_replaces_previous(service):
    prop = service.create(
        PropertyInput(name="Noted", address_text="3 Memo Ln")
    ).value
    service.set_note(prop.id, "first")
    service.set_note(prop.id, "second")
    assert service.get_note(prop.id).value == "second"


def test_note_on_unknown_property_is_not_found(service):
    assert not service.get_note("nope").is_ok
    assert service.get_note("nope").error.kind == "not_found"
    assert not service.set_note("nope", "x").is_ok


def test_note_scoped_to_owner(repo):
    owner = PropertyService(repo, UserContext(user_id="owner"))
    intruder = PropertyService(repo, UserContext(user_id="intruder"))
    prop = owner.create(PropertyInput(name="Owned", address_text="1 Owned St")).value
    owner.set_note(prop.id, "private note")

    # Intruder cannot read or write the note.
    assert not intruder.get_note(prop.id).is_ok
    assert not intruder.set_note(prop.id, "hijack").is_ok
    # Owner's note is intact.
    assert owner.get_note(prop.id).value == "private note"


def test_note_removed_when_property_deleted(service, repo):
    prop = service.create(
        PropertyInput(name="ToDelete", address_text="9 Gone St")
    ).value
    service.set_note(prop.id, "will be deleted")
    assert service.delete(prop.id).is_ok
    # The NOTE row is gone with the property.
    from logstead.repository import keys

    assert (
        repo.get_item(keys.property_scoped_pk(prop.id), keys.property_note_sk())
        is None
    )
