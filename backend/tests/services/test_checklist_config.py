"""Examples for the Year-end checklist configuration (Requirements 3.1, 3.2, 3.3, 3.6)."""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

import logstead.services as services_pkg
from logstead.services.checklist_config import (
    CHECKLIST_CONFIG,
    ChecklistConfig,
    ChecklistConfigError,
)


def test_defaults_are_the_six_proposed_values():
    cfg = CHECKLIST_CONFIG
    assert cfg.large_entry_amount == Decimal("250.00")
    assert cfg.capital_candidate_amount == Decimal("2500.00")
    assert cfg.swing_percent == Decimal("50")
    assert cfg.swing_minimum_amount == Decimal("500.00")
    assert cfg.anchor_max_age_months == 12
    assert cfg.summary_year_count == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"large_entry_amount": Decimal("-0.01")},
        {"capital_candidate_amount": Decimal("-1")},
        {"swing_minimum_amount": Decimal("-0.01")},
        {"large_entry_amount": 250.0},
        {"swing_percent": 50.0},
        {"swing_percent": Decimal("0")},
        {"swing_percent": Decimal("-5")},
        {"anchor_max_age_months": 0},
        {"summary_year_count": 0},
        {"anchor_max_age_months": 1.5},
    ],
)
def test_invalid_value_raises(kwargs):
    with pytest.raises(ChecklistConfigError):
        ChecklistConfig(**kwargs)


def test_money_is_quantized_and_applied_echoes():
    cfg = ChecklistConfig(large_entry_amount=Decimal("10"))
    assert str(cfg.large_entry_amount) == "10.00"
    assert cfg.applied().large_entry_amount == Decimal("10.00")


def _literals(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                yield Decimal(str(value))
            elif isinstance(value, str):
                try:
                    yield Decimal(value)
                except Exception:
                    continue


def test_no_default_money_threshold_literals_outside_config():
    # The money defaults are distinctive; 50, 12 and 5 are too common (line numbers,
    # month counts) to scan for as bare literals.
    watched = {Decimal("250"), Decimal("2500"), Decimal("500")}
    root = Path(services_pkg.__file__).parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "checklist_config.py":
            continue
        found = {v for v in _literals(ast.parse(path.read_text())) if v.is_finite()} & watched
        if found:
            offenders.append((path.name, sorted(found)))
    assert offenders == []
