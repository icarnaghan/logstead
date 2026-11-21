"""Property-based test for all-or-nothing Schedule E import validation (task 5.4).

# Feature: schedule-e-import, Property 4: all-or-nothing validation performs no mutation on any invalid submission

For any Import_Submission containing at least one invalid element,
``import_schedule_e`` must reject the whole submission with a failure that names
the offending entry/field (a structured dotted ``field`` path) AND must leave
the stored data byte-for-byte identical: no transaction created, deleted, or
modified, and no inline property created.

Each example provisions its own moto-backed single table (base + GSI1 for
property rows + GSI2 for the tax-year transaction partition) and an S3 bucket,
mirroring the existing service-test fixtures. One or more owned properties are
pre-seeded so a *valid* submission is possible — then exactly one fault is
injected so the all-or-nothing rule still trips. The oracle for "nothing
mutated" is a raw DynamoDB ``scan`` snapshot taken before and after the call:
the two whole-table snapshots must be equal (the strongest "created/deleted/
modified nothing" check, and it also catches any orphan inline property).

The injected fault is randomly one of:

* a negative line amount (Req 9.1),
* a non-monetary amount string (Req 9.2),
* an all-zero entry (Req 9.3/9.4),
* a missing / not-owned property mapping (Req 10.3),
* a duplicate property mapping across two entries (Req 2.5),
* a ``schedule_e_line == 18`` line (Req 5.1),
* an invalid four-digit tax year (Req 3.2).

Per-example table + bucket provisioning is not instantaneous, so the deadline is
disabled while ``max_examples`` is held at 100.
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
USER_ID = "user-sub-1"
OTHER_USER_ID = "user-sub-2"

# The Schedule E lines a submission may legitimately carry: income 3-4,
# expense 5-17, and Line 19 Other. Line 18 (Depreciation) is intentionally
# excluded (it is never importable).
_VALID_LINES = [3, 4, *range(5, 18), 19]


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

    Pages through a raw DynamoDB ``scan`` so the snapshot covers every partition
    — all property rows (base + GSI1 mirror) and any transaction rows — giving a
    whole-table "nothing mutated" oracle that also detects an orphan inline
    property.
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


# --- Generators --------------------------------------------------------------

# A valid two-decimal, strictly-positive money string, so a baseline entry is
# importable (and so an entry remains non-zero after a different fault is
# injected elsewhere).
_positive_money = st.integers(min_value=1, max_value=5_000_000).map(
    lambda cents: f"{cents // 100}.{cents % 100:02d}"
)

# A money string that is NOT a valid non-negative two-decimal value: either a
# negative amount or a non-monetary token. Used only for the amount faults.
_negative_money = st.integers(min_value=1, max_value=5_000_000).map(
    lambda cents: f"-{cents // 100}.{cents % 100:02d}"
)
_non_monetary = st.sampled_from(["abc", "1.2.3", "$100", "12,00", "ten", "NaN", ""])

# A valid four-digit tax year.
_valid_year = st.integers(min_value=1000, max_value=9999)
# An invalid "year" the service must reject (outside 1000-9999).
_invalid_year = st.one_of(
    st.integers(min_value=-50, max_value=999),
    st.integers(min_value=10000, max_value=20000),
)

# The fault to inject into an otherwise-valid submission.
_fault = st.sampled_from(
    [
        "negative_amount",
        "non_monetary_amount",
        "all_zero_entry",
        "not_owned_property",
        "duplicate_mapping",
        "line_18",
        "invalid_tax_year",
    ]
)


@st.composite
def _valid_entry(draw, property_id: str) -> PropertyEntryInput:
    """A valid entry on ``property_id`` with >= 1 non-zero line (never Line 18)."""
    lines_chosen = draw(
        st.lists(st.sampled_from(_VALID_LINES), min_size=1, max_size=4, unique=True)
    )
    lines = [
        LineAmountInput(schedule_e_line=line, amount=draw(_positive_money))
        for line in lines_chosen
    ]
    return PropertyEntryInput(property_id=property_id, lines=lines)


# --- The property ------------------------------------------------------------


# Deadline disabled: each example provisions a fresh moto table + S3 bucket
# whose setup time varies run-to-run and is unrelated to the validation
# behavior under test.
@settings(deadline=None, max_examples=100)
@given(
    data=st.data(),
    tax_year=_valid_year,
    fault=_fault,
)
# Feature: schedule-e-import, Property 4: all-or-nothing validation performs no mutation on any invalid submission
def test_invalid_submission_rejects_and_mutates_nothing(
    data: st.DataObject,
    tax_year: int,
    fault: str,
) -> None:
    """Validates: Requirements 9.1, 9.2, 9.3, 9.5, 10.3"""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        service = ImportService(repo, UserContext(user_id=USER_ID), files)
        owner = PropertyService(repo, USER_ID)

        # Pre-seed owned properties so a *valid* entry is possible; the injected
        # fault is what trips all-or-nothing, not an absence of valid data.
        prop_a = owner.create(
            PropertyInput(name="Maple Duplex", address_text="1 Main St")
        )
        prop_b = owner.create(
            PropertyInput(name="Oak Triplex", address_text="2 Oak St")
        )
        assert prop_a.is_ok and prop_b.is_ok
        prop_a_id = prop_a.value.id
        prop_b_id = prop_b.value.id

        # Start from a valid single-entry submission on an owned property.
        entries = [data.draw(_valid_entry(prop_a_id))]
        submission_year: int | None = tax_year

        # Inject exactly one fault. The field prefix we expect in the error.
        if fault == "negative_amount":
            line = data.draw(st.sampled_from(_VALID_LINES))
            entries[0].lines.append(
                LineAmountInput(
                    schedule_e_line=line, amount=data.draw(_negative_money)
                )
            )
            expected_field = f"entries[0].lines[{line}]"

        elif fault == "non_monetary_amount":
            # A non-blank, non-monetary token on a valid line. (Blank is treated
            # as zero and is NOT a fault, so empty string is excluded here.)
            token = data.draw(_non_monetary.filter(lambda s: s.strip() != ""))
            line = data.draw(st.sampled_from(_VALID_LINES))
            entries[0].lines.append(
                LineAmountInput(schedule_e_line=line, amount=token)
            )
            expected_field = f"entries[0].lines[{line}]"

        elif fault == "all_zero_entry":
            # A second entry (on a distinct owned property) whose every line is
            # zero/blank, so the entry has no non-zero line (Req 9.4).
            zero_lines = data.draw(
                st.lists(
                    st.sampled_from(_VALID_LINES),
                    min_size=1,
                    max_size=4,
                    unique=True,
                )
            )
            amounts = [
                data.draw(st.sampled_from(["0.00", "0", None, "", "   "]))
                for _ in zero_lines
            ]
            entries.append(
                PropertyEntryInput(
                    property_id=prop_b_id,
                    lines=[
                        LineAmountInput(schedule_e_line=line, amount=amount)
                        for line, amount in zip(zero_lines, amounts)
                    ],
                )
            )
            expected_field = "entries[1]"

        elif fault == "not_owned_property":
            # A second entry mapping to a property owned by a DIFFERENT user.
            other = PropertyService(repo, OTHER_USER_ID).create(
                PropertyInput(name="Theirs", address_text="9 Other St")
            )
            assert other.is_ok
            entries.append(
                PropertyEntryInput(
                    property_id=other.value.id,
                    lines=[
                        LineAmountInput(
                            schedule_e_line=3, amount=data.draw(_positive_money)
                        )
                    ],
                )
            )
            # Not-owned surfaces as not_found; no structured field prefix is
            # asserted beyond the kind for this fault.
            expected_field = None

        elif fault == "duplicate_mapping":
            # A second entry mapping to the SAME owned property as entry 0.
            entries.append(
                PropertyEntryInput(
                    property_id=prop_a_id,
                    lines=[
                        LineAmountInput(
                            schedule_e_line=4, amount=data.draw(_positive_money)
                        )
                    ],
                )
            )
            expected_field = "entries[1]"

        elif fault == "line_18":
            # Line 18 (Depreciation) is never importable (Req 5.1).
            entries[0].lines.append(
                LineAmountInput(
                    schedule_e_line=18, amount=data.draw(_positive_money)
                )
            )
            expected_field = "entries[0].lines[18]"

        elif fault == "invalid_tax_year":
            submission_year = data.draw(_invalid_year)
            expected_field = "tax_year"

        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown fault {fault!r}")

        submission = ImportSubmission(tax_year=submission_year, entries=entries)

        # Snapshot the whole table immediately before the call.
        before = _scan_all(ddb)

        result = service.import_schedule_e(submission)

        # 1. The submission is rejected (Req 9.5).
        assert not result.is_ok
        assert result.error.kind in ("validation", "not_found")
        # 2. The failure identifies the offending entry/field.
        assert result.error.field is not None
        if expected_field is not None:
            assert result.error.field == expected_field

        # 3. Stored data is byte-for-byte identical: no transaction created,
        #    deleted, or modified, and no inline property created.
        after = _scan_all(ddb)
        assert after == before
