# Using agent-hub for another project

A runbook for an agent: from nothing to a verified hub, committed and pushed once, then into a session and `/onboard`.
Run the steps in order. Every command sits in an `sh` block, one command per line; replace each `<…>` placeholder with
its value before you run the line. `make check` runs these lines against the CLI (`tests/e2e/test_using_guide.py`), so
a line that drifts from the CLI fails agent-hub's own build.

## Who this is for

You are an agent asked to set up or run an agent hub for a project that is **not** agent-hub. The rules in
agent-hub's `AGENTS.md` (authorship, `roquettejh/` branches, `docs/SPEC.md` first) are for changing agent-hub and do
not apply to your project. Your project's rules come from its own hub once it exists: `hub.json`, the rendered
`AGENTS.md` and `AGENTS.project.md`. A teammate joining a project whose hub already exists clones that hub into the
folder that holds (or will hold) the project's repos, so they sit side by side, then runs `./hub setup` in it instead
(it exits 0 when every line is `ok`; each `missing` line names its fix); the rest of this guide creates a new hub.

## Prerequisites and access

- uv 0.9.0 or newer, git 2.28 or newer (for `git init -b`), `python3` 3.9 or newer and `claude` (Claude Code).
- `gh` (GitHub CLI), logged in, is optional: it creates the hub's repo and checks that it is private. Without it, the
  user does those two things (§ Commit and push once).
- agent-hub is public: its `uvx` lines need no credential (unless the hub's `hub.json` → `platform.repository` names
  another source). The hub's repo and the app repos need the user's git credentials through a credential helper, for
  example the one `gh auth setup-git` sets up:

  ```sh
  gh auth setup-git
  ```

  or work in a cloud session that has those repos attached. Either way, never put a token in the URL, in a file or in
  a command line.

## Find the version and check the CLI

Every command below names the release as `v<version>`. Find it first, before any `uvx` line:

```sh
git ls-remote --tags --refs https://github.com/jroquette/agent-hub 'v*'
```

Take the highest semver tag it lists (compare numbers, not text: `v0.10.0` is above `v0.9.0`) and use it without its
`v` as `<version>`. When the project already has a hub, use that hub's `platform.version` from its `hub.json` instead.
Never copy a version from this guide or from memory.

Then check that the CLI runs at that version; it prints `<version>`:

```sh
uvx --from 'git+https://github.com/jroquette/agent-hub@v<version>#subdirectory=packages/agent-hub' hub --version
```

## Make the workspace and an empty hub folder

The workspace is one folder holding the hub and a checkout of each app repo next to it: the hub finds the repos at
`../<dir>`, where `<dir>` is the repo's name. Make the workspace, clone each app repo into it (one `git clone` per repo
of `--repos`; `<repo-url>` is the repo's clone URL), then make a **new, empty** folder for the hub and start git in it:

```sh
mkdir -p <workspace>
cd <workspace>
git clone <repo-url>
mkdir <workspace>/<hub>
cd <workspace>/<hub>
git init -b main
```

`<hub>` is the hub folder's name, usually `<project>-hub`. The folder must not exist before: `hub init` refuses a
folder that holds files it does not know (§ When init refuses).

## Create the hub

Run init once, from the hub folder, with the values you know. Ask the user for the ones you do not know, one question
at a time, and never guess them:

- `<project>`: the project's name.
- `<org>/<repo>`: the app repos, comma-separated (`acme/api,acme/web`).
- `<tracker>`: the task tracker and its team key(s), for example `linear:APP` or `linear:APP,OPS`.
- `<prefix>`: the prefix of every branch, for example `jdoe/`. Ask the user.
- `<owner>/<name>`: the hub's own GitHub repo, for example `acme/acme-hub`. Ask the user.
- `<author_name>` and `<author_email>`: who authors commits and PRs, the user and never you. Ask the user.

```sh
uvx --from 'git+https://github.com/jroquette/agent-hub@v<version>#subdirectory=packages/agent-hub' hub init <project> \
  --repos <org>/<repo> \
  --tracker <tracker> \
  --branch-prefix <prefix> \
  --hub-repo <owner>/<name> \
  --author-name "<author_name>" \
  --author-email <author_email> \
  --dir <workspace>/<hub>
```

It exits 0, and its first line starts `created ` and counts the files and links it wrote. Init then prints its own
`Next steps:`; ignore them (their commit would use your identity) and follow this guide (§ Commit and push once).
When the user gives you a `hub.json` for a new hub, pass `--config <path to hub.json>` instead of the project name and
the value flags. When the project already has a hub (on another machine, or on GitHub), do not init: see § When init
refuses. Init writes only what is needed to start: project rules, gates and onboarding come later, from `/onboard`
(§ Open a session and run /onboard).

## When init refuses

Init exits 1 and changes nothing when the folder is not new. Read its stderr line.

The folder is already a hub:

```text
hub.lock: this folder is already a hub; run hub sync
```

Do not init again. If this is the folder you made in § Make the workspace and an empty hub folder (init ran there
already), run `./hub sync`, then go on to § Verify the hub. It prints `up to date` when there is nothing to do:

```sh
./hub sync
```

Otherwise the hub existed before this run, here or on another machine or on GitHub: clone the hub repo next to the app
repos and work in that clone, where `./hub sync` brings it up to date. § Commit and push once does not apply to such a
hub. Commit any changes `./hub sync` makes on a new branch named with the hub's branch prefix (`hub.json` →
`project.branch_prefix`) and land them through a PR the user merges. Never commit on `main`, and never run
`git add -A` over files you do not know: add only the paths `./hub sync` printed.

The folder holds a file the hub does not know, and no `hub.json`:

```text
<path>: not part of the hub; run hub sync --adopt
```

Here, start again in a new, empty folder (§ Make the workspace and an empty hub folder). Do **not** run
`hub sync --adopt` there: with no `hub.json` it exits 1, and its last stderr line is

```text
hub.json: run hub sync in the hub folder
```

`--adopt` is only for a hand-made hub that already holds a `hub.json` (a hub made before agent-hub, or one whose
`hub.lock` was lost). From that hub's folder:

```sh
uvx --from 'git+https://github.com/jroquette/agent-hub@v<version>#subdirectory=packages/agent-hub' hub sync --adopt
```

`hub sync --adopt` exits `0` (every file settled: its last line is `updated hub.lock`, or `up to date` on a second run), `1` (an error in `hub.json`, `hub.lock` or a file it reads: fix the named input), `2` (a usage error) or `3` (it lists files that differ from the templates, or conflicts: show the user the list; never pass `--accept` without the user's agreement).

## Verify the hub

From the hub folder, run the doctor and the sync check. Both write nothing:

```sh
./hub doctor --json
./hub sync --check
```

`./hub doctor --json` exits `0` (no error finding: go on), `1` (at least one error finding: fix each one its `message` names, then run it again) or `2` (a usage error, or the folder is not a hub: run it from the hub folder).

`./hub sync --check` exits `0` (up to date: go on), `4` (changes pending: run `./hub sync`, then check again), `3` (a conflict: show the user the listed paths and the way out it prints) or `1` (an error: fix the named input, such as `hub.json` or `hub.lock`).

Go on only when both exit 0.

## Commit and push once

This section is only for a hub created in this run, in a new, empty folder; any other hub changes through a PR (§ When
init refuses). Commit the new hub as the user. The author is `hub.json` → `project.author_name` and
`project.author_email`; when `hub.json` holds no author, ask the user. Never use your own identity, and add no AI
trailer (no `Co-Authored-By`, no "Generated with"):

```sh
git add -A
git -c user.name="<author_name>" -c user.email=<author_email> commit -m 'Create the hub'
```

Then push this commit once. This is a narrow exception to "no push to the default branch": it covers only the very
first commit of a hub repo that is empty on the remote, on a private repo, never forced. Do it before any session in
the hub: the hub's guard denies pushes to the default branch, and the guard is not changed for this. Everything after
goes through PRs.

`<remote>` is the hub repo's URL, `https://github.com/<owner>/<name>.git`. Pick the case that holds:

- No remote yet and `gh` works: create it private. If `gh repo create` fails (for example, the name already exists,
  maybe public), stop and tell the user.

  ```sh
  gh repo create <owner>/<name> --private
  ```

- No remote yet and no `gh` (or no `gh` login): stop and ask the user to create an empty private repo `<owner>/<name>`,
  then go on with the privacy check and the emptiness check.
- The user made the remote: go on with the privacy check and the emptiness check.

Privacy check, always. It must print `PRIVATE`, else stop and tell the user. Without `gh`, ask the user to confirm that
the repo is private:

```sh
gh repo view <owner>/<name> --json visibility --jq .visibility
```

Emptiness check, always. It must exit 0 and print nothing (no branches, no tags). Any output means stop and tell the
user: never push over an existing history. Any other exit (`128`: no access, or no such repo) means stop too:

```sh
git ls-remote <remote>
```

Then push, with no `--force`:

```sh
git remote add origin <remote>
git push -u origin main
```

## Open a session and run /onboard

Open a Claude Code session in the hub, with every app repo attached:

```sh
./agent
```

Then type `/onboard` in that session. It reads each repo read-only, proposes the project rules (`AGENTS.project.md`)
and the `hub.json` values (gates and more) with the evidence for each, and applies them only after the user approves.

With no human present, run it headless. It only writes its proposal to `brain/_inbox/onboard-proposal.md` and stops:

```sh
./agent -p "/onboard propose"
```

A human then reads the proposal and sets its `status` to `approved`, and `/onboard apply` runs in a session (`./agent`).

`/onboard` needs a hub whose `.claude/skills/onboard` exists. If it does not, the hub's release is older than
`/onboard`: raise `platform.version` in `hub.json` to the version of § Find the version and check the CLI, run
`./hub sync`, and commit that change through a PR. If the newest release has no `.claude/skills/onboard` either, stop
and tell the user; do not try other versions.

### Run the control plane

The control plane (`hub web`) shows the hub's sessions, runs, approvals and health; old `/live` links open the Sessions
grid. It serves on `127.0.0.1` only, port 7420 by default. Run it one of two ways, on the same machine as the sessions:

- **Locally:** `./hub web` from the hub folder (the pinned release, through the shim). It prints the address to
  open, `http://127.0.0.1:7420/?token=…` (a new token each start; `--open` opens it). Ctrl C stops it.
- **In Docker:** in a clone of agent-hub at the hub's release (`git clone --branch v<version>` into the workspace),
  `make up` builds the image and starts it, published on `127.0.0.1:7420` only; the workspace folder is mounted
  read-only so the server can read the hubs in it, and `~/.claude/projects` for the transcripts. `make down` stops
  it (its data volume stays); `make logs` and `make ps` show it. The variables are in that clone's `.env.example`.

Register the hub once, with its absolute path: in the app under Settings › Hubs, or, from the agent-hub clone,
`make connect HUB=<workspace>/<hub>`, which also checks that the hub has the event sensor and says what to do when it
does not. The hub's hooks then send each session's events as they happen; without the control plane running they do
nothing and the session is unaffected. Older work can be added once: `./hub collect --transcript <file>` for a
transcript under `~/.claude/projects/`, and `./hub collect --runs .agent-runs` for `hub run` records. Only metadata
is stored (sizes, tools, repo-relative paths, short commands with secrets redacted, and for a failed tool its error
text, redacted and cut at 300 characters), never prompt, output or file text.

Each session is shown by its issue and workflow (`DEMO-1511 · /feature`), read from its branch or task worktree name and
the hub's tracker team; each failure says what failed, where, which agent, and whether the agent handled it or it needs
you. To read the brain, open Knowledge › Brain (or a project's Brain): it lists the hub's `brain/` notes (never
`brain/auto/`) and renders any one, with links between notes; a feature's Spec, Research, Plan, Eval and Criteria tabs
show its records. The app reads the registered hub's checkout as it is on disk, so pull the hub to see merged changes.

The Skills tab (Knowledge › Skills, or a project's Skills) lists the hub's skills, agents and hooks with how each is
invoked, whether it is managed or the project's, and how often it was used in the last 30 days; a skill's page shows
its text (rendered or raw), the steps, agents and commands derived from it, its bundled files and its diagnostics
(for example "not linked yet: run hub sync"). It only reads the hub's files: nothing is run.

A feature's Tickets tab shows each ticket's title, status, assignee, Linear link and blockers, what can start now and
in which order, and its golden path says which step the whole feature has reached. For live status, `hub web` reads
Linear's API itself, read-only, with the `LINEAR_API_KEY` of the environment it runs in (the same key `hub next` and
`hub run` use; never in `hub.json`), and only when the Tickets tab is opened. Locally, export the key in the shell that
runs `./hub web`. In Docker, export it in the shell that runs `make up`: `compose.yaml` passes `LINEAR_API_KEY` from
that environment into the container and holds no value itself (keep it out of `.env`). Without a key, or for a hub
whose `tracker.transport` is `"mcp"` (the app never reads Linear through MCP), the tab shows the plan from
`features.json` with a notice that status may be stale; when a read fails, it says why and shows Linear's last good
read for up to 15 minutes.

Knowledge › Learnings shows each inbox note and can accept or reject it. Neither changes the brain or the user's
checkout: each opens a pull request in the hub repo (branch `<branch_prefix>learning-<accept|reject>-<note>`,
authored as the hub's author), and nothing changes until the user merges it. That needs, on the machine running
`hub web`, a writable hub checkout whose `origin` is the hub's GitHub repo, `git`, and `gh` signed in to GitHub (the
PR is opened as that `gh` account). Under Docker the hubs are mounted read-only, so both actions are disabled with
"Hub is read-only here"; run `./hub web` locally to decide learnings. Workflows: [README](../README.md#-workflows).

**Sessions from the app.** On the Sessions screen, New session starts the user's own `claude` (on `PATH`, logged in)
in the hub, a repo or one of their worktrees, with the hub's CLAUDE.md, hooks (the guard still applies), skills and
agents; the chat sends messages, answers permission prompts, interrupts, changes mode and model, resumes and forks.
It needs the `sessions` extra (the Claude Agent SDK, about 240 MiB): from the hub folder, run `uvx --from
'agent-hub[sessions] @ git+https://github.com/jroquette/agent-hub@v<version>#subdirectory=packages/agent-hub' hub web`
instead of `./hub web`; without it the screen says what is missing. Open the printed address once per browser: the
token becomes a cookie the session routes need. Limits are `hub web` options with `AGENT_HUB_*` variables (`hub web
--help`; 4 live sessions, 30 min idle, 10 min to answer a prompt). Their conversations are kept, redacted, in `hub
web`'s database for 30 days after they end (Delete removes one at once). Off in Docker. From another device, keep
`hub web` on loopback and bring the port to it: `ssh -L 7420:127.0.0.1:7420 <host>`, or `tailscale serve` to
`http://127.0.0.1:7420` on your own tailnet, then open the token address there; never Tailscale Funnel, ngrok or
`--host 0.0.0.0`. Claude's Remote Control also reaches a session from a phone. Cloud sessions (claude.ai/code) are not
driven from the app: it gives the `claude --cloud` command, then the session's link and `claude --teleport <id>`.

Release notes, for reviewing the sync PR's diff. Control plane: `./hub sync` adds the hook `event_sensor.py` and
rewrites `hooks.json`, `.claude/settings.json` (the sensor joins eleven hook events), `guard.py`, `stop_gate.py` and
`hubhooks.py`, decisions unchanged. Read-only gate (AGH-141): adds the hook `readonly_gate.py` and rewrites
`hooks.json`, `.claude/settings.json` and the researcher, spec-reviewer and quality-reviewer (`mutates_checkout: false`,
which any agent may add); one that changes a checkout is held at its stop once, or the change is reported.
