# STANDING RULES

- Source of truth: SPEC.md. Progress: PLAN.md. Work only on the phase I ask for.
- Windows + PowerShell commands only. Python 3.13 in .venv; Node 20 in frontend/.
- My network blocks Amazon S3 and maybe other hosts: no runtime model downloads. Tests run offline with LLM_PROVIDER=scripted, TOOLS_MODE=fixtures, EMBEDDING_PROVIDER=hash.
- Commit as you go: small Conventional Commits (feat/fix/test/refactor/docs/chore/ci with a scope), one logical change each, tests passing at every commit, bodies explaining WHY when not obvious. Never one giant commit per phase.
- After every change run the relevant tests and fix failures. Show real command output as evidence; never claim something works without running it.
- At the end of each phase: tick PLAN.md, update CHANGELOG.md, tag if it is a milestone, then stop and summarise what was built and how to see it.
- Code style: comments explain why, not what; no emoji, print(), commented-out code, placeholder TODOs or unused code; vendor SDKs only in app/adapters/; files under ~400 lines.
