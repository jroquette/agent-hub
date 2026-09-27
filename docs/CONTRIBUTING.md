# Contributing

How work flows from an issue to `main`. The git and history rules are [ADR 0007](adr/0007-git-and-change-flow.md); the
tracker process below is team process and lives only here. Code rules are in [CONVENTIONS.md](CONVENTIONS.md), test rules
in [TESTING.md](TESTING.md).

## Task workflow

1. **Issue.** Every change starts from a Linear issue in team AGH that meets the Definition of Ready. Move it to
   In Progress when work starts.
2. **Spec first.** A change of scope or architecture updates [SPEC.md](SPEC.md) (and an ADR, if it is a decision) in the
   same PR.
3. **Branch** from a freshly fetched `origin/main`: `roquettejh/agh-<n>-<desc>`, where `<n>` is the issue number and
   `<desc>` a short kebab-case description, e.g. `roquettejh/agh-2-foundation`. Never `claude/…`; never commit on `main`.
4. **Set up** with `uv sync --all-packages` (uv 0.9.0 or newer; Python 3.14).
5. **Test first** ([TESTING.md](TESTING.md)), then implement. Run `make check-fast` while working.
6. **Before the PR**, run `make check`. Redirect the output and check the exit code:
   `make check > check.log 2>&1; echo $?`.
7. **PR** against `main`, with a Conventional Commit title and the body from `.github/pull_request_template.md` (tracker
   issue, summary, ACs covered, the Definition of Done checklist). Move the issue to In Review.
8. **Review and merge.** The owner reviews and squash-merges. Fixes after review are new commits; no force-push. The issue
   moves to Done.

## Authorship

Commits and PRs are authored by the owner, José Henrique Roquette (`roquettejh@gmail.com`). No AI co-author trailer, no
"Generated with" line, no robot emoji and no mention of an agent in commits, PRs, comments or branch names. No push to
`main`, no force-push, no production deploys: everything lands through a PR the owner merges.

## Commits and PR titles

PR titles follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject`. Squash merge makes
the PR title the commit on `main`, so the title is what the history and the future changelogs read.

- **Types:** `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `ci`, `build`, `perf`, `revert`.
- **Scopes:** `core`, `storage`, `collector`, `cli`, `api`, `web`, `repo`, `deps`, `ci`, `docs`.
- The scope is required. `!` before the colon marks a breaking change: `fix(cli)!: rename flag`.
- The whole title is at most 72 characters, has no trailing period and no trailing whitespace.
- Examples: `feat(collector): ingest hook events`, `chore(repo): foundation workspace, gates, ADRs and English docs`.

CI checks the title with `scripts/check_pr_title.py` (stdlib only), which holds the same lists. Check a title locally
with `uv run --locked --all-packages python scripts/check_pr_title.py "<title>"` (any Python 3.10+ runs it); it exits 1
and prints the allowed types and scopes when the title is invalid. Commits inside a branch should use the same format,
but only the PR title is enforced.

Per-package changelogs and semantic versions will be generated from this history; the release tool comes in a
follow-up chore.

## Project management (Linear)

- **Team:** AGH. **Projects:** one per SPEC phase, with the phase gate as the project's final milestone.
- **Cycles:** 2 weeks.
- **States:** Backlog → Todo → In Progress → In Review (PR open and `check` green) → Done, plus Canceled.
- **Labels:**
  - type, exactly one per issue: `feature`, `bug`, `chore`, `spike`, `docs`;
  - area: `pkg:core`, `pkg:storage`, `pkg:collector`, `pkg:cli`, `pkg:api`, `app:web`;
  - automation: `agent-ready` (an agent may pick it up), `agent-failed` (an agent run failed; the issue has the diagnosis).
- **Size:** `spike`, `bounded` or `architectural`. No story points; cycle time is tracked instead.

### Issue template

```markdown
## Context
Why this is needed and what exists today.

## Acceptance criteria
- **AC-1** Given <state>, when <action>, then <observable result>.
- **AC-2** …

## Out of scope
What this issue does not do.

## Notes
Links, constraints, open questions.
```

### Definition of Ready

An issue can be labeled `agent-ready` (or picked up) when:

- its acceptance criteria are testable, written as Given/When/Then with AC ids;
- the affected packages are tagged with area labels;
- its dependencies are linked (blocked-by / related issues).

### Definition of Done

- check green in CI;
- every AC has a test;
- docs/ADR/SPEC updated if scope changed;
- PR reviewed and merged by the owner;
- issue Done.

The same checklist is in the PR template.

## Architecture Decision Records

- Location and name: `docs/adr/NNNN-kebab-title.md`, numbered in sequence (`0009-…` is next).
- Format: [MADR](https://adr.github.io/madr/): a header with `Status`, `Date` and `Deciders`, then the sections Context
  and Problem Statement, Considered Options, Decision Outcome (with Consequences) and More Information. Follow
  [ADR 0001](adr/0001-uv-workspace-with-namespace-packages.md) as the model.
- Statuses: `proposed` (under review in a PR), `accepted` (merged), `superseded by NNNN`.
- An accepted ADR is never edited. A changed decision is a new ADR that supersedes the old one; the only change to the
  old file is its status line, `Status: superseded by NNNN`, in the same PR.
- Write an ADR for decisions that are hard to reverse or shape the tooling and history (structure, persistence, API
  style, testing, conventions, git flow). Team process stays in this file.
- ADR files are guarded: the hub asks before ADR edits, including a new ADR, so every change to `docs/adr/` gets an
  explicit confirmation.

## Database migrations

Alembic is configured in `packages/storage/alembic.ini`, with the scripts in `packages/storage/alembic/` and the
revisions in `packages/storage/alembic/versions/`. Tables are declared only in `agent_hub.storage.db.metadata`.

1. Change `metadata` in `packages/storage/src/agent_hub/storage/db.py`.
2. Create the next revision (numbered ids, like the baseline `0001`), from the repo root:

   ```bash
   uv run --locked --all-packages alembic -c packages/storage/alembic.ini revision -m "<message>" --rev-id <NNNN>
   ```

   To autogenerate it against a scratch database, first upgrade one to head, then pass the same URL:

   ```bash
   db="$(mktemp -d)/scratch.db"
   uv run --locked --all-packages alembic -c packages/storage/alembic.ini -x db_url="sqlite:///$db" upgrade head
   uv run --locked --all-packages alembic -c packages/storage/alembic.ini -x db_url="sqlite:///$db" \
     revision --autogenerate -m "<message>" --rev-id <NNNN>
   ```

3. Review the generated file; migrations run in batch mode on SQLite. The file is formatted by ruff on creation.
4. `make migrations` (in `make check`) upgrades a scratch database to head and runs `alembic check`, so a `metadata`
   change without a migration fails. The integration test also downgrades to base.

A merged revision is never edited; fix it with a new revision. The hub asks before edits in `alembic/versions/` too.
Never point Alembic at the real database (`~/.local/share/agent-hub/agent-hub.db`) from a test or a gate.

## Manual repository and Linear settings

These live outside the repo and are set by the owner:

1. **GitHub `main` protection:** pull request required; required status checks = the CI `check` job and the `pr-title`
   job; linear history; squash merge only (merge commits and rebase merge disabled); default squash commit message =
   the PR title. `.github/CODEOWNERS` is informational: code-owner review is not required.
2. **Linear:** team AGH states, labels (type, area, automation), one project per SPEC phase with the phase gate as the
   final milestone, 2-week cycles, and the issue template above.
