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

[Unreleased]: https://github.com/jroquette/agent-hub/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/jroquette/agent-hub/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/jroquette/agent-hub/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/jroquette/agent-hub/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/jroquette/agent-hub/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/jroquette/agent-hub/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/jroquette/agent-hub/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/jroquette/agent-hub/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/jroquette/agent-hub/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/jroquette/agent-hub/releases/tag/v0.2.0
