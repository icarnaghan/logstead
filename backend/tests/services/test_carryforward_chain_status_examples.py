"""Unit examples for carryforward chain status (worked example and edge cases).

Feature: carryforward-chain-status, task 1.9; re-derived for carry-in
semantics (carryforward-carry-in-semantics, task 2.6).

Each test provisions an isolated moto DynamoDB + S3 stack, seeds one property
with exactly one transaction per year (so the year's Schedule_E_Net is known),
records reported values, and asserts status, drift and carried_from_year from
``CarryforwardService.reconcile``.

Validates: Requirements 1.5, 2.2, 2.3, 2.4, 2.6, 2.7, 2.8, 3.1, 4.1
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


def D(value: str | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@contextlib.contextmanager
def _stack():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": f"GSI{i}",
                    "KeySchema": [
                        {"AttributeName": f"GSI{i}PK", "KeyType": "HASH"},
                        {"AttributeName": f"GSI{i}SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for i in (1, 2)
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


def _build(properties, transactions, nets: dict[int, int]) -> None:
    """Seed one property with one transaction per year so net == nets[year]."""
    created = properties.create(
        PropertyInput(
            name="P", address_text="1 Main St", property_type="single_family"
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id
    for year, net in nets.items():
        assert net != 0
        result = transactions.create(
            TransactionInput(
                property_id=pid,
                date=f"{year}-03-15",
                amount=D(abs(net)),
                type="income" if net > 0 else "expense",
                category_id="rents-received" if net > 0 else "repairs",
            )
        )
        assert result.is_ok, result.error


def _report(service, reported: dict[int, int | str]) -> None:
    for year, value in reported.items():
        result = service.set_reported(year, str(D(value)))
        assert result.is_ok, result.error


def _by_year(service) -> dict:
    return {y.tax_year: y for y in service.reconcile().years}


# 2014 -10,000; 2015 -2,000; 2016 -1,000; 2017 +1,500; 2018 -500
_WORKED_NETS = {2014: -10000, 2015: -2000, 2016: -1000, 2017: 1500, 2018: -500}
# Reported values are Form 8582 "Prior years unallowed losses" (carry-in).
# Expected carry-in: 2014 0, 2015 10000, 2016 12000, 2017 13000, 2018 11500.
# 2015 is entered wrong (7000, not 10000); each later return faithfully carries
# it through the previous year's activity: 2016 = 7000 + 2000, 2017 = 9000 + 1000,
# 2018 = 10000 - 1500.
_WORKED_REPORTED = {2014: 0, 2015: 7000, 2016: 9000, 2017: 10000, 2018: 8500}


def test_worked_example() -> None:
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, _WORKED_NETS)
        _report(service, _WORKED_REPORTED)
        years = _by_year(service)

        # Carry-out running balance is unchanged by the semantics.
        assert [years[y].expected_carryforward for y in sorted(years)] == [
            D(10000), D(12000), D(13000), D(11500), D(12000)
        ]
        assert [years[y].expected_carry_in for y in sorted(years)] == [
            D(0), D(10000), D(12000), D(13000), D(11500)
        ]
        assert years[2014].status == "ok"
        assert years[2014].drift == D(0)
        assert years[2014].carried_from_year is None

        assert years[2015].status == "mismatch"
        assert years[2015].drift == D(-3000)
        assert years[2015].carried_from_year is None

        for y in (2016, 2017, 2018):
            assert years[y].status == "carried", y
            assert years[y].carried_from_year == 2015
            assert years[y].drift == D(-3000)


def test_first_year_uses_opening_balance_and_skips_chain_rule() -> None:
    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2014: -1000, 2015: -200})
        # 2014 expected carry-in = opening 500. Reporting 0 ignores the opening
        # balance: first year has no chain rule, so it is a mismatch.
        _report(service, {2014: 0, 2015: 1000})
        years = _by_year(service)
        assert years[2014].expected_carry_in == D(500)
        assert years[2014].expected_carryforward == D(1500)
        assert years[2014].status == "mismatch"
        assert years[2014].drift == D(-500)
        # 2015 expected carry-in 1500; chain = 0 + 1000 = 1000 from reported 2014.
        assert years[2015].expected_carry_in == D(1500)
        assert years[2015].status == "carried"
        assert years[2015].carried_from_year == 2014
        assert years[2015].drift == D(-500)

    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2014: -1000})
        _report(service, {2014: 500})
        assert _by_year(service)[2014].status == "ok"


def test_unreported_prior_year_falls_back_then_chains_again() -> None:
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, _WORKED_NETS)
        # 2016 left blank. 2017 would carry 10000 (9000 + 1000) if 2016 were filled.
        _report(service, {2014: 0, 2015: 7000, 2017: 10000, 2018: 8500})
        years = _by_year(service)
        assert years[2015].status == "mismatch"
        assert years[2016].status == "unreported"
        assert years[2016].drift is None
        assert years[2016].carried_from_year is None
        assert years[2016].expected_carry_in == D(12000)
        # No prior reported value: fallback rules only (expected 13000).
        assert years[2017].status == "mismatch"
        assert years[2017].carried_from_year is None
        # 2018 chains from 2017's reported 10000: 10000 - 1500 = 8500.
        assert years[2018].status == "carried"
        assert years[2018].carried_from_year == 2017


def test_gain_floor_reproduces_smaller_drift_as_carried() -> None:
    nets = dict(_WORKED_NETS)
    nets[2017] = 11000
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # 2018 expected carry-in = max(13000 - 11000, 0) = 2000;
        # chain = max(10000 - 11000, 0) = 0, so the 3000 error shrinks to -2000.
        _report(
            service, {2014: 0, 2015: 7000, 2016: 9000, 2017: 10000, 2018: 0}
        )
        years = _by_year(service)
        assert years[2017].status == "carried"
        assert years[2017].drift == D(-3000)
        y = years[2018]
        assert y.expected_carry_in == D(2000)
        assert y.status == "carried"
        assert y.carried_from_year == 2015
        assert y.drift == D(-2000)


def test_gain_floor_hides_drift_as_ok() -> None:
    nets = dict(_WORKED_NETS)
    nets[2017] = 20000
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(
            service, {2014: 0, 2015: 7000, 2016: 9000, 2017: 10000, 2018: 0}
        )
        years = _by_year(service)
        assert years[2017].expected_carryforward == D(0)
        assert years[2017].status == "carried"
        # 2018 expected carry-in is floored to 0 and so is the reported chain:
        # the inherited error is gone.
        assert years[2018].expected_carry_in == D(0)
        assert years[2018].status == "ok"
        assert years[2018].drift == D(0)
        assert years[2018].carried_from_year is None
        assert years[2018].expected_carryforward == D(500)


def test_second_independent_error_is_mismatch_and_later_years_name_it() -> None:
    nets = dict(_WORKED_NETS)
    nets[2019] = -100
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # 2018 reports 6000 instead of the chained 8500 (and expected 11500).
        _report(
            service,
            {
                2014: 0, 2015: 7000, 2016: 9000, 2017: 10000,
                2018: 6000, 2019: 6500,  # 2019 chain = 6000 + 500
            },
        )
        years = _by_year(service)
        assert years[2015].status == "mismatch"
        assert years[2016].carried_from_year == 2015
        assert years[2017].carried_from_year == 2015
        assert years[2018].status == "mismatch"
        assert years[2018].carried_from_year is None
        assert years[2019].status == "carried"
        assert years[2019].carried_from_year == 2018


def test_allowed_loss_years_are_not_misread_as_errors() -> None:
    nets = {
        2014: -10000, 2015: -2000, 2016: -1000, 2017: -3000, 2018: -500,
    }
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        assert service.set_fully_allowed(2016, True).is_ok
        assert service.set_allowed_loss(2017, "1000.00").is_ok
        # Expected carry-in: 0, 10000, 12000, 12000 (2016 fully allowed adds 0),
        # 14000 (2017 adds 2000). Returns chained from the 2015 error (7000):
        # 2016 = 7000 + 2000, 2017 = 9000 + 0, 2018 = 9000 + 2000.
        _report(
            service,
            {2014: 0, 2015: 7000, 2016: 9000, 2017: 9000, 2018: 11000},
        )
        years = _by_year(service)
        assert years[2016].expected_carryforward == D(12000)
        assert years[2017].expected_carryforward == D(14000)
        assert years[2017].expected_carry_in == D(12000)
        assert years[2018].expected_carry_in == D(14000)
        assert years[2015].status == "mismatch"
        assert years[2016].status == "carried"
        assert years[2016].carried_from_year == 2015
        assert years[2017].status == "carried"
        assert years[2017].carried_from_year == 2015
        assert years[2017].drift == D(-3000)
        assert years[2018].status == "carried"
        assert years[2018].carried_from_year == 2015
        assert years[2018].drift == D(-3000)


def test_fully_allowed_series_with_correct_returns_is_ok() -> None:
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, {2014: -1000, 2015: -2000})
        assert service.set_fully_allowed(2014, True).is_ok
        assert service.set_fully_allowed(2015, True).is_ok
        # Fully allowed losses add nothing: carry-in stays 0 in both years.
        _report(service, {2014: 0, 2015: 0})
        years = _by_year(service)
        assert years[2014].status == "ok"
        assert years[2015].status == "ok"
