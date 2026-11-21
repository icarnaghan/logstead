"""Property-based tests: injected return errors and unreported gaps.

Feature: carryforward-chain-status

The reported value of a year is the Form 8582 "Prior years unallowed losses"
carry-in. Carry-in semantics (carryforward-carry-in-semantics): reported is
compared with ``expected_carry_in``; the chain value for year Y is the *previous*
year's step applied to the previous year's reported carry-in.

Property 6 (Requirements 2.3, 2.4, 2.8, 3.1): starting from a correct reported
series (reported == expected_carry_in), one year N is replaced by a value that
differs from both the expected carry-in and the chain value, and every later
year Y is reported by applying year Y-1's step to year Y-1's *reported* carry-in
(a filed return that correctly carries forward the prior return's figure). Exactly one ``mismatch``
appears at N, years before N are ``ok``, later years are ``carried`` (naming N)
or ``ok`` once the gain-year floor equalises the figures. A second injected
error is ``mismatch`` for its own year and later carried years name it.

Property 7 (Requirement 2.6): after an unreported year U, the next year is
classified with the fallback rules only (``ok`` or ``mismatch``, never
``carried``), and chain attribution resumes for the year after that.

Each example provisions its own moto-backed single-table DynamoDB and S3 bucket,
mirroring ``test_carryforward_status_property.py``. Allowed-loss data is not set,
so the effective allowed amount is ``0.00`` for every year.
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
    """Isolated moto DynamoDB (base + GSI1 + GSI2) and S3 with composed services."""
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


# --- Strategies ---------------------------------------------------------------

_amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("50000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
# One (is_income, amount) per year: a single transaction fixes the year's net.
_year_net = st.tuples(st.booleans(), _amounts)
# Injected errors must differ from the compared figures by MORE than the status
# tolerance, otherwise they would still count as a match.
_deltas = st.decimals(
    min_value=STATUS_TOLERANCE + Decimal("0.01"),
    max_value=Decimal("20000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def _years_strategy(min_size: int):
    return st.lists(
        st.sampled_from(_TAX_YEARS), min_size=min_size, max_size=len(_TAX_YEARS), unique=True
    ).map(sorted)


def _seed(properties, transactions, years, nets) -> None:
    created = properties.create(
        PropertyInput(name="P", address_text="1 Main St", property_type="single_family")
    )
    assert created.is_ok, created.error
    for index, (year, (is_income, amount)) in enumerate(zip(years, nets)):
        result = transactions.create(
            TransactionInput(
                property_id=created.value.id,
                date=f"{year:04d}-{(index % 12) + 1:02d}-{(index % 28) + 1:02d}",
                amount=amount,
                type="income" if is_income else "expense",
                category_id="rents-received" if is_income else "repairs",
            )
        )
        assert result.is_ok, result.error


def _step(prior: Decimal, net: Decimal) -> Decimal:
    """One year's balance step with a 0.00 effective allowed amount."""
    if net < 0:
        return to_money(prior + (-net))
    return to_money(max(prior - net, _ZERO))


def _within(a: Decimal, b: Decimal) -> bool:
    """Independent tolerance rule: |a - b| <= STATUS_TOLERANCE."""
    return abs(a - b) <= STATUS_TOLERANCE


def _wrong(chain: Decimal, expected: Decimal, delta: Decimal, up: bool) -> Decimal:
    """A non-negative value differing from both ``chain`` and ``expected``."""
    if not up:
        low = min(chain, expected) - delta
        if low >= 0:
            return to_money(low)
    return to_money(max(chain, expected) + delta)


def _set(service: CarryforwardService, year: int, value: Decimal) -> None:
    result = service.set_reported(year, money_to_str(value))
    assert result.is_ok, result.error


# Feature: carryforward-chain-status, Property 6: Injected errors produce
# mismatch at the error year and carried afterwards
# Validates: Requirements 2.3, 2.4, 2.8, 3.1
@settings(deadline=None, max_examples=100)
@given(
    years=_years_strategy(2),
    nets=st.lists(_year_net, min_size=5, max_size=5),
    n_pick=st.integers(min_value=0, max_value=4),
    m_pick=st.one_of(st.none(), st.integers(min_value=0, max_value=4)),
    delta1=_deltas,
    delta2=_deltas,
    up1=st.booleans(),
    up2=st.booleans(),
)
def test_injected_errors_are_mismatch_then_carried(
    years, nets, n_pick, m_pick, delta1, delta2, up1, up2
) -> None:
    """Error year N is mismatch; later years are carried/ok; second error is its own mismatch.

    Validates: Requirements 2.3, 2.4, 2.8, 3.1
    """
    count = len(years)
    n_index = n_pick % count
    # Optional independent second error strictly after N.
    m_index = None
    if m_pick is not None and n_index + 1 < count:
        m_index = n_index + 1 + (m_pick % (count - n_index - 1))

    with _moto_service() as (service, properties, transactions):
        _seed(properties, transactions, years, nets[:count])
        base = service.reconcile()
        assert [y.tax_year for y in base.years] == years
        expected = [y.expected_carry_in for y in base.years]
        net_by = [y.schedule_e_net for y in base.years]

        reported: list[Decimal] = []
        for i in range(count):
            if i < n_index:
                value = expected[i]
            elif i == n_index:
                value = _wrong(expected[i], expected[i], delta1, up1)
            else:
                chain = _step(reported[i - 1], net_by[i - 1])
                if i == m_index:
                    value = _wrong(chain, expected[i], delta2, up2)
                else:
                    value = chain
            reported.append(value)
            _set(service, years[i], value)

        final = service.reconcile()
        last_mismatch: int | None = None
        mismatches = []
        for i, year in enumerate(final.years):
            assert year.tax_year == years[i]
            if i < n_index:
                want = "ok"
            elif i == n_index or i == m_index:
                want = "mismatch"
            elif _within(reported[i], expected[i]):
                want = "ok"
            else:
                want = "carried"
            assert year.status == want, (year.tax_year, year.status, want)
            if want == "mismatch":
                last_mismatch = year.tax_year
                mismatches.append(year.tax_year)
            if want == "carried":
                assert year.carried_from_year == last_mismatch
                assert last_mismatch is not None
                assert year.carried_from_year < year.tax_year
            else:
                assert year.carried_from_year is None
        expected_mismatches = [years[n_index]] + (
            [years[m_index]] if m_index is not None else []
        )
        assert mismatches == expected_mismatches


# Feature: carryforward-chain-status, Property 7: Unreported gap restarts
# attribution
# Validates: Requirements 2.6
@settings(deadline=None, max_examples=100)
@given(
    years=_years_strategy(3),
    nets=st.lists(_year_net, min_size=5, max_size=5),
    u_pick=st.integers(min_value=0, max_value=3),
    delta=_deltas,
)
def test_unreported_gap_restarts_attribution(years, nets, u_pick, delta) -> None:
    """The year after an unreported year uses fallback rules; chaining resumes after.

    Validates: Requirements 2.6
    """
    count = len(years)
    u_index = u_pick % (count - 1)  # U+1 always exists
    after = u_index + 1

    with _moto_service() as (service, properties, transactions):
        _seed(properties, transactions, years, nets[:count])
        base = service.reconcile()
        expected = [y.expected_carry_in for y in base.years]
        net_by = [y.schedule_e_net for y in base.years]

        # Years before U are correct; U is left unreported.
        for i in range(u_index):
            _set(service, years[i], expected[i])
        # U+1 is strictly above expected, so it is a fallback `mismatch` even
        # though it could never be `carried` (its prior year is unreported).
        value_after = to_money(expected[after] + delta)
        _set(service, years[after], value_after)
        # Later years carry forward the prior year's step on its reported figure.
        reported = {after: value_after}
        for i in range(after + 1, count):
            reported[i] = _step(reported[i - 1], net_by[i - 1])
            _set(service, years[i], reported[i])

        final = service.reconcile()
        by_index = dict(enumerate(final.years))

        assert by_index[u_index].status == "unreported"
        assert by_index[u_index].drift is None
        assert by_index[u_index].carried_from_year is None

        assert by_index[after].status == "mismatch"
        assert by_index[after].carried_from_year is None

        for i in range(after + 1, count):
            want = "ok" if _within(reported[i], expected[i]) else "carried"
            assert by_index[i].status == want, (years[i], by_index[i].status, want)
            if want == "carried":
                assert by_index[i].carried_from_year == years[after]
            else:
                assert by_index[i].carried_from_year is None
