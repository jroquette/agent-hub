# Feature records: tickets, evals, reviews and the golden path

## Purpose

A feature is a hub folder, `brain/features/<slug>/`, written by the workflow agents and read by `hub web` and
`hub doctor`. This file is the contract for the records that say what a feature planned and delivered: the ticket
plan in `features.json`, one eval per delivery, one review record per ticket, and the golden path the app folds from
them (AGH-136). The app only reads these files; a record changes through a hub PR. Ticket status comes from Linear
through the read-only port of [ADR 0025](../adr/0025-reading-the-tracker-from-the-app.md); the route that serves it is
in [API.md](../API.md) "Feature tickets"; the screens are in
[control-plane/specs/17-features.md](control-plane/specs/17-features.md).

## Contract

### `features.json`

`{"linear": [...], "tickets": [...], "acs": [...]}`; at most 1 MiB; unknown keys are ignored, and a record without
`tickets`, `ticket` or `withdrawn` (the older shape) parses unchanged (`agent_hub.core.features.feature_record`).

- `linear` (optional): tracker ids of the feature, joined with the spec's `linear:` frontmatter.
- `tickets` (optional, at most 200): the planner's ticket plan, each
  `{"key", "id", "title", "repo", "blocked_by", "order"}`.
  - `key`: a draft key (`T1`…), `^[A-Za-z][A-Za-z0-9_-]{0,31}$`, unique in the record.
  - `id`: `null` until `/feature` creates the issue, then the tracker id (`DEMO-1520`).
  - `title` (≤ 200 characters), `repo`, `order` (a whole number ≥ 0, the plan's order): optional.
  - `blocked_by`: at most 50 keys or ids of other tickets of the plan, never the ticket itself.
- `acs`: `{"id", "description", "repo", "verification", "passes", "evidence", "ticket", "withdrawn"}`.
  `ticket` (optional) is a key or id of `tickets`, or a `linear` id: the ticket that delivers the AC. `withdrawn`
  (default `false`) marks an AC an amendment withdrew; it stays in the file and the spec and leaves every count.

### `evals/<delivery>.md`

One new file per evaluation, written by the evaluator and never overwritten. `<delivery>` is
`^[a-z0-9][a-z0-9-]{0,62}$`: the lower-case ticket id (`demo-1520`), `pr-<repo>-<n>`, or `feature` for a whole-feature
run; a re-run adds `-r2`, `-r3`. The frontmatter holds:

| Key | Value |
|---|---|
| `type` | `eval` |
| `delivery` | the file name without `.md` |
| `verdict` | `SHIP`, `SHIP-WITH-OWNER-STEPS` or `NO-SHIP` |
| `tickets` | the tickets evaluated (keys or ids) |
| `acs` | the AC ids evaluated, or `all` |
| `prs`, `commit`, `evaluated_at` | the PRs, the commit evaluated and an ISO 8601 time |

At least one of `acs` and `tickets` is required. At most 200 eval files are read (the rest are counted as skipped),
each head up to 16 KiB. A legacy `eval.md` is read as one delivery named `legacy`: its verdict is its first `Verdict`
line, its scope its frontmatter when it has one.

### `reviews/<ticket>.md`

Written by `/feature` step 7 once both reviewers pass: `type: review`, `ticket`, `outcome` (`approved` or
`changes-requested`), `pr`, `reviewed_at`. At most 500 are read (first by name), heads of 8 KiB.

### Agent outputs: `reviews/<ticket>/<reviewer>-r<N>.json` and `evals/<delivery>.json`

JSON the agents hand to `/feature` ([ADR 0028](../adr/0028-agent-outputs-as-validated-json.md)), checked by
`agent_hub.core.features.agent_outputs` (`review_problems`, `eval_problems`: bytes in, every problem at its JSON path
out) against the models of `output_models.py`, exported as `review.v1.json` and `eval.v1.json` beside them. Every key
is required, unknown keys are refused, text is one line and non-empty.

- Review, schema `agent-hub/review/1`: `reviewer` (`spec`, `quality`), `ticket`, `task`, `round`, `commit`,
  `verdict` (`PASS`, `FAIL`), `findings` (`severity` `blocking` or `minor`). The file name gives `reviewer` and `round`
  (`N` 1 to 9999); `ticket` is the folder's name, ASCII case ignored; `FAIL` iff a finding is blocking; ids unique.
- Eval, schema `agent-hub/eval/1`, beside `evals/<delivery>.md`: `delivery`, `verdict`, `commit`, `tickets`, `acs`
  (`"all"`, ids, or `[]` for the tickets' ACs), `results` and `gates` (`status` with `exit_code`), `red_on_parent`,
  `owner_steps`. `SHIP` needs `results` and `gates`, all `pass`; `SHIP-WITH-OWNER-STEPS` an owner step; `pass` exits 0,
  `not-run` null; list items are unique; the stem is `delivery`; the sibling exists and holds the same `verdict`,
  `tickets`, `acs` (as sets) and `commit`; `results` name each AC of the scope once. With `features.json`, `all` and a
  tickets-only scope mean the live ACs (of those tickets), and no listed id or result is withdrawn or unknown.
- Bounds, applied by core to the bytes it is given: `MAX_OUTPUT_BYTES` per output, each list's `MAX_*`, the sibling's
  first `EVAL_HEAD_BYTES`, `MAX_RECORD_BYTES` for the record; echoed values are cut to `ECHO_LIMIT`.

The feature list reads at most about 32 MiB of records per call (it may go over by one folder); folders past that are
listed unread with a record problem. The detail and the tickets route read only their own folder. A malformed record counts for
nothing and carries its problem.

### Golden path

Computed once in core (`agent_hub.core.features.golden_path`) and served as `golden_path` on the feature list, the
detail and the tickets route: `steps` (each `name`, `state`, `meta`, `reason`, `progress {done, total}` or `null`)
and `phase`, the first step neither `done` nor `skipped` (`shipped` when every step is done).

| Step | Done when |
|---|---|
| Spec, Research, Plan | its file exists (one missing while a later record exists is `skipped`) |
| Tickets | every planned ticket has a tracker id ("15 of 17 created") |
| Implement | every ticket is Done in Linear and every AC passes ("1/17 tickets · 3/36 ACs") |
| Review | every ticket is reviewed: Done in Linear (state type `completed`) or an `approved` review record; "In Review" is not |
| Evaluate | the latest eval naming each AC is a SHIP, none `SHIP-WITH-OWNER-STEPS` waiting ("partial: covers 3 of 36 ACs") |
| Shipped | every ticket is Done in Linear |

States: the first step that does not hold is `current` (or `unknown` when its evidence cannot be read). After it, a
step whose own condition holds is `blocked` with a `reason` naming that earlier step; one with evidence for part of
the feature is `partial`; one that cannot be read is `unknown`; the rest are `pending`. Without a Linear snapshot,
ticket states are unknown: Implement's ticket count, Shipped, and Review unless every ticket has an approved record,
are `unknown` with "Linear not connected" (or "Linear not loaded yet" when a key is set but the cache is cold).
Canceled (and duplicate) tickets and withdrawn ACs are left out of every count.

### Planning

`agent_hub.core.features.ticket_planning`: one row per planned ticket and per `linear` id. Edges are the union of the
plan's `blocked_by` and Linear's "blocks" relations, each tagged `plan`, `linear` or `both`. A blocker is done when its
state type is `completed`; a canceled one no longer blocks. Over the tickets neither done nor canceled: cycles
(strongly connected components) are flagged and left out; the rest form layers (Kahn's algorithm) that can run in
parallel; the order is the layers in turn, each by priority (1 urgent first, 0 none last), then plan `order`, then id.
Blockers outside the feature (from Linear relations or named only in the plan's `blocked_by`) are read with the
feature's ids, up to 200 in total, and listed with their Linear status. A ticket behind an outside blocker that is open
or unread gets no layer: it is listed under `waiting` and left out of the order, so the first layer is `can_start`.
The critical path is the longest chain of not-done tickets. Linear titles, assignees and state names are redacted.

## Invariants

- The app never writes a record and never writes to Linear; nothing read from Linear is stored.
- An eval file is never overwritten: a re-run is a new `-rN` file. Every eval stays listed in the Eval tab.
- An approved spec (`status: approved`) is never rewritten: changes go in `## Amendments` (`A1 (date, who): …`); new
  ACs take the next free number; withdrawn ACs stay listed; AC ids are never renumbered.
- No golden-path step is `done` while an earlier step is not.
- Planning and the golden path are pure folds: the same records and snapshot give the same answer, whatever the order.
- Linear's text is untrusted: titles and assignees are redacted and clipped, and a `url` outside `https://linear.app/`
  is dropped.
- `hub doctor`'s `features.tracker` rule checks the shapes above: an unknown `blocked_by`, a duplicate key, an AC
  `ticket` that names no ticket, an eval without `verdict` or scope or naming an unknown AC are findings, and a
  withdrawn AC stays in the spec cross-check (the spec keeps naming it); a `blocked_by` cycle is a warning.

## Decisions

- Evals per file, not sections of `eval.md`: parallel worktrees add distinct files without a merge conflict, and
  "never overwrite" is a file-level rule a doctor can check.
- For each AC the latest eval naming it decides. Dated evals compare as UTC instants; when a date is missing or
  equal, a re-run (`-rN`, higher N) is newer than what it re-runs and any `evals/` file is newer than `eval.md`.
  Evals with no known order that disagree give the conservative verdict (NO-SHIP, then SHIP-WITH-OWNER-STEPS). An eval naming only `tickets` covers the ACs whose `ticket` is one of them.
- A legacy `eval.md` without scope covers every AC only when every non-withdrawn AC passes; otherwise Evaluate reads
  "partial: scope not recorded".
- The planner records `blocked_by` and never calls the tracker; `/feature` step 4 creates the issues, fills each `id`
  and creates the Linear "blocked by" relations.
- `withdrawn` is a `features.json` key because the app does not read a spec's amendments.
- The first step not done is `current` even with progress; `partial` is for a later step with some evidence.

## Open questions

- Should the hub guard also ask before overwriting an existing `evals/*.md` or an approved `spec.md`? Today the
  templates and the doctor rule enforce it.
- Linear's real field names (`relations`, `inverseRelations`, `team.key` with `number in`) are proven only by the
  by-hand live test, not in CI.
