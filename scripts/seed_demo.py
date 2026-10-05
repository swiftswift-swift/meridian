"""Seed the demo databases. Idempotent: running it twice leaves identical data.

    python -m scripts.seed_demo

Idempotence matters more than it sounds. The acceptance checks run the seed twice and compare row
counts, and a seed that appends would make every demo figure drift between runs.

The approach is deterministic ids plus delete-and-rewrite for the company tables, rather than
upserting row by row. The company database is generated data with no external references, so
rewriting it is both simpler and provably idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.embedding.hash_embedding import HashEmbedding
from app.container import ServiceContainer
from app.domain.models import Role
from app.infra.db import Database
from app.infra.logging import configure_logging
from app.infra.models import EvaluationResult, EvaluationRun, Report, Run, User
from app.services.auth_service import AuthService
from app.services.document_service import DocumentService
from app.settings import Settings
from company_db import generate as company_generate
from company_db.documents import DOCUMENTS
from company_db.schema import DDL

logger = structlog.get_logger("seed")

DEMO_PASSWORD = "demo-password"  # noqa: S105 - a seeded demo credential, documented in the README

DEMO_USERS = (
    ("admin@meridian.demo", "Dana Admin", Role.ADMIN),
    ("analyst@meridian.demo", "Avery Analyst", Role.ANALYST),
    ("viewer@meridian.demo", "Robin Viewer", Role.VIEWER),
)


# Stable ids so documents can be re-ingested in place rather than duplicated.
def _document_id(index: int) -> str:
    return f"seeddoc{index:024d}"


async def seed_company_database(database: Database) -> dict[str, int]:
    """Create and populate the read-only company schema."""
    data = company_generate.generate()

    # The company engine is opened read-only, so writing needs its own engine. Creating one here
    # rather than relaxing the shared engine keeps the read-only guarantee intact for the path
    # the agent uses.
    url = str(database.company_engine.url)
    writable = create_async_engine(url, future=True)
    try:
        async with writable.begin() as connection:
            for statement in DDL:
                await connection.execute(text(statement))

            for table in (
                "order_items",
                "orders",
                "marketing_spend",
                "customers",
                "products",
                "product_lines",
                "countries",
                "currencies",
                "regions",
            ):
                await connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed list

            await connection.execute(
                text("INSERT INTO regions (id, name, code) VALUES (:id, :name, :code)"),
                [{"id": r[0], "name": r[1], "code": r[2]} for r in company_generate.REGIONS],
            )
            await connection.execute(
                text("INSERT INTO currencies (code, name, symbol) VALUES (:code, :name, :symbol)"),
                [{"code": c[0], "name": c[1], "symbol": c[2]} for c in company_generate.CURRENCIES],
            )
            await connection.execute(
                text(
                    "INSERT INTO countries (id, region_id, name, iso_code, currency_code) "
                    "VALUES (:id, :region_id, :name, :iso_code, :currency_code)"
                ),
                [
                    {
                        "id": c[0],
                        "region_id": c[1],
                        "name": c[2],
                        "iso_code": c[3],
                        "currency_code": c[4],
                    }
                    for c in company_generate.COUNTRIES
                ],
            )
            await connection.execute(
                text(
                    "INSERT INTO product_lines (id, name, category, gross_margin_pct) "
                    "VALUES (:id, :name, :category, :margin)"
                ),
                [
                    {"id": p[0], "name": p[1], "category": p[2], "margin": p[3]}
                    for p in company_generate.PRODUCT_LINES
                ],
            )
            await connection.execute(
                text(
                    "INSERT INTO products "
                    "(id, product_line_id, name, sku, unit_price_usd, unit_cost_usd) "
                    "VALUES (:id, :line, :name, :sku, :price, :cost)"
                ),
                [
                    {
                        "id": p[0],
                        "line": p[1],
                        "name": p[2],
                        "sku": p[3],
                        "price": p[4],
                        "cost": p[5],
                    }
                    for p in company_generate.PRODUCTS
                ],
            )
            await connection.execute(
                text(
                    "INSERT INTO customers "
                    "(id, name, country_id, segment, signed_on, churned_on, annual_contract_usd) "
                    "VALUES (:id, :name, :country, :segment, :signed, :churned, :acv)"
                ),
                [
                    {
                        "id": c[0],
                        "name": c[1],
                        "country": c[2],
                        "segment": c[3],
                        "signed": c[4],
                        "churned": c[5],
                        "acv": c[6],
                    }
                    for c in company_generate.CUSTOMERS
                ],
            )
            await _insert_many(
                connection,
                "INSERT INTO orders (id, customer_id, order_date, currency_code, fx_rate_to_usd, "
                "subtotal_local, subtotal_usd, status) "
                "VALUES (:id, :customer, :date, :currency, :fx, :local, :usd, :status)",
                [
                    {
                        "id": o[0],
                        "customer": o[1],
                        "date": o[2],
                        "currency": o[3],
                        "fx": o[4],
                        "local": o[5],
                        "usd": o[6],
                        "status": o[7],
                    }
                    for o in data.orders
                ],
            )
            await _insert_many(
                connection,
                "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_usd, "
                "discount_pct, line_total_usd) "
                "VALUES (:id, :order, :product, :qty, :price, :discount, :total)",
                [
                    {
                        "id": i[0],
                        "order": i[1],
                        "product": i[2],
                        "qty": i[3],
                        "price": i[4],
                        "discount": i[5],
                        "total": i[6],
                    }
                    for i in data.order_items
                ],
            )
            await connection.execute(
                text(
                    "INSERT INTO marketing_spend (id, region_id, campaign, channel, month, "
                    "spend_usd, attributed_revenue_usd) "
                    "VALUES (:id, :region, :campaign, :channel, :month, :spend, :attributed)"
                ),
                [
                    {
                        "id": m[0],
                        "region": m[1],
                        "campaign": m[2],
                        "channel": m[3],
                        "month": m[4],
                        "spend": m[5],
                        "attributed": m[6],
                    }
                    for m in data.marketing_spend
                ],
            )

        async with writable.connect() as connection:
            counts = {}
            for table in company_generate_tables():
                counts[table] = int(
                    (await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar() or 0  # noqa: S608
                )
        return counts
    finally:
        await writable.dispose()


def company_generate_tables() -> tuple[str, ...]:
    return (
        "regions",
        "countries",
        "currencies",
        "product_lines",
        "products",
        "customers",
        "orders",
        "order_items",
        "marketing_spend",
    )


async def _insert_many(connection: object, statement: str, rows: list[dict[str, object]]) -> None:
    """Insert in batches.

    SQLite caps the number of bound parameters per statement, and two years of order items is
    comfortably past it as a single executemany.
    """
    batch_size = 2_000
    for start in range(0, len(rows), batch_size):
        await connection.execute(text(statement), rows[start : start + batch_size])  # type: ignore[attr-defined]


async def seed_users(auth_service: AuthService, database: Database) -> int:
    created = 0
    for email, name, role in DEMO_USERS:
        async with database.session() as session:
            existing = await session.scalar(select(User).where(User.email == email))
            if existing is not None:
                # Keep the row current without creating a second account.
                existing.display_name = name
                existing.role = role.value
                existing.is_demo = True
                continue
            session.add(
                User(
                    email=email,
                    display_name=name,
                    password_hash=auth_service.hash_password(DEMO_PASSWORD),
                    role=role.value,
                    is_demo=True,
                )
            )
            created += 1
    return created


async def seed_documents(service: DocumentService) -> tuple[int, int]:
    suspicious = 0
    for index, document in enumerate(DOCUMENTS):
        stored = await service.ingest(
            title=document.title,
            content=document.content,
            doc_type=document.doc_type,
            source="seed",
            document_id=_document_id(index),
        )
        if stored.is_suspicious:
            suspicious += 1
    return len(DOCUMENTS), suspicious


async def seed_run_history(database: Database) -> int:
    """Synthetic completed runs so the Insights page has a trend to draw on first use.

    Flagged with a `seeded` marker in `usage` so they are distinguishable from real activity.
    """
    async with database.read_session() as session:
        analyst = await session.scalar(select(User).where(User.email == "analyst@meridian.demo"))
        existing = await session.scalar(
            select(func.count()).select_from(Run).where(Run.idempotency_key.like("seed-history-%"))
        )
    if analyst is None or (existing or 0) > 0:
        return 0

    questions = [
        "Why did EMEA revenue drop in Q3 compared to Q2?",
        "Which product line should we prioritise next quarter?",
        "Is the Quantum Leap campaign worth continuing?",
        "What is driving margin compression in hardware?",
        "How exposed is EMEA revenue to EUR/USD movement?",
        "Which accounts are at renewal risk this quarter?",
    ]
    now = datetime.now(UTC)
    created = 0
    async with database.session() as session:
        for day_offset in range(28, 0, -1):
            # Two or three runs on most days, none on some, so the chart is not a flat line.
            daily = (day_offset * 7) % 4
            for sequence in range(daily):
                index = (day_offset + sequence) % len(questions)
                started = now - timedelta(days=day_offset, hours=sequence * 3)
                duration = 40 + (index * 11) + (sequence * 7)
                # One run in seven fails, and one in nine exhausts its budget, so the outcome
                # chart shows a realistic mix rather than a wall of green.
                if (day_offset + sequence) % 7 == 0:
                    status, score, stopped = "failed", 0.0, None
                elif (day_offset + sequence) % 9 == 0:
                    status, score, stopped = "completed", 0.72, "budget reached"
                else:
                    status, score, stopped = "completed", 0.88 + (index % 3) * 0.04, None

                run = Run(
                    user_id=analyst.id,
                    question=questions[index],
                    status=status,
                    idempotency_key=f"seed-history-{day_offset}-{sequence}",
                    plan={"steps": [], "revision": 0},
                    budget={
                        "max_steps": 8,
                        "max_tokens": 90_000,
                        "max_cost_usd": 0.25,
                        "max_wall_seconds": 240.0,
                    },
                    usage={
                        "steps": 4 + (index % 4),
                        "tokens": 18_000 + index * 2_400,
                        "cost_usd": round(0.012 + index * 0.004, 4),
                        "wall_seconds": float(duration),
                        "tool_calls": 6 + (index % 5),
                        "seeded": True,
                    },
                    allowed_tools=["sql_query", "knowledge_search", "calculator"],
                    stopped_early_reason=stopped,
                    created_at=started,
                    started_at=started,
                    finished_at=started + timedelta(seconds=duration),
                    error="The language model provider timed out." if status == "failed" else None,
                )
                session.add(run)
                await session.flush()
                if status == "completed":
                    session.add(
                        Report(
                            run_id=run.id,
                            title=questions[index],
                            executive_summary="Seeded historical run used for trend charts.",
                            markdown="Seeded historical run used for trend charts.",
                            verification_score=round(score, 4),
                        )
                    )
                created += 1
    return created


async def reset_evaluation_history(database: Database) -> None:
    """Clear seeded evaluation rows so `scripts.evaluate` always writes fresh numbers."""
    async with database.session() as session:
        await session.execute(delete(EvaluationResult))
        await session.execute(delete(EvaluationRun))


async def run_seed(settings: Settings) -> dict[str, object]:
    container = await ServiceContainer.create(settings)
    try:
        database = container.database
        await database.create_all()

        company_counts = await seed_company_database(database)
        auth_service = AuthService(database, settings)
        users_created = await seed_users(auth_service, database)

        embedding = HashEmbedding(settings.hash_embedding_dimensions)
        document_service = DocumentService(database, embedding)
        documents, suspicious = await seed_documents(document_service)
        chunks = await document_service.count_chunks()

        history = await seed_run_history(database)
        await reset_evaluation_history(database)

        return {
            "company": company_counts,
            "users_created": users_created,
            "documents": documents,
            "suspicious_documents": suspicious,
            "chunks": chunks,
            "history_runs": history,
        }
    finally:
        await container.aclose()


def _report(summary: dict[str, object]) -> None:
    company = summary["company"]
    if isinstance(company, dict):
        logger.info("seed.company", **company)
    logger.info(
        "seed.complete",
        users_created=summary["users_created"],
        documents=summary["documents"],
        suspicious_documents=summary["suspicious_documents"],
        chunks=summary["chunks"],
        history_runs=summary["history_runs"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the Meridian demo data.")
    parser.add_argument("--quiet", action="store_true", help="Only report errors.")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.quiet:
        settings.log_level = "ERROR"
    configure_logging(settings)

    summary = asyncio.run(run_seed(settings))
    _report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
