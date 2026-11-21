"""Task 2.1: moto example/edge tests for ``BusinessService`` entity CRUD.

Exercises :class:`BusinessService`'s entity surface (create/list/get/update, plus
``owns``) against a ``moto``-backed single-table DynamoDB (base + GSI1 + GSI2) so
no live AWS call is made and the repository is real. Covers the Requirement 1-4
example/edge behavior called out in the design's Testing Strategy:

* create happy path writes both rows and returns a stamped record (Req 1.1);
* blank/whitespace ``legal_name`` -> ``validation`` (field ``legal_name``,
  Req 1.4); missing/invalid ``entity_type`` -> ``validation`` (field
  ``entity_type``, Req 1.5);
* ``tax_year_end`` defaults to ``"12-31"`` when omitted (Req 1.3); ``ein`` is
  stored verbatim (Req 1.6);
* list is empty, then returns only the current user's businesses (Req 2.1-2.3);
* get owned -> ok; unknown / cross-user -> ``not_found`` (Req 3.1-3.3);
* update owned applies changes, preserves ``created_at``, refreshes
  ``updated_at`` (Req 4.1), re-validates ``legal_name``/``entity_type``
  (Req 4.2, 4.3), and unknown / cross-user -> ``not_found`` (Req 4.4);
* ``owns`` reports True for an owned business and False otherwise.

The S3 document surface (task 3.1) lives in ``test_business_documents.py`` and
the create->get round-trip property (task 2.2) in
``test_business_service_property.py`` so the three leaves never collide.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from logstead.models.business import BusinessInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService

TABLE_NAME = "Logstead"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"


@pytest.fixture
def aws():
    """A moto context with the table (base + GSI1 + GSI2) pre-created."""
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
        yield ddb


@pytest.fixture
def repo(aws):
    return DynamoRepository(aws, TABLE_NAME)


@pytest.fixture
def service(repo):
    """A ``BusinessService`` scoped to user A."""
    return BusinessService(repo, UserContext(user_id=USER_A))


@pytest.fixture
def service_b(repo):
    """A ``BusinessService`` scoped to user B (same repo), for cross-user tests."""
    return BusinessService(repo, UserContext(user_id=USER_B))


def _valid_input(**overrides) -> BusinessInput:
    """A valid create payload with sensible defaults, overridable per test."""
    data = {
        "legal_name": "Maple Holdings LLC",
        "entity_type": "llc",
    }
    data.update(overrides)
    return BusinessInput(**data)


# --- Create: happy path (Req 1.1, 2.2, 13.1) ---------------------------------


def test_create_returns_record_with_id_and_timestamps(service):
    result = service.create(_valid_input())

    assert result.is_ok
    biz = result.value
    assert biz.id
    assert biz.user_id == USER_A
    assert biz.legal_name == "Maple Holdings LLC"
    assert biz.entity_type == "llc"
    assert biz.created_at is not None
    assert biz.updated_at is not None
    assert biz.created_at == biz.updated_at


def test_create_writes_both_list_row_and_meta_mirror(service, repo):
    biz = service.create(_valid_input()).value

    list_row = repo.get_item(
        keys.user_pk(USER_A), keys.business_user_sk(biz.id)
    )
    meta_row = repo.get_item(
        keys.business_scoped_pk(biz.id), keys.business_meta_sk()
    )
    assert list_row is not None
    assert meta_row is not None
    # Both rows carry the same identity + owner.
    assert list_row["id"] == biz.id
    assert meta_row["id"] == biz.id
    assert list_row["userId"] == USER_A
    assert meta_row["userId"] == USER_A
    assert list_row["legalName"] == "Maple Holdings LLC"
    assert meta_row["legalName"] == "Maple Holdings LLC"


def test_create_strips_legal_name(service):
    biz = service.create(_valid_input(legal_name="  Spaced Co LLC  ")).value
    assert biz.legal_name == "Spaced Co LLC"


# --- Create: validation of legal_name (Req 1.4) ------------------------------


@pytest.mark.parametrize("bad_name", ["", "   ", "\t", "\n ", "  \t\n"])
def test_create_rejects_blank_legal_name(service, repo, bad_name):
    result = service.create(_valid_input(legal_name=bad_name))

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "legal_name"
    assert result.error.message
    # Nothing persisted on the rejected path.
    assert service.list() == []


# --- Create: validation of entity_type (Req 1.5) -----------------------------


@pytest.mark.parametrize(
    "bad_type", ["", "LLC", "corporation", "s-corp", "unknown", " llc "]
)
def test_create_rejects_missing_or_invalid_entity_type(service, bad_type):
    result = service.create(_valid_input(entity_type=bad_type))

    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entity_type"
    assert result.error.message


@pytest.mark.parametrize(
    "good_type",
    [
        "llc",
        "sole_proprietorship",
        "partnership",
        "s_corporation",
        "c_corporation",
        "individual_other",
    ],
)
def test_create_accepts_each_supported_entity_type(service, good_type):
    result = service.create(_valid_input(entity_type=good_type))
    assert result.is_ok
    assert result.value.entity_type == good_type


# --- Create: tax_year_end default (Req 1.3) ----------------------------------


def test_tax_year_end_defaults_when_omitted(service):
    biz = service.create(_valid_input()).value
    assert biz.tax_year_end == "12-31"


@pytest.mark.parametrize("blank", ["", "   "])
def test_tax_year_end_defaults_when_blank(service, blank):
    biz = service.create(_valid_input(tax_year_end=blank)).value
    assert biz.tax_year_end == "12-31"


def test_tax_year_end_preserved_when_provided(service):
    biz = service.create(_valid_input(tax_year_end="06-30")).value
    assert biz.tax_year_end == "06-30"


# --- Create: ein stored verbatim (Req 1.6) -----------------------------------


@pytest.mark.parametrize(
    "ein",
    ["12-3456789", "123456789", "12 3456789", "EIN pending", "  12-3456789  "],
)
def test_ein_stored_verbatim(service, repo, ein):
    biz = service.create(_valid_input(ein=ein)).value
    assert biz.ein == ein
    # And it round-trips byte-for-byte from the stored meta row.
    fetched = service.get(biz.id).value
    assert fetched.ein == ein


def test_ein_omitted_is_none(service):
    biz = service.create(_valid_input()).value
    assert biz.ein is None
    assert service.get(biz.id).value.ein is None


# --- List (Req 2.1-2.3) ------------------------------------------------------


def test_list_empty_when_no_businesses(service):
    assert service.list() == []


def test_list_returns_populated(service):
    a = service.create(_valid_input(legal_name="Alpha LLC")).value
    b = service.create(_valid_input(legal_name="Beta LLC")).value

    listed = service.list()
    assert {biz.id for biz in listed} == {a.id, b.id}
    assert {biz.legal_name for biz in listed} == {"Alpha LLC", "Beta LLC"}


def test_list_excludes_other_users_businesses(service, service_b):
    mine = service.create(_valid_input(legal_name="Mine LLC")).value
    service_b.create(_valid_input(legal_name="Theirs LLC"))

    listed = service.list()
    assert [biz.id for biz in listed] == [mine.id]
    assert all(biz.user_id == USER_A for biz in listed)


# --- Get (Req 3.1-3.3) -------------------------------------------------------


def test_get_owned_returns_record(service):
    biz = service.create(_valid_input()).value
    result = service.get(biz.id)
    assert result.is_ok
    assert result.value.id == biz.id
    assert result.value.legal_name == biz.legal_name


def test_get_unknown_is_not_found(service):
    result = service.get("does-not-exist")
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_get_cross_user_is_not_found(service, service_b):
    # Seed a business under user B, try to read it as user A.
    theirs = service_b.create(_valid_input(legal_name="Theirs LLC")).value
    result = service.get(theirs.id)
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


# --- Update (Req 4.1-4.4) ----------------------------------------------------


def test_update_owned_applies_changes(service):
    biz = service.create(_valid_input()).value

    updated = service.update(
        biz.id,
        _valid_input(
            legal_name="Renamed Co LLC",
            entity_type="s_corporation",
            ein="99-8887776",
            formation_state="CA",
            tax_year_end="03-31",
            note="now an s-corp",
        ),
    )
    assert updated.is_ok
    out = updated.value
    assert out.id == biz.id
    assert out.legal_name == "Renamed Co LLC"
    assert out.entity_type == "s_corporation"
    assert out.ein == "99-8887776"
    assert out.formation_state == "CA"
    assert out.tax_year_end == "03-31"
    assert out.note == "now an s-corp"


def test_update_preserves_created_at_and_refreshes_updated_at(service):
    biz = service.create(_valid_input()).value

    updated = service.update(biz.id, _valid_input(legal_name="New Name LLC")).value
    assert updated.created_at == biz.created_at
    assert updated.updated_at != biz.created_at

    # The change is persisted and readable via get.
    fetched = service.get(biz.id).value
    assert fetched.legal_name == "New Name LLC"
    assert fetched.created_at == biz.created_at


def test_update_stores_ein_verbatim(service):
    biz = service.create(_valid_input(ein="11-1111111")).value
    updated = service.update(biz.id, _valid_input(ein="22 222 2222")).value
    assert updated.ein == "22 222 2222"
    assert service.get(biz.id).value.ein == "22 222 2222"


@pytest.mark.parametrize("bad_name", ["", "   ", "\n\t"])
def test_update_rejects_blank_legal_name(service, bad_name):
    biz = service.create(_valid_input()).value
    result = service.update(biz.id, _valid_input(legal_name=bad_name))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "legal_name"
    # The original record is unchanged.
    assert service.get(biz.id).value.legal_name == "Maple Holdings LLC"


@pytest.mark.parametrize("bad_type", ["", "LLC", "nonsense"])
def test_update_rejects_invalid_entity_type(service, bad_type):
    biz = service.create(_valid_input()).value
    result = service.update(biz.id, _valid_input(entity_type=bad_type))
    assert not result.is_ok
    assert result.error.kind == "validation"
    assert result.error.field == "entity_type"
    assert service.get(biz.id).value.entity_type == "llc"


def test_update_unknown_is_not_found(service):
    result = service.update("does-not-exist", _valid_input())
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"


def test_update_cross_user_is_not_found(service, service_b):
    theirs = service_b.create(_valid_input(legal_name="Theirs LLC")).value
    result = service.update(theirs.id, _valid_input(legal_name="Hijacked LLC"))
    assert not result.is_ok
    assert result.error.kind == "not_found"
    assert result.error.field == "business_id"
    # User B's record is untouched.
    assert service_b.get(theirs.id).value.legal_name == "Theirs LLC"


# --- owns() ------------------------------------------------------------------


def test_owns_true_for_owned_business(service):
    biz = service.create(_valid_input()).value
    assert service.owns(biz.id) is True


def test_owns_false_for_unknown_business(service):
    assert service.owns("does-not-exist") is False


def test_owns_false_cross_user(service, service_b):
    theirs = service_b.create(_valid_input()).value
    assert service.owns(theirs.id) is False
