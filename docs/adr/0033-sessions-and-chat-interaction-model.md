# 0033. One Sessions screen grouped by status, and the chat's interaction model

- Status: accepted. Accepted by the owner, José Henrique Roquette, on 2026-10-14 (plan approval for AGH-234, all
  defaults).
- Date: 2026-10-14
- Deciders: José Henrique Roquette
- Supersedes: none. Amends the control-plane design specs
  [01 (navigation)](../design/control-plane/specs/01-navigation.md),
  [11 (live sessions, retired)](../design/control-plane/specs/11-live-sessions.md) and
  [14 (sessions list)](../design/control-plane/specs/14-sessions-list.md), and the web part of
  [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md)'s chat view without changing its transport, access or
  storage.

## Context and Problem Statement

The console's first user stopped using its sessions area and went back to the terminal. Two sidebar entries show
sessions: **Live sessions** (a tile grid of running sessions, fed by SSE) and **Sessions** (a filtered table of
observed sessions, with the sessions `hub web` drives in a separate list above it). A driven session shows up twice.
Nothing on a tile or a row says it opens. The New session dialog shows seven fields. The chat (ADR 0031) has no
scroll management: it opens at the top, never follows the stream, and its composer and Stop button fall below the
fold; code has no copy, the draft is lost on reload, and a tool call waiting for permission reads "Running".
(Evidence: the AGH-234 research and its audit, frictions F1 to F17.)

How should one screen show both kinds of session, ordered by what needs the owner, and how should the chat behave,
without new transport, a new store or a new runtime dependency?

## Considered Options

List:
1. **One Sessions screen with a grid/table toggle, both grouped in status sections**; observed sessions from
   `GET /sessions` (one query per section), plus the driven sessions that have no observed twin.
2. A new unified feed endpoint over both kinds, with server-side grouping and counts.
3. Keep two screens and only cross-link them.

Grouping:
1. **Sections, one query per status** with the existing `status` filter; counts from each query's `total_estimate`.
2. Group rows inside one table sorted by status; counts from a new endpoint.

Chat placement:
1. **Full page at `/agent-sessions/:id`**, rebuilt as a fixed-height column (sticky header and composer, transcript
   as the only scroll container).
2. A drawer or panel inside Sessions.

Markdown:
1. **Keep the in-house `apps/web/src/components/Markdown.tsx`** (React elements only, raw HTML inert, bounded),
   adding code-block chrome and a table wrapper.
2. `react-markdown` + `remark-gfm` (no `rehype-raw`).
3. marked + DOMPurify.

## Decision Outcome

Chosen: list option 1, grouping option 1, chat option 1, markdown option 1.

- **Sessions is the only sessions screen.** `/live` redirects (replace) to `/sessions?view=grid`, mapping
  `group=repo|run|workflow` to `within=` and dropping `group=flat` and unknown parameters (`project` is kept). The
  sidebar's live badge moves to Sessions; `g l` stays as an alias to the grid. `apps/web/src/screens/live-sessions`
  is deleted once its pieces move to `screens/sessions-list`.
- **Views:** `view=grid|table` in the URL, remembered in `ah.sessions.view`; the URL wins, the default is the grid.
  The grid uses `SessionTile`.
- **Status sections, needs-me first:** Waiting → Live → Idle → Ended or failed. Observed `waiting|live|idle|ended`
  map one to one (failed = `ended` with `outcome=error`, marked red); agent `waiting_permission|running|idle|
  ended|failed` map to the same four. A troubled session keeps its section and gets the red edge. Each section is
  its own paginated query, so counts come from the API and sorting, pagination and filters keep their meaning per
  section. The period filter applies to the Ended section only. Sections refetch on the existing live-tile stream
  (debounced), never moving a reader's scroll position.
- **API, additive only:** `Session` gains the tile fields that `LiveTile` already computes (`waiting_reason`,
  `last_action`, `last_tool`, `needs_you_problem`, `failing_notice`, `sparkline_60s` while running), derived in core
  read models from the same code; `AgentSession` gains `observed_session_id` (null when no twin), so the list shows a
  driven session once. No new payload key, no migration, no new route.
- **Open is explicit:** every tile and row has a visible primary button (Open, Open chat, Answer) and a real link;
  `j`/`k` and `Enter`/`o` work across sections. The Cloud guidance becomes a collapsed "Cloud sessions" details below
  the sections.
- **One Dialog primitive** (`apps/web/src/components/Dialog.tsx`) replaces the hand-rolled traps: header with title
  and close, footer, sizes, topmost-only Escape, scrim mousedown that started on the scrim, scroll lock, focus
  restore. The New session dialog shows only *where* and the *prompt*; mode and model sit under a collapsed
  "Options"; resume and fork move to a Resume action on ended driven sessions.
- **Chat interaction model:** opens at the latest message (or the oldest pending permission); follows the stream
  only while the reader is at the bottom (24 px), with a "Jump to latest · N new" button; deltas render at most once
  per frame; Stop works while running or waiting, and Esc in an empty composer stops; messages carry time and
  Copy; code blocks have a language label and Copy; tool calls show running, waiting for you, done, error or denied,
  long output is cut with "Show all", consecutive calls group into one "Explored" row; the composer grows, keeps a
  per-session draft in the browser, shows "Sending…" and "Queued", has a `/` menu of the session's slash commands and
  skills, and keyboard paths for Allow and Deny. Permissions, todos, cost and status keep their current domain. The
  details are in [docs/design/agent-sessions.md](../design/agent-sessions.md#chat-behaviour).
- **Open WebUI is design study material, not a dependency.** Open WebUI (github.com/open-webui/open-webui, Open WebUI
  License, a BSD-3 variant with a branding clause) was read as design study material at commit `6a18585` (v0.12.2)
  for chat and list interaction patterns. We write our own React code. Nothing was copied, no asset or branding is
  used, and `NOTICE` and `LICENSES/` do not change. Open WebUI is not affiliated with, and has not endorsed, this
  project.

### Consequences

- Good: one place to see and open every session, with what needs the owner on top; the chat reads like a chat
  (latest in view, composer and Stop always reachable); no new transport, store or dependency.
- Good: the API change is additive and generated (`make openapi`); old links keep working.
- Bad: four section queries instead of one (small pages, cached; acceptable for a local single-user server).
- Bad: `Session` grows six derived fields; `GET /sessions` does a little more work per row.
- Bad: the spec 11 screen and its e2e assertions are retired; the smoke test moves to Sessions.
- Neutral: syntax highlighting is a separate decision, with its own ADR if it is adopted.

## More Information

- Design: [docs/SPEC.md](../SPEC.md) (Layer 2, "Sessions and chat"),
  [01-navigation.md](../design/control-plane/specs/01-navigation.md),
  [14-sessions-list.md](../design/control-plane/specs/14-sessions-list.md),
  [agent-sessions.md](../design/agent-sessions.md). Tracker: AGH-234 and its children.
- Related: [ADR 0017](0017-api-second-composition-root.md) (`api` never imports `cli`),
  [ADR 0019](0019-metadata-only-events-and-redaction.md) (metadata-only events, payload allow-list),
  [ADR 0020](0020-web-stack-and-committed-build.md) (committed web build),
  [ADR 0031](0031-driving-claude-code-sessions-from-the-app.md) (driving sessions: SSE + POST, cookie, own store).
