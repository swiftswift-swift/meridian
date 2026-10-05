"""Data source endpoints: schema browser, knowledge base, and the SQL guard playground."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.adapters.embedding.hash_embedding import HashEmbedding
from app.api.deps import ContainerDep, get_current_user
from app.services.company_query_service import CompanyQueryService
from app.services.document_service import DocumentService

# Authentication is declared on the router rather than as a parameter each handler ignores.
router = APIRouter(
    prefix="/datasources",
    tags=["data sources"],
    dependencies=[Depends(get_current_user)],
)


class TableView(BaseModel):
    name: str
    columns: list[str]
    description: str
    row_count: int


class SqlCheckRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=4_000)


class SqlCheckResponse(BaseModel):
    ok: bool
    refused: bool
    reason: str = ""
    guardrail: str = ""
    executed_sql: str = ""
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    latency_ms: int = 0
    referenced_tables: list[str] = []
    limit_applied: int | None = None


class DocumentView(BaseModel):
    id: str
    title: str
    doc_type: str
    chunk_count: int
    is_suspicious: bool
    suspicion_reason: str
    excerpt: str


def _query_service(container: ContainerDep) -> CompanyQueryService:
    return CompanyQueryService(
        container.database,
        row_limit=container.settings.sql_row_limit,
        timeout_seconds=container.settings.sql_statement_timeout_seconds,
    )


@router.get("/schema", response_model=list[TableView])
async def schema(container: ContainerDep) -> list[TableView]:
    tables = await _query_service(container).describe_schema()
    return [TableView(**table) for table in tables]


@router.get("/tables/{table}/sample", response_model=SqlCheckResponse)
async def sample(table: str, container: ContainerDep) -> SqlCheckResponse:
    """Sample rows. Routed through the guard, so an invented table name is refused, not 404'd."""
    result = await _query_service(container).sample_rows(table)
    return SqlCheckResponse(**asdict(result))


@router.post("/sql-check", response_model=SqlCheckResponse)
async def sql_check(payload: SqlCheckRequest, container: ContainerDep) -> SqlCheckResponse:
    """Run a query against the read-only company database, or explain why it was refused.

    This is the same guard and the same read-only engine the agent's `sql_query` tool uses, so
    what a user sees here is exactly what the agent would be allowed to do.
    """
    result = await _query_service(container).run(payload.sql)
    return SqlCheckResponse(**asdict(result))


@router.get("/documents", response_model=list[DocumentView])
async def documents(container: ContainerDep) -> list[DocumentView]:
    service = DocumentService(
        container.database, HashEmbedding(container.settings.hash_embedding_dimensions)
    )
    rows = await service.list_documents()
    return [
        DocumentView(
            id=row.id,
            title=row.title,
            doc_type=row.doc_type,
            chunk_count=row.chunk_count,
            is_suspicious=row.is_suspicious,
            suspicion_reason=row.suspicion_reason,
            excerpt=row.content[:280].strip(),
        )
        for row in rows
    ]


@router.get("/providers")
async def providers(container: ContainerDep) -> dict[str, Any]:
    """What this deployment is actually wired to, for the status panel."""
    return container.describe_providers()
