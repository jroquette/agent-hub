# 0059. Every app offers Claude Code's auto mode, and an unanswered request waits a day

- Status: proposed
- Date: 2026-11-10
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0036](0036-live-playground-and-auto-mode.md), for where `auto` is offered only
  (0036 is not edited; the playground's preselection stands), and
  [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md), for the default wait of a permission request only
  (its sentence "Nothing answered within 10 minutes, an interrupt or a close is a deny"; 0031 is not edited)

## Context and Problem Statement

A teammate drove a session from `hub web` and stepped away. Claude asked a question (`AskUserQuestion`), and when
they came back the card read "Denied: no answer before the deadline". `hub web` denies any unanswered permission
request (a tool, a question, a plan approval) after `--permission-timeout-seconds`, which defaults to 600 seconds.
Ten minutes is too short for a person away from the screen, and a denied question costs the turn.

The same teammate wanted Claude Code's `auto` mode, where a classifier approves the safe actions and blocks the risky
ones. [ADR 0036](0036-live-playground-and-auto-mode.md) offers it only in the dev app of `make playground`: "Built
apps and every other screen keep the three modes and show `auto` only as a session's current mode, never as a
choice." The server already accepts `auto` from any client holding the launch cookie, and that holder is the owner,
who can already allow any request. So the limit is in the picker, not in what the server allows.

Decision drivers:

- A person who steps away comes back to the question still open.
- A developer outside the playground can pick `auto` without a dev server.
- No API change: `deadline_at` stays required, and the server's mode check does not change.
- `bypassPermissions` and `dontAsk` stay out of every picker and refused by the server.

## Considered Options

- **Raise the default wait to one day, and offer `auto` in every app.** One day is the option's existing ceiling
  (86400 seconds).
- Wait with no deadline. `deadline_at` becomes nullable, which changes the API and the card, and a request could
  hold a session open for good.
- Keep 600 seconds and tell people to start `hub web` with `--permission-timeout-seconds 86400`. Nobody finds the
  option before the first lost question.
- Offer `auto` only behind a new `hub web` option. It adds an option for a mode the cookie holder can already use.

## Decision Outcome

Chosen option: **raise the default wait to one day, and offer `auto` in every app**, because it fixes both
problems with two small changes and no new option or API field.

- `SessionLimits.permission_timeout_seconds` defaults to 86400 (one day); its range stays 1 to 86400.
  `--permission-timeout-seconds` and `AGENT_HUB_PERMISSION_TIMEOUT_SECONDS` still set it. A request's
  `deadline_at` is its ask time plus that wait, and the card still says when it will be denied.
- A session waiting on a request is not idle, so the idle timeout does not end it meanwhile.
- The mode picker of the composer, the New session dialog and the New feature screen offers `default`,
  `acceptEdits`, `plan` and `auto` in every app. A fork keeps its session's mode, `auto` included.
- Only the dev app of `make playground` preselects `auto` (a shake, or New session in the served checkout's
  project), as ADR 0036 decided. Everywhere else a new session starts in `default`.
- `bypassPermissions` and `dontAsk` are never offered, and the server still refuses them.

### What this supersedes

- [ADR 0036](0036-live-playground-and-auto-mode.md), in part: built apps now offer `auto` as a choice. The rest of
  ADR 0036 stands: the playground's processes, its sign-in address, its preselection of `auto` and its limits.
- [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md), in part: the default wait is one day, not
  10 minutes. An unanswered request, an interrupt or a close is still a deny.
- Neither ADR is edited, as accepted ADRs are never edited.

### Consequences

- Good: a question asked while the person is away is still open when they come back, for up to a day.
- Good: a developer can run a session in `auto` from any `hub web`, without `make playground`.
- Bad: a session can sit on an open request for a day and keep its `claude` process for that time. It still counts
  against `--sessions-max`, and a person who wants the old behaviour sets `--permission-timeout-seconds 600`.
- Bad: ADR 0031's spike saw a parked request survive 10.5 minutes with no SDK or CLI timeout; nothing has checked a
  full day. If the CLI ends the turn sooner, the session shows that end as it does today.
- Bad: an `auto` session acts without asking within what the classifier allows, now on any checkout, not only a
  playground clone. The guard hook still runs first, and in `auto` it denies where it would ask (AGH-430).

## More Information

- [ADR 0036](0036-live-playground-and-auto-mode.md): the playground and its `auto` mode.
- [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md): driving Claude Code sessions from `hub web`.
- [SPEC](../SPEC.md): Agent sessions, Control.
- [agent-sessions](../design/agent-sessions.md): the limits table and the invariants.
