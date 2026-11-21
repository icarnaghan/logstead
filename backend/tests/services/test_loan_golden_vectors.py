"""Golden-vector test for the loan projection engine.

Asserts ``compute_payment_rows`` against the vectors shared with the
frontend preview (``frontend/src/data/loan-projection-vectors.json``).

**Validates: Requirements 10.6**
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from logstead.models.loan import Loan
from logstead.services.loan import compute_payment_rows, payment_date

_VECTORS_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "data"
    / "loan-projection-vectors.json"
)
_VECTORS: list[dict] = json.loads(_VECTORS_PATH.read_text())


def _loan(v: dict) -> Loan:
    return Loan(
        id="golden",
        property_id="prop",
        description="golden",
        annual_interest_rate=Decimal(v["annual_interest_rate"]),
        monthly_payment=Decimal(v["monthly_payment"]),
        anchor_balance=Decimal(v["anchor_balance"]),
        anchor_date=v["anchor_date"],
        extra_principal=Decimal(v["extra_principal"]),
        payoff_date=v["payoff_date"],
        original_principal=None,
        closing_date=None,
        include_in_report=True,
        interest_overrides={},
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )


def _opt(value: object) -> str | None:
    return None if value is None else str(value)


def test_vector_file_has_expected_count() -> None:
    assert len(_VECTORS) == 62


@pytest.mark.parametrize(
    "vector", _VECTORS, ids=[f"vector-{i}" for i in range(len(_VECTORS))]
)
def test_engine_matches_golden_vector(vector: dict) -> None:
    loan = _loan(vector)
    rows, payoff_balance = compute_payment_rows(loan)

    assert len(rows) == vector["remaining_payments"]
    assert (
        payment_date(date.fromisoformat(loan.anchor_date), 1).isoformat()
        == vector["next_payment_date"]
    )
    assert _opt(payoff_balance) == vector["payoff_balance"]

    # A payoff date that stops the schedule leaves no projected payoff date
    # and no final payment; otherwise the last row is the final payment.
    if payoff_balance is None and rows:
        assert rows[-1].date == vector["projected_payoff_date"]
        assert str(rows[-1].payment) == vector["final_payment"]
    else:
        assert vector["projected_payoff_date"] is None
        assert vector["final_payment"] is None

    assert str(sum((r.interest for r in rows), Decimal("0.00"))) == vector[
        "total_interest"
    ]
