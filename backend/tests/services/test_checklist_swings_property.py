"""Property 13: year-over-year swings (Requirements 13.1-13.7, 21.3).

An independent ``Decimal`` oracle decides whether a line is a swing; the
checklist's ``swing_for`` and ``yoy_swings`` rule must agree with it.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from logstead.services.checklist import _rule_yoy_swings, swing_for
from logstead.services.checklist_config import ChecklistConfig
from logstead.services.report import ReportLine

_ZERO = Decimal("0.00")
_CENT = Decimal("0.01")

_money = st.decimals(
    min_value=Decimal("0.00"),
    max_value=Decimal("100000.00"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
_configs = st.builds(
    ChecklistConfig,
    swing_percent=st.decimals(
        min_value=Decimal("1"), max_value=Decimal("200"), places=1,
        allow_nan=False, allow_infinity=False,
    ),
    swing_minimum_amount=st.decimals(
        min_value=Decimal("0.00"), max_value=Decimal("2000.00"), places=2,
        allow_nan=False, allow_infinity=False,
    ),
)


@st.composite
def _pair(draw):
    """Prior/current totals, often placed on or next to the percent boundary."""
    prior = draw(_money)
    if draw(st.booleans()):
        return prior, draw(_money)
    pct = draw(st.sampled_from([Decimal("10"), Decimal("25"), Decimal("50"), Decimal("100")]))
    delta = draw(st.integers(min_value=-2, max_value=2)) * _CENT
    sign = draw(st.sampled_from([1, -1]))
    current = prior + sign * (prior * pct / 100) + delta
    current = max(_ZERO, current.quantize(_CENT, rounding=ROUND_HALF_UP))
    return prior, current


def _oracle(prior: Decimal, current: Decimal, config: ChecklistConfig):
    """Return (is_swing, change, percent) straight from Requirement 13.3/13.6."""
    change = current - prior
    if abs(change) < config.swing_minimum_amount:
        return False, change, None
    if prior == 0:
        return True, change, None
    pct = (abs(change) * 100 / prior).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return pct >= config.swing_percent, change, pct


def _snapshot(prior_totals, current_totals):
    def report(totals):
        rows = tuple(
            ReportLine(3 + i, f"L{3 + i}", "income", t) for i, t in enumerate(totals)
        )
        return SimpleNamespace(lines=rows)

    return SimpleNamespace(
        property_id="p1",
        tax_year=2024,
        report=report(current_totals),
        prior_report=report(prior_totals),
    )


# Feature: year-end-checklist, Property 13: Year-over-year swings
# **Validates: Requirements 13.3, 13.6, 21.3**
@settings(max_examples=300, deadline=None)
@given(pair=_pair(), config=_configs)
def test_swing_for_matches_oracle(pair, config):
    prior, current = pair
    expected, change, pct = _oracle(prior, current, config)
    found = swing_for(prior, current, config)
    assert (found is not None) == expected
    if found is not None:
        assert found.prior == prior and found.current == current
        assert found.change == change
        assert found.percent == pct


# **Validates: Requirements 13.1, 13.2, 13.4, 13.5, 13.7**
@settings(max_examples=200, deadline=None)
@given(
    pairs=st.lists(_pair(), min_size=1, max_size=8),
    config=_configs,
)
def test_yoy_rule_status_and_details(pairs, config):
    priors = [p for p, _ in pairs]
    currents = [c for _, c in pairs]
    item = _rule_yoy_swings(_snapshot(priors, currents), config)
    if all(p == 0 for p in priors):
        assert item.status == "not_applicable"
        assert item.details["swings"] == []
        return
    expected = [
        (3 + i, *_oracle(p, c, config)[1:])
        for i, (p, c) in enumerate(pairs)
        if _oracle(p, c, config)[0]
    ]
    listed = item.details["swings"]
    assert [(s["line"], s["change"], s["percent"]) for s in listed] == expected
    for s, (p, c) in zip(listed, [pairs[line - 3] for line, _, _ in expected]):
        assert s["prior_total"] == p and s["current_total"] == c
        assert (s["percent"] is None) == (p == 0)
    assert item.status == ("needs_attention" if expected else "done")


def test_boundary_examples():
    config = ChecklistConfig()  # 50% and 500.00
    # exactly 50.0% and exactly 500.00 -> swing
    assert swing_for(Decimal("1000.00"), Decimal("1500.00"), config) is not None
    # 49.95% rounds half-up to 50.0 -> swing, compared after rounding
    assert swing_for(Decimal("10000.00"), Decimal("14995.00"), config) is not None
    # 49.94% rounds to 49.9 -> not a swing
    assert swing_for(Decimal("10000.00"), Decimal("14994.00"), config) is None
    # change below the minimum amount -> not a swing, even from zero
    assert swing_for(Decimal("0.00"), Decimal("499.99"), config) is None
    found = swing_for(Decimal("0.00"), Decimal("500.00"), config)
    assert found is not None and found.percent is None
