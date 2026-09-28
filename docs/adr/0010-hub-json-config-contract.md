# 0010. hub.json as the versioned config contract

- Status: accepted
- Date: 2026-09-28
- Deciders: José Henrique Roquette

## Context and Problem Statement

A hub keeps every project value (project name, tracker, repos, gate commands, guard paths) in one file, `hub.json`, at
its root. Today the file has no version and no schema, and it is read by two hand-written stdlib readers: the hub
scripts' reader fails fast on a missing key, while the hooks' reader defaults every field and never raises, because a
hook must never break a session. In Phase 1 the `hub` CLI renders templates from this file, so it becomes the product's
public contract. The hooks keep running on the system `python3`, which is 3.9 on the owner's machine. Which format and
validation model does the config use, and how do the CLI and the hooks read it?

## Considered Options

- **JSON validated by a Pydantic model in core, with an exported JSON Schema.**
- **TOML** (`hub.toml`).
- **YAML** (`hub.yaml`).
- **A Python config module** (`hub_config.py`) that the tools import.

## Decision Outcome

Chosen option: **JSON validated by a Pydantic model in core, with an exported JSON Schema**, because JSON is the only
one of the four that the Python 3.9 standard library reads with no dependency, so the hooks keep working unchanged,
while the CLI still gets strict, typed validation.

- The file stays plain JSON (no comments, no trailing commas), UTF-8, readable by `json` on Python 3.9. `hub init`
  writes it; `hub sync` never does ([ADR 0009](0009-hub-sync-by-file-ownership.md): it is seeded).
- A frozen Pydantic model `HubConfig` in core (proposed module `agent_hub.core.hub_config`) is the source of truth. The
  JSON Schema is exported from it; a unit test fails when the shipped schema file differs from the export. The
  generator writes that schema as a managed `hub.schema.json`, and `hub.json` may name it in `$schema`, an optional
  string key declared at the root of the model, so editors validate as the owner types.
- New keys:
  - `schema_version` (integer, required, starting at `1`), bumped only by a breaking change: removing, renaming or
    retyping a key, or making an optional key required. Adding an optional key does not bump it. The CLI knows one
    current version; `hub sync` and `hub doctor` report any other version as an error that names the fix. The CLI
    reads `platform.version` and `schema_version` leniently first and checks them in that order, and only then
    validates the whole file, so an older CLI facing a newer file reports the version mismatch instead of an unknown
    key. The pin is checked first because its fix, running the pinned release, also settles a schema mismatch.
  - `platform.version`: the `hub` CLI release the hub is generated with ([ADR 0013](0013-release-by-git-tags.md)).
  - `modules`: an object keyed by module id whose value holds that module's settings; an unknown id fails.
- Unknown keys are forbidden at every object level, so a typo fails loudly, as it does for the canonical event. Keys
  starting with `_` (such as `_comment`) are accepted and ignored at every level, which keeps the comment convention:
  a before-validator on each object model drops them before validation. The exported schema says the same at every
  object level, `"additionalProperties": false` with `"patternProperties": {"^_": {}}`, and the schema-equality test
  covers those keywords, so editors and the CLI agree on every per-object check. Cross-field checks (settings of an
  unselected module, guard paths that must start with a declared repo or `@hub`) are model validators that JSON Schema
  cannot express; there an editor accepts a document the CLI rejects. [project-config.md](../design/project-config.md)
  lists them.
- Values that templates render into shell, Make or YAML text are restricted by patterns, set loose enough to accept
  the values the existing hubs already use: a repo `dir` is one safe path segment (`^[A-Za-z0-9._-]+$`, not `.` or
  `..`), so a mixed-case directory such as `tradeSentinel` is valid while a `/`, a space or a quote is not.
- Guard paths are relative to the workspace that holds the hub and its repos. A path inside the hub starts with the
  fixed token `@hub`, never with the hub checkout's directory name, which differs between clones, worktrees and
  cloud sessions; `@` is not allowed in a repo `dir`, so the token cannot collide with a repo. Paths rooted at a repo
  need no change; a path written with the hub's directory name migrates to `@hub/…` by hand.
- Two readers, one contract. CLI code validates with `HubConfig` and fails fast: exit 1 and one line per error with its
  JSON path. The hooks keep a defensive stdlib reader that never raises and falls back to defaults; a Phase 1 test
  compares that reader's defaults with the model's so the two cannot drift.

### Consequences

- Good: migrating an existing hub is adding three keys; no reader has to learn a new format.
- Good: one model validates in the CLI, in `hub doctor` and, through the exported schema, in editors.
- Good: `schema_version` gives the CLI an explicit way to refuse a config it does not understand, instead of guessing.
- Bad: JSON has no comments; the `_`-prefixed keys are the only way to annotate the file.
- Bad: the hooks' reader duplicates the defaults in stdlib code; only the consistency test keeps it honest.
- Neutral: TOML was rejected because Python 3.9 has no `tomllib`, so the hooks would need a dependency or a parser of
  their own. YAML was rejected because it needs a third-party parser and its implicit typing turns values such as `no`,
  `on` or `1.10` into booleans and numbers. A Python config module was rejected because loading it runs arbitrary code,
  cannot be validated before it runs, and cannot be edited safely by tools.

## More Information

- [design/project-config.md](../design/project-config.md): the field table, defaults, readers and module selection.
- [ADR 0002](0002-lean-hexagonal-architecture.md): why the model lives in core.
