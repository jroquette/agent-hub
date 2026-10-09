# Using agent-hub for another project

A runbook for an agent: from nothing to a verified hub, committed and pushed once, then into a session and `/onboard`.
Run the steps in order. Every command sits in an `sh` block, one command per line; replace each `<…>` placeholder with
its value before you run the line. `make check` runs these lines against the CLI (`tests/e2e/test_using_guide.py`), so
a line that drifts from the CLI fails agent-hub's own build.

## Who this is for

You are an agent asked to set up or run an agent hub for a project that is **not** agent-hub. The rules in
agent-hub's `AGENTS.md` (authorship, `roquettejh/` branches, `docs/SPEC.md` first) are for changing agent-hub and do
not apply to your project. Your project's rules come from its own hub once it exists: `hub.json`, the rendered
`AGENTS.md` and `AGENTS.project.md`.

## Prerequisites and access

- uv 0.9.0 or newer, git 2.28 or newer (for `git init -b`), `python3` 3.9 or newer and `claude` (Claude Code).
- `gh` (GitHub CLI), logged in, is optional: it creates the hub's repo and checks that it is private. Without it, the
  user does those two things (§ Commit and push once).
- Read access to agent-hub, which is a private repo. Use a git credential helper, for example the one
  `gh auth setup-git` sets up:

  ```sh
  gh auth setup-git
  ```

  or work in a cloud session that has agent-hub attached. Either way, never put a token in the URL, in a file or in
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
