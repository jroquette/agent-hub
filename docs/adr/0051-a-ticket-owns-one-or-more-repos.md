# 0051. A ticket owns one or more repos, each with its own worktree, review rounds and pull request

- Status: proposed
- Date: 2026-10-27
- Deciders: José Henrique Roquette (plan approved for AGH-585 on 2026-10-27)
- Partially supersedes: [ADR 0043](0043-two-level-feature-and-ticket-flows.md), for "one ticket, one repo, one pull
  request" in the ticket flow. 0043 is not edited: its records, folds and names stay as decided.
- Relates to: [ADR 0028](0028-agent-outputs-as-validated-json.md) (agent outputs as validated JSON),
  [ADR 0050](0050-implement-conducted-in-its-own-session.md) (`/implement` conducts the ticket)

## Context and Problem Statement

A feature's plan can split one ticket into slices in two repos (a backend change and the UI that uses it), the second
merging after the first. `features.json` gives a ticket one `repo`, and every step after it assumes one repo, one
worktree, one base and one pull request: the brief finds no plan section when headings name slices, the preflight
calls the other repo's slice drift, a review round in a second repo has no valid path, the eval holds one commit, and
nothing records the second pull request or the order they merge in. How does a ticket own several repos while a
ticket with one keeps every record it writes today?

## Considered Options

1. **A ticket names its repos** (`repos: [{repo, slices}]`, in contract order). One brief, one preflight, one ticket
   plan and one eval per ticket; a worktree, gates, review rounds and a pull request per repo.
2. **Split such a ticket into one ticket per repo** with a `blocked_by` edge. No schema change, but the plan's unit of
   work (one reviewable change, one eval of its ACs) is cut in two, and the owner tracks two tickets for one change.
3. **One ticket and one combined record** (the workaround used on ABC-12): merged reviews with path prefixes, one
   eval commit. It loses the second repo's commit and the merge order.

## Decision Outcome

Chosen option: 1.

- **Data:** `repos` (1 to 4) replaces `repo` for such a ticket, never beside it; the list order is the contract order
  and the merge order. A ticket's repos are its `repos`, else its `repo`. Old releases ignore `repos` and refuse the
  ticket at `ticket-brief`.
- **Brief and preflight:** the brief finds plan sections by the slices' ids too, and reads main per repo. Preflight runs
  once with every checkout (one plan, one drift, one change request); `agent-hub/preflight/2` adds the commit per repo.
- **Records:** review rounds go to `reviews/<ticket>/<repo>/<reviewer>-r<N>.json`, still `agent-hub/review/1`: the
  path already gives reviewer, round and ticket, and now the repo. `agent-hub/eval/2` holds a base and a commit per
  repo and a repo per result. The review record and the outcome list the pull requests as `prs`, in merge order.
- **Compatibility:** a ticket with one repo writes `/1` records at today's paths; every old record stays valid.
- **The engine:** the `implement` workflow refuses a ticket with several repos (the engine has no fan-out; unrolled
  repo slots are AGH-594); `/implement` conducts it.

### Consequences

- Good: one ticket, one eval and one review decision for one change, with each repo's commit and pull request
  recorded, and the merge order written down.
- Good: no record of a one-repo ticket changes.
- Bad: two schema versions (preflight, eval) to read; the readers accept both.
- Bad: until AGH-594, a multi-repo ticket runs only through `/implement`, not as a workflow run.

## More Information

Plan and research: the hub's `brain/features/multi-repo-tickets/`. Epic AGH-585, slices AGH-586 to AGH-595.
