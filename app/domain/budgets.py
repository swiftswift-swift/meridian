"""Budget arithmetic and the stop decision.

Pure functions. The graph asks "may I keep going?" and gets a reason it can put in the report's
limitations section, which is why `BudgetVerdict` carries prose rather than a bare bool.

Budgets exist because an agent that chooses its own tools can loop. A cap on steps alone is not
enough: one step can call a tool fifty times, and a cheap model can still burn wall-clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.models import Budget, BudgetUsage, TokenUsage


class BudgetPreset(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


# Presets are deliberately coarse. An analyst picking "Quick" wants an answer in under a
# minute; the exact token ceiling is not a decision they should have to make.
PRESET_BUDGETS: dict[BudgetPreset, Budget] = {
    BudgetPreset.QUICK: Budget(
        max_steps=4, max_tokens=30_000, max_cost_usd=0.05, max_wall_seconds=90.0
    ),
    BudgetPreset.STANDARD: Budget(
        max_steps=8, max_tokens=90_000, max_cost_usd=0.25, max_wall_seconds=240.0
    ),
    BudgetPreset.DEEP: Budget(
        max_steps=14, max_tokens=200_000, max_cost_usd=0.75, max_wall_seconds=600.0
    ),
}


class BudgetLimit(StrEnum):
    STEPS = "steps"
    TOKENS = "tokens"
    COST = "cost"
    WALL_TIME = "wall_time"


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    """Whether a run may continue, and if not, the sentence that goes in the report."""

    may_continue: bool
    limit_hit: BudgetLimit | None = None
    limitation: str = ""

    @property
    def exhausted(self) -> bool:
        return not self.may_continue


def resolve_budget(preset: BudgetPreset, ceiling: Budget) -> Budget:
    """Clamp a requested preset to the configured ceiling.

    A user may always ask for less than the deployment allows and never for more, so a
    generous preset cannot be used to escape an operator's cost control.
    """
    requested = PRESET_BUDGETS[preset]
    return Budget(
        max_steps=min(requested.max_steps, ceiling.max_steps),
        max_tokens=min(requested.max_tokens, ceiling.max_tokens),
        max_cost_usd=min(requested.max_cost_usd, ceiling.max_cost_usd),
        max_wall_seconds=min(requested.max_wall_seconds, ceiling.max_wall_seconds),
    )


def check_budget(usage: BudgetUsage, budget: Budget) -> BudgetVerdict:
    """Decide whether another step may start.

    Checked before a step, not during one: stopping mid-step would leave a tool call recorded
    with no observation, and the report would cite evidence it never actually read.
    """
    if usage.steps >= budget.max_steps:
        return BudgetVerdict(
            may_continue=False,
            limit_hit=BudgetLimit.STEPS,
            limitation=(
                f"Stopped early: budget reached. The investigation used its full allowance of "
                f"{budget.max_steps} steps, so later planned steps were not executed."
            ),
        )
    if usage.tokens >= budget.max_tokens:
        return BudgetVerdict(
            may_continue=False,
            limit_hit=BudgetLimit.TOKENS,
            limitation=(
                f"Stopped early: budget reached. The token allowance of {budget.max_tokens:,} "
                "was consumed before every step completed."
            ),
        )
    if usage.cost_usd >= budget.max_cost_usd:
        return BudgetVerdict(
            may_continue=False,
            limit_hit=BudgetLimit.COST,
            limitation=(
                f"Stopped early: budget reached. The cost cap of ${budget.max_cost_usd:.2f} "
                f"was reached after ${usage.cost_usd:.4f} of model usage."
            ),
        )
    if usage.wall_seconds >= budget.max_wall_seconds:
        return BudgetVerdict(
            may_continue=False,
            limit_hit=BudgetLimit.WALL_TIME,
            limitation=(
                f"Stopped early: budget reached. The run exceeded its "
                f"{budget.max_wall_seconds:.0f} second time limit."
            ),
        )
    return BudgetVerdict(may_continue=True)


def fraction_used(usage: BudgetUsage, budget: Budget) -> dict[str, float]:
    """Normalised meter readings for the run page, clamped to [0, 1]."""
    return {
        "steps": _ratio(usage.steps, budget.max_steps),
        "tokens": _ratio(usage.tokens, budget.max_tokens),
        "cost": _ratio(usage.cost_usd, budget.max_cost_usd),
        "wall_time": _ratio(usage.wall_seconds, budget.max_wall_seconds),
    }


def _ratio(used: float, allowed: float) -> float:
    if allowed <= 0:
        return 1.0
    return min(1.0, max(0.0, used / allowed))


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-million-token prices, which is how every provider publishes them."""

    prompt_usd_per_million: float
    completion_usd_per_million: float


# Published list prices, used to attribute cost per run. Kept as data so a deployment can
# correct them without a code change when a provider adjusts pricing.
DEFAULT_PRICE_TABLE: dict[str, ModelPrice] = {
    "scripted": ModelPrice(0.0, 0.0),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4o": ModelPrice(2.50, 10.00),
    "llama-3.3-70b-versatile": ModelPrice(0.59, 0.79),
    "llama-3.1-8b-instant": ModelPrice(0.05, 0.08),
}

# Unknown models are costed at this rate rather than zero, so an unpriced model cannot make a
# run look free and slip past the cost cap.
FALLBACK_PRICE = ModelPrice(1.00, 3.00)


def price_for(model_name: str, table: dict[str, ModelPrice] | None = None) -> ModelPrice:
    prices = table if table is not None else DEFAULT_PRICE_TABLE
    return prices.get(model_name, FALLBACK_PRICE)


def estimate_cost_usd(
    usage: TokenUsage, model_name: str, table: dict[str, ModelPrice] | None = None
) -> float:
    price = price_for(model_name, table)
    prompt = usage.prompt_tokens / 1_000_000 * price.prompt_usd_per_million
    completion = usage.completion_tokens / 1_000_000 * price.completion_usd_per_million
    return round(prompt + completion, 6)


def estimate_tokens(text: str) -> int:
    """A cheap token estimate.

    Deliberately not a real tokeniser: loading one would mean a model download, which this
    deployment cannot rely on. Four characters per token is close enough for budget accounting,
    and it errs high on dense text, which fails safe.
    """
    return max(1, (len(text) + 3) // 4)
