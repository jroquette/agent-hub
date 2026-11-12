# 0061. A hub's git hooks check only what the commit stages, from `./hub`, with no pre-commit framework

- Status: proposed
- Date: 2026-11-12
- Deciders: José Henrique Roquette

## Context and Problem Statement

Every hub rendered a `.pre-commit-config.yaml`. Its two defects blocked unrelated pull requests:

1. **The `hub-doctor` hook checked the whole working tree.** It ran `./hub doctor` with `always_run: true`, over
   every feature, and read files the commit did not stage. In the tipple hub (2026-11-12), uncommitted edits to one
   feature's `spec.md` added AC ids its `features.json` did not hold yet. Every commit in that checkout failed on
   `features.tracker`, a commit that only added records to another feature included. `origin/main` was clean.
2. **The hooks could not run inside the Claude Code sandbox the hub turns on.** pre-commit cloned
   `https://github.com/pre-commit/pre-commit-hooks` into `~/.cache/pre-commit` at commit time. The sandbox denies
   writes outside the hub, the repos and `$TMPDIR`, and the proxy refused the clone. Agents ended up running the
   checks by hand and committing with `--no-verify`, with the owner's OK.

Two fixes were proposed for the second defect: (a) replace the `pre-commit-hooks` checks with local hooks run by
`./hub`, or (b) point `PRE_COMMIT_HOME` at a hub-local folder and install once outside the sandbox. While checking
(a), we found that pre-commit itself writes its store (`~/.cache/pre-commit`, its `README`, `db.db` and `.lock`)
on every run, before it reads the config, even when every hook is `repo: local`. So (a) alone still fails in the
sandbox on a fresh machine, and (b) needs `PRE_COMMIT_HOME` in the environment of every `git commit`, which nothing
the hub renders can set reliably (Claude Code's settings `env` takes literal values, the hub's path differs per
machine, and a relative value would land in each repo an agent commits in).

## Considered Options

- **(a) Local `./hub` hooks, still run by pre-commit.** No clone, but pre-commit's own store write fails in the
  sandbox.
- **(b) `PRE_COMMIT_HOME` in the hub, one install outside the sandbox.** Needs the variable in every commit's
  environment; fails on a fresh machine, and depends on someone remembering the install.
- **Hub-managed git hooks.** `hub sync` renders `.githooks/pre-commit` and `.githooks/commit-msg` and sets the hub's
  `core.hooksPath` to `.githooks`. No pre-commit framework at commit time.

## Decision Outcome

Chosen: **hub-managed git hooks**, with (a)'s idea for the checks.

- `.githooks/pre-commit` runs `./hub doctor --staged`. It reads git's index (`GIT_INDEX_FILE` as git sets it, so
  `git commit <paths>` is checked on the temporary index git commits), never the working tree, and checks only what
  the commit stages:
  - each staged file's hygiene, what `pre-commit-hooks` did: no trailing whitespace, exactly one newline at the end,
    valid JSON (no repeated key) for `*.json`, one valid YAML document for `*.yaml` and `*.yml`. Binary and
    non-UTF-8 files are skipped. The checks report; they never rewrite a file;
  - `features.tracker` on each feature folder with a staged path, on that folder's index files only;
  - the config rules (`config.schema`, `platform.version`) only when `hub.json` is staged. A broken `hub.json` the
    commit does not stage skips the feature checks with a note: CI reports it.
- `.githooks/commit-msg` runs `plugin/hub-workflow/hooks/commit_msg.py` on the system `python3`, as before.
- `hub sync` sets `core.hooksPath = .githooks` when it is unset or git's default `.git/hooks` (where
  `pre-commit install` put the old hooks, now unused). Another value (husky, lefthook) is left as it is, with a
  warning.
- CI keeps the whole-hub check: the managed `ci.yml` runs `make check`, whose `hub doctor` checks every rule
  (links, `hub.lock` against the managed files, the config schema, every feature) on the merged state.

### Consequences

- Good: a commit is blocked only by findings in the paths it stages. An unrelated feature's work in progress,
  committed or not, never blocks it.
- Good: nothing is cloned or downloaded at commit time, and nothing is written outside the hub and `$TMPDIR`
  (`./hub` keeps its uv folders in `.hub-uv/` inside the sandbox), so agents commit inside the sandbox without
  `--no-verify`. The sandbox is not loosened.
- Good: one fewer tool to install (pre-commit), and no pinned third-party hook release to bump.
- Neutral: `./hub` must be able to run its pinned release, as every other hub command already does. With
  `hub.lock` recording the release commit (ADR 0054), uv serves it from its cache.
- Bad: the hygiene checks only report. A developer fixes the whitespace by hand or with their editor, where
  `end-of-file-fixer` used to rewrite the file.
- Bad: a clone made before its first `hub sync` has no hooks on until someone runs `hub sync` or
  `git config core.hooksPath .githooks`.

## More Information

AGH-835. Code: `agent_hub.core.doctor.staged_check`, `agent_hub.cli.staged_index`, `agent_hub.cli.git_hooks_path`,
the templates `githooks/pre-commit.tmpl` and `githooks/commit-msg.tmpl`. Tests:
`packages/cli/tests/integration/test_commit_hooks.py` (real `git commit` through the rendered hooks),
`packages/core/tests/unit/doctor/test_staged_check.py`.
