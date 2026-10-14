# Changelog

All notable changes to agent-hub are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) through annotated `vX.Y.Z` tags
([ADR 0013](docs/adr/0013-release-by-git-tags.md)). While the version is 0.x, a minor release may break a hub: the
**Changed** entries say what to do when you bump `platform.version`.

A PR that users will notice adds a line under `[Unreleased]`; the release PR turns that section into the new version.
Entries before 0.11.0 were written afterwards from the merged PR titles.

## [Unreleased]

### Added

- `hub doctor` (`features.tracker`) warns on a feature's agent outputs, `evals/*.json` and `reviews/<ticket>/*.json`:
  one without its `.md` record, or one that fails validation, with its problem count, its first problem and the
  `./hub validate-output` command that lists them all. Warnings only; one validation budget per run, and an info line counts the outputs it skipped (AGH-139).
- Skills tab in `hub web` (`/projects/:project/skills`): every skill, agent and hook of the hub with what it does, a
  copyable invocation, origin (managed by `hub sync`, project-owned or local) and invocation mode, the frontmatter, the
  rendered text with a table of contents and a Raw view, the steps derived from the text, uses and used-by links,
  bundled files by role, diagnostics, an approximate context cost and 30-day usage counts from the collected events.
  Read-only and bounded; links are never followed. New routes `GET /api/v1/projects/{project}/skills` and below
  (AGH-164).
- `hub.json` takes an optional `models` key: `tiers` maps `small`, `medium` and `large` to model names, and `agents`
  moves a plugin agent to another tier, e.g. `{"tiers": {"large": "claude-opus-4-1"}, "agents": {"researcher":
  "large"}}`. `./hub sync` renders each agent's `model:` from it, and `hub run` takes its default model from `medium`
  (`--model` still wins). Without the key nothing changes (AGH-180).

### Changed

- `hub run` no longer reports a run that ended with no commit, or whose session stopped to ask a human, as a failure.
  No commit: a `Run <id> ended with no changes at <STAGE>: …` comment, no label, exit 0. Stopped: the blocked label, a
  `Run <id> stopped at <STAGE> and needs a human. The session asked: …` comment, exit 3. A failure still adds
  `tracker.failed_label` and exits 1. A run that did not fail, and `hub ship`, remove the failed and blocked labels the
  issue carries. When you bump `platform.version`, update scripts that read `hub run`'s exit code: 0 now includes "no
  changes" and 3 is new (ADR 0030, AGH-178).
- `hub run` refuses, dry or live, an issue whose description lacks one of the six input-brief headings (Problem, Why,
  Why now, Outcome, Invariants, Acceptance criteria), naming them, before it creates anything; `/feature` gains step 0
  Brief, which drafts the missing sections with you. When you bump `platform.version`, add the headings to the issues
  you run (ADR 0026, AGH-138).

### Added

- Optional `tracker.blocked_label` in `hub.json`: the label a blocked `hub run` adds. Absent, it is
  `tracker.failed_label`; create the label in the tracker before you set it (ADR 0030, AGH-178).

## [0.13.0] - 2026-10-13

### Added

- Feature Tickets tab in `hub web`: each ticket with its Linear status, assignee and link, the parallel groups
  (layers), a recommended order, what blocks each ticket (from the plan's `blocked_by` and Linear's relations), cycles,
  outside blockers and the critical path. `hub web` reads Linear server-side and read-only when `LINEAR_API_KEY` is
  set (cached 60 s; ADR 0025); without it the tab shows the plan from `features.json` with a notice. New route
  `GET /api/v1/features/{project}/{slug}/tickets` (AGH-136).
- Feature records: `features.json` gains `tickets` (with `blocked_by`) and a `ticket` per AC; the evaluator writes
  one `evals/<delivery>.md` per delivery instead of overwriting `eval.md`; reviews are recorded in
  `reviews/<ticket>.md`; approved specs change only through an Amendments section. `hub doctor` checks them
  (AGH-136).

### Changed

- The golden path reflects the whole feature: Evaluate is done only when the latest evals cover every AC, Review
  only when every ticket is reviewed (Linear `completed` or an approved review record), Implement counts tickets and
  ACs; a canceled ticket no longer blocks. Run `hub sync` after bumping `platform.version` to get the updated
  planner, evaluator, requirements-analyst and `/feature` templates (AGH-136).

## [0.12.0] - 2026-10-13

### Added

- `hub run` keeps the run's status apart from what it delivered: a session that left no commit (`no_changes`) or
  stopped to ask for a human (`blocked`) records `not_delivered` instead of `failed`, and `reported` names the
  `outcome`. The control plane shows those runs as "No changes" or "Blocked" (not failed), with the reason, the
  workflow-run API adds `delivery` and `delivery_reason`, and `retro_metrics.py` counts them apart. The tracker
  still gets the failed label for them, and the command still exits 1 (AGH-140).
- Apache License 2.0 (`LICENSE`, `NOTICE`, and `license` in every package), `SECURITY.md`, this changelog, a Renovate
  configuration, and `llms.txt` / `llms-full.txt` for AI agents, generated from the docs and checked by
  `make check-fast` (AGH-137).

### Changed

- The generated hub-workflow asks for the minimum: `/feature` states a minimum-sufficient rule that the
  requirements-analyst, architect, implement step and both reviewers cite; *bounded* is the default size and a path
  under `guard.ask_before_edit` alone no longer makes a feature *architectural*; hostile-input scale, bounds and budget
  checks apply only to code that parses untrusted or unbounded input; reviewers flag what is extra and the main session
  weighs their findings. Bump `platform.version` and run `./hub sync` (AGH-147).

### Fixed

- A feature's tracker issue ids now reach `features.json` → `linear`, where `hub web` reads them: `/feature` step 4
  writes the ids of the issues it creates there and runs `./hub doctor --only features.tracker`, and the planner
  writes `"linear": []`. `features.tracker` warns on a feature folder with `issues.md` but no tracker id in
  `features.json` or in the spec's frontmatter. After `./hub sync`, fill `linear` for existing features; the warning
  names any left (AGH-143).

## [0.11.0] - 2026-10-13

### Added

- Control plane: readable sessions, problems, learning accept and reject through hub PRs, the Brain browser and
  feature records (AGH-201).

### Changed

- Generated `.claude/settings.json` leaves `terraform` and `aws` to the guard's infra rules instead of denying them
  outright (AGH-45).

## [0.10.0] - 2026-10-12

### Added

- The guard classifies infra commands by environment (`guard.infra`: allow and prod-marker patterns) (AGH-45).

### Changed

- The hub workflow works inside Claude Code's sandbox, which generated hubs now enable: `./hub` moves uv's folders
  into `.hub-uv/` when the sandbox denies them, and `hub doctor` checks the setup (`sandbox.workflow`) (AGH-134).

## [0.9.0] - 2026-10-12

### Added

- `hub ship`: checks, push and cross-linked PRs per changed repo, and the issue moved to review (AGH-63).
- `hub start ISSUE`: worktrees, the issue moved to started, and a Claude session with a first prompt (AGH-62).
- `hub setup`: one-command onboarding of a developer's machine (AGH-71, AGH-51).
- `tracker.states` with `started` and `review`; the tracker moves an issue only from an unstarted state (AGH-62).
- Phase 2's first slice: the control plane `hub web` (REST API, React app, hook sensor, transcript collector,
  redaction) and its Docker packaging (AGH-200).
- Infra settings in `hub.json` (`guard.infra`) (AGH-45).

### Fixed

- The Stop gate sees an unstaged edit of a tracked code file (AGH-132).
- `release.yml` refuses a lightweight tag (AGH-30).

## [0.8.0] - 2026-10-09

### Added

- Workflow skills: `/fix`, `/triage`, `/review`, `/deliver`, `/release`, `/retro`, `/refactor`, `/incident`, `/adr`,
  `/upgrade` and `/onboard`, registered and routed from `/kickoff` and `/feature` (AGH-108).
- Stop gate budget and timeouts, and an optional `check_fast`.
- Hubs seed a starter `AGENTS.md` for app repos; `hub doctor` warns when a repo has none, and when personal memory
  can reach git.
- Learnings are routed by layer; personal memory stays local.
- Worktree setup scripts get the task's name, folders and port offset.
- A configurable platform repository in `hub.json` (`platform.repository`).
- The superpowers plugin is optional in generated hubs.
- The agent usage guide (`docs/USING.md`), executed as a test (AGH-111).

### Fixed

- The guard denies clustered force flags and `--mirror`, and `/kickoff` detects unguarded sessions.
- Headless `/onboard` can write its proposals (AGH-114).
- `hub bench` runs its git worktree commands one at a time (AGH-120).

## [0.7.0] - 2026-10-06

### Added

- `hub sync --adopt [--accept PATH]`: join a hand-made hub to `hub.lock` (AGH-16).
- Per-developer identity in `hub.local.json` (AGH-65), several tracker teams (AGH-56), per-repo default branch
  (AGH-46) and conventions in `hub.json` (AGH-57).

## [0.6.0] - 2026-10-02

### Added

- Optional modules (`cloud`, `bench`, `contract-sync`, `marketplace`) with their templates and makefiles.
- `hub bench` and `hub bench --validate`.

## [0.5.0] - 2026-10-02

### Added

- `hub next` and `hub run` on the tracker port.
- The Linear MCP transport, chosen by `tracker.transport`.

## [0.4.0] - 2026-10-01

Includes 0.3.0, which was never tagged.

### Added

- `hub doctor` with its rule runner and config rules.
- The tracker port and the Linear GraphQL adapter.
- `hub worktree`, `hub agent`, the `./hub` shim and the `./agent` launcher.

## [0.2.0] - 2026-09-30

### Added

- The foundation: uv workspace, `check-fast`/`check` gates, ADRs, the canonical event, `hub collect` and the event
  store.
- The `hub.json` config model and schema, the generator templates, `hub init` and `hub sync`.
- The release check on `v*` tags.

[Unreleased]: https://github.com/jroquette/agent-hub/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/jroquette/agent-hub/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/jroquette/agent-hub/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/jroquette/agent-hub/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/jroquette/agent-hub/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/jroquette/agent-hub/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/jroquette/agent-hub/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/jroquette/agent-hub/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/jroquette/agent-hub/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/jroquette/agent-hub/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jroquette/agent-hub/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/jroquette/agent-hub/releases/tag/v0.2.0
