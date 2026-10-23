# 0048. Scheduled and event starts run inside hub web

- Status: proposed
- Date: 2026-10-22
- Deciders: José Henrique Roquette (the scheduler's place, the 5-minute polling, the rejected options and the
  one-catch-up rule were set by the owner for AGH-481)

## Context and Problem Statement

Workflow packs such as a weekly retro, a security sweep or a post-merge check should start by themselves: at a time,
or when something happens in a repo (a merge to the default branch, a red CI run, a newly opened pull request). Today a
run starts only by hand: `hub workflow run`, `hub run`, or the Start button of `hub web` (`StartWorkflowRun`, which
starts a detached `hub workflow run --live` child). Where should automatic starts be declared, what runs them, and how
do we make sure that one time slot or one event never starts two runs, without new outbound hosts and without tracker
writes ([ADR 0030](0030-run-outcomes-in-the-tracker.md))?

## Considered Options

- **A scheduler inside `hub web`**: `hub.json` declares `schedules` and `events`; `hub web`, already a long-running
  local process that starts runs, ticks once a minute and polls GitHub through `gh` every 5 minutes.
- **OS cron** (crontab, launchd, systemd timers) calling `hub workflow run`.
- **Claude scheduled tasks** (scheduled Claude Code sessions, local or cloud) that run a prompt.
- **GitHub Actions** (`schedule` and `push`/`pull_request`/`workflow_run` triggers) running the workflow in CI.

## Decision Outcome

Chosen option: **a scheduler inside `hub web`**, because it reuses the one path that already starts runs from the
app (the live-run guard per issue, the refusal of `issue-to-pr`, the children's environment without
`LINEAR_API_KEY`), it is declared and reviewed in the hub like the rest of the project's configuration, it needs no
setup per operating system, and its only new network traffic is `gh`'s own calls to GitHub.

- `hub.json` gains `schedules: [{workflow, cron, inputs, environment?}]` and
  `events: [{workflow, on: "merge" | "ci_red" | "pr_opened", repo, inputs}]`, checked by `HubConfig` and the shipped
  schema. Cron has 5 numeric fields (minute, hour, day of month, month, day of week; `*`, lists, ranges, steps) and is
  read in UTC, by a small parser in core (no dependency). `hub doctor` rule `workflows.starts` reports an entry that
  names an unknown workflow or `issue-to-pr`; `hub workflow schedule list` prints each schedule's next start.
- `hub web` runs one periodic task in its app lifecycle, only where it can start runs (not with the agent sessions
  off, as in the container). Each minute, for each registered hub, the most recent slot at or before now that has not
  started yet starts one run. A slot missed while `hub web` was down therefore runs once when it comes back; older
  missed slots never run (no backlog).
- Every 5 minutes it polls each declared event source with `gh api` (REST, `repos/<owner>/<name>/…`, the newest 20
  items, bounded output and time). The first successful poll of a source records what it sees as a baseline and starts
  nothing. Later polls start, for `merge`, one run per poll on the newest new commit of the default branch (every new
  sha is recorded, so a many-commit merge is one run); for `pr_opened` and `ci_red`, one run per pull request number or
  Actions run id above the highest one the source has recorded (its mark), so an older item that comes back onto the
  page, or one that stays there, never starts a run. Only the repo's own events count: `ci_red` reads push runs of the
  repo's own branch, and a pull request from a fork (or a deleted fork) is dropped. The event's data reaches the run
  only as ordinary inputs the workflow declares: `sha`, `pr`, `ci_run`. No workflow document key is added.
- Each start is a normal `hub workflow run --live` child; a hidden `--trigger schedule|event` writes `trigger` into the
  run's start record.
- Idempotency key: workflow + slot, or workflow + source + event id, kept in a per-hub ledger
  (`<hub>/.agent-runs/schedules/state.json`), changed under an exclusive file lock and replaced atomically. The ledger
  is written **before** the child starts: a start is at most once.

### Consequences

- Good: one place declares automatic starts, reviewed in the hub's pull requests; `hub doctor` catches a wrong name.
- Good: scheduled runs keep every guard of runs started from the app; `issue-to-pr` stays refused (ADR 0030).
- Good: no new dependency, no new host, no new credential: `gh` uses the account it is already signed in with.
- Bad: nothing starts while `hub web` is not running (a laptop asleep or closed); only the most recent missed slot
  runs when it comes back.
- Bad: at most once, not exactly once: if `hub web` dies between writing the ledger and starting the child, that slot
  or event is lost; a refused start (bad inputs, a live run of the same issue, too many children) is logged, not
  retried.
- Bad: events arrive up to 5 minutes late and cost about 12 `gh api` calls an hour per source against the user's
  GitHub rate limit; more than 20 events between two polls are not all seen.
- Neutral: two `hub web` processes on one hub do not double-start (the ledger lock), but each still polls GitHub.
- Rejected, **OS cron**: a different setup per operating system and machine, outside `hub.json`, invisible to `hub web`
  and its guards; every developer's machine with the entry would start the run, and the container has no cron.
- Rejected, **Claude scheduled tasks**: they run a prompt in a model session, so orchestration would spend tokens and
  depend on the model, against the engine's rule that orchestration is deterministic and token-free
  ([ADR 0032](0032-workflow-engine.md)); they are declared outside the hub and give no idempotency key we control.
- Rejected, **GitHub Actions**: the run would happen on GitHub's runners, away from the hub's checkout, brain and
  hooks, and would need the agent's credentials as repository secrets; it fits event triggers but breaks the local,
  single-process deployment of `hub web` ([ADR 0022](0022-container-packaging.md)).

## More Information

- Contract: [project-config.md](../design/project-config.md) (`schedules`, `events`),
  [hub-doctor.md](../design/hub-doctor.md) (`workflows.starts`),
  [workflow-engine-rules.md](../design/workflow-engine-rules.md) (`trigger` in the start record).
- Code: `agent_hub.core.schedules` (cron, the use case and its ports), `agent_hub.hub_git.github_events`
  (`GhEventSource`), `agent_hub.api.start_ledger` and `agent_hub.api.scheduled_starts_runtime`.
- Tests: `-k schedule` over `packages/core/tests`, `packages/api/tests` and `packages/cli/tests`.
