"""Property-based test for guarded delete all-or-nothing with cascade (task 6.2).

# Feature: business-entities, Property 2: Guarded delete is all-or-nothing with cascade

Validates: Requirements 5.1, 5.2, 5.4

For any randomized business / document / property-link state owned by the user,
:meth:`BusinessService.delete` on a target business is *all-or-nothing*:

* **Guarded (any property linked -> conflict, nothing mutated).** When one or
  more of the user's properties currently names the target business as its
  owner (``businessId`` equals the target), ``delete`` returns a ``conflict``
  failure and mutates *nothing* — every business row, every business-document
  metadata row, and every property link is byte-for-byte identical before and
  after the call (Requirement 5.2).

* **Cascade (no property linked -> full cascade).** When no property is linked
  to the target, ``delete`` succeeds and removes the target's two rows (the
  ``USER#<user> / BUSINESS#<id>`` list row and the ``BUSINESS#<id> / META``
  mirror) **and** every one of its ``DOC#`` document-metadata rows — a complete
  cascade (Requirements 5.1, 5.4). Businesses other than the target, their
  documents, and all property rows are left untouched.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) and a moto S3 bucket, with the Business and Property
services wired *router-style* so the delete-guard's ``linked_properties`` and
``set_business``'s ownership check both resolve against real collaborators. The
whole-table "mutates nothing" assertion is taken via a raw DynamoDB ``scan`` of
the moto table, so it observes every stored row regardless of partition.
Per-example table + bucket provisioning is not instantaneous, so the deadline is
disabled while ``max_examples`` is held at 100.
"""

from __future__ import annotations

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.business import BusinessInput
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-1"

# The target business ``delete`` is called on always exists; additional
# "other" businesses (never deleted) let the test confirm non-target rows are
# untouched by both the guarded-refusal and the successful cascade paths.
_OTHER_BUSINESS_COUNT = 2


def _create_table(ddb) -> None:
    """Provision the single-table Logstead schema (base + GSI1 + GSI2)."""
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


def _scan_all(ddb) -> dict[tuple[str, str], dict]:
    """Snapshot every row in the moto table, keyed by (PK, SK).

    Pages through a raw DynamoDB ``scan`` so the snapshot covers all partitions
    — business list rows, business META mirrors, document metadata rows, and
    both property rows — giving a whole-table "mutated nothing" oracle.
    """
    snapshot: dict[tuple[str, str], dict] = {}
    kwargs: dict = {"TableName": TABLE_NAME}
    while True:
        resp = ddb.scan(**kwargs)
        for item in resp.get("Items", []):
            pk = item["PK"]["S"]
            sk = item["SK"]["S"]
            snapshot[(pk, sk)] = item
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return snapshot


# Each property is linked to: None (unlinked), 0 (the target business), or a
# positive index into the "other" businesses pool (1.._OTHER_BUSINESS_COUNT).
_property_link = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=_OTHER_BUSINESS_COUNT),
)
# A random roster of properties with their link targets; include the empty
# roster so the "no properties at all" cascade case is exercised too.
_properties = st.lists(_property_link, min_size=0, max_size=6)
# How many documents the target business carries (including zero).
_doc_count = st.integers(min_value=0, max_value=5)


# Deadline disabled: each example provisions a fresh moto table + S3 bucket
# whose setup time varies run-to-run and is unrelated to the delete behavior.
@settings(deadline=None, max_examples=100)
@given(property_links=_properties, doc_count=_doc_count)
# Feature: business-entities, Property 2: Guarded delete is all-or-nothing with cascade
def test_guarded_delete_is_all_or_nothing_with_cascade(
    property_links: list[int | None],
    doc_count: int,
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)

        # Router-style wiring so the delete-guard's linked_properties and
        # set_business's ownership check both resolve.
        user = UserContext(user_id=USER_ID)
        biz = BusinessService(repo, user, files=files)
        prop = PropertyService(repo, user, business_service=biz)
        biz._property_service = prop

        # The target business (index 0) plus a pool of "other" businesses that
        # must never be touched by the delete under test.
        target = biz.create(
            BusinessInput(legal_name="Target LLC", entity_type="llc")
        )
        assert target.is_ok
        target_id = target.value.id

        other_ids: list[str] = []
        for i in range(_OTHER_BUSINESS_COUNT):
            created = biz.create(
                BusinessInput(legal_name=f"Other {i} LLC", entity_type="llc")
            )
            assert created.is_ok
            other_ids.append(created.value.id)

        # index 0 -> the target; index 1.._OTHER_BUSINESS_COUNT -> an "other".
        pool = [target_id, *other_ids]

        # Attach ``doc_count`` documents to the target business.
        for n in range(doc_count):
            up = biz.request_document_upload(
                target_id, f"doc-{n}.pdf", "application/pdf"
            )
            assert up.is_ok

        # Create the roster of properties and apply each one's link.
        any_linked_to_target = False
        for n, link in enumerate(property_links):
            created = prop.create(
                PropertyInput(name=f"Property {n}", address_text=f"{n} Main St")
            )
            assert created.is_ok
            if link is not None:
                target_business = pool[link]
                linked = prop.set_business(created.value.id, target_business)
                assert linked.is_ok
                if target_business == target_id:
                    any_linked_to_target = True

        before = _scan_all(ddb)

        result = biz.delete(target_id)

        if any_linked_to_target:
            # Guarded: conflict + absolutely nothing mutated (Req 5.2).
            assert not result.is_ok
            assert result.error.kind == "conflict"
            after = _scan_all(ddb)
            assert after == before
        else:
            # Cascade: success, and the target's rows + all its document
            # metadata rows are gone, with every other row untouched
            # (Req 5.1, 5.4).
            assert result.is_ok
            after = _scan_all(ddb)

            target_list_key = (
                keys.user_pk(USER_ID),
                keys.business_user_sk(target_id),
            )
            target_meta_key = (
                keys.business_scoped_pk(target_id),
                keys.business_meta_sk(),
            )
            removed = set(before) - set(after)

            # The two target business rows are removed.
            assert target_list_key in removed
            assert target_meta_key in removed

            # Every DOC# row under the target partition is removed (full
            # cascade) and none remains in the table.
            scoped_pk = keys.business_scoped_pk(target_id)
            before_doc_keys = {
                key
                for key in before
                if key[0] == scoped_pk
                and key[1].startswith(keys.business_document_list_prefix())
            }
            assert len(before_doc_keys) == doc_count
            assert before_doc_keys <= removed
            assert not any(
                key[0] == scoped_pk
                and key[1].startswith(keys.business_document_list_prefix())
                for key in after
            )

            # Nothing beyond the target's own rows was removed: the only keys
            # that disappeared are the two business rows plus its documents.
            assert removed == {target_list_key, target_meta_key} | before_doc_keys

            # Every surviving row is byte-for-byte unchanged (other businesses,
            # their rows, and all property rows are untouched).
            for key, item in after.items():
                assert item == before[key]
