# 0021. Hook event sensor and envelope v1

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (delegated to the lead for AGH-200)

## Context and Problem Statement

Live sessions need hook events within a second, from stdlib Python 3.9 hooks that must never change a session's
outcome. How do hooks send events, and how do the guard and Stop gate report their own decisions?

## Considered Options

1. Hooks write to the SQLite file directly (needs SQLAlchemy-free schema knowledge in 3.9 code; lock contention).
2. Hooks append to a spool file that `hub web` tails.
3. A sensor hook POSTs an envelope to `hub web` on loopback, fire and forget.

## Decision Outcome

Option 3. Managed template `plugin/hub-workflow/hooks/event_sensor.py` registered (matcher `*` where a matcher
applies) for SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Notification, SubagentStart,
SubagentStop, Stop, PreCompact and SessionEnd (eleven; the spec listed nine before PostToolUseFailure and
SubagentStart were verified against Claude Code 2.1.296). Envelope v1:
`{v: 1, project, repo, run, step, attempt, sent_at, hook, decision}`, `decision` null or
`{by: guard|stop_gate, kind: deny|ask|block, rule, command, exit_code}`. POST `http://127.0.0.1:7420/api/v1/events/hooks`
(override `AGENT_HUB_WEB_URL`, loopback hosts only, else disabled), timeout 0.5 s, strings over 64 KiB replaced by
`{"_omitted_bytes": n}`, no output, exit 0 always. The guard and Stop gate call the same `post_envelope` after deciding;
their output and exit codes are unchanged (goldens).

### Consequences

- Good: no new dependency in hooks; at most 0.5 s per hook call when the server hangs, ~0 when it is down.
- Bad: events sent while `hub web` is down are lost (transcript backfill recovers tool calls, not guard decisions).
- Every hub's managed `.claude/settings.json` and `hooks.json` change once (`hub sync`, release note).

## More Information

Control-plane feature spec (AGH-200) D6, D7, D8 and errata E2 to E4; [SPEC](../SPEC.md) "Hooks as sensors";
[USING.md](../USING.md) (the sync release note).
