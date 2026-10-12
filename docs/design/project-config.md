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
| `platform.repository` | `git+https://` repository root (Rendered values) | `git+https://github.com/jroquette/agent-hub` | shims, SessionStart, cloud setup, CI credential step (at run time); pin-mismatch command. Tokens only on exactly `https://github.com/`: CI maps `AGENT_HUB_READ_TOKEN` there alone, and cloud setup's `GH_TOKEN` helper answers for `github.com` alone; another host needs the repository attached or its own credential (follow-up) |
| `project.name` | kebab-case (Rendered values) | req. | templates (plugin, marketplace names), `hub brief` |
| `project.hub_repo` | `owner/name` | req. | `hub run` (PR links), marketplace |
| `project.branch_prefix` | e.g. `jdoe/` (Rendered values) | optional, per developer ([developer-identity.md](developer-identity.md)); `hub setup` writes it to `hub.local.json` | `hub worktree`, `hub run`, `hub start`, guard branch hint, `AGENTS.md` |
| `project.default_branch` | `^S(?:/S)*$` (Rendered values) | `main` | the hub's own branch (CI, brief hub line, retro), default of `repos[].default_branch`, guard |
| `project.author_name`, `project.author_email` | strings | optional, per developer ([developer-identity.md](developer-identity.md)) | cloud setup (git identity), `attribution.ai` rule, marketplace owner, `AGENTS.md` |
| `project.conventions` | object of optional patterns `branch`, `commit_title`, `pr_title` (Rendered values); not in `hub.local.json` | `branch` `{prefix}{issue_lower}-{slug}`, `commit_title` `{type}({scope}): {summary} ({ISSUE})`; `pr_title` the effective `commit_title` | `hub worktree`, `hub run` and `hub start` (branch per repo; refused, before anything is created, when its branch is checked out in another worktree, when the existing task worktree is on another branch, or when the task folder is not a worktree); the run prompt; the PR title: a repo whose titles are configured (either layer sets `commit_title` or `pr_title`) parses its newest commit subject with `commit_title` and renders `pr_title`, and no match keeps today's title, records `title_unmatched` and warns; `AGENTS.md`: the project's shapes and examples, then, when a repo sets `repos[].conventions`, one line naming at most three such repos and how many more (their patterns stay in `hub.json`) and saying that a `pr_title` neither layer sets follows the repo's own `commit_title`; kickoff: the branch shape only; doctor `instructions.refs`: skips, as valid references whether rendered or not, the project's shapes and examples, each repo's own shapes, and each repo's effective branch shape and example |
| `tracker.kind` | closed list: `linear` | req. | selects the tracker adapter (Tracker, below) |
| `tracker.team`, `tracker.teams` | a team key; or a list of them (≥ 1, unique ignoring case), the first the default; `hub run`/`hub worktree` match keys ignoring case, `features.tracker` exactly | exactly one of the two | `hub next` (each team, in order), `hub run`, `hub start` (exact upper-case `<TEAM>-<n>`), worktree names, `features.tracker`, branch hints, `AGENTS.md` |
| `tracker.ready_label`, `tracker.failed_label` | strings | `agent-ready`, `agent-failed` | `hub next` (ready), `hub run` on failure (failed) |
| `tracker.states.started`, `tracker.states.review` | strings; an object with only these keys; not in `hub.local.json` | `In Progress`, `In Review` | `hub start` reads `started`: the state a fresh start, or a resume of an unstarted issue, moves to; `review`: the state `hub run` (success report and dry run) and `hub ship` move the issue to |
| `tracker.transport` | closed list: `api`, `mcp`; `hub.local.json` may override it | `api` | `hub next`, `hub run`, `hub start` (adapter; Tracker, below), `hub setup` (its `tracker` item) |
| `repos[]` | list, at least one item | req. | launcher, worktrees, `hub setup` (clone or fetch each), `hub start`, hooks, cloud setup |
| `repos[].dir` | one path segment (Rendered values), unique across `repos` ignoring case | req. | the sibling directory next to the hub |
| `repos[].github` | `owner/name` | req. | cloud setup, `hub run`, `hub setup` (clone URL over the scheme of the hub's `origin`) |
| `repos[].role` | free string; `app` is the only known value | `app` | templates may branch on known roles |
| `repos[].check_fast`, `repos[].check` | shell commands; `check_fast` may be absent, empty or blank (no Stop gate: `config.stop_gate` warns); `check` holds a non-space character | `check` req. | stop gate (`check_fast`), `hub run` (`check`, also step 3 when there is no `check_fast`), `hub doctor` (`repos.agents` fix, escaped) |
| `repos[].check_fast_timeout` | strict integer 1–160 (seconds), within the stop gate's 160 s budget | 150 | stop gate |
| `repos[].conventions` | like `project.conventions`; a project `pr_title` its `commit_title` cannot fill is reported at `project.conventions.pr_title`, naming each such `repos[<i>].conventions.commit_title` | per key the project's, else today's shape; `pr_title`, else the repo's effective `commit_title` | as `project.conventions`, for the repo; `AGENTS.md` names the repo, not its patterns |
| `repos[].default_branch` | like `project.default_branch` | `project.default_branch` | `hub worktree`, `hub run` (base, `--base`), `hub start`, `hub brief`, retro CI, guard (union of `main`, `master` and every configured default branch, plus the root `hub.json`'s when `$HUB_CONFIG` points elsewhere, from any cwd); `AGENTS.md` names it only when set |
| `guard.ask_before_edit` | list of paths | `[]` | guard: ask before an edit under them |
| `guard.deny_hosts` | list of host names | `[]` | guard: deny network calls to them |
| `guard.deny_paths` | list of paths | `[]` | guard: deny any read or edit under them |
| `guard.infra` | object; not in `hub.local.json` | absent | hooks' config reader (validated); present, even `{}`, it turns on the guard's infra classification (the [SPEC](../SPEC.md)'s infra guard; absent, the guard's fixed infra rule); an unknown key under it (other than `_` keys) is reported by the reader as unusable (`InfraSection.problem`; the CLI rejects it), and the guard then denies every infra command |
| `guard.infra.allow` | list of Python `re` patterns (Infra patterns, below) | `[]` | hooks' config reader; guard: the allowed environments; a part or call naming a covered tool must match one unless it is a local-only form, and what passes is asked instead when the command holds a character other than ASCII letters, digits, space, tab and `_ - . / : = @ , + %` (joined by `;`, `&&`, `||`, `|`, newline), or a word that always asks (a shell, `python*`, `perl`, `node`, `ruby`, `php`, `xargs`, `eval`, `exec`, `source`, `.` as a command, `env -i`/`-u`, `sudo`, `su`, `doas`, a lone `--`, `parallel`, a `sed` that runs its text: the [SPEC](../SPEC.md)'s infra guard), or a part that sets the environment twice (a second `AWS_PROFILE=` or `--profile`, …, also under two spellings such as `AWS_PROFILE=` and `--profile`), or an environment selector the guard knows (`AWS_PROFILE=`, `AWS_DEFAULT_PROFILE=`, `KUBECONFIG=`, `KUBE_CONTEXT=`, `HELM_KUBECONTEXT=`, `TF_WORKSPACE=`, `TF_DATA_DIR=`, `TF_CLI_ARGS[_*]=`, `PULUMI_BACKEND_URL=`, `AWS_CONFIG_FILE=`, `AWS_SHARED_CREDENTIALS_FILE=`, `AWS_ROLE_ARN=`, `CDK_DEFAULT_ACCOUNT=` anywhere, and any other word holding one of these names as an identifier, such as `export AWS_PROFILE` or `read KUBECONFIG`; `--profile`, `--aws-profile`, `--context`, `--kube-context`, `--cluster`, `--server`, `--user`, `--kubeconfig`, `--kube-apiserver`, `-chdir`, `--cwd`, `--stack`, `-s`, `--stage`, `--workspace`, `-var-file`, `-backend-config`, pulumi's `-C`, as `--x v` or `--x=v`, in a part naming a covered tool) that no match holds whole, so a pattern must match the whole setting, not its value alone, or a command that changes a tool's configuration (`aws configure set|import`, `kubectl config set-context|use-context|set-cluster|set-credentials|use|set|rename-context|delete-context`, `terraform workspace select|new`, `pulumi stack select`); a match that overlaps a quoted region (`'…'`, `"…"`, `$'…'`) neither allows nor denies |
| `guard.infra.prod_markers` | list of Python `re` patterns (Infra patterns, below) | `[]` | hooks' config reader; guard: the production markers; a match anywhere in a command naming a covered tool denies it |
| `modules` | object keyed by module id | `{}` | generator, commands, doctor (Modules) |
| `doctor.rules` | object keyed by rule id | `{}` | `hub doctor`; contract in [hub-doctor.md](hub-doctor.md) |

Unknown keys are an error at every object level; `_` keys (such as `_comment`) are accepted and ignored at every level,
and the exported schema says the same ([ADR 0010](../adr/0010-hub-json-config-contract.md)). Cross-field checks are
model validators JSON Schema cannot express, so an editor accepts what the CLI rejects: unique `repos[].dir`, team keys
unique ignoring case, guard path roots, `doctor.rules` entries of an unselected module, `contract-sync` repos, a
`pr_title` part (not `{ISSUE}`) the repo's effective `commit_title` lacks, `guard.infra` patterns that compile.

### Rendered values

Rendered values are safe unquoted in shell, Make and Markdown; YAML templates double-quote them (`on`, `NO` would
retype); brain frontmatter lists repo dirs unquoted (no type resolution). A safe segment `S` is
`[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*`: no leading `-`/`.`, `..`, trailing punctuation or `_` separator (backtracking).

- `project.name`: kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`. `repos[].dir`: `^S$`, unique ignoring case (`tradeSentinel`).
  `project.hub_repo`, `repos[].github`: `^S/S$`. `project.branch_prefix`: `^S/$`. `guard.deny_hosts`: `.`-joined DNS
  labels `[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?`. `project.default_branch`, `repos[].default_branch`: `^S(?:/S)*$`.
  `tracker.team` and each `tracker.teams` item: `^[A-Za-z0-9]+$`. `project.author_email`:
  `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$`. Other free text has no control character (`\x00-\x1f`, `\x7f`); `author_name`
  is rendered only with format quoting (`shlex.quote`, JSON encoder, escaped YAML scalar), never into a Makefile;
  `check_fast` and `check` are read at run time, never rendered.
- `platform.version` matches `^[0-9]+\.[0-9]+\.[0-9]+$` in the CLI and the hooks' stdlib reader (a bad value counts as
  absent). `platform.repository` matches `^git\+https://H(?:/S)+$` (`H` as `guard.deny_hosts`), ≤ 200 characters, as
  written: no credential, port, query, fragment, `@ref` or trailing `/`. Read at run time, never baked in; a bad one
  stops each reader (SessionStart: mini brief), never echoed.
- Guard paths: relative to the workspace (the directory holding the hub and its repos), normalized, `/`-separated, not
  absolute; segments are printable ASCII without space or `\`, never `.` or `..`. The first is a `repos[].dir` or `@hub`
  (the hub, whatever its checkout is called; `@` cannot start a `dir`); `guard.deny_paths` may also start with another
  workspace directory (Loki's `_archive`). Hooks resolve `@hub` to the hub root holding the hook file. Loki's guards on
  adoption: [hub-adopt.md](hub-adopt.md#project-guards).
- Conventions: each pattern ≤ 120 characters, each placeholder at most once. `branch`: `{prefix}` (the developer's
  effective branch prefix: `project.branch_prefix`, or `hub.local.json`), `{ISSUE}` (the issue id, e.g. `DEM-7`) or
  `{issue_lower}` (the same lowercased; one of the two needed), `{slug}` (the worktree name's description; empty, it
  drops one `-`, `_`, `.` or `/` before it), literals `[A-Za-z0-9._/-]`; it must render to a valid branch. Titles:
  `{ISSUE}`, the commit's parts `{type}`, `{scope}`, `{summary}` (needed), placeholders separated by a literal; a
  literal holds no control, format or line-separator character (Unicode Cc, Cf, Zl, Zp), backtick or brace.
- Infra patterns: non-blank, no control character, compiling with Python's `re` (no repeat count overflow such as
  `a{4294967296}`, no too-deep nesting); searched (`re.search`) with no flags in Python 3.9 `re` syntax (the hooks run
  on the system `python3`). Avoid nested quantifiers: `(a+)+$` takes over a second on a 25-character input. Bound an
  environment pattern by a space or tab, as a whole word, `(?<![^ \t])--profile[= ]demo-dev(?![^ \t])`, and an
  `AWS_PROFILE` prefix by the part's start, `^[ \t]*AWS_PROFILE=demo-dev(?=[ \t])`; not `\b` (it also matches
  `demo-dev.x`, `demo-dev{,-admin}` or a redirection target `>--profile=demo-dev`) or `\s` (it also matches a carriage
  return, a vertical tab or a no-break space, which the shell does not split on).

### Versioning

`schema_version` changes only on a breaking change (a key removed, renamed or retyped, or an optional key made
required); adding an optional key keeps it. The CLI reads `platform.version` and `schema_version` leniently (plain JSON,
no model), in that order, before validating the file, so an older CLI facing a newer file reports the pin mismatch
(whose fix settles both), not an unknown key. On another schema version, `hub sync` writes nothing and exits 1
([hub-sync.md](hub-sync.md)) and `config.schema` errors, both naming the fix (update the file, or use the shim).

### Modules

Each entry's value is that module's settings object; an unknown id is an error. A module adds files, commands or doctor
rules only when selected ([hub-generator.md](hub-generator.md)). `cloud` (cloud-session setup), `bench` (configuration
benchmark) and `marketplace` (plugin marketplace) take `{}` only; `contract-sync` (cross-repo contract recipe) takes
`{"source": "<repo dir>", "target": "<repo dir>"}`, two different `repos[].dir` (at `modules.contract-sync.<key>`).

### Readers

- **CLI**: validates with `HubConfig` and fails fast: exit 1 and one line per error, `hub.json: <json path>: <message>`;
  `hub.local.json: <json path>: <message>` for the developer's file ([developer-identity.md](developer-identity.md)).
- **Hooks**: a defensive stdlib reader that never raises (`plugin/hub-workflow/hooks/stdlib_reader.py`; its defaults on
  a minimal `hub.json` match `HubConfig`'s in `test_hub_json_reader.py`): a missing file, bad JSON or a wrong type gives
  the defaults; the hook fails open. It ignores unknown and `_` keys, except under `guard.infra` (a wrong type, an
  unusable item or an unknown key sets `InfraSection.problem`). A bad `repos[].default_branch` inherits; a bad
  `tracker.teams` (not a non-empty list of non-empty strings) counts as absent. No hook reads `conventions`.

### Tracker

`tracker.kind` and `tracker.transport` pick the `TrackerClient` adapter: `api` is `LinearGraphqlTrackerClient` (key only
from `LINEAR_API_KEY`, at call time, never `hub.json`); `mcp` is `McpTrackerClient`, short `claude -p` calls to the user's
Linear MCP server ([ADR 0015](../adr/0015-linear-mcp-tracker-transport.md)). Both pass `TrackerClientContract`. `hub
next` calls `list_ready` once per team, in order; `hub start` calls `get_issue`, then `move_state` (`only_if_unstarted`
on a resume; [hub-start.md](hub-start.md)).

### Example (synthetic project)

```json
{"$schema": "./hub.schema.json", "schema_version": 1, "platform": {"version": "0.2.0"}, "tracker": {"kind": "linear", "team": "DEM"},
 "project": {"name": "demo", "hub_repo": "acme/demo-hub", "branch_prefix": "jdoe/", "author_name": "Jane Doe", "author_email": "jane@example.com"},
 "repos": [{"dir": "demo-api", "github": "acme/demo-api", "check_fast": "make check-fast", "check_fast_timeout": 120, "check": "make check"}],
 "guard": {"ask_before_edit": ["demo-api/docs/adr"]}, "modules": {"cloud": {}, "bench": {}}}
```

## Invariants

- `hub.json` is the only committed file of project values; no template or command hard-codes one; no field is a secret.
  It stays readable by Python 3.9's `json`, nothing writes it after `hub init`, and a hook never fails because of it.
- The CLI and `hub doctor` validate with the same model; the exported schema never drifts from it.

## Decisions

- [ADR 0010](../adr/0010-hub-json-config-contract.md): JSON, a Pydantic model and an exported schema; not TOML (no 3.9
  stdlib reader) nor YAML (a dependency, implicit typing). [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md):
  `hub.json` is seeded. [ADR 0013](../adr/0013-release-by-git-tags.md): `platform.version` pins the CLI release.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): the model lives in core; `TrackerClient` is a port because a
  swap is expected ([SPEC](../SPEC.md)); [ADR 0014](../adr/0014-tracker-port-linear-graphql.md): the GraphQL adapter.

## Open questions

- Schema migration: a `hub config migrate` command or a documented manual edit, decided when version 2 is needed.
