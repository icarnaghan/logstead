"""Property-based test for Schedule E replace-on-reimport (task 5.3).

# Feature: schedule-e-import, Property 3: replace-on-reimport is scoped and residue-free

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6

For *any* initial import across several ``(Property, Tax_Year)`` pairs (with
some user-tracked transactions mixed into the same years) followed by *any*
re-import for a randomized **subset** of those properties (same tax year), the
``ImportService`` replace is **scoped** and **residue-free**:

* **Included pairs** (present in the re-import): the surviving imported rows for
  that pair equal **exactly** the re-import's non-zero lines — prior imported
  rows are removed, and a line dropped to zero leaves **no** surviving imported
  row (Req 8.1, 8.2, 8.5, 8.6).
* **Omitted pairs** (absent from the re-import): every prior imported row is
  **byte-for-byte unchanged** — an omitted property is never queried, deleted,
  or rewritten (Req 8.3).
* **User-tracked transactions** (``imported = False``) across *all* properties
  are **byte-for-byte unchanged** — the replace never selects or touches a
  user-tracked row (Req 8.4).

Each example provisions its own moto-backed single table (base + GSI1 for
property rows + GSI2 for tax-year transaction queries) and an S3 bucket,
mirroring the existing service-test fixtures. The before/after oracle is a raw
DynamoDB ``scan`` snapshot keyed by ``(PK, SK)``, so it observes every stored
row regardless of partition. Per-example table + bucket provisioning varies
run-to-run, so the deadline is disabled while ``max_examples`` is held at 100.
"""

from __future__ import annotations

from decimal import Decimal

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
from logstead.models.transaction import TransactionInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.property import PropertyService
from logstead.services.schedule_e_import import ImportService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER_ID = "user-sub-1"
TAX_YEAR = 2023

# The importable Schedule E lines (income 3-4, expense 5-17, Other 19); Line 18
# (Depreciation) is intentionally never importable (Req 5.1).
_ALL_LINES = [3, 4, *range(5, 18), 19]

# A user-tracked transaction uses a real catalog category id (never carries the
# imported marker). A small spread across income/expense is enough.
_USER_CATEGORY_IDS = ["rents-received", "repairs", "supplies", "utilities"]


# --- Table / snapshot helpers (match the existing service-test fixtures) -----


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
    (property rows, imported transaction rows, and user-tracked transaction
    rows), giving a whole-table "unchanged" oracle.
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


def _imported_rows_for(ddb, property_id: str) -> dict[tuple[str, str], dict]:
    """Raw rows under a property's transaction partition that are imported."""
    pk = keys.property_scoped_pk(property_id)
    rows: dict[tuple[str, str], dict] = {}
    for (row_pk, sk), item in _scan_all(ddb).items():
        if row_pk != pk or not sk.startswith(keys.TXN_PREFIX):
            continue
        if item.get("imported", {}).get("BOOL", False):
            rows[(row_pk, sk)] = item
    return rows


# --- Hypothesis strategies ---------------------------------------------------
#
# A "line map" is {schedule_e_line: non-zero amount}. We draw a subset of the
# importable lines and give each a positive two-decimal amount so that an entry
# always has at least one non-zero line (validation requires it; Req 9.4).


def _amount() -> st.SearchStrategy[str]:
    """A positive two-decimal money string (strictly > 0.00)."""
    return st.integers(min_value=1, max_value=9_999_999).map(
        lambda cents: f"{Decimal(cents) / 100:.2f}"
    )


def _line_map(min_lines: int = 1) -> st.SearchStrategy[dict[int, str]]:
    """A non-empty mapping of a random line subset to positive amounts."""
    return st.lists(
        st.sampled_from(_ALL_LINES), min_size=min_lines, max_size=len(_ALL_LINES), unique=True
    ).flatmap(
        lambda lines: st.fixed_dictionaries(
            {line: _amount() for line in lines}
        )
    )


@st.composite
def _scenario(draw):
    """Draw a full two-phase scenario.

    Returns:
      * ``initial`` — per-property line maps for the first import (one per
        property, each non-empty).
      * ``reimport_subset`` — the subset of property indices included in the
        re-import, each with its new line map (may drop prior lines by omission
        and may set brand-new lines; at least one included so a replace happens).
      * ``user_tracked`` — a list of (property_index, category_id, amount) for
        user-tracked rows seeded in the same year across random properties.
    """
    property_count = draw(st.integers(min_value=2, max_value=4))

    # Phase 1: every property gets a non-empty initial import.
    initial = [draw(_line_map(min_lines=1)) for _ in range(property_count)]

    # Phase 2: choose a non-empty subset of properties to re-import.
    included = draw(
        st.lists(
            st.integers(min_value=0, max_value=property_count - 1),
            min_size=1,
            max_size=property_count,
            unique=True,
        )
    )
    # Each included property gets a fresh non-empty line map. Because it is drawn
    # independently of the initial map, some prior lines are naturally dropped
    # (omission == dropped to zero) and some new lines appear.
    reimport_subset = {idx: draw(_line_map(min_lines=1)) for idx in included}

    # Some user-tracked transactions (imported=False) in the same year, spread
    # across random properties (including possibly a re-imported one).
    user_tracked = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=property_count - 1),
                st.sampled_from(_USER_CATEGORY_IDS),
                _amount(),
            ),
            min_size=0,
            max_size=6,
        )
    )

    return {
        "property_count": property_count,
        "initial": initial,
        "reimport_subset": reimport_subset,
        "user_tracked": user_tracked,
    }


def _lines(line_map: dict[int, str]) -> list[LineAmountInput]:
    """Build LineAmountInputs for a {line: amount} map (Line 19 gets a desc)."""
    out: list[LineAmountInput] = []
    for line in sorted(line_map):
        description = "User note" if line == 19 else None
        out.append(
            LineAmountInput(
                schedule_e_line=line, amount=line_map[line], description=description
            )
        )
    return out


# Deadline disabled: each example provisions a fresh moto table + S3 bucket
# whose setup time varies run-to-run and is unrelated to the replace behavior.
@settings(deadline=None, max_examples=100)
@given(scenario=_scenario())
# Feature: schedule-e-import, Property 3: replace-on-reimport is scoped and residue-free
def test_reimport_is_scoped_and_residue_free(scenario: dict) -> None:
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        _create_table(ddb)
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        repo = DynamoRepository(ddb, TABLE_NAME)
        files = S3FileAdapter(s3, BUCKET)
        user = UserContext(user_id=USER_ID)
        service = ImportService(repo, user, files)
        txn_svc = TransactionService(repo, files)
        properties = PropertyService(repo, user)

        initial = scenario["initial"]
        reimport_subset = scenario["reimport_subset"]
        user_tracked = scenario["user_tracked"]

        # --- Seed properties -------------------------------------------------
        property_ids: list[str] = []
        for n in range(scenario["property_count"]):
            created = properties.create(
                PropertyInput(name=f"Property {n}", address_text=f"{n} Main St")
            )
            assert created.is_ok
            property_ids.append(created.value.id)

        # --- Phase 1: initial import for every property ----------------------
        first = service.import_schedule_e(
            ImportSubmission(
                tax_year=TAX_YEAR,
                entries=[
                    PropertyEntryInput(
                        property_id=property_ids[n], lines=_lines(initial[n])
                    )
                    for n in range(scenario["property_count"])
                ],
            )
        )
        assert first.is_ok

        # --- Seed user-tracked transactions in the same year -----------------
        user_tracked_ids: set[str] = set()
        for idx, category_id, amount in user_tracked:
            created = txn_svc.create(
                TransactionInput(
                    property_id=property_ids[idx],
                    date=f"{TAX_YEAR}-06-15",
                    amount=Decimal(amount),
                    type="income" if category_id == "rents-received" else "expense",
                    category_id=category_id,
                    description=None,
                )
            )
            assert created.is_ok
            assert created.value.imported is False
            user_tracked_ids.add(created.value.id)

        # Snapshot the entire table immediately before the re-import.
        before = _scan_all(ddb)

        # Capture the imported rows for omitted pairs so we can assert they are
        # byte-for-byte unchanged afterward.
        omitted_indices = [
            n for n in range(scenario["property_count"]) if n not in reimport_subset
        ]
        omitted_imported_before = {
            property_ids[n]: _imported_rows_for(ddb, property_ids[n])
            for n in omitted_indices
        }

        # --- Phase 2: re-import a subset of properties -----------------------
        result = service.import_schedule_e(
            ImportSubmission(
                tax_year=TAX_YEAR,
                entries=[
                    PropertyEntryInput(
                        property_id=property_ids[idx], lines=_lines(line_map)
                    )
                    for idx, line_map in reimport_subset.items()
                ],
            )
        )
        assert result.is_ok

        after = _scan_all(ddb)

        # --- Assertion 1: included pairs == exactly the re-import's lines ----
        for idx, line_map in reimport_subset.items():
            property_id = property_ids[idx]
            imported = _imported_rows_for(ddb, property_id)
            by_line = {
                int(item["scheduleELine"]["N"]): item for item in imported.values()
            }
            # Exactly the re-import's non-zero lines survive — no more, no less.
            assert set(by_line) == set(line_map), (
                f"property {idx}: imported lines {sorted(by_line)} != "
                f"re-import lines {sorted(line_map)}"
            )
            # Each surviving imported row carries exactly the re-import amount
            # and the imported marker; no residue from the replaced set remains.
            for line, raw_amount in line_map.items():
                row = by_line[line]
                assert row["imported"]["BOOL"] is True
                assert Decimal(row["amount"]["S"]) == Decimal(raw_amount)

        # --- Assertion 2: omitted pairs byte-for-byte unchanged --------------
        for property_id, prior in omitted_imported_before.items():
            now = _imported_rows_for(ddb, property_id)
            assert now == prior

        # --- Assertion 3: every user-tracked row byte-for-byte unchanged -----
        # Locate user-tracked rows in both snapshots by id and compare raw items.
        def _user_rows(snapshot: dict) -> dict[str, dict]:
            found: dict[str, dict] = {}
            for item in snapshot.values():
                if (
                    item["SK"]["S"].startswith(keys.TXN_PREFIX)
                    and not item.get("imported", {}).get("BOOL", False)
                    and item.get("id", {}).get("S") in user_tracked_ids
                ):
                    found[item["id"]["S"]] = item
            return found

        user_before = _user_rows(before)
        user_after = _user_rows(after)
        assert set(user_before) == user_tracked_ids
        assert user_after == user_before
