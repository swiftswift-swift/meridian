## What this changes

<!-- One or two sentences. The why belongs in the commit message. -->

## How it was verified

<!-- Paste the real output. "Tests pass" without the run is not evidence. -->

```
.\tasks.ps1 test
.\tasks.ps1 lint
.\tasks.ps1 typecheck
```

## Checklist

- [ ] Tests cover the new behaviour, including the failure case
- [ ] Comments explain why, not what
- [ ] No new `TODO` without a matching entry in `docs/backlog.md`
- [ ] Any guardrail change has a scenario in `app/services/evaluation_service.py`
- [ ] README and `PLAN.md` still describe what the code actually does
