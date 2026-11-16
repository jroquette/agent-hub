# Workflows

A workflow is data: a YAML (or JSON) file in the hub's `workflows/<pack>/` folder whose nodes (`agent`, `shell`,
`script`, `loop`, `loop_group`, `include`, `approval`, `wait`, `halt`) depend on each other and run in layers
([format](design/workflow-schema.md), [ADR 0032](adr/0032-workflow-engine.md)). `hub init` and `hub sync`
seed the built-in packs once: `issue-to-pr` (what `hub run` runs) and `sdlc` (`deliver`: implement, validate and
review in a loop until green, then the PR; `review`: a spec lens and a quality lens side by side, then one verdict), `retro` (the
week's run metrics, at most five changes each backed by those numbers, then issue drafts for the ones the owner keeps),
`post-merge-verify` (after a merge, or weekly with a blank `sha`: `select` the passing ACs of the merged tickets and of
the paths it changed, `run` each verification once in a throwaway worktree at the commit, `explain` a failure from the
merges since its last pass, read-only, and `report` it to `brain/_inbox/verify-<date>.md`; a verification with a
machine path is listed as "cannot run after merge"; fetch first:
`./hub workflow run post-merge-verify --input repo=<dir> --input sha=<sha> --live`),
`brain-care` (`inbox`: the weekly inbox review, one owner gate per group of notes, then one hub PR; `context`: the monthly
always-loaded context audit, a trim only after the owner's approval),
`spike` (`spike`: recall, research, 2 or 3 options, the owner's pick, a premortem of the pick, then
`brain/features/<slug>/research.md` and an ADR draft for `/adr`, within a timebox of 2h of agent time by default; it
changes no code),
`incident` (git evidence, a recall of past incidents, at most 5 ranked hypotheses each with a read-only check, the
checks in a throwaway worktree, a mitigation gate, then a hand-off draft for `/change` and a blameless postmortem draft
in `brain/_inbox/`; it writes no tracker and applies nothing; `/incident` starts it with
`./hub workflow run incident --input report=… --live`),
`upgrade` (one uv or npm package from its changelog to a PR: the bump made with the repo's own tooling, the changelog
read, the fast check, up to three adapt rounds, test strength on the adapted lines, the `size` approval for a risky
bump, the full check, then the PR behind the `publish` approval; `/upgrade` starts it),
`security-sweep` (the installed scanners on every repo as of `origin/<branch>`, read-only, then one security-reviewer
triage of the new findings; the kept ones go to `brain/_inbox/security-YYYY-MM-DD.md` for `/triage`, no secret value
and no tracker write; suggested weekly in `hub.json` `schedules`: `{"workflow": "security-sweep", "cron": "0 6 * * 1"}`),
`backlog-care` (what `/triage --backlog` runs: hygiene findings on the issues it read, then a draft for each of the
oldest unready issues, one approval per issue; `/triage` applies the approved ones after the run),
`doc-drift` (after a merge, or monthly with `sha` blank: the contract names the change removed, such as commands,
make targets, flags, config keys, skills, workflows, paths, tables and columns, then the doc lines that still name
them, a read-only judge's corrected lines, the owner's approval, and a docs-only PR in the repo; ADR lines are reported,
never edited; nothing writes the tracker; fetch the repo first: `doc-drift` reads `origin/<default branch>` as last
fetched),
`flaky` (one pytest test run many times alone, in its file's order, shuffled and with its folder under pytest-xdist,
in a throwaway worktree at `origin/<default branch>`; a read-only agent names the likely cause when a run fails, and
the counts go to `brain/_inbox/flaky-<test slug>.md`; fetch first:
`./hub workflow run flaky --input repo=<dir> --input "test=<node id>" --live`),
`review-incoming` (12 nodes, started by
`/review`: someone else's PR through the spec, quality and security lenses, the repo's check at the head (never for a
fork) and one draft you edit; `/review` reads the PR and posts the draft only after you approve it) and
`release` (`release`: the version PR, behind one approval of the version and the commit, where the run ends;
`release-pin`: the tag checked on the version PR's merge commit, then the hub pin PR, with no approval). A hub's own
file overrides a built-in of the same name.

```bash
./hub workflow list                          # the workflows that load; problems as <file>:<line>: <key>: <message>
./hub workflow run deliver --input issue=DEM-7 --input repo=api --input issue_text="..."  # dry: what would run
./hub workflow run spike --input question="..." --input slug=brief-cache --live  # a spike; answer its pick with respond
./hub workflow run upgrade --input issue=DEM-8 --input repo=api --input package=httpx --input to=0.28.1 --live
./hub workflow run deliver --input issue=DEM-7 --input repo=api --input issue_text="..." --live
./hub workflow run doc-drift --input repo=api --input sha=<merge sha> --live  # sha blank: the last month
./hub workflow run --resume <run>            # continue a failed or paused run; --abandon ends it
./hub workflow approve <run>                 # or reject / respond: decide a paused gate; the run resumes
./hub workflow test                          # every pack's fixtures, in memory (the hub's make check runs it)
```

In `hub web`, the Workflows screen shows each workflow's graph; Workflow runs › Start run starts one live from a form
built from its `inputs:`; Run detail shows the run's graph with each node's state, decides a waiting gate, and
cancels, resumes or abandons the run. Portfolio's Needs you lists every gate waiting for a person. The format and
the engine's rules: [workflow-schema.md](design/workflow-schema.md), [workflow-engine-rules.md](design/workflow-engine-rules.md).

Which flow to use, how each starts and what you decide in it: [docs/FLOWS.md](FLOWS.md).

## Scenarios

A scenario drives your own system step by step in a declared environment (`hub env`), so a walk you now do by hand
(send a message, wait, read a table, retry) runs the same way twice and is audited. Actions are your scripts in the
hub's `actions/<pack>/`, each declaring its effect (`read`, `write` or `destroy`); scenarios are files with
`kind: scenario` in `scenarios/<pack>/`, written as named stages of blocks (`version: 2`: Do runs an action, Wait
until polls a read action until a condition holds, You asks a person, Wait pauses the run, Include runs another
scenario's blocks; Repeat, If/else and At the same time hold blocks), which core turns into the workflow graph when
it loads them. A graph scenario (`version: 1`, `action` and `expect` nodes) still runs, `hub doctor` warns on it,
and `./hub scenario migrate` writes it again as blocks. Before each action runs, the access policy decides from the
environment's access whether it runs, asks or is denied, and only that action's process gets the environment's
credentials. `hub init` writes one example of each, `demo-get-status` and `demo-service-up`; declare an environment
and a service, commit, then plan it:

```bash
./hub scenario plan demo-service-up --env <environment> --input service=<service>  # each step and its decision
./hub scenario run demo-service-up --env <environment> --input service=<service>   # interactive by default
```

A divergence pauses an interactive scenario run. In `hub web` (Scenarios), a read-only Claude session investigates
and proposes findings and workaround options, each with its plan, and you pick one, retry or stop.

A scenario run written as blocks can be debugged off production: `--break ADDR` (a block address, such as `2` or
`2.1`) pauses it before that block, `./hub scenario step RUN` runs the next block and pauses before the one after it,
`./hub scenario continue RUN` runs it to the next breakpoint or its end, and `./hub scenario break RUN ADDR…` changes
its breakpoints. hub web's scenario run page offers the same, and shows the run's values while it is paused. No debug
command answers an ask, edits a value or skips a block. Contract and limits: [scenarios.md](design/scenarios.md),
[ADR 0041](adr/0041-scenarios-actions-and-enforced-access.md),
[ADR 0049](adr/0049-scenario-blocks-and-run-control.md).
