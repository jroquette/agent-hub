# Design docs

One file per subject. For a task, open the one file it touches plus the ADRs that file links; do not read them all.
The product and its phases are in [SPEC.md](../SPEC.md). Phase 1 is designed as contracts; Phases 2 to 4 are sketches.

| File | Subject | Load it when |
|---|---|---|
| [project-config.md](project-config.md) | the `hub.json` contract: fields, validation, versioning, readers, tracker | a change reads or adds a config key |
| [developer-identity.md](developer-identity.md) | each developer's branch prefix, author and transport: `hub.local.json`, then `hub.json`, then git config, in the CLI, hooks, rendering, doctor and cloud setup | a change reads the identity keys or `hub.local.json` |
| [environments.md](environments.md) | declared environments and services in `hub.json` and `hub.local.json`, `access`, what agents see, the blocked words the guard enforces (surfaces, order, bounds, layers), `hub env`, known limits | a change reads environments, services or blocked words, or touches the guard's blocked-word rule or `hub env` |
| [hub-generator.md](hub-generator.md) | what a hub holds and who owns it, `hub init`, plugin and hooks, commands, releases | generating hub files, a hook, a `hub` command that replaces a script |
| [hub-sync.md](hub-sync.md) | `hub.lock`, `hub sync`, `--check`, the write path, the `*.project.json` merge, the project-entry links | syncing a hub, reading the lock |
| [hub-adopt.md](hub-adopt.md) | `hub sync --adopt`: per-path rules, `--accept`, the directory-link migration, listing lines, exit codes, project guards on adoption | adopting a hand-made hub (with [hub-sync.md](hub-sync.md)) |
| [hub-setup.md](hub-setup.md) | one-command onboarding of a developer's machine: tools, identity, repos, doctor | changing hub setup or what it checks |
| [hub-start.md](hub-start.md) | `hub start ISSUE`: the issue to its worktrees, its started state and a Claude Code session; resume, task name, launch, failure lines | changing hub start, its task names or its launch |
| [hub-doctor.md](hub-doctor.md) | the `hub doctor` rule interface, rule set, output and exit codes | adding or tuning a check |
| [memory-layers.md](memory-layers.md) | where a learning goes (team brain, personal memory, repo `AGENTS.md`), `/learn personal`, the personal-memory `.gitignore` lines | a change touches `brain/auto/`, `/learn` or the routing list |
| [domain-model.md](domain-model.md) | the nine entities: identity, attributes, relations, phase (sketch) | modeling an entity in core; for Session, WorkflowRun or Learning read [event-derivations.md](event-derivations.md) too |
| [event-derivations.md](event-derivations.md) | how Session (with its label, actors and problems), WorkflowRun and Learning are folded from events, and what events may hold (sketch) | a derived entity (with [domain-model.md](domain-model.md)), a projection or a view over events; a source adapter: its "Sources and privacy" part (redaction before append) and the SPEC's [canonical event](../SPEC.md#data-sources-and-event-model) |
| [feature-records.md](feature-records.md) | a feature's records: the `features.json` ticket plan (`tickets`, `blocked_by`, each AC's `ticket`, `withdrawn`), `evals/<delivery>.md`, `reviews/<ticket>.md`, the legacy `eval.md`, the planning fold and the golden path states | a change reads or writes a feature record, the planner or evaluator templates, the Tickets tab or the golden path |
| [workflow-schema.md](workflow-schema.md) | the workflow format and engine (Phase 4): packs, node types, `depends_on`/`trigger_rule`/`when`, substitution, typed outputs, status apart from outcome, retry and failure kinds, events, fixtures | workflow nodes, gates, outputs, the engine or its executors |
| [workflow-engine-rules.md](workflow-engine-rules.md) | the engine's finer rules: include expansion (inputs, sinks, depth and node caps), prompt-file scope, loop group bodies, concurrent layers | changing includes, loop groups or how a layer runs (with [workflow-schema.md](workflow-schema.md)) |
| [control-plane/README.md](control-plane/README.md) | the approved UI design of the Phase 2 control plane: principles, tokens, the screen specs in `control-plane/specs/` and the departures of Phase 2 and of AGH-201, of AGH-136 in `specs/17-features.md`, and the Learnings screen as built in `specs/18-learnings.md` (AGH-272) (a copied reference, not a subject file) | building `apps/web` screens or the `/api/v1` read models they show |
| [agent-sessions.md](agent-sessions.md) | the sessions `hub web` drives: the `SessionDriver` port, the log and its stream, the state machine, permissions, limits, access, storage and retention | changing `agent_hub.core.agent_sessions`, `claude_sessions`, the agent-session routes or the chat screen |
| [playground-export.md](playground-export.md) | `make playground-export`: each request the owner made in the playground, with their turns and answers, its commits, patch, hub files and screens on synthetic data, and how a delivery reproduces them | changing the export or delivering one |
| [worktree-environment.md](worktree-environment.md) | what the repo's worktree setup and teardown scripts get: argv, cwd, the six `HUB_*` variables, the port slot, examples | writing or running a repo's worktree script, changing what `hub worktree`, `hub run` or `hub start` passes it |

## Rules for these files

- Every subject file has exactly the sections Purpose, Contract, Invariants, Decisions and Open questions, in that
  order, and stays at or under 150 lines.
- A contract is stated once, in its subject file, and linked from elsewhere. The reasons live in the ADRs.
- A sketch is rewritten as a contract when its phase starts.

## Decisions behind them

- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): each generated file is managed or seeded; a lock guards sync.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): `hub.json` stays JSON, validated by a core model and a schema.
- [ADR 0011](../adr/0011-templates-as-package-data.md): hub templates ship as package data in a generator package.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): hub logic moves into the CLI, except the hooks.
- [ADR 0013](../adr/0013-release-by-git-tags.md): the CLI is released by semver git tags and pinned per hub.
- [ADR 0014](../adr/0014-tracker-port-linear-graphql.md): the tracker is a core port; Linear is reached over GraphQL.
- [ADR 0015](../adr/0015-linear-mcp-tracker-transport.md): transport `mcp`: the user's Linear MCP server, via `claude -p`.
- [ADR 0016](../adr/0016-per-developer-identity.md): identity per developer: `hub.local.json`, `hub.json`, git config.
- [ADR 0023](../adr/0023-short-error-message.md): a failed tool keeps a short, redacted `error_message` (300 chars).
- [ADR 0024](../adr/0024-learning-actions-from-the-app.md): learning accept and reject open hub PRs through `hub_git`.
- [ADR 0025](../adr/0025-reading-the-tracker-from-the-app.md): `hub web` reads ticket metadata through a read-only `TrackerReader`.
- [ADR 0027](../adr/0027-workflow-format-and-minimum-engine.md): the Phase 4 workflow format and minimum engine.
- [ADR 0031](../adr/0031-driving-claude-code-sessions-from-the-app.md): `hub web` drives the user's own Claude Code through the Claude Agent SDK.
- [ADR 0030](../adr/0030-run-outcomes-in-the-tracker.md): `no_changes` and `blocked` runs get their own tracker report and exit (0, 3).
- [ADR 0032](../adr/0032-workflow-engine.md): our own graph workflow engine and format (proposed; supersedes ADR 0027).
- [ADR 0033](../adr/0033-sessions-and-chat-interaction-model.md): one Sessions screen grouped by status, and the chat's interaction model.
- [ADR 0034](../adr/0034-syntax-highlighting-in-the-chat.md): completed chat code blocks are highlighted by lowlight, rendered without an HTML path.
- [ADR 0035](../adr/0035-session-titles.md): a session's name is the short title Claude Code writes in its transcript, kept as `session.title`.
- [ADR 0036](../adr/0036-live-playground-and-auto-mode.md): `make playground`, a live loop for agent-hub's own web app whose sessions run in Claude Code's `auto` mode.
- [ADR 0037](../adr/0037-learning-decisions-unpushed-notes-and-edits.md): a learning decision reads an unpushed inbox note from the hub checkout.
- [ADR 0038](../adr/0038-declared-environments-and-blocked-words.md): environments and services in `hub.json` and `hub.local.json`; the guard enforces blocked words, `access` is an instruction (proposed).
- [ADR 0039](../adr/0039-item-versions-and-server-writes-to-the-hub.md): item versions stored in agent-hub's database, recorded on read and before a write; the server writes a hub's items on Publish and Restore (proposed).
