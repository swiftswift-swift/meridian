# Meridian - Build Plan

Source of truth: [SPEC.md](SPEC.md). Working agreements: [CLAUDE.md](CLAUDE.md).
This file tracks progress. Tick a box only after the proving command has been run and its output shown.

Status legend: `[ ]` not started, `[~]` in progress, `[x]` done and proven.

---

## 1. Target folder structure

```
meridian/
  .github/
    workflows/ci.yml                  # lint, typecheck, unit, integration, frontend, eval, audit, docker-build
    ISSUE_TEMPLATE/{bug_report.md,feature_request.md}
    PULL_REQUEST_TEMPLATE.md
    dependabot.yml
  .vscode/
    launch.json                       # API, worker, seed, tests
    settings.json
  app/
    __init__.py
    main.py                           # create_app(settings) factory only
    settings.py                       # pydantic-settings, fail-fast validation
    container.py                      # ServiceContainer: the single composition root
    domain/                           # pure: entities, value objects, errors, policies
      __init__.py
      errors.py                       # DomainError taxonomy
      models.py                       # Pydantic domain entities (Run, Plan, Observation, Report...)
      budgets.py                      # pure budget arithmetic + decisions
      citations.py                    # pure citation extraction/verification
      sql_guard.py                    # pure sqlglot-based SELECT-only validation
      routing.py                      # pure graph routing decisions
      ports.py                        # Protocols: ChatModelPort, EmbeddingPort, SearchProviderPort,
                                      #   QueuePort, CheckpointStorePort, ToolPort, ClockPort
    agent/
      graph.py                        # StateGraph assembly
      state.py                        # AgentState TypedDict
      nodes/{clarify,plan,approve_plan,execute_step,reflect,synthesize,verify,finalize}.py
      prompts/*.md                    # versioned prompt files
      summarise.py                    # observation summarisation above token threshold
    tools/
      registry.py                     # name -> ToolPort, per-run allowlist filtering
      base.py                         # timeout, retry, circuit breaker, structured errors, logging
      sql_query.py knowledge_search.py web_search.py fetch_url.py
      exchange_rates.py wikipedia_summary.py calculator.py
      untrusted.py                    # delimiter wrapping + taint tracking
    adapters/                         # the only place vendor SDKs are imported
      chat/{openai_chat.py,scripted_chat.py}
      embedding/{chroma_local.py,hash_embedding.py,openai_embedding.py}
      search/{tavily.py,ddgs.py,fixtures.py}
      queue/{redis_streams.py,in_process.py}
      checkpoint/{sqlite_saver.py,postgres_saver.py}
      http/{httpx_client.py,ssrf_guard.py}
      cache/{redis_cache.py,memory_cache.py}
    services/                         # orchestration, transactions, no framework types
      auth_service.py run_service.py report_service.py document_service.py
      ledger_service.py memory_service.py evaluation_service.py insights_service.py
      events_service.py              # Pub/Sub publish + SSE fan-out
    api/
      deps.py errors.py               # RFC 9457 problem+json handlers
      middleware.py                   # request id, security headers, rate limit, logging
      v1/{auth,runs,reports,documents,datasources,insights,evaluation,settings,events,health}.py
      spa.py                          # static mount + SPA fallback, /api/docs only
    worker/
      __main__.py                     # python -m app.worker
      loop.py heartbeat.py reaper.py shutdown.py
    infra/
      db.py models.py                 # SQLAlchemy 2.0 ORM
      migrations/                     # Alembic
      logging.py metrics.py tracing.py pricing.py
  company_db/                         # read-only sample company schema + its own engine
  frontend/
    src/{components,features,hooks,lib,pages,styles}
    src/api/types.gen.ts              # generated from OpenAPI, CI fails if stale
    tests/
  scripts/
    seed_demo.py evaluate.py export_graph.py gen_types.py
  tests/
    unit/ integration/ e2e/ fixtures/ load/
  docs/
    architecture.md runbook.md slo.md threat-model.md backlog.md
    evaluation.md performance.md interview-guide.md
    adr/0001..0006-*.md
    postmortems/001-*.md
  tasks.ps1  .env.example  .python-version  .nvmrc  .editorconfig
  requirements.in requirements.txt requirements-dev.in requirements-dev.txt
  pyproject.toml  .pre-commit-config.yaml
  Dockerfile  docker-compose.yml  .dockerignore
  README.md CHANGELOG.md CONTRIBUTING.md SECURITY.md LICENSE
```

## 2. Pinned libraries

Pins are exact. Lock files (`requirements.txt` via pip-tools, `package-lock.json`) are the enforced record;
the tables below are the intent. Where the newest major is very fresh, the plan deliberately picks the
previous stable major so the repo builds the same way in six months.

### Python (3.13 target - see Question 1)

| Package | Pin | Why |
| --- | --- | --- |
| fastapi | 0.142.2 | API |
| uvicorn[standard] | 0.54.0 | ASGI server |
| pydantic | 2.13.5 | v2 required by spec |
| pydantic-settings | 2.15.0 | settings, fail-fast |
| sqlalchemy | 2.1.3 | 2.0-style ORM |
| alembic | 1.20.0 | migrations |
| aiosqlite | 0.22.1 | async SQLite default |
| psycopg[binary] | 3.3.6 | PostgreSQL in Docker |
| greenlet | 3.5.6 | SQLAlchemy async |
| langgraph | 1.2.12 | StateGraph, interrupts |
| langgraph-checkpoint-sqlite | 3.1.1 | default checkpointer |
| langgraph-checkpoint-postgres | 3.1.2 | Docker checkpointer |
| langchain | 1.4.3 | tools, chat model base |
| langchain-core | 1.6.6 | tool/message primitives |
| sqlglot | 30.21.0 | SQL guard by parsing |
| chromadb | 1.5.9 | vector store (local embeddings) |
| rank-bm25 | 0.2.2 | lexical half of hybrid search |
| numpy | 2.5.3 | hash embeddings, RRF, regression |
| httpx | 0.28.1 | all outbound HTTP |
| tenacity | 9.1.4 | retry on transient errors only |
| trafilatura | 2.3.0 | readable text extraction |
| ddgs | 9.16.0 | keyless web search |
| redis | 8.1.0 | Streams queue + Pub/Sub |
| sse-starlette | 3.5.0 | SSE run events |
| pyjwt | 2.15.1 | JWT auth |
| argon2-cffi | 25.1.0 | password hashing (no bcrypt 72-byte limit) |
| python-multipart | 0.0.32 | document upload |
| structlog | 26.1.0 | structured JSON logs + redaction |
| prometheus-client | 0.26.0 | /metrics |
| opentelemetry-sdk | 1.45.0 | optional exporter |

Dev: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0, hypothesis 6.168.3, ruff 0.16.10,
mypy 2.4.0, pip-tools 7.6.1, pre-commit 4.6.2, locust 2.46.6.

### Frontend (Node 20 - see Question 1)

| Package | Pin | Why |
| --- | --- | --- |
| react / react-dom | 19.3.0 | current stable |
| typescript | 5.9.3 | strict; TS 7 native port too fresh to pin |
| vite | 7.3.6 | Vite 8 only days old |
| @vitejs/plugin-react | 5.2.0 | matches Vite 7 |
| tailwindcss | 4.3.3 | CSS-first config, no postcss plumbing |
| react-router-dom | 7.18.4 | routing |
| @tanstack/react-query | 5.104.1 | server state |
| recharts | 3.10.1 | charts from SQL results |
| lucide-react | 0.577.0 | icons |
| vitest | 3.2.7 | matches Vite 7 |
| @testing-library/react | 16.3.3 | component tests |
| jsdom | 30.1.2 | test DOM |
| eslint | 9.39.5 | flat config; ESLint 10 too fresh |
| prettier | 3.9.9 | formatting |
| openapi-typescript | 7.13.0 | generated API types |
| @playwright/test | 1.63.0 | one skippable e2e smoke |

---

## Phase 1 - Scaffold, tooling, settings, DB, auth, seed

- [ ] `chore(repo)`: .gitignore, .editorconfig, .python-version, .nvmrc, LICENSE (MIT), CONTRIBUTING.md, SECURITY.md, CHANGELOG.md skeleton
- [ ] `chore(tooling)`: pyproject.toml (ruff, mypy strict, pytest, coverage config)
- [ ] `chore(deps)`: requirements.in / requirements-dev.in, compile to locked requirements.txt / requirements-dev.txt
- [ ] `chore(tooling)`: .pre-commit-config.yaml (ruff format, ruff check, mypy, eslint, prettier, gitleaks)
- [ ] `chore(tooling)`: tasks.ps1 with setup, dev, test, lint, typecheck, eval, gen-types, seed, docker-up
- [ ] `feat(settings)`: app/settings.py - providers, budgets, DB URLs, secrets; fail fast with actionable messages; .env.example
- [ ] `feat(domain)`: errors.py taxonomy + ports.py Protocols (no implementations yet)
- [ ] `feat(infra)`: db.py engines (app DB read-write, company DB read-only), SQLAlchemy ORM models for all 14 app tables
- [ ] `feat(infra)`: Alembic init + first migration, every index justified in a comment
- [ ] `feat(infra)`: company DB schema + its own migration/DDL script
- [ ] `feat(auth)`: argon2 hashing, JWT issue/verify, RBAC roles (admin/analyst/viewer), POST /api/v1/auth/{login,signup,demo}, GET /me
- [ ] `feat(api)`: create_app factory, ServiceContainer wiring, RFC 9457 handlers, request-id + security-header middleware, /health/live, /health/ready
- [ ] `feat(seed)`: scripts/seed_demo.py - idempotent; 2 years of Northwind Analytics data with the 3 planted stories; 12 documents incl. one poisoned; 3 demo users; synthetic run history
- [ ] `test(phase1)`: settings validation, auth + RBAC, health, seed idempotency (run twice, identical row counts)
- [ ] `docs(phase1)`: README skeleton, docs/backlog.md started

**Proves Phase 1**
```powershell
.\tasks.ps1 setup ; copy .env.example .env ; .\tasks.ps1 seed ; .\tasks.ps1 seed ; .\tasks.ps1 lint ; .\tasks.ps1 typecheck ; .\tasks.ps1 test
```
Expect: setup clean, second seed changes no row counts, lint/typecheck clean, Phase 1 tests green.

---

## Phase 2 - Tools with guardrails

- [ ] `feat(tools)`: base.py - timeout, tenacity retry on transient only, circuit breaker, structured ToolError results, latency logging
- [ ] `feat(domain)`: sql_guard.py - single statement, SELECT only, table/column allowlist, auto LIMIT injection
- [ ] `feat(tools)`: sql_query with statement timeout, typed rows + column types, schema description for the planner
- [ ] `feat(adapters)`: hash + chroma-local + openai embeddings; local falls back to hash with exactly one warning
- [ ] `feat(tools)`: knowledge_search - semantic + BM25 fused with RRF, returns cited passages with offsets
- [ ] `feat(adapters)`: ssrf_guard - resolve host, reject private/loopback/link-local/non-http(s); size cap; timeout
- [ ] `feat(tools)`: fetch_url via trafilatura
- [ ] `feat(adapters)`: search providers tavily / ddgs / fixtures behind SearchProviderPort
- [ ] `feat(tools)`: web_search (results marked untrusted)
- [ ] `feat(tools)`: exchange_rates (Frankfurter) + wikipedia_summary, fixtures fallback
- [ ] `feat(tools)`: calculator - AST-walking safe evaluator, stats + linear regression, no eval/exec
- [ ] `feat(tools)`: registry with per-run allowlist
- [ ] `test(tools)`: unit test per tool; hypothesis property tests for the SQL guard (rejects UPDATE/DELETE/DROP/multi-statement/non-allowlisted); SSRF table-driven tests; calculator rejects attribute access and imports
- [ ] `test(tools)`: contract test per adapter against recorded fixtures
- [ ] `chore(fixtures)`: tests/fixtures recorded responses for every external call

**Proves Phase 2**
```powershell
$env:TOOLS_MODE="fixtures" ; $env:EMBEDDING_PROVIDER="hash" ; .\tasks.ps1 test
python -m pytest tests/unit/tools tests/integration/tools --cov=app/tools --cov=app/domain --cov-fail-under=85
```

---

## Phase 3 - LangGraph agent (milestone v0.1.0)

- [ ] `feat(agent)`: state.py AgentState, prompts/*.md (versioned, with a version header)
- [ ] `feat(adapters)`: scripted_chat.py - deterministic tool-calling fake covering the 3 demo tasks and all tests
- [ ] `feat(adapters)`: openai_chat.py - one OpenAI-compatible client (OpenAI/Groq/Ollama)
- [ ] `feat(agent)`: clarify node + interrupt
- [ ] `feat(agent)`: plan node (3-8 steps, each naming tools + expected evidence)
- [ ] `feat(agent)`: approve_plan node - interrupt for approve / edit / cancel
- [ ] `feat(agent)`: execute_step ReAct loop, each tool result stored as an observation with source id S#
- [ ] `feat(agent)`: reflect node - continue / re-plan with reason / stop early
- [ ] `feat(agent)`: synthesize node - exec summary, findings, evidence, chart specs, limitations, next questions; every factual sentence cites [S#]
- [ ] `feat(agent)`: verify node - deterministic citation checks + LLM support check, rewrite/remove unsupported claims, verification score
- [ ] `feat(agent)`: finalize node - persist report, close run
- [ ] `feat(agent)`: budget-enforcing conditional edges -> synthesize with "stopped early: budget reached"
- [ ] `feat(agent)`: observation summarisation above the token threshold, raw data stays in the DB
- [ ] `feat(adapters)`: SqliteSaver + PostgresSaver behind CheckpointStorePort
- [ ] `test(agent)`: routing table tests, budget stop tests, interrupt + resume, citation verification, scripted determinism (same input -> same report), graph compiles and exports a diagram
- [ ] `chore(release)`: CHANGELOG + tag v0.1.0

**Proves Phase 3**
```powershell
.\tasks.ps1 test ; python -m scripts.export_graph ; python -m pytest tests/integration/agent -v
```

---

## Phase 4 - Worker, queue, durability, SSE, run APIs

- [ ] `feat(adapters)`: QueuePort - Redis Streams with consumer group; in-process fallback when Redis is absent
- [ ] `feat(services)`: ledger_service - idempotency key = hash(run, step, tool, args); replay recorded results
- [ ] `feat(worker)`: loop.py claim/execute/ack, bounded concurrency
- [ ] `feat(worker)`: heartbeat.py + reaper.py for stuck runs
- [ ] `feat(worker)`: shutdown.py - SIGINT/SIGTERM stop intake, checkpoint, exit 0 with a log line
- [ ] `feat(worker)`: startup resume of runs left `running`, emits a resumed-from-checkpoint event
- [ ] `feat(services)`: events_service - Redis Pub/Sub with in-process fallback, ordered event sequence numbers
- [ ] `feat(api)`: POST /api/v1/runs with Idempotency-Key, GET runs (cursor pagination), GET run, pause/resume/cancel, POST interrupt responses, GET /runs/{id}/events (SSE), reports + share link, Markdown export
- [ ] `test(worker)`: crash mid-run then restart - run completes, ledger shows zero duplicate tool calls
- [ ] `test(worker)`: graceful shutdown test; reaper test
- [ ] `test(api)`: SSE event order, idempotency replay, RBAC on every route, cursor pagination

**Proves Phase 4**
```powershell
.\tasks.ps1 test ; python -m pytest tests/integration/worker -v -k "crash or shutdown or ledger"
```

---

## Phase 5 - Injection defense, memory, evaluation, observability (milestone v0.2.0)

- [ ] `feat(security)`: untrusted.py delimiter wrapping + taint propagation; system prompt forbids following tool-result instructions
- [ ] `feat(security)`: block tool calls whose arguments are tainted unless user-enabled/approved; flag suspicious content in the run record
- [ ] `test(security)`: >= 8 attack scenarios (ignore-instructions, exfiltrate via fetch_url, SQL mutation via document text, tool-allowlist escape, fake citation, data-exfil query string, markdown-image beacon, role-switch)
- [ ] `feat(memory)`: per-user long-term findings with vector recall, cited as past findings
- [ ] `feat(memory)`: tool-result cache with TTL - Redis, in-memory fallback
- [ ] `feat(eval)`: >= 15 tasks with expected key facts, required tools, forbidden behaviours
- [ ] `feat(eval)`: metrics - task success, key-fact recall, citation precision, unsupported-claim rate, avg steps, cost, latency
- [ ] `feat(eval)`: scripts/evaluate.py - table to stdout, results to DB and docs/evaluation.md
- [ ] `feat(observability)`: trace per run, span per node and tool call; cost from a configurable price table
- [ ] `feat(observability)`: structlog JSON logs with run_id/request_id + secret redaction; /metrics; optional OTel exporter
- [ ] `test(phase5)`: memory recall, cache hit/miss, eval determinism, metrics endpoint shape, redaction
- [ ] `chore(release)`: CHANGELOG + tag v0.2.0

**Proves Phase 5**
```powershell
.\tasks.ps1 test ; .\tasks.ps1 eval ; python -m pytest tests/integration/security -v
```

---

## Phase 6 - Frontend foundation

- [ ] `chore(frontend)`: Vite + React + TS strict + Tailwind 4 + Router + TanStack Query, package-lock.json
- [ ] `feat(frontend)`: design system - tokens, dark/light, Button/Card/Badge/Table/Skeleton/Toast/EmptyState/Dialog
- [ ] `chore(frontend)`: openapi-typescript generation + gen-types task + CI staleness check
- [ ] `feat(frontend)`: typed API client, auth context, protected routes, redirect-after-login
- [ ] `feat(frontend)`: workspace shell - sidebar, user menu, theme toggle, mobile drawer
- [ ] `feat(frontend)`: landing page - animated real agent run in the hero, how it works, features, Built for trust, FAQ, footer, Try the demo
- [ ] `test(frontend)`: auth redirect, theme toggle, landing renders, design-system a11y basics

**Proves Phase 6**
```powershell
.\tasks.ps1 gen-types ; git diff --exit-code frontend/src/api/types.gen.ts ; .\tasks.ps1 typecheck ; .\tasks.ps1 test
```

---

## Phase 7 - New research, Run page, Report, Runs

- [ ] `feat(frontend)`: New research - question box, suggested demo questions, tool toggles, Quick/Standard/Deep presets, ask-before-web option
- [ ] `feat(frontend)`: Run page - live plan checklist, SSE timeline of tool cards (tables as tables, latency, retries, reasoning summary), budget meters, pause/resume/cancel, resumed-from-checkpoint banner, progressive report
- [ ] `feat(frontend)`: inline approval cards for plan approval, clarification, web-tool approval
- [ ] `feat(frontend)`: Report view - [S#] chips opening a source panel (SQL + rows, passage, or URL excerpt), charts from cited SQL only, verification badge, limitations, Markdown + PDF export, share link
- [ ] `feat(frontend)`: Runs history - search, filters, duration/cost/score columns, re-run, duplicate-and-edit
- [ ] `test(frontend)`: timeline ordering, approval card submits, citation chip opens correct source, chart renders from SQL rows, runs filtering

**Proves Phase 7**
```powershell
.\tasks.ps1 dev   # then: ask the EMEA demo question, approve the plan, watch the timeline, click a citation
.\tasks.ps1 test
```

---

## Phase 8 - Data sources, Insights, Evaluation, Settings (milestone v0.3.0)

- [ ] `feat(frontend)`: Data sources - schema browser with row counts and sample rows; KB upload/status/delete; tool health and live/fixtures mode
- [ ] `feat(api)`: insights aggregation endpoints (runs/day, outcomes, avg steps, p50/p95 duration, cost/day, tool usage and error rates, failure reasons, budget-exhausted rate)
- [ ] `feat(frontend)`: Insights (admin only) with real charts
- [ ] `feat(frontend)`: Evaluation page - suite results, injection scenarios, run history, trend charts
- [ ] `feat(frontend)`: Settings - profile, model info, budget defaults, admin user management
- [ ] `test(phase8)`: insights aggregation correctness, admin-only gating, upload flow
- [ ] `chore(release)`: CHANGELOG + tag v0.3.0

**Proves Phase 8**
```powershell
.\tasks.ps1 test ; .\tasks.ps1 dev   # Insights and Evaluation show charts from seeded history
```

---

## Phase 9 - Production, Docker, CI, docs, acceptance (milestone v1.0.0)

- [ ] `feat(api)`: serve built frontend with SPA fallback; /api/docs kept unlinked
- [ ] `build(docker)`: multi-stage Dockerfile, non-root, healthcheck; docker-compose.yml (api, worker, postgres, redis)
- [ ] `ci`: GitHub Actions jobs lint / typecheck / unit / integration / frontend / eval (threshold-gated) / audit / docker-build, cached; dependabot.yml; README badge
- [ ] `test(load)`: Locust scenario, real numbers into docs/performance.md
- [ ] `test(e2e)`: Playwright demo-flow smoke, auto-skipped if the browser cannot install
- [ ] `docs`: README (architecture Mermaid, exported graph, run lifecycle incl. crash, Windows quick start, Docker, feature tour, eval results, security model, design decisions, trade-offs, 10x/100x)
- [ ] `docs`: architecture.md (C4 + sequence diagrams), runbook.md, slo.md, threat-model.md, performance.md, evaluation.md, backlog.md, interview-guide.md
- [ ] `docs(adr)`: 6 ADRs - single vs multi-agent, checkpointing + idempotent ledger, separate worker + queue, interrupts for approval, read-only SQL by parsing, scripted model + fixtures
- [ ] `docs(postmortem)`: 001 blameless postmortem of a real bug met during the build
- [ ] `test(acceptance)`: clean-room run of all 16 acceptance checks, real numbers written into README and docs
- [ ] `chore(release)`: CHANGELOG + tag v1.0.0

**Proves Phase 9**
```powershell
git clone . ..\meridian-cleanroom ; cd ..\meridian-cleanroom
.\tasks.ps1 setup ; copy .env.example .env ; .\tasks.ps1 seed ; .\tasks.ps1 test ; .\tasks.ps1 lint ; .\tasks.ps1 typecheck ; pre-commit run --all-files ; .\tasks.ps1 gen-types ; git diff --exit-code ; .\tasks.ps1 eval ; .\tasks.ps1 dev
docker compose up --build
git log --oneline ; git tag
```

---

## Open questions

Tracked in the conversation; answers get folded into this plan before the phase that needs them.
See the questions raised with the Step 0 handoff (Python/Node versions, Docker availability, PDF export,
LLM key for check 13, visual direction, repo remote).
