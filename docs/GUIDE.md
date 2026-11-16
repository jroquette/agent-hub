# Usage guide

## Tutorial: from an empty folder to a working session

This is the most common path: a project with two repos tracked in Linear.

1. **Lay out the workspace.** The hub and the repos are siblings, because every repo is found at `../<dir>` from the
   hub:

   ```text
   work/
   ├── demo-hub/   # the hub (this is where you run ./agent)
   ├── backend/    # repos[0].dir in hub.json
   └── frontend/   # repos[1].dir in hub.json
   ```

2. **Generate the hub** with `hub init` ([Quick Start](../README.md#-quick-start), step 3). It writes three kinds of things:
   - **managed** files, owned by the platform and rewritten by `hub sync` (base rules in `AGENTS.md`, the
     `plugin/hub-workflow/` plugin, `.claude/settings.json`, the `./hub` and `./agent` shims, the `Makefile`, whose `next` and `run-issue` targets call `hub next` and
     `hub run`);
   - **seeded** files, written once and then yours (`hub.json`, `AGENTS.project.md`, `Makefile.project`, the `brain/`
     skeleton, the project plugin `plugin/<project>/`);
   - **links** from `.claude/agents/` and `.claude/skills/` into the plugins.

   `hub.lock` records which is which, so later syncs never touch your files. Init also writes an example action and
   scenario (`actions/demo/`, `scenarios/demo/`, [Scenarios](WORKFLOWS.md#scenarios)), each only when absent: they are yours from the start,
   `hub.lock` does not list them and `hub sync` never adds them back.

3. **Make it yours.** Put project rules in `AGENTS.project.md`, project make targets in `Makefile.project`, and the
   current focus in `brain/now.md`. Set each repo's `check_fast` and `check` commands in `hub.json`.

4. **Start each session from the hub.** `./hub brief` prints what the agent should know first: `brain/now.md`, the
   last journal days and each repo's git, PR and CI state. The SessionStart hook injects the same brief.

5. **Work in isolated worktrees.** For issue `DEMO-7`, `./hub worktree demo-7-login` creates
   `<repo>/.claude/worktrees/demo-7-login` on branch `jdoe/demo-7-login` in every repo, from a freshly fetched
   `origin/main`. Remove them with `./hub worktree --remove demo-7-login` (branches are kept).

6. **Keep the hub healthy.** Run `./hub doctor` in CI or before a release of your hub, and upgrade with the recipe
   below. Your hub's CI needs no secret for this public repository; only when `platform.repository` names a private
   source does `./hub` need the Actions secret `AGENT_HUB_READ_TOKEN`, a token with read-only Contents on that
   repository only ([the hub's CI](design/hub-adopt.md#in-the-hubs-ci)). Private repos in `hub.json` are skipped
   in CI, so their repo rules run locally only, unless you give CI a read token for them: in an organisation, a
   GitHub App (the variable `HUB_REPOS_APP_CLIENT_ID` and the secret `HUB_REPOS_APP_KEY`), else the secret
   `HUB_REPOS_READ_TOKEN` (a fine-grained token with read-only Contents on those repos).

## Recipes

### Upgrade a hub to a newer release

Edit `platform.version` in `hub.json`, then sync through the shim, which already runs the new release:

```bash
./hub sync --check   # plan only: exit 4 when changes are pending, 3 on a conflict
./hub sync           # apply: managed files are rewritten, seeded files are left alone
```

`./hub sync` prints `up to date` when nothing changed. A `hub` whose version differs from the pin refuses to sync and
prints the pinned `uvx` command to use instead.


### Create a hub from an existing `hub.json`

The recipes that call a bare `hub` assume it is installed ([Quick Start](../README.md#-quick-start) tip), or prefixed with the `uvx --from …` of
step 1.

```bash
hub init --config path/to/hub.json --dir path/to/new-hub
```

The file's `platform.version` must equal the running CLI's version.


### Run only some `hub doctor` rules, or get JSON

```bash
./hub doctor --only links.dead --only instructions.size
./hub doctor --json
```

Exit codes: `0` no errors, `1` at least one error, `2` usage error. Rules and their meaning are in
[docs/design/hub-doctor.md](design/hub-doctor.md).


### Check an agent's JSON output

```bash
./hub validate-output review brain/features/login/reviews/DEMO-7/spec-r1.json
./hub validate-output eval brain/features/login/evals/demo-7.json
```

Exit codes: `0` valid (`<file>: valid`), `1` one line per problem, `<file>: <json path>: <message>` (the first 200, then
the total), or one line naming a file that could not be read, `2` usage error. The schemas ship in every hub as
`plugin/hub-workflow/schemas/review.v1.json`, `eval.v1.json` and `eval.v2.json` (a ticket that owns several repos).


### Create worktrees in one repo only

```bash
./hub worktree demo-7-login --only backend
```

A repo can ship executable `scripts/worktree-setup.sh` and `scripts/worktree-teardown.sh`; `hub worktree` (and
`hub run`, setup only) runs them with the worktree path and `HUB_WORKTREE_NAME`, `HUB_WORKTREE_BRANCH`, `HUB_REPO_DIR`,
`HUB_HUB_DIR`, `HUB_WORKTREE_SLOT` and `HUB_PORT_OFFSET`, for env files, databases or ports. `HUB_REPO_DIR` and
`HUB_HUB_DIR` are the repo's and the hub's main checkouts; `HUB_PORT_OFFSET` is the slot × 100, to add to the repo's
ports, and two tasks can share a slot. See [docs/design/worktree-environment.md](design/worktree-environment.md).


### Store agent events (synthetic data only, for now)

`hub collect` ingests canonical events (the [event model](SPEC.md#data-sources-and-event-model)) from JSON Lines,
all or nothing:

```bash
cat > events.jsonl <<'EOF'
{"project":"demo","session":"s-1","type":"session.start","timestamp":"2026-10-01T09:00:00+00:00","source":"claude_code","source_id":"evt-1"}
{"project":"demo","session":"s-1","type":"tool.call","timestamp":"2026-10-01T09:00:05+00:00","source":"claude_code","source_id":"evt-2","payload":{"tool":"Read"},"repo":"backend"}
EOF
hub collect events.jsonl --db ./events.db
```

```text
appended 2, duplicates 0
```

Running it again prints `appended 0, duplicates 2`: an identical event is skipped, never written twice.

> [!WARNING]
> Redaction of secrets is not built yet. Until it ships, feed `hub collect` synthetic events only, never real
> transcripts or hook payloads.

