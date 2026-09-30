# Hub doctor: pluggable rules

## Purpose

`hub doctor` checks that a hub and the repos it lists are healthy: the config is valid, the generated files match the
lock, links resolve, agent instructions stay short, true and safe, and nothing from the brain leaks into a code repo.
It will replace the hub's config lint and feature-tracker check. This file is the Phase 1 contract for the rule interface,
the rule set, the output, the exit codes and the per-project configuration.

## Contract

### Rule interface

A rule is a pure function in core with metadata. The CLI builds a read-only snapshot through an adapter and passes it
to every enabled rule; no rule touches the disk, the network or git itself.

| Field | Meaning |
|---|---|
| `id` | dotted `<area>.<name>`, unique, stable across releases (a rename is a breaking change) |
| `severity` | default level of its findings: `error`, `warning` or `info` |
| `summary` | one line: what it checks |
| `module` | the module that owns it, or none for a base rule |
| `check(snapshot) -> findings` | the check itself |

A finding has `rule`, `severity`, `path`, `line` (optional), `message` and `fix` (one line saying how to repair it).
The snapshot is read from the cwd's real path (no walk-up) and holds the validated config (or the validation errors),
the files of the hub and the fixed set of paths the rules read by name. Later inputs arrive with the rules that need
them: `hub.lock` and its paths, looked at by path (`lock.drift`); the release's base hooks block, read from the
templates package installed with the running CLI, so doctor still renders no file (`settings.weakening`); the files of
each `repos[].dir` checkout next to the hub, where a missing checkout gives one `info` finding on the first selected
repo-scoped rule (`brain.leak`, else `links.dead`) and those rules skip it (`links.dead`, `brain.leak`). A root with
no `.git` entry, a hub inside a larger repository included, is walked, skipping `.git` and nested repositories. A root
with a `.git` entry is listed with `git ls-files -z --cached --others --exclude-standard`, and git must name the root
as the work-tree top; git missing, failing, timing out or naming another top is a tree problem, never a walk. No link
is followed, and git runs only when a selected rule needs a listing. A tree problem (a failed listing or read of the
hub) is one `error` finding at path `.` on the first selected rule, by id, that reads the listing, else the first by
id other than `config.schema` and `platform.version` (none when only those run), never retuned; its message is the
cause (`could not list the files: …` or `could not read the files: <path>: …`), its fix one line. Proof: one unit
test per rule on an in-memory snapshot, plus one e2e test of the command on a synthetic hub. A rule's `module` comes
from core's `RULE_MODULES`; a module's rules are core functions registered when the module ships.

### Rules

| Rule id | Default | Checks | Origin |
|---|---|---|---|
| `config.schema` | error | `hub.json` against `HubConfig`, including `schema_version` and `doctor.rules` ids; cannot be disabled or retuned | [ADR 0010](../adr/0010-hub-json-config-contract.md) |
| `platform.version` | error | the running CLI equals `platform.version` (a shim always runs the pin; a direct `hub` may not); one finding only; its `doctor.rules` entry has no effect on findings | [ADR 0013](../adr/0013-release-by-git-tags.md) |
| `lock.drift` | error | each managed file exists and matches its `hub.lock` entry (a missing one: `hub sync` restores it); a lock older than the pin: warning "sync pending"; newer: warning "downgrade"; no `hub.lock`: warning "not adopted" | [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md), [hub-sync.md](hub-sync.md) |
| `links.dead` | error | relative Markdown links resolve to an existing file (hub and repos) | new |
| `instructions.size` | error | line limits: `AGENTS.md` 100, `CLAUDE.md` 150, `CLAUDE.local.md` 50, `.claude/rules/*.md` 80 | config lint |
| `instructions.refs` | error | paths, make targets and package scripts named in instruction files exist | config lint |
| `instructions.duplicates` | error | the same instruction line (60 or more characters) in two instruction files | config lint |
| `rules.frontmatter` | error | `.claude/rules` `paths:` globs match tracked files | config lint |
| `settings.valid` | error | `.claude/settings.json` is valid JSON, with no deprecated keys | config lint |
| `settings.weakening` | error | `.claude/settings.project.json` sets no `disableAllHooks` or `permissions.defaultMode`, and `.claude/settings.json` keeps every hook of the release's base hooks block (in the snapshot) | [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md) |
| `permissions.bypass` | error | no bypass permission mode and no skip-permissions flag in settings, scripts, Makefile or CI | config lint |
| `secrets.config` | error | no secret patterns in agent config files | config lint |
| `mcp.pinned` | error | MCP servers in `.mcp.json` are pinned to a version | config lint |
| `attribution.ai` | error | no AI co-author trailer, generated-by line or agent branch prefix in agent config, contributing guide or PR template | config lint |
| `brain.leak` | error | no trimmed brain line of `min_line_length` (default 60) or more characters in a file tracked in a repo | [SPEC](../SPEC.md) direction 2 |
| `hooks.guard-extension` | error | static: `ast.parse(text, feature_version=(3, 9))` on the extension parses and has a top-level `def check` with two positional parameters (names not enforced); no file: no finding; project code is never imported | [hub-generator.md](hub-generator.md) |
| `makefile.override` | warning | `Makefile.project` does not redefine a managed target | [hub-generator.md](hub-generator.md) |
| `features.tracker` | error | each feature's `features.json`: shape, AC ids, evidence, and the cross-check with its `spec.md` | feature check |
| `bench.tasks` | error | module `bench`: the benchmark cases file is valid | module `bench` |

"config lint" and "feature check" are the hub scripts these rules replace ([hub-generator.md](hub-generator.md),
Commands). Each ported rule keeps the old check's behavior, pinned first by characterization tests. This release
registers `config.schema` and `platform.version`; the other rules come in later AGH-11 PRs. Until a rule ships,
`doctor.rules` accepts its settings and `--only` on it exits 2 with `<id> is not in this release`.

### Output

One line per finding, sorted by rule id, path (a finding without one first) and line:

```text
error instructions.size AGENTS.md: 132 lines, limit 100. Fix: move detail into linked docs.
warning makefile.override Makefile.project:12: redefines target 'check'. Fix: rename the project target.
1 error, 1 warning, 0 infos
```

The format is `<severity> <rule> <path>[:<line>]: <message> Fix: <fix>`, or `<severity> <rule>: <message> Fix: <fix>`
without a path, then the totals: three counts, singular at 1; with no finding: `0 errors, 0 warnings, 0 infos`.
`--only RULE` (repeatable) runs just those rules, plus `config.schema` always; once `features.tracker` ships, skills
use `hub doctor --only features.tracker`. `--json` prints one object with a `findings` list (the finding fields above)
and the totals (keys `errors`, `warnings`, `infos` with integer counts), for scripts and the Layer 2 control plane.

### Exit codes

0 when no finding has severity `error`; 1 when at least one does; 2 on a usage error, an unknown rule id in `--only`,
a rule in `--only` whose module is not selected or that is not in this release, or a directory that is not a hub (no
`hub.json` entry in the cwd; the message says so). An unusable `hub.json` is a `config.schema` error. A rule in
`--only` that `doctor.rules` disables does not run; stderr notes it. The pin is checked before `schema_version`, as in
`hub sync` ([hub-sync.md](hub-sync.md)): on a pin mismatch the `platform.version` error is reported and `config.schema`
reports no `schema_version` mismatch (the pinned release, which fixes both, judges it). On an invalid config only the
two config rules run: `config.schema` reports the config problems, `platform.version` a pin mismatch; `--only` names
are then only checked to be known ids (an unshipped id does not exit 2). A missing `hub.lock` does not stop the other
rules.

### Configuration

A project tunes rules in `hub.json` → `doctor.rules.<id>` ([project-config.md](project-config.md)):

```json
{"doctor": {"rules": {"instructions.duplicates": {"enabled": false},
                      "makefile.override": {"severity": "error"},
                      "instructions.size": {"max_lines": {"AGENTS.md": 120}}}}}
```

`enabled` (default `true`), `severity` (overrides the default; not for `config.schema`) and rule options, validated per
rule. An unknown rule id or option is a `config.schema` error. Options in Phase 1: `instructions.size.max_lines` (file
or glob to limit, merged over the defaults) and `brain.leak.min_line_length`. A rule declares its `module`; the rules of
a module that is not selected in `modules` never run and cannot be configured (a cross-field check of the model, not of
the JSON Schema: [project-config.md](project-config.md)).

## Invariants

- Read-only: `hub doctor` never writes a file, never commits and never calls the network.
- Deterministic: the same snapshot gives the same findings in the same order.
- The rule list and the tuned settings come only from the release and `hub.json`; there is no per-machine state.
- `config.schema` always runs, so a broken config is never silently skipped.

## Decisions

- [ADR 0010](../adr/0010-hub-json-config-contract.md): config validity comes from the same model the CLI uses.
- [ADR 0012](../adr/0012-cli-subsumes-hub-scripts.md): the config lint and the feature-tracker check become rules.
- [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md): `lock.drift` reads the same lock that `hub sync` writes.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md): rules are pure core functions over a snapshot, so no port.

## Open questions

- Whether each code repo's own CI also runs the repo-scoped rules (it needs the hub checkout for `brain.leak`).
