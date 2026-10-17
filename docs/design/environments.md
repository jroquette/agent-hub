# Environments: declared environments, services and blocked words

## Purpose

How `hub.json` and `hub.local.json` declare a project's environments (a local stack, a developer's replica, a shared
test environment, production) and services, how agents see them, what `access` means, and what the guard enforces
through blocked words. Other keys: [project-config.md](project-config.md), [developer-identity.md](developer-identity.md).

## Contract

### Keys

All optional and additive under `schema_version: 1`; a hub without them behaves, renders and guards as before.

| Key | Shape |
|---|---|
| `environments.<name>` | `access` (required: `read`, `write` or `ask`), `production` (bool, `false`), `description`, `credentials` |
| `…credentials` | `aws_profile` (`^[A-Za-z0-9_.-]{1,64}$`) and `env` (≤ 10 names `^[A-Z_][A-Z0-9_]{0,63}$`): names, never values |
| `repos[].services.<name>` | `kind` (`^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 32, informational), `description`, `endpoints` |
| `…endpoints.<env>` | `url` or `resource` (one required), `note`, `credentials`; `<env>` must be declared |
| `guard.blocked_words` | ≤ 200 words `^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$`, 2-64 characters, matched literally |
| `guard.blocked_words_files` | ≤ 100 globs, ≤ 200 printable ASCII characters, no leading `/`, no `..` segment, no space |
| `guard.blocked_words_env` | ≤ 50 variable names `^[A-Z_][A-Z0-9_]{0,63}$`, a trailing `*` matching a prefix |

Names are a safe segment `S` (project-config.md) of ≤ 40 characters, environment names unique ignoring case across
both files. A `url` is `scheme://host[:port][/path]`, printable ASCII, ≤ 200 characters, no `@`, `?` or `#`. Strings
under `environments` and `services` must not match doctor's secret shapes (the error names the key and the kind, never
the value). No behaviour comes from a name: `production: true` is a flag. An example `hub.json` and `hub.local.json`:

```json
"environments": {"local": {"access": "write", "description": "docker compose stack on this machine"},
  "staging": {"access": "ask", "credentials": {"aws_profile": "demo-staging"}},
  "live": {"access": "read", "production": true, "credentials": {"aws_profile": "demo-live-ro", "env": ["DEMO_LIVE_DB_URL"]}}},
"repos": [{"dir": "demo-api", "services": {"api": {"kind": "api", "endpoints": {"local": {"url": "http://localhost:8000"},
  "live": {"url": "https://api.example.com"}}}, "orders": {"endpoints": {"staging": {"resource": "demo-orders-staging"}}}}}],
"guard": {"blocked_words": ["prod", "production"], "blocked_words_files": ["config/*.json", "serverless.yml"]}
```

```json
{"environments": {"jane-cloud": {"access": "write", "credentials": {"aws_profile": "jane-sandbox"}}, "staging": {"access": "read"}},
 "repos": [{"dir": "demo-api", "services": {"api": {"endpoints": {"jane-cloud": {"url": "https://api.jane.example.com"}}}}}],
 "guard": {"blocked_words": ["demo-live"], "blocked_words_files": ["deploy/*.tfvars"]}}
```

### The developer's layer

`hub.local.json` adds the developer's own rules on top of the team's, never looser ones: new environments (never a
`hub.json` name) and their endpoints on `hub.json`'s repos (`repos: [{dir, services}]`; a committed service only gains
`endpoints`, on local environments); on a committed name, `access` alone and only stricter (`write` → `ask` → `read`;
else `hub.local.json: environments.<name>.access: may only tighten hub.json's <a>`); and the three blocked lists, which
add to the team's. Every other `guard` key stays set only in `hub.json`. The effective view is the union, committed
entries first. An environment's **source** is the file its effective `access` comes from (`hub.local.json` when it
tightens); the brief, `hub env list`, doctor and setup show it.

### What agents see

- **`AGENTS.md`** renders `hub.json` only: with `environments`, an `## Environments and services` section of fixed
  rules (only listed environments exist; `write` covers data, never a deploy; use the named profile or variable and
  never print its value; blocked words are denied), a line per environment (`` `live` (read, PRODUCTION): … ``) and per
  repo with services (`demo-api: api, orders`), no endpoint or credential. Each line counts in `instructions.size`.
- **`hub brief`** reads both files: after `## Repos`, an `Environments` block with each environment's access,
  PRODUCTION, source and credential names, each service's endpoint per environment and the effective blocked words
  (≤ 60 lines and 2000 characters, then `… <n> more: ./hub env list`), never cut by the 5500-character limit. The
  hooks' mini brief lists names, access and PRODUCTION; with an unusable `hub.local.json`, `hub.json`'s ones and
  `hub.local.json is unusable: your own environments are not shown`.
- **Production lines** `production environment: <name> (access <a>, <source>)`: `hub sync` (`hub.json` only, after
  its report, `up to date` and `--check` included; none on a conflict or `--adopt`), `hub setup` (under its
  `environments` item, shown only when one is declared) and `hub env add|set`, whatever doctor's settings. Doctor's
  `environments.production`, an ordinary `doctor.rules` entry, warns for `write` or `ask` and informs for `read`.

### Blocked words

- **Matching:** case-insensitive over ASCII, `(?<![A-Za-z])<word>(?![A-Za-z])`. Anything that is not an ASCII letter
  is a boundary, digits included: `prod` matches `my-prod-db`, `AWS_PROFILE=prod`, `/envs/prod/`, `PROD`, `prod2` and
  `eu2prod`, not `product`, `reproduce` or `demoProd`. False positives are accepted.
- **Bash command text**, in three views (a match in any denies): raw; backslash-newlines removed; every `'`, `"` and
  `\` removed (`p''rod`). Inline assignments and selector flags (`STAGE=prod cmd`, `--profile prod`) are command text.
- **Session variables:** the hook's environment, values only, of the infra selectors and the stage and connection
  names listed in [SPEC.md](../SPEC.md) (`AWS_PROFILE`, `STAGE`, `DATABASE_URL`, …), every declared `credentials.env`
  and every `guard.blocked_words_env` name (no other value, no name). A match denies every Bash call of the session.
- **Paths:** `file_path`, `notebook_path`, `path`, Grep's `glob`, Glob's `pattern` and WebFetch's `url`.
- **Contents** of files whose last component starts with `.env` or that match a `blocked_words_files` glob (no `/`:
  the last component; with `/`: a trailing run of segments, so `config/*.json` matches any repo's or worktree's
  copy), read through Read, Grep (a directory `path` is walked, no links, `.git` and `node_modules` skipped) and Bash
  (every token naming such a file from the event's cwd, glob tokens expanded; not `ls`, `test`, `[`, `stat`).
- **Order:** the rule runs first on every surface; a deny is final (the project extension does not run) and wins over
  any `access` and any `guard.infra.allow` match. It never opens a file the secret-file rule treats as secret: that
  file keeps the secret-file reason, unless its path or the command text holds a word. `prod_markers` is unchanged.
- **Bounds:** a regular file only (`O_NONBLOCK`, `S_ISREG`), read as latin-1 bytes; 1 MiB per command text or file,
  64 files and 4 MiB per call, 300 ms for the views, variables and files together. Over a bound, or not a regular
  file: **ask**, with a reason starting `blocked words not checked` and naming the cause (`too large`, `too many
  files`, `out of time`, `not a regular file`); an unreadable file: no verdict.
- **Layers:** the CLI, doctor and the brief union `hub.json` and `hub.local.json`; the hooks also add a `hub.json`
  named by `$HUB_CONFIG`. No layer removes an entry; an empty list adds nothing.
- **Fail closed:** a list that is not a list, a bad item or an unknown `guard` key in any layer makes the guard ask on
  every Bash and file-tool call, naming the layer and key. So does a `hub.local.json` that exists but is unusable (not
  JSON, not an object, not a regular file, over 64 KiB), until it is fixed (doctor's `config.schema` reports it); an
  absent one changes nothing.
- **Reason:** ``blocked word `<w>` (guard.blocked_words, <first layer listing it>) in <where>: agents do not reach what
  a blocked word names``, `<where>` one of `the command`, `the session variable <NAME>`, `the path <path>`, `the
  contents of <path>` (the path escaped, ≤ 100 characters). Never the command, a value or a line. Rule id
  `blocked_word` (asks too), so the recorded event carries `rule: blocked_word`. `access` is **not** enforced by the
  guard (it cannot tell a read from a write in `psql`, `curl`, `aws` or a script), nor is "only listed environments exist".

### `hub env`

`list`, `show NAME` (both `--json`), `add NAME --access A [--production] [--description T] [--aws-profile P]
[--credential-env VAR]…`, `set`, `remove`, `service add REPO SERVICE --env NAME (--url U | --resource R)`, `service
remove`; `--local` writes `hub.local.json` (created when absent), else `hub.json`. None prompts. A write validates the
result (invalid: exit 1, file unchanged), keeps every key and their order in indent 2 (a file in another indent is
normalised once, and the output says so), refuses (exit 1) when the file changed since it was read, and replaces it
through a temporary file in the same folder (a writer between that check and the replace is overwritten: a narrow
window). `remove` refuses while endpoints use the environment; a committed write
prints `run ./hub sync to update AGENTS.md`. The guard asks before a mutating `hub env` and an edit of
`hub.local.json`; `list` and `show` pass. `hub setup`'s optional step writes only `hub.local.json`.

### Known limits

Blocked words are a best-effort text tripwire, not a security boundary: the boundary is which credentials the
agent's machine holds. The guard runs only on Bash, Read, Grep, Glob, Edit, Write, MultiEdit, NotebookEdit and WebFetch.

1. **`hub run`'s implement step** runs `claude -p` in the app repo's worktree, where the hub's SessionStart brief and
   guard do not load: no Environments block and no blocked-word guard there (older than this contract; AGH-278).
2. **`CLAUDE_ENV_FILE`:** variables a SessionStart hook exports through `$CLAUDE_ENV_FILE` reach Bash only; the guard
   hook sees neither them nor the variable, so they are not scanned. Shell and settings `env` variables are.
3. **Plugin-cache mode with `$HUB_CONFIG`** has no identity home, so it reads no `hub.local.json`.
4. Not checked: MCP tools, WebSearch, subagent (Task) prompts; files a program opens without the command naming them
   (`python sync.py` reading `config/app.json`, `find … -exec cat`); tool output; obfuscation (`$'\x70rod'`, a built
   name); Grep's search regex and edit contents.

## Invariants

- Credentials are referenced by name only; values with a known secret shape are rejected.
- The same `hub.json` renders the same `AGENTS.md` for everyone; `hub.local.json` reaches agents only via the brief.
- Blocked words only grow across layers, and `hub.local.json` only tightens: nothing in it relaxes a guard.
- The model and the hooks' stdlib reader give the same effective words, globs and names for the same two files.
- Hooks stay Python 3.9 stdlib; the guard asks on its own error, other hooks fail open.

## Decisions

- [ADR 0038](../adr/0038-declared-environments-and-blocked-words.md): environments in `hub.json` and
  `hub.local.json`, blocked words enforced, `access` advisory, `hub env` and setup as writers, local environments in
  the brief rather than a rendered `CLAUDE.local.md`.
- Variables by a fixed list of names, not every value (`PATH`, `HOME` hold names); `$HUB_CONFIG` is hooks-only.

## Open questions

- Whether the hook's environment equals the Bash tool's in an interactive session (checked headless only).
- Enforcing `access`, credential injection and audit events: a later `hub env exec`.
