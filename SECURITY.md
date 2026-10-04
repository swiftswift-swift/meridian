# Security policy

## Reporting a vulnerability

Open a private security advisory on the repository rather than a public issue. Include
reproduction steps and the commit you tested. Expect an acknowledgement within three working
days.

## Scope and threat model

The full analysis is in [docs/threat-model.md](docs/threat-model.md). The controls that matter
most in this codebase:

| Control | Where |
| --- | --- |
| SQL is read-only, enforced by parsing rather than string matching | `app/domain/sql_guard.py` |
| The SQL tool connects with a separate read-only engine to a separate database | `app/infra/db.py` |
| SSRF protection on every outbound fetch (private, loopback and link-local addresses blocked) | `app/adapters/http/ssrf_guard.py` |
| Tool results are treated as untrusted data and wrapped in delimiters | `app/tools/untrusted.py` |
| Tool calls with arguments derived from untrusted content require user approval | `app/tools/registry.py` |
| Hard per-run budgets on steps, tokens, cost and wall time | `app/domain/budgets.py` |
| Per-user rate limits | `app/api/middleware.py` |
| Citations are validated before a report is published | `app/domain/citations.py` |
| Passwords hashed with Argon2id; JWT access tokens | `app/services/auth_service.py` |
| Secrets redacted from structured logs | `app/infra/logging.py` |

## Known limitations

Recorded honestly in [docs/backlog.md](docs/backlog.md). The demo deployment ships seeded
demo accounts with known passwords and is not intended for untrusted multi-tenant use.
