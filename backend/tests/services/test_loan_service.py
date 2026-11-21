"""LoanService (anchor shape) against a moto-backed table."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import boto3
import pytest
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.repository import keys
from logstead.repository.dynamo_repo import DynamoRepository
from logstead.services.loan import LoanService, StoredLoanError

TABLE_NAME = "Logstead"
PROP = "prop-1"


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("PK", "SK", "GSI2PK", "GSI2SK")
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoRepository(ddb, TABLE_NAME)


@pytest.fixture
def service(repo):
    return LoanService(repo, today=lambda: date(2025, 6, 1))


def _input(**kw) -> LoanInput:
    """Default: 214,500.00 at 6.875% anchored 2025-06-01 (payments run to 2037)."""
    base = dict(
        property_id=PROP,
        description="Mortgage",
        annual_interest_rate=Decimal("6.875"),
        monthly_payment=Decimal("1970.79"),
        anchor_balance=Decimal("214500.00"),
        anchor_date="2025-06-01",
        original_principal=Decimal("300000.00"),
        closing_date="2022-02-14",
    )
    base.update(kw)
    return LoanInput(**base)


def _small(**kw) -> LoanInput:
    """5 zero-interest payments of 1000.00: 2025-07-01 .. 2025-11-01."""
    base = dict(
        annual_interest_rate=Decimal("0"),
        monthly_payment=Decimal("1000.00"),
        anchor_balance=Decimal("5000.00"),
        original_principal=None,
        closing_date=None,
    )
    base.update(kw)
    return _input(**base)


def _rollup_sks(repo, loan_id):
    rows = repo.query(
        keys.property_scoped_pk(PROP),
        sk_begins_with=keys.loan_year_list_prefix(loan_id),
        money_attrs=set(),
    )
    return [r["SK"] for r in rows]


def _raw_loan(repo, loan_id):
    return repo.get_item(
        keys.property_scoped_pk(PROP), keys.loan_sk(loan_id), money_attrs=set()
    )


def _raw_rollup(repo, loan_id, year):
    return repo.get_item(
        keys.property_scoped_pk(PROP),
        keys.loan_year_sk(loan_id, year),
        money_attrs=set(),
    )


def _years(service, loan_id):
    return [y.tax_year for y in service.schedule_for(PROP, loan_id).value.yearly]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_writes_loan_and_rollups(service, repo):
    res = service.create_loan(_input())
    assert res.error is None
    view = res.value
    assert view.status == "active"
    assert view.anchor_balance == Decimal("214500.00")
    assert view.anchor_date == "2025-06-01"
    assert view.next_payment_date == "2025-07-01"
    assert view.remaining_payments == len(
        service.schedule_for(PROP, view.id).value.payments
    )
    assert view.projected_payoff_date is not None and view.payoff_balance is None
    years = _years(service, view.id)
    assert years[0] == 2025 and years == list(range(2025, years[-1] + 1))
    assert len(_rollup_sks(repo, view.id)) == len(years)
    assert service.get_loan(PROP, view.id).value == view
    assert [v.id for v in service.list_loans(PROP).value] == [view.id]


def test_create_derived_fields_for_small_loan(service):
    view = service.create_loan(_small()).value
    assert view.remaining_payments == 5
    assert view.next_payment_date == "2025-07-01"
    assert view.projected_payoff_date == "2025-11-01"
    assert view.extra_principal == Decimal("0.00")
    assert view.original_principal is None


def test_create_validation_failure_writes_nothing(service):
    res = service.create_loan(_input(description=" ", anchor_balance=Decimal("0")))
    assert res.error.kind == "validation"
    assert service.list_loans(PROP).value == []


def test_create_payment_not_above_interest_is_validation_on_payment(service):
    res = service.create_loan(_input(monthly_payment=Decimal("100.00")))
    assert res.error.kind == "validation"
    assert res.error.field == "monthly_payment"
    assert service.list_loans(PROP).value == []


def test_create_over_600_payments_is_validation_on_payment(service):
    # 0% interest, 700 payments of 1.00 -> needs more than 600 rows.
    res = service.create_loan(
        _small(monthly_payment=Decimal("1.00"), anchor_balance=Decimal("700.00"))
    )
    assert res.error.kind == "validation"
    assert res.error.field == "monthly_payment"


def test_create_payment_past_year_9999_is_validation_on_anchor_date(service):
    res = service.create_loan(_small(anchor_date="9999-12-01"))
    assert res.error.kind == "validation"
    assert res.error.field == "anchor_date"


def test_update_drops_stale_rollups_and_keeps_created_at(service, repo):
    view = service.create_loan(_input()).value
    assert len(_rollup_sks(repo, view.id)) > 3
    upd = service.update_loan(PROP, view.id, _small())
    assert upd.error is None
    assert upd.value.created_at == view.created_at
    assert upd.value.remaining_payments == 5
    assert len(_rollup_sks(repo, view.id)) == 1  # 2025 only


def test_update_missing_is_not_found(service):
    res = service.update_loan(PROP, "nope", _input(description=""))
    assert res.error.kind == "not_found"
    assert res.error.field == "loan_id"


def test_delete_removes_loan_and_rollups(service, repo):
    view = service.create_loan(_input()).value
    assert service.delete_loan(PROP, view.id).error is None
    assert service.list_loans(PROP).value == []
    assert _rollup_sks(repo, view.id) == []
    assert service.delete_loan(PROP, view.id).error.kind == "not_found"


def test_ended_status_when_fully_paid_in_past(repo):
    svc = LoanService(repo, today=lambda: date(2026, 1, 1))
    assert svc.create_loan(_small()).value.status == "ended"


def test_read_seams_empty_property(service):
    assert service.property_effective_interest_for_year(PROP, 2025) == Decimal("0.00")
    assert service.report_years(PROP) == set()
    assert service.earliest_year(PROP) is None


# ---------------------------------------------------------------------------
# Anchor year and override-only years
# ---------------------------------------------------------------------------


def test_anchor_year_row_has_partial_year_payments(service):
    view = service.create_loan(_input()).value
    first = service.schedule_for(PROP, view.id).value.yearly[0]
    assert first.tax_year == 2025
    assert first.payments == 6  # Jul..Dec after the June anchor payment
    assert first.interest_override is None and first.variance is None
    assert first.ending_balance is not None


def test_schedule_without_override_has_no_variance(service):
    view = service.create_loan(_input()).value
    sched = service.schedule_for(PROP, view.id).value
    assert sched.estimate is True
    assert sched.payments[0].date == "2025-07-01"
    assert all(y.interest == y.estimated_interest for y in sched.yearly)


def test_set_override_on_generated_year_persists_with_signed_variance(service, repo):
    view = service.create_loan(_input()).value
    est = service.schedule_for(PROP, view.id).value.yearly[0].estimated_interest
    res = service.set_interest_override(PROP, view.id, 2025, "100.00")
    assert res.error is None
    assert res.value.interest == Decimal("100.00")
    assert res.value.variance == Decimal("100.00") - est < 0
    assert service.get_loan(PROP, view.id).value.interest_overrides == {
        "2025": Decimal("100.00")
    }
    row = _raw_rollup(repo, view.id, 2025)
    assert row["interestOverride"] == "100.00"
    assert row["effectiveInterest"] == "100.00"
    assert row["endingBalance"]  # generated rows keep an ending balance


def test_override_only_year_before_anchor(service, repo):
    view = service.create_loan(_input()).value
    res = service.set_interest_override(PROP, view.id, 2023, "20650.12")
    assert res.error is None
    v = res.value
    assert v.tax_year == 2023 and v.payments == 0
    assert v.interest == Decimal("20650.12")
    assert v.estimated_interest == Decimal("0.00")
    assert v.variance == Decimal("20650.12")
    assert v.principal == Decimal("0.00") and v.total_paid == Decimal("0.00")
    assert v.ending_balance is None

    row = _raw_rollup(repo, view.id, 2023)
    assert row["payments"] == 0
    assert "endingBalance" not in row
    assert row["effectiveInterest"] == "20650.12"

    sched = service.schedule_for(PROP, view.id).value
    assert sched.yearly[0].tax_year == 2023 and sched.yearly[0].ending_balance is None
    assert service.get_loan(PROP, view.id).value.interest_overrides == {
        "2023": Decimal("20650.12")
    }
    # Report-side seams see the override-only row.
    assert service.property_effective_interest_for_year(PROP, 2023) == Decimal("20650.12")
    assert 2023 in service.report_years(PROP)
    assert service.earliest_year(PROP) == 2023


def test_clearing_override_only_year_removes_its_row(service, repo):
    view = service.create_loan(_input()).value
    service.set_interest_override(PROP, view.id, 1999, "5.00")
    assert service.earliest_year(PROP) == 1999
    assert service.clear_interest_override(PROP, view.id, 1999).value is None
    assert _raw_rollup(repo, view.id, 1999) is None
    assert service.get_loan(PROP, view.id).value.interest_overrides == {}
    assert service.earliest_year(PROP) == 2025


@pytest.mark.parametrize(
    "year,amount",
    [(1899, "10.00"), (2099, "10.00"), (2025, "-1.00"), (2025, "1.001"),
     (2025, "abc"), (2025, "1000000000.00"), (2025, 5.0)],
)
def test_set_override_invalid_writes_nothing(service, year, amount):
    view = service.create_loan(_input()).value
    res = service.set_interest_override(PROP, view.id, year, amount)
    assert res.error.kind == "validation"
    assert res.error.field == f"interest_overrides.{year}"
    assert service.get_loan(PROP, view.id).value.interest_overrides == {}


def test_year_after_payoff_is_rejected_but_anchor_year_is_not(service):
    view = service.create_loan(_small()).value  # pays off in 2025
    assert service.set_interest_override(PROP, view.id, 2026, "1.00").error.kind == "validation"
    assert service.set_interest_override(PROP, view.id, 2025, "1.00").error is None


def test_clear_override_restores_estimate(service):
    view = service.create_loan(_input()).value
    est = service.schedule_for(PROP, view.id).value.yearly[0].estimated_interest
    service.set_interest_override(PROP, view.id, 2025, Decimal("50.00"))
    res = service.clear_interest_override(PROP, view.id, 2025)
    assert res.error is None
    assert res.value.interest == est and res.value.variance is None
    assert service.get_loan(PROP, view.id).value.interest_overrides == {}
    # Clearing again succeeds; a year with no row yields None.
    assert service.clear_interest_override(PROP, view.id, 2025).error is None
    assert service.clear_interest_override(PROP, view.id, 1999).value is None


def test_update_keeps_only_still_allowed_overrides(service, repo):
    view = service.create_loan(_input()).value
    service.set_interest_override(PROP, view.id, 2023, "10.00")  # <= anchor year
    service.set_interest_override(PROP, view.id, 2030, "20.00")  # generated year
    upd = service.update_loan(PROP, view.id, _small())  # pays off in 2025
    assert upd.error is None
    assert upd.value.interest_overrides == {"2023": Decimal("10.00")}
    assert _years(service, view.id) == [2023, 2025]
    assert _raw_rollup(repo, view.id, 2030) is None
    assert _raw_rollup(repo, view.id, 2023) is not None


def test_effective_interest_sums_included_loans_and_uses_override(service):
    a = service.create_loan(_input()).value
    b = service.create_loan(_input(description="Second", anchor_date="2025-09-01")).value
    est_a = service.schedule_for(PROP, a.id).value.yearly[0].estimated_interest
    est_b = service.schedule_for(PROP, b.id).value.yearly[0].estimated_interest
    assert service.property_effective_interest_for_year(PROP, 2025) == est_a + est_b
    service.set_interest_override(PROP, a.id, 2025, Decimal("50.00"))
    assert service.property_effective_interest_for_year(PROP, 2025) == Decimal("50.00") + est_b
    assert service.property_effective_interest_for_year(PROP, 2010) == Decimal("0.00")
    assert service.property_effective_interest_for_year("other", 2025) == Decimal("0.00")


def test_excluded_loan_is_left_out_of_seams(service):
    inc = service.create_loan(_small(description="In")).value
    service.create_loan(
        _small(description="Out", anchor_date="2020-01-01", include_in_report=False)
    )
    est = service.schedule_for(PROP, inc.id).value.yearly[0].estimated_interest
    assert service.property_effective_interest_for_year(PROP, 2025) == est
    assert service.property_effective_interest_for_year(PROP, 2020) == Decimal("0.00")
    assert service.report_years(PROP) == {2025}
    # earliest_year spans all loans, included or not.
    assert service.earliest_year(PROP) == 2020


def test_corrupt_rollup_raises_in_seam_but_not_in_schedule(service, repo):
    view = service.create_loan(_input()).value
    item = _raw_rollup(repo, view.id, 2025)
    item["interest"] = "not-money"
    repo.put_item(item, money_attrs=set())
    with pytest.raises(StoredLoanError):
        service.property_effective_interest_for_year(PROP, 2025)
    # schedule_for is engine-derived and never reads stored rollups (D10).
    assert service.schedule_for(PROP, view.id).error is None


# ---------------------------------------------------------------------------
# Failure injection (fake repo raising ClientError)
# ---------------------------------------------------------------------------

from botocore.exceptions import ClientError  # noqa: E402


def _snapshot():
    """Every raw item in the table, sorted, for before/after comparison."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    items = ddb.scan(TableName=TABLE_NAME)["Items"]
    return sorted(items, key=lambda i: (i["PK"]["S"], i["SK"]["S"]))


class _FailingWrites:
    """Repo proxy whose ``transact_write`` raises; everything else delegates."""

    def __init__(self, inner, exc=None):
        self._inner = inner
        self.calls = []
        self._exc = exc or ClientError(
            {"Error": {"Code": "InternalServerError", "Message": "boom"}},
            "TransactWriteItems",
        )

    def transact_write(self, actions, **kw):
        self.calls.append(list(actions))
        raise self._exc

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _failing_service(repo):
    proxy = _FailingWrites(repo)
    return LoanService(proxy, today=lambda: date(2025, 6, 1)), proxy


def test_create_transact_failure_is_unavailable_and_writes_nothing(repo):
    svc, proxy = _failing_service(repo)
    before = _snapshot()
    res = svc.create_loan(_input())
    assert res.error.kind == "unavailable"
    assert len(proxy.calls) == 1
    assert _snapshot() == before == []


def test_update_transact_failure_leaves_table_unchanged(service, repo):
    view = service.create_loan(_input()).value
    before = _snapshot()
    svc, _ = _failing_service(repo)
    res = svc.update_loan(PROP, view.id, _small())
    assert res.error.kind == "unavailable"
    assert _snapshot() == before


def test_delete_transact_failure_leaves_table_unchanged(service, repo):
    view = service.create_loan(_input()).value
    before = _snapshot()
    svc, _ = _failing_service(repo)
    assert svc.delete_loan(PROP, view.id).error.kind == "unavailable"
    assert _snapshot() == before


def test_override_transact_failure_leaves_table_unchanged(service, repo):
    view = service.create_loan(_input()).value
    service.set_interest_override(PROP, view.id, 2025, "75.00")
    before = _snapshot()
    svc, _ = _failing_service(repo)
    assert svc.set_interest_override(PROP, view.id, 2023, "10.00").error.kind == "unavailable"
    assert svc.set_interest_override(PROP, view.id, 2026, "10.00").error.kind == "unavailable"
    assert svc.clear_interest_override(PROP, view.id, 2025).error.kind == "unavailable"
    assert _snapshot() == before


def test_botocore_error_is_also_unavailable(service, repo):
    from botocore.exceptions import EndpointConnectionError

    view = service.create_loan(_input()).value
    proxy = _FailingWrites(repo, EndpointConnectionError(endpoint_url="http://x"))
    svc = LoanService(proxy, today=lambda: date(2025, 6, 1))
    assert svc.delete_loan(PROP, view.id).error.kind == "unavailable"


def test_not_found_cases_for_every_operation(service):
    assert service.get_loan(PROP, "nope").error.kind == "not_found"
    assert service.schedule_for(PROP, "nope").error.kind == "not_found"
    assert service.set_interest_override(PROP, "nope", 2025, "1.00").error.kind == "not_found"
    assert service.clear_interest_override(PROP, "nope", 2025).error.kind == "not_found"
    assert service.delete_loan(PROP, "nope").error.kind == "not_found"
    view = service.create_loan(_input()).value
    assert service.get_loan("other", view.id).error.kind == "not_found"


# ---------------------------------------------------------------------------
# 100-action transaction guard
# ---------------------------------------------------------------------------


def _plant_stale(repo, loan_id, count):
    for y in range(3000, 3000 + count):
        repo.put_item(
            {
                "PK": keys.property_scoped_pk(PROP),
                "SK": keys.loan_year_sk(loan_id, y),
                "loanId": loan_id,
            },
            money_attrs=set(),
        )


def test_transaction_over_100_actions_is_rejected_without_writing(service, repo):
    view = service.create_loan(_small()).value
    # Update = 1 loan put + 1 rollup put + 99 deletes = 101.
    _plant_stale(repo, view.id, 99)
    before = _snapshot()
    res = service.update_loan(PROP, view.id, _small())
    assert res.error.kind == "validation"
    assert res.error.field == "interest_overrides"
    assert "too many yearly interest totals" in res.error.message
    assert _snapshot() == before


def test_exactly_100_actions_is_allowed(service, repo):
    view = service.create_loan(_small()).value
    # 1 loan put + 1 rollup put + 98 deletes = 100.
    _plant_stale(repo, view.id, 98)
    res = service.update_loan(PROP, view.id, _small())
    assert res.error is None
    assert len(_rollup_sks(repo, view.id)) == 1


def test_too_many_override_only_years_is_rejected_on_set(service, repo):
    view = service.create_loan(_small()).value
    # 1 loan put + 1 generated rollup + 98 override-only years = 100: fine.
    overrides = {str(1900 + i): "1.00" for i in range(98)}
    item = _raw_loan(repo, view.id)
    item["interestOverrides"] = overrides
    repo.put_item(item, money_attrs=set())
    before = _snapshot()
    res = service.set_interest_override(PROP, view.id, 1950, "2.00")  # replaces, still 100
    assert res.error is None
    res = service.set_interest_override(PROP, view.id, 2000, "2.00")  # 99th year
    assert res.error.kind == "validation"
    assert res.error.field == "interest_overrides"
    assert "2000" not in service.get_loan(PROP, view.id).value.interest_overrides
    assert before != _snapshot()  # only the successful replace changed anything


# ---------------------------------------------------------------------------
# Strict reads: corrupt or missing anchor attributes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,bad",
    [
        ("monthlyPayment", "12"),
        ("anchorBalance", "12"),
        ("anchorBalance", Decimal("5")),
        ("anchorDate", "2025-13-45"),
        ("anchorDate", "20250601"),
        ("anchorDate", 7),
        ("annualInterestRate", "NaN"),
        ("annualInterestRate", "x"),
        ("originalPrincipal", "12"),
        ("includeInReport", "yes"),
        ("extraPrincipal", "1"),
        ("interestOverrides", {"2024": "1"}),
        ("interestOverrides", "nope"),
        ("description", 7),
        ("createdAt", None),
        ("monthlyPayment", None),
        ("anchorBalance", None),
        ("anchorDate", None),
    ],
)
def test_corrupt_or_missing_loan_field_is_conflict_with_field_and_not_written_back(
    service, repo, field, bad
):
    view = service.create_loan(_input()).value
    item = _raw_loan(repo, view.id)
    if bad is None:
        item.pop(field)
    else:
        item[field] = bad
    repo.put_item(item, money_attrs=set())
    before = _snapshot()

    for res in (
        service.get_loan(PROP, view.id),
        service.schedule_for(PROP, view.id),
        service.set_interest_override(PROP, view.id, 2025, "1.00"),
        service.clear_interest_override(PROP, view.id, 2025),
        service.list_loans(PROP),
        service.update_loan(PROP, view.id, _input()),
    ):
        assert res.error.kind == "conflict"
        assert res.error.field == field
    assert _snapshot() == before  # corrupt value never written back


def test_stored_item_missing_anchor_balance_raises_and_maps_to_conflict(service, repo):
    view = service.create_loan(_input()).value
    item = _raw_loan(repo, view.id)
    del item["anchorBalance"]
    repo.put_item(item, money_attrs=set())

    with pytest.raises(StoredLoanError) as exc:
        service.earliest_year(PROP)
    assert exc.value.field == "anchorBalance"

    res = service.get_loan(PROP, view.id)
    assert res.error.kind == "conflict"
    assert res.error.field == "anchorBalance"
    assert "anchorBalance" in res.error.message


def test_old_origination_shape_item_is_conflict_naming_missing_field(service, repo):
    item = {
        "PK": keys.property_scoped_pk(PROP),
        "SK": keys.loan_sk("old"),
        "id": "old",
        "propertyId": PROP,
        "description": "Old",
        "annualInterestRate": "6.875",
        "originalPrincipal": "300000.00",
        "termMonths": 360,
        "firstPaymentDate": "2024-03-01",
        "extraPrincipal": "0.00",
        "includeInReport": True,
        "createdAt": "t",
        "updatedAt": "t",
    }
    repo.put_item(item, money_attrs=set())
    res = service.get_loan(PROP, "old")
    assert res.error.kind == "conflict"
    assert res.error.field in {"anchorDate", "monthlyPayment", "anchorBalance"}


def test_corrupt_loan_raises_in_earliest_year_seam(service, repo):
    view = service.create_loan(_input()).value
    item = _raw_loan(repo, view.id)
    item["anchorDate"] = "bad"
    repo.put_item(item, money_attrs=set())
    with pytest.raises(StoredLoanError):
        service.earliest_year(PROP)


# ---------------------------------------------------------------------------
# ScheduleError mapping on stored loans
# ---------------------------------------------------------------------------


def test_stored_loan_over_600_payments_maps_to_conflict_on_payment(service, repo):
    view = service.create_loan(_input()).value
    item = _raw_loan(repo, view.id)
    item["monthlyPayment"] = "100.00"  # below monthly interest: never pays off
    repo.put_item(item, money_attrs=set())
    before = _snapshot()
    for res in (
        service.get_loan(PROP, view.id),
        service.list_loans(PROP),
        service.schedule_for(PROP, view.id),
        service.set_interest_override(PROP, view.id, 2025, "1.00"),
        service.clear_interest_override(PROP, view.id, 2025),
    ):
        assert res.error.kind == "conflict"
        assert res.error.field == "monthly_payment"
    assert _snapshot() == before


def test_stored_loan_past_year_9999_maps_to_conflict_on_anchor_date(service, repo):
    view = service.create_loan(_small()).value
    item = _raw_loan(repo, view.id)
    item["anchorDate"] = "9999-12-01"
    repo.put_item(item, money_attrs=set())
    for res in (
        service.get_loan(PROP, view.id),
        service.schedule_for(PROP, view.id),
    ):
        assert res.error.kind == "conflict"
        assert res.error.field == "anchor_date"
