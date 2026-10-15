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

- `hub workflow list` and `hub workflow validate [NAME]` load and plan the hub's `workflows/<pack>/` files (YAML through
  the strict loader, or JSON), then the built-ins, against the graph workflow format (ADR 0032): unknown keys, unknown
  or non-upstream node references, argv references that are not a whole element, cycles and a bad
  `returns`/`outcome_field` are reported as `<file>:<line>: <key>: <message>`, exit 1 (AGH-218).
- `hub workflow test [NAME]` dry-runs each pack's `fixtures/*.yaml` through the workflow engine with stubbed node
  results, in memory (no child, network, tracker write or event), and checks `expect` (status, outcome) and the exact
  `failed` and `reached` sets; a reached node without a stub fails its fixture, and any failure exits 1.
  `--stubs-init` writes a passing skeleton fixture for NAME without overwriting a file (AGH-222).
- Workflow `approval` and `wait` nodes. An approval (`message`, `decisions`, `capture_response`) or a wait (`duration`
  up to 7 days, an `until` instant, or `attention` answered with text or one of `options`) pauses the run: `hub
  workflow run` prints `run <id>: paused at <node>` and records a `gate.request` (an approval or attention wait shows
  in Approvals). `--resume RUN` takes the same gate up again and goes on once it has its decision or its time. The
  output (`{decision}`, `{at}`, `{text}`, `{choice, text}`) is readable from `when:`; rejecting the default decisions
  cancels the run unless a `when:` reads the decision. An `until` is at most 7 days ahead; a timed wait ends on a
  resume past its time. `hub workflow test` stubs gates with `{decision, text}`, `{text}`, `{choice}` or `{}`; without
  a stub the run pauses (`expect.status: paused`). A gate in a `loop_group` body pauses its iteration, and the resume
  goes on in it (rework: reject, fix, approve); two gates with no order between them are a load error (AGH-230).
- `hub workflow approve|reject|respond RUN [NODE] [TEXT]` decide a paused run's open gate (`respond` takes
  `--choice` for a declared decision or option) and resume the run. One decision per gate: a second, a gate that is
  not open or an answer the gate does not take is refused. The text stays in the run's record; the event database
  gets a `control_plane` `gate.result`, so Approvals shows the gate decided. A workflow gate closed without a decision
  (run abandoned, gate skipped or failed on resume) shows declined, and its "How to decide" names these commands
  (AGH-230).
- `hub workflow run NAME --input name=value` prints the nodes a run would start; with `--live` it runs them: agent
  nodes as `claude -p` in the hub with its settings and plugin, shell and script nodes as programs without a shell,
  each child with a scoped environment (none gets `LINEAR_API_KEY`). The run is recorded under
  `.agent-runs/workflows/<run>/` with a snapshot of its document, prompts and scripts, and its events go to the
  event database. `--resume RUN` continues a failed run on its snapshot, reusing what completed; `--abandon RUN` ends
  it cancelled. It makes no tracker write (AGH-221).
- Workflow runs read any workflow engine run: steps keep their node ids (`a__b` inside an include) with `skipped`,
  `failure_kind` and `skip_cause`; a run has `status`, `outcome`, `revision` and `content_hash`, and its latest
  `run.end` decides how a resumed run ended. `GET /api/v1/workflow-runs` filters by `workflow` and `failure_kind`;
  `hub run` runs read as before (AGH-225).
- `GET /api/v1/workflows` lists each project's workflows (source `hub` or `builtin`) and the files that do not load;
  `GET /api/v1/workflows/{project}/{name}` gives a workflow's document and its layers (AGH-225).
- `hub step worktree|verdict|commits|pr|report` run `hub run`'s stages one at a time and print one JSON object each (the
  worktree and the repo's target, the session's verdict, the branch's commits, the PR's url, the delivery), for the issue-to-pr
  workflow's `hub step` nodes. Only the fetch, the push and `gh` get the GitHub tokens; none reads or writes the
  tracker (AGH-223).
- `GET /api/v1/sessions` and `GET /api/v1/sessions/{session_id}` carry the Live tile fields (`waiting_reason`,
  `last_action`, `last_tool`, `needs_you_problem`, `failing_notice`, and `sparkline_60s` until the session ends), derived
  by the same code as the Live tiles, so a sessions list can show what Live shows (AGH-236).
- `GET /api/v1/agent-sessions` and `GET /api/v1/agent-sessions/{id}` carry `observed_session_id`, the observed
  session's id once its twin has been observed, else `null`, so a list can show a driven session once (AGH-236).
- A workflow node of type `include` copies in another workflow of the same pack at load: its nodes become
  `<include id>__<id>`, `with:` fills its `inputs`, the include's `depends_on`/`when`/`trigger_rule` go to the block's
  roots, and `$<include>.output` reads its `returns` node (or its single sink); at most 3 levels and 512 nodes, no
  cycles. A block's prompt files read its own inputs and nodes. Fixtures stub the namespaced ids (AGH-228).
- A `loop_group` node repeats a body of nodes until its `until_when` holds or its `until_bash` exits 0, at most
  `max_iterations` times; body steps are recorded as `<group>__<id>`, `$LOOP_PREV.<id>.output` reads the previous
  iteration, and `$<group>.output.<id>` reads the last one (AGH-228).
- The workflow engine runs a layer's nodes concurrently (at most 4 attempts at once in a run), each recorded as it
  ends; Ctrl-C stops the running children. A `mutates_checkout: false` node never shares a layer with one that may change the checkout, and fails
  `config` when its attempt changes `git status` (AGH-228).

### Changed

- The chat of a session `hub web` drives is one fixed-height column: the header (title, status, cost, actions) and the
  composer stay on screen and only the transcript scrolls. It opens at the latest message, or at the oldest permission
  still waiting, follows the reply while you are at the bottom, stops when you scroll up, and offers "Jump to latest ·
  N new" (or End); Send brings you back to the bottom (AGH-237).
- The chat streams smoothly: replies render once per frame with a caret, long transcripts open fast, a "Claude is
  working · <tool>" row shows while a turn runs, Stop works while a permission waits, Esc in the empty composer stops
  the turn, and "Turn interrupted" follows its result (AGH-238).

### Fixed

- Releases are annotated tags again. The tags `v0.9.0` to `v0.14.0` were pushed as lightweight tags, so `release.yml`
  refused each one (red runs nobody acted on), and a stray `v.0.14.0` tag points at the `v0.14.0` commit; `release.yml`
  refused it for its form. Tags are never moved or deleted, so all of them stay, and `v.0.14.0` is not a release: do not
  pin it. This patch release is the first annotated tag since `v0.8.0`; nothing changes for a hub that pins an older
  version. A new e2e test runs the workflow's annotation step with real git and proves a lightweight tag is refused
  (AGH-216).

## [0.14.0] - 2026-10-14

### Added

- Read-only agents are held when they change a checkout. An agent whose frontmatter says `mutates_checkout: false` (the
  base researcher, spec-reviewer and quality-reviewer; any hub or project agent may add the key) is checked by a new
  hook, `plugin/hub-workflow/hooks/readonly_gate.py`, on SubagentStart and SubagentStop: the repos of `hub.json`, the
  hub (not `brain/`) and their task worktrees are snapshotted at the start and compared at the stop. A change the
  agent's own file tools made, or any change when nothing else ran meanwhile, holds its stop once with the paths and its
  Bash commands; a change something else may have made is reported to the main session, never blocked. Outcomes go to a
  local record, `$TMPDIR/hub-readonly-<session>.jsonl` (paths only), and nothing is sent yet (AGH-159). The gate fails
  open with a `not checked` note. Run `./hub sync` after the bump: it adds the hook and rewrites `hooks.json`,
  `.claude/settings.json` and the three agents (AGH-141).
- Drive Claude Code sessions from `hub web`: "New session" on the Sessions screen starts your own `claude` in the hub,
  a repo or a worktree, with the hub's CLAUDE.md, hooks (the guard still applies), skills and agents; the chat sends
  messages, answers permission prompts, interrupts, changes mode and model, resumes and forks. Install with the
  `sessions` extra (`agent-hub[sessions]`, the Claude Agent SDK). `hub web` now prints
  `http://127.0.0.1:<port>/?token=…`: open it once per browser, the token becomes the cookie the new
  `/api/v1/agent-sessions` routes need (every other route is unchanged); `--open` opens it, and the session limits are
  options with `AGENT_HUB_*` variables. These sessions' conversations are stored, redacted, in the `hub web` database
  for 30 days after they end. Off in the Docker image. No `hub.json` change and no `hub sync` needed (ADR 0031,
  AGH-165).
- `hub validate-output review|eval FILE` checks one agent JSON output, a reviewer's
  `reviews/<ticket>/<reviewer>-r<N>.json` or the evaluator's `evals/<delivery>.json` (with its sibling `.md` and the
  feature's `features.json`), against its versioned schema and cross-field rules: exit 0 `<file>: valid`, exit 1 with
  one line per problem (the first 200, then the total), exit 2 on a usage error. Links are never followed and no
  `hub.json` is needed. `hub sync` now ships the two JSON Schemas to `plugin/hub-workflow/schemas/review.v1.json` and
  `eval.v1.json` (managed, run `hub sync` after the bump) (AGH-139).
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
- `hub.json` takes `guard.readable_env_files` and `guard.secret_env_files`: env file names (`.env.<suffix>`) the guard
  lets agents read, e.g. `[".env.local"]`, or always denies, e.g. `[".env.staging"]`. `.env` itself, paths and key
  files are rejected, and a name cannot be in both lists. A `$HUB_CONFIG` file can add secret names but never release
  one. `hub doctor` (`secrets.config`) lists both as infos. Run `./hub sync` after bumping `platform.version` to get
  the new guard. Without the keys nothing changes (AGH-210).

### Changed

- The `spec-reviewer` and `quality-reviewer` agents speak one vocabulary: `PASS` or `FAIL`, findings `blocking` or
  `minor`, `PASS` only when no finding is `blocking` (`APPROVE`/`CHANGES` and `blocker`/`should-fix`/`nit` are gone).
  Given the ticket, task, round and commit, each ends its reply with one JSON block, a review output
  (`agent-hub/review/1`); both stay read-only. `/fix`, `/refactor` and `/review` read the new words. `hub sync` rewrites
  five managed files (the two agents and the three skills): run `hub sync` after the bump (AGH-139).
- `/feature` acts only on validated outputs. Step 7 saves each reviewer's JSON to
  `reviews/<ticket>/<reviewer>-r<N>.json`, runs `./hub validate-output review`, re-asks once with every printed line
  and stops on a second failure; a ticket is `approved` only when the latest round of both reviewers is a validated
  `PASS`. The evaluator writes and validates `evals/<delivery>.json` beside its `.md`; step 8 re-dispatches it once
  (a new `-rN` pair) when that file is missing or invalid, and ships only on a validated `SHIP`. `hub sync` rewrites
  `agents/evaluator.md` and `skills/feature/SKILL.md`: run `hub sync` after the bump (AGH-139).
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

[Unreleased]: https://github.com/jroquette/agent-hub/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/jroquette/agent-hub/compare/v0.13.0...v0.14.0
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
