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
| `environments.<name>` | `access` (required: `read`, `write` or `ask`), `production` (bool, `false`), `description` (≤ 80, rendered as plain text), `credentials`, `values` |
| `…values` | ≤ 32 entries keyed by a scenario input name (`^[a-z][a-z0-9_]{0,63}$`), each a text of 1 to 200 characters with no control, line-break or bidi character and never a secret's shape; `_` keys are comments. They fill a scenario's inputs of the same name (§ Values) |
| `…credentials` | `aws_profile` (`^[A-Za-z0-9_.-]{1,64}$`), `env` (≤ 10 names `^[A-Z_][A-Z0-9_]{0,63}$`) and `env_file` (a dotenv path relative to the workspace, ≤ 200, no `..`, no leading `/` or `~`, its values read only by actions, its names listed by hub web: [scenarios.md](scenarios.md)): names and paths, never values |
| `repos[].services.<name>` | `kind` (`^[a-z0-9]+(-[a-z0-9]+)*$`, ≤ 32, informational), `description`, `endpoints` |
| `…endpoints.<env>` | `url` or `resource` (one required), `note`, `credentials`; `<env>` must be declared |
| `guard.blocked_words` | ≤ 200 words `^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$`, 2-64 characters, matched literally, never a secret's shape |
| `guard.blocked_words_files` | ≤ 100 globs, ≤ 200 printable ASCII characters, no leading `/`, no `..` segment, no space |
| `guard.blocked_words_env` | ≤ 50 variable names `^[A-Z_][A-Z0-9_]{0,63}$`, a trailing `*` matching a prefix |

Names are a safe segment `S` (project-config.md) of ≤ 40 characters, environment names unique ignoring case across both
files. A `url` is `scheme://host[:port][/path]`, printable ASCII, ≤ 200 characters, no `@`, `?` or `#`. Strings under
`environments` and `services` hold no control, line-break or bidi character nor a doctor secret shape (the error names
the key and kind, never the value). No behaviour comes from a name: `production: true` is a flag. Examples:

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
`endpoints`, on local environments); on a committed name, only `access`, and only stricter (`write` → `ask` → `read`;
else `hub.local.json: environments.<name>.access: may only tighten hub.json's <a>`), and `values`, which win per key
over the team's (any other key: `may only tighten its access or set values`); and the three blocked lists, which
add to the team's. Every other `guard` key stays set only in `hub.json`. The effective view is the union, committed
entries first. An environment's **source** is the file its effective `access` comes from (`hub.local.json` when it
tightens); the brief, `hub env list`, doctor and setup show it.

### Values

An environment's `values` are facts of the place, not of a scenario: the developer's account id, a user name, a
region. A scenario planned or started in environment E (`hub scenario plan|run --env E`, and hub web's plan and start)
fills each declared input it is not given with E's value of the same name, typed as the input declares (`integer`,
`number`, `boolean` as `true`/`false`; a value that does not read as the type refuses the plan or start, naming the
input and environment). The order is: **given input > environment value > declared default**; a required input that
none of them fills refuses the plan or start, naming the input (`hub scenario plan|run` name the environment too). A
value for a name the scenario does not declare is ignored; the run record keeps the effective inputs. The effective
values of a committed environment are `hub.json`'s, then `hub.local.json`'s per key. Values are never secrets: a
secret-shaped one is refused like any string here, and credentials stay in `credentials.env_file`.

```json
{"environments": {"local": {"values": {"personal_name": "jane-personal", "aws_account_id": "123456789012"}}}}
```

### What agents see

- **`AGENTS.md`** renders `hub.json` only: with `environments`, an `## Environments and services` section of fixed
  rules (only environments listed there or in the brief exist; `write` covers data, never a deploy; `access` is not
  enforced; never print a credential; blocked words are denied; the rest: the brief, `./hub env list`), one line per
  environment (`` `live` (read, PRODUCTION): … ``, its description Markdown-escaped) and per repo with services, no
  endpoint or credential. Each counts in `instructions.size` (the example: 96 of 100; more raise its `max_lines`).
- **`hub brief`** reads both files: after `## Repos`, an `Environments` block with each environment's access,
  PRODUCTION, source and credential names, each service's endpoint per environment and the effective blocked words (≤ 60
  lines, 2000 characters, then `… <n> more: ./hub env list`; urls and resources as code, descriptions and notes cut at
  80, escaped), never cut by the 5500-character limit. Mini brief: names (`<hidden>` if secret-shaped), access,
  PRODUCTION (≤ 60); with an unusable `hub.local.json`, `hub.json`'s and `hub.local.json is unusable: your own
  environments are not shown`.
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
- **Tool inputs:** every key and string value of the input of the input tools: MCP tools (`mcp__*`), WebSearch, Task,
  Agent and SendMessage, walked in document order, each string as it is (no joins or quote removal); numbers, booleans
  and null are counted, not scanned; the tool name is not scanned.
- **Contents** of files whose last component (as named or linked to) starts with `.env` or matches a
  `blocked_words_files` glob (no `/`: the last component; with `/`: a trailing run of segments, so `config/*.json`
  matches any repo's copy), read through Read, Grep (its `path`, or the cwd, walked without following links) and Bash
  (each token naming such a file from the event's cwd, braces and globs expanded; not `ls`, `test`, `[`, `stat`).
- **Order:** the rule runs first on every surface; a deny is final (the project extension does not run) and wins over
  any `access` and any `guard.infra.allow` match. It never opens a secret file, by any case or link: it keeps the
  secret-file reason (this rule gives it then), unless its path or the command holds a word. `prod_markers` is unchanged.
  On the input tools the blocked-word rule is the only rule, and the project extension does not run.
- **Bounds:** regular files only (`O_NONBLOCK`, `S_ISREG`), as latin-1; 1 MiB per command or file, 64 listed files
  and 4 MiB per call, 1 MiB of keys and strings and 50,000 values (objects, arrays, keys and scalars) per tool input,
  300 ms (checked per folder entry and per value) in all. Over one, or not regular: **ask** `blocked words not
  checked: <cause>` (`too large`, `too many files`, `too many values`, `out of time`, `not a regular file`); a listed
  name that is a folder, or unreadable: no verdict. In a tool input, a word found before a bound is crossed denies;
  "before" means earlier in walk order, so a string over the cap asks even when a word sits at its start. Walks skip heavy vendored and cache trees: `.git`, `node_modules`,
  `.claude/worktrees`, `.venv`, `__pycache__`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.terraform`, `.next`.
- **Layers:** the CLI, doctor and the brief union `hub.json` and `hub.local.json`; the hooks also add a `hub.json`
  named by `$HUB_CONFIG`. No layer removes an entry; an empty list adds nothing.
- **Fail closed:** a list that is not a list, a bad item or an unknown `guard` key in any layer makes the guard ask on
  every call the guard checks (Bash, the file tools and the input tools), naming the layer and key. So does a `hub.local.json` that exists but is unusable (not
  JSON, not an object, not a regular file, over 64 KiB), until it is fixed (doctor's `config.schema` reports it); an
  absent one changes nothing. A hook event that is not a JSON object (bad UTF-8, invalid or truncated JSON, nested too
  deep for the parser, a list) makes the guard ask
  `blocked words not checked: the tool input could not be read (not a JSON object)` while blocked words, or a problem
  with the blocked-word list, are in effect; without them, nothing changes.
- **Reason:** ``blocked word `<w>` (guard.blocked_words, <first layer listing it>) in <where>: agents do not reach what
  a blocked word names``, `<where>` one of `the command`, `the session variable <NAME>`, `the path <path>`, `the
  contents of <path>`, ``the input of `<tool>` `` (the path or tool name escaped, ≤ 100 characters). Never the command, a value or a line. Rule id
  `blocked_word` (asks too), so the recorded event carries `rule: blocked_word`. `access` is **not** enforced by the
  guard (it cannot tell a read from a write in `psql`, `curl`, `aws` or a script), nor is "only listed environments exist".

### `hub env`

`list`, `show NAME` (both `--json`, which hold `values`), `add NAME --access A [--production] [--description T]
[--aws-profile P] [--credential-env VAR]… [--value NAME=VALUE]…`, `set` (also `--value NAME=VALUE`… and
`--unset-value NAME`…; with `--local` on a committed name, an entry emptied of its values is dropped), `remove`, `service add REPO SERVICE --env NAME (--url U | --resource R)`, `service
remove`; `--local` writes `hub.local.json` (created mode 0644, as by `hub setup`), else `hub.json`. None prompts. A
write validates the result (invalid: exit 1, file unchanged), keeps every key and their order in indent 2 (another
indent is normalised once, and the output says so), refuses (exit 1) a file changed since it was read, a symlinked
file and a `_` name (a comment key), and replaces the file through a temporary one in the same folder (a writer
between that check and the replace is overwritten: a narrow window). `remove` refuses while endpoints use the
environment; a committed write prints `run ./hub sync to update AGENTS.md`. The guard asks before a mutating
`hub env` and an edit of `hub.local.json`; `list` and `show` pass. `hub setup`'s optional step writes only it.

### From hub web

The Environments screens (AGH-417) read and make the same edits as `hub env` through `GET /projects/{project}/config` (its
`environments`, each with its effective `values`) and `POST /projects/{project}/config/environments` (AGH-416):
`add_environment` takes `values` (name → text, an empty text left out) and `set_environment` takes `values` (name →
text sets it, an empty text removes it, a name left out stays), in the `team` or `local` scope. The edit is checked as a read checks
both files (each file, then the rules across them) before anything is written, refuses a file changed since it was
read or a symlinked one, replaces the file through a temporary one, and is never committed: a `hub.json` change waits
for the owner's hub PR and `./hub sync` ([ADR 0040](../adr/0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md),
option 1). The route is a hub registry write: it needs this server's `Origin`. A refused edit answers 422 "This change
was not saved" with the reason; `hub env` gains no command from it.

**Renames.** renaming a `hub.json` environment also moves every endpoint `hub.json` keys by it, and renaming
a `hub.json` service keeps its place in its repo. When this developer's `hub.local.json` holds the old name (a
tightening, or that service's endpoints), the same write renames it there too, both files or neither; other
developers' `hub.local.json` are not touched, and their entries under the old name stop applying until they rename
them (the screen warns). A local rename of a `hub.json` name is refused, and `hub.local.json` may only add endpoints to
a committed service, never change its `kind`, `description` or name.

**Acceptance criteria (AGH-416)**

- **AC-416.1** Given environments and services in `hub.json` and `hub.local.json`, when the Hub config is read, then
  its `environments` lists every effective environment (name, access, production, description, credentials by name)
  and every repo service with its endpoints, each with the file it comes from; when `hub.local.json` breaks a rule
  across both files (a looser `access`), only the team's are listed and the problem is reported.
- **AC-416.2** Given `hub.local.json` tightens a `hub.json` environment, when the Hub config is read, then that
  environment carries hub.json's `access` as `team_access` beside the effective one; a developer's own environment
  has none.
- **AC-416.3** Given a scope (`team`: `hub.json`, `local`: `hub.local.json`), when `add_environment`,
  `set_environment` or `remove_environment` is posted, then the change is made in that file as `hub env` makes it:
  a new environment goes last, credentials are names and a path only (an empty text or list removes the key), a
  local file is created when absent and removed when its last entry goes, a local `set_environment` on a `hub.json`
  name may only tighten `access`, a looser `access` or another field is refused, and removing an environment an
  endpoint uses (or a `hub.json` one this developer's file still tightens) is refused; nothing is committed.
- **AC-416.4** Given a repo service, when `add_endpoint` or `remove_endpoint` is posted, then the endpoint is added
  (the service too, when new) or removed (the whole service when no environment is named); an endpoint with both or
  neither of a URL and a resource, or a URL with user info, is refused and the file is unchanged.
- **AC-416.5** Given a service with an endpoint in an environment, when `add_endpoint` is posted with `replace`, then
  that endpoint is replaced in the same write and the service keeps its `kind`.
- **AC-416.6** Given a new service of a repo, when `add_service` is posted with a `kind`, a `description` and one
  address per environment, then each address goes to its environment's file (a URL when it holds `://`, else a
  resource), the kind and description go with the service's first declaration (`hub.json`'s when a team environment
  gets an address), and when any address is refused or makes either file invalid, neither file is written.
- **AC-416.7** Given a `hub.json` environment, when `rename_environment` is posted with scope `team`, then it is
  renamed in its place, every endpoint `hub.json` keys by it follows, and this developer's `hub.local.json`
  tightening or endpoints under the old name are renamed in the same write; other developers' `hub.local.json` are
  not touched. A local rename renames the developer's own environment and its endpoints. A new name another
  environment of either file holds (ignoring case; a change of case renames) is refused, and so is a local rename of
  a `hub.json` name.
- **AC-416.8** Given a service, when `set_service` is posted, then its `kind` and `description` change (an empty text
  removes the key) and a `new_name` renames it in its place in its repo; a team rename also renames this developer's
  endpoints for it in `hub.local.json`. A name the repo already has is refused, and so is a local change to a
  `hub.json` service.
- **AC-416.9** Given a `batch` of edits, when it is posted, then the edits are made in order on both files in memory
  and written together; when one is refused (named `op N: ...`) or the result is invalid, neither file is written.
- **AC-416.10** Given a request from another origin or without an `Origin`, when it posts an environment edit, then
  it is refused as every hub registry write is; with this server's `Origin` the composed app answers the new Hub
  config view.

**Acceptance criteria (AGH-417)** (the screens: [control-plane/specs/23-environments.md](control-plane/specs/23-environments.md))

- **AC-417.12** Given an env file path, when `GET /projects/{project}/env-file-keys?path=` is read, then it answers
  the file's variable names only, never a value, whether it exists, which of the hub and its repos holds it and
  whether git ignores it there; a file outside the hub and its repos, reached through a link, not regular or over
  64 KiB gives its reason and no names; a path with `..`, a leading `/` or `~`, or a space is refused (400).

### Discoveries

`hub web` can find services with Claude ([ADR 0046](../adr/0046-read-only-discovery-sessions.md)): the person picks
repos and declared environments (and whether Claude may suggest new ones); the server starts a read-only session
(`Read`, `Grep`, `Glob` only) in the hub with the repos attached, and Claude ends its reply with one JSON proposal of
environments, services and their addresses, each with evidence. The server checks every item with this file's
shapes (an invalid one is listed as dropped, with the reason), sets `access` and `production` from the preset Claude
names, and marks each item `new`, `differs` or `declared` against the effective config. Nothing is written until the
person applies the rows they pick through the batch edit. Routes: `/api/v1/projects/{project}/environment-discoveries`
(POST, GET) and `/{discovery_id}` (GET, DELETE); one file per discovery under `<hub>/.agent-runs/env-discoveries/`.

A discovery's state follows its session: `running` while a turn works or a request is open, `finished` once the last
reply holds a proposal, `stopped` when the person interrupted the turn or closed the session before one, else `failed`
with the reason in plain words. The session's `tool_access` (`all` or `read_only`) is stored with it (migration 0009)
so a session reopened by a later message stays read-only; `POST /agent-sessions` never sets it (AC-418.1 and
AC-418.2 in [agent-sessions.md](agent-sessions.md#read-only-sessions-agh-418)).

**Acceptance criteria (AGH-418)** (the screens: [control-plane/specs/23-environments.md](control-plane/specs/23-environments.md))

- **AC-418.3** Given picked repos and declared environments, when `POST /projects/{project}/environment-discoveries`
  is posted, then a `read_only` session starts in the hub with the server's prompt (the repos, the environments, where
  to look, never open a `.env` file, never print a secret) and the picked repos attached, and the discovery is
  recorded as one file under `<hub>/.agent-runs/env-discoveries/`; a repo `hub.json` does not hold, or an environment
  not declared, is refused (422, naming each one) before anything starts, and so is an empty repo list.
- **AC-418.4** Given a finished session, when its discovery is read, then the last fenced JSON block of its final reply
  (at most 512 KiB, parsed strictly) is the proposal; each item is checked with `hub.json`'s shapes, an invalid item
  or field is listed as dropped with its reason (a secret-shaped value never echoed), `access` and `production` come
  from the preset Claude names, evidence must name a file inside a picked repo, and each item is `new`, `differs` or
  `declared` against the effective config of now.
- **AC-418.5** Given a discovery, when it is read, then it is `running` while its session works, `finished` with a
  proposal, `stopped` when the person interrupted or closed it before a proposal, and `failed` with the reason when
  the reply holds no proposal, the session failed or was removed, or `hub web` stopped first.
- **AC-418.6** Given discoveries, when they are listed, then the project's own not discarded ones come newest first,
  at most 50; `DELETE` marks one discarded and ends its session; an unknown or discarded id answers 404 and an id
  that is not 12 hex digits is refused.
- **AC-418.7** Given the discovery routes, when they are called, then they follow the agent-session rules: the
  session cookie, this server's `Origin` for the writes, off in the container; nothing in `hub.json` changes until
  the person applies rows through `POST /projects/{project}/config/environments`.

### Known limits

Blocked words are a best-effort text tripwire, not a security boundary: the boundary is which credentials the
agent's machine holds. The guard runs only on Bash, Read, Grep, Glob, Edit, Write, MultiEdit, NotebookEdit, WebFetch
and the input tools: MCP tools (`mcp__*`), WebSearch, Task, Agent and SendMessage (matcher `^(…)$|^mcp__`).

1. **`hub run` and repo-cwd agent nodes** run under the hub's hooks through a hooks-only `--settings` file,
   `.agent-runs/session-settings/<effort>.json`, rebuilt before each session (AGH-278); a guard `ask` is refused there.
2. **`CLAUDE_ENV_FILE`:** variables a SessionStart hook exports through `$CLAUDE_ENV_FILE` reach Bash only; the guard
   hook sees neither them nor the variable, so they are not scanned. Shell and settings `env` variables are.
3. **Plugin-cache mode with `$HUB_CONFIG`** has no identity home, so it reads no `hub.local.json`.
4. Not checked: files a program opens without the command naming them from the cwd (`python sync.py` reading
   `config/app.json`, `find … -exec cat`, `cd dir && cat file`, `$PWD` or a variable in a path, `git show REV:path`);
   tool output; obfuscation (`$'\x70rod'`); Grep's search regex and edit contents.
5. On the input tools only the blocked-word rule runs: `deny_hosts` (a listed host in an MCP input passes),
   `deny_paths`, `guard.infra` and the secret-file rule do not; a path in an MCP input is text, never opened (AGH-372).
6. Skill, TodoWrite, ExitPlanMode and AskUserQuestion are not checked (AGH-373).
7. The tool name is not scanned, nor the MCP server's name: `mcp__prod-db__query` with a clean input passes (AGH-373).
8. A hub synced by an older release keeps the old matcher, so the input tools are unchecked there until
   `hub sync` (doctor's `settings.weakening` reports `hooks.PreToolUse`).
9. A recorded event of a guard deny or ask, like the sensor's own `PreToolUse`, carries these tools' input whole (up
   to the 64 KiB per-string omission) to the loopback control plane (AGH-371).
10. The event is parsed whole before the walk's caps apply: there is no byte cap on the guard's stdin (AGH-375).

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
- [ADR 0040](../adr/0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md): hub web makes the writes
  `hub env` would make, in `hub.json` or `hub.local.json`, left uncommitted for the owner's hub PR (AGH-416).
- Variables by a fixed list of names, not every value (`PATH`, `HOME` hold names); `$HUB_CONFIG` is hooks-only.

## Open questions

- Whether the hook's environment equals the Bash tool's in an interactive session (checked headless only).
- Holding agent steps: `access` is enforced for actions and declared `shell` and `script` nodes ([scenarios.md](scenarios.md)); agent steps are checked on a best-effort basis.
