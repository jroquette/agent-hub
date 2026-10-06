# Project config: `hub.json`

## Purpose

`hub.json` names a project: repos, tracker, authorship and branch rules, guard paths and the platform release. Every
generated file and `hub` command takes project values from it and nowhere else. This is its Phase 1 contract.

## Contract

### File

- Location: the hub root. Format: plain JSON (no comments, no trailing commas), UTF-8, readable by `json` on the Python
  3.9 standard library, so hooks and shell tools keep reading it with no dependency.
- Ownership: `seeded` ([hub-generator.md](hub-generator.md)). `hub init` writes it once; `hub sync` never writes it.
- Source of truth: the frozen Pydantic model `HubConfig` (core, `agent_hub.core.hub_config`), proved by unit tests.
- JSON Schema: `HubConfig.model_json_schema()`, a managed `hub.schema.json` that the generator writes to the hub. It
  stays core package data (`agent_hub/core/hub_config/hub.schema.json`); the generator copies those bytes verbatim. A
  unit test fails on drift from a fresh export. Consumers: editors (`$schema`), [`config.schema`](hub-doctor.md), hooks.

### Fields

| Key | Type | "req." or default | Read by |
|---|---|---|---|
| `schema_version` | integer, `1` | req. | every reader; see Versioning |
| `$schema` | string, e.g. `./hub.schema.json`; a declared root key | optional | editors only |
| `platform.version` | `^[0-9]+\.[0-9]+\.[0-9]+$` | req. | shims (the release they run), `hub sync`, `hub doctor`, cloud setup |
| `project.name` | kebab-case (Rendered values) | req. | templates (plugin, marketplace names), `hub brief` |
| `project.hub_repo` | `owner/name` | req. | `hub run` (PR links), marketplace |
| `project.branch_prefix` | e.g. `jdoe/` (Rendered values) | optional, per developer ([developer-identity.md](developer-identity.md)) | `hub worktree`, `hub run`, guard branch hint, `AGENTS.md` |
| `project.default_branch` | `^S(?:/S)*$` (Rendered values) | `main` | the hub's own branch (CI, brief hub line, retro), default of `repos[].default_branch`, guard |
| `project.author_name`, `project.author_email` | strings | optional, per developer ([developer-identity.md](developer-identity.md)) | cloud setup (git identity), `attribution.ai` rule, marketplace owner, `AGENTS.md` |
| `project.conventions` | object of optional patterns `branch`, `commit_title`, `pr_title` (Rendered values); not in `hub.local.json` | `branch` `{prefix}{issue_lower}-{slug}`, `commit_title` `{type}({scope}): {summary} ({ISSUE})`; `pr_title` the effective `commit_title` | `hub worktree` and `hub run` (branch per repo; refused, before anything is created, when its branch is checked out in another worktree, when the existing task worktree is on another branch, or when the task folder is not a worktree); the run prompt; the PR title: a repo whose titles are configured (either layer sets `commit_title` or `pr_title`) parses its newest commit subject with `commit_title` and renders `pr_title`, and no match keeps today's title, records `title_unmatched` and warns; `AGENTS.md`: shapes and examples, and it notes when a repo's own `commit_title` also titles its PRs (no layer sets `pr_title`); kickoff: the branch shape only; doctor `instructions.refs`: skips the shapes and examples the Conventions block renders, plus each repo's effective branch example |
| `tracker.kind` | closed list: `linear` | req. | selects the tracker adapter (Tracker, below) |
| `tracker.team`, `tracker.teams` | a team key; or a list of them (≥ 1, unique ignoring case), the first the default; `hub run`/`hub worktree` match keys ignoring case, `features.tracker` exactly | exactly one of the two | `hub next` (each team, in order), `hub run`, worktree names, `features.tracker`, branch hints, `AGENTS.md` |
| `tracker.ready_label`, `tracker.failed_label` | strings | `agent-ready`, `agent-failed` | `hub next` (ready), `hub run` on failure (failed) |
| `tracker.transport` | closed list: `api`, `mcp`; `hub.local.json` may override it | `api` | `hub next`, `hub run` (adapter; Tracker, below) |
| `repos[]` | list, at least one item | req. | launcher, worktrees, hooks, cloud setup |
| `repos[].dir` | one path segment (Rendered values), unique across `repos` ignoring case | req. | the sibling directory next to the hub |
| `repos[].github` | `owner/name` | req. | cloud setup, `hub run` |
| `repos[].role` | free string; `app` is the only known value | `app` | templates may branch on known roles |
| `repos[].check_fast`, `repos[].check` | shell commands | req. | stop gate (`check_fast`), `hub run` (`check`) |
| `repos[].conventions` | like `project.conventions`; a project `pr_title` its `commit_title` cannot fill is reported at `project.conventions.pr_title`, naming each such `repos[<i>].conventions.commit_title` | per key the project's, else today's shape; `pr_title`, else the repo's effective `commit_title` | as `project.conventions`, for the repo |
| `repos[].default_branch` | like `project.default_branch` | `project.default_branch` | `hub worktree`, `hub run` (base, `--base`), `hub brief`, retro CI, guard (union of `main`, `master` and every configured default branch, plus the root `hub.json`'s when `$HUB_CONFIG` points elsewhere, from any cwd); `AGENTS.md` names it only when set |
| `guard.ask_before_edit` | list of paths | `[]` | guard: ask before an edit under them |
| `guard.deny_hosts` | list of host names | `[]` | guard: deny network calls to them |
| `guard.deny_paths` | list of paths | `[]` | guard: deny any read or edit under them |
| `modules` | object keyed by module id | `{}` | generator, commands, doctor (Modules) |
| `doctor.rules` | object keyed by rule id | `{}` | `hub doctor`; contract in [hub-doctor.md](hub-doctor.md) |

Unknown keys are an error at every object level; keys starting with `_` (such as `_comment`) are accepted and ignored at
every level, and the exported schema says the same ([ADR 0010](../adr/0010-hub-json-config-contract.md)). Cross-field
checks are model validators JSON Schema cannot express, so there an editor accepts what the CLI rejects: unique
`repos[].dir`, team keys unique ignoring case, guard path roots, `doctor.rules` entries of an unselected module,
`contract-sync` repos, an explicit `pr_title` part (not `{ISSUE}`) the repo's effective `commit_title` lacks.

### Rendered values

The model restricts rendered values: safe unquoted in shell, Make and Markdown. YAML templates double-quote placeholders
(`on`, `NO`, `1.0` would retype). Brain frontmatter lists repo dirs unquoted: readers load it without type resolution.
`S` is a safe segment, `[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*`: no leading `-` or `.`, no `..`, no trailing punctuation,
no `_` separator (hooks match branches with Python's `re`: exponential backtracking if a separator extends a segment).

- `project.name`: kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`. `repos[].dir`: `^S$`, unique ignoring case (`tradeSentinel`).
  `project.hub_repo`, `repos[].github`: `^S/S$`. `project.branch_prefix`: `^S/$`. `guard.deny_hosts`: `.`-joined DNS
  labels `[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?`. `project.default_branch`, `repos[].default_branch`: `^S(?:/S)*$`.
  `tracker.team` and each `tracker.teams` item: `^[A-Za-z0-9]+$`. `project.author_email`:
  `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$`. Other free text has no control character (`\x00-\x1f`, `\x7f`); `author_name`
  is rendered only with format quoting (`shlex.quote`, JSON encoder, escaped YAML scalar), never into a Makefile;
  `check_fast` and `check` are read at run time, never rendered.
- `platform.version` matches `^[0-9]+\.[0-9]+\.[0-9]+$` in the CLI and in the hooks' stdlib reader (a bad value counts
  as absent). Shims read it at run time (a stdlib `python3` one-liner, same pattern), never baked in at render time.
- Guard paths: relative to the workspace (the directory holding the hub and its repos), normalized, `/`-separated, not
  absolute; segments are printable ASCII without space or `\`, never `.` or `..`. The first is a `repos[].dir` or `@hub`
  (the hub, whatever its checkout is called; `@` cannot start a `dir`); `guard.deny_paths` may also start with another
  workspace directory (Loki's `_archive`). Hooks resolve `@hub` to the hub root holding the hook file.
- Conventions: each pattern ≤ 120 characters, each placeholder at most once. `branch`: `{prefix}` (the developer's
  effective branch prefix: `project.branch_prefix`, or `hub.local.json`), `{ISSUE}` (the issue id, e.g. `DEM-7`) or
  `{issue_lower}` (the same lowercased; one of the two needed), `{slug}` (the worktree name's description; empty, it
  drops one `-`, `_`, `.` or `/` before it), literals `[A-Za-z0-9._/-]`; it must render to a valid branch. Titles:
  `{ISSUE}`, the commit's parts `{type}`, `{scope}`, `{summary}` (needed), placeholders separated by a literal; a
  literal holds no control, format or line-separator character (Unicode Cc, Cf, Zl, Zp), backtick or brace.

### Versioning

`schema_version` changes only on a breaking change (a key removed, renamed or retyped, or an optional key made
required); adding an optional key keeps it. The CLI reads `platform.version` and `schema_version` leniently (plain JSON,
no model) and checks them in that order before validating the whole file, so an older CLI facing a newer file reports
the pin mismatch (whose fix settles both), not an unknown key. It supports one schema version: on any other, `hub sync`
writes nothing and exits 1 ([hub-sync.md](hub-sync.md)) and `config.schema` reports an error, both naming the fix
(update the file, or run the pinned release through the shim). Phase 1 ships version 1, so there is no migration command yet.

### Modules

Each entry's value is that module's settings object; an unknown id is an error. A module adds files, commands or doctor
rules only when selected ([hub-generator.md](hub-generator.md)). Phase 1 modules: `cloud` (cloud-session setup), `bench`
(configuration benchmark) and `marketplace` (the optional plugin marketplace) take `{}` only; `contract-sync`
(cross-repo contract recipe) takes `{"source": "<repo dir>", "target": "<repo dir>"}`: both required, each a
`repos[].dir`, and different (cross-field checks, at `modules.contract-sync.<key>`). `_` keys are ignored.

### Readers

- **CLI**: validates with `HubConfig` and fails fast: exit 1 and one line per error, `hub.json: <json path>: <message>`;
  `hub.local.json: <json path>: <message>` for the developer's file ([developer-identity.md](developer-identity.md)).
- **Hooks**: a defensive stdlib reader that never raises (`plugin/hub-workflow/hooks/stdlib_reader.py`; its defaults on
  a minimal `hub.json` match `HubConfig`'s in `test_hub_json_reader.py`): a missing file, bad JSON or a wrong type gives
  the defaults; the hook fails open. It ignores unknown and `_` keys; a bad `repos[].default_branch` inherits; a
  `tracker.teams` that is not a non-empty list of non-empty strings counts as absent. No hook reads `conventions`.

### Tracker

`tracker.kind` and `tracker.transport` pick the `TrackerClient` adapter: `api` is `LinearGraphqlTrackerClient` (key only
from `LINEAR_API_KEY`, at call time, never `hub.json`); `mcp` is `McpTrackerClient`, short `claude -p` calls to the user's
Linear MCP server ([ADR 0015](../adr/0015-linear-mcp-tracker-transport.md)). Both pass `TrackerClientContract`.
With several teams, `hub next` calls `list_ready` once per team, in order.

Where each project guard of the Loki hub goes on adoption: [hub-adopt.md](hub-adopt.md#project-guards).

### Example (synthetic project)

```json
{"$schema": "./hub.schema.json", "schema_version": 1, "platform": {"version": "0.2.0"},
 "project": {"name": "demo", "hub_repo": "acme/demo-hub", "branch_prefix": "jdoe/",
             "author_name": "Jane Doe", "author_email": "jane@example.com"},
 "tracker": {"kind": "linear", "team": "DEM"},
 "repos": [{"dir": "demo-api", "github": "acme/demo-api", "check_fast": "make check-fast", "check": "make check"}],
 "guard": {"ask_before_edit": ["demo-api/docs/adr"]}, "modules": {"cloud": {}, "bench": {}}}
```

An existing hub migrates by adding `schema_version`, `platform` and, if it uses any, `modules`. Guard paths rooted at a
repo stay as they are; one rooted at the hub's directory name is rewritten as `@hub/…`.

## Invariants

- `hub.json` is the only committed file of project values; no template or command hard-codes one. No field is a secret.
- It stays readable by the Python 3.9 standard library `json` module, and nothing writes it after `hub init`.
- The CLI and `hub doctor` validate with the same model; the exported schema never drifts from it.
- A hook never fails because of `hub.json`.

## Decisions

- [ADR 0010](../adr/0010-hub-json-config-contract.md): JSON with a Pydantic model and an exported JSON Schema; TOML
  rejected (no reader in the 3.9 stdlib), YAML rejected (a dependency and implicit typing).
- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md) (`hub.json` is seeded) and
  [ADR 0013](../adr/0013-release-by-git-tags.md) (`platform.version` pins the CLI release).
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): the model lives in core; `TrackerClient` is a port because a
  swap is expected ([SPEC](../SPEC.md)); [ADR 0014](../adr/0014-tracker-port-linear-graphql.md): the GraphQL adapter.

## Open questions

- Schema migration: a `hub config migrate` command or a documented manual edit, decided when version 2 is needed.
