# Configuration

## `hub.json`

`hub.json` is the only place with project values. It is plain JSON, validated by the `HubConfig` model, with a JSON
Schema (`hub.schema.json`) for editors. Unknown keys are errors; keys starting with `_` are ignored. Full contract:
[docs/design/project-config.md](design/project-config.md).

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `schema_version` | yes | | Always `1` for now |
| `platform.version` | yes | | The agent-hub release the hub runs (`X.Y.Z`) |
| `platform.repository` | no | `git+https://github.com/jroquette/agent-hub` | The platform's git source, `git+https://<host>/<path>`, e.g. a private fork; the hub runs `<repository>@v<platform.version>#subdirectory=packages/agent-hub` |
| `project.name` | yes | | Kebab-case project name |
| `project.hub_repo` | yes | | GitHub `owner/name` of the hub |
| `project.branch_prefix` | no | per developer | Prefix of every branch, e.g. `jdoe/`; leave it out on a team hub (see `hub.local.json` below) |
| `project.default_branch` | no | `main` | Base of worktrees unless a repo sets its own; the guard blocks pushes to it |
| `project.author_name`, `project.author_email` | no | per developer | Author of commits and PRs; leave them out on a team hub (see `hub.local.json` below) |
| `project.conventions.branch` | no | `{prefix}{issue_lower}-{slug}` | Branch pattern; placeholders `{prefix}`, `{ISSUE}`, `{issue_lower}`, `{slug}`, and it needs `{ISSUE}` or `{issue_lower}` |
| `project.conventions.commit_title` | no | `{type}({scope}): {summary} ({ISSUE})` | Commit title pattern; placeholders `{ISSUE}`, `{type}`, `{scope}`, `{summary}`, and it needs `{summary}` |
| `project.conventions.pr_title` | no | the effective `commit_title` | PR title pattern, with `commit_title`'s placeholders |
| `tracker.kind` | yes | | Task tracker; only `linear` today |
| `tracker.team` | one of the two | | Tracker team key, e.g. `DEMO` |
| `tracker.teams` | one of the two | | Several team keys, the first the default, e.g. `["APP", "OPS"]` |
| `tracker.transport` | no | `api` | How the CLI reaches Linear: `api` (GraphQL with `LINEAR_API_KEY`) or `mcp` (the Linear MCP server through `claude -p`, [ADR 0015](adr/0015-linear-mcp-tracker-transport.md)); `hub.local.json` may set it per developer |
| `tracker.ready_label` | no | `agent-ready` | Label of issues an agent may pick up |
| `tracker.failed_label` | no | `agent-failed` | Label set when an agent run fails |
| `tracker.blocked_label` | no | `tracker.failed_label` | Label set when the run's session stopped to ask a human; create it in the tracker before you set it ([ADR 0030](adr/0030-run-outcomes-in-the-tracker.md)) |
| `tracker.states.started` | no | `In Progress` | State `hub start` moves an issue to: on a fresh start, or on a resume while the issue is unstarted |
| `tracker.states.review` | no | `In Review` | Reserved for the review step; not read yet |
| `repos[].dir` | yes | | Folder name of the repo, next to the hub |
| `repos[].github` | yes | | GitHub `owner/name` |
| `repos[].role` | no | `app` | Free string; `app` is the only known value |
| `repos[].check_fast` | no | | The repo's fast gate command, run by the Stop hook when there is no `check_stop`; unset or blank, and no `check_stop`, the repo has no Stop gate |
| `repos[].check_fast_timeout` | no | `150` | Seconds the Stop hook gives the command it runs, `check_stop` or `check_fast` (1–160, within its 160 s budget) |
| `repos[].check_stop` | no | | A narrower command the Stop hook runs instead of `check_fast` (not blank), with the paths the session changed in `HUB_CHANGED_FILES` ([project-config.md](design/project-config.md)); `hub repo` does not set it yet |
| `repos[].check` | yes | | The repo's full gate command (not blank), run before a PR |
| `repos[].default_branch` | no | `project.default_branch` | Base of the repo's worktrees and PRs; the guard blocks pushes to it |
| `repos[].conventions` | no | | Overrides `project.conventions` for this repo, key by key |
| `guard.ask_before_edit` | no | `[]` | Paths where the guard asks before an edit |
| `guard.deny_paths` | no | `[]` | Paths the guard never lets the agent read or edit |
| `guard.deny_hosts` | no | `[]` | Hosts the guard blocks network calls to |
| `guard.readable_env_files` | no | `[]` | Env file names (`.env.<suffix>`, e.g. `.env.local`) the guard lets agents read and edit; `.env` itself, paths and key files are rejected; `hub doctor` lists them |
| `guard.secret_env_files` | no | `[]` | Env file names the guard always denies, even `.env.staging` or another name of its fixed non-secret list; not also in `readable_env_files` |
| `guard.infra` | no | absent | Present, even `{}`, the guard classifies infra commands by environment (see [the guard](DAILY-WORKFLOW.md#what-the-guard-blocks-and-asks-and-how-to-configure-it)) and `.claude/settings.json` drops its `terraform *` and `aws *` denies (after `./hub sync`); absent, the fixed infra rule |
| `guard.infra.allow` | no | `[]` | Python `re` patterns for allowed environments, e.g. `(?<![^ \t])--profile[= ]demo-dev(?![^ \t])` and `^[ \t]*AWS_PROFILE=demo-dev(?=[ \t])`; bound each by a space or tab (an `AWS_PROFILE` prefix by the part's start), since `\b` also matches `demo-dev.x` or `>--profile=demo-dev` and `\s` also matches a carriage return the shell does not split on |
| `guard.infra.prod_markers` | no | `[]` | Python `re` patterns that mark production; a match anywhere in an infra command blocks it |
| `modules` | no | `{}` | Optional modules (`cloud`, `bench`, `contract-sync`, `marketplace`), from 0.6.0: each selected one renders its files and `mk/<id>.mk`; `contract-sync` takes `{"source": <repo dir>, "target": <repo dir>}`, the others `{}` |
| `doctor.rules` | no | `{}` | Per-rule `hub doctor` settings |
| `models.tiers.small`, `.medium`, `.large` | no | `haiku`, `sonnet`, `opus` | The model each tier names (`^[A-Za-z0-9._-]{1,64}$`, e.g. `claude-opus-4-1-20250805`); each plugin agent renders its tier's model in its `model:` line after `./hub sync`, and `hub run` uses `medium` |
| `models.agents.<agent>` | no | the agent's own tier | Moves one of the 7 plugin agents to another tier, e.g. `{"researcher": "large"}` |

Example (synthetic project):

```jsonc
{
  "$schema": "./hub.schema.json",
  "schema_version": 1,
  "platform": { "version": "X.Y.Z" },          // the release ./hub runs
  "project": {
    "name": "demo",
    "hub_repo": "acme/demo-hub",
    "branch_prefix": "jdoe/",                   // branches: jdoe/<team>-<n>-<desc>
    "author_name": "Jane Doe",
    "author_email": "jane@example.com"
  },
  "tracker": { "kind": "linear", "team": "DEMO" },
  "repos": [
    {
      "dir": "backend",                         // cloned at ../backend
      "github": "acme/backend",
      "check_fast": "make check-fast",          // the Stop hook runs this, unless check_stop is set
      "check_fast_timeout": 120,                // seconds the Stop hook gives it (1–160)
      "check": "make check"                     // the full gate before a PR
    }
  ],
  "guard": { "ask_before_edit": ["backend/docs/adr"] }
}
```

> [!NOTE]
> The comments above are for reading only: `hub.json` is plain JSON and must not contain comments.

## `hub.local.json`

On a hub shared by a team, leave the identity out of `hub.json`: each developer sets their own in a `hub.local.json`
at the root of the hub's main checkout. It is never committed, and only the CLI and the hooks read it, never `hub sync`.
`./hub setup` proposes it from the hub's git config and writes it after asking (`--yes`: without asking); it never
rewrites an existing one.

```json
{"project": {"branch_prefix": "jane/", "author_name": "Jane Roe", "author_email": "jane@example.com"},
 "tracker": {"transport": "mcp"}}
```

- **Keys:** only `project.branch_prefix`, `project.author_name`, `project.author_email` and `tracker.transport`, with
  `hub.json`'s rules, plus `_` comment keys; at most 64 KiB. Any other key is an error (`hub doctor` reports it).
- **Precedence, per key:** `hub.local.json`, else `hub.json`, else the hub repo's `git config user.name`/`user.email`.
  With no prefix in either file, the prefix is your email's local part plus `/` (`jane@example.com` gives `jane/`).
  With none at all, `hub worktree`, `hub run` and `hub start` refuse and name the three sources; `hub setup` reports
  the identity as missing.
- **Existing hubs:** `hub init` writes `hub.local.json` into `.gitignore`, but `.gitignore` is seeded, so `hub sync`
  never adds it. Add the line by hand: `echo hub.local.json >> .gitignore`.
- Nothing in it relaxes the guard: it cannot add or remove a guarded path, host, protected branch or repo.
- **Personal memory (existing hubs):** `hub sync` creates `brain/auto/workspace/.gitkeep` but never rewrites
  `.gitignore`; add both lines: `printf 'brain/auto/workspace/*\n!brain/auto/workspace/.gitkeep\n' >> .gitignore`.
  If a memory file was committed, `git ls-files brain/auto/workspace` lists it; run `git rm --cached -- <file>` for
  each one except `.gitkeep`. It stays on your disk and in history, but teammates who pull that commit lose their
  copy: tell them to copy it out first (or restore it with `git show <commit>~1:<file> > <file>`). `hub doctor`
  warns (`brain.memory`) until both lines are in `.gitignore` and no memory file is tracked.

Contract: [docs/design/developer-identity.md](design/developer-identity.md).

## Environment variables

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `LINEAR_API_KEY` | for `hub next`, `hub run` and `hub start` with `tracker.transport` `"api"` (the default) | | Linear API key, read at call time; never stored in `hub.json`; `hub setup` reports it when missing |
| `AGENT_HUB_DB` | no | `$XDG_DATA_HOME/agent-hub/agent-hub.db`, else `~/.local/share/agent-hub/agent-hub.db` | Event database of `hub collect`; `--db` overrides it |
| `XDG_DATA_HOME` | no | | Used for the default database path when it is absolute |
| `HUB_AUTHOR_NAME`, `HUB_AUTHOR_EMAIL` | no | | Module `cloud`: your commit author in a cloud session, read by `scripts/cloud-setup.sh` only when `hub.json` names no author; written to the repo-local git config of the hub and each repo, never the global one (unset: a `WARN`, and commits carry the container's identity) |
| `AGENT_HUB_CLAUDE_PROJECTS` | no | `~/.claude/projects` | The only folder `hub web` reads transcripts from (absolute path) |
| `AGENT_HUB_ALLOWED_HOSTS` | no | | Extra exact `host[:port]` names `hub web` answers besides its loopback ones (comma list, never `*`) |
| `AGENT_HUB_IN_CONTAINER` | no | | Set to `1` by the agent-hub image only: lets `hub web --host` bind outside loopback inside the container |
| `AGENT_HUB_WEB_URL` | no | `http://127.0.0.1:7420` | Where a hub's event sensor sends events (loopback URLs only) |
| `AGENT_HUB_HUBS_ROOT`, `AGENT_HUB_PORT` | no | the folder holding this clone, `7420` | `make up`: the hubs folder mounted read-only, the host port (on 127.0.0.1) |
| `AGENT_HUB_ROOT` | no | the current folder | The hub folder for `hub setup`, `hub worktree`, `hub brief`, `hub env`, `hub repo`, `hub agent`, `hub start`, `hub next`, `hub run` and `hub bench` (`hub sync` and `hub doctor` use the current folder); the `./hub` shim sets it for you |
| `BENCH_EFFORT` | no | `medium` | Module `bench`: the `effortLevel` of `hub bench`'s sessions, `low`, `medium` or `high` |
