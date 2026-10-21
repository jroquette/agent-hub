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
  `{"key", "id", "title", "repo", "blocked_by", "order", "parent"}`.
  - `key`: a draft key (`T1`…), `^[A-Za-z][A-Za-z0-9_-]{0,31}$`, unique in the record.
  - `id`: `null` until `/feature` creates the issue, then the tracker id (`ACME-1520`).
  - `title` (≤ 200 characters), `repo`, `order` (a whole number ≥ 0, the plan's order): optional.
  - `blocked_by`: at most 50 keys or ids of other tickets of the plan, never the ticket itself.
  - `parent` (optional): the key or id of the plan's epic the ticket belongs to (the tracking ticket that groups
    the work and is never worked on itself), never the ticket itself.
- `acs`: `{"id", "description", "repo", "verification", "passes", "evidence", "ticket", "withdrawn"}`.
  `ticket` (optional) is a key or id of `tickets`, or a `linear` id: the ticket that delivers the AC. `withdrawn`
  (default `false`) marks an AC an amendment withdrew; it stays in the file and the spec and leaves every count.

### `evals/<delivery>.md`

One new file per evaluation, written by the evaluator and never overwritten. `<delivery>` is
`^[a-z0-9][a-z0-9-]{0,62}$`: the lower-case ticket id (`acme-1520`), `pr-<repo>-<n>`, or `feature` for a whole-feature
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

The feature's **acceptance eval** is the latest whole-feature eval: `acs: all`, or a legacy `eval.md` whose
frontmatter lists no `acs` or `tickets` (it was the one eval per feature; one that lists ACs counts only with
`acs: all`). "Latest" is the order of the decisions below, ties going to the conservative verdict. The feature's
header `verdict` is that eval's verdict, and none before one exists: ticket-scoped evals never set it, even when
together they cover every AC (two-level-flows AC-1.6, AGH-323). The owner's sign-off
(`evals/owner-signoff[-rN].md`, `provenance: owner`) lists the ACs it signs off, never `all`, so it is never the
acceptance eval (Amendment A3).

### `brief.md` and `ux-*.md`

`brief.md` (the `/feature` intake brief) is checked present, never read; it has no tab of its own. The folder's own
`ux-*.md` files (top level only, not in subfolders) are the UX designs: at most 50 are read in name order, each up to
4 KiB for its frontmatter `status`, never through a link. A design that cannot be read (a link) or has no valid
frontmatter counts as a draft; more than 50 of them makes the UX design step `unknown`: an unread design could be a
draft (AGH-325). Only screen designs use the `ux-` prefix at a feature folder's top level: a review or a note must
not, since every top-level `ux-*.md` counts as a design.

### `plan.md`

`plan.md` is read whole up to 256 KiB (`MAX_PLAN_BYTES`); over it, its version is a record problem ("plan.md is larger
than 256 KiB; its version could not be read."). Its version is `v1` plus one per distinct entry
`A<n> (<YYYY-MM-DD>, <who>): <title>` (a bare line or a `- ` list item, its head optionally `**` bold) under a
`## Amendments…` heading, up to the next level-1 or level-2 heading; each entry's anchor is that heading's text. Lines
in fenced code blocks do not count (`agent_hub.core.features.plan_version`).

### `reviews/<ticket>.md`

Written by `/feature` step 7 once both reviewers pass: `type: review`, `ticket`, `outcome` (`approved` or
`changes-requested`), `pr`, `reviewed_at`. At most 500 are read (first by name), heads of 8 KiB.

Beside them, `reviews/<ticket>/` holds the review rounds (below, "Agent outputs"). Only one feature's read (detail,
tickets, owner sign-off) looks into them, never the Features list, and it only learns which tickets have one, never reading a
round: of the first 500 ticket folders by name (not hidden, UTF-8 names, no link followed), it reads each folder's
entries until the first regular file named as the review check names a round (`<reviewer>-r<N>.json`). A budget of
20,000 entries covers the entries of those ticket folders together; listing `reviews/` itself is not counted.

### `tickets/<ticket>/` and `change-requests/`

The ticket flow's records (two-level-flows S2), written by the `implement` workflow's nodes, never by the app.
`<ticket>` is the ticket's plan key or tracker id, matched in any case.

- `tickets/<ticket>/brief.md` (the context brief) and `tickets/<ticket>/plan.md` (the ticket plan) are checked
  present, never read. The brief opens with frontmatter `type: ticket-brief` and `ticket`, then holds one section per
  context run, `## Brief v<n> (<ISO time>)`, appended and never rewritten: a re-run adds `v<n+1>` and keeps every
  earlier byte. Each section starts with its fields as a JSON block, `{"plan_version", "blockers": [{"id",
  "outcome_path", "recorded_at"}], "adrs": []}` (a flat frontmatter could not hold the blockers, and frontmatter at the
  top could not change without a rewrite), then `### Acceptance criteria` (the live ACs of `features.json` keyed to the
  ticket or named in its plan section), `### Plan section` (each section of `plan.md` whose heading names the
  ticket's key, id or plan ids, and each table row whose first cell lists one of them, quoted with `> `; a key joining
  plan ids, `S2-T3-T4`, names `S2-T3` and `S2-T4`),
  `### Blockers` (each `blocked_by` ticket with its `tickets/<key or id>/outcome.md` and `merged_at`, or "none
  recorded"), `### Main commits since the plan` (the ticket's repo checkout's `origin/<default branch>` as last
  fetched, after the hub's last commit of `plan.md`, on the files the plan section names in code spans; at most 50, or
  the reason none were read) and `### ADRs cited` (`ADR NNNN` or `docs/adr/NNNN-…` in the plan section).
- `tickets/<ticket>/preflight.json`: schema `agent-hub/preflight/1` (`PreflightRecord` in `output_models.py`, exported
  as `preflight.v1.json`, checked by `hub validate-output preflight FILE`): `{"schema", "ticket", "runs": [...]}`,
  at most 200 runs, oldest first, only ever appended. Each run is `{ran_at, plan_version, commit, blockers_read[],
  input, input_text, drift, local_notes[], change_request, run_id}`: `ran_at` an ISO 8601 time with an offset,
  `plan_version` a whole number ≥ 1 (the plan's `v<n>`), `commit` the main commit it checked, `blockers_read` the
  blocker tickets whose outcome it read (at most 50), `input` `none`, `discovery` or `declined_change` with its one-line
  `input_text` (required for those two, `null` for `none`), `drift` `none`, `local` or `plan`, `local_notes` one
  line each (at most 50; at least one for `local`), `change_request` the number of the request it opened (required
  for `plan`, else `null` allowed), `run_id` the workflow run's id. Every key is required and unknown keys are
  refused. Read whole up to 64 KiB (`MAX_PREFLIGHT_BYTES`); over it, malformed, or naming another ticket than its
  folder (ASCII case ignored), it is the Preflight step's problem.
- `change-requests/<n>.md` (`n` 1 to 999999): a plan change request, written once with frontmatter `type:
  change-request`, `ticket` (the asking ticket), `status: open`, `plan_from`, `plan_to` (whole numbers), `affected`
  (ticket keys or ids), `opened_at`, `run_id`, then its evidence and proposal; never edited afterwards (a `status`
  other than `open` is a record problem).
- `change-requests/<n>.decision.md`: the owner's decision, created once (D-11), frontmatter `type:
  change-request-decision`, `decision` (`approved` or `declined`), `decided_by` (a person: empty or `unknown`, case
  and spaces ignored, is a record problem, A5), `decided_at` (ISO 8601), `note`. The request's status is folded from
  it: `open` without one, else its `decision`. A decision that cannot be read leaves the request `open` (it is not
  known to be decided) with the decision's problem on the asking ticket's Preflight.

Only the tickets route opens `tickets/` (the detail, the list and the owner sign-off never do): its first folders by
name (not hidden, UTF-8 names, no link followed), at most 500 and no more than a full `preflight.json` (64 KiB + 1)
each can add before the read reaches 32 MiB; a ticket whose folder was left out reads Context and Preflight
`unknown`. `change-requests/` is read by the Features list and the detail too (the golden path's Plan signal and
`waiting_on_owner` need it): its first 400 `.md` files by name (200 requests and their decisions), heads of 16 KiB;
more than that is a record problem on Plan's signal. A file that cannot be read or parsed reads "<file> could not be
read (…). Fix it in a hub PR." on the step it feeds.

The `implement` run writes them with `hub step` (P7), in the hub's main checkout, never committing (its report names
the files for the owner's hub PR). Every writer checks its record as the readers above read it, follows no link (the
feature folder, `tickets/`, `change-requests/` and each file) and writes nothing when it refuses
(`agent_hub.core.features.ticket_writes`, `agent_hub.cli.step_records`). A ticket must be planned in `features.json`,
and its records go to one folder whatever name the run gives: the existing `tickets/` folder the ticket flow reads for
its key or id (`ticket_records.ticket_folder`), else its id (its key while it has none). `brief.md`, `preflight.json` and `plan.md` are read and replaced
under the feature's lock `.agent-runs/locks/<slug>.lock` (never committed); a run that finds it held is refused.

| Command | Writes | Refuses |
|---|---|---|
| `ticket-brief --feature --ticket` | the next `## Brief v<n>` of `brief.md` (temp file, then rename) | a ticket `features.json` does not plan, no `plan.md`, a `brief.md` that is not this ticket's brief |
| `preflight --feature --ticket --run JSON` | `preflight.json` with one run appended: earlier runs copied as parsed JSON, so each stays equal in canonical form; the file is new or replaced whole (temp file, then rename) | a run `PreflightRun` refuses (cross-field rules included), a record there that is malformed or names another ticket, a result over 64 KiB |
| `change-request --feature --ticket --run-id --evidence --proposal [--affected]…` | `change-requests/<n>.md`, `n` the next free number, `status: open`, `plan_from` the plan's current version, `plan_to` the next; created exclusively | a field its reader could not read, an empty evidence or proposal, a text over 256 KiB (what `decide` and `amend-plan` read) |
| `decide --feature --request N --decision approved\|declined --by WHO [--note]` | `change-requests/<n>.decision.md`, `decided_by` the gate's approver, `decided_at` now, `note` on one line (cut at 1,000 characters; the whole note is the body); created exclusively | a decision other than exactly `approved` or `declined`, a text over 256 KiB, a second decision, an approver that names no person (empty or `unknown`, A5), an approval whose approver `amend-plan` could not write (a `(` or `)`), a decline without a note, no request `n` |
| `amend-plan --feature --request N --summary` | one entry `- A<k> (<decided_at date>, <decided_by>): <summary> ([change request n](change-requests/n.md))` at the end of `plan.md`, after a new `## Amendments` heading when the last section is another; every earlier byte kept; a re-run once the plan holds the request's entry writes nothing and answers `already amended as A<k>` | a request not decided `approved`, a plan whose version is no longer the request's `plan_from`, an entry that would not read as `A<k>`, a lock another run holds |

### `summaries/<record>.md`

The human summary of `spec.md`, `research.md` or `plan.md`, written by the hub's `/summarize` skill each time the
record is written or amended; the record stays the agents' reference and is never changed by it. Frontmatter:
`type: summary`, `of` (the record's file name), `source_sha256` (the hex SHA-256 of the record's bytes when the summary
was written), `written_at`, `provenance: agent`. Body: a bottom line first, then only the non-empty sections of
Decisions, Risks, Open questions and Next step; 150 to 300 words (at most 350), plain language, every point linking
to the record's section it comes from. People skim long agent text rather than read it (NN/g: about 20% of a page's
words are read), so `hub web` opens a record tab on its summary ("For humans") with the record one click away
("Agent markdown"), and says the summary is out of date when `source_sha256` differs from the `sha256` the brain
note route gives for the record.

### Agent outputs: `reviews/<ticket>/<reviewer>-r<N>.json` and `evals/<delivery>.json`

JSON the agents hand to `/feature` ([ADR 0028](../adr/0028-agent-outputs-as-validated-json.md)), checked by
`agent_hub.core.features.agent_outputs` (`review_problems`, `eval_problems`: bytes in, every problem at its JSON path
out) against the models of `output_models.py`, exported as `review.v1.json` and `eval.v1.json` beside them (and
`preflight.v1.json` for the ticket record above, `preflight_problems`). Every key
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

The feature list reads at most about 32 MiB of records per call (it may go over by one folder, at most 15,572,994
bytes, about 14.9 MiB, with the change request heads); folders past that are listed unread with a record problem.
The detail reads only its own folder (at most those 14.9 MiB); the tickets route reads its folder and `tickets/`
within 32 MiB in all, which in the worst case still leaves room for 274 full `preflight.json`. A malformed record counts for
nothing and carries its problem.

### Golden path

Computed once in core (`agent_hub.core.features.golden_path`) and served as `golden_path` on the feature list, the
detail and the tickets route: `steps` (each `name`, `state`, `meta`, `reason`, `progress {done, total}` or `null`)
and `phase`, the first step neither `done` nor `skipped` (`shipped` when every step is done).

The steps are the feature's own ([ADR 0043](../adr/0043-two-level-feature-and-ticket-flows.md), AGH-325); each
ticket's implement, review and eval belong to the ticket, not to the golden path.

| Step | Done when |
|---|---|
| Spec | `spec.md` exists; with only `brief.md` it is `current`, "Brief only · spec not written" |
| UX design | every `ux-*.md` says `status: approved` ("2 designs · 1 draft" otherwise); none while a later record exists is `skipped`, "No screen change recorded" |
| Research, Plan | its file exists (one missing while a later record exists is `skipped`); Plan's meta is the plan's version ("v3 · 2 amendments"); while a plan change request is open, its `signal` reads "v4 waits for you" (the first open request's `plan_to`), else a change request's record problem |
| Tickets | every planned ticket has a tracker id ("15 of 17 created") |
| Build | every ticket is merged, Done in Linear (state type `completed`) ("1 of 3 merged · 1 in progress"; "· 2 paused for a plan change" counts the tickets not merged that an open request names as its origin or affected); with no ticket to build (Tickets done by `issues.md` alone, or only epics) it is never done, "No tickets planned" |
| Acceptance | the acceptance eval is SHIP, or SHIP-WITH-OWNER-STEPS whose owner steps are signed off: each AC it leaves as an owner step has a later SHIP with `provenance: owner` (ticket evals never sign one off) |
| Shipped | Build and Acceptance are done |

States: the first step that does not hold is `current` (or `unknown` when its evidence cannot be read, `unrecorded`,
"Not recorded", when it is Acceptance with no whole-feature eval: its meta says how many ACs the ticket evals cover,
"Ticket evals cover 6 of 23 ACs"). After it, a step whose own condition holds is `blocked` with a `reason` naming that
earlier step; one with evidence for part of the feature (created or merged tickets, ticket evals covering some ACs, a
design written) is `partial`; one that cannot be read is `unknown`; the rest are `pending`. A SHIP-WITH-OWNER-STEPS
acceptance eval not signed off reads "Waiting on you: sign off n ACs" ("1 AC" for one). One rule decides which ACs
wait (`feature_evals.owner_wait`), for the step and the sign-off alike: the acceptance eval is whole-feature, so every
non-withdrawn AC is an owner step (a legacy `eval.md` without scope too, failing ACs included) until a later SHIP with
`provenance: owner` names it (ticket evals never do); the sign-off lists exactly those. The sign-off is refused,
writing nothing, with a one-line reason: when any of those ACs has a NO-SHIP as its latest eval (it names them: fix
or re-evaluate first), when it would not rank newer than the acceptance eval (one with no `evaluated_at`, or one in
the future), and when the folder holds more evals than were read. A sign-off that names the acceptance eval as its
`delivery` (AGH-384's per-eval decision) follows the same rule (A11): "done" and "more work" cover exactly those ACs,
"more work" is not refused over ACs an agent's eval reopened, and either is refused, writing nothing, once an owner
decision newer than the acceptance eval settled it (its SHIP signed them off, or its NO-SHIP is still the latest eval
of one). While waiting ACs have a NO-SHIP as their latest eval, the step reads "n ACs reopened · evaluate again"
instead of a sign-off prompt; ahead of that, while no sign-off can rank newer than the acceptance eval (spec amendment
A15), it reads "Acceptance eval undated · evaluate again" (no usable `evaluated_at`; a legacy `eval.md` never is) or
"Sign-off possible after <date-time>" (dated at or after the read; the minute after which a sign-off can follow it,
in UTC, "21 Nov 2026, 09:01:00 UTC"), and neither reads "Waiting on you". The detail serves
the same wait as `acceptance_eval.owner_wait` ([API.md](../API.md)). With no AC to list (no `features.json`, or every
AC withdrawn), the step is not done, "Waiting on owner steps · no ACs listed", until a later owner SHIP of any scope
exists; the app cannot write that one, so the owner writes it by hand.

The owner can also sign off named ACs they checked by hand (AGH-425, the sign-off's `acs`): an owner eval over
exactly those live ACs, with no source eval and no tickets. It keeps the refusals above, writing nothing: an unknown
or withdrawn AC, `done` over an AC whose latest eval is NO-SHIP, a note that would not rank newer than every eval
naming those ACs, and evals left unread. An AC whose latest evals are all owner SHIPs reads `signed_off` and counts as
passing (`EvalCoverage.signed_off`) even when `features.json` says it does not; being an owner SHIP, it also leaves
the Acceptance wait. `features.json` is never changed by it.

Each feature (list and detail) carries `waiting_on_owner`, the owner decision it waits on: `change_request` (with the
open requests' origin tickets) while a plan change request is open, else `owner_signoff` while the acceptance eval
waits on a sign-off the app can record, or `owner_signoff_manual` while it lists no AC (A17); none otherwise. Without a Linear snapshot, ticket states are
unknown: Build and Shipped are `unknown` with "Linear not connected" (or "Linear not loaded yet" when a key is set but
the cache is cold). Canceled (and duplicate) tickets and withdrawn ACs are left out of every count; a ticket with
children (an epic) counts under Tickets only.

### Ticket flow

Each ticket's own steps (`agent_hub.core.features.ticket_flow`, AC-1.8), served as each row's `flow` on the tickets
route; an epic has none. A ticket is named by its plan key and its tracker id, in any case; a malformed record counts
for nothing.

| Step | Evidence |
|---|---|
| Context | `done` when `tickets/<ticket>/brief.md` exists |
| Preflight | `waiting`, "Waiting for you", while a change request the ticket asked is open (even with no `preflight.json`: a lost run); else by the latest run of `preflight.json`: `stale`, "Plan v4 approved: re-run preflight", when the ticket is not merged and the run checked an older plan version than the newest approved (the plan's version, or an approved request's `plan_to`); `done` on drift `none`, or `local` with the meta "Local drift · 2 notes"; `blocked`, "Plan drift", on drift `plan` otherwise; `unknown` with the problem when `preflight.json` or the ticket's request cannot be read |
| Implement | `done` when a review round of the ticket exists (`reviews/<ticket>/<reviewer>-r<N>.json`); `current`, "Ticket plan written", when only `tickets/<ticket>/plan.md` exists |
| Review | `done` when a review record of the ticket is `approved`; `current`, "Changes requested", while its records only request changes |
| Eval | the latest eval whose `tickets` name the ticket (the order of "Decisions" below, conservative when unordered): SHIP or SHIP-WITH-OWNER-STEPS `done`, NO-SHIP `blocked`; the meta is the verdict |
| PR | `done` when its review record's `pr` or an eval naming it lists a pull request (`<repo>#<n>` or a GitHub pull request URL; `#pending` is none) |
| Merged | `done` when Linear has the ticket `completed`, the rule Build counts by; `unknown` with Build's meta when Linear was not read |

A step with no evidence reads `unrecorded` ("Not recorded") when a later step has some, else `pending` ("Not
reached"): a ticket Done in Linear with no review record reads Context, Preflight and Review "Not recorded" and Merged
done. `current` is the first step neither `done` nor `unrecorded` (`merged` when there is none). The step bar
reads "Merged" alone only once Merged is done; otherwise it keeps the position ("Merged · 7/7"). The flow's `signal`
is its one line that needs attention, in this order: "Waiting for you: plan change" (its own request is open, whatever
its Preflight reads), "Held: plan change pending" (another ticket's open request names it as affected and it asks
none itself; not once merged), the stale Preflight's
meta, the local drift meta; `null` otherwise (spec amendment A13: preflight and change requests are its first
producers).

### Planning

`agent_hub.core.features.ticket_planning`: one row per planned ticket and per `linear` id. Edges are the union of the
plan's `blocked_by` and Linear's "blocks" relations, each tagged `plan`, `linear` or `both`. A blocker is done when its
state type is `completed`; a canceled one no longer blocks. Over the tickets neither done nor canceled: cycles
(strongly connected components) are flagged and left out; the rest form layers (Kahn's algorithm) that can run in
parallel; the order is the layers in turn, each by priority (1 urgent first, 0 none last), then plan `order`, then id.
Blockers outside the feature (from Linear relations or named only in the plan's `blocked_by`) are read with the
feature's ids, up to 200 in total, and listed with their Linear status. A ticket behind an outside blocker that is open
or unread gets no layer: it is listed under `waiting` and left out of the order, so the first layer is `can_start`.
The critical path is the longest chain of not-done tickets. A ticket that is the parent of another row (the plan's
`parent`, else Linear's parent issue) is an epic: readiness `epic` (until Linear has it done or canceled), listed under
`epics`, never in a layer and never a blocker; the golden path counts it under Tickets only. The Tickets tab shows it
above the flow with its children's progress. Linear titles, assignees and state names are redacted.

## Invariants

- The app never writes a record and never writes to Linear; nothing read from Linear is stored.
- An eval file is never overwritten: a re-run is a new `-rN` file. Every eval stays listed in the Eval tab.
- An approved spec (`status: approved`) is never rewritten: changes go in `## Amendments` (`A1 (date, who): …`); new
  ACs take the next free number; withdrawn ACs stay listed; AC ids are never renumbered.
- No golden-path step is `done` while an earlier step is not.
- Planning, the golden path and the ticket flows are pure folds: the same records and snapshot give the same answer,
  whatever the order. No ticket step is `pending` while a later step of the same ticket has evidence.
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
- A legacy `eval.md` without scope covers every AC only when every non-withdrawn AC passes; it is still the
  feature's whole-feature eval (Amendment A6), so it decides Acceptance.
- The planner records `blocked_by` and never calls the tracker; `/feature` step 4 creates the issues, fills each `id`
  and creates the Linear "blocked by" relations.
- `withdrawn` is a `features.json` key because the app does not read a spec's amendments.
- The first step not done is `current` even with progress; `partial` is for a later step with some evidence.

## Open questions

- Should the hub guard also ask before overwriting an existing `evals/*.md` or an approved `spec.md`? Today the
  templates and the doctor rule enforce it.
- Linear's real field names (`relations`, `inverseRelations`, `team.key` with `number in`) are proven only by the
  by-hand live test, not in CI.
