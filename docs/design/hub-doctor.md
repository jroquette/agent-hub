# Hub doctor: pluggable rules

## Purpose

`hub doctor` checks that a hub and the repos it lists are healthy: the config is valid, the generated files match the
lock, links resolve, agent instructions stay short, true and safe, and nothing from the brain leaks into a code repo.
It will replace the hub's config lint and feature-tracker check. This file is the Phase 1 contract for the rule
interface, the rule set, the output, the exit codes and the per-project configuration.

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
the files of the hub and the fixed set of paths the rules read by name. Two inputs are read only when a selected rule
needs them: the parsed `hub.lock` and its managed paths, looked at by path (`lock.drift`), and the release's base hooks
block, built by the templates package installed with the running CLI, so doctor still renders no file
(`settings.weakening`). A third, read only when a repo rule (`brain.leak`, `links.dead`) is selected, is the files of
each `repos[].dir` checkout at `../<dir>`: a missing or non-folder `../<dir>` gives one `info`, a checkout that cannot
be listed one `error` (its cause), both at `../<dir>` on the first selected repo rule by id, never retuned; the repo
rules skip both. A linked `../<dir>` is resolved once to its real path. A root with no `.git` entry, a hub inside a
larger repository included, is walked, skipping `.git` and nested repositories. A root with a `.git` entry is listed
with `git ls-files -z --cached --others --exclude-standard`, and git must name the root as the work-tree top; git
missing, failing, timing out or naming another top is a tree problem, never a walk. No link is followed, and git runs
only when a selected rule needs a listing. A tree problem (a failed listing or read of the hub) is one `error` finding
at path `.` on the first selected rule, by id, that reads the listing, else the first by id other than `config.schema`
and `platform.version` (none when only those run), never retuned; its message is the cause (`could not list the files:
…` or `could not read the files: <path>: …`), its fix one line. Fixed paths are read one by one before the listing, so a
failed listing keeps them; after a failed read no rule calls an absent path missing. A rule whose check raises gives one
`error` of that rule at `.` (`rule crashed: <type>: <message>`), never retuned, and the other rules keep running. An
instruction or plugin file that is not UTF-8 text (a NUL included) is one `error` at its path (`not UTF-8 text: …`),
never retuned, from the first selected rule in registry order that reads it; the other rules skip it. Proof: one unit
test per rule on an in-memory snapshot, plus one e2e test of the command on a synthetic hub. A rule's `module` comes
from core's `RULE_MODULES`; a module's rules are core functions registered when the module ships.

### Rules

| Rule id | Default | Checks | Origin |
|---|---|---|---|
| `config.schema` | error | `hub.json` against `HubConfig`, including `schema_version` and `doctor.rules` ids, and `hub.local.json`; cannot be disabled or retuned | [ADR 0010](../adr/0010-hub-json-config-contract.md) |
| `platform.version` | error | the running CLI equals `platform.version` (a shim always runs the pin; a direct `hub` may not); one finding only; its `doctor.rules` entry has no effect on findings | [ADR 0013](../adr/0013-release-by-git-tags.md) |
| `lock.drift` | error | each managed file (bytes and executable bit) and link (target, not followed) matches its `hub.lock` entry (a missing one: `hub sync` restores it); a lock `platform_version` older than the pin, compared as numbers: warning "sync pending"; newer: warning "downgrade"; no `hub.lock`: warning "not adopted" | [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md), [hub-sync.md](hub-sync.md) |
| `links.dead` | error | in each listed UTF-8 `.md` file of the hub and the repos, inline links, images and reference definitions (CommonMark: a definition only when nothing or a title follows it) resolve from the file's folder, `#fragment`/`?query` cut, to a listed file or folder; skipped: any URI scheme, absolute and fragment-only links, code spans, fenced blocks and HTML comments; a hub link into `../<dir>` is checked against that repo's listing (skipped when the checkout is missing or cannot be listed); any other link leaving the hub or a repo is skipped | new |
| `instructions.size` | error | line limits of the listed regular instruction files (root `AGENTS.md`, `CLAUDE.md`, `CLAUDE.local.md`, `GEMINI.md`; `.github/copilot-instructions.md` and every `.md` under `.claude/{rules,agents,skills,commands}` or `.github/instructions`): root `AGENTS.md` 100, `CLAUDE.md` 150, `CLAUDE.local.md` 50, every nested one 80, `GEMINI.md` none; `max_lines` merges over them (exact key before glob, then the longest glob). A link is not an instruction file, so a plugin agent linked into `.claude/agents/` gets no `instructions.*` check (it keeps `rules.frontmatter`, `secrets.config` and `attribution.ai` as a plugin file) | config lint |
| `instructions.refs` | error | paths, `make` targets and `pnpm` scripts an instruction file names below its frontmatter exist: a path resolves against the listed paths and the fixed paths present, and their folders, from the file's folder or the root, then by name or ending (a reference of at most 32 segments); nothing out of the hub or under a link resolves; targets are `Makefile`'s, `Makefile.project`'s and those of `mk/<id>.mk` of selected modules, scripts `package.json`'s (not read when linked or not text); `hub.lock` is ignored by design (its absence is `lock.drift`'s), and so is exactly `hub.local.json` (each developer's, gitignored); links are not instruction files | config lint |
| `instructions.duplicates` | error | the same normalized instruction line (60 or more characters; not a table, fence or heading line) in two instruction files, flagged on the later path naming the first; repeats within a file are not; links are not instruction files | config lint |
| `rules.frontmatter` | error | at line 1 of each listed regular instruction or plugin (`plugin/…/{agents,skills}/…/*.md`) file: a `---` frontmatter is terminated; a `.claude/rules` file with frontmatter has a non-empty `paths:` list whose globs (braces expanded) each match a file or folder in the hub (listed or a fixed path present); an agent or skill file has a `name` and a `description`. A glob over 256 characters or expanding to more than 64 globs is its own finding and not matched; the globs past a run budget of 64,000,000 path characters get `was not checked` | config lint |
| `settings.valid` | error | `.claude/settings.json` (strict, as `settings.weakening` reads it) and `.mcp.json` (lenient, as the old lint) parse to a JSON object; settings hold no deprecated key (`allowedTools`, `ignorePatterns`); a linked file gives no finding | config lint |
| `settings.weakening` | error | neither `.claude/settings.project.json` nor `.claude/settings.json` sets `disableAllHooks` or `permissions.defaultMode`; both parse as strict JSON; `settings.json` holds every group of the release's base hooks block, compared by JSON form | [ADR 0009](../adr/0009-hub-sync-by-file-ownership.md) |
| `permissions.bypass` | error | no `bypassPermissions` default mode in `.claude/settings.json`; no skip-permissions flag in a key or string of it or `.mcp.json` (both read leniently, so a `settings.valid` error never hides one), nor in a line of a hub file (listed, or a fixed path present) under `scripts/` or `.github/workflows/`, `Makefile` or `package.json` | config lint |
| `secrets.config` | error | no secret shape (eight kinds: JWT, AWS access key, private key, API key, GitHub token, Linear API key, credential assignment, Fernet-like key) in the instruction and plugin files, `.mcp.json`, `.claude/settings.json`, `CONTRIBUTING.md` or the PR template; once per kind per line, naming the kind, never the text | config lint |
| `mcp.pinned` | error | each `.mcp.json` server is not `@latest` and, run by `npx`, names a version (`@<digit>`); a server whose `args` are not all strings is skipped; settings' `mcpServers` are not checked | config lint |
| `attribution.ai` | error | no AI co-author trailer, "Generated with Claude Code" line or `claude/` branch prefix in the files `secrets.config` reads | config lint |
| `brain.leak` | error | no trimmed line of `min_line_length` (default 60, 1–10000) or more characters of a listed UTF-8 file under `brain/` (frontmatter, an unterminated one read as text, fenced blocks and table rows skipped) is a trimmed line of a listed text file in a repo; reported at the repo `path:line`, naming the brain `path:line`, never the leaked line | [SPEC](../SPEC.md) direction 2 |
| `hooks.guard-extension` | error | static, never imported or run: the extension (at most 1 MiB, UTF-8) parses from its raw bytes as Python 3.9 (BOM and coding cookie as the runner reads them; best-effort: newer f-string syntax passes), and the last top-level binding of `check` is a `def` that `check(event, cfg)` can call; no file: no finding | [hub-generator.md](hub-generator.md) |
| `makefile.override` | warning | `Makefile.project` does not redefine a target parsed from the managed `Makefile` (and the targets of `mk/<id>.mk` of selected modules; grouped `&:` rules read; `$(T):` targets not expanded; no other included file is followed) | [hub-generator.md](hub-generator.md) |
| `features.tracker` | error | each listed `brain/features/*/features.json`: shape, AC ids, evidence, and the cross-check with a listed sibling `spec.md`; links are not followed | feature check |
| `bench.tasks` | error | module `bench`, snapshot only (no git, no process): listed `brain/workflow/bench/tasks.json` is a strict JSON list (at most 1 MiB, 200 cases; absent or `[]` is clean); each case an object with `id` (`[A-Za-z0-9._-]{1,64}`, unique ignoring case), `repo` (a `repos[].dir` unless `excluded`), `merge` (a 7–40 hex sha), `prompt` (1–20 000 characters, not starting with `-`), `hidden_tests` (1–100 literal relative paths of at most 1 024 characters: no glob or `\`, no leading `/`, `-` or `:` (pathspec magic), no empty, `.`, `..` or `.git` segment in any case, no control, format or surrogate character), `test_cmd` (1–32 non-empty strings of at most 1 024 characters); optional `setup_cmd` (at most 4 096 characters), `env` (at most 32 keys `[A-Za-z_][A-Za-z0-9_]*`, values string, number or boolean), `excluded` (boolean); no NUL in a string a process gets; one finding per problem | module `bench` |
| `config.identity` | info | the branch prefix this developer gets when no file sets one: derived from the effective email (named with its source); can be disabled, cannot be retuned (a `severity` is a `config.schema` error), so every developer's run exits alike | AGH-65 |

"config lint" and "feature check" are the hub scripts these rules replace ([hub-generator.md](hub-generator.md),
Commands). Each ported rule keeps the old check's behavior, pinned first by characterization tests, but for what its
row states. This release registers every rule.

### Output

One line per finding, sorted by rule id, path (a finding without one first) and line:

```text
error instructions.size AGENTS.md: 132 lines, limit 100 Fix: keep it a map, not a manual: move details to docs or the brain
warning makefile.override Makefile.project:12: redefines target 'check' Fix: rename the project target
1 error, 1 warning, 0 infos
```

The format is `<severity> <rule> <path>[:<line>]: <message> Fix: <fix>`, or `<severity> <rule>: <message> Fix: <fix>`
without a path, then the totals: three counts, singular at 1; with no finding: `0 errors, 0 warnings, 0 infos`.
`--only RULE` (repeatable) runs just those rules, plus `config.schema` always; skills use
`hub doctor --only features.tracker`. `--json` prints one object with a `findings` list (the finding fields above)
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

`enabled` (default `true`), `severity` (overrides the default; not for `config.schema` or `config.identity`) and rule
options, validated per rule. An unknown rule id or option is a `config.schema` error. Options in Phase 1:
`instructions.size.max_lines` (file or glob to limit, merged over the defaults; keys of 1 to 1024 characters, at most
256 of them, `_` comment keys aside) and `brain.leak.min_line_length` (1 to 10000). A rule declares its `module`; the
rules of a module that is not selected in `modules` never run and cannot be configured (a cross-field check of the
model, not of the JSON Schema: [project-config.md](project-config.md)).

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
