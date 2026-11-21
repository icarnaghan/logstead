"""Unit examples for carry-in semantics (the user's real 2014 to 2020 shape).

Feature: carryforward-carry-in-semantics, task 1.4.

Each test provisions an isolated moto DynamoDB + S3 stack, seeds one property
with exactly one transaction per year (so the year's Schedule_E_Net is known),
records reported values (Form 8582 "Prior years unallowed losses", the
carry-in) and asserts expected carry-in / carry-out, status, drift and
carried_from_year from ``CarryforwardService.reconcile``. Every expectation is
derived by hand from the design's rules.

Validates: Requirements 3.2, 3.3, 3.4, 3.6, 3.7, 4.4, 5.1, 6.1, 7.4, 13.5
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


def _report(service, reported: dict[int, int]) -> None:
    for year, value in reported.items():
        result = service.set_reported(year, str(D(value)))
        assert result.is_ok, result.error


def _by_year(service) -> dict:
    return {y.tax_year: y for y in service.reconcile().years}


def test_users_real_2014_to_2020_shape() -> None:
    nets = {
        2014: -837, 2015: -1615, 2016: -500, 2017: 300,
        2018: -1000, 2019: -200, 2020: -300,
    }
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        assert service.set_fully_allowed(2016, True).is_ok  # adds nothing
        assert service.set_allowed_loss(2018, "400.00").is_ok  # adds 600
        # 2016-2018 are blank on the real forms.
        _report(service, {2014: 0, 2015: 837, 2019: 107, 2020: 307})
        summary = service.reconcile()
        years = {y.tax_year: y for y in summary.years}

        assert [years[y].expected_carry_in for y in sorted(years)] == [
            D(0), D(837), D(2452), D(2452), D(2152), D(2752), D(2952)
        ]
        assert [years[y].expected_carryforward for y in sorted(years)] == [
            D(837), D(2452), D(2452), D(2152), D(2752), D(2952), D(3252)
        ]

        assert years[2014].status == "ok"
        assert years[2014].drift == D(0)
        # 2015's 837 equals the expected end-2014 balance: ok (old rules flagged it).
        assert years[2015].status == "ok"
        assert years[2015].drift == D(0)
        for y in (2016, 2017, 2018):
            assert years[y].status == "unreported", y
            assert years[y].drift is None
            assert years[y].reported_carryforward is None
            assert years[y].carried_from_year is None
        # First reported year after the blank gap: fallback only.
        assert years[2019].status == "mismatch"
        assert years[2019].drift == D(-2645)
        assert years[2019].carried_from_year is None
        # 2020 faithfully carries 2019's 107 through 2019's 200 loss: 307.
        assert years[2020].status == "carried"
        assert years[2020].drift == D(-2645)
        assert years[2020].carried_from_year == 2019

        assert summary.next_year == 2021
        assert summary.next_year_expected_carry_in == D(3252)


def test_first_year_compares_with_opening_balance() -> None:
    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2014: -1000})
        _report(service, {2014: 500})
        y = _by_year(service)[2014]
        assert y.expected_carry_in == D(500)
        assert y.expected_carryforward == D(1500)
        assert y.status == "ok"

    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2014: -1000})
        _report(service, {2014: 0})
        y = _by_year(service)[2014]
        assert y.status == "mismatch"
        assert y.drift == D(-500)
        assert y.carried_from_year is None


def test_unreported_previous_year_falls_back_then_chains_one_year_later() -> None:
    nets = {2014: -1000, 2015: -200, 2016: -300, 2017: -100}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # Expected carry-in: 0, 1000, 1200, 1500. 2015 blank.
        _report(service, {2014: 0, 2016: 1000, 2017: 1300})
        years = _by_year(service)
        assert years[2014].status == "ok"
        assert years[2015].status == "unreported"
        assert years[2015].expected_carry_in == D(1000)
        # 2016: no prior reported value, so compared with expected 1200 only.
        assert years[2016].status == "mismatch"
        assert years[2016].drift == D(-200)
        assert years[2016].carried_from_year is None
        # 2017: chain = 1000 + 300 = 1300 equals reported, expected is 1500.
        assert years[2017].status == "carried"
        assert years[2017].carried_from_year == 2016
        assert years[2017].drift == D(-200)


def test_gain_year_floor_hides_inherited_error_as_ok() -> None:
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, {2014: -1000, 2015: 5000, 2016: -100})
        # Expected carry-in: 0, 1000, 0. 2015 reports 800 instead of 1000.
        # 2016 chain = max(800 - 5000, 0) = 0 = expected carry-in.
        _report(service, {2014: 0, 2015: 800, 2016: 0})
        years = _by_year(service)
        assert years[2015].status == "mismatch"
        assert years[2015].drift == D(-200)
        assert years[2016].expected_carry_in == D(0)
        assert years[2016].status == "ok"
        assert years[2016].drift == D(0)
        assert years[2016].carried_from_year is None


def test_second_independent_error_names_the_later_year() -> None:
    nets = {2014: -1000, 2015: -200, 2016: -300, 2017: -100, 2018: -50}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # Expected carry-in: 0, 1000, 1200, 1500, 1600.
        # 2015 wrong (900); 2016 chain 900 + 200 = 1100 (carried);
        # 2017 reports 5000: differs from expected 1500 and chain 1400 (mismatch);
        # 2018 chain 5000 + 100 = 5100 (carried from 2017).
        _report(service, {2014: 0, 2015: 900, 2016: 1100, 2017: 5000, 2018: 5100})
        years = _by_year(service)
        assert years[2014].status == "ok"
        assert years[2015].status == "mismatch"
        assert years[2016].status == "carried"
        assert years[2016].carried_from_year == 2015
        assert years[2017].status == "mismatch"
        assert years[2017].carried_from_year is None
        assert years[2018].status == "carried"
        assert years[2018].carried_from_year == 2017


def test_fully_and_partly_allowed_loss_years_are_not_misread() -> None:
    nets = {2014: -1000, 2015: -400, 2016: -600, 2017: -100}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        assert service.set_fully_allowed(2015, True).is_ok  # adds 0
        assert service.set_allowed_loss(2016, "200.00").is_ok  # adds 400
        # Carry-in: 0, 1000, 1000, 1400. Carry-out: 1000, 1000, 1400, 1500.
        _report(service, {2014: 0, 2015: 1000, 2016: 1000, 2017: 1400})
        summary = service.reconcile()
        years = {y.tax_year: y for y in summary.years}
        assert [years[y].expected_carry_in for y in sorted(years)] == [
            D(0), D(1000), D(1000), D(1400)
        ]
        assert [years[y].expected_carryforward for y in sorted(years)] == [
            D(1000), D(1000), D(1400), D(1500)
        ]
        for y in sorted(years):
            assert years[y].status == "ok", y
            assert years[y].drift == D(0)
        assert summary.next_year == 2018
        assert summary.next_year_expected_carry_in == D(1500)
