"""The security evaluation suite.

The suite executes the real guards, so these tests are a check on the check: they confirm the
scenarios still measure what they claim, and that the suite would notice if a guard regressed.
"""

from __future__ import annotations

import pytest

from app.services.evaluation_service import (
    ALL_SCENARIOS,
    INJECTION_SCENARIOS,
    SQL_SCENARIOS,
    Expectation,
    Scenario,
    run_suite,
    summarise,
)


def test_every_scenario_passes_today() -> None:
    failures = [result.scenario.id for result in run_suite() if not result.passed]
    assert failures == [], f"scenarios regressed: {failures}"


def test_the_suite_contains_attacks_and_legitimate_inputs() -> None:
    """A suite of attacks alone cannot detect a guard that refuses everything."""
    expectations = {scenario.expectation for scenario in ALL_SCENARIOS}
    assert Expectation.REFUSE in expectations
    assert Expectation.ALLOW in expectations
    assert Expectation.FLAG in expectations
    assert Expectation.PASS_THROUGH in expectations


def test_there_are_enough_injection_scenarios_to_be_meaningful() -> None:
    attacks = [s for s in INJECTION_SCENARIOS if s.expectation is Expectation.FLAG]
    assert len(attacks) >= 8


def test_the_sql_suite_covers_each_class_of_mutation() -> None:
    payloads = " ".join(s.payload.upper() for s in SQL_SCENARIOS)
    for keyword in ("DROP", "DELETE", "UPDATE", "ATTACH", "PRAGMA"):
        assert keyword in payloads


def test_summary_separates_attacks_from_benign_inputs() -> None:
    summary = summarise(run_suite())
    assert summary["total"] == len(ALL_SCENARIOS)
    assert summary["passed"] == summary["total"]
    assert summary["failed"] == 0
    assert summary["pass_rate"] == 1.0
    # Reported apart because they fail in opposite directions.
    assert summary["attacks_blocked"] == summary["attacks_total"]
    assert summary["benign_allowed"] == summary["benign_total"]
    assert summary["attacks_total"] > 0
    assert summary["benign_total"] > 0


def test_every_scenario_explains_itself() -> None:
    """The Evaluation page shows these verbatim, so an empty one is a visible hole."""
    for scenario in ALL_SCENARIOS:
        assert scenario.name
        assert scenario.rationale
        assert scenario.payload.strip() or scenario.id.endswith("empty")


def test_scenario_ids_are_unique() -> None:
    ids = [scenario.id for scenario in ALL_SCENARIOS]
    assert len(ids) == len(set(ids))


def test_results_carry_the_detail_the_page_renders() -> None:
    for result in run_suite():
        assert result.observed in {"allowed", "refused", "flagged", "clean"}
        assert result.detail


def test_the_suite_is_deterministic() -> None:
    first = [(r.scenario.id, r.passed, r.observed) for r in run_suite()]
    second = [(r.scenario.id, r.passed, r.observed) for r in run_suite()]
    assert first == second


@pytest.mark.parametrize(
    "scenario",
    [s for s in SQL_SCENARIOS if s.expectation is Expectation.ALLOW],
    ids=lambda s: s.id,
)
def test_legitimate_sql_is_not_blocked(scenario: Scenario) -> None:
    """These are the cases a keyword-matching guard gets wrong."""
    result = next(r for r in run_suite() if r.scenario.id == scenario.id)
    assert result.passed
    assert result.observed == "allowed"
