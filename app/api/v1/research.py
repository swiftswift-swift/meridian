"""Ask a question in natural language and get a verified, cited answer."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.chat.openai_chat import OpenAiChatAdapter
from app.api.deps import ContainerDep, get_current_user
from app.container import ServiceContainer
from app.domain.errors import ValidationError
from app.services.company_query_service import CompanyQueryService
from app.services.research_service import ResearchService
from app.settings import LlmProvider

router = APIRouter(
    prefix="/research",
    tags=["research"],
    dependencies=[Depends(get_current_user)],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class StepView(BaseModel):
    source_id: str
    purpose: str
    sql: str
    executed_sql: str
    ok: bool
    refused: bool
    reason: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    latency_ms: int


class AnswerView(BaseModel):
    question: str
    answerable: bool
    plan: list[str]
    steps: list[StepView]
    title: str
    body: str
    limitation: str
    verification_score: float
    removed_claims: list[str]
    model: str
    tokens: int
    cost_usd: float
    elapsed_ms: int
    message: str


def _build(container: ServiceContainer) -> ResearchService:
    settings = container.settings
    if settings.llm_provider is not LlmProvider.OPENAI:
        raise ValidationError(
            "This endpoint needs a real language model. Set LLM_PROVIDER=openai with "
            "OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL, then restart the server."
        )
    chat = OpenAiChatAdapter(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key.get_secret_value() if settings.openai_api_key else None,
        model=settings.openai_model,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
    queries = CompanyQueryService(
        container.database,
        row_limit=settings.sql_row_limit,
        timeout_seconds=settings.sql_statement_timeout_seconds,
    )
    return ResearchService(chat, queries)


@router.get("/status")
async def status(container: ContainerDep) -> dict[str, Any]:
    """Whether free-form questions are available, so the UI can say so before asking."""
    settings = container.settings
    enabled = settings.llm_provider is LlmProvider.OPENAI
    return {
        "enabled": enabled,
        "model": settings.openai_model if enabled else "scripted-demo",
        "provider": settings.openai_base_url if enabled else "built-in",
    }


@router.post("/ask", response_model=AnswerView)
async def ask(payload: AskRequest, container: ContainerDep) -> AnswerView:
    """Plan, query, write and verify.

    The model writes the SQL, but it never reaches a database without passing the same guard a
    user's SQL would, and the answer it writes is checked against the rows that came back.
    """
    service = _build(container)
    answer = await service.answer(payload.question)
    return AnswerView(**asdict(answer))
