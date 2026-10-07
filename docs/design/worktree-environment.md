# Worktree environment: what a repo's setup and teardown scripts get

## Purpose

A task worktree of a repo that runs services (an API, a database, a web UI) collides with the main checkout and with
other task worktrees on ports, compose projects and `.env` values. A repo can ship executable
`scripts/worktree-setup.sh` and `scripts/worktree-teardown.sh` to give each worktree its own. This is the contract for
how `hub worktree` and `hub run` run them and what they get, so a script needs no scheme of its own to tell which task
it serves, where the main checkout and the hub are, and which ports to use. The commands themselves are in the
[README](../../README.md) and [SPEC.md](../SPEC.md); the steps are `agent_hub.cli.worktree_steps`.

## Contract

### When the scripts run

- **Setup** runs once, right after `git worktree add` creates the repo's worktree, in `hub worktree <name>` and in
  `hub run` (which makes the worktree of its issue). It never runs on a worktree that already exists: a rerun prints
  `exists` and leaves it alone.
- **Teardown** runs in `hub worktree --remove <name>` only, before `git worktree remove`, and only on a clean worktree:
  one with modified or untracked files is refused before the teardown runs. `hub run` never removes a worktree.
- A script runs only when it is an executable regular file in the new worktree (the repo's committed copy); otherwise
  it is skipped without a word. Its argv is `[<worktree>]` (`$1`), its cwd is the worktree, it has no timeout and runs
  in the caller's process group (Ctrl-C reaches it). Each line it prints on stdout is shown as `  <repo>: <line>`;
  its stderr passes through unprefixed.
- A setup that fails (non-zero exit, a signal, or it cannot start) stops the command with exit 1 and keeps the
  worktree, with a hint to run the script again or remove the worktree. A failed teardown keeps that repo's worktree
  (repos handled before it are already removed).

### Environment

The caller's environment, minus git's location variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, …), plus
six variables set last, so a caller's value of any of them is overridden:

| Variable | Value | `dem-7-x`, repo `demo-api` |
|---|---|---|
| `HUB_WORKTREE_NAME` | the task's worktree name (`hub run`: its slug) | `dem-7-x` |
| `HUB_WORKTREE_BRANCH` | this repo's task branch (it can differ per repo through `conventions`) | `jdoe/dem-7-x` |
| `HUB_REPO_DIR` | the repo's main checkout `<workspace>/<repo>`, not the worktree (that is `$1`) | `/ws/demo-api` |
| `HUB_HUB_DIR` | the hub's main checkout, also when the command runs from a hub worktree | `/ws/hub` |
| `HUB_WORKTREE_SLOT` | the task's port slot, `0` to `49`, in decimal | `34` |
| `HUB_PORT_OFFSET` | slot × 100, `0` to `4900`, in decimal: add it to each of the repo's ports | `3400` |

- `HUB_REPO_DIR` and `HUB_HUB_DIR` are absolute and built on the hub's real path (its links resolved).
- **Slot:** `int(sha256(name).hexdigest(), 16) % 50`, the SHA-256 of the name's UTF-8 bytes read as one big-endian
  integer, from the whole worktree name (`core.workspace.worktree_slot`). **Offset:** `slot * 100`.
- In `hub worktree` every other variable is the developer's shell environment, tokens included. In `hub run` the
  setup script gets no `LINEAR_API_KEY`, `GH_TOKEN` or `GITHUB_TOKEN` (SPEC, secret scope of `hub run`).

### Collisions and overrides

Nothing allocates or locks a slot. Two names share one with probability 1/50, and the slot comes from the whole name,
so `dem-7-x` and `dem-7-y`, or `hub worktree dem-1-x` and `hub run`'s `dem-1`, get different slots, while the same
name always gets the same one. On a collision, edit the worktree's `.env`: it is the script's own copy, and setup never
reruns on an existing worktree, so the edit stays. Ports stay below 65536 for any base port up to 60535.

### Example scripts

A repo that keeps a gitignored `.env` in its main checkout and runs its services with `docker compose`. Both scripts
are POSIX `sh` and name the compose project `<repo>-<name>`. **The repo's `.gitignore` must list `.env`**: the copy
would otherwise be an untracked file, and `--remove` refuses a dirty worktree before the teardown runs.

`scripts/worktree-setup.sh` copies `$HUB_REPO_DIR/.env` into the worktree, every `<NAME>_PORT=<number>` line shifted by
`$HUB_PORT_OFFSET`, and sets `COMPOSE_PROJECT_NAME` (dropping a copied `COMPOSE_PROJECT_NAME=…` line). Only a line of
the exact form `<NAME>_PORT=<digits>`, `<NAME>` in upper case, is shifted: a quoted value, spaces around `=`, an inline
comment, `export`, a CRLF ending or a bare `PORT` is copied unshifted, so write the ports in that form:

```sh
#!/bin/sh
# worktree-setup.sh <worktree>: hub worktree runs it once, in the new worktree.
set -eu
project="$(basename "$HUB_REPO_DIR")-$HUB_WORKTREE_NAME"
if [ -f "$HUB_REPO_DIR/.env" ]; then
  awk -v offset="$HUB_PORT_OFFSET" '
    /^COMPOSE_PROJECT_NAME=/ { next }
    /^[A-Z0-9_]*_PORT=[0-9]+$/ { i = index($0, "="); print substr($0, 1, i) (substr($0, i + 1) + offset); next }
    { print }
  ' "$HUB_REPO_DIR/.env" > .env
else
  : > .env
fi
printf 'COMPOSE_PROJECT_NAME=%s\n' "$project" >> .env
```

`scripts/worktree-teardown.sh` runs `docker compose down` under the same project name, and does nothing without
`docker`. It fails closed: if `docker` is installed but `docker compose down` fails (daemon stopped, no compose plugin),
it exits non-zero and `--remove` keeps that repo's worktree; fix docker and rerun, or remove the worktree by hand with
`git worktree remove`:

```sh
#!/bin/sh
# worktree-teardown.sh <worktree>: hub worktree --remove runs it before git worktree remove.
# Runs docker compose down for the worktree's compose project; without docker it does nothing.
set -eu
command -v docker >/dev/null 2>&1 || exit 0
docker compose -p "$(basename "$HUB_REPO_DIR")-$HUB_WORKTREE_NAME" down
```

With `API_PORT=8000` and `WEB_PORT=5173` in the main checkout's `.env`, task `dem-7-x` of `demo-api` gets
`API_PORT=11400`, `WEB_PORT=8573` and `COMPOSE_PROJECT_NAME=demo-api-dem-7-x`.
`test_worktree_command.py::TestScriptEnvironment` runs these two blocks as written, with and without a main
checkout `.env` and `docker`.

## Invariants

- Deterministic and stateless: the six depend on the name, the repo's branch and the two checkouts only. No file,
  lock or tracker write; a rerun computes the same values in every process, machine and Python hash seed (never
  `hash()`).
- One slot per task: every repo of a task gets the same slot and offset; only `HUB_WORKTREE_BRANCH` and
  `HUB_REPO_DIR` differ per repo.
- No secret among the six: they are names, paths and numbers. `hub run`'s script env keeps its secret scope.
- No extra git call or child process; a script that ignores the six behaves as before (argv, cwd, output, failures).

## Decisions

- **Slot from a hash of the name** (D-slot), not an allocation file or lock: stateless, and collisions are accepted.
- **The six variables** (D-vars), for both scripts in both commands; `HUB_WORKTREE_SLOT`, not an index, because it
  promises no uniqueness.
- **`HUB_REPO_DIR` is the main checkout** (D-repodir): the worktree is already `$1` and the cwd, and the main checkout
  is where the gitignored `.env` to copy lives.
- **Set last** (D-override): a caller's `HUB_PORT_OFFSET` never wins. After a collision a person edits the worktree's
  `.env` (setup never reruns on an existing worktree); no script does.
- **No new secret scope** (D-secrets): `hub run` keeps its untrusted environment; `hub worktree` keeps the developer's.
- No ADR: no architecture change. The scope was already in [SPEC.md](../SPEC.md) (isolated worktrees with their own
  ports and `.env`; the secret scope of `hub run`).

## Open questions

- Allocation (unique slots across concurrent tasks), if collisions ever matter: AGH-60.
- A configurable slot count or port step (a `hub.json` key); none is planned.
