"""Property-based test for cross-user scoping isolation (task 7.2).

# Feature: business-entities, Property 1: User scoping isolates all business data

Validates: Requirements 2.2, 3.3, 6.4, 13.1

For any two distinct users A and B and any randomized sequence of business,
document, and property-link operations performed *as A*, no
``BusinessService``/``PropertyService`` read or mutation performed *as B* ever
returns, modifies, or deletes a business, document, or property-business link
created by A:

* **Reads exclude / not-found A's records.** B's ``BusinessService.list`` and
  ``PropertyService.list`` never contain A's records; B's ``get`` (business),
  ``list_documents``, and ``linked_properties`` against A's business ids all
  return ``not_found`` (Requirements 2.2, 3.3, 6.4, 7.4, 13.1).

* **Mutations against A's ids are rejected and change nothing.** B's
  ``update``, ``delete``, ``request_document_upload``, and ``delete_document``
  against A's business ids return ``not_found``; B's ``set_business`` linking
  *B's own* property to *A's* business returns ``not_found`` (the ownership
  check in :meth:`PropertyService.set_business` sees A's business as unowned by
  B). None of these touch A's data.

The oracle for "A's data is unchanged" is a raw DynamoDB ``scan`` snapshot taken
after A finishes setup and again after every one of B's attempts: the two
snapshots must be byte-for-byte identical. The scan observes every stored row
across all partitions (business list rows, business META mirrors, document
metadata rows, and both property rows for A and B), so it catches any mutation,
deletion, or cross-user write B could have caused.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) and a moto S3 bucket, with each user's Business and
Property services wired *router-style* (each service pair shares one
``UserContext`` and resolves its collaborator after construction). Per-example
table + bucket provisioning is not instantaneous, so the deadline is disabled
while ``max_examples`` is held at 100.
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
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.business import BusinessService
from logstead.services.property import PropertyService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"


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
    — both users' business list rows, business META mirrors, document metadata
    rows, and all property rows — giving a whole-table "A's data unchanged"
    oracle.
    """
    snapshot: dict[tuple[str, str], dict] = {}
    kwargs: dict = {"TableName": TABLE_NAME}
    while True:
        resp = ddb.scan(**kwargs)
        for item in resp.get("Items", []):
            snapshot[(item["PK"]["S"], item["SK"]["S"])] = item
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return snapshot


def _wire(repo, files, user_id: str) -> tuple[BusinessService, PropertyService]:
    """Build a router-style BusinessService + PropertyService pair for a user.

    The two collaborators are cross-wired after construction so
    ``linked_properties`` (business→property) and ``set_business`` (ownership
    check) both resolve, exactly as the router wires them per request.
    """
    user = UserContext(user_id=user_id)
    biz = BusinessService(repo, user, files=files)
    prop = PropertyService(repo, user, business_service=biz)
    biz._property_service = prop
    return biz, prop


# A roster of businesses A creates, each with a document count. An empty roster
# is allowed so the "A owns nothing" case is also exercised. Each entry is the
# number of documents to attach to that business.
_a_businesses = st.lists(st.integers(min_value=0, max_value=3), min_size=0, max_size=4)
# A roster of properties A owns; each either unlinked (None) or linked to the
# i-th business A created (index into A's business roster).
_a_properties = st.lists(
    st.one_of(st.none(), st.integers(min_value=0, max_value=3)),
    min_size=0,
    max_size=4,
)


# Deadline disabled: each example provisions a fresh moto table + S3 bucket
# whose setup time varies run-to-run and is unrelated to the scoping behavior.
@settings(deadline=None, max_examples=100)
@given(a_businesses=_a_businesses, a_properties=_a_properties)
# Feature: business-entities, Property 1: User scoping isolates all business data
def test_user_scoping_isolates_all_business_data(
    a_businesses: list[int],
    a_properties: list[int | None],
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)

        a_biz, a_prop = _wire(repo, files, USER_A)
        b_biz, b_prop = _wire(repo, files, USER_B)

        # --- A sets up its businesses, documents, and property links ----------
        a_business_ids: list[str] = []
        a_document_ids: dict[str, list[str]] = {}
        for i, doc_count in enumerate(a_businesses):
            created = a_biz.create(
                BusinessInput(legal_name=f"A Entity {i} LLC", entity_type="llc")
            )
            assert created.is_ok
            business_id = created.value.id
            a_business_ids.append(business_id)
            doc_ids: list[str] = []
            for n in range(doc_count):
                up = a_biz.request_document_upload(
                    business_id, f"a-doc-{i}-{n}.pdf", "application/pdf"
                )
                assert up.is_ok
                doc_ids.append(up.value.document.id)
            a_document_ids[business_id] = doc_ids

        a_property_ids: list[str] = []
        for n, link in enumerate(a_properties):
            created = a_prop.create(
                PropertyInput(name=f"A Property {n}", address_text=f"{n} A St")
            )
            assert created.is_ok
            property_id = created.value.id
            a_property_ids.append(property_id)
            if link is not None and link < len(a_business_ids):
                linked = a_prop.set_business(property_id, a_business_ids[link])
                assert linked.is_ok

        # B owns one of its own properties, used to attempt an illegal link to
        # one of A's businesses via set_business.
        b_property_id: str | None = None
        created_b = b_prop.create(
            PropertyInput(name="B Property", address_text="1 B St")
        )
        assert created_b.is_ok
        b_property_id = created_b.value.id

        # Snapshot taken after all legitimate setup (A's writes + B's own
        # property). Every subsequent B attempt against A's ids must leave this
        # unchanged.
        baseline = _scan_all(ddb)

        def assert_unchanged() -> None:
            assert _scan_all(ddb) == baseline

        # --- B's list views never contain A's records (Req 2.2) ---------------
        b_business_list_ids = {biz.id for biz in b_biz.list()}
        assert all(bid not in b_business_list_ids for bid in a_business_ids)
        b_property_list_ids = {p.id for p in b_prop.list()}
        assert all(pid not in b_property_list_ids for pid in a_property_ids)
        assert_unchanged()

        # --- B's reads/mutations against each of A's business ids -------------
        for business_id in a_business_ids:
            # get -> not_found (Req 3.3)
            got = b_biz.get(business_id)
            assert not got.is_ok
            assert got.error.kind == "not_found"

            # list_documents -> not_found (never surfaces A's documents, Req 6.4)
            docs = b_biz.list_documents(business_id)
            assert not docs.is_ok
            assert docs.error.kind == "not_found"

            # linked_properties -> not_found (A's business is unowned by B)
            linked = b_biz.linked_properties(business_id)
            assert not linked.is_ok
            assert linked.error.kind == "not_found"

            # update -> not_found, nothing mutated (Req 4.4 scoping)
            updated = b_biz.update(
                business_id,
                BusinessInput(legal_name="Hijacked LLC", entity_type="llc"),
            )
            assert not updated.is_ok
            assert updated.error.kind == "not_found"

            # request_document_upload -> not_found, nothing mutated (Req 6.3/6.4)
            upload = b_biz.request_document_upload(
                business_id, "b-intruder.pdf", "application/pdf"
            )
            assert not upload.is_ok
            assert upload.error.kind == "not_found"

            # delete_document against each of A's real document ids -> not_found
            for document_id in a_document_ids[business_id]:
                del_doc = b_biz.delete_document(business_id, document_id)
                assert not del_doc.is_ok
                assert del_doc.error.kind == "not_found"

            # set_business: B links its OWN property to A's business -> not_found
            # (the ownership check sees A's business as unowned by B, Req 9.5).
            linked_attempt = b_prop.set_business(b_property_id, business_id)
            assert not linked_attempt.is_ok
            assert linked_attempt.error.kind == "not_found"

            # delete -> not_found, nothing mutated (Req 5.3 scoping)
            deleted = b_biz.delete(business_id)
            assert not deleted.is_ok
            assert deleted.error.kind == "not_found"

            # Every single attempt above left A's (and B's) data byte-for-byte
            # unchanged.
            assert_unchanged()

        # Final whole-table check: nothing B did touched any stored row.
        assert_unchanged()
