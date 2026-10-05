"""The evaluation suite, executed live against the real guards."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.services.evaluation_service import run_suite, summarise

router = APIRouter(
    prefix="/evaluation",
    tags=["evaluation"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/suite")
async def suite() -> dict[str, Any]:
    """Run every scenario now and return what happened.

    Executed on request rather than read from a stored result, so this page cannot drift away
    from the behaviour of the code it reports on.
    """
    results = run_suite()
    return {
        "summary": summarise(results),
        "results": [
            {
                "id": result.scenario.id,
                "category": result.scenario.category,
                "name": result.scenario.name,
                "rationale": result.scenario.rationale,
                "payload": result.scenario.payload,
                "expectation": result.scenario.expectation.value,
                "observed": result.observed,
                "passed": result.passed,
                "detail": result.detail,
            }
            for result in results
        ],
    }
