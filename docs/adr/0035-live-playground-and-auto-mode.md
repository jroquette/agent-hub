# 0035. A live playground for agent-hub's own web app, with Claude Code's auto mode

- Status: proposed
- Date: 2026-10-16
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md), for the `auto` permission
  mode only (0031 is not edited)

## Context and Problem Statement

Changing the web app took a ticket, a worktree, a spec, a PR, a release and a hub sync before the owner saw the
result. The owner wants to ask Claude for a change from the app itself (a shake), and watch it land in seconds, on
the frontend and on the API, without approving each step; an idea that holds up is then done properly. `make dev`
almost did it, but a session driven by `hub web` runs inside the very server a Python change restarts, so the change
ended the session; the session started outside the served checkout, so its edits never showed; and every command
asked, since the web offered `default`, `acceptEdits` and `plan` only.

## Considered Options

1. Keep `make dev` and approve each step in the chat: the session still dies on an API change.
2. `bypassPermissions` for the playground's sessions: nothing asks, and nothing stops a risky action either.
3. A playground of three processes, and Claude Code's `auto` mode for its sessions: a classifier approves the safe
   actions and blocks the risky ones, as in an interactive Claude Code session.

## Decision Outcome

Option 3, for the developer's own checkout of agent-hub only.

- `make playground` starts a conductor (`hub web` on 7420, run from a copy of the checkout taken at each start,
  committed and uncommitted files alike) that drives the sessions, and `make live`: the checkout's own `hub web` on
  7421, restarted on each Python change by `scripts/live_api.py`, and the web app on 5173. Vite sends the
  agent-session routes to the conductor and the rest of `/api` to 7421, so a restart never ends a session; the
  three share the event database, which is why the conductor runs the same code.
- The owner opens one address: `/__playground/session?token=` on 5173 trades the conductor's launch token for its
  cookie and redirects to the app.
- The dev app offers `auto` besides the three modes, and a shake or New session preselects it, with the project and
  the folder of the served checkout (a hub listing it, `agent-hub-hub`, makes it a session folder). Built apps and
  every other screen keep the three modes; `bypassPermissions` and `dontAsk` stay refused by the server.
- The conductor keeps 16 live sessions and a day of idleness (the limits' ceilings), not 4 and 30 minutes.
- A `CLAUDE.local.md` in the checkout (never committed) gives the playground's sessions their working rules.

### Consequences

- Good: a request becomes a visible change in seconds, on either side, and the session survives it.
- Bad: three processes; the routes that need the playground server's own launch cookie (gate decisions, run starts,
  learning decisions) fail on 5173, as its token changes on each restart.
- Bad: a playground session acts without asking within what the classifier allows; it works on a local clone only,
  where git undoes it, and the server still refuses `bypassPermissions` and `dontAsk`.
