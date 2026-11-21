"""Property-based test: drift is exact and null iff unreported.

Feature: carryforward-carry-in-semantics, Property 7: Drift is exact and null
iff unreported.

*For any* input, each year's ``drift`` is ``None`` exactly when
``reported_carryforward`` (the Form 8582 carry-in) is ``None``, and otherwise
equals ``reported_carryforward - expected_carry_in`` exactly as a signed
two-decimal ``Decimal`` (never a float). ``status`` equals an independent
four-rule carry-in oracle (chain = previous year's step applied to the previous
year's reported value) that never reads ``drift``.

Validates: Requirements 6.1, 6.2, 6.3, 12.1

Each Hypothesis example provisions its own moto-backed DynamoDB (base + GSI1 +
GSI2) and S3 bucket, mirroring ``test_carryforward_status_property.py``.
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
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.carryforward import STATUS_TOLERANCE, CarryforwardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService
from logstead.util.money import money_to_str, to_money

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"

_TAX_YEARS = [2018, 2019, 2020, 2022, 2023]
_ZERO = Decimal("0.00")


@contextlib.contextmanager
def _moto_service():
    """Isolated moto DynamoDB + S3 with a composed CarryforwardService."""
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


_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_SPECS = [
    ("income", "rents-received"),
    ("income", "royalties-received"),
    ("expense", "repairs"),
    ("expense", "utilities"),
    ("expense", "other"),
]


@st.composite
def _txn(draw: st.DrawFn) -> tuple[str, str, Decimal, str | None, int]:
    ttype, category = draw(st.sampled_from(_SPECS))
    amount = draw(_amounts)
    year = draw(st.sampled_from(_TAX_YEARS))
    description: str | None = None
    if category == "other":
        description = draw(
            st.text(min_size=1, max_size=20).filter(lambda s: s.strip())
        )
    return ttype, category, amount, description, year


_property_txns = st.lists(_txn(), min_size=1, max_size=10)


def _seed(properties, transactions, properties_txns) -> None:
    for p_index, txns in enumerate(properties_txns):
        created = properties.create(
            PropertyInput(
                name=f"Prop{p_index}",
                address_text=f"{p_index} Main St",
                property_type="single_family",
            )
        )
        assert created.is_ok, created.error
        for t_index, (ttype, category, amount, description, year) in enumerate(
            txns
        ):
            result = transactions.create(
                TransactionInput(
                    property_id=created.value.id,
                    date=f"{year:04d}-{(t_index % 12) + 1:02d}-{(t_index % 28) + 1:02d}",
                    amount=amount,
                    type=ttype,
                    category_id=category,
                    description=description,
                )
            )
            assert result.is_ok, result.error


def _off_by_cent(value: Decimal, up: bool) -> Decimal:
    if up or value < Decimal("0.01"):
        return to_money(value + Decimal("0.01"))
    return to_money(value - Decimal("0.01"))


def _oracle_statuses(years) -> list[str]:
    """Four-rule tolerant status oracle; never reads ``drift``.

``ok`` / ``carried`` hold when within ``STATUS_TOLERANCE``; ``drift`` itself
stays exact, so an ``ok`` year may carry a nonzero drift.
"""
    out: list[str] = []
    prior_reported: Decimal | None = None
    prior_year = None
    for index, year in enumerate(years):
        reported = year.reported_carryforward
        chain: Decimal | None = None
        if index > 0 and prior_reported is not None:
            pnet = prior_year.schedule_e_net
            if pnet < 0:
                effective = (
                    -pnet if prior_year.fully_allowed else prior_year.allowed_loss
                )
                chain = to_money(
                    prior_reported + max(-pnet - effective, _ZERO)
                )
            else:
                chain = to_money(max(prior_reported - pnet, _ZERO))
        if reported is None:
            out.append("unreported")
        elif abs(reported - year.expected_carry_in) <= STATUS_TOLERANCE:
            out.append("ok")
        elif chain is not None and abs(reported - chain) <= STATUS_TOLERANCE:
            out.append("carried")
        else:
            out.append("mismatch")
        prior_reported = reported
        prior_year = year
    return out


# Feature: carryforward-carry-in-semantics, Property 7: Drift is exact and null
# iff unreported
# Validates: Requirements 6.1, 6.2, 6.3, 12.1
@settings(deadline=None, max_examples=100)
@given(
    properties_txns=st.lists(_property_txns, min_size=1, max_size=3),
    choices=st.lists(
        st.sampled_from(
            ["unreported", "expected", "up", "down", "far", "zero"]
        ),
        min_size=0,
        max_size=40,
    ),
)
def test_drift_is_exact_and_null_iff_unreported(
    properties_txns: list[list[tuple[str, str, Decimal, str | None, int]]],
    choices: list[str],
) -> None:
    """drift is null iff unreported, else exactly reported - expected carry-in.

    Validates: Requirements 6.1, 6.2, 6.3, 12.1
    """
    with _moto_service() as (service, properties, transactions):
        _seed(properties, transactions, properties_txns)
        first = service.reconcile()

        for index, year in enumerate(first.years):
            choice = choices[index % len(choices)] if choices else "unreported"
            expected = year.expected_carry_in
            if choice == "unreported":
                continue
            if choice == "expected":
                value = expected
            elif choice == "up":
                value = _off_by_cent(expected, True)
            elif choice == "down":
                value = _off_by_cent(expected, False)
            elif choice == "far":
                value = to_money(expected + Decimal("12345.67"))
            else:
                value = _ZERO
            result = service.set_reported(year.tax_year, money_to_str(value))
            assert result.is_ok, result.error

        final = service.reconcile()
        statuses = _oracle_statuses(final.years)
        assert len(statuses) == len(final.years)

        for year, oracle_status in zip(final.years, statuses):
            reported = year.reported_carryforward
            if reported is None:
                assert year.drift is None, year.tax_year
            else:
                assert isinstance(year.drift, Decimal), year.tax_year
                assert not isinstance(year.drift, float)
                assert year.drift == reported - year.expected_carry_in, (
                    year.tax_year,
                    money_to_str(reported),
                    money_to_str(year.expected_carry_in),
                    money_to_str(year.drift),
                )
                # Exactly two decimal places.
                assert year.drift == to_money(year.drift)
                assert year.drift.as_tuple().exponent == -2
            # Status is independent of drift: it matches the oracle that
            # never reads drift.
            assert year.status == oracle_status, (
                year.tax_year,
                year.status,
                oracle_status,
            )
