# 0050. `/implement` is conducted in its own session, each agent stage a subagent

- Status: proposed
- Date: 2026-10-27
- Deciders: José Henrique Roquette (the owner set the direction for AGH-579: one session conducts the whole ticket)
- Partially supersedes: [ADR 0043](0043-two-level-feature-and-ticket-flows.md), for who conducts the ticket flow that
  `/implement` starts ("Who writes them": the `implement` run; "The owner decides plan drift through the engine's
  gate"). 0043 is not edited: its records, folds, names and the `implement` workflow stay as decided.

## Context and Problem Statement

hub web's Start on a ticket opens a Claude session with `/implement <ticket>`, and the skill ran
`./hub workflow run implement … --live` from the session's Bash. A project hub runs Bash in Claude Code's sandbox, so
the engine could not open its event store, and its first agent step (a `claude -p` child) failed with no transcript:
every ticket started from hub web failed. Even where it ran, the owner got a session that waited on a background run
whose stages they could not see or talk to. The owner wants the session that Start opens to be the ticket's only
conductor: it reports each stage in its chat, they can reopen it at any time and talk to it, and the ticket page still
shows each stage as recorded. Who conducts the ticket flow, and how do its agent stages keep the workflow's prompts,
output contracts and records?

## Considered Options

1. **The session conducts the ticket.** Each agent stage is a subagent the session dispatches with the Agent tool.
   The prompts and output contracts stay the workflow's, read through `hub step prompt` and `hub step output`; the
   records are written by the same `hub step` writers a run uses.
2. **Run the workflow outside the sandbox** (`hub workflow run` as an excluded command, AGH-577's approach). It
   works again, but the session still only waits on a background run with its own `claude -p` sessions, and the owner
   cannot talk to a stage.
3. **Skill prose with its own prompts.** The session runs the stages from prompts pasted into the skill. Two copies
   of each prompt and schema drift apart, and records written from them may not read as a run's do.

## Decision Outcome

Chosen option: 1.

- `/implement` starts no `hub workflow run`, `claude -p` child or other session. The session runs the workflow's
  stages in order (context, pending decision, preflight with its change request and re-check, worktree, ticket plan,
  implementation, review rounds, ticket eval, PR, delivery report) with the workflow's caps (three passes, three
  review rounds a pass), and writes a short result in its chat after each.
- `hub step prompt --stage STAGE` renders the stage's agent node's `prompt_file` with the given `with` values, read
  from the workflows the hub would run (its `workflows/` over the built-ins). `hub step output --stage STAGE` reads a
  reply as the workflow's agent runner does (last JSON line) and checks it with the engine's validator. The stages
  are the agent nodes that read only `$WITH`: `preflight`, `ticket-plan`, `spec-lens`, `quality-lens`,
  `ticket-eval`. The implementing session's prompt reads the run's own nodes (`$worktree.output`,
  `$LOOP_PREV.feedback`), so implementation follows `/feature` step 6 instead: one subagent a task of the ticket plan.
- The records name `session-<ticket>` as their run. No workflow run carries that id, so hub web decides an open
  change request at once (as for a run that is gone, ADR 0043); the session also takes the owner's decision in its
  chat and records it with `hub step decide`. Only people decide; the session never does.
- The review rounds also write the review records `/feature` writes (`reviews/<ticket>/<reviewer>-r<N>.json`,
  `reviews/<ticket>.md`), so the ticket's Implement, Review and PR steps are recorded.
- The worktree, the push and the PR are bare calls the sandbox excludes (`./hub worktree`, `git push`, `gh pr create`),
  after the owner's OK. A ticket stacked on a blocker in review takes this flow too (`--stack-on`).
- The `implement` workflow is unchanged, for hub web's Workflow runs screen and the CLI.

### Consequences

- Good: Start works in a sandboxed hub, and the ticket's whole story is one session the owner can reopen and steer.
- Good: one copy of each prompt and output contract; a test proves a record written in the session from an agent's
  reply equals the one a run writes from the same reply, but for its time and run id.
- Bad: the session follows the flow from the skill's prose, not an engine. A step it skips is not enforced by a
  graph; the records and the ticket page show what was written.
- Bad: the worktree starts from a fresh fetch, not from the exact commit the preflight read, as `hub step worktree`
  does for a run.

## More Information

AGH-579. The skill is `plugin/hub-workflow/skills/implement/SKILL.md` (generator template); the commands are
`agent_hub.cli.step_stages` and `step_command`; the parity tests are in
`packages/cli/tests/integration/test_step_stages.py`. Start's prompt is `apps/web/src/screens/feature-detail/StartTicket.tsx`.
