"""Property test — per-year item persistence round-trip for allowed data.

# Feature: carryforward-allowed-loss, Property 6: Persistence round-trip —
#   allowed data and reported value are independent, siblings never clobbered
# Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 2.4, 2.5, 4.1, 7.2

Design Property 6 — *Persistence round-trip; independence; siblings never
clobbered*: for any per-year ``PLCF#<year>`` item, writing then reading back
yields each of ``amount`` (Reported_Carryforward), ``allowedLoss``
(Allowed_Loss amount), and ``fullyAllowed`` (the Fully_Allowed flag) equal to
its normalized written value (two-decimal money for the amounts, a boolean for
the flag); setting or clearing any one of the three attributes preserves the
other two unchanged; clearing the last remaining attribute deletes the item
(``get_item`` returns ``None``); and an item written with only a reported value
(the pre-feature shape) reads back with ``allowed_loss == 0.00`` and
``fully_allowed == false`` and carries no ``allowedLoss``/``fullyAllowed``
stored keys.

This property is about the per-year item read-modify-write — not the full
report/property composition — so it exercises the persistence setters
(``set_reported`` / ``clear_reported`` / ``set_allowed_loss`` /
``clear_allowed_loss`` / ``set_fully_allowed``) directly and reads the raw
stored item back through the repository
(``repo.get_item(user_pk(USER), plcf_year_sk(year),
money_attrs={"amount", "allowedLoss"})``). However, ``set_allowed_loss`` and
``set_fully_allowed(True)`` validate against the year's net, so the target year
is provisioned as a real **loss year of a known magnitude M** — built via a
property + a single expense transaction exactly as
``test_carryforward_running_balance_property.py`` composes its moto stack — so
the allowed setters accept any amount in ``[0, M]``.

Each Hypothesis example provisions its own moto-backed single-table DynamoDB
(base + GSI1 + GSI2) plus an S3 bucket needed to construct the
``S3FileAdapter``, mirroring ``_moto_service()`` in
``test_carryforward_running_balance_property.py``. Per-example provisioning is
not instantaneous, so the deadline is disabled; the example count is held at 50.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from logstead.adapters.s3_files import S3FileAdapter
from logstead.models.property import PropertyInput
from logstead.models.transaction import TransactionInput
from logstead.repository import keys
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

# A single known tax year the loss transaction is dated within, well below the
# latest-completed-year cap so the year is always a real Data_Year.
_LOSS_YEAR = 2020

_MONEY_ATTRS = {"amount", "allowedLoss"}


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields ``(service, repo, properties, transactions)`` bound to freshly
    created resources so each Hypothesis example runs against a clean store. The
    service is composed exactly as the carryforward route composes it:
    ``CarryforwardService(repo, USER, reports, properties, transactions,
    depreciation)``.
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
        yield service, repo, properties, transactions


def _provision_loss_year(properties, transactions, magnitude: Decimal) -> None:
    """Make ``_LOSS_YEAR`` a loss year of exactly ``magnitude`` (a pure expense).

    One property with a single expense transaction of ``magnitude`` dated in the
    year makes the year's Schedule_E_Net ``-magnitude`` (net = income -
    expenses, with no income), so the Loss_Magnitude is ``magnitude``.
    """
    created = properties.create(
        PropertyInput(
            name="Prop",
            address_text="1 Main St",
            property_type="single_family",
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id
    result = transactions.create(
        TransactionInput(
            property_id=pid,
            date=f"{_LOSS_YEAR:04d}-06-15",
            amount=magnitude,
            type="expense",
            category_id="repairs",
            description=None,
        )
    )
    assert result.is_ok, result.error


def _raw_item(repo) -> dict | None:
    """Read the raw stored per-year item for ``_LOSS_YEAR``, money-parsed."""
    return repo.get_item(
        keys.user_pk(USER),
        keys.plcf_year_sk(_LOSS_YEAR),
        money_attrs=_MONEY_ATTRS,
    )


# --- Strategies --------------------------------------------------------------

# The Loss_Magnitude M for the year: a positive two-decimal money magnitude,
# large enough to leave room for a strictly-smaller allowed amount.
_loss_magnitude = st.decimals(
    min_value=Decimal("100.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A fraction in (0, 1] used to pick an allowed amount within [0, M]; combined
# with the magnitude below so the drawn allowed <= M always holds.
_fraction = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A non-negative two-decimal reported amount (independent of the loss; the
# reported value is not validated against the net).
_reported = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("1000000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: f"{d:.2f}")


def _allowed_within(magnitude: Decimal, fraction: Decimal) -> str:
    """A two-decimal allowed amount in ``[0, magnitude]`` as a money string."""
    allowed = (magnitude * fraction).quantize(Decimal("0.01"))
    if allowed > magnitude:
        allowed = magnitude
    return f"{allowed:.2f}"


# --- Property 6 : persistence round-trip; independence; siblings preserved ---


# Feature: carryforward-allowed-loss, Property 6: Persistence round-trip —
# allowed data and reported value are independent, siblings never clobbered
@settings(deadline=None, max_examples=50)
@given(
    magnitude=_loss_magnitude,
    fraction=_fraction,
    reported=_reported,
)
def test_per_year_item_persistence_round_trip_and_independence(
    magnitude: Decimal, fraction: Decimal, reported: str
) -> None:
    """Writing/reading each attribute round-trips; siblings never clobbered.

    Validates: Requirements 1.1, 1.2, 1.3, 1.4, 2.2, 2.3, 2.4, 2.5, 4.1, 7.2
    """
    with _moto_service() as (service, repo, properties, transactions):
        _provision_loss_year(properties, transactions, magnitude)

        allowed_str = _allowed_within(magnitude, fraction)
        allowed_money = Decimal(allowed_str)
        reported_money = Decimal(reported)

        # --- Round-trip: each attribute reads back its normalized value ------

        # amount (reported) alone.
        assert service.set_reported(_LOSS_YEAR, reported).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money  # two-decimal money (Req 1.6)
        assert "allowedLoss" not in item  # sibling absent (Req 2.2)
        assert "fullyAllowed" not in item
        assert service.clear_reported(_LOSS_YEAR).is_ok
        assert _raw_item(repo) is None  # last attribute → item deleted (Req 2.5)

        # allowedLoss alone.
        assert service.set_allowed_loss(_LOSS_YEAR, allowed_str).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["allowedLoss"] == allowed_money  # two-decimal money (Req 1.1)
        assert "amount" not in item  # reported independent (Req 2.2)
        assert "fullyAllowed" not in item
        assert service.clear_allowed_loss(_LOSS_YEAR).is_ok
        assert _raw_item(repo) is None  # deleted when empty (Req 1.4, 2.5)

        # fullyAllowed alone (a BOOL, present only when True).
        assert service.set_fully_allowed(_LOSS_YEAR, True).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["fullyAllowed"] is True  # boolean flag (Req 4.1)
        assert "amount" not in item
        assert "allowedLoss" not in item  # flag never snapshots the loss (Req 4.1)
        assert service.set_fully_allowed(_LOSS_YEAR, False).is_ok
        assert _raw_item(repo) is None  # off deletes when empty (Req 2.5)

        # --- Independence: set allowedLoss then amount → BOTH present --------
        assert service.set_allowed_loss(_LOSS_YEAR, allowed_str).is_ok
        assert service.set_reported(_LOSS_YEAR, reported).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money  # reported persisted (Req 2.3)
        assert item["allowedLoss"] == allowed_money  # allowed preserved (Req 2.3)

        # Add the flag too; now all three coexist.
        assert service.set_fully_allowed(_LOSS_YEAR, True).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money
        assert item["allowedLoss"] == allowed_money
        assert item["fullyAllowed"] is True

        # clear_reported → allowedLoss / fullyAllowed PRESERVED, not deleted.
        assert service.clear_reported(_LOSS_YEAR).is_ok
        item = _raw_item(repo)
        assert item is not None  # still carries allowed data (Req 2.4)
        assert "amount" not in item
        assert item["allowedLoss"] == allowed_money
        assert item["fullyAllowed"] is True

        # Restore amount, then clear_allowed_loss → amount / fullyAllowed kept.
        assert service.set_reported(_LOSS_YEAR, reported).is_ok
        assert service.clear_allowed_loss(_LOSS_YEAR).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money  # reported preserved
        assert "allowedLoss" not in item
        assert item["fullyAllowed"] is True

        # Restore allowedLoss, then set_fully_allowed(False) → amount/allowed kept.
        assert service.set_allowed_loss(_LOSS_YEAR, allowed_str).is_ok
        assert service.set_fully_allowed(_LOSS_YEAR, False).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money  # preserved (Req 2.5)
        assert item["allowedLoss"] == allowed_money
        assert "fullyAllowed" not in item  # off is sparse (Req 4.6)

        # --- Delete-when-empty: clearing the LAST attribute deletes the item -
        assert service.clear_reported(_LOSS_YEAR).is_ok
        item = _raw_item(repo)
        assert item is not None  # allowedLoss still remains
        assert "amount" not in item
        assert item["allowedLoss"] == allowed_money
        assert service.clear_allowed_loss(_LOSS_YEAR).is_ok
        assert _raw_item(repo) is None  # now truly empty → deleted (Req 2.5)

        # --- Idempotent clear of an absent attribute succeeds ----------------
        assert service.clear_reported(_LOSS_YEAR).is_ok
        assert service.clear_allowed_loss(_LOSS_YEAR).is_ok
        assert service.set_fully_allowed(_LOSS_YEAR, False).is_ok
        assert _raw_item(repo) is None

        # --- Backward compatibility: a pre-feature {amount, taxYear} item ----
        # A plain set_reported with no allowed data stores an item carrying NO
        # allowedLoss / fullyAllowed keys (Req 7.2) ...
        assert service.set_reported(_LOSS_YEAR, reported).is_ok
        item = _raw_item(repo)
        assert item is not None
        assert item["amount"] == reported_money
        assert item["taxYear"] == _LOSS_YEAR
        assert "allowedLoss" not in item
        assert "fullyAllowed" not in item
        # ... and reconcile() surfaces that year with allowed_loss == 0.00 and
        # fully_allowed == False (absent reads as the defaults, Req 7.2).
        found = next(
            (y for y in service.reconcile().years if y.tax_year == _LOSS_YEAR),
            None,
        )
        assert found is not None
        assert found.allowed_loss == Decimal("0.00")
        assert found.fully_allowed is False
