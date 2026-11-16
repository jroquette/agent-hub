# 0065. A launch token shared through a private file, and one rule for what needs the launch cookie

- Status: proposed
- Date: 2026-11-14
- Deciders: José Henrique Roquette (validated in the playground, snapshot `20261114T171258Z`; AGH-842)
- Supersedes: in part [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md), its **Access** bullet on two
  points only: the token may come from a file, and the cookie may be named after that file. Everything else in 0031
  stands, and its default (a fresh token in memory, `agent_hub_<port>`) does not change.

## Context and Problem Statement

ADR 0031 gives each `hub web` launch a fresh token, held in memory only, traded for an `agent_hub_<port>` cookie. Since
then the routes that need that cookie grew: run writes and reads, item writes (restores, Publish, the owner
sign-off) and owner writes (AGH-699). Two problems follow.

1. The playground ([ADR 0036](0036-live-playground-and-auto-mode.md)) runs two servers of one launch: the conductor
   on 7420 and the live API on 7421, restarted on each change. Each minted its own token, so the browser held the
   conductor's cookie only, and every cookie write that reached 7421 (the owner's sign-off, runs, gates) answered 401.
   ADR 0036 lists this as a consequence.
2. In any browser without the cookie (another browser, the address opened without `?token=`), the page did not know
   it was read-only. The owner filled in a form, then got a 401. The list of routes that need the cookie lived in the
   API's access checks only; the web app had no way to know which controls would fail.

How can two servers of one launch share one cookie, and how does the web app know, before any request, which of its
controls need the cookie?

Decision drivers:

- The token never on a command line or in an environment variable (the sessions a server starts inherit both).
- One list of the routes that need the cookie, used by the server's checks and the web app alike.
- No request of its own to learn whether the page holds the cookie.

## Considered Options

1. **`hub web --token-file <file>`**, a private file read at start, and a cookie named after the file; the API marks
   each operation that needs the cookie in its OpenAPI document, from its access checks.
2. The token in an environment variable shared by both servers.
3. A proxy that rewrites the cookie between the two ports.
4. A list of cookie routes kept by hand in the web app.

## Decision Outcome

Chosen option: **1**.

- **Token file.** `hub web --token-file <file>` reads the launch token from `<file>` instead of minting one. The file
  must be a regular file (not a link) of this user, with no group or other bits (mode 0600), and hold one url-safe
  token of at most 128 characters; else `hub web` exits 2 without printing the file. It is an option, never a
  variable. It is refused in the container (`AGENT_HUB_IN_CONTAINER=1`), where no token exists.
- **Shared cookie.** With a token file, the cookie is `agent_hub_<12 hex>`, the start of the SHA-256 of the file's real
  path, never of the token. Every server given the same file reads the same cookie, also after a restart. Without a
  token file, the cookie stays `agent_hub_<port>`.
- **The playground** writes a fresh token file at each start (mode 0600, in its private logs folder) and gives it to
  the conductor and to every start of the live API.
- **One rule.** `needs_launch_cookie(method, path)` is the union of the API's existing checks (agent-session routes,
  run writes and reads, item writes, owner writes). The API marks each such operation with
  `x-agent-hub-launch-cookie: true` in its OpenAPI document. An inventory test pins the mark to the write routes of
  the cookie class.
- **The web app** generates `LAUNCH_COOKIE_ROUTES` from the mark (`make openapi`). The shell read answers
  `launch_cookie`: `held`, `missing` or `off` (the container), from the same check as the agent-session reads, with
  no request of its own. While the page lacks the cookie, a banner says it is read-only and how to unlock it, every
  control of a marked operation is disabled with the reason, and `send()` refuses a marked write before any request.
  A real 401 from a marked operation teaches the app that the cookie is missing.

### Consequences

- Good: the playground's owner writes work on 7421, and a restart keeps the browser signed in.
- Good: a page without the cookie says so up front, instead of failing after the owner typed a note.
- Good: a new route that needs the cookie is marked by the same check that guards it; a web control that calls it
  fails the web inventory test until it reads the lock.
- Bad: with `--token-file`, the token lives in a file for as long as the launch. The file is private to the user, the
  same trust as the conductor's log, which already holds the launch address.
- Bad: the shared cookie is not tied to a port. Two launches given the same file share one cookie by design; two given
  different files do not.

### Why not the others

- 2: the sessions a server starts inherit its environment, so they would hold the owner's token.
- 3: a third moving part that must understand cookies, for the playground only.
- 4: it drifts from the server the first time a route is added.

## More Information

- AGH-842, the playground's v0.35.1 work, part 1. Code: `session_token.read_token_file`,
  `session_token.shared_cookie_name`, `session_access.needs_launch_cookie`, `web_command.launch_token`;
  `apps/web/src/api/launchCookie.ts` (generated), `apps/web/src/shell/LockedBanner.tsx`,
  `apps/web/src/launchCookieControls.test.ts`.
- Related: [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md) (the launch token and its cookie),
  [ADR 0036](0036-live-playground-and-auto-mode.md) (the playground), [ADR 0056](0056-screen-shaped-reads.md) (the
  shell read).
