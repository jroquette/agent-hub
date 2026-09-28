# 0012. The hub CLI subsumes the hub scripts

- Status: proposed
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

A hand-made hub carries its own logic as stdlib scripts: a worktree helper, a session brief, an issue-to-PR runner, a
benchmark, a config lint, a feature-tracker check, transcript tools and a Makefile that calls them. Each hub has its own
copy, several copies have no tests, and a fix made in one hub does not reach the others. The workflow plugin (skills,
agents and hooks) is copied the same way. Phase 1 generates hubs for N projects. Where does the hub logic live, what
stays a file inside the generated hub, and how does the plugin reach the sessions that run in the hub?

## Considered Options

- **Logic in the `hub` CLI**: the scripts become tested commands in agent-hub; the hub keeps files, config and thin
  shims.
- **Generated stdlib scripts**: the scripts become managed templates, written into every hub as they are today.
- **A hybrid**: some commands in the CLI, the rest generated as scripts, decided script by script.

## Decision Outcome

Chosen option: **logic in the `hub` CLI**, because it gives N hubs one implementation that is tested under agent-hub's
gates and hexagonal architecture, and a fix reaches every hub through a release instead of a copy per hub.

- Each hub script maps to a `hub` command (for example `hub worktree`, `hub brief`, `hub next`, `hub run`, `hub agent`),
  to a `hub doctor` rule, to an optional module, or stays a hub file with a stated reason. The full mapping is the
  Commands table of the hub generator design. Scripts that Phase 2 will redesign (the transcript mining, recall and
  retro metrics) stay hub files until then.
- The launcher and the Makefile targets that map to a command become shims: each runs the `hub` release pinned in
  `hub.json` through uv ([ADR 0013](0013-release-by-git-tags.md)). When uv is missing, the shim prints how to install
  it and exits 127, to tell "tool missing" apart from a failing command. When uv is present but the pinned release
  cannot be fetched, it prints which access is missing (the credential, or the repository not attached) and exits 1.
- Skill and agent text that names a `hub` command is managed template content, so it changes in the same release as
  the command it names.
- Each script is migrated only after characterization tests pin its current behavior; the old script is deleted in the
  template release where its command lands.
- **Hooks are the exception.** They stay managed stdlib scripts that run on Python 3.9, read `hub.json` directly and
  fail open, so a misconfigured hub never breaks a session. They do not call the CLI: a CLI start-up on every tool call
  would add latency, and the guard must keep working when the CLI is missing. The only call allowed is the SessionStart
  hook, which runs once per session: it calls the pinned `hub brief` the same way the shims do, with a short timeout,
  and falls back to a small stdlib brief when uv or the release is unavailable, the call fails or it times out (the
  first run of a new version may be spent filling the uv cache).
- Project-specific guard rules go in a seeded extension file that the base guard consults after its own checks. The
  guard hardens that call:
  - it resolves the file from the hub root that holds the hook file itself; `CLAUDE_PROJECT_DIR`, the current
    directory and the tool input never choose which file is loaded, and a `CLAUDE_PROJECT_DIR` that points elsewhere
    is ignored for loading;
  - a base `deny` is final: the extension runs only when the base verdict is not `deny`, and its answer can only
    tighten the verdict (allow to ask or deny, ask to deny);
  - it runs the extension in a child `python3` process with a timeout, not with `signal.alarm`, which only works on the
    main thread of a POSIX process; the child loads the file, reads the config with the same stdlib reader and gets
    the event on stdin;
  - a timeout, an import error or any exception, `BaseException` included (so `SystemExit` too), gives the tool call
    `ask` with the cause as the reason, so a broken or slow project guard never silently allows a call;
  - its built-in ask-before-edit covers the guard's own inputs: the whole `plugin/<project>/hooks/` directory (the
    extension and anything it imports), `.claude/settings*.json`, `hub.lock` and `hub.json` (which holds the `guard`
    block), so an agent cannot weaken the guard without the owner's confirmation.
- **The plugin lives in the hub.** The base workflow plugin is written into every hub as managed files under
  `plugin/hub-workflow/`, with the same name in every hub; a seeded `plugin/<project>/` holds the project's own skills,
  agents and guard extension. The generated `.claude/` wiring is part of the templates, because cloud sessions do not
  install plugins declared by the repository: `.claude/agents/` and `.claude/skills/` are managed directories holding
  one link per agent or skill of both plugins, and `.claude/settings.json` carries the hooks block. A new entry under
  `plugin/<project>/` gets its link at the next `hub sync`. A marketplace file stays optional.

### Consequences

- Good: one tested implementation; hubs differ only in `hub.json`, extension files and project-owned content.
- Good: the untested scripts gain tests as a precondition of their migration.
- Good: the hooks keep their latency and their independence from the CLI.
- Bad: every session that uses a command needs uv, Python 3.14 and read access to agent-hub, including cloud sessions
  ([ADR 0013](0013-release-by-git-tags.md) pins the version and lists the credentials).
- Bad: the guard extension runs under a time bound and the guard's inputs are ask-before-edit paths, which adds a
  confirmation whenever the owner changes them.
- Bad: the hooks remain stdlib code outside the hexagonal packages, with their own config reader and their own tests.
- Neutral: generated stdlib scripts were rejected because they keep N copies whose only test is the golden comparison
  and they cannot share code with the CLI; the hybrid was rejected because a per-script rule would leave the boundary
  undecided for every new script.

## More Information

- [design/hub-generator.md](../design/hub-generator.md): the Commands table, the shims, the hooks and the plugin wiring.
- [ADR 0008](0008-cli-as-composition-root.md): `cli` wires the adapters the new commands need.
- [ADR 0009](0009-hub-sync-by-file-ownership.md): managed and seeded files.
