# Developer identity: `hub.local.json`, then `hub.json`, then git config

## Purpose

One hub repo serves every developer of a project, but a branch prefix and a commit author belong to one developer.
This is the contract for where each developer's `project.branch_prefix`, `project.author_name` and
`project.author_email` (and their own `tracker.transport`) come from, in the CLI, the hooks, rendering, doctor and
cloud setup. The `hub.json` fields themselves are in [project-config.md](project-config.md); reasons in
[ADR 0016](../adr/0016-per-developer-identity.md).

## Contract

### Precedence

- Per key, the first source that sets it wins: the gitignored `hub.local.json`, else `hub.json`, else the hub repo's
  `git config user.name`/`user.email`. A hub that sets the identity in `hub.json` behaves as before.
- `branch_prefix` has no git key. When no file sets it, it is derived: the local part of the effective `author_email`
  plus `/`. A derived value that fails the `branch_prefix` pattern (`^S/$`) is no prefix; it is never normalized.
- Git is read only for a key no file sets, only when a consumer needs it, at most once per key.
- A git value loses one trailing newline (never stripped otherwise), must be valid UTF-8 and must match `hub.json`'s
  pattern for the key (`author_name`: no control character; `author_email`: the email pattern), else it counts as unset.

### `hub.local.json`

- **Location: the identity home**, the root of the hub's main checkout. From a hub worktree the main checkout's file
  is read, never one in the worktree. It is never read beside a `$HUB_CONFIG` file.
- **Format.** `hub.json`'s nesting, plain JSON, a regular file of at most 65,536 bytes. It accepts only
  `project.branch_prefix`, `project.author_name`, `project.author_email` and `tracker.transport` (`api` or `mcp`),
  each with `hub.json`'s rule, plus `_` comment keys at `$`, `project` and `tracker`. `null` is refused.
- **Example:** `{"project": {"branch_prefix": "jane/", "author_name": "Jane Roe", "author_email": "jane@example.com"}}`.
- **Problems** (CLI and doctor), one per error, `hub.local.json: <json path>: <message>`. A `hub.json` key that is not
  local: `set only in hub.json; hub.local.json holds project.branch_prefix, author_name, author_email and
  tracker.transport`. Any other key: `Extra inputs are not permitted`. Not an object: `$: must be a JSON object`. Too
  big: `$: cannot read <path>: larger than 65536 bytes`. An absent file sets nothing.
- **Ignored by git.** `hub init` seeds `.gitignore` with `hub.local.json`. `.gitignore` is seeded, so `hub sync` never
  adds the line: an existing hub adds it by hand (README, `hub.local.json`).
- **Nothing in it relaxes a guard**: it cannot add or remove a guard path, host, protected branch or repo.

### CLI

- `hub.json` is read from the hub root as before. `hub.local.json` is read from `hub_root.local_home(root)`: the root,
  or its main checkout when `root/.git` is a file and git runs.
- The git read (`effective_config.git_identity_reader`, through `read_git_defaults`) runs `git config --get` in the
  identity home, 10 s each, with `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR` and the session's tokens dropped.
- `hub next`, `hub brief`, `hub agent` and `hub bench` use `hub.json` with the local values over it
  (`load_effective_config_or_exit`). A bad `hub.local.json` exits 1 with its problem lines. A local
  `tracker.transport` picks the adapter of `hub next` and `hub run`.
- `hub worktree` (create and `--remove`) and `hub run` resolve the prefix before any git write
  (`effective_with_prefix_or_fail`). A bad local file, or no prefix, is a usage error, exit 2:
  ```
  no branch prefix for this developer; set one of:
    hub.local.json → project.branch_prefix
    hub.json → project.branch_prefix
    git config user.email in the hub (its local part plus /)
  ```
  One more line says why when it can: `  <source>'s project.author_email gives "<local>", not a valid prefix` (or
  `git's user.email gives …`), `  git's user.email is not an email address`, or `  git: <problem>`.
- `hub init` and `hub sync` never read `hub.local.json`. `hub init` still fills the identity into `hub.json` from flags
  or git, and `--config` copies a `hub.json` without identity keys.

### Hooks

- The stdlib reader (`stdlib_reader.py`, `EffectiveValues`) applies the same precedence and never raises. The local
  file counts only as a regular file (opened `O_NONBLOCK`, `S_ISREG` on `fstat`) of at most 65,536 bytes holding a
  JSON object; otherwise it sets nothing. A local value counts only when it is a non-empty string with the model's
  shape (pattern, or `api`/`mcp`) that encodes as UTF-8; otherwise that key falls through to `hub.json`, then git.
  `hub.json`'s own non-empty prefix is used unchecked, as before.
- **Identity home** (`hubhooks._identity_home`): the hook root's main checkout; with no hook root (plugin cache), the
  walked hub, unless `$HUB_CONFIG` names a file, in which case there is none: no local file and no git.
- **Git** (`Config._git_value`): `git config --get <key>` in the identity home, 2 s (`IDENTITY_GIT_TIMEOUT`), without
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`; raw bytes decoded strictly; any failure, timeout or non-zero exit is
  `""`. It runs only for a guard deny whose reason holds the branch hint, never when a file sets the prefix.
- The guard's branch hint is `<prefix><team>-<N>-<desc>`; with no prefix, it starts at the team.

### Rendering

`hub init`, `hub sync` and `render_hub` read `hub.json` only, never `hub.local.json` or git config, so rendered files
and `hub.lock` are the same for every developer. With both author keys and the prefix in `hub.json`, `AGENTS.md` and
`marketplace.json` are byte-identical to before. Otherwise:

- `AGENTS.md` rule 1: when `hub.json` lacks either author key, commits are authored by the developer running the
  session (`hub.local.json`, else their git config); when it lacks the prefix, branches read `<prefix>…`, with a note
  that `<prefix>` is `hub.local.json` → `project.branch_prefix`, else the local part of the author email plus `/`.
- `marketplace.json`'s owner is `{"name": author_name or project.name}`, with `email` only when `hub.json` sets it.

### Doctor

- `config.schema` reports each `hub.local.json` problem as an error at path `hub.local.json`, fix
  `fix hub.local.json (docs/design/developer-identity.md)`. On a `platform.version` mismatch it reports none.
- `config.identity` (info; can be disabled, cannot be retuned) reports a derived prefix:
  ``branch prefix `jane/` is derived from git config user.email (hub.local.json and hub.json set none)``, fix `set
  project.branch_prefix in hub.local.json to choose another`. It is the only rule that reads git for identity.
- File rules use `hub.json` values only; `instructions.refs` never checks the exact reference `hub.local.json`.

### Cloud setup

With `project.author_name` and `project.author_email` in `hub.json`, `scripts/cloud-setup.sh` is unchanged (global and
repo-local). Otherwise it reads `HUB_AUTHOR_NAME` and `HUB_AUTHOR_EMAIL` (set per developer in their cloud
environment). When both are non-empty, valid UTF-8 and free of control characters, it writes them repo-local in the
hub and each repo, never global, and prints `cloud-setup: git identity (repo-local, from
HUB_AUTHOR_NAME/HUB_AUTHOR_EMAIL) = <name> <email>`. Else it prints `cloud-setup: WARN no commit author in hub.json or
HUB_AUTHOR_NAME/HUB_AUTHOR_EMAIL; commits carry the container's identity`, writes nothing and goes on (exit 0).

## Invariants

- One rule, two readers: core `effective_identity.resolve_identity` (git behind a `GitReader` the CLI supplies) and the
  hooks' `EffectiveValues`. The shared cases in `agent_hub.core.testing.identity_cases` run against both
  (`test_identity_parity.py`, the hooks on the current Python and on 3.9).
- Committed files never depend on who runs `hub sync`; `hub.local.json` is never rendered, locked or committed.
- A hub that keeps the identity in `hub.json` runs no extra git call in the CLI and keeps its rendered bytes.
- A hook never fails because of `hub.local.json` or git.

## Decisions

- [ADR 0016](../adr/0016-per-developer-identity.md): `hub.local.json`, then `hub.json`, then git config; rendering
  reads `hub.json` only; cloud setup writes an env identity repo-local.
- [ADR 0010](../adr/0010-hub-json-config-contract.md): the `hub.json` contract; optional keys are additive under
  `schema_version: 1`.

## Open questions

- A team mode for `hub init` (no identity in `hub.json`, a `hub.local.json` for the first developer): `hub setup`,
  AGH-71.
- Whether doctor should also report no prefix at all (`hub worktree` and `hub run` would refuse).
