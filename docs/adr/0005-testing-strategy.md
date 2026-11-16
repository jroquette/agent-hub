# 0005. Testing strategy

- Status: accepted
- Date: 2026-09-27
- Deciders: José Henrique Roquette

## Context and Problem Statement

agent-hub is built mostly by agents working test-first, in parallel worktrees, with a fast gate after every change. Tests
must be fast where they run often, must prove that fakes behave like the real adapters
([ADR 0002](0002-lean-hexagonal-architecture.md)), must never touch real transcripts or the network, and must stay easy
to find as the repo grows. Which test levels, layout and rules do we adopt, and how do we keep them from eroding?

## Considered Options

- **Pyramid with contract tests for ports**, the level given by the folder, rules enforced by a checker.
- **Unit + e2e only, without contract tests**: fakes are trusted to match the adapters.
- **Tests colocated with src** (`module.py` next to `test_module.py`).
- **Markers declared by hand** on each test or module.

The last three were considered during planning; no alternative was named when the decision was made.

## Decision Outcome

Chosen option: **pyramid with contract tests for ports**, because contract tests are what make in-memory fakes safe to
use in unit tests, and a folder-based level is the one a checker can verify.

- Levels: **unit** (core against in-memory fakes, no I/O), **contract** (one suite per port in
  `agent_hub.core.testing.contracts`, run against the fake in `agent_hub.core.testing.fakes` and against the real adapter),
  **integration** (real SQLite file under `tmp_path`, Alembic up and down), **e2e** (root `tests/e2e/`, subprocess of the
  installed `hub` and of the gate tools). Web later: Vitest and Playwright.
- Layout: `packages/<pkg>/tests/{unit,contract,integration}/`, unit tests mirroring src paths; root `tests/{unit,e2e}/`
  (root unit tests mirror `scripts/`). The level is the folder: `scripts/pytest_levels.py` applies the marker, and pytest
  runs with `strict = true`, so an unregistered marker fails collection.
- Unit and contract tests run with sockets blocked (pytest-socket).
- Names: `test_<behavior>_when_<condition>`. No ticket names (`test_pr_987.py`, `test_agh_12.py`), generic names
  (`test_misc`, `test_utils`, `test_new`, `test_temp`) or numbered names (`test_ingest_2`). A regression test goes in the
  affected module's test file, named after the behavior, with the issue id only in its docstring.
- `scripts/check_test_layout.py` enforces the layout and names in `make check-fast`.
- Fixtures are synthetic, built with `agent_hub.core.testing.builders`; never real transcripts.
- Hypothesis property tests for secret redaction and the transcript parser, when those exist.
- Coverage floors, lines plus branches: 90% for `core`, 80% for every other package (`scripts/check_coverage.py`).
- TDD is required: the failing test comes first. Assertions are never weakened to make a test pass.
- Python 3.14, whose stdlib has `uuid.uuid7` ([ADR 0004](0004-rest-api-standard.md)).

### Consequences

- Good: `make check-fast` runs only unit and contract tests, so it stays fast enough for every change.
- Good: a misplaced or badly named test fails the gate instead of waiting for review.
- Bad: every port needs a fake plus a contract suite before its first use case.
- Bad: the mirror rule forces a src module for every unit test file, and a src module name cannot end in `_<digits>`
  (`rfc9457.py`, not `rfc_9457.py`), because the test file name would read as a numbered name.

## More Information

- [TESTING.md](../TESTING.md): the full rules, commands and checker rule ids.
