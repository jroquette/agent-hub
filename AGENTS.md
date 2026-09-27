# AGENTS.md — agent-hub

A platform to create, run and observe AI agent hubs for N projects.
The spec is in `docs/SPEC.md`: read it before any task. The directions already set are in its "Defined directions" section.

## Stack

- **Python 3.14** (`.python-version`; `requires-python = ">=3.14"`), managed with **uv** (0.9.0 or newer).
- A **uv workspace** with one package per component under `packages/`, all in the implicit namespace `agent_hub`:

  | Package (distribution) | Module root | What it holds |
  | --- | --- | --- |
  | `packages/core` (`agent-hub-core`) | `agent_hub.core` | Entities, use cases, ports, test fakes/builders/contracts |
  | `packages/storage` (`agent-hub-storage`) | `agent_hub.storage` | SQLAlchemy Core + Alembic adapter |
  | `packages/collector` (`agent-hub-collector`) | `agent_hub.collector` | Event collector adapter |
  | `packages/cli` (`agent-hub-cli`) | `agent_hub.cli` | Typer CLI, command `hub` |
  | `packages/agent-hub` (`agent-hub`) | `agent_hub_meta` (placeholder, no code) | Meta-package: `uv tool install` gets everything |

- Everything depends on `core`; `core` depends on nothing internal; siblings never import each other (import-linter).
- `packages/api` (FastAPI) and `apps/web` (React) come in Phase 2.

## Gates

Set up once per clone or worktree with `uv sync --all-packages` (the `make` targets also sync on their own).

- `make check-fast`: while working (format, lint, mypy --strict, test layout, unit and contract tests).
- `make check`: before a PR, and what CI runs (`check-fast` + integration, e2e, import contracts, migrations, coverage floors).

Redirect the output to a file and check the exit code: `make check > check.log 2>&1; echo $?`. Never run them with `-j`.

## Where things are

- `docs/ARCHITECTURE.md`: packages, dependency rule, hexagonal layout, where each kind of code goes.
- `docs/CONVENTIONS.md`: code rules and which tool enforces each one; glossary.
- `docs/TESTING.md`: test levels, layout, naming, fixtures, coverage floors.
- `docs/API.md`: REST API standard (implemented in Phase 2).
- `docs/CONTRIBUTING.md`: task workflow, branches, commits, PRs, Definition of Ready and Done, ADR process.
- `docs/adr/`: architecture decision records. Accepted ADRs are never edited; a new ADR supersedes them.

## Rules

1. **Authorship belongs to the user.** Commits and PRs are by José Henrique Roquette (`roquettejh@gmail.com`).
   Never add an AI `Co-Authored-By`, "Generated with", 🤖 or any sign that the work was done by an agent,
   in a commit, PR, comment or branch name.
2. **Branches:** `roquettejh/agh-<n>-<desc>` (`<n>` = the tracker issue number), never `claude/…`. No push to `main` and
   no force-push: every change lands through a PR.
3. **Spec first.** A change of scope or architecture updates `docs/SPEC.md` in the same PR.
4. **No secrets in the repo.** No tokens, keys or real transcripts in code, tests or fixtures.
5. **Private repo.** The internal workings (brain, workflows, rules) are not shared outside the repo.

## Gotchas

- `cmd | tail` hides the exit code. Redirect to a file and check `$?` before saying the suite passed.
- uv older than 0.9.0 may only offer a Python 3.14 release candidate, and an already-installed 3.14 rc can satisfy
  `.python-version = 3.14`. Run `uv self update` and `uv python install 3.14`, and check that `uv python find 3.14` points to
  a final build (no `rc`).
