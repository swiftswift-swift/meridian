# Interview brief

A short, honest script for talking about this repository. Read the three bug stories; they are
the strongest material here, because each one is a real defect found by a real mechanism, not a
feature description.

## Open with the honest framing

> "It's a partial build of an autonomous research agent. The backend foundation, the guardrails
> and the data layer are done and verified; the agent graph, the worker and the UI are specified
> but not built yet. Happy to go deep on anything that is built."

Saying this first is a strength, not a weakness. An interviewer who discovers an overstatement
themselves will discount everything else you say.

## The 60-second summary

A LangGraph agent plans a multi-step investigation, gets the plan approved by the user, executes
it by choosing tools (read-only SQL, hybrid document search, web, external APIs), and writes a
report where every claim is cited to a tool result. Runs are durable, so a worker crash resumes
from the last checkpoint without repeating tool calls.

What I built so far is the part that has to be right before any of that is safe: a SQL guard that
cannot be talked into a mutation, hard budgets, citation verification, an error taxonomy, the port
protocols that make the whole thing testable offline, and the seeded data with real stories in it.

## Three bug stories (the highest-value thing you can talk about)

### 1. A property test caught an unhandled exception on the untrusted path

The SQL guard catches parse failures. I wrote a hypothesis property test asserting that arbitrary
text produces a decision and never raises. It failed on a single backtick.

sqlglot raises `TokenError` for an unterminated quote, and `TokenError` is a **sibling** of
`ParseError`, not a subclass — both inherit `SqlglotError`. So malformed input escaped the guard
as an unhandled exception, which on the untrusted path is a denial of service at best.

Fix: catch `SqlglotError`, plus `RecursionError` for deeply nested parentheses.

**Why it matters:** I would not have found this by enumerating test cases, because I was wrong
about the exception hierarchy. The property test did not need me to be right.

### 2. A tolerance bug made citation verification accept anything

Citation checking matches the numbers in a sentence against the cited rows, allowing for rounding
and for a report writing "3.48M" where the query returned 3,480,000.

The rescale branch normalised the difference by the **original** magnitude rather than the
rescaled one. So for a claim of `$999` against a stored `3,480,000`, the comparison was
`|3480 - 999| / 3,480,000`, which is tiny, and the check passed. In effect any small number
matched any large number — the verification was decorative.

Found by a test asserting that a fabricated figure attached to a real source id gets rejected.

Second, smaller bug in the same area: a percentage emitted `7.1` **and** `0.071` as two separately
*required* values, when they are alternative forms of one written figure. Fixed by separating
claim values (any-of) from the evidence haystack (flat).

**Why it matters:** this is the difference between a verification score that means something and a
badge that always says 100%.

### 3. The demo data told the opposite story to the one intended

The headline demo is "why did EMEA revenue drop in Q3, and how do exchange rates explain it?" The
intended answer: USD revenue fell, local-currency revenue did not, so most of the decline is
currency plus one lost account.

The first generator produced USD amounts and **derived** local currency from them
(`local = usd / fx_rate`). With that causality, a falling euro cannot reduce USD revenue — it
mathematically *raises* local revenue. The seeded data showed local currency down 37% alongside
USD, which says demand collapsed. The demo would have taught the agent to reach the wrong
conclusion, and the planted "story" was not in the data at all.

Fix: local list prices are fixed at the year's reference rate and USD is the conversion at the
order-date spot rate — which is what the seeded pricing policy document already claimed. Now USD
fell 5.7% while local-currency revenue rose 2.2%.

Two supporting fixes: order volume went from 963 to about 4,500 so quarterly aggregates are driven
by the planted effects rather than sampling noise, and the growth curve was flattened because it
was outgrowing the churn it was supposed to reveal.

**Why it matters:** I only caught it because I queried the seeded data to check the story was
there instead of assuming the generator did what the docstring said. Verify outputs, not
intentions.

## Design decisions to have ready

**Why parse SQL instead of matching patterns?** A regex cannot tell a CTE named `delete_me`, the
literal `'DROP TABLE orders'`, or a column `update_ts` from a mutation. There are tests for all
three. Dispatching on `exp.Query` rather than hand-listing `Select | Union` also fixed refusing
`INTERSECT`/`EXCEPT`, which are read-only and valid. And it is layered: the company database is a
separate engine opened with `PRAGMA query_only`, because a parser is software too.

**Why Protocols instead of abstract base classes?** Adapters inherit nothing and the dependency
arrow points inward. Every port has a real implementation and a deterministic offline one, which
is why 95 tests run with no network and no API key.

**Why Argon2 and not bcrypt?** bcrypt silently truncates at 72 bytes, so a long passphrase is
weaker than the user believes.

**How do you avoid account enumeration?** Sign-in hashes a throwaway password when the email is
unknown, so a wrong password and a missing account are indistinguishable in both response body and
response time.

**Why cap four things and not just steps?** One step can call a tool fifty times, so a step cap
alone is not a cost control. A model missing from the price table is costed at a fallback rate
rather than zero, so an unpriced model cannot slip past the cost cap.

**How would prompt-injection defence work?** Tool results are untrusted data wrapped in
delimiters; the system prompt forbids following instructions inside them; and a tool call whose
arguments derive from untrusted content is blocked unless the user approved it. Ingest also
screens documents and flags them in the UI — detection for the operator, not the actual defence.
The seeded corpus contains a realistic injection attempt that trips eight signatures with no false
positives on the other eleven documents. **Be clear that the screening is built and the agent-side
enforcement is not yet.**

**What is the hardest part of durable execution?** Not the checkpoint — it is making a resumed run
not repeat side effects. The design is a tool-call ledger keyed by a hash of (run, step, tool,
canonical arguments) with a uniqueness constraint, so two workers racing on the same resumed run
cannot both record the same logical call. **Designed and in the schema; the worker is not built.**

## Commands to run live

```powershell
.\tasks.ps1 test        # 95 passed, offline
.\tasks.ps1 lint        # clean
.\tasks.ps1 typecheck   # mypy --strict, 56 files, clean
.\tasks.ps1 seed        # idempotent; run twice, same counts
git log --oneline       # small Conventional Commits with rationale in the bodies
```

Worth showing: `git log` bodies explain *why*, which is the habit interviewers are actually
checking for. Also `app/domain/sql_guard.py` and `tests/unit/test_sql_guard.py` side by side.

## If asked what you would do next

In order: the LangGraph agent with the scripted deterministic model (so tests stay offline), then
the worker and the tool ledger to prove crash recovery, then the run page with the live timeline.
The order is deliberate — each phase is provable by a command before the next one starts, and the
riskiest claim in the whole project (resume without duplicate tool calls) gets tested before any
UI is written.

## What not to claim

- There is no UI. Do not call it a SaaS website yet.
- The agent does not run. There is no LangGraph graph in the repo.
- No Docker, no CI, no evaluation numbers.
- Acceptance checks 5 to 16 in SPEC.md are unverified.
