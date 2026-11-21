"""Unit examples for the carryforward status tolerance.

Feature: carryforward-tolerance-and-year-range, task 1.9.

Each test provisions an isolated moto DynamoDB + S3 stack, seeds one property
with exactly one transaction per year (so the year's Schedule_E_Net is known to
the cent), records reported values, and asserts status and drift from
``CarryforwardService.reconcile``. Expected carry-ins are made to hit the
real-return figures (10,056.73, 8,691.91, 11,830.40) by choosing the prior
year's loss.

Validates: Requirements 1.2, 1.3, 1.4, 1.7, 1.9, 1.10, 2.3, 2.7, 2.8, 2.9
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
from logstead.services.carryforward import STATUS_TOLERANCE, CarryforwardService
from logstead.services.depreciation import DepreciationService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from logstead.services.transaction import TransactionService

TABLE_NAME = "Logstead"
BUCKET = "logstead-files-test"
REGION = "us-east-1"
USER = "user-abc"


def D(value: str | int | Decimal) -> Decimal:
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


def _build(properties, transactions, nets: dict[int, str | int]) -> None:
    """Seed one property with one transaction per year so net == nets[year]."""
    created = properties.create(
        PropertyInput(
            name="P", address_text="1 Main St", property_type="single_family"
        )
    )
    assert created.is_ok, created.error
    pid = created.value.id
    for year, net in nets.items():
        value = D(net)
        assert value != 0
        result = transactions.create(
            TransactionInput(
                property_id=pid,
                date=f"{year}-03-15",
                amount=abs(value),
                type="income" if value > 0 else "expense",
                category_id="rents-received" if value > 0 else "repairs",
            )
        )
        assert result.is_ok, result.error


def _report(service, reported: dict[int, str | int]) -> None:
    for year, value in reported.items():
        result = service.set_reported(year, str(D(value)))
        assert result.is_ok, result.error


def _years(service) -> dict:
    return {y.tax_year: y for y in service.reconcile().years}


def _single(prior_loss: str, reported: str):
    """Year 2019 expects ``prior_loss`` carried in; only 2019 is reported."""
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, {2018: f"-{prior_loss}", 2019: -1})
        _report(service, {2019: reported})
        year = _years(service)[2019]
        assert year.expected_carry_in == D(prior_loss)
        return year


def test_tolerance_constant_is_two_dollars() -> None:
    assert STATUS_TOLERANCE == Decimal("2.00")


def test_whole_dollar_return_above_cents_is_ok() -> None:
    # Reported 10,057 against expected 10,056.73.
    year = _single("10056.73", "10057")
    assert year.status == "ok"
    assert year.drift == D("0.27")
    assert year.carried_from_year is None


def test_whole_dollar_return_round_up_small_gap_is_ok() -> None:
    # Reported 8,692 against expected 8,691.91.
    year = _single("8691.91", "8692")
    assert year.status == "ok"
    assert year.drift == D("0.09")


def test_whole_dollar_return_against_11830_is_ok() -> None:
    # Reported 11,831 against expected 11,830.40.
    year = _single("11830.40", "11831")
    assert year.status == "ok"
    assert year.drift == D("0.60")


def test_reported_below_expected_by_cents_is_ok() -> None:
    year = _single("8691.91", "8691")
    assert year.status == "ok"
    assert year.drift == D("-0.91")


def test_boundary_exactly_two_dollars_is_ok_and_one_cent_more_is_mismatch() -> None:
    high = _single("5000.00", "5002.00")
    assert high.status == "ok"
    assert high.drift == D("2.00")

    low = _single("5000.00", "4998.00")
    assert low.status == "ok"
    assert low.drift == D("-2.00")

    over = _single("5000.00", "5002.01")
    assert over.status == "mismatch"
    assert over.drift == D("2.01")

    under = _single("5000.00", "4997.99")
    assert under.status == "mismatch"
    assert under.drift == D("-2.01")


def test_blank_zero_line_against_large_expected_is_mismatch() -> None:
    year = _single("9000.00", "0.00")
    assert year.status == "mismatch"
    assert year.drift == D("-9000.00")
    assert year.carried_from_year is None


def test_return_that_omitted_902_of_carried_loss_is_mismatch() -> None:
    nets = {2019: -9000, 2020: -1000, 2021: -100}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # 2020 carry-in 9000 is right. 2021 should show 9000 + 1000 = 10000,
        # but the return left out 902 of the carried loss.
        _report(service, {2020: 9000, 2021: 9098})
        years = _years(service)
        assert years[2020].status == "ok"
        assert years[2021].expected_carry_in == D(10000)
        assert years[2021].status == "mismatch"
        assert years[2021].drift == D(-902)
        assert years[2021].carried_from_year is None


def test_carried_year_within_tolerance_of_chain_and_outside_of_expected() -> None:
    nets = {2018: -1000, 2019: -1000, 2020: -1000}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # 2019 root-cause error of 20; 2020 chains from it, rounded up 1.00.
        _report(service, {2018: 0, 2019: 1020, 2020: 2021})
        years = _years(service)
        assert years[2019].status == "mismatch"
        assert years[2020].expected_carry_in == D(2000)
        assert years[2020].status == "carried"
        assert years[2020].carried_from_year == 2019
        assert years[2020].drift == D(21)


def test_tolerance_does_not_accumulate_across_years() -> None:
    nets = {2018: -1000, 2019: -1000, 2020: -1000, 2021: -1000}
    # Each return is within 2.00 of the expected figure: all ok.
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2018: 0, 2019: 1002, 2020: 2002, 2021: 3002})
        years = _years(service)
        assert [years[y].status for y in sorted(years)] == ["ok"] * 4

    # A return that carries a 2.00 error forward AND adds 2.00 more drifts 4.00
    # from expected: the first year's slack is not reused, so it is not ok.
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2018: 0, 2019: 1002, 2020: 2004, 2021: 3006})
        years = _years(service)
        assert years[2019].status == "ok"
        assert years[2020].status == "carried"
        assert years[2020].drift == D(4)
        assert years[2021].status == "carried"
        assert years[2021].drift == D(6)

    # Chain slack is not reused either: 3 over the chain value is a mismatch.
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2018: 0, 2019: 1002, 2020: 2005})
        years = _years(service)
        assert years[2020].status == "mismatch"
        assert years[2020].drift == D(5)


def test_gain_year_floor_with_few_dollars_reported() -> None:
    # 2018 loss 1000, 2019 gain 1002: expected 2020 carry-in floors at 0.00.
    nets = {2018: -1000, 2019: 1002, 2020: 100}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2019: 1000, 2020: "1.50"})
        year = _years(service)[2020]
        assert year.expected_carry_in == D(0)
        assert year.status == "ok"
        assert year.drift == D("1.50")

    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2019: 1000, 2020: 2})
        assert _years(service)[2020].status == "ok"

    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2019: 1000, 2020: "2.01"})
        year = _years(service)[2020]
        assert year.status == "mismatch"
        assert year.drift == D("2.01")

    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        _report(service, {2019: 1000, 2020: 5})
        assert _years(service)[2020].status == "mismatch"


def test_first_year_uses_tolerance_against_opening_balance() -> None:
    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2018: -1000})
        _report(service, {2018: 502})
        year = _years(service)[2018]
        assert year.status == "ok"
        assert year.drift == D(2)
        assert year.carried_from_year is None

    with _stack() as (service, properties, transactions):
        assert service.set_opening_balance("500.00").is_ok
        _build(properties, transactions, {2018: -1000})
        _report(service, {2018: "502.01"})
        assert _years(service)[2018].status == "mismatch"


def test_first_year_has_no_chain_rule() -> None:
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, {2018: -1000, 2019: -1000})
        # Only the first year is reported, 10 off: no chain exists -> mismatch.
        _report(service, {2018: 10})
        year = _years(service)[2018]
        assert year.status == "mismatch"
        assert year.carried_from_year is None


def test_unreported_prior_year_falls_back_to_expected_only() -> None:
    nets = {2018: -1000, 2019: -1000, 2020: -1000}
    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # 2019 blank. 2020 expected 2000; reported 2001.50 is within tolerance.
        _report(service, {2018: 0, 2020: "2001.50"})
        years = _years(service)
        assert years[2019].status == "unreported"
        assert years[2020].status == "ok"
        assert years[2020].drift == D("1.50")

    with _stack() as (service, properties, transactions):
        _build(properties, transactions, nets)
        # Same gap, 3 off expected, no chain available -> mismatch, not carried.
        _report(service, {2018: 0, 2020: 2003})
        year = _years(service)[2020]
        assert year.status == "mismatch"
        assert year.carried_from_year is None
