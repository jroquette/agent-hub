# 0042. Two-level feature and ticket flows, ticket records, and plan change requests the owner decides

- Status: proposed
- Date: 2026-10-19
- Deciders: José Henrique Roquette
- Relates to: [ADR 0024](0024-learning-actions-from-the-app.md) (the app's hub writes go through a pull request),
  [ADR 0028](0028-agent-outputs-as-validated-json.md) (agent outputs as validated JSON),
  [ADR 0032](0032-workflow-engine.md) (the workflow engine, built-in packs, gates),
  [ADR 0040](0040-hub-web-keeps-local-settings-writes-hub-files-and-runs-checks.md) (hub web writes some hub files
  without committing; proposed)

## Context and Problem Statement

A feature's golden path folded per-ticket stages (Implement, Review, Evaluate, Shipped) over the whole feature, so one
ticket's evidence read three contradictory ways; `/feature` restarted brief and spec when run on a ticket; a ticket
started from the plan as written with nothing checking it still held, and nothing recorded when it did not. Where do
the two levels live, which records does the ticket level write, who writes them, and how does the owner decide a plan
change that a running ticket finds?

## Considered Options

1. Two nested flows: a feature flow (Spec, UX design, Research, Plan, Tickets, Build, Acceptance, Shipped) folded from
   the feature's records, and a ticket flow (Context, Preflight, Implement, Review, Eval, PR, Merged) folded per
   ticket; the ticket flow is a built-in engine workflow (`implement`) that writes ticket records into the hub and
   pauses at an approval gate on plan drift.
2. Keep one golden path and mark partial states (the AGH-322 fix alone).
3. Ticket flow as skill prose only (no engine), with records written by the session.

## Decision Outcome

Chosen option: 1.

- **Two folds in core, both pure.** The golden path holds feature steps only; each ticket row carries its own flow.
  A step with no record before a later step with evidence reads `unrecorded`, never "not reached". Build counts a
  ticket merged when Linear has it completed or its outcome is recorded; Acceptance moves only on a whole-feature eval
  (`acs: all`; a legacy `eval.md` without scope counts as one).
- **Ticket records** under `brain/features/<slug>/`: `tickets/<id>/brief.md` (versions appended), `preflight.json`
  (schema `agent-hub/preflight/1`, entries append-only), `plan.md` (the ticket plan), `outcome.md` (created once);
  `change-requests/<n>.md` (never edited) and `change-requests/<n>.decision.md` (created once); the feature plan's
  `## Amendments` entries `A<n> (date, who): …` (appended, earlier bytes unchanged).
- **Who writes them.** The `implement` run, through `hub step` subcommands that validate with core's models and create
  exclusively; the run never commits: its report names the changed hub files for the owner's hub PR. A ticket resumes
  as soon as the files exist locally, without waiting for that PR.
- **The owner decides plan drift through the engine's gate.** A `plan` drift opens a change request and pauses the
  run at an approval node (decisions approve / decline, note captured). Hub web, the ticket panel and the CLI answer
  that gate (`POST /approvals/{approval_id}/decision`); a decision with no person (empty or `unknown` approver) is
  refused. Only people approve or decline; no agent does.
- **When the run is gone,** hub web records the owner's decision itself: it creates
  `change-requests/<n>.decision.md` exclusively (never overwriting, symlinked folders refused) and leaves it
  uncommitted for the hub PR, as the owner sign-off does; the route refuses while the run's gate is open. The next
  `/implement` of the origin ticket reads it.
- **Workflows.** `implement` and its pass workflow ship in core's built-in `sdlc` pack and run from the release a hub
  pins; a hub's seeded `workflows/` copy stays the project's (sync neither updates nor deletes it). The discovery loop
  is the pass included up to three times, so the engine needs no nested loops.
- **Names.** `/feature` is the feature level, `/implement` the ticket flow, `/merge` an open PR to merged (it never
  approves or merges), `issue-to-pr` work outside a feature.

### Consequences

- Good: each level reads one way; a ticket's plan version, drift, decisions and outcome are auditable records.
- Good: the owner's decision is the engine's existing gate, so the guard, the cookie gate and the decision log apply.
- Bad: a run leaves uncommitted files in the hub's checkout until the owner's hub PR; two tickets amending one plan
  need a per-feature lock.
- Bad: `FeaturePhase` changes values (breaking for the in-repo web app only); old `?phase=` links are redirected.
- Bad: hubs keep stale seeded `sdlc` files (`deliver.yaml`, `review.yaml`) until their owner deletes or restores them.

## More Information

Spec, research and plan: the hub's `brain/features/two-level-flows/` (AGH-321). Delivered in three slices (S1 screen,
S2 ticket flow, S3 outcome, acceptance, names and lens wiring). Optional `hub.json` → `repos[].ui_paths` (globs) gates
the UX review lens; it is a config key validated by `hub doctor`, documented in the config design doc.
