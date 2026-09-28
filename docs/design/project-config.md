# Project config: `hub.json`

## Purpose

`hub.json` names a project: repos, tracker, authorship and branch rules, guard paths and the platform release. Every
generated file and `hub` command takes project values from it and nowhere else. This is its Phase 1 contract: format,
fields, validation, versioning and the two readers.

## Contract

### File

- Location: the hub root. Format: plain JSON (no comments, no trailing commas), UTF-8, readable by `json` on the Python
  3.9 standard library, so hooks and shell tools keep reading it with no dependency.
- Ownership: `seeded` ([hub-generator.md](hub-generator.md)). `hub init` writes it once; `hub sync` never writes it.
- Source of truth: the frozen Pydantic model `HubConfig` in core (area `agent_hub.core.hub_config`), proved by unit
  tests (valid and invalid documents, defaults, error paths).
- JSON Schema: exported with `HubConfig.model_json_schema()` and shipped as template data that the generator writes to
  the hub as a managed `hub.schema.json`; a unit test fails when it differs from a fresh export. Consumers: editors
  (`$schema`), the `config.schema` doctor rule ([hub-doctor.md](hub-doctor.md)) and the hooks' defaults test.

### Fields

| Key | Type | "req." or default | Read by |
|---|---|---|---|
| `schema_version` | integer, `1` | req. | every reader; see Versioning |
| `$schema` | string, e.g. `./hub.schema.json`; a declared root key | optional | editors only |
| `platform.version` | `^\d+\.\d+\.\d+$` | req. | shims (the release they run), `hub sync`, `hub doctor`, cloud setup |
| `project.name` | kebab-case (Rendered values) | req. | templates (plugin, marketplace names), `hub brief` |
| `project.hub_repo` | `owner/name` | req. | `hub run` (PR links), marketplace |
| `project.branch_prefix` | e.g. `jdoe/` (Rendered values) | req. | `hub worktree`, `hub run`, guard branch hint |
| `project.default_branch` | string | `main` | `hub worktree`, guard (no push to it) |
| `project.author_name`, `project.author_email` | strings | req. | cloud setup (git identity), `attribution.ai` rule |
| `tracker.kind` | closed list: `linear` | req. | selects the tracker adapter (Tracker, below) |
| `tracker.team` | string, the tracker's team key | req. | `hub next`, `hub run`, worktree names |
| `tracker.ready_label` | string | `agent-ready` | `hub next` |
| `tracker.failed_label` | string | `agent-failed` | `hub run` on failure |
| `repos[]` | list, at least one item | req. | launcher, worktrees, hooks, cloud setup |
| `repos[].dir` | kebab-case, unique across `repos` | req. | the sibling directory next to the hub |
| `repos[].github` | `owner/name` | req. | cloud setup, `hub run` |
| `repos[].role` | free string; `app` is the only known value | `app` | templates may branch on known roles |
| `repos[].check_fast`, `repos[].check` | shell commands | req. | stop gate (`check_fast`), `hub run` (`check`) |
| `guard.ask_before_edit` | list of paths | `[]` | guard: ask before an edit under them |
| `guard.deny_hosts` | list of host names | `[]` | guard: deny network calls to them |
| `guard.deny_paths` | list of paths | `[]` | guard: deny any read or edit under them |
| `modules` | object keyed by module id | `{}` | generator, commands, doctor (Modules) |
| `doctor.rules` | object keyed by rule id | `{}` | `hub doctor`; contract in [hub-doctor.md](hub-doctor.md) |

Unknown keys are an error at every object level (`extra="forbid"`), so a typo fails loudly.
Keys that start with `_` (such as `_comment`) are accepted and ignored at every level, the only way to annotate the
file: a before-validator on each object model drops them. The exported schema matches: every object carries
`"additionalProperties": false` and `"patternProperties": {"^_": {}}`, and the schema-equality test covers both.
Cross-field checks are model validators JSON Schema cannot express, so there an editor accepts what the CLI rejects:
unique `repos[].dir`, guard path roots, settings or `doctor.rules` entries of an unselected module.

### Rendered values

The model restricts values that land in shell, Make or YAML text, so templates need not escape them:

- `project.name`, `repos[].dir`: kebab-case `^[a-z0-9]+(-[a-z0-9]+)*$`, one path segment (never `/`, `..` or an
  absolute path). `tracker.team`: `^[A-Za-z0-9]+$`. `project.branch_prefix`: `^[A-Za-z0-9._-]+/$`.
- `project.hub_repo`, `repos[].github`: `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. `project.author_email`: one `@`, no space.
- `project.author_name` is free text, rendered only with format-specific quoting: `shlex.quote` in shell, the JSON
  encoder in JSON, a double-quoted escaped scalar in YAML; never into a Makefile. `repos[].check_fast` and
  `repos[].check` are commands by design: hooks and `hub run` read them at run time; no template renders them.
- `platform.version` matches `^\d+\.\d+\.\d+$` in the CLI and in the hooks' stdlib reader (a bad value counts as
  absent). Shims read it at run time (a stdlib `python3` one-liner, same pattern), never baked in at render time.
- Guard paths: relative to the workspace (the directory that holds the hub and its repos), normalized, POSIX
  separators, no `.` or `..` segment, not absolute; the first segment is a `repos[].dir` or the hub's directory name
  (checked by the CLI, which knows the hub root).

### Versioning

`schema_version` changes only on a breaking change (a key removed, renamed or retyped, or an optional key made
required); adding an optional key keeps it. The CLI loads in three steps: read `schema_version` and `platform.version`
leniently (plain JSON, no model), check them, then validate the whole file; so an older CLI facing a newer file reports
the version mismatch, not an unknown key. It supports exactly one version: on any other, `hub sync` writes nothing and
exits 1 and `config.schema` reports an error, both naming the fix (update the file, or run the pinned release through
the shim). Phase 1 ships version 1, so there is no migration command yet.

### Modules

Each entry's value is that module's settings object (`{}` when it has none); an unknown id is an error. A module adds
files, commands or doctor rules only when selected ([hub-generator.md](hub-generator.md)). Phase 1 modules: `cloud`
(cloud-session setup), `bench` (configuration benchmark), `contract-sync` (cross-repo contract recipe; its settings
name the source and target repos) and `marketplace` (the optional plugin marketplace).

### Readers

- **CLI**: validates with `HubConfig` and fails fast: exit 1 and one line per error, `hub.json: <json path>: <message>`.
  The hub's stdlib config loader is dropped once its last script moves into the CLI.
- **Hooks**: a defensive stdlib reader that never raises: a missing file, bad JSON or a wrong type falls back to the
  defaults above and the hook fails open. It ignores unknown and `_` keys.
- **Consistency**: `test_matches_schema_defaults_when_hub_json_minimal` (generator package, Phase 1) runs the hook
  template's reader on a minimal `hub.json` and compares its defaults with `HubConfig`'s.

### Tracker

`tracker.kind` selects the adapter behind the core port `TrackerClient` (list ready issues, get an issue, move its
state, add a label, comment). Linear is the first adapter, in its own adapter package, registered like any adapter
([ARCHITECTURE.md](../ARCHITECTURE.md)). Its API token comes from an environment variable, never from `hub.json`.
`hub next` and `hub run` are tested against its fake and contract suite.

### Project guards

Where each project guard of the Loki hub goes on adoption. "Extension file" is the seeded
`plugin/<project>/hooks/project_guard.py` ([hub-generator.md](hub-generator.md), Hooks).

| Guard today | Covered by |
|---|---|
| Exchange-host denylist | `guard.deny_hosts` |
| `app_db` destructive-SQL check | extension file (needs command parsing specific to the project) |
| Docker / service check | extension file; the base guard keeps its generic docker-volume rule |
| `_archive/` denial | `guard.deny_paths` |
| `tests/invariants/` ask-before-edit | `guard.ask_before_edit` |
| Brain write roles (curator vs implementer) | extension file (role logic is project policy) |

### Example (synthetic project)

```json
{"$schema": "./hub.schema.json", "schema_version": 1, "platform": {"version": "0.2.0"},
 "project": {"name": "demo", "hub_repo": "acme/demo-hub", "branch_prefix": "jdoe/",
             "author_name": "Jane Doe", "author_email": "jane@example.com"},
 "tracker": {"kind": "linear", "team": "DEM"},
 "repos": [{"dir": "demo-api", "github": "acme/demo-api", "check_fast": "make check-fast", "check": "make check"}],
 "guard": {"ask_before_edit": ["demo-api/docs/adr"]}, "modules": {"cloud": {}, "bench": {}}}
```

An existing hub migrates by adding `schema_version`, `platform` and, if it uses any, `modules`.

## Invariants

- `hub.json` is the only file with project values; templates and commands never hard-code them. No secret is a field.
- It stays readable by the Python 3.9 standard library `json` module, and nothing writes it after `hub init`.
- The CLI and `hub doctor` validate with the same model; the exported schema never drifts from it.
- A hook never fails because of `hub.json`.

## Decisions

- [ADR 0010](../adr/0010-hub-json-config-contract.md): JSON with a Pydantic model and an exported JSON Schema; TOML
  rejected (no reader in the 3.9 stdlib), YAML rejected (a dependency and implicit typing).
- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md) (`hub.json` is seeded) and
  [ADR 0013](../adr/0013-release-by-git-tags.md) (`platform.version` pins the CLI release).
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): the model lives in core; `TrackerClient` is a port because a
  swap is expected ([SPEC](../SPEC.md)).

## Open questions

- Schema migration: a `hub config migrate` command or a documented manual edit, decided when version 2 is needed.
- The exact `contract-sync` settings keys, fixed by the issue that implements the module.
