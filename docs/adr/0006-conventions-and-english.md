# 0006. Conventions and English

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

Most of the code will be written by agents, reviewed by one owner. Style rules that live only in prose drift, and review
time goes to naming and structure instead of behavior. The first spec and agent guide were written in Portuguese, while
the code, the tools and the agents work in English. Which code conventions do we adopt, how are they enforced, and which
language does the project use?

## Considered Options

- **Written conventions, enforced by tools wherever a tool can check them**, the rest marked review-only.
- **Review-only conventions**: a style guide, checked by the reviewer.
- **Portuguese docs** with English code.

The last two were considered during planning; no alternative was named when the decision was made.

## Decision Outcome

Chosen option: **written conventions, enforced by tools where possible, and English everywhere**.

- [CONVENTIONS.md](../CONVENTIONS.md) lists every rule (Clean Code: names, functions, types, errors, comments, logs) and
  marks each one "enforced by <tool/rule>" or "review-only".
- Enforcement is in the gates: ruff (`C901` with max complexity 8, `PLR0917` with at most 3 positional params, `FBT`,
  `BLE001` and `S110`, `ERA001`, `N`), mypy strict, and the layout checker (`forbidden-module` and the test name rules).
- `tests/e2e/test_quality_gates.py` runs ruff and mypy with the repo's configs against scratch modules that break each
  rule, so a config change that switches a rule off fails `make check`.
- One term per concept, matching the SPEC glossary. A workflow execution is a `WorkflowRun`, which contains Sessions;
  "run", "job" and "execution" are never synonyms for Session.
- English everywhere: code, docs, ADRs, commits, PRs and issues.

### Consequences

- Good: review focuses on behavior; a convention a tool checks cannot erode silently.
- Good: the docs are readable by any agent or contributor without translation.
- Bad: some rules stay review-only (names that reveal intent, one level of abstraction per function), so review still
  carries them.
- Bad: tool rules are strict (complexity 8, three positional params) and occasionally force a refactor where a human
  would accept the code.

## More Information

- [CONVENTIONS.md](../CONVENTIONS.md): the rules and how each one is enforced.
