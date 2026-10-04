# Contributing

## Prerequisites

- Windows 10/11 with PowerShell
- Python 3.13 or 3.14 on PATH
- Node.js 20 or newer

## Setup

```powershell
.\tasks.ps1 setup
copy .env.example .env
.\tasks.ps1 seed
```

## Before opening a pull request

```powershell
.\tasks.ps1 lint
.\tasks.ps1 typecheck
.\tasks.ps1 test
.\tasks.ps1 gen-types   # must leave no diff
```

`pre-commit install` runs as part of `tasks.ps1 setup`, so ruff, mypy, eslint, prettier and
gitleaks run on every commit. Run `pre-commit run --all-files` to check the whole tree.

## Commit messages

Conventional Commits with a scope, one logical change per commit:

```
feat(tools): add read-only SQL guard backed by sqlglot

Parsing beats regex matching here because a regex cannot tell a CTE named
"delete_me" from a DELETE statement.
```

Types in use: `feat`, `fix`, `test`, `refactor`, `docs`, `chore`, `ci`, `build`, `perf`.

## Code conventions

- Comments explain why, not what.
- Files stay under roughly 400 lines.
- Vendor SDKs are imported only inside `app/adapters/`.
- Decision logic (routing, budgets, citation checks, SQL validation) lives in pure functions
  under `app/domain/` so it can be tested without any I/O.
- No `print()`, no bare `except`, no commented-out code. A `TODO` must link an entry in
  `docs/backlog.md`.
- Every new endpoint needs an RBAC test.

## Tests

Tests run fully offline. The suite forces `LLM_PROVIDER=scripted`, `TOOLS_MODE=fixtures` and
`EMBEDDING_PROVIDER=hash`, so no network access or API key is required. Any test that would
reach the network must use a recorded fixture in `tests/fixtures/`.
