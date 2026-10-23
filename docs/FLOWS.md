# Flows

The built-in flows a hub gets from its pinned release, for after `/onboard`. Setting up a hub is in [USING.md](USING.md).

## Pick a flow

Which built-in flow to use, how it starts and what you decide in it. `/kickoff` and `/triage` route work by
this table, and a new hub's `README.md` ends with the same one. A flow's scripts read your `hub.json` (and your
`hub.local.json` prefix) only through `./hub step config`, which prints those values and changes nothing.

<!-- flow-catalog:start -->
| Flow | Use when | Start | Your gates | Skills and agents inside |
|---|---|---|---|---|
| `backlog-care` (`backlog-care` pack) | The weekly backlog pass - hygiene findings and drafts for the oldest unready issues, one approval per issue. | `/triage` | The owner applies this issue's draft and label, or skips the issue. | `/triage` |
| `context` (`brain-care` pack) | The monthly context audit - measure the always-loaded text, the owner picks the cuts, one hub PR. | `./hub workflow run context` | The owner picks the cuts (a note keeps some), or skips this month. | `/context-audit` |
| `inbox` (`brain-care` pack) | The weekly inbox review - group duplicate notes, the owner decides each group, one hub PR. | `/learn` | The owner decides the group; an external note needs his explicit apply. | own prompts |
| `doc-drift` (`doc-drift` pack) | Doc lines a contract change made wrong, fixed in a docs-only PR the owner approves first. | `./hub workflow run doc-drift` | The owner approves the proposed doc lines, or rejects them (no PR). | `/plain-language` |
| `flaky` (`flaky` pack) | A flaky test run many times alone, in suite order, shuffled and in parallel; the likely cause to the inbox. | `./hub workflow run flaky` | none | own prompts |
| `incident` (`incident` pack) | An incident - git evidence, ranked hypotheses with read-only checks, a gated mitigation, a hand-off draft and a blameless postmortem draft. | `/incident` | The owner records a mitigation of a confirmed hypothesis, or their own, or none. Nothing is applied. | `/recall`, `/learn` |
| `issue-to-pr` (`issue-to-pr` pack) | One tracker issue to a PR, as hub run takes it. | `./hub run <issue>` | none | own prompts |
| `post-merge-verify` (`post-merge-verify` pack) | The merged tickets' AC verifications, run again on the default branch; failures to the inbox. | `./hub workflow run post-merge-verify` | none | own prompts |
| `release` (`release` pack) | Cut a platform release when the owner asks: the PRs merged since the last tag, the version bump, the check on the exact release commit and the notes with what hub sync rewrites, then, once the platform repo's release workflow has tagged it, the hub's pin bump, each PR behind its own approval. | `/release` | The owner approves the release PR.; The owner merges the release PR, /release dispatches the release workflow, then the owner answers.; The owner approves the hub PR that bumps the pin. | `/plain-language` |
| `retro` (`retro` pack) | The week's run metrics, at most five evidence-backed changes, and issue drafts for the ones the owner keeps. | `/retro` | The owner keeps some of the changes (their numbers, or all), or none. | own prompts |
| `review-incoming` (`review-incoming` pack) | Someone else's PR through the spec, quality and security lenses, drafted as one review posted only after the owner approves it. | `/review` | The owner edits the review file, then picks how it is posted, or rejects it. | `/plain-language`, `security-reviewer` agent |
| `deliver` (`sdlc` pack) | One issue to a PR, implemented and reviewed in rounds until the check and both reviewers pass. | `./hub workflow run deliver` | none | own prompts |
| `implement` (`sdlc` pack) | One ticket of a planned feature to a PR - context, preflight and plan change gate, review rounds, ticket eval. | `/implement` | The owner approves the plan change, or declines it with a note. | own prompts |
| `preflight` (`sdlc` pack) | A dependent ticket's read-only preflight after a blocker's merge - once per outcome, a plan change gate on plan drift. | `./hub workflow run preflight` | The owner approves the plan change, or declines it with a note. | own prompts |
| `preflight-check` (`sdlc` pack) | One ticket's preflight - the read-only check, a plan change gate on plan drift, and the re-check after the owner's decision. | inside `preflight`, inside `ticket-pass` | The owner approves the plan change, or declines it with a note. | own prompts |
| `review` (`sdlc` pack) | The spec and quality lenses on a checkout, then one verdict. | `./hub workflow run review` | none | own prompts |
| `ticket-pass` (`sdlc` pack) | One ticket pass - preflight, a plan change gate on plan drift, the worktree, the ticket plan and the review rounds. | inside `implement` | The owner approves the plan change, or declines it with a note. | own prompts |
| `security-sweep` (`security-sweep` pack) | Weekly scanners on every repo, new findings triaged by the security reviewer, kept ones to brain/_inbox for /triage. | `./hub workflow run security-sweep` | none | `security-reviewer` agent |
| `spike` (`spike` pack) | A timeboxed spike - recall, research, options, the owner's pick, a premortem, then research.md and an ADR draft. | `/feature` | The owner picks an option, or asks for more with a note. | `/recall`, `/research`, `/adr`, `/premortem`, `researcher` agent |
| `upgrade` (`upgrade` pack) | One package bumped with the repo's tooling, its changelog read, the code adapted, checked and opened as a PR. | `/upgrade` | A risky bump (major, no changelog, or more than five files touched) asks before the full check.; Every push waits on a person; a reject stops the run with the branch kept. | own prompts |

Any flow can also start from `hub web` (Workflow runs › Start run; `issue-to-pr` only through `./hub run`), or by itself from `hub.json` → `schedules` (a time) and `events` (a merge, a new PR, a red CI run). Each pack's file suggests its own entries.
<!-- flow-catalog:end -->

## Start a flow by itself

**Scheduled and event starts.** `hub web` can start a workflow by itself. Declare it in `hub.json`: a schedule such
as `"schedules": [{"workflow": "retro", "cron": "0 9 * * 1", "inputs": {"since": 7}}]` starts `retro` every Monday at
09:00, and an event such as `"events": [{"workflow": "post-merge-verify", "on": "merge", "repo": "<repo dir>"}]`
starts `post-merge-verify` after merges to that repo's default branch: at most one run per poll (every 5 minutes), on
the newest new commit (`on` may also be `ci_red`, one run per failed Actions run on it, or `pr_opened`, one run per
newly opened pull request; an older pull request or run that comes back onto GitHub's page never starts one). The cron has 5 numeric fields and is read in UTC.
Nothing starts while `hub web` is not running; when it comes back, the most recent missed slot runs once and older
ones never do. Events are polled through `gh` every 5 minutes, so `gh` must be signed in; only the repo's own push runs and pull
requests count (one from a fork never starts a run); the first poll only records
what is there, and the run gets the event's `sha`, `pr` or `ci_run` when the workflow declares that input. Each run
records `trigger` in its start record and is listed in Runs like any other. `./hub workflow schedule list` prints each
schedule's next start, and `./hub doctor --only workflows.starts` flags a misspelled workflow. In Docker no run starts
by itself, as no run starts from the app there.

## Each flow

`/feature` sends a spike to the `spike` workflow.

For an outage or a bug with no known reproduction, `/incident` in a session starts the built-in `incident` workflow;
its gate is answered in hub web or with `./hub workflow respond <run>`, and its drafts land in `brain/_inbox/`.

Once a week (on Mondays, after the brain's inbox), run `/triage --backlog` in a session: it reads the open issues,
runs the `backlog-care` workflow on them, asks the owner to apply or skip each draft one issue at a time, and writes
only the approved ones to the tracker. A schedule cannot start it: the run needs the issues file the skill writes.

To review someone else's PR, type `/review <PR>` in a session. It reads the PR with `gh` and starts the built-in
`review-incoming` workflow, which drafts one review in `.agent-runs/review-incoming/<run>.md` and pauses; you edit that
file and answer `./hub workflow respond <run> --choice comment|request-changes|approve` (or `--choice reject`), and only
then does `/review` post it. The repo's check runs at the PR's head in a throwaway worktree, never for a fork.

The platform's own releases come from `/release`, which runs the built-in `release` workflow: the owner approves
the release PR, merges it with a merge commit, and approves the hub PR that raises `platform.version`.

**The weekly retro.** `/retro` runs the built-in `retro` workflow (`./hub workflow run retro --input since=7 --live`):
the week's run metrics, at most five changes each backed by those numbers, and, for the ones you keep at its gate,
issue drafts in `brain/_inbox/retro-<date>.md`. Nothing reaches the tracker on its own: you file the drafts you want,
then `/triage` them. To run it every week once the pinned release has `hub.json` → `schedules`, add
`{"workflow": "retro", "cron": "0 10 * * 1", "inputs": {"since": 7}}` there (Mondays at 10:00 UTC).

**Brain care.** The built-in `brain-care` pack has two workflows, run from the hub with `--live`. `inbox` (also
`/learn promote`) reads `brain/_inbox/` (at most 50 notes, oldest first), lets a read-only agent group duplicates and
propose one action per group (promote into `brain/learnings/`, route to a repo, check, drop), then asks you about each
group at its own gate (`./hub workflow respond <run> --choice apply|drop|keep --text "<note>"`); a note whose provenance
is not `agent`, `agent-from-code` or `human` is always a group of its own, and the first gate lists the notes no
gate shows. `context` measures the hub's always-loaded text as
`/context-audit` does, names the files past its limits, and trims only after you choose `trim` at its gate (a trim
that touches a file `hub.lock` marks managed is refused). Only after
the gates does a run add a hub worktree on `<branch_prefix>brain-care-<workflow>-<run id>` (from the local
`origin/<default branch>`, so fetch first; a note not on it is skipped and named in the PR body) and open one hub PR
that you merge; neither writes the tracker. Each run ends with an outcome (`pr_opened`, or why no PR opened, such
as `no_pr`, `kept` or `declined`). A run that made a worktree leaves it and its branch in the hub: remove them after
the merge, or at once when no PR opened, with `git worktree remove .claude/worktrees/brain-care-<workflow>-<run id>`
then `git branch -D <branch_prefix>brain-care-<workflow>-<run id>` (the outcome's reason prints both). Suggested schedules, for `hub.json` → `schedules` (AGH-481): `inbox` every
Monday, `context` on day 1 of each month. The first live run on a hub is the end-to-end check of `hub step pr` there
(the push and `gh` on the hub's own repo): tests cover the steps up to the commits only.

**Weekly security sweep.** `./hub workflow run security-sweep --live` (or a weekly `schedules` entry) runs the
scanners found on `PATH` (Semgrep, Bandit, pip-audit, npm audit; none is installed for you, a missing one is named in
the note) and the guard's secret-file rule on each repo as last fetched, triages the new findings with the
security-reviewer's steps, and writes `brain/_inbox/security-YYYY-MM-DD.md`; file an issue for each finding you accept,
then run `/triage <issue>`. Semgrep's registry rules, pip-audit and npm audit reach the network.

**Doc drift.** The built-in `doc-drift` workflow finds doc lines a contract change made wrong and, once you approve
them at its gate, opens a docs-only PR in the repo (ADRs are reported, never edited). Fetch the repo, then run
`./hub workflow run doc-drift --input repo=<dir> --input sha=<merge sha> --live` after a merge, or with `sha` blank
for the last month. To run it on every merge and once a month, add to `hub.json`:
`"events": [{"workflow": "doc-drift", "on": "merge", "repo": "<dir>", "inputs": {"repo": "<dir>"}}]` and
`"schedules": [{"workflow": "doc-drift", "cron": "0 6 1 * *", "inputs": {"repo": "<dir>"}}]`. Known limit: a command
renamed in one command group while another group keeps the same name is not seen as gone. Each approved run
leaves a worktree at `<repo>/.claude/worktrees/doc-drift-<run id>` on the branch `<branch_prefix>doc-drift-<run id>`
(a resumed run reuses both); once its PR is merged or closed, or it committed nothing, remove them in the repo with
`git worktree remove .claude/worktrees/doc-drift-<run id>` and `git branch -D <branch_prefix>doc-drift-<run id>`.

**Flaky test.** The built-in `flaky` workflow runs one pytest test many times to tell why it fails only sometimes.
Fetch the repo, then run
`./hub workflow run flaky --input repo=<dir> --input "test=<node id>" --input runs=20 --live`, the node id from the
repo root (`tests/test_x.py::test_y[case]`). Each round runs it alone, in its file's order, shuffled (with
pytest-randomly or pytest-random-order, one seed per round) and with its folder under pytest-xdist `-n auto`; a mode
whose plugin the repo lacks is skipped and named. The runs happen in a throwaway worktree at `origin/<default
branch>`, through `uv run --locked` when the repo holds `uv.lock`, each within 10 minutes and all within 5h30m. When a
run fails, a read-only agent names the likely cause (order dependence, timing, shared state, external); either way the
counts go to `brain/_inbox/flaky-<test slug>.md`, one note per test, one section per run. It changes no code and
writes no tracker.
