# Changelog

All notable changes to agent-hub are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) through annotated `vX.Y.Z` tags
([ADR 0013](docs/adr/0013-release-by-git-tags.md)). While the version is 0.x, a minor release may break a hub: the
**Changed** entries say what to do when you bump `platform.version`.

A PR that users will notice adds a line under `[Unreleased]`; the release PR turns that section into the new version.
Entries before 0.11.0 were written afterwards from the merged PR titles.

## [Unreleased]

## [0.15.0] - 2026-10-16

### Added

- `hub web` highlights completed code blocks in the chat, notes and plans (about a dozen languages, lazily loaded,
  design-token colours in both themes) with `lowlight`; a block still streaming or over 2,000 lines or 64 KiB stays
  plain, and agent output stays inert (ADR 0034, AGH-252, AC-234.31).
- README: a Workflows section, and the banner no longer says the control plane is read-only. USING.md points to
  it. The web smoke starts a workflow run, approves its gate and cancels it against an installed `hub web`
  (AGH-233, AC-213.20).
- `hub web` can start a Claude session from any project screen by shaking the mouse, with a screenshot of the
  screen: a "Shake to start a session" setting (off by default) opens New session with the prompt focused and an
  "Attach a screenshot" checkbox; `POST /api/v1/agent-sessions` takes an optional PNG `screenshot` (at most
  3,932,160 bytes decoded, 8 MiB body on that route only) sent to `claude` as an image block with the first prompt;
  the stored conversation keeps only an `attachments` marker. Under `make dev` it preselects the served checkout and
  Accept edits, so Claude's edits show through Vite's live reload (AGH-260).
- Workflow runs start from hub web: "Start run" (replacing the P4 placeholder) picks a workflow and fills a form built
  from its `inputs:`, starts it live (a dry run belongs to the CLI; issue-to-pr starts from `hub run`) and opens the
  new run. Run detail offers Cancel, Resume and Abandon on an engine run, each after a confirmation; issue-to-pr runs
  keep their P4 retry (AGH-233).
- Approvals and Run detail decide a workflow run's open gate: one button per declared decision or option (labels
  from the workflow), a dialog for the reason or response where the gate takes one, and the run resumes on the
  server; Run detail lists the running run's open gates and shows the card in the waiting node's panel. Human gates
  outside a workflow run keep their Phase 4 placeholders (AGH-231).
- `hub web` can decide a paused workflow run's gate: `GET /api/v1/approvals/{id}/gate` shows its decisions or options
  (with labels) and whether it takes a text, and `POST /api/v1/approvals/{id}/decision` (a strict write that needs
  the launch cookie) records the answer through the new hidden `hub workflow decide RUN --gate ID` (text on stdin,
  no resume, `gate.result` where `web`), then resumes the run detached (AGH-231).
- `hub web` can start, cancel, resume and abandon workflow runs: `POST /api/v1/workflow-runs` and
  `/workflow-runs/{run_id}/cancel|resume|abandon` run `hub workflow run --live` as a detached child (no
  `LINEAR_API_KEY`, a pid file under `.agent-runs/web/`), keep one live run per issue across starts and resumes,
  refuse `issue-to-pr`, and are strict writes that need the launch cookie. A run's events now carry its `issue` input
  when it is a tracker key (AGH-232).
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
- `hub web` has a Workflows page (sidebar group Improve): each workflow with its source (hub or built-in), the files
  that do not load, and a workflow's graph by layers (a column per layer, arrows for `depends_on`, a list view, a
  keyboard-reachable node panel) with its document, read-only (AGH-226).
- `hub web` Run detail shows an engine run as its workflow's graph: each node with its state, attempt, skip cause and
  failure kind, and a side panel (reason, sessions, loop body steps); issue-to-pr runs keep their stage pipeline. The
  Runs list gains Workflow and Failure kind facets (AGH-226).
- `hub step worktree|verdict|commits|pr|report` run `hub run`'s stages one at a time and print one JSON object each (the
  worktree and the repo's target, the session's verdict, the branch's commits, the PR's url, the delivery), for the issue-to-pr
  workflow's `hub step` nodes. Only the fetch, the push and `gh` get the GitHub tokens; none reads or writes the
  tracker (AGH-223).
- `GET /api/v1/sessions` and `GET /api/v1/sessions/{session_id}` carry the Live tile fields (`waiting_reason`,
  `last_action`, `last_tool`, `needs_you_problem`, `failing_notice`, and `sparkline_60s` until the session ends), derived
  by the same code as the Live tiles, so a sessions list can show what Live shows (AGH-236).
- `GET /api/v1/agent-sessions` and `GET /api/v1/agent-sessions/{id}` carry `observed_session_id`, the observed
  session's id once its twin has been observed, else `null`, so a list can show a driven session once (AGH-236).
- The built-in `issue-to-pr` workflow (inputs `issue`, `repo`, `issue_text`) takes one issue to a PR as `hub run` does:
  `hub step worktree`, one implementing session in the worktree with `hub run`'s prompt, `hub step verdict`,
  `hub step commits`, the repo's `check`, `hub step pr`, then `hub step report`, whose `delivery` is the run's outcome;
  no node retries. Its fixtures (delivered, no commit, blocked, dirty tree, error, gate failure, PR failure) run in
  `hub workflow test`. Agent and loop nodes take an optional `cwd`, a reference allowed, inside the hub or a configured
  repo; shell and script nodes take an optional `stdin`, a literal or one whole reference written to the child (at
  most 1 MiB, as an agent's reply, `hub run`'s session cap), which carries the reply to `hub step verdict`; the dry
  run shows it (AGH-223).
- `hub workflow run issue-to-pr --live --input issue=ISSUE --input repo=REPO` gives what `hub run ISSUE --repo REPO --live`
  gives: it reads the issue (filling `issue_text`), writes the same `.agent-runs` records and events, makes ADR 0030's
  tracker writes from the run's delivery and exits 0 (delivered, no changes), 3 (blocked) or 1 (failed); its runs
  cannot be resumed or abandoned (exit 2) (AGH-223).
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
- `hub init` and `hub sync` seed the built-in `issue-to-pr` pack into the hub once, byte for byte as shipped
  (`workflows/issue-to-pr/`: the workflow, its prompt and its fixtures), as a whole: never into a hub whose `hub.lock`
  already lists the pack or whose folder holds files of its own, so a later release never adds a file to the hub's
  pack. The hub then owns its copy, which `hub run` and `hub workflow` read instead of the built-in; delete
  `workflows/issue-to-pr/` to follow the built-in again (AGH-227).
- `hub doctor` rule `workflows.valid` (error): every workflow of the hub's `workflows/` and the built-ins loads and
  plans, as `hub workflow validate` checks them, one finding per problem at its file and line (AGH-227).
- Built-in pack `sdlc`, seeded into hubs next to `issue-to-pr`: `review` runs the spec and quality lenses side by
  side (the pack's own reviewer prompts; a lens whose attempt changes the checkout's git status fails), each replying
  with the review JSON `hub validate-output review` checks, then a verdict (PASS only when both pass, the run's
  outcome); `deliver` takes an issue (`issue`, `repo`, `issue_text`) through up to three rounds of implement, its
  verdict (a blocked session ends the rounds), the repo's check and that review, each round reading the last one's
  check and findings within 32 KiB, then the commits, the PR and the delivery as `issue-to-pr` makes them, with no
  tracker read or write. A loop group's body agent with `context: fresh` starts afresh each iteration. `hub workflow
  test` takes several names, and a dry `hub workflow run` lists a loop group's body under it (AGH-229).

### Changed

- The chat of a session `hub web` drives is one fixed-height column: the header (title, status, cost, actions) and the
  composer stay on screen and only the transcript scrolls. It opens at the latest message, or at the oldest permission
  still waiting, follows the reply while you are at the bottom, stops when you scroll up, and offers "Jump to latest ·
  N new" (or End); Send brings you back to the bottom (AGH-237).
- The chat streams smoothly: replies render once per frame with a caret, long transcripts open fast, a "Claude is
  working · <tool>" row shows while a turn runs, Stop works while a permission waits, Esc in the empty composer stops
  the turn, and "Turn interrupted" follows its result (AGH-238).
- `hub run --live` now runs the `issue-to-pr` workflow through the workflow engine, with its options, records, events,
  tracker writes and exit codes unchanged: a hub's own `workflows/<pack>/issue-to-pr.yaml` replaces the built-in (it
  must load, else exit 1, and declare the inputs `issue`, `repo`, `issue_text`, plus `start` for `--from verify`, else
  exit 2) and is read from a copy taken at the start. `--model`, `--effort`, `--max-turns` and `--budget`, when typed,
  win over its `implement` node's own model and limits (the built-in's are `hub run`'s defaults). A failed stage's `failed`
  record and its `step.end` event now carry the failure kind (`failure_kind`, e.g. `exec_failed`, `timeout`). The dry
  run is unchanged. The built-in `issue-to-pr` gains the input `start` (`verify` skips the session), runs its `hub step`
  nodes in process as `hub run` does, and keeps the gate output's last line break (AGH-224).
- The chat composer grows with its text up to 40% of the window, keeps an unsent draft per session in the browser
  (restored after a reload), has focus on open unless a permission waits, ignores Enter while an IME composes (and on
  touch screens Enter is a new line); a message shows "Sending…" at once, and "Queued: Claude reads it after this
  turn" when sent during a running turn (AGH-239).
- Chat tool cards read running, waiting for you, done, error or denied (icon and text), with a call's permission card
  right under it; output over 10,000 characters is cut with "Show all (N characters)", consecutive calls group as
  "Explored · 3 Read, 2 Grep" (open while one waits for you or failed), and thinking reads "Thought for N s" (AGH-240).
- Chat messages show when they were written ("3 min ago", the full date and time on hover) and a Copy button for
  their raw Markdown, on hover or focus (always on touch screens); Markdown code blocks show their language and a Copy
  button, and wide tables scroll sideways in their own region (AGH-241).
- A hub's `make check` also runs `./hub workflow test`, the workflow packs' fixtures, after `hub doctor` and before the
  hub's own tests (AGH-227).
- The chat is complete for the keyboard and screen readers: `/` at the start of a message lists the session's slash
  commands and skills (filter as you type, arrows, Enter or Tab inserts, Esc closes; Enter never sends while it is
  open, and a live region announces how many commands match); Ctrl/Cmd+Alt+Enter allows and Ctrl/Cmd+Alt+Backspace
  denies the oldest waiting tool permission (not on a key repeat, mid-composition or under a dialog), `a` / `d`
  answer a focused tool card (`g a` still goes to Approvals and never allows), plain Alt+Enter still sends, Shift+Esc focuses the composer, ArrowUp in an empty composer recalls your last prompt, and a new
  permission card never takes focus from a composer holding text; the shortcut sheet has a Chat group, and the chat
  has no serious axe violation in any state (AGH-242).
- Sessions groups its table into Waiting, Live, Idle and Ended or failed sections, each with its own count, table
  and "Load more", and one shared sort applied within each section; a header button collapses a section (remembered
  in this browser), empty sections are hidden, a section past 100 rows scrolls in its own window, a status facet
  shows only its section, and the period now filters only Ended or failed (the count line says so), so a running
  session older than the period still shows (AGH-243).
- Sessions' status sections refresh live as sessions change (at most every 2 s), without moving your scroll position
  or losing the focused row when it moves to another section (AGH-243).
- Sessions lists the sessions hub web drives in its status sections: one with an observed twin shows once, as that
  row with a "Chat" badge, and opens its chat (in Waiting while it waits on a permission); one without a twin shows in
  the section of its status with the fields it has. "New session" moves to the page header, the "Driven from hub web"
  list is gone, and the cloud guidance is a collapsed "Cloud sessions" below the sections (AGH-244).

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

[Unreleased]: https://github.com/jroquette/agent-hub/compare/v0.15.0...HEAD
[0.15.0]: https://github.com/jroquette/agent-hub/compare/v0.14.0...v0.15.0
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
