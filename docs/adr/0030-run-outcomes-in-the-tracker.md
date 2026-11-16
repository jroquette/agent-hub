# 0030. Run outcomes in the tracker and in `hub run`'s exit code

- Status: accepted
- Date: 2026-10-13
- Deciders: José Henrique Roquette (the fallback label, exit 3, stale-label removal and the comment texts, approved
  with the AGH-178 plan on 2026-10-13)

## Context and Problem Statement

AGH-140 gave every `hub run` an outcome: `delivered`, `no_changes` (the session left no commit), `blocked` (the session
stopped and asked for a human) or `failed`. Only the run records use it. The tracker report and the exit code still
treat `no_changes` and `blocked` as failures: they add `tracker.failed_label`, post a "failed at … Diagnosis:" comment
and exit 1. The tracker then shows failures where nothing broke, the session's question is buried in a diagnosis, and
a script cannot tell the cases apart. Every tracker adapter refuses a label the tracker does not know (E10), so any
new label has to be one that the hub opted into. How should each outcome show up in the tracker and in the exit code?

## Considered Options

1. Keep today's behaviour: every outcome other than `delivered` is a failure.
2. One report per outcome, with a new optional `tracker.blocked_label` that **defaults to `agent-blocked`**.
3. One report per outcome, with a new optional `tracker.blocked_label` that has **no default** and falls back to
   `tracker.failed_label`.

## Decision Outcome

Chosen option: **3**. It ends the false failures without breaking any hub: a hub that never created a blocked label
keeps getting `failed_label` on a blocked run, now with a comment of its own.

| Outcome | Tracker writes | Exit |
|---|---|---|
| `delivered` | move to `tracker.states.review`, remove the outcome labels the issue carries, comment `Run <id> opened <url>. <summary>` | 0 |
| `no_changes` | remove the outcome labels the issue carries, comment `Run <id> ended with no changes at <STAGE>: <reason>` | 0 |
| `blocked` | add the blocked label, remove `failed_label` if the issue carries it and it differs, comment `Run <id> stopped at <STAGE> and needs a human. The session asked: <question>` | 3 |
| `failed` | add `failed_label`, comment `Run <id> failed at <STAGE>. Diagnosis: <reason>` (unchanged) | 1 |

- The *outcome labels* are `failed_label` and the effective blocked label (`blocked_label`, else `failed_label`). A
  label is removed only when the issue read at PICKED carries it (E10). `hub ship`'s success report follows the
  `delivered` row.
- A tracker write that fails makes the exit 1 whatever the outcome. The writes stay ordered, the first failure stops
  them, and none is retried (D8).
- `tracker.blocked_label` is an optional string (ADR 0010: no `schema_version` bump). It cannot be set in
  `hub.local.json` and the hooks do not read it.
- Exit 3 belongs to `hub run` alone. 2 stays the usage error, and `hub sync`'s 3 and 4 are another command's.

### Consequences

- Good: the tracker tells "needs a human" apart from "broke", and a wrapper script can branch on 0, 1 and 3.
- Good: no existing hub breaks: the fallback keeps the only label that hub already has.
- Bad: `hub run` exits 0 on `no_changes`. A script that read a non-zero exit as "look at this issue" stops seeing it
  (CHANGELOG **Changed**).
- Neutral: the issue stays in `hub next`'s ready list after `no_changes` or `blocked`, as it did after a failure.
  Changing that is a separate decision.

## More Information

- AGH-140 (the outcome model), AGH-178 (this change).
- [ADR 0010](0010-hub-json-config-contract.md): optional keys.
- [design/event-derivations.md](../design/event-derivations.md) § Delivery, and
  [design/project-config.md](../design/project-config.md).
