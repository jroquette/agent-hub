# Environments: declared environments, services and blocked words

## Purpose

A project runs services (APIs, databases, queues, web portals) in several environments: a local stack, a developer's
own replica, a shared test environment, production. This is the contract for how `hub.json` and `hub.local.json`
declare them, how agents see them, what `access` means, and what the guard enforces through blocked words. Other keys:
[project-config.md](project-config.md), [developer-identity.md](developer-identity.md); reasons: ADR 0038 (Decisions).

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

Names (of environments and services) are a safe segment `S` (project-config.md, Rendered values) of at most 40
characters; environment names are unique ignoring case across both files. A `url` is `scheme://host[:port][/path]`,
printable ASCII without space, ≤ 200 characters, with no user info (`@`), query (`?`) or fragment (`#`). Every string
under `environments` and `services` is run through doctor's secret shapes; the error names the key and the kind of
secret, never the value. No default and no behaviour comes from a name: `production: true` is a flag, not a policy,
and an environment that is not declared is out of bounds for the agent. An example `hub.json` and `hub.local.json`:

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
  rule lines (only listed environments exist; `read`, `ask` and `write` mean what they say, and `write` covers data,
  never a deploy; credentials are never here, so use the named profile or variable and never print its value;
  commands naming a blocked word are denied), one line per environment (`` `live` (read, PRODUCTION): … ``) and one
  per repo with services (`demo-api: api, orders`). No endpoint, resource or credential name. Each environment adds a
  line to the 100-line `instructions.size` budget; a large list raises `doctor.rules["instructions.size"]`.
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
- **Session variables:** the hook's environment, values only, of these names: the infra guard's selectors
  (`AWS_PROFILE`, `KUBECONFIG`, `TF_WORKSPACE`, … as in [SPEC.md](../SPEC.md)), `STAGE`, `SLS_STAGE`, `ENV`,
  `ENVIRONMENT`, `APP_ENV`, `NODE_ENV`, `RAILS_ENV`, `RACK_ENV`, `FLASK_ENV`, `DATABASE_URL`, `PGHOST`, `PGSERVICE`,
  `PGDATABASE`, `MYSQL_HOST`, `REDIS_URL`, `MONGODB_URI`, `AWS_ENDPOINT_URL`, every declared `credentials.env` name
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
  file: **ask**, naming the cause (`too large`, `too many files`, `out of time`, `not a regular file`); unreadable: no verdict.
- **Layers:** the CLI, doctor and the brief union `hub.json` and `hub.local.json`; the hooks also add a `hub.json`
  named by `$HUB_CONFIG`. No layer removes an entry; an empty list adds nothing.
- **Fail closed:** a list that is not a list, a bad item or an unknown `guard` key in any layer makes the guard ask on
  every Bash and file-tool call, naming the layer and key. So does a `hub.local.json` that exists but is unusable (not
  JSON, not an object, not a regular file, over 64 KiB), until it is fixed; an absent one changes nothing.
- **Reason:** ``blocked word `<w>` (guard.blocked_words, <first layer listing it>) in <where>: agents do not reach what
  a blocked word names``, `<where>` one of `the command`, `the session variable <NAME>`, `the path <path>`, `the
  contents of <path>` (the path escaped, ≤ 100 characters). Never the command, a value or a line. Rule id
  `blocked_word` (asks too), so the recorded event carries `rule: blocked_word`.
- `access` is **not** enforced by the guard: it cannot tell a read from a write in `psql`, `curl`, `aws` or a script.

### `hub env`

`list`, `show NAME` (both `--json`), `add NAME --access A [--production] [--description T] [--aws-profile P]
[--credential-env VAR]…`, `set`, `remove`, `service add REPO SERVICE --env NAME (--url U | --resource R)`, `service
remove`; `--local` writes `hub.local.json` (created when absent), else `hub.json`. None prompts. A write validates the
result (invalid: exit 1, file unchanged), keeps every key and their order in indent 2 (a file in another indent is
normalised once, and the output says so), refuses (exit 1) when the file changed since it was read, and replaces it
through a temporary file in the same folder. `remove` refuses while endpoints use the environment; a committed write
prints `run ./hub sync to update AGENTS.md`. The guard asks before a mutating `hub env` and an edit of
`hub.local.json`; `list` and `show` pass. `hub setup`'s optional step writes only `hub.local.json`.

### Known limits

1. **`hub run`'s implement step** runs `claude -p` in the app repo's worktree, where the hub's SessionStart brief and
   guard do not load: no Environments block and no blocked-word guard there (older than this contract; follow-up).
2. **`CLAUDE_ENV_FILE`:** variables a SessionStart hook exports through `$CLAUDE_ENV_FILE` reach Bash only; the guard
   hook sees neither them nor the variable, so they are not scanned. Shell and settings `env` variables are.
3. **Plugin-cache mode with `$HUB_CONFIG`** has no identity home, so it reads no `hub.local.json`.
4. Not checked: tool output, obfuscation (`$'\x70rod'`, a built name), Grep's search regex and edit contents.

## Invariants

- No credential in either file, the rendered files, the brief, a reason or an event: names and references only.
- The same `hub.json` renders the same `AGENTS.md` for every developer; `hub.local.json` reaches agents only through
  the brief.
- Blocked words only grow across layers, and `hub.local.json` only tightens: nothing in it relaxes a guard.
- The model and the hooks' stdlib reader give the same effective words, globs and names for the same two files.
- Hooks stay Python 3.9 stdlib; the guard asks on its own error, other hooks fail open.

## Decisions

- [ADR 0038](../adr/0038-declared-environments-and-blocked-words.md): environments in `hub.json` and
  `hub.local.json`, blocked words enforced, `access` advisory, `hub env` and setup as writers, local environments in
  the brief rather than a rendered `CLAUDE.local.md`.
- Variables by a fixed list of names, not every value (`PATH`, `HOME` hold folder and user names).
- `$HUB_CONFIG` stays a hooks-only layer: no command reads it.

## Open questions

- Whether the hook's environment equals the Bash tool's in an interactive session (checked headless only).
- Enforcing `access`, credential injection and audit events: a later `hub env exec`.
