# Backlog

Known gaps, recorded rather than hidden. Each entry says what is wrong, why it was left, and
what fixing it would involve.

## Not built

- **The LangGraph agent.** The research pipeline is a single pass: plan, query, write, verify.
  The specification describes a graph with re-planning, interrupts and a checkpointer. The
  guardrails that make the current pipeline safe are real; the orchestration is simpler.
- **The worker and queue.** `app/services/run_service.py` writes runs synchronously inside the
  request. The `tool_calls` ledger table and its uniqueness constraint exist for the idempotent
  replay the worker will need, but nothing populates them yet.
- **Crash recovery.** Follows from the worker. Nothing resumes an interrupted run.
- **Live streaming.** The run page shows a staged animation while the request is in flight
  rather than server-sent events from a worker.
- **Plan approval for free-form questions.** The approval step exists for the three built-in
  demo questions only.

## Known limitations of what is built

- **The lock file targets Python 3.14 only.** pip-tools resolves against the running
  interpreter, and this was compiled on 3.14, so `pip install -r requirements-dev.txt` fails on
  3.13. Fixing it means compiling the lock on the lowest supported version, which needs 3.13
  installed. `requires-python` has been narrowed to match reality rather than claim support
  that is not tested.
- **Chunk embeddings are JSON arrays scored in Python.** Fine at twelve documents, wrong above
  roughly ten thousand chunks, where a real vector index is needed.
- **Hash embeddings capture lexical overlap, not meaning.** "Revenue fell" and "income
  declined" are far apart. Hybrid search with BM25 compensates; a sentence encoder would be
  better but needs a model download the target network cannot rely on.
- **The in-process queue, cache and rate limiter are per-process.** Several API workers each
  get their own counters, so the effective rate limit multiplies. Redis is wired and fixes it.
- **JWTs are stateless.** A token stays valid until it expires; there is no revocation list.
- **The fixed-window rate limiter admits up to twice the limit across a boundary.** It exists
  to stop runaway clients, not to meter a paid quota.
- **Numeric citation checking compares magnitudes.** It cannot catch a reversed direction:
  "revenue grew 7.1%" passes against a stored `-7.1`. The model review step is meant to cover
  this and is not yet wired in.
- **Column renaming is heuristic.** `app/assets/format.js` derives friendly names from column
  names because the model invents its own aliases. An alias it has never seen falls back to a
  title-cased version of the raw name.
- **The Docker image has never been built locally.** Docker is not installed on the development
  machine; the CI `docker` job is where that claim is tested.

## Deliberate trade-offs

- **PDF export goes through the browser's print dialog.** A server-side renderer needs native
  libraries that are awkward on Windows; a canvas-based one turns selectable text into an
  image. Print keeps the text searchable and costs nothing.
- **No bundler for the frontend.** ES modules are served directly. The React and Vite phase in
  PLAN.md would replace the presentation layer without changing the API contract.
- **chromadb was removed.** It was never imported, pulled in 27 transitive packages and carried
  five unfixed advisories. Reinstating the "local" ONNX embedding provider means adding it back
  deliberately.
