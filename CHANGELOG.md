# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project specification, build plan and working agreements.
- Repository tooling: pinned and locked dependencies, ruff, mypy strict, pre-commit config,
  `tasks.ps1` task runner for PowerShell.
- Settings with fail-fast validation, including a minimum JWT secret length and a refusal to
  accept blank credentials as configured ones.
- Domain layer: error taxonomy, entities, port protocols, read-only SQL guard, budget arithmetic,
  citation verification, RBAC rules.
- Persistence: 14-table application schema with justified indexes, and a separate read-only
  company database.
- API: application factory, Argon2 and JWT authentication, RBAC, RFC 9457 problem responses,
  security headers, request correlation ids, liveness and readiness probes.
- Adapters: offline hash embeddings, Redis and in-process cache and rate limiter.
- Sample data: two years of generated company data containing three deliberate analytical
  stories, and twelve internal documents of which one carries a prompt-injection attempt.
- Test suite of 95 offline tests, including hypothesis property tests for the SQL guard.

### Fixed

- SQL guard: malformed input raising `TokenError` escaped as an unhandled exception, because
  `TokenError` is a sibling of `ParseError` rather than a subclass. Found by a property test.
- SQL guard: `INTERSECT` and `EXCEPT` were refused as "not a SELECT" despite being read-only.
- Citation verification: the thousands and millions rescale normalised by the original magnitude,
  so any small number matched any large one.
- Citation verification: a percentage was treated as two separately required values rather than
  two alternative forms of one figure.
- Seed data: the generator derived local currency from USD, which made the planted exchange-rate
  story impossible to find and reversed its meaning.

### Not yet implemented

The LangGraph agent, the worker and queue, SSE run events, the evaluation suite, observability,
the frontend, Docker and CI. Tracked in PLAN.md.
