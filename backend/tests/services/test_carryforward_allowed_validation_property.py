"""Property-based test: allowed-data validation rejects every impossible
submission with the right field and persists nothing.

Design Property 5 — *Validation rejects impossible allowed data and persists
nothing* (Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6): for any per-year allowed
submission that cannot be right for the year, ``CarryforwardService``
(``services/carryforward.py``) rejects it with a ``Result`` ``validation``
failure whose ``field`` names the offending control (``"allowedLoss"`` for the
amount setter, ``"fullyAllowed"`` for the toggle) and leaves the per-year
``PLCF#<year>`` item byte-for-byte unchanged; and any submission that CAN be
right (a non-negative amount within ``[0.00, Loss_Magnitude]`` on a loss year,
or fully-allowed on a loss year) is accepted and persisted.

Each unsatisfiable case this exercises:

* a negative ``set_allowed_loss(loss_year, bad)`` → failure, ``field ==
  "allowedLoss"`` (Req 5.1);
* ``set_allowed_loss(loss_year, amount)`` with ``amount`` strictly greater than
  that year's ``Loss_Magnitude`` → failure, ``field == "allowedLoss"`` (Req
  5.3, deriving the net per Req 5.2);
* ``set_allowed_loss(gain_year, amount > 0.00)`` → failure, ``field ==
  "allowedLoss"`` (Req 5.4; note ``0.00`` on a non-loss year is accepted);
* ``set_fully_allowed(gain_year, True)`` → failure, ``field == "fullyAllowed"``
  (Req 5.4).

And the satisfiable cases:

* a valid ``set_allowed_loss(loss_year, amount in [0.00, Loss_Magnitude])`` is
  accepted (``Result`` ok) and persisted (Req 5.5);
* ``set_fully_allowed(loss_year, True)`` is accepted and persisted.

Every rejection uses the existing ``Result.failure("validation", message,
field=...)`` pattern (Req 5.6). The "persists nothing" half is proved by reading
the raw per-year item (``repo.get_item(user_pk(USER), plcf_year_sk(year))``)
immediately before and after each rejected call and asserting it is identical.

The fixture mirrors the moto-composed stack in
``test_carryforward_running_balance_property.py``: a real
``CarryforwardService(repo, USER, reports, properties, transactions,
depreciation)`` over a freshly provisioned single-table DynamoDB (base + GSI1 +
GSI2) and S3 bucket, so each Hypothesis example runs against a clean store.
Rather than hope a random transaction mix produces both a loss year and a gain
year, the fixture provisions a deliberate set that makes 2020 a known loss year
(expenses only, magnitude fixed by the generated amounts) and 2023 a known gain
year (income strictly greater than expenses). ``service.reconcile()`` is called
up front to read each year's actual ``schedule_e_net``, and the submitted
amounts are generated relative to the derived ``Loss_Magnitude`` so the
"within" / "exceeds" cases are deterministic.

Per-example provisioning is not instantaneous, so the deadline is disabled; the
example count is held at 100.
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
from logstead.util.money import money_to_str, to_money

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

# A known loss year (expenses only) and a known gain year (income strictly
# greater than expenses), both non-contiguous, so every example has a loss year
# of a known magnitude AND a non-loss year to exercise Req 5.4.
LOSS_YEAR = 2020
GAIN_YEAR = 2023


@contextlib.contextmanager
def _moto_service():
    """Provision an isolated moto DynamoDB (base + GSI1 + GSI2) and S3 bucket.

    Yields the composed CarryforwardService bound to freshly created resources
    so each Hypothesis example runs against a clean store. The service is
    constructed exactly as the carryforward route composes it:
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
        yield service, properties, transactions, repo


def _iso_date(year: int, index: int) -> str:
    """A deterministic in-year ISO date, cycling day/month to stay valid."""
    month = (index % 12) + 1
    day = (index % 28) + 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def _read_year_item(repo: DynamoRepository, year: int) -> dict | None:
    """Read the raw per-year PLCF item, money attrs parsed, for a before/after
    equality check proving a rejected call persisted nothing."""
    return repo.get_item(
        keys.user_pk(USER),
        keys.plcf_year_sk(year),
        money_attrs={"amount", "allowedLoss"},
    )


# --- Strategies ---------------------------------------------------------------
#
# A positive two-decimal money magnitude, bounded so the deliberate loss/gain
# split stays comfortably within range. The loss year gets expense-only lines;
# the gain year gets an income line strictly larger than its expense line.
_amounts = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A strictly-negative two-decimal amount string — the reliably-rejected "bad
# amount" case for Req 5.1 (a negative is not a valid non-negative money
# magnitude; a >2-decimal string is NOT a reliable rejection because to_money
# rounds it half-up rather than failing).
_negative_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
).map(lambda d: money_to_str(to_money(-d)))

# A strictly-positive overshoot added to the loss magnitude to exceed it.
_overshoot = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# A fraction in [0, 1] used to pick a valid in-range allowed amount.
_fractions = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("1"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


# Feature: carryforward-allowed-loss, Property 5: Validation rejects impossible
# allowed data and persists nothing
@settings(deadline=None, max_examples=100)
@given(
    loss_expense=_amounts,
    gain_income=_amounts,
    gain_expense=_amounts,
    bad_negative=_negative_amounts,
    overshoot=_overshoot,
    gain_amount=_amounts,
    valid_fraction=_fractions,
)
def test_allowed_validation_rejects_impossible_data_and_persists_nothing(
    loss_expense: Decimal,
    gain_income: Decimal,
    gain_expense: Decimal,
    bad_negative: str,
    overshoot: Decimal,
    gain_amount: Decimal,
    valid_fraction: Decimal,
) -> None:
    """Each unsatisfiable allowed submission is rejected with the right field
    and persists nothing; each satisfiable one is accepted and persisted.

    Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
    """
    with _moto_service() as (service, properties, transactions, repo):
        created = properties.create(
            PropertyInput(
                name="Prop",
                address_text="1 Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        pid = created.value.id

        # LOSS_YEAR: an expense line only → a strictly-negative net of a known
        # magnitude (Req 5.2 derives it, below, from the real reconcile).
        loss_txn = transactions.create(
            TransactionInput(
                property_id=pid,
                date=_iso_date(LOSS_YEAR, 0),
                amount=loss_expense,
                type="expense",
                category_id="repairs",
                description=None,
            )
        )
        assert loss_txn.is_ok, loss_txn.error

        # GAIN_YEAR: income strictly greater than expense → a strictly-positive
        # net, so the year is a Non_Loss_Year.
        gain_inc = transactions.create(
            TransactionInput(
                property_id=pid,
                date=_iso_date(GAIN_YEAR, 0),
                amount=gain_income + gain_expense,
                type="income",
                category_id="rents-received",
                description=None,
            )
        )
        assert gain_inc.is_ok, gain_inc.error
        gain_exp = transactions.create(
            TransactionInput(
                property_id=pid,
                date=_iso_date(GAIN_YEAR, 1),
                amount=gain_expense,
                type="expense",
                category_id="utilities",
                description=None,
            )
        )
        assert gain_exp.is_ok, gain_exp.error

        # Derive each year's actual net up front (Req 5.2). Pull the loss
        # magnitude straight from the reconciled series so the "within" /
        # "exceeds" amounts are deterministic.
        summary = service.reconcile()
        nets = {ry.tax_year: ry.schedule_e_net for ry in summary.years}
        assert LOSS_YEAR in nets and GAIN_YEAR in nets, nets
        loss_net = nets[LOSS_YEAR]
        gain_net = nets[GAIN_YEAR]
        assert loss_net < 0, loss_net
        assert gain_net > 0, gain_net
        loss_magnitude = -loss_net

        # ---- Rejections: each must fail with the right field and persist
        # nothing. Snapshot the raw item before, assert it is unchanged after.

        # (a) Negative amount on a loss year → field="allowedLoss" (Req 5.1).
        before = _read_year_item(repo, LOSS_YEAR)
        rejected = service.set_allowed_loss(LOSS_YEAR, bad_negative)
        assert not rejected.is_ok
        assert rejected.error.kind == "validation", rejected.error
        assert rejected.error.field == "allowedLoss", rejected.error
        assert _read_year_item(repo, LOSS_YEAR) == before

        # (b) Amount strictly exceeding the loss magnitude → field="allowedLoss"
        # (Req 5.3). Net derived per Req 5.2.
        exceeds = money_to_str(to_money(loss_magnitude + to_money(overshoot)))
        before = _read_year_item(repo, LOSS_YEAR)
        rejected = service.set_allowed_loss(LOSS_YEAR, exceeds)
        assert not rejected.is_ok
        assert rejected.error.kind == "validation", rejected.error
        assert rejected.error.field == "allowedLoss", rejected.error
        assert _read_year_item(repo, LOSS_YEAR) == before

        # (c) A positive amount on a NON-loss year → field="allowedLoss"
        # (Req 5.4). Snapshot the gain year's item (expected absent).
        positive_on_gain = money_to_str(to_money(gain_amount))
        before = _read_year_item(repo, GAIN_YEAR)
        rejected = service.set_allowed_loss(GAIN_YEAR, positive_on_gain)
        assert not rejected.is_ok
        assert rejected.error.kind == "validation", rejected.error
        assert rejected.error.field == "allowedLoss", rejected.error
        assert _read_year_item(repo, GAIN_YEAR) == before

        # (d) Fully-allowed on a NON-loss year → field="fullyAllowed" (Req 5.4).
        before = _read_year_item(repo, GAIN_YEAR)
        rejected = service.set_fully_allowed(GAIN_YEAR, True)
        assert not rejected.is_ok
        assert rejected.error.kind == "validation", rejected.error
        assert rejected.error.field == "fullyAllowed", rejected.error
        assert _read_year_item(repo, GAIN_YEAR) == before

        # ---- Acceptances: a valid amount in [0, loss_magnitude] and the
        # fully-allowed toggle on the loss year are accepted and persisted.

        # (e) A valid amount strictly within [0.00, loss_magnitude] is accepted
        # (Req 5.5) and persisted as allowedLoss.
        valid_amount = to_money(loss_magnitude * valid_fraction)
        if valid_amount > loss_magnitude:  # guard against rounding overshoot
            valid_amount = loss_magnitude
        valid_str = money_to_str(valid_amount)
        accepted = service.set_allowed_loss(LOSS_YEAR, valid_str)
        assert accepted.is_ok, accepted.error
        stored = _read_year_item(repo, LOSS_YEAR)
        assert stored is not None
        assert stored.get("allowedLoss") == valid_amount, stored

        # (f) fully_allowed on the loss year is accepted (Req 5.4 only rejects
        # non-loss years) and persisted as the flag, preserving the amount.
        accepted = service.set_fully_allowed(LOSS_YEAR, True)
        assert accepted.is_ok, accepted.error
        stored = _read_year_item(repo, LOSS_YEAR)
        assert stored is not None
        assert stored.get("fullyAllowed") is True, stored
        assert stored.get("allowedLoss") == valid_amount, stored
