# 0042. No limit on live sessions in the playground's conductor

- Status: proposed
- Date: 2026-10-19
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0036](0036-live-playground-and-auto-mode.md), for its line "The conductor keeps 16 live
  sessions and a day of idleness (the limits' ceilings), not 4 and 30 minutes", on the number of live sessions only
  (0036 is not edited; its day of idleness stands)

## Context and Problem Statement

The playground's conductor (`make playground`, ADR 0036) drives the owner's own sessions on their own checkout. It
started with 16 live sessions, the ceiling `hub web --sessions-max` allows. With several tickets, reviews and
background agents at once, 16 is within reach: a new session then ends the one idle the longest, or is refused
(429 `limit`) when all are busy, although nothing on the developer's machine needs that bound. The owner asked for no
limit there. The limit protects a shared or long-running `hub web` from runaway sessions; the playground is neither.

## Considered Options

1. Keep 16: the owner keeps losing idle sessions, or waits for one to end.
2. Raise the ceiling (for example to 64) for everyone: every `hub web` could keep that many live sessions, and the
   playground would hit the new bound later.
3. Let `--sessions-max 0` (`AGENT_HUB_SESSIONS_MAX=0`) mean no limit, and start the conductor with it; the default
   (4) and the ceiling (16) stay for every other `hub web`.

## Decision Outcome

Option 3.

- `SessionLimits.sessions_max` takes 0 to 16; 0 sets no limit: no live session is ended for the limit and no start or
  reopen is refused for it. 1 to 16 behave as before.
- `make playground` (`scripts/playground.sh`) starts its conductor with `AGENT_HUB_SESSIONS_MAX=0` and, as ADR 0036
  decided, a day of idleness (`AGENT_HUB_SESSION_IDLE_SECONDS=86400`).
- Every other limit (idle seconds, permission answer seconds, log records and bytes) keeps its range.

### Consequences

- Good: the owner keeps as many sessions live as their machine holds; none is ended behind their back.
- Bad: on the conductor, nothing bounds the `claude` processes but the machine itself; an idle session still closes
  after a day.
- Neutral: 0 is an explicit choice; no default or other script sets it.

## More Information

- The limits and their ranges: [design/agent-sessions.md](../design/agent-sessions.md) (Limits).
- Tracker: AGH-383.
