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
4. **Set up** with `uv sync --all-packages` (uv 0.9.0 or newer; Python 3.14) and, for the web app,
   `npm --prefix apps/web ci` (Node from `apps/web/.node-version`, `engines.node` in `apps/web/package.json`; npm
   installs exactly what `package-lock.json` pins). The `make` targets sync both on their own. The web smoke needs a
   Playwright Chromium (`npm --prefix apps/web exec playwright install chromium` once on a new machine); without one it
   skips locally and fails under `CI`. A change under `apps/web/src` ends with `make web-build`, and the rebuilt
   `packages/api/src/agent_hub/api/web_dist/` is committed with it (`make web-dist-check` fails otherwise).
5. **Test first** ([TESTING.md](TESTING.md)), then implement. Run `make check-fast` while working.
6. **Before the PR**, run `make check`. Redirect the output and check the exit code:
   `make check > check.log 2>&1; echo $?`.
7. **PR** against `main`, with a Conventional Commit title (check it first with `make pr-title TITLE="<title>"`) and the body from `.github/pull_request_template.md` (tracker
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
- **Scopes:** `core`, `storage`, `collector`, `cli`, `generator`, `tracker`, `hub-git`, `claude-sessions`, `api`,
  `mcp-server`, `web`, `repo`, `deps`, `ci`, `docs`.
- The scope is required. `!` before the colon marks a breaking change: `fix(cli)!: rename flag`.
- The whole title is at most 72 characters, has no trailing period and no trailing whitespace.
- Examples: `feat(collector): ingest hook events`, `chore(repo): foundation workspace, gates, ADRs and English docs`.

`scripts/check_pr_title.py` (stdlib only) holds the same lists. Check the title before opening the PR, and again after
renaming it: `make pr-title TITLE="<title>"` (or `python3 scripts/check_pr_title.py "<title>"`, any Python 3.10+); it
exits 1 and prints the allowed types and scopes when the title is invalid. CI does not check titles ([ADR 0045](adr/0045-pr-titles-checked-before-the-pr-not-in-ci.md)): the owner,
who squash-merges, reads the title last. Commits inside a branch should use the same format,
but only the PR title is enforced.

Releases are cut with the hub's `/release` skill (§ Releases), which proposes the version bump from the PR titles
merged since the last tag. Changelogs are not generated yet.

## Project management (Linear)

- **Team:** AGH. **Projects:** one per SPEC phase, with the phase gate as the project's final milestone.
- **Cycles:** 2 weeks.
- **States:** Backlog → Todo → In Progress → In Review (PR open and `check` green) → Done, plus Canceled.
- **Labels:**
  - type, exactly one per issue: `feature`, `bug`, `chore`, `spike`, `docs`;
  - area: `pkg:core`, `pkg:storage`, `pkg:collector`, `pkg:cli`, `pkg:generator`, `pkg:tracker`, `pkg:api`, `app:web`;
  - automation: `agent-ready` (an agent may pick it up), `agent-failed` (an agent run failed; the issue has the
    diagnosis), `needs-human` (set by `/triage`: an open question, a guarded path, or an architectural or spike size;
    never together with `agent-ready`).
- **Size:** within `/fix`'s limits (one repo, at most 5 changed non-test files, no new contract, no guarded path), else
  `spike`, `bounded` or `architectural` as `/feature` sizes them. No story points; cycle time is tracked instead.

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
- its size is set (an `agent-ready` issue is within `/fix`'s limits or a bounded `/feature`);
- the repos it changes are named and the affected packages are tagged with area labels;
- its dependencies are linked (blocked-by / related issues);
- it has a verification command that runs from the repo root after the merge and proves the ACs;
- it has no open question.

`/triage <issue>` drafts these sections, and after the owner's approval writes them and sets `agent-ready`, or
`needs-human` when something above is missing.

### Definition of Done

- check green in CI;
- every AC has a test;
- docs/ADR/SPEC updated if scope changed;
- PR reviewed and merged by the owner;
- issue Done.

The same checklist is in the PR template.

## Architecture Decision Records

- Location and name: `docs/adr/NNNN-kebab-title.md`, numbered in sequence: the next free number in `docs/adr/`.
- Format: [MADR](https://adr.github.io/madr/): a header with `Status`, `Date` and `Deciders`, then the sections Context
  and Problem Statement, Considered Options, Decision Outcome (with Consequences) and More Information. Follow
  [ADR 0001](adr/0001-uv-workspace-with-namespace-packages.md) as the model.
- Statuses: `proposed` (under review in a PR), `accepted` (merged), `superseded by NNNN`.
- An accepted ADR is never edited. A changed decision is a new ADR that supersedes the old one; the only change to the
  old file is its status line, `Status: superseded by NNNN`, in the same PR.
- Write an ADR for decisions that are hard to reverse or shape the tooling and history (structure, persistence, API
  style, testing, conventions, git flow). Team process stays in this file.
- Every change to `docs/adr/`, including a new ADR, needs the owner's explicit confirmation before it is made.

## Database migrations

The migrations ship inside the installed storage package, so an installed `hub` creates and upgrades its own database:
the scripts (`env.py`, `script.py.mako`) are in `packages/storage/src/agent_hub/storage/migrations/` and the revisions in
`packages/storage/src/agent_hub/storage/migrations/versions/`. There is no `alembic.ini`: the Alembic config is built in
code by `agent_hub.storage.migration.alembic_config`, which `make migrations`, the tests and `hub collect` all use.
Contributors run the Alembic sub-commands through `python -m agent_hub.storage.migration`, with the database URL passed
as `-x db_url=…` (default `sqlite://`, an in-memory database). Tables are declared only in
`agent_hub.storage.db.metadata`, and the schema is only ever created by the migrations (never `metadata.create_all`).

1. Change `metadata` in `packages/storage/src/agent_hub/storage/db.py`.
2. Create the next revision (numbered ids, like `0001` and `0002`), from the repo root:

   ```bash
   uv run --locked --all-packages python -m agent_hub.storage.migration revision -m "<message>" --rev-id <NNNN>
   ```

   To autogenerate it against a scratch database, first upgrade one to head, then pass the same URL:

   ```bash
   db="$(mktemp -d)/scratch.db"
   uv run --locked --all-packages python -m agent_hub.storage.migration -x db_url="sqlite:///$db" upgrade head
   uv run --locked --all-packages python -m agent_hub.storage.migration -x db_url="sqlite:///$db" \
     revision --autogenerate -m "<message>" --rev-id <NNNN>
   ```

3. Review the generated file; migrations run in batch mode on SQLite. The file is formatted by ruff on creation. It is
   package code: mypy strict, ruff and coverage check it like the rest of `src/`.
4. `make migrations` (in `make check`) upgrades a scratch database to head and runs `alembic check`, so a `metadata`
   change without a migration fails. The integration test also downgrades to base.

A merged revision is never edited; fix it with a new revision. Any edit in
`packages/storage/src/agent_hub/storage/migrations/versions/` needs the owner's explicit confirmation, as ADR edits do.
Never point Alembic or a test at the real database: the file `hub collect` picks (`--db`, else `AGENT_HUB_DB`, else the
XDG default `$XDG_DATA_HOME/agent-hub/agent-hub.db` or `~/.local/share/agent-hub/agent-hub.db`).

## Hub config schema

`hub.schema.json`, the JSON Schema of `hub.json`, is exported from the `HubConfig` model and ships as core package data
(`packages/core/src/agent_hub/core/hub_config/hub.schema.json`). After any change to a `HubConfig` model, regenerate it
from the repo root and commit the file with the change:

```bash
make hub-schema
```

The drift tests (in `make check-fast`) fail while the file differs from the export:
`packages/core/tests/unit/hub_config/test_schema.py` compares the content,
`tests/unit/scripts/test_export_hub_schema.py` the exact bytes (LF, key order). On an unchanged model
`make hub-schema` leaves `git status --porcelain` empty. A Pydantic upgrade that changes the export needs the same
regeneration in its PR.

The agent output schemas `review.v1.json` and `eval.v1.json` (ADR 0028) are exported the same way from `ReviewOutput`
and `EvalOutput` and ship beside them (`packages/core/src/agent_hub/core/features/`). After any change to either model,
run `make output-schemas` and commit both files. Two drift tests fail while a file differs from the export:
`packages/core/tests/unit/features/test_agent_outputs.py` (`test_matches_export_when_shipped_schema_read`) and
`tests/unit/scripts/test_export_output_schemas.py` (`test_matches_repo_files_when_schemas_exported`), both on the exact
bytes.

## Releases

A release is an annotated tag `vX.Y.Z` on a commit of `main` ([ADR 0013](adr/0013-release-by-git-tags.md)). The
`release.yml` workflow creates it when dispatched ([ADR 0047](adr/0047-release-tag-by-workflow-dispatch.md)); no agent
session holds a credential that can push a tag. Never create a tag through the GitHub Releases UI or with a plain
`git tag`: both make a lightweight tag, which `release.yml` rejects.

The hub's `/release` skill runs the whole release. The owner does three things: confirm the version and the SHA at its
gate, merge the version PR, and merge the hub pin PR. The agent does the rest:

1. **The version PR.** It sets `version` in `packages/cli/pyproject.toml` and `packages/agent-hub/pyproject.toml` to
   `X.Y.Z`, runs `uv lock` and commits `uv.lock`. `make lockstep` (in `make check-fast`) fails while the two versions
   differ; the other packages keep their versions. The same PR renames `CHANGELOG.md`'s `[Unreleased]` section to
   `[X.Y.Z] - <date>`, opens an empty `[Unreleased]` above it and updates the compare links at the bottom, bumps the
   README's version badge, updates the status line of `docs/SPEC.md`, and runs `make llms-txt`. After the owner
   merges it, the run continues on the merge commit with a new gate (the version and that commit's full SHA).
2. **The check.** `make check` on a clean checkout of that exact SHA, output redirected and `$?` checked.
3. **The notes.** Features, fixes, what `hub sync` rewrites in every hub (computed by syncing two throwaway hubs, one
   per version, and comparing their `hub.lock`), doctor rules, migration steps. They become the tag message.
4. **The tag.** The agent dispatches `release.yml` with the version, the SHA and the notes, then watches the run; a
   red run stops the release with its URL:

   ```bash
   gh workflow run release.yml --ref main -f version=X.Y.Z -f sha=<full sha> -f notes="$(cat <notes file>)"
   gh run list --workflow release.yml --event workflow_dispatch --limit 1   # the run's id
   gh run watch <run id> --exit-status
   ```

   Its `release-tag` job refuses a malformed version or SHA, empty notes, a commit not on `main`, a commit whose cli
   and meta versions differ from `X.Y.Z` (`scripts/check_release.py` on that commit's files) and a tag that already
   exists. Then it runs `git tag -a vX.Y.Z --cleanup=verbatim -F <notes> <sha>` as `github-actions[bot]` and pushes
   that one tag. A tag pushed with `GITHUB_TOKEN` starts no other workflow, so `release-check` runs next in the same
   run: the tag form, that it is annotated (the remote has a peeled `^{}` entry for it) and that it is `v` + the cli
   and meta version (`scripts/check_release.py --tag=vX.Y.Z --peeled=…`), that its commit is on `main`, and that the
   pinned `uvx` command prints `X.Y.Z`.
5. **The verification.** `git ls-remote --tags origin "refs/tags/vX.Y.Z^{}"` prints the SHA.
6. **The hub pin PR.** `platform.version` in the hub's `hub.json`, `hub sync`, `hub doctor` and the hub's check, with
   the notes' sync section in the PR body.

A tag pushed by hand (`git tag -a vX.Y.Z -F <notes> <sha>`, then `git push origin vX.Y.Z`, that one tag, never
`--tags`) is still checked: `release.yml` runs `release-check` on every pushed `v*` tag. Wait for that run to be green:
a red run means the tag is not a release (0.9.0 to 0.14.0, and 0.20.0, were lightweight tags whose runs failed).
`tests/e2e/test_release_annotated_tag.py` runs the annotation step with real git and proves a lightweight tag is
refused; `tests/e2e/test_release_dispatch_tag.py` does the same for the dispatch job's tag step.

- A wrong or failed tag is never moved or deleted: fix the cause in a PR, bump the patch version and tag that. This
  holds for a lightweight tag too: the existing ones stay as they are. The dispatch job refuses a tag that exists.
- Tag immutability rests on this written rule and that refusal (tag rulesets are not set up).

## Manual repository and Linear settings

These live outside the repo and are set by the owner:

1. **GitHub `main` protection:** pull request required; required status check = the CI `check` job (it passes only when
   every other job of `ci.yml` passed); linear history; squash merge only (merge commits and rebase merge disabled); default squash commit message =
   the PR title. `.github/CODEOWNERS` is informational: code-owner review is not required.
2. **Linear:** team AGH states, labels (type, area, automation), one project per SPEC phase with the phase gate as the
   final milestone, 2-week cycles, and the issue template above.
