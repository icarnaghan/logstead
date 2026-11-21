"""Property-based test for Schedule E Import per-user scoping isolation (task 5.1).

# Feature: schedule-e-import, Property 1: per-user scoping isolation

Validates: Requirements 2.3, 10.1, 10.3

For any two distinct authenticated users A and B and any randomized
``Import_Submission`` by A that includes a ``Property_Entry`` mapping to a
property owned by B (or to a non-existent property), ``ImportService`` rejects
the ENTIRE submission with a ``not_found`` error and creates, deletes, or
modifies NO transaction in either user's data scope. The companion undo entry
point, ``remove_imported_set``, is likewise ``not_found`` for a property not
owned by the caller and mutates nothing.

The oracle for "nothing changed in either scope" is a raw DynamoDB ``scan``
snapshot of the whole table taken after all legitimate setup and again after
every one of A's illegal attempts: the two snapshots must be byte-for-byte
identical. The scan observes every stored row across all partitions (both
users' property list rows and META mirrors, and any transaction rows), so it
catches any mutation, deletion, or cross-user write the submission could have
caused.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 for property rows + GSI2 for tax-year transaction queries) and a
moto S3 bucket, with each user's ``PropertyService`` + ``ImportService`` wired
router-style from the same ``UserContext``. Per-example table + bucket
provisioning is not instantaneous, so the deadline is disabled while
``max_examples`` is held at 100.
"""

from __future__ import annotations

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.schedule_e_import import (
    ImportSubmission,
    LineAmountInput,
    PropertyEntryInput,
)
from logstead.models.user import UserContext
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService
from logstead.services.schedule_e_import import ImportService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_A = "user-a"
USER_B = "user-b"

# The Schedule E lines a submission may legitimately carry: income 3-4,
# expense 5-17, and Line 19 (Other). Line 18 (Depreciation) is intentionally
# excluded so this test never conflates the ownership rejection with a Line 18
# validation rejection.
_IMPORTABLE_LINES = [3, 4, *range(5, 18), 19]


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
    — both users' property list rows, property META mirrors, and any
    transaction rows — giving a whole-table "nothing changed" oracle.
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


# A line amount: a positive, two-decimal money string (so the only reason A's
# submission can be rejected is the ownership/not-found check, never a bad
# amount). Kept to a modest range to stay well inside money precision.
_amount_strings = st.integers(min_value=1, max_value=5_000_000).map(
    lambda cents: f"{cents // 100}.{cents % 100:02d}"
)

# One line of a Property_Entry: a valid importable Schedule E line with a
# positive amount. (Line 18 is never generated.)
_lines = st.lists(
    st.builds(
        LineAmountInput,
        schedule_e_line=st.sampled_from(_IMPORTABLE_LINES),
        amount=_amount_strings,
    ),
    min_size=1,
    max_size=4,
)

# A four-digit tax year inside the service's accepted 1000..9999 band, so the
# submission can never be rejected for an invalid year.
_tax_years = st.integers(min_value=1000, max_value=9999)


@settings(deadline=None, max_examples=100)
@given(
    tax_year=_tax_years,
    b_lines=_lines,
    missing_lines=_lines,
    b_remove_year=_tax_years,
    missing_remove_year=_tax_years,
)
# Feature: schedule-e-import, Property 1: per-user scoping isolation
def test_import_rejects_cross_user_or_missing_property_and_mutates_nothing(
    tax_year: int,
    b_lines: list[LineAmountInput],
    missing_lines: list[LineAmountInput],
    b_remove_year: int,
    missing_remove_year: int,
) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)

        user_a = UserContext(user_id=USER_A)
        user_b = UserContext(user_id=USER_B)

        a_import = ImportService(repo, user_a, files)
        a_properties = PropertyService(repo, USER_A)
        b_properties = PropertyService(repo, USER_B)

        # --- Legitimate setup: B owns a property; A owns one of its own. ------
        b_created = b_properties.create(
            PropertyInput(name="B Rental", address_text="1 B St")
        )
        assert b_created.is_ok
        b_property_id = b_created.value.id

        a_created = a_properties.create(
            PropertyInput(name="A Rental", address_text="1 A St")
        )
        assert a_created.is_ok

        # A non-existent property id (owned by nobody). Fixed UUID-shaped string
        # so it never collides with the freshly minted ids above.
        missing_property_id = "00000000-0000-0000-0000-000000000000"

        # Snapshot after all legitimate setup. Every illegal attempt below must
        # leave this byte-for-byte unchanged.
        baseline = _scan_all(ddb)

        def assert_unchanged() -> None:
            assert _scan_all(ddb) == baseline

        # --- A imports against B's property -> not_found, nothing written. ----
        result_b = a_import.import_schedule_e(
            ImportSubmission(
                tax_year=tax_year,
                entries=[
                    PropertyEntryInput(property_id=b_property_id, lines=b_lines)
                ],
            )
        )
        assert not result_b.is_ok
        assert result_b.error.kind == "not_found"
        assert_unchanged()

        # --- A imports against a non-existent property -> not_found, no write. -
        result_missing = a_import.import_schedule_e(
            ImportSubmission(
                tax_year=tax_year,
                entries=[
                    PropertyEntryInput(
                        property_id=missing_property_id, lines=missing_lines
                    )
                ],
            )
        )
        assert not result_missing.is_ok
        assert result_missing.error.kind == "not_found"
        assert_unchanged()

        # --- A submits a not-owned column alongside an owned-by-A column, with
        # the NOT-OWNED column FIRST: ownership is checked per entry in order, so
        # the not-owned entry is rejected not_found before any write occurs and
        # nothing is created under A's own property either (per-user scoping +
        # ownership-before-write). Note: v1 does not roll back a column written
        # before a *later* column fails (design "Atomicity"), so this test only
        # asserts the guaranteed case where the offending column comes first. --
        a_second = a_properties.create(
            PropertyInput(name="A Rental Two", address_text="2 A St")
        )
        assert a_second.is_ok
        a_second_id = a_second.value.id
        # Re-baseline to include A's second property, then attempt the mixed
        # submission; it must not create any transaction under A's own property.
        baseline = _scan_all(ddb)

        result_mixed = a_import.import_schedule_e(
            ImportSubmission(
                tax_year=tax_year,
                entries=[
                    PropertyEntryInput(property_id=b_property_id, lines=b_lines),
                    PropertyEntryInput(property_id=a_second_id, lines=missing_lines),
                ],
            )
        )
        assert not result_mixed.is_ok
        assert result_mixed.error.kind == "not_found"
        assert_unchanged()

        # --- remove_imported_set against B's property -> not_found, no change. -
        remove_b = a_import.remove_imported_set(b_property_id, b_remove_year)
        assert not remove_b.is_ok
        assert remove_b.error.kind == "not_found"
        assert_unchanged()

        # --- remove_imported_set against a non-existent property -> not_found. -
        remove_missing = a_import.remove_imported_set(
            missing_property_id, missing_remove_year
        )
        assert not remove_missing.is_ok
        assert remove_missing.error.kind == "not_found"
        assert_unchanged()
