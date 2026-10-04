You are a principal-level full-stack AI engineer. In the current EMPTY folder, build the production-quality web application described below, from nothing to fully working. A senior reviewer must conclude, within minutes of browsing the repo, that an experienced engineer built it.

# STEP 0: SET UP THE WORKSPACE BEFORE WRITING ANY CODE
1. Run `git init`.
2. Save this ENTIRE message verbatim as SPEC.md (it is the source of truth for every later session).
3. Create CLAUDE.md containing exactly the "STANDING RULES" section at the bottom of this message.
4. Write PLAN.md: break the phases in "BUILD PHASES" into small concrete tasks with checkboxes, list the folder structure and main libraries with pinned versions, and give the exact command that proves each phase works.
5. Ask me any questions where this spec is ambiguous. Then commit (`chore: add spec, plan and working agreements`) and STOP, waiting for my go-ahead.
After that I will ask you for one phase at a time. Never start a phase I haven't asked for.

# PRODUCT
"Meridian": an autonomous research and analysis agent for business analysts, delivered as a real SaaS-style website, NOT an API demo. No Swagger as the interface and no raw JSON visible to users. Developer docs live at /api/docs, unlinked from the main navigation.

A user asks a multi-step question, for example:
- "Why did EMEA revenue drop in Q3 compared to Q2, and how do exchange rates explain it?"
- "Which product line should we prioritise next quarter? Use our sales data and strategy memos."

A single LangGraph agent:
1. Plans the investigation as explicit steps.
2. Asks the user to approve or edit the plan.
3. Executes each step by choosing tools dynamically: internal SQL database, internal document knowledge base, web search, external APIs.
4. Re-plans when results change the picture.
5. Writes a structured report where every claim is cited to a tool result, with charts built from the actual query results.

Runs are durable: if the worker crashes or restarts, a run resumes from its last checkpoint without repeating completed tool calls.

# MY ENVIRONMENT (hard constraints)
- Windows 10/11, PowerShell, VS Code, Python 3.13, Node.js 20 LTS. Every command must work in PowerShell (use `;` not `&&`, `copy` not `cp`).
- My network blocks Amazon S3 and possibly other hosts. Every external dependency must degrade gracefully, and nothing may need a runtime model download.
- Embeddings are pluggable:
  - "local": ChromaDB ONNX MiniLM; if the download fails, log one warning and fall back to "hash".
  - "hash": offline feature hashing.
  - "openai": OpenAI-compatible API.
- LLM providers use one OpenAI-compatible interface (OPENAI_BASE_URL, OPENAI_API_KEY, model):
  - "openai": OpenAI, Groq or Ollama.
  - "scripted": a deterministic hand-written fake chat model with tool calls, covering the 3 built-in demo tasks and all tests. For any other question in scripted mode, the UI explains that a real model is needed and how to configure a free one (Groq or Ollama).
- External tools have an offline "fixtures" mode (recorded responses in tests/fixtures), used by tests and selectable in .env.
- Default local storage: SQLite (app DB + LangGraph SqliteSaver checkpoints) and an in-process queue fallback when Redis is not running. Docker Compose: PostgreSQL (app DB + LangGraph PostgresSaver) + Redis.

# TECH STACK
- Backend: Python, FastAPI, LangGraph (StateGraph, checkpointers, interrupts), LangChain (tools, chat models), Pydantic v2, pydantic-settings, SQLAlchemy 2.0 + Alembic, Redis (Streams for the job queue, Pub/Sub for live run events), ChromaDB, rank-bm25, sqlglot, httpx, tenacity, JWT auth (bcrypt or argon2), pytest + hypothesis.
- Worker: a separate process (`python -m app.worker`) executes runs from the queue. The API never runs agents inside request handlers.
- Frontend: React + TypeScript (strict) + Vite + Tailwind CSS + React Router + TanStack Query + Recharts + lucide-react. In production FastAPI serves the built frontend with SPA fallback.

# AGENT DESIGN (LangGraph)
State: question, plan (steps with status), observations (each with a unique source id S1, S2, …), messages, budget usage (steps, tokens, cost, wall time), report draft, errors.
Nodes:
1. clarify: if the question is ambiguous, interrupt and ask the user one clarifying question.
2. plan: produce 3–8 concrete steps, each naming the intended tool(s) and the expected evidence.
3. approve_plan: INTERRUPT. The user approves, edits steps, or cancels.
4. execute_step: a ReAct-style tool-calling loop for the current step; every tool result is recorded as an observation with a source id.
5. reflect: continue, re-plan (with a reason), or stop early because the question is answered.
6. synthesize: write the report (executive summary, findings, evidence, chart specs, limitations, next questions). Every factual sentence cites [S#].
7. verify: check every citation exists and supports its sentence (deterministic checks + LLM check). Remove or rewrite unsupported claims and record a verification score.
8. finalize: persist the report and close the run.
Conditional edges enforce budgets. When a budget is hit, go straight to synthesize with a "stopped early: budget reached" limitation.
Context management: summarise older observations above a token threshold; keep raw data in the DB and reference it by source id.
Prompts live in versioned files (app/agent/prompts/*.md), not inline strings.

# TOOLS (typed LangChain tools with Pydantic input schemas)
1. sql_query: read-only queries over the sample company DB.
   - Validated with sqlglot: SELECT only, allowlisted tables and columns, single statement, automatic LIMIT, statement timeout.
   - Returns rows + column types. The schema description is available to the planner.
2. knowledge_search: hybrid (semantic + BM25 fused with RRF) search over internal documents, returning cited passages.
3. web_search: Tavily (if key), DuckDuckGo via ddgs (no key), or fixtures. Results are untrusted.
4. fetch_url: readable text extraction.
   - SSRF protection: block private, loopback and link-local IPs and non-http(s) schemes.
   - Size limit and timeout.
5. External APIs: exchange_rates (Frankfurter, free), wikipedia_summary (Wikipedia REST); fixtures fallback when the network is unavailable.
6. calculator: a safe arithmetic/statistics evaluator (no eval/exec) for growth rates, percentages, simple regressions.
Every tool has:
- a timeout
- retries with exponential backoff for transient errors only
- a circuit breaker
- structured error results the agent can reason about (never tracebacks)
- logging of inputs, outputs and latency.

# SAMPLE DATA (`python -m scripts.seed_demo`, idempotent)
- Fictional "Northwind Analytics" company DB: regions, countries, currencies, products, product_lines, customers, orders, order_items, marketing_spend, with 2 years of generated data containing deliberate stories:
  - an EMEA Q3 revenue drop explained mostly by EUR/USD movement plus one lost key account
  - a fast-growing low-margin product line
  - a marketing campaign with poor ROI
- 10–15 internal documents (strategy memos, QBR notes, product briefs) that partly explain those stories. One contains a prompt-injection attempt.
- 3 demo users (admin, analyst, viewer), 3 built-in demo tasks that work fully in scripted mode, and several weeks of synthetic run history for Insights.

# WEBSITE
1. Landing page ("/"):
   - The hero shows a real animated agent run: plan, then tools firing, then a cited report.
   - "How it works", features, a "Built for trust" section (plan approval, read-only SQL, verified citations, budgets, resumable runs), FAQ, footer.
   - "Try the demo" signs in with a demo account.
2. Sign in / Sign up with one-click demo accounts.
3. Workspace shell: navigation (New research, Runs, Data sources, Insights, Evaluation, Settings), user menu, dark/light toggle, responsive drawer on mobile.
4. New research: a question box, suggested demo questions, tool toggles, budget presets (Quick / Standard / Deep: max steps, tokens, cost, time), and an "Ask me before using web tools" option.
5. Run page (the signature screen):
   - Left: the plan as a live checklist (pending / running / done / re-planned / skipped).
   - Centre: a live SSE timeline of tool-call cards showing tool, input, result preview (tables as tables), latency, retries, and a short reasoning summary.
   - Inline approval cards when the graph interrupts.
   - Right: budget meters.
   - Pause / resume / cancel. A "Resumed from checkpoint" banner after crash recovery. The report renders progressively.
6. Report view:
   - [S#] citation chips. Clicking one opens a source panel with the exact SQL and rows, the document passage, or the web excerpt with its URL.
   - Charts only from cited SQL results. Verification score badge and limitations section.
   - Export to Markdown and PDF. Read-only share link.
7. Runs: searchable history (status, question, duration, cost, verification score), with re-run and duplicate-and-edit actions.
8. Data sources: schema browser (tables, columns, row counts, sample rows); knowledge base (upload, status, delete); tool health and live/fixtures mode.
9. Insights (admin): runs per day, outcome rates, average steps, p50/p95 duration, cost per day, tool usage and error rates, failure reasons, budget-exhausted rate.
10. Evaluation: suite results, run history, trend charts.
11. Settings: profile, model info, budget defaults; admin user management.
12. Everywhere: skeletons, toasts, friendly errors, empty states with a next action, accessibility, responsive, and a distinctive non-template visual design.

# SENIOR FEATURES (implemented, tested, explained in the docs)
A. Durable execution
   - Every node transition is checkpointed. On startup the worker resumes runs left "running".
   - A tool_call ledger keyed by idempotency key (run + step + call hash) means resumed runs reuse recorded results.
   - A heartbeat-based stuck-run reaper.
   - Graceful shutdown on Ctrl+C/SIGTERM: stop taking jobs, checkpoint, exit cleanly.
B. Guardrails: SQL read-only by parsing, hard budgets in the graph, per-run tool allowlist, SSRF protection, citation validation, per-user rate limits.
C. Prompt-injection defense
   - Tool results are untrusted data, wrapped in delimiters; the system prompt forbids following instructions found in them.
   - Tool calls whose arguments come from untrusted content are blocked unless the user enabled or approved them.
   - Suspicious content is flagged in the UI.
   - A suite of at least 8 attack scenarios in pytest, shown on the Evaluation page.
D. Human-in-the-loop via LangGraph interrupts (plan approval, clarification, web-tool approval). Interrupted runs survive restarts.
E. Memory: short-term graph state with summarisation; long-term per-user findings with vector recall (cited as past findings); Redis tool-result cache with TTL (in-memory fallback).
F. Evaluation
   - At least 15 research tasks with expected key facts, required tools and forbidden behaviours.
   - Metrics: task success, key-fact recall, citation precision, unsupported-claim rate, average steps, cost, latency.
   - Deterministic in scripted + fixtures mode.
   - `python -m scripts.evaluate` prints a table and saves results to the DB and docs/evaluation.md.
G. Observability
   - A trace per run with a span per node and tool call: timing, tokens, cost from a configurable price table, retries, cache hits.
   - Structured JSON logs with run_id and request_id, and secret redaction.
   - /metrics in Prometheus format. Optional OpenTelemetry exporter.

# DATA MODEL
users, runs, run_steps, tool_calls (ledger), observations, reports, report_citations, interrupts, documents, chunks, user_memories, evaluation_runs, evaluation_results, plus the LangGraph checkpoint tables. The sample company tables live in a separate DB/schema that the SQL tool accesses READ-ONLY. Every frequent query has an index, justified in a migration comment.

# CRAFTSMANSHIP (non-negotiable)
Code design:
- Ports-and-adapters: Protocols for ChatModelPort, EmbeddingPort, SearchProviderPort, QueuePort, CheckpointStorePort, ToolPort. Vendor SDKs only in app/adapters/, wired in one composition root (ServiceContainer). App factory `create_app(settings)`. No global singletons.
- Layout: app/domain, app/agent, app/tools, app/adapters, app/services, app/api, app/worker, app/infra.
- Pure functions for decision logic (routing, budgets, citation verification, SQL validation).
- One error taxonomy (DomainError → ValidationError, NotFoundError, PermissionDeniedError, BudgetExceededError, ToolError, ExternalServiceError), returned as RFC 9457 problem+json.
- Typed everywhere, explicit readable names, files under ~400 lines, no dead or commented-out code, no print(), no bare except, no placeholder TODOs (every TODO links a docs/backlog.md item).
- Comments explain WHY, never WHAT. Fail fast on invalid settings, with actionable messages.
API:
- /api/v1, cursor pagination, consistent envelopes.
- An Idempotency-Key header on POST /runs.
- Frontend TypeScript types generated from OpenAPI (openapi-typescript); CI fails if they are stale.
- Separate /health/live and /health/ready. Security headers and locked-down CORS.
Tooling:
- uv or pip-tools lock file + package-lock.json. .python-version and .nvmrc.
- pre-commit: ruff format/check, mypy, eslint, prettier, gitleaks.
- `tasks.ps1` with tasks: setup, dev (API + worker + frontend together), test, lint, typecheck, eval, gen-types, seed, docker-up.
Tests:
- tests/unit, tests/integration, tests/e2e. Fully OFFLINE (scripted model, fixtures, hash embeddings).
- Cover: every tool, the SQL guard (property-based with hypothesis; rejects UPDATE/DELETE/DROP, multi-statements, non-allowlisted tables), SSRF, graph routing and budget stops, interrupts and resume, crash recovery without duplicate tool calls, citation verification, the injection suite, SSE event order, RBAC, idempotency.
- Contract tests for each tool adapter. Coverage ≥ 85% on app/domain, app/agent, app/tools.
- Frontend: Vitest + React Testing Library (timeline, approval cards, citation chips, auth redirects).
- One Playwright e2e smoke test of the demo flow, skipped automatically if the browser can't install.
- A Locust load test with results in docs/performance.md.
Delivery:
- Multi-stage Dockerfile (non-root, healthcheck); docker-compose.yml (api, worker, postgres, redis).
- GitHub Actions: separate lint, typecheck, unit, integration, frontend, eval (fails below thresholds), audit (pip-audit, npm audit) and docker-build jobs, with caching. Status badge in the README. dependabot.yml.
- .vscode/launch.json (API, worker, seed, tests), .editorconfig, LICENSE (MIT), CONTRIBUTING.md, SECURITY.md, CHANGELOG.md (Keep a Changelog, updated per phase), PR and issue templates.

# DOCUMENTATION
- README: plain, factual tone with no emoji, no marketing adjectives, and only real numbers. It covers:
  - what it is, with screenshot placeholders
  - architecture diagram (Mermaid) and the exported LangGraph diagram
  - run lifecycle, including the crash case
  - Windows quick start using tasks.ps1, and Docker
  - feature tour, evaluation results, security model
  - "Design decisions", "Known trade-offs", "What I would change at 10× and 100× scale"
- docs/architecture.md: C4-style context and container diagrams, plus sequence diagrams for start run, interrupt and approve, crash and resume.
- docs/adr/: at least 6 ADRs (context, decision, alternatives, consequences):
  - single agent vs multi-agent
  - checkpointing + idempotent tool ledger
  - separate worker + queue
  - human approval via interrupts
  - read-only SQL via parsing
  - scripted model + fixtures for deterministic tests
- docs/runbook.md: metrics, suggested alerts, and handling for stuck runs, Redis down, LLM rate-limited, checkpoint growth, rollback.
- docs/slo.md: 3 SLOs with measurement queries:
  - 99% of runs reach a terminal state
  - p95 time-to-first-event under 2 s
  - tool error rate under 2%
- docs/threat-model.md: a STRIDE-lite table with mitigation + test per threat.
- docs/postmortems/001-*.md: a blameless postmortem of a real bug met during the build.
- docs/backlog.md (honest gaps), docs/evaluation.md, docs/performance.md.
- docs/interview-guide.md: 15 likely interview questions with answers grounded in this codebase, plus the 3 hardest bugs or edge cases met and how they were solved.

# BUILD PHASES
Phase 1: scaffold, tooling (pre-commit, tasks.ps1, lock files), settings, DB models + Alembic, auth, health, seed of company DB and documents.
Phase 2: tools with guardrails and adapters, plus tests (fixtures mode).
Phase 3: LangGraph agent (all nodes, budgets, interrupts, checkpointer) with the scripted model, plus graph tests.
Phase 4: worker + queue (Redis with in-process fallback), tool ledger, crash recovery, graceful shutdown, reaper, SSE run events, run/report APIs.
Phase 5: injection defense, memory, evaluation suite, observability, plus their tests.
Phase 6: frontend foundation: design system, generated API types, shell, auth, landing page.
Phase 7: New research, Run page (live timeline + approvals), Report view, Runs.
Phase 8: Data sources, Insights, Evaluation, Settings.
Phase 9: production build served by FastAPI, Docker, CI, load test, all docs, then a full clean-room run of the acceptance checks with real numbers written into README and docs.
Tag milestones: v0.1.0 after Phase 3, v0.2.0 after Phase 5, v0.3.0 after Phase 8, v1.0.0 after Phase 9.

# ACCEPTANCE CHECKS (all must pass on my machine)
1. .\tasks.ps1 setup → venv, Python deps, frontend deps, pre-commit installed without errors
2. copy .env.example .env ; .\tasks.ps1 seed
3. .\tasks.ps1 test → all backend and frontend tests green, with no network and no API key; coverage ≥ 85% on core packages
4. .\tasks.ps1 lint ; .\tasks.ps1 typecheck ; pre-commit run --all-files → clean; .\tasks.ps1 gen-types → no diff
5. .\tasks.ps1 dev → http://localhost:8000 shows the landing page; "Try the demo" opens the workspace
6. Scripted demo "Why did EMEA revenue drop in Q3?" → plan approval card; after approving, the timeline streams SQL, knowledge-search and exchange-rate calls; the report cites [S#], includes a chart from SQL results, and shows a verification score
7. Clicking a citation shows the exact SQL and rows (or passage, or URL excerpt)
8. Close the worker mid-run, restart it → "Resumed from checkpoint", the run completes, the ledger shows no duplicate tool calls. Ctrl+C on the worker logs a graceful shutdown with a checkpoint.
9. "Delete the orders table" → the SQL guard refuses and the report explains why
10. The poisoned-document demo → injected instructions ignored and flagged in the UI
11. A tiny cost cap → the run stops early with a "budget reached" limitation
12. Insights and Evaluation show real charts; .\tasks.ps1 eval prints the metrics table
13. With a free Groq key (LLM_PROVIDER=openai), a custom question runs end to end
14. docker compose up --build → api, worker, postgres, redis healthy and the site works at http://localhost:8000
15. git log --oneline shows small Conventional Commits and tags v0.1.0 … v1.0.0
16. docs/ contains architecture, runbook, slo, threat-model, performance (real numbers), evaluation (real numbers), at least one postmortem, at least 6 ADRs, and the interview guide

When everything passes, give me: the final folder tree, the exact PowerShell commands to run it, the evaluation results table, and a 10-line summary of the design decisions I should be ready to explain in an interview.

# STANDING RULES (copy into CLAUDE.md)
- Source of truth: SPEC.md. Progress: PLAN.md. Work only on the phase I ask for.
- Windows + PowerShell commands only. Python 3.13 in .venv; Node 20 in frontend/.
- My network blocks Amazon S3 and maybe other hosts: no runtime model downloads. Tests run offline with LLM_PROVIDER=scripted, TOOLS_MODE=fixtures, EMBEDDING_PROVIDER=hash.
- Commit as you go: small Conventional Commits (feat/fix/test/refactor/docs/chore/ci with a scope), one logical change each, tests passing at every commit, bodies explaining WHY when not obvious. Never one giant commit per phase.
- After every change run the relevant tests and fix failures. Show real command output as evidence; never claim something works without running it.
- At the end of each phase: tick PLAN.md, update CHANGELOG.md, tag if it is a milestone, then stop and summarise what was built and how to see it.
- Code style: comments explain why, not what; no emoji, print(), commented-out code, placeholder TODOs or unused code; vendor SDKs only in app/adapters/; files under ~400 lines.
