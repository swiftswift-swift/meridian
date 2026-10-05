"""Tests for budget arithmetic and the stop decision."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.budgets import (
    PRESET_BUDGETS,
    BudgetLimit,
    BudgetPreset,
    check_budget,
    estimate_cost_usd,
    estimate_tokens,
    fraction_used,
    price_for,
    resolve_budget,
)
from app.domain.models import Budget, BudgetUsage, TokenUsage

CEILING = Budget(max_steps=8, max_tokens=50_000, max_cost_usd=0.20, max_wall_seconds=120.0)


def test_preset_is_clamped_to_the_ceiling() -> None:
    # Deep asks for more than this deployment allows, so the ceiling wins on every axis.
    resolved = resolve_budget(BudgetPreset.DEEP, CEILING)
    assert resolved == CEILING


def test_preset_below_the_ceiling_is_preserved() -> None:
    resolved = resolve_budget(BudgetPreset.QUICK, CEILING)
    quick = PRESET_BUDGETS[BudgetPreset.QUICK]
    assert resolved.max_steps == quick.max_steps
    assert resolved.max_cost_usd == quick.max_cost_usd


@given(preset=st.sampled_from(list(BudgetPreset)))
def test_property_resolved_budget_never_exceeds_the_ceiling(preset: BudgetPreset) -> None:
    resolved = resolve_budget(preset, CEILING)
    assert resolved.max_steps <= CEILING.max_steps
    assert resolved.max_tokens <= CEILING.max_tokens
    assert resolved.max_cost_usd <= CEILING.max_cost_usd
    assert resolved.max_wall_seconds <= CEILING.max_wall_seconds


def test_fresh_run_may_continue() -> None:
    assert check_budget(BudgetUsage(), CEILING).may_continue


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (BudgetUsage(steps=8), BudgetLimit.STEPS),
        (BudgetUsage(tokens=50_000), BudgetLimit.TOKENS),
        (BudgetUsage(cost_usd=0.20), BudgetLimit.COST),
        (BudgetUsage(wall_seconds=120.0), BudgetLimit.WALL_TIME),
    ],
)
def test_each_limit_stops_the_run(usage: BudgetUsage, expected: BudgetLimit) -> None:
    verdict = check_budget(usage, CEILING)
    assert verdict.exhausted
    assert verdict.limit_hit is expected
    # The limitation is what the report shows the user, so it must be prose, not an enum.
    assert "budget reached" in verdict.limitation.lower()


def test_steps_are_checked_before_tokens() -> None:
    # Both are exhausted; the message should name steps, which is the one the user controls.
    verdict = check_budget(BudgetUsage(steps=99, tokens=99_999), CEILING)
    assert verdict.limit_hit is BudgetLimit.STEPS


def test_fractions_are_clamped_to_one() -> None:
    fractions = fraction_used(BudgetUsage(steps=100, tokens=10_000_000), CEILING)
    assert fractions["steps"] == 1.0
    assert fractions["tokens"] == 1.0
    assert 0.0 <= fractions["cost"] <= 1.0


def test_scripted_model_is_free() -> None:
    assert estimate_cost_usd(TokenUsage(prompt_tokens=10_000), "scripted") == 0.0


def test_unknown_model_is_not_free() -> None:
    """An unpriced model must not look free, or it could slip past the cost cap."""
    cost = estimate_cost_usd(TokenUsage(prompt_tokens=10_000, completion_tokens=1_000), "mystery")
    assert cost > 0


def test_known_model_price_is_used() -> None:
    cost = estimate_cost_usd(
        TokenUsage(prompt_tokens=1_000_000, completion_tokens=0), "gpt-4o-mini"
    )
    assert cost == pytest.approx(price_for("gpt-4o-mini").prompt_usd_per_million)


@given(st.text(max_size=400))
def test_property_token_estimate_is_always_positive(text: str) -> None:
    assert estimate_tokens(text) >= 1


@given(
    prompt=st.integers(min_value=0, max_value=1_000_000),
    completion=st.integers(min_value=0, max_value=1_000_000),
)
def test_property_cost_is_monotonic_in_usage(prompt: int, completion: int) -> None:
    base = estimate_cost_usd(
        TokenUsage(prompt_tokens=prompt, completion_tokens=completion), "gpt-4o"
    )
    more = estimate_cost_usd(
        TokenUsage(prompt_tokens=prompt + 1_000, completion_tokens=completion), "gpt-4o"
    )
    assert more >= base
