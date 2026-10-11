# Hub setup: one-command onboarding of a developer's machine

## Purpose

A developer (or an agent) joining a project clones its hub next to the repos' folder and runs `./hub setup` there. It
checks the tools and the tracker credential, writes the developer's `hub.local.json` when the hub needs one, clones the
missing repos and fetches the present ones, runs `hub doctor`, and lists what is still missing, each with its fix. This
is the contract for its options, output, writes, git environment and exit codes (AGH-71).

## Contract

### Command

- `hub setup [--yes]`, run as `./hub setup` from the hub. `--yes` (write a new `hub.local.json` without asking) is the
  only option, besides `--help`; no `--json`, `--only` or `--no-fetch`.
- Root: `AGENT_HUB_ROOT` when `./hub` exports it, else the cwd. No `hub.json` there: exit 2 with `<root>: not a hub: no
  hub.json in this folder (hub setup runs in the hub folder or through ./hub)`. `hub.json` is read once; any problem,
  a `platform.version` pin other than the running release included, prints the reader's lines and exits 1 before any
  git call. Repos are cloned next to the root (`<root>/../<dir>`); `hub.local.json` is read and written in the identity
  home, the main checkout ([developer-identity.md](developer-identity.md)).
- Sections run and print in this order, each whatever failed before: tools, identity (then `gitignore`), repos, `hub
  doctor`. The only prompt comes before the network step, so the rest runs unattended.

### Output

Stdout holds only the checklist, each item printed as soon as it is decided: `<state> <item>: <detail>[ Fix: <fix>]`,
`<state>` being `ok` or `missing` padded to 7 columns plus one space. Sub-lines (doctor findings, `hub.local.json`
problems, no-prefix reasons, git's problem) follow their item, indented 8 spaces. The last line is `setup: <n> ok`, or
`setup: <m> missing, <n> ok` (items, not sub-lines). Stderr holds the identity proposal (`hub setup: proposed
hub.local.json in <home>: <values> (<sources>)`), the prompt (`Write <home>/hub.local.json? [y/N] `) and the usage,
not-a-hub and config errors. A team hub, `demo-web` missing, an SSH origin, `--yes`, `gh` not logged in, no key:

```text
ok      uv: 0.9.5
ok      git: on PATH
ok      python3: 3.12.4
ok      claude: on PATH
missing gh: gh auth status exited 1 Fix: gh auth login
missing tracker: LINEAR_API_KEY is not set (transport api) Fix: export LINEAR_API_KEY=<your Linear API key>, or set tracker.transport "mcp" in hub.local.json
ok      identity: wrote hub.local.json: jane/, Jane Roe <jane@example.com> (git config)
ok      repo demo-api: present, fetched
ok      repo demo-web: cloned acme/demo-web into ../demo-web (ssh)
ok      hub doctor: 0 errors, 1 warning, 0 infos
        warning makefile.override Makefile.project:3: redefines target 'check' Fix: rename the project target
setup: 2 missing, 8 ok
```

| Item | `ok` detail | `missing` detail → Fix |
|---|---|---|
| `uv` | `<X.Y.Z>` | `not on PATH` → `curl -LsSf https://astral.sh/uv/install.sh \| sh`; `<X.Y.Z>, need 0.9.0 or newer` → `uv self update`; `cannot read its version` / `timed out after 10 s` → `uv --version` |
| `git` | `on PATH` | `not on PATH` → `install git 2.28 or newer (https://git-scm.com/downloads)` |
| `python3` | `<X.Y.Z>` | `not on PATH` / `<X.Y.Z>, need 3.9 or newer` → `install Python 3.9 or newer as python3 (https://www.python.org/downloads/)`; unreadable / timed out as `uv` → `python3 --version` |
| `claude` | `on PATH` | `not on PATH` → `install Claude Code (https://docs.anthropic.com/en/docs/claude-code/setup)` |
| `gh` | `logged in` | `not on PATH` → `install the GitHub CLI (https://cli.github.com), then gh auth login`; `gh auth status exited <n>` / `timed out after 10 s` / `cannot run gh auth status` → `gh auth login` |
| `tracker` | `LINEAR_API_KEY set (transport api)`; `transport mcp: Linear through claude -p (its Linear MCP server is not checked)` | `LINEAR_API_KEY is not set (transport api)` → as the sample; `transport mcp needs claude on PATH` → the `claude` fix |
| `identity` | `wrote hub.local.json: <values> (<sources>)` (the written keys only); `<values> (<sources>)`, sources distinct in key order | below |
| `gitignore` | no line | `hub.local.json is not ignored by git` → `add the line hub.local.json to .gitignore and commit it; if git tracks it, also git rm --cached hub.local.json` |
| `repo <dir>` | `present, fetched`; `cloned <owner/name> into ../<dir> (<ssh\|https>)` | below |
| `hub doctor` | its totals line | its totals line → `fix each error below, then ./hub doctor`; its finding lines as sub-lines in both states |

`<values>` is the prefix, then `<name> <<email>>`, each escaped by `one_line`. Identity gaps, with their Fix:

- `hub.local.json not written (declined)` / `(stdin is not a terminal)` → `./hub setup --yes, or write hub.local.json
  yourself (docs/design/developer-identity.md)`; `could not write hub.local.json: <strerror>` → the same.
- `hub.local.json not written (larger than 65536 bytes)` → `shorten git's user.name or user.email in the hub, then
  ./hub setup`; `hub.local.json appeared while writing; left as is` → `./hub setup`.
- `git config in the hub has no user.name` (`user.email`, or `user.name or user.email`), `git's user.email is not an
  email address`, `git's user.name holds a control character` (joined by `; `) → the matching `git config user.name
  "<Your Name>"` and/or `git config user.email <you@example.com>`, joined by ` and `, then `, then ./hub setup`; when
  git gave no answer, a sub-line `git: git not found` / `git: git timed out`.
- `<giver> gives "<local part>", not a valid branch prefix`, where `<giver>` is `git's user.email`, `hub.json's
  project.author_email` or `hub.local.json's project.author_email`, and `no branch prefix` (with the `no_prefix_lines`
  sub-lines) → `write hub.local.json with project.branch_prefix (docs/design/developer-identity.md)`.
- `hub.local.json is invalid` (one sub-line per problem) → `fix hub.local.json (docs/design/developer-identity.md)`.

Repo gaps, with their Fix:

- `clone failed (git exit <n>)` / `clone timed out after 600 s` → `check that your git credentials can read
  github.com/<owner/name> (e.g. gh auth setup-git), then ./hub setup`.
- `fetch failed (git exit <n>)` / `fetch timed out after 600 s` → `git -C ../<dir> fetch origin`.
- `../<dir> exists but is not a git repository; left untouched` and `../<dir> has no commit (an interrupted clone?)` →
  `move ../<dir> away, then ./hub setup`.
- `git not found` / `git could not run` → the `git` fix.

### Steps and what they write

- **Tools.** `uv --version` (≥ 0.9.0), `python3 --version` (≥ 3.9), `gh auth status` (exit 0), each at most 10 s with
  4,096 bytes of stdout kept; `git` and `claude` on `PATH`. A version is the first `X.Y.Z` with 1 to 6 digits per part.
  The tracker item reads the effective `tracker.transport` (`hub.local.json` over `hub.json`) and only whether
  `LINEAR_API_KEY` is set and non-empty.
- **Identity.** An existing `hub.local.json` (valid or not), or a `hub.json` setting all three identity keys, is never
  written: the item resolves the identity (git read only for keys no file sets). Else the keys `hub.json` leaves unset
  are proposed from the hub's git config; with every one valid, `--yes`, or `y`/`yes` at the prompt on a terminal,
  writes `{"project": {…}}` (keys in the order `branch_prefix`, `author_name`, `author_email`, indent 2, UTF-8, mode
  0644) through a temporary file linked to `hub.local.json`, which fails if a file appeared. An answer cut at 64 bytes
  or not UTF-8 is a no. Then, when the file exists, `git -C <home> check-ignore -q hub.local.json` exiting 1
  gives the `gitignore` item; any other outcome gives no line.
- **Repos.** Per `repos` entry, in `hub.json` order, at `<root>/../<dir>`: no entry → `git clone --quiet <url>`, the
  url over the hub origin's scheme (`git@github.com:<owner/name>.git` when `origin` is a GitHub SSH remote, else
  `https://github.com/<owner/name>.git`); a folder, or a link to one, holding `.git` → `git -C ../<dir> rev-parse
  --verify -q HEAD`, then, on exit 0, `git -C ../<dir> fetch --quiet origin`; anything else is reported, never touched.
  The commit check's exit 1 is `has no commit`, any other failing exit `not a git repository`, and its timeout (10 s,
  a local read) is reported as `fetch timed out after 10 s`, the fetch never having run. Clones and fetches are cut at
  600 s, their process group killed. Only git's exit code is read.
- **Doctor.** `hub doctor`'s check runs in process on the root, whatever the cwd, with its own reads and rules.
- Setup writes only the clones into absent entries and a new `hub.local.json`; it deletes nothing.

### Git environment

Setup's own git calls (scheme read, check-ignore, clone, commit check, fetch) run with stdin from `/dev/null`,
`GIT_TERMINAL_PROMPT=0`, no git location variable (`GIT_DIR` and the like) and no `LINEAR_API_KEY`; nothing else is
added, so the developer's own config and credentials answer. Every call aimed at `../<dir>` also sets
`GIT_CEILING_DIRECTORIES` to the workspace (the root's parent), so git never runs in a repo above `../<dir>`. The
scheme read runs only when `<home>/.git` exists, with the ceiling at the home's parent.

### Exit codes and seams

0 when every item is `ok`; 1 after the full checklist when any is `missing`, or for an invalid `hub.json`; 2 for a
usage error or not a hub. Tests replace three module-level seams, none a flag or a variable and none public:
`setup_tools.tool_probe` (the tool probe factory), `setup_identity.stdin_is_tty` and
`setup_repos.NETWORK_TIMEOUT_SECONDS`.

## Invariants

- Never overwrites: `hub.local.json`, `.gitignore`, `hub.json`, git config, a working tree and any existing
  `../<dir>` entry stay as they are; a re-run after a clean run clones nothing and writes nothing.
- No credential is read beyond `LINEAR_API_KEY`'s presence, asked for or shown; no remote URL, built URL or git output
  is printed (lines name `<owner/name>` and the scheme only).
- `hub doctor` is unchanged and stays read-only and network-free; setup calls its check.
- Rendered files are unchanged: setup and the generator's repo lists (`repo_dirs`, `repo_githubs`) share
  `workspace_repos`.

## Decisions

- [ADR 0016](../adr/0016-per-developer-identity.md) and [developer-identity.md](developer-identity.md): the precedence
  and the `hub.local.json` format setup writes.
- [ADR 0002](../adr/0002-lean-hexagonal-architecture.md), [ADR 0008](../adr/0008-cli-as-composition-root.md): the
  checklist texts, version rule and exit rule are pure core (`workspace/setup_checklist.py`); subprocesses, the
  prompt and the write are in `cli`; the tool probe is a cli Protocol, not a port.
- AGH-71 spec decisions D-cmd, D-order, D-repos, D-url, D-id, D-write, D-ignore, D-tools, D-doctor, D-exit, D-shared.

## Open questions

- SSH prompts: `GIT_TERMINAL_PROMPT=0` does not stop `ssh` asking for a passphrase or host key; the 600 s timeout ends
  it (Q-5).
- Whether to report a present repo whose `origin` is not `repos[].github` (Q-7).
- Machine checks in `hub doctor` (AGH-66) and a team mode for `hub init` (F-1).
