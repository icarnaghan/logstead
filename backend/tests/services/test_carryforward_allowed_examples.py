"""Hand-built example tests — carryforward allowed-loss reconciliation.

# Feature: carryforward-allowed-loss, example-based (unit) tests
# Validates: Requirements 3.1, 3.3, 3.7, 4.5, 7.1

These are *example* tests (plain ``pytest``, not Hypothesis): they drive the
real, moto-backed, composed :class:`CarryforwardService` over a deterministic
multi-year fixture built from real transactions and assert the exact
``expected_carryforward`` / ``allowed_loss`` / ``fully_allowed`` / ``status``
per year, plus that the allowed reductions roll the running balance onto later
years correctly (the delta shows up downstream).

The moto composition mirrors ``_moto_service()`` in
``test_carryforward_running_balance_property.py``: an isolated single-table
DynamoDB (base + GSI1 + GSI2) and an S3 bucket, with the service composed
exactly as the carryforward route composes it — ``CarryforwardService(repo,
USER, reports, properties, transactions, depreciation)`` — so the shared
``derive_data_years`` helper picks up the transaction years.

Net direction (grounding, from ``services/report.py``): a property's
Schedule_E ``net`` is ``total_income - total_expenses`` (expenses include Line
18 depreciation). An income line (``rents-received``) raises income; an expense
line (``repairs``) raises expenses. So a single expense transaction of ``X`` in
a year produces a Schedule_E_Net of ``-X`` (a loss of magnitude ``X``), and a
single income transaction of ``X`` produces ``+X`` (a gain). One transaction
per year keeps every year's net exact and the roll-forward hand-checkable.

Structured so later tasks (3.5 read-modify-write sibling examples, and 5.3 the
2010 acceptance scenario) can append additional ``test_*`` functions cleanly:
the moto fixture (``_moto_service``), the resource constants, and the two
small per-transaction helpers below are shared module-level seams; each test
builds its own properties/transactions inside a fresh ``_moto_service()``
context so the examples never share mutable state.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.carryforward import CarryforwardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields ``(service, properties, transactions)`` composed exactly as the
    carryforward route composes the service — ``CarryforwardService(repo, USER,
    reports, properties, transactions, depreciation)`` — bound to freshly
    created resources so each example runs against a clean store. Mirrors
    ``_moto_service()`` in ``test_carryforward_running_balance_property.py``.
    """
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)
        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        depreciation = DepreciationService(repo)
        reports = ReportingService(transactions, depreciation, properties)
        service = CarryforwardService(
            repo, USER, reports, properties, transactions, depreciation
        )
        yield service, properties, transactions


def _create_property(properties: PropertyService, name: str) -> str:
    """Create one single-family property and return its id (asserting ok)."""
    created = properties.create(
        PropertyInput(
            name=name,
            address_text=f"{name} St",
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    return created.value.id


def _add_loss(
    transactions: TransactionService, pid: str, year: int, magnitude: str
) -> None:
    """Add one in-year expense so the year's Schedule_E_Net is ``-magnitude``.

    A single ``repairs`` expense of ``magnitude`` makes ``net == total_income -
    total_expenses == -magnitude`` (a loss of that magnitude).
    """
    result = transactions.create(
        TransactionInput(
            property_id=pid,
            date=f"{year:04d}-06-15",
            amount=Decimal(magnitude),
            type="expense",
            category_id="repairs",
        )
    )
    assert result.is_ok, result.error


def _add_gain(
    transactions: TransactionService, pid: str, year: int, magnitude: str
) -> None:
    """Add one in-year income line so the year's Schedule_E_Net is ``+magnitude``.

    A single ``rents-received`` income line of ``magnitude`` makes ``net ==
    +magnitude`` (a gain of that magnitude).
    """
    result = transactions.create(
        TransactionInput(
            property_id=pid,
            date=f"{year:04d}-06-15",
            amount=Decimal(magnitude),
            type="income",
            category_id="rents-received",
        )
    )
    assert result.is_ok, result.error


def _by_year(summary) -> dict[int, object]:
    """Index the reconciled years by ``tax_year`` for direct lookup."""
    return {row.tax_year: row for row in summary.years}


def test_reconcile_mixed_allowed_fixture() -> None:
    """Exact per-year reconciliation over a deterministic mixed fixture.

    Fixture (single property, one transaction per year so every net is exact),
    with an Opening_Balance of ``150.00``:

    * 2020 — loss ``-1000.00``, PARTIALLY allowed ``400.00`` → suspended
      ``600.00``; reported carry-in ``150.00`` (= opening) → ``ok``.
    * 2021 — loss ``-500.00``, FULLY allowed (flag on, no explicit amount) →
      suspended ``0.00``; reported carry-in ``999.00`` (expected ``750.00``)
      → ``mismatch``, drift ``+249.00``.
    * 2022 — loss ``-300.00``, allowed ``100.00`` set but NO reported value →
      suspended ``200.00``; ``reported_carryforward`` absent, status
      ``unreported``.
    * 2023 — gain ``+250.00`` absorbing prior balance; reported carry-in
      ``950.00`` (= 2022's carry-out) → ``ok``.

    Reported values are the Form 8582 "Prior years unallowed losses"
    (carry-in); ``expected_carryforward`` is the carry-out.

    Hand-checked running balance (starts at the ``150.00`` opening):

    ===== ========= ========= ========= ======== ==========
    year  net       allowed   suspended carry-in carry-out
    ===== ========= ========= ========= ======== ==========
    2020  -1000.00  400.00    600.00    150.00   750.00
    2021   -500.00  500.00*   0.00      750.00   750.00
    2022   -300.00  100.00    200.00    750.00   950.00
    2023   +250.00  n/a       n/a       950.00   700.00
    ===== ========= ========= ========= ======== ==========

    \\*2021's effective allowed equals its current Loss_Magnitude (500.00)
    because Fully_Allowed is on, even though no explicit amount is stored.

    The allowed reductions (400.00 + 500.00 + 100.00 == 1000.00 total) roll
    forward: without them the 2023 balance would be
    ``150 + 1000 + 500 + 300 - 250 == 1700.00``; with them it is ``700.00`` — a
    ``1000.00`` delta visible downstream at 2023 (asserted explicitly below).

    Validates: Requirements 3.1, 3.3, 3.7, 4.5, 7.1
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "Mixed")

        _add_loss(transactions, pid, 2020, "1000.00")
        _add_loss(transactions, pid, 2021, "500.00")
        _add_loss(transactions, pid, 2022, "300.00")
        _add_gain(transactions, pid, 2023, "250.00")

        # Non-zero opening balance carried into the earliest reconciled year.
        assert service.set_opening_balance("150.00").is_ok

        # 2020 — partial allowance.
        assert service.set_allowed_loss(2020, "400.00").is_ok
        assert service.set_reported(2020, "150.00").is_ok

        # 2021 — fully allowed via the flag (no explicit amount), mismatched
        # reported value.
        assert service.set_fully_allowed(2021, True).is_ok
        assert service.set_reported(2021, "999.00").is_ok

        # 2022 — allowed data set, deliberately NO reported value.
        assert service.set_allowed_loss(2022, "100.00").is_ok

        # 2023 — gain year, reported matches expected.
        assert service.set_reported(2023, "950.00").is_ok

        summary = service.reconcile()

        assert summary.opening_balance == Decimal("150.00")
        assert summary.has_data is True
        rows = _by_year(summary)
        assert sorted(rows) == [2020, 2021, 2022, 2023]

        # --- 2020: partially allowed loss ---------------------------------
        y2020 = rows[2020]
        assert y2020.schedule_e_net == Decimal("-1000.00")
        assert y2020.allowed_loss == Decimal("400.00")
        assert y2020.fully_allowed is False
        assert y2020.expected_carryforward == Decimal("750.00")
        assert y2020.expected_carry_in == Decimal("150.00")
        assert y2020.reported_carryforward == Decimal("150.00")
        assert y2020.drift == Decimal("0.00")
        assert y2020.status == "ok"

        # --- 2021: fully allowed loss (flag on, amount absent → 0.00) ------
        y2021 = rows[2021]
        assert y2021.schedule_e_net == Decimal("-500.00")
        assert y2021.allowed_loss == Decimal("0.00")
        assert y2021.fully_allowed is True
        # Fully allowed → suspended 0.00 → balance unchanged at 750.00.
        assert y2021.expected_carryforward == Decimal("750.00")
        assert y2021.expected_carry_in == Decimal("750.00")
        assert y2021.reported_carryforward == Decimal("999.00")
        assert y2021.drift == Decimal("249.00")
        # Chain value = 2020 step on 2020's reported 150 = 150 + 600 = 750 != 999.
        assert y2021.status == "mismatch"

        # --- 2022: allowed set, reported ABSENT ---------------------------
        y2022 = rows[2022]
        assert y2022.schedule_e_net == Decimal("-300.00")
        assert y2022.allowed_loss == Decimal("100.00")
        assert y2022.fully_allowed is False
        # suspended = 300 - 100 = 200 → balance 750 + 200 = 950.00.
        assert y2022.expected_carryforward == Decimal("950.00")
        assert y2022.reported_carryforward is None
        assert y2022.status == "unreported"

        # --- 2023: gain absorbs prior balance -----------------------------
        y2023 = rows[2023]
        assert y2023.schedule_e_net == Decimal("250.00")
        assert y2023.allowed_loss == Decimal("0.00")
        assert y2023.fully_allowed is False
        # balance = max(950 - 250, 0) = 700.00.
        assert y2023.expected_carryforward == Decimal("700.00")
        assert y2023.expected_carry_in == Decimal("950.00")
        assert y2023.reported_carryforward == Decimal("950.00")
        assert y2023.status == "ok"

        # --- The allowed reductions roll forward onto 2023 ----------------
        # Without any allowed data the balance would be
        # 150 + 1000 + 500 + 300 - 250 == 1700.00 at 2023; the 1000.00 of total
        # allowed reductions show up as the downstream delta (1700 - 700).
        total_allowed_delta = Decimal("1700.00") - y2023.expected_carryforward
        assert total_allowed_delta == Decimal("1000.00")

        # Every expected is a non-negative two-decimal Decimal.
        for row in summary.years:
            assert isinstance(row.expected_carryforward, Decimal)
            assert row.expected_carryforward >= Decimal("0.00")
            assert row.expected_carryforward.as_tuple().exponent == -2


def test_allowed_only_and_reported_only_coexist_across_years() -> None:
    """An allowed-only year and a reported-only year never interfere.

    Two non-contiguous loss years over a single property with a ``0.00``
    opening balance:

    * 2020 — loss ``-800.00``, ALLOWED-only: ``allowed_loss == 300.00`` is set
      but no reported value. Its reconciled row surfaces the stored allowed
      amount with ``reported_carryforward is None`` / ``unreported``, and its
      suspended portion (``800 - 300 == 500.00``) rolls onto the balance.
    * 2022 — loss ``-200.00``, REPORTED-only: a reported carry-in is set but no
      allowed data. Its row surfaces ``allowed_loss == 0.00`` /
      ``fully_allowed False`` and reconciles against the expected carry-in.

    Hand-checked balance (opening ``0.00``):

    * 2020: suspended ``500.00`` → carry-out ``500.00`` (allowed-only).
    * 2022: carry-in ``500.00``; full loss ``200.00`` (no allowed) → carry-out
      ``700.00`` (reported-only). Reported carry-in ``500.00`` → ``ok``.

    Setting allowed on one year and reported on the other leaves each year's
    other figure at its default — the two coexist without clobbering each other
    (Req 2.2-2.4, read-modify-write preserves siblings across distinct years).

    Validates: Requirements 3.1, 3.3, 4.5, 7.1
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "Coexist")

        _add_loss(transactions, pid, 2020, "800.00")
        _add_loss(transactions, pid, 2022, "200.00")

        # 2020 — allowed only (no reported).
        assert service.set_allowed_loss(2020, "300.00").is_ok
        # 2022 — reported only (no allowed).
        assert service.set_reported(2022, "500.00").is_ok

        summary = service.reconcile()
        rows = _by_year(summary)
        assert sorted(rows) == [2020, 2022]

        # 2020 — allowed set, reported absent.
        y2020 = rows[2020]
        assert y2020.schedule_e_net == Decimal("-800.00")
        assert y2020.allowed_loss == Decimal("300.00")
        assert y2020.fully_allowed is False
        # suspended = 800 - 300 = 500.00 → expected 500.00.
        assert y2020.expected_carryforward == Decimal("500.00")
        assert y2020.reported_carryforward is None
        assert y2020.status == "unreported"

        # 2022 — reported set, allowed absent (defaults).
        y2022 = rows[2022]
        assert y2022.schedule_e_net == Decimal("-200.00")
        assert y2022.allowed_loss == Decimal("0.00")
        assert y2022.fully_allowed is False
        # carry-in 500.00 (2020's carry-out); full loss carries out: 700.00.
        assert y2022.expected_carry_in == Decimal("500.00")
        assert y2022.expected_carryforward == Decimal("700.00")
        assert y2022.reported_carryforward == Decimal("500.00")
        assert y2022.status == "ok"


# ---------------------------------------------------------------------------
# Task 3.5 — read-modify-write sibling preservation and delete-when-empty.
#
# Feature: carryforward-allowed-loss, example-based (unit) tests
# Validates: Requirements 2.2, 2.3, 2.4, 2.5, 4.6, 9.6
#
# These appended examples exercise the per-year item lifecycle directly: that
# the read-modify-write setters/clears preserve sibling attributes, that
# clearing the LAST remaining attribute deletes the item (so the year reverts
# to pure-computed and reconciles exactly as if never touched), that clearing
# an absent attribute is idempotent, and that per-year allowed data is confined
# to the authenticated user's partition (two-user isolation, Req 9.6).
#
# The shared ``_moto_service()`` fixture above yields ``(service, properties,
# transactions)`` — NOT the repo — and another appended test (task 5.3) also
# uses it, so its signature is left untouched. Where a raw per-year item must
# be inspected, the appended ``_moto_service_with_repo()`` context below
# duplicates the minimal moto setup and additionally yields the repo (plus a
# second user's service, for the isolation example). Most assertions, though,
# verify persistence through the SERVICE's observable ``reconcile()`` output —
# the documented delete-when-empty behavior shows up as a year reconciling with
# its defaults (allowed_loss ``0.00`` / fully_allowed ``False``), exactly as a
# never-touched loss year does.
# ---------------------------------------------------------------------------

from logstead.repository import keys  # noqa: E402


SECOND_USER = "user-xyz"


@contextlib.contextmanager
def _moto_service_with_repo():
    """Provision an isolated moto store and yield the repo + two users' services.

    Mirrors ``_moto_service()`` above but additionally yields the underlying
    :class:`DynamoRepository` (so an appended test can read the raw per-year
    item via ``keys.plcf_year_sk``) and a *second* user's composed
    ``CarryforwardService`` bound to the SAME resources (so a test can prove
    per-user partition isolation, Req 9.6). The shared single-``USER`` fixture
    is left untouched because task 5.3 also appends against it.

    Yields ``(service, properties, transactions, repo, service_other)`` where
    ``service`` / ``properties`` / ``transactions`` are scoped to ``USER`` and
    ``service_other`` is scoped to ``SECOND_USER``.
    """
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
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)
        repo = DynamoRepository(ddb, TABLE_NAME)

        properties = PropertyService(repo, USER)
        transactions = TransactionService(repo, S3FileAdapter(s3, BUCKET))
        depreciation = DepreciationService(repo)
        reports = ReportingService(transactions, depreciation, properties)
        service = CarryforwardService(
            repo, USER, reports, properties, transactions, depreciation
        )

        # A second, independent user composed over the SAME resources, so a
        # test can prove one user's allowed data never leaks to the other.
        properties_other = PropertyService(repo, SECOND_USER)
        reports_other = ReportingService(
            transactions, depreciation, properties_other
        )
        service_other = CarryforwardService(
            repo,
            SECOND_USER,
            reports_other,
            properties_other,
            transactions,
            depreciation,
        )

        yield service, properties, transactions, repo, service_other


def _raw_year_item(repo: DynamoRepository, user_id: str, year: int):
    """Read the raw per-year ``PLCF#<year>`` item for a user (or ``None``).

    Passes ``money_attrs={"amount", "allowedLoss"}`` so both money fields come
    back as two-decimal strings and ``fullyAllowed`` stays a boolean, exactly as
    the service reads it.
    """
    return repo.get_item(
        keys.user_pk(user_id),
        keys.plcf_year_sk(year),
        money_attrs={"amount", "allowedLoss"},
    )


def test_set_allowed_then_set_reported_both_persist() -> None:
    """Setting allowed then reported on a loss year persists BOTH figures.

    # Feature: carryforward-allowed-loss
    Single loss year 2020 (net ``-1000.00``), opening ``0.00``. Set
    ``allowed_loss == 400.00`` then ``set_reported("0.00")``: the
    read-modify-write setters never clobber the sibling, so the reconciled 2020
    row surfaces BOTH — ``allowed_loss == 400.00`` and
    ``reported_carryforward == 0.00`` (the carry-in, equal to the opening
    balance → ``ok``) — with the unallowed ``600.00`` as the carry-out.

    Validates: Requirements 2.2, 2.3
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "AllowedThenReported")
        _add_loss(transactions, pid, 2020, "1000.00")

        assert service.set_allowed_loss(2020, "400.00").is_ok
        assert service.set_reported(2020, "0.00").is_ok

        rows = _by_year(service.reconcile())
        y2020 = rows[2020]
        assert y2020.schedule_e_net == Decimal("-1000.00")
        # Both figures persisted — neither write clobbered the other.
        assert y2020.allowed_loss == Decimal("400.00")
        assert y2020.fully_allowed is False
        assert y2020.reported_carryforward == Decimal("0.00")
        # Carry-in is the opening 0.00; unallowed 1000 - 400 = 600.00 carries out.
        assert y2020.expected_carry_in == Decimal("0.00")
        assert y2020.expected_carryforward == Decimal("600.00")
        assert y2020.status == "ok"


def test_clear_reported_preserves_allowed_data() -> None:
    """Clearing reported on a year with allowed data preserves the allowed data.

    # Feature: carryforward-allowed-loss
    Loss year 2021 (net ``-500.00``) carries BOTH an explicit
    ``allowed_loss == 200.00`` and ``fully_allowed`` ... here we test the
    explicit-amount path: set ``allowed_loss == 200.00`` and
    ``set_reported("300.00")``, then ``clear_reported``. The year is still
    present with its allowed data preserved (``allowed_loss == 200.00``), and
    only the reported value reverts to ``None`` / ``unreported``. The raw item
    confirms ``allowedLoss`` survived and ``amount`` is gone.

    Validates: Requirements 2.4
    """
    with _moto_service_with_repo() as (service, properties, transactions, repo, _):
        pid = _create_property(properties, "ClearReportedKeepAllowed")
        _add_loss(transactions, pid, 2021, "500.00")

        assert service.set_allowed_loss(2021, "200.00").is_ok
        assert service.set_reported(2021, "300.00").is_ok
        assert service.clear_reported(2021).is_ok

        # Allowed data preserved; reported back to unreported.
        rows = _by_year(service.reconcile())
        y2021 = rows[2021]
        assert y2021.allowed_loss == Decimal("200.00")
        assert y2021.fully_allowed is False
        assert y2021.reported_carryforward is None
        assert y2021.status == "unreported"
        # Unallowed portion still carries: 500 - 200 = 300.00.
        assert y2021.expected_carryforward == Decimal("300.00")

        # The raw item still exists carrying allowedLoss but no amount.
        raw = _raw_year_item(repo, USER, 2021)
        assert raw is not None
        assert "allowedLoss" in raw
        assert raw["allowedLoss"] == Decimal("200.00")
        assert "amount" not in raw


def test_clear_reported_preserves_fully_allowed_flag() -> None:
    """Clearing reported on a fully-allowed year preserves the flag.

    # Feature: carryforward-allowed-loss
    Loss year 2021 (net ``-500.00``): turn on ``fully_allowed`` and set a
    reported value, then ``clear_reported``. The ``fully_allowed`` flag survives
    (the reconciled row still shows ``fully_allowed is True`` with
    ``allowed_loss == 0.00`` — fully-allowed is a flag, never snapshotted into
    the amount), suspended stays ``0.00`` so expected is ``0.00``, and the
    reported value reverts to ``None`` / ``unreported``.

    Validates: Requirements 2.4, 4.6
    """
    with _moto_service_with_repo() as (service, properties, transactions, repo, _):
        pid = _create_property(properties, "ClearReportedKeepFlag")
        _add_loss(transactions, pid, 2021, "500.00")

        assert service.set_fully_allowed(2021, True).is_ok
        assert service.set_reported(2021, "250.00").is_ok
        assert service.clear_reported(2021).is_ok

        rows = _by_year(service.reconcile())
        y2021 = rows[2021]
        assert y2021.fully_allowed is True
        # Flag is stored as a flag, not snapshotted into allowedLoss.
        assert y2021.allowed_loss == Decimal("0.00")
        assert y2021.reported_carryforward is None
        assert y2021.status == "unreported"
        # Fully allowed → suspended 0.00 → expected 0.00.
        assert y2021.expected_carryforward == Decimal("0.00")

        # Raw item carries fullyAllowed (BOOL) but no amount.
        raw = _raw_year_item(repo, USER, 2021)
        assert raw is not None
        assert raw.get("fullyAllowed") is True
        assert "amount" not in raw


def test_clear_last_allowed_attribute_deletes_item_year_pure_computed() -> None:
    """Clearing the LAST attribute deletes the item; the year reverts to computed.

    # Feature: carryforward-allowed-loss
    Loss year 2022 (net ``-300.00``) with ONLY an ``allowed_loss == 100.00``
    (no reported, not fully allowed). ``clear_allowed_loss`` removes the last
    remaining attribute, so the per-year item is deleted (delete-when-empty).
    Observed through reconcile, 2022 reverts to pure-computed — exactly as a
    never-touched loss year: ``allowed_loss == 0.00``, ``fully_allowed False``,
    the FULL loss (``300.00``) carries, and the row is ``unreported`` with no
    reported value. The raw item read confirms the delete.

    Validates: Requirements 2.5
    """
    with _moto_service_with_repo() as (service, properties, transactions, repo, _):
        pid = _create_property(properties, "DeleteWhenEmptyAllowed")
        _add_loss(transactions, pid, 2022, "300.00")

        assert service.set_allowed_loss(2022, "100.00").is_ok
        assert _raw_year_item(repo, USER, 2022) is not None  # item exists

        assert service.clear_allowed_loss(2022).is_ok

        # Item deleted — not left as a bare {taxYear} tombstone.
        assert _raw_year_item(repo, USER, 2022) is None

        # The year reconciles exactly as if never touched: pure-computed.
        rows = _by_year(service.reconcile())
        y2022 = rows[2022]
        assert y2022.schedule_e_net == Decimal("-300.00")
        assert y2022.allowed_loss == Decimal("0.00")
        assert y2022.fully_allowed is False
        assert y2022.reported_carryforward is None
        assert y2022.status == "unreported"
        # Full loss carries (no allowed data) → expected 300.00.
        assert y2022.expected_carryforward == Decimal("300.00")


def test_turning_off_last_fully_allowed_deletes_item_year_pure_computed() -> None:
    """Turning off the LAST attribute (fully_allowed) deletes the item.

    # Feature: carryforward-allowed-loss
    Loss year 2022 (net ``-300.00``) with ONLY ``fully_allowed`` on (no reported,
    no explicit amount). ``set_fully_allowed(2022, False)`` drops the sole
    attribute, so the item is deleted (sparse — ``False`` is never stored). The
    year reverts to pure-computed through reconcile: ``fully_allowed False``,
    ``allowed_loss 0.00``, full loss carries, ``unreported``.

    Validates: Requirements 2.5, 4.6
    """
    with _moto_service_with_repo() as (service, properties, transactions, repo, _):
        pid = _create_property(properties, "DeleteWhenEmptyFlag")
        _add_loss(transactions, pid, 2022, "300.00")

        assert service.set_fully_allowed(2022, True).is_ok
        assert _raw_year_item(repo, USER, 2022) is not None

        assert service.set_fully_allowed(2022, False).is_ok

        # Item deleted (sparse: False never stored, nothing else remains).
        assert _raw_year_item(repo, USER, 2022) is None

        rows = _by_year(service.reconcile())
        y2022 = rows[2022]
        assert y2022.fully_allowed is False
        assert y2022.allowed_loss == Decimal("0.00")
        assert y2022.reported_carryforward is None
        assert y2022.status == "unreported"
        assert y2022.expected_carryforward == Decimal("300.00")


def test_idempotent_clear_of_absent_attributes_succeeds() -> None:
    """Clearing an attribute that was never set succeeds without error.

    # Feature: carryforward-allowed-loss
    On a loss year 2023 (net ``-200.00``) that has NO per-year item at all,
    ``clear_reported``, ``clear_allowed_loss``, and ``set_fully_allowed(.., False)``
    each return ok (idempotent) and leave no item behind. The year reconciles as
    pure-computed throughout.

    Validates: Requirements 2.4, 2.5, 4.6
    """
    with _moto_service_with_repo() as (service, properties, transactions, repo, _):
        pid = _create_property(properties, "IdempotentClear")
        _add_loss(transactions, pid, 2023, "200.00")

        # No item exists yet.
        assert _raw_year_item(repo, USER, 2023) is None

        # Each clear of an absent attribute is a successful no-op.
        assert service.clear_reported(2023).is_ok
        assert service.clear_allowed_loss(2023).is_ok
        assert service.set_fully_allowed(2023, False).is_ok

        # Still no item; year is pure-computed.
        assert _raw_year_item(repo, USER, 2023) is None
        rows = _by_year(service.reconcile())
        y2023 = rows[2023]
        assert y2023.allowed_loss == Decimal("0.00")
        assert y2023.fully_allowed is False
        assert y2023.reported_carryforward is None
        assert y2023.expected_carryforward == Decimal("200.00")
        assert y2023.status == "unreported"


def test_two_user_partition_isolation_of_allowed_data() -> None:
    """One user's allowed data never leaks into another user's reconciliation.

    # Feature: carryforward-allowed-loss
    Both ``USER`` and ``SECOND_USER`` own a property with an identical loss year
    2020 (net ``-1000.00``). ``USER`` records ``allowed_loss == 400.00`` and
    reported carry-in ``0.00``; ``SECOND_USER`` touches nothing. ``USER``
    reconciles with the allowed reduction applied (carry-out ``600.00``, allowed
    ``400.00``, ``ok``); ``SECOND_USER`` reconciles pure-computed on their OWN loss (expected
    the full ``1000.00``, allowed ``0.00``, ``unreported``) — the allowed data is
    confined to ``USER``'s ``USER#<userId>`` partition and does not cross over.

    Validates: Requirements 9.6
    """
    with _moto_service_with_repo() as (
        service,
        properties,
        transactions,
        _repo,
        service_other,
    ):
        # USER's property + loss year.
        pid = _create_property(properties, "UserA")
        _add_loss(transactions, pid, 2020, "1000.00")

        # SECOND_USER's own property + identical-magnitude loss year.
        properties_other = PropertyService(_repo, SECOND_USER)
        created_other = properties_other.create(
            PropertyInput(
                name="UserB",
                address_text="UserB St",
                property_type="single_family",
            )
        )
        assert created_other.is_ok, created_other.error
        pid_other = created_other.value.id
        _add_loss(transactions, pid_other, 2020, "1000.00")

        # Only USER records allowed + reported data.
        assert service.set_allowed_loss(2020, "400.00").is_ok
        assert service.set_reported(2020, "0.00").is_ok

        # USER sees their allowed reduction applied.
        a_rows = _by_year(service.reconcile())
        a2020 = a_rows[2020]
        assert a2020.allowed_loss == Decimal("400.00")
        assert a2020.reported_carryforward == Decimal("0.00")
        assert a2020.expected_carryforward == Decimal("600.00")
        assert a2020.status == "ok"

        # SECOND_USER's reconciliation is pure-computed on their OWN loss — no
        # leak of USER's allowed/reported data across the partition boundary.
        b_rows = _by_year(service_other.reconcile())
        b2020 = b_rows[2020]
        assert b2020.schedule_e_net == Decimal("-1000.00")
        assert b2020.allowed_loss == Decimal("0.00")
        assert b2020.fully_allowed is False
        assert b2020.reported_carryforward is None
        assert b2020.expected_carryforward == Decimal("1000.00")
        assert b2020.status == "unreported"

# ---------------------------------------------------------------------------
# Task 5.3 — Property 7: the 2010 acceptance scenario reconciles to ok, both ways.
#
# Feature: carryforward-allowed-loss, Property 7: The 2010 acceptance scenario
# reconciles to ok, both ways
# Validates: Requirements 8.1, 8.2, 8.3
#
# The motivating real-world case carried into the requirements: the 2010 tax
# year had a Schedule_E_Net of -758.00, the ENTIRE loss was allowed on the
# filed return (Form 8582 Part II line 10 == 758.00), so the true end-of-year
# carryforward is 0.00. With a 0.00 opening balance the balance carried INTO
# 2010 is 0.00, so a correct allowed amount makes expected == 0.00 and a
# reported 0.00 reconciles to ``ok`` — instead of today's permanent false
# ``mismatch`` where the app suspends the whole 758.00.
#
# Each path builds the same single-property 2010 -758.00 loss inside its OWN
# fresh ``_moto_service()`` context (no shared mutable state), reusing the
# module-level ``_create_property`` / ``_add_loss`` / ``_by_year`` helpers.
# ---------------------------------------------------------------------------


def test_2010_acceptance_explicit_allowed_reconciles_ok() -> None:
    """2010 (-758.00) with an explicit allowed 758.00 → expected 0.00 → ok.

    # Feature: carryforward-allowed-loss, Property 7: The 2010 acceptance
    # scenario reconciles to ok, both ways

    Single property, 2010 a Loss_Year with ``schedule_e_net == -758.00``, a
    ``0.00`` opening balance (so the balance carried into 2010 is ``0.00``).

    * Path A (Req 8.1/8.2): ``set_allowed_loss(2010, "758.00")`` → reconcile →
      the whole loss is allowed, suspended ``max(758 - 758, 0) == 0.00``, so
      2010's ``expected_carryforward == 0.00``. Then
      ``set_reported(2010, "0.00")`` → reconcile → the reported ``0.00`` matches
      the expected ``0.00`` to the cent → ``status == "ok"``.

    Validates: Requirements 8.1, 8.2
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "Acceptance2010Explicit")
        _add_loss(transactions, pid, 2010, "758.00")

        # Opening balance 0.00 → balance carried into 2010 is 0.00.
        assert service.set_opening_balance("0.00").is_ok

        # --- Req 8.1: explicit allowed 758.00 → expected 0.00 -------------
        assert service.set_allowed_loss(2010, "758.00").is_ok

        rows = _by_year(service.reconcile())
        y2010 = rows[2010]
        assert y2010.schedule_e_net == Decimal("-758.00")
        assert y2010.allowed_loss == Decimal("758.00")
        assert y2010.fully_allowed is False
        # Entire loss allowed → suspended 0.00 → expected 0.00.
        assert y2010.expected_carryforward == Decimal("0.00")

        # --- Req 8.2: reported 0.00 → ok ----------------------------------
        assert service.set_reported(2010, "0.00").is_ok

        rows = _by_year(service.reconcile())
        y2010 = rows[2010]
        assert y2010.expected_carryforward == Decimal("0.00")
        assert y2010.reported_carryforward == Decimal("0.00")
        assert y2010.status == "ok"


def test_2010_acceptance_fully_allowed_reconciles_ok() -> None:
    """2010 (-758.00) fully allowed via the flag → expected 0.00 → ok.

    # Feature: carryforward-allowed-loss, Property 7: The 2010 acceptance
    # scenario reconciles to ok, both ways

    A SEPARATE fresh ``_moto_service()`` store building the same 2010 -758.00
    loss with a ``0.00`` opening balance.

    * Path B (Req 8.3): ``set_fully_allowed(2010, True)`` → reconcile → the
      effective allowed equals the current Loss_Magnitude ``758.00`` (no
      explicit amount stored, ``allowed_loss`` stays ``0.00`` — fully-allowed is
      a flag, never a snapshot), so suspended ``0.00`` and
      ``expected_carryforward == 0.00``, matching the explicit-758 case to the
      cent. Then ``set_reported(2010, "0.00")`` → ``status == "ok"``.

    Validates: Requirements 8.3
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "Acceptance2010Flag")
        _add_loss(transactions, pid, 2010, "758.00")

        assert service.set_opening_balance("0.00").is_ok

        # --- Req 8.3: fully-allowed flag → expected 0.00 (matches explicit) --
        assert service.set_fully_allowed(2010, True).is_ok

        rows = _by_year(service.reconcile())
        y2010 = rows[2010]
        assert y2010.schedule_e_net == Decimal("-758.00")
        assert y2010.fully_allowed is True
        # Flag is stored as a flag, not snapshotted into allowed_loss.
        assert y2010.allowed_loss == Decimal("0.00")
        # Effective allowed == current Loss_Magnitude 758.00 → suspended 0.00
        # → expected 0.00, exactly matching the explicit-758.00 allowed case.
        assert y2010.expected_carryforward == Decimal("0.00")

        # Reported 0.00 reconciles to ok.
        assert service.set_reported(2010, "0.00").is_ok
        rows = _by_year(service.reconcile())
        y2010 = rows[2010]
        assert y2010.expected_carryforward == Decimal("0.00")
        assert y2010.reported_carryforward == Decimal("0.00")
        assert y2010.status == "ok"


def test_2010_without_allowed_data_is_mismatch_showing_allowed_flips_it() -> None:
    """Without allowed data, 2011 expects 758.00 in and the reported 0.00 mismatches.

    # Feature: carryforward-allowed-loss, Property 7: The 2010 acceptance
    # scenario reconciles to ok, both ways

    A SEPARATE fresh ``_moto_service()`` store building the same 2010 -758.00
    loss (plus a small 2011 loss ``-100.00``) with a ``0.00`` opening balance,
    but recording NO allowed data — the pre-feature behavior. The whole
    ``758.00`` loss is suspended, so 2010's ``expected_carryforward == 758.00``
    (the carry-in expected on the 2011 return). The filed 2011 return shows
    ``0.00`` on the prior-years line, which is a ``mismatch`` (drift
    ``-758.00``; the chain value ``0.00 + 758.00`` is also
    ``758.00``, so reported ``0.00`` matches neither). 2010 itself reports
    carry-in ``0.00`` = opening → ``ok``. This makes explicit that it is the
    recorded allowed amount (the two cases above) that makes the 2011 line
    reconcile.

    Validates: Requirements 8.1, 8.2, 8.3
    """
    with _moto_service() as (service, properties, transactions):
        pid = _create_property(properties, "Acceptance2010NoAllowed")
        _add_loss(transactions, pid, 2010, "758.00")
        _add_loss(transactions, pid, 2011, "100.00")

        assert service.set_opening_balance("0.00").is_ok

        # No allowed data recorded; the filed returns show 0.00 on both
        # prior-years lines (the true-economic carry-in for 2010, and the
        # carry-in the filer reported for 2011 after allowing the whole loss).
        assert service.set_reported(2010, "0.00").is_ok
        assert service.set_reported(2011, "0.00").is_ok

        rows = _by_year(service.reconcile())
        y2010 = rows[2010]
        assert y2010.schedule_e_net == Decimal("-758.00")
        assert y2010.allowed_loss == Decimal("0.00")
        assert y2010.fully_allowed is False
        assert y2010.expected_carry_in == Decimal("0.00")
        # Pre-feature behavior: the whole loss is suspended → carry-out 758.00.
        assert y2010.expected_carryforward == Decimal("758.00")
        assert y2010.reported_carryforward == Decimal("0.00")
        assert y2010.status == "ok"

        y2011 = rows[2011]
        # 2011 expects 758.00 in; the reported 0.00 matches neither it nor the
        # chain value (0.00 + 758.00) → mismatch, drift -758.00.
        assert y2011.expected_carry_in == Decimal("758.00")
        assert y2011.reported_carryforward == Decimal("0.00")
        assert y2011.drift == Decimal("-758.00")
        assert y2011.status == "mismatch"
