# 0027. Driving Claude Code sessions from the app

- Status: accepted
- Date: 2026-10-14
- Deciders: José Henrique Roquette (gates delegated to the lead for AGH-165: D1 to D11, L1 to L12)
- Partially supersedes, none of them edited:
  - [ADR 0017](0017-api-second-composition-root.md)'s "No auth" consequence, for the routes under
    `/api/v1/agent-sessions/**` only (they need a per-launch cookie; every other route is unchanged);
  - [ADR 0019](0019-metadata-only-events-and-redaction.md)'s "no raw transcript text", for the conversations of
    sessions started from `hub web` only (stored redacted, in their own tables; the hook-fed events stay metadata-only);
  - [ADR 0022](0022-container-packaging.md)'s startup line: outside the container it is now
    `agent-hub at http://127.0.0.1:<port>/?token=<token>` (the container still prints the plain URL).

## Context and Problem Statement

`hub web` only observes sessions: every session route is a `GET`, approvals say "decide in the terminal", and nothing
in `packages/api` starts, talks to or stops Claude. The owner wants to open a Claude Code session from the app and keep
talking to it as in the desktop app, with full control (send, interrupt, answer permission prompts, change mode and
model, close, resume, fork). Three rules stand in the way. The SPEC's non-goal says the platform "is not a new agent or
an LLM runtime". ADR 0017 (`docs/adr/0017-api-second-composition-root.md`) gives the server no authentication:
anything on the machine can call it, and a write without an `Origin` passes. ADR 0019
(`docs/adr/0019-metadata-only-events-and-redaction.md`) and the domain model keep events metadata-only, and no entity
holds raw transcript text. The server also has no long-lived process model, and `api` cannot import `cli`'s process
helpers. Cloud sessions (claude.ai) have no supported API to list, stream or control them. How does the app drive the
user's own Claude Code, safely, without becoming an agent runtime?

## Considered Options

Engine:
1. The Python Claude Agent SDK (`ClaudeSDKClient`, streaming input, `can_use_tool`) behind a core port, running the
   user's own `claude` binary (`cli_path`), in a new adapter package wired only by `api`.
2. A `claude -p --input-format stream-json --output-format stream-json` subprocess behind the same port (the SDK's
   own protocol, less documented on the input side).
3. A PTY or tmux wrapper around the terminal UI (no structured permissions).
4. An agent loop on the Messages API (breaks the non-goal).

Transport: SSE for events with `Last-Event-ID` replay and same-origin `POST`s for commands; or a WebSocket.

Access: unauthenticated like the rest of the API; a per-launch secret exchanged for a cookie; a login system.

## Decision Outcome

Engine option 1 (the Wave 0 spike's go, 2026-10-13), with option 2 as the documented fallback behind the same port
(not built); SSE plus `POST`; a per-launch secret.

- **Scope.** The non-goal stays true: `hub web` drives the user's installed, unmodified Claude Code, as `hub run`
  already does, and implements no agent loop. The SPEC records this in Defined directions and the Phase 4 note.
- **Engine.** The adapter uses the Python Claude Agent SDK pinned at `claude-agent-sdk==0.2.165`: one `ClaudeSDKClient`
  per session with streaming input, `include_partial_messages`, a `can_use_tool` callback and an 8 MiB `max_buffer_size`;
  `cli_path` is the user's own `claude` from `PATH`, so the CLI bundled in the wheel never runs. The Wave 0 spike
  (2026-10-13, CPython 3.14.6, a stub CLI and the local Claude Code 2.1.296 against a local fake Messages API, no model
  called) showed: a permission request stays parked with no SDK or CLI timeout for at least 10.5 minutes; interrupt ends
  the turn with `aborted_streaming` or `aborted_tools`; resume keeps the session id and fork makes a new one, and the
  SDK's `session_id` option fixes the id before `init`; `disconnect()` leaves no process 5 s later, and shutdown
  interrupts a running turn first so the SDK's 5 s grace does not use the budget; the CLI's own default mode is `auto`,
  so the adapter always passes one (`default`, `acceptEdits` or `plan`; never `bypassPermissions`, `dontAsk` or `auto`).
  The SDK installs about 242 MiB, almost all of it the bundled CLI, so session control is the optional extra
  `agent-hub[sessions]`.
  Fallback, should the SDK stop fitting: an adapter running `claude -p` with stream-json in and out,
  `--include-partial-messages` and `--permission-prompts host`, in its own process group, behind the same port and
  contract suite. Setting sources stay at the CLI's default, so CLAUDE.md, the hub's hooks (guard, brief, stop gate),
  skills and agents load as in the terminal. Credentials are the user's existing `claude` login or `ANTHROPIC_API_KEY`;
  the platform never reads, stores or forwards a token, never opens `~/.claude/.credentials.json`, and has no login
  flow.
- **Port.** `SessionDriver` (`agent_hub.core.agent_sessions.driver`), async: `start`, `send`, `interrupt`,
  `answer_permission`, `set_mode`, `set_model`, `close`, `events`, `list_resumable`, `capabilities`. Events are a
  closed union (`init`, `text.delta`, `text`, `thinking`, `tool.call`, `tool.result`, `todos`, `permission.request`,
  `result`, `error`, `exited`). The fake `InMemorySessionDriver` and the suite `SessionDriverContract` live in core;
  core never imports the SDK. The use case `AgentSessionControl` owns the live sessions in `hub web`'s event loop: the
  state machine (`idle`, `running`, `waiting_permission`, `ended`, `failed`), the permission policy, the caps and the
  in-process notification of streams.
- **Adapter and packaging.** `packages/claude_sessions` (`agent-hub-claude-sessions` 0.1.0, outside the CLI's
  lockstep, `agent_hub.claude_sessions`) imports only `core` and sits in the adapters' layer; only `api` wires it;
  import-linter confines `claude_agent_sdk` to it and forbids `cli` from importing it. The SDK's platform wheels
  bundle a Claude Code binary (98 to 110 MB compressed for 0.2.165), so the adapter is an optional extra:
  `agent-hub[sessions]`. Without it, or without `claude` on `PATH`, session control reports why and every write
  answers 503. The adapter points the SDK at the user's own `claude` (absolute `shutil.which` result), so the bundled
  binary never runs.
- **Transport.** Each agent session has an ordered log with a gap-free `seq`, persisted in the `hub web` store. The
  browser reads it over SSE: a persisted record's id is its `seq`; text deltas live only in an in-memory ring (at most
  2,000) with ids `<seq>.<n>`, and the completed text record supersedes them, so a reconnect never loses content.
  Commands are same-origin `POST`s. No WebSocket: the security middleware closes any WebSocket scope (code 1008).
- **Access.** `hub web` mints `secrets.token_urlsafe(32)` per launch, held in memory only and printed in the URL
  (`/?token=`). A `GET` of a page with the token answers 303 to the same URL without it, setting
  `agent_hub_<port>=…; HttpOnly; SameSite=Strict; Path=/` (the port in the name, because cookies are not
  port-scoped). Every route under `/api/v1/agent-sessions/**` needs that cookie, reads included, compared with
  `hmac.compare_digest`; writes also need `Origin` equal to the server's own, `Sec-Fetch-Site: same-origin` when sent,
  and a JSON body; the stream refuses a foreign `Origin` or a cross-site `Sec-Fetch-Site` and accepts a missing
  `Origin` with a valid cookie (Chromium sends none on a same-origin `EventSource`; Firefox and WebKit unverified).
  This is an exception to ADR 0017's "no auth" for this route family only; every other route is unchanged, and the
  Host allowlist still runs first. `--open` never puts the token on a command line (another local user can read
  argv): the browser opens a `file://` page of mode 0600 that redirects to the token URL, removed when `hub web` stops.
  The hub registry writes (`POST /hubs`, `DELETE /hubs/{id}`) also need this server's exact `Origin`, a missing one
  refused, because a registered hub is a folder sessions may start in; a workdir is listed only when its real path is
  owned by the current user and is not group- or world-writable.
- **Permissions.** Modes `default`, `acceptEdits` and `plan` only; `bypassPermissions`, `dontAsk` and `auto` are never
  offered or accepted. A permission request reaches the browser with the tool, an input summary and Claude's
  suggestions; answers are allow once, deny with a message, or always allow with one suggested `addRules` rule with
  behaviour `allow` whose destination is `localSettings`. Any other suggestion (`setMode`, which could switch to
  `bypassPermissions`, `addDirectories`, other destinations) is dropped before it is stored or shown, and refused. `AskUserQuestion` and plan approval use the same path. Nothing answered within 10 minutes, an
  interrupt or a close is a deny. Every request and decision (by `web`, `timeout` or `closed`) is a log record. The
  hub's guard hook runs before any prompt and can deny first.
- **Conversation data (exception to ADR 0019).** Only sessions started from `hub web` store conversation text: in the
  `hub web` database (`agent_sessions`, `agent_session_records`), redacted with ADR 0019's rules before storage, at
  most 50,000 records and 32 MiB per session, tool results at most 64 KiB each (truncated with a marker), kept 30 days
  after the session ends, removed at once by "Delete session". The owner's live view is not redacted (he must see the
  exact command he approves); a reload shows the stored, redacted copy. No server log line, problem detail or metric
  holds conversation text. The hook-fed event store stays metadata-only.
- **Working directories.** Only the registered hub, its repos' checkouts and their existing worktrees, by an opaque id;
  never a path from the browser. No shell: messages and cloud tasks are single argv elements or SDK calls.
- **Lifecycle.** At most 4 live sessions, an idle timeout of 30 minutes, every limit a `hub web` option with an
  `AGENT_HUB_*` variable. A child's environment is `hub web`'s own plus `AGENT_HUB_WEB_URL` (the address `hub web` is
  bound to, so the hub's event sensor reports to it); never the token or the cookie name. Each `claude` child ends with `hub web` (interrupt, terminate, kill, within 5 s); nothing
  survives the server; a session left open by a crash is marked ended at the next start and can be resumed. An agent
  session links to the hook-observed Session by Claude's `session_id`.
- **Container.** Session control is off when `AGENT_HUB_IN_CONTAINER=1` (as ADR 0024 makes hubs read-only there): the
  routes answer 404, no token is minted, and the image ships neither `claude` nor the extra.
- **Cloud and remote.** Only what the CLI supports, as argv-only subprocesses (60 s, 64 KiB), never a claude.ai
  private API, credential or relay. The spike found `claude --cloud "<task>"` needs an interactive terminal and refuses
  `-p`, so starting a cloud session from the app is link-out guidance (the command to run, then the
  `https://claude.ai/code/<id>` link and `claude --teleport <id>`); a follow-up through
  `claude -p --cloud <id> --output-format json` stays behind a capability flag, off until an owner run confirms its
  JSON. Remote use of the local machine is documented, not built: an SSH tunnel or `tailscale serve` to the loopback
  port (token still required), or Claude's own Remote Control. Never a public bind.
- **Network.** The server itself makes no new outbound call; the `claude` children do, as when the user runs them.

### Consequences

- Good: the owner talks to Claude from the app with the desktop app's controls, and the session is the CLI's own, with
  the hub's hooks, guard and attribution rules.
- Good: one security model (Host, Origin, JSON, cookie) and one transport (SSE + POST); no WebSocket to secure.
- Good: the engine can change (SDK or stream-json) without touching the API, the UI or the acceptance tests.
- Bad: a new data class (conversation text) in a local database, with redaction, retention and a delete action to
  maintain; a reload shows redacted text where the live view did not.
- Bad: a token to handle: printed in the terminal, needed once per browser per launch; `localhost` and `127.0.0.1`
  hold separate cookies.
- Bad (residual risk): cookies are not port-scoped on http, so another local server on `127.0.0.1` (any port) is sent
  the `agent_hub_<port>` cookie by the browser and can replay it against this server; the port in the name only keeps
  two `hub web` launches apart. The cookie is per launch and dies with `hub web`; a process of the same user that runs
  such a server could read the terminal anyway.
- Bad (residual risk): the hook-observed copy of a session (the event store and the Phase 2 routes, such as
  `/sessions/{id}/events` and Approvals) stays readable without the token, as every route outside
  `/api/v1/agent-sessions/**` is: it holds metadata only (ADR 0019), never the conversation text of the drive log.
- Bad: one more package (and an optional extra of about 240 MiB installed) to register in the gates; the SDK's support of Python
  3.14 rests on the spike, not on its classifiers.
- Bad: sessions live and die with `hub web`; resume is the way back after a restart.

## More Information

Web sessions spec (AGH-165) D1 to D11, S1 to S8, AC-165.1 to AC-165.55, lead answers L1 to L12;
ADR 0017 (`docs/adr/0017-api-second-composition-root.md`), ADR 0019 (`docs/adr/0019-metadata-only-events-and-redaction.md`),
ADR 0022 (`docs/adr/0022-container-packaging.md`), ADR 0024 (`docs/adr/0024-learning-actions-from-the-app.md`);
`docs/API.md` "Agent sessions"; `docs/design/agent-sessions.md`; Claude Agent SDK docs (overview, Python reference,
user input, sessions) and Claude Code headless and cloud docs, read 2026-10-13.
