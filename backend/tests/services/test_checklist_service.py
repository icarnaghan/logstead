"""Example tests for ``ChecklistService`` (year-end checklist task 4.8).

Requirements 2.1, 4.3, 4.8, 15.4, 15.6, 15.7, 15.8.
"""
from __future__ import annotations

import ast
import inspect
from decimal import Decimal

import pytest
from moto import mock_aws

from logstead.models.loan import LoanInput
from logstead.models.property import Property
from logstead.models.property import PropertyInput
from logstead.models.user import UserContext
from logstead.repository import keys
from logstead.services import checklist as checklist_module
from logstead.services import dashboard as dashboard_module
from logstead.services.carryforward import CarryforwardService
from logstead.services.checklist import ChecklistService
from logstead.services.depreciation import DepreciationService
from logstead.services.loan import LoanService
from logstead.services.property import PropertyService
from logstead.services.report import ReportingService
from tests.services.test_checklist_read_sharing_property import (
    _service as _fake_service,
)
from tests.services.test_imported_marker_update_property import USER_ID, _Env

YEAR = 2023


@pytest.fixture
def env():
    with mock_aws():
        yield _Env()


def _real(env: _Env):
    user = UserContext(user_id=USER_ID)
    properties = PropertyService(env.repo, user)
    depreciation = DepreciationService(env.repo)
    loans = LoanService(env.repo)
    reports = ReportingService(env.txns, depreciation, properties, loans=loans)
    carry = CarryforwardService(
        env.repo, user, reports, properties, env.txns, depreciation, loans=loans
    )
    service = ChecklistService(
        reports, env.txns, depreciation, loans, properties, carry
    )
    return service, loans


def test_year_with_no_data(env):
    service, _ = _real(env)
    result = service.checklist_for(env.property_id, YEAR)
    assert result.is_ok, result.error
    items = {i.id: i for i in result.value.items}
    assert len(items) == 11
    assert items["income_entered"].status == "needs_attention"
    assert items["expenses_entered"].status == "needs_attention"
    assert items["imported_values_edited"].status == "not_applicable"
    assert items["receipts_missing"].status == "not_applicable"


def test_corrupt_loan_is_conflict_and_no_items(env):
    service, loans = _real(env)
    pid = env.property_id
    loan = loans.create_loan(
        LoanInput(
            property_id=pid,
            description="Mortgage",
            annual_interest_rate=Decimal("0"),
            monthly_payment=Decimal("1000.00"),
            anchor_balance=Decimal("5000.00"),
            anchor_date="2022-12-31",
            original_principal=None,
            closing_date=None,
        )
    ).value
    item = env.repo.get_item(
        keys.property_scoped_pk(pid), keys.loan_sk(loan.id), money_attrs=set()
    )
    item["anchorDate"] = "bad"
    env.repo.put_item(item, money_attrs=set())

    result = service.checklist_for(pid, YEAR)
    assert not result.is_ok
    assert result.error.kind == "conflict"
    assert result.ok is None


def test_dashboard_summary_reconciles_once_for_three_properties():
    props = [Property(f"p{i}", "u", f"Prop {i}", "addr") for i in range(3)]
    service, _reports, carry, _txns = _fake_service(props, {})
    result = service.portfolio_summary(YEAR)
    assert result.is_ok
    assert len(result.value.properties) == 3
    assert carry.calls == 1


def test_default_year_is_latest_tax_year_with_frozen_clock(monkeypatch):
    monkeypatch.setattr(dashboard_module, "_current_tax_year", lambda: 2031)
    assert dashboard_module.latest_tax_year() == 2030
    props = [Property("p0", "u", "Prop", "addr")]
    service, reports, _carry, _txns = _fake_service(props, {})
    single = service.checklist_for("p0", None)
    assert single.is_ok
    assert single.value.tax_year == 2030
    assert ("p0", 2030) in reports.calls
    portfolio = service.portfolio_summary(None)
    assert portfolio.is_ok
    assert portfolio.value.tax_year == 2030


def _names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
    return out


def test_source_has_no_tolerance_comparison_or_line_sum():
    tree = ast.parse(inspect.getsource(checklist_module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            assert not any(
                n.lower() == "status_tolerance" for n in _names(node)
            ), f"STATUS_TOLERANCE compared at line {node.lineno}"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sum"
        ):
            assert "schedule_e_line" not in _names(node), (
                f"sum over schedule_e_line at line {node.lineno}"
            )
