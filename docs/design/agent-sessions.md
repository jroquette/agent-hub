# Agent sessions: Claude Code sessions `hub web` drives

## Purpose

`hub web` opens Claude Code sessions and keeps talking to them as the desktop app does: send, interrupt, answer
permission prompts, change mode and model, close, resume, fork. It drives the user's own installed `claude`, never a
loop of its own ([ADR 0031](../adr/0031-driving-claude-code-sessions-from-the-app.md)). This file is the contract of
the core area `agent_hub.core.agent_sessions`, its adapter `agent_hub.claude_sessions` and what the API builds on
them; the routes and frames are in [API.md](../API.md#agent-sessions), the product rules in the
[SPEC](../SPEC.md).

## Contract

### Port and adapter

- `SessionDriver` (`driver.py`), async: `start(StartSpec)` → handle, `send`, `interrupt`, `answer_permission`,
  `set_mode`, `set_model`, `close`, `events(handle)` (an async iterator), `list_resumable(cwd)`, `capabilities()`.
  `StartSpec` holds a resolved `cwd`, the mode, an optional model, `resume` and `fork`, an optional `session_id` and
  `environment_extra` (`AGENT_HUB_WEB_URL` only).
- Driver events, a closed union: `init` (Claude's `session_id`, model, slash commands), `text.delta`, `text`,
  `thinking`, `tool.call`, `tool.result`, `todos`, `permission.request` (`request_kind`: `tool`,
  `ask_user_question`, `plan_approval`; suggestions), `result` (cost, usage, terminal reason), `error`, `exited`.
- `ClaudeSdkSessionDriver` (`claude_sessions/sdk_driver.py`, `claude-agent-sdk==0.2.165`): one `ClaudeSDKClient` per
  session, streaming input, partial messages, `can_use_tool` parked on a future, `cli_path` = the absolute
  `shutil.which("claude")` of `hub web`'s `PATH`; setting sources stay the CLI's defaults (CLAUDE.md, hooks, skills,
  agents load). Mode `default` maps to the CLI's own name when it differs; a mode is always passed (the CLI's default
  is `auto`).
- `CloudLauncher` (`cloud.py`), implemented by `ClaudeCloudLauncher`: `claude -p --cloud <id> --output-format json`,
  argv only, 60 s and 64 KiB. Starting a cloud session is link-out guidance (`claude --cloud` needs a terminal).
- `AgentSessionStore` (`store.py`), implemented by `SqliteAgentSessionStore`: tables `agent_sessions` and
  `agent_session_records` (migration 0004), primary key `(agent_session_id, seq)`; the store deletes records itself.

### The log

- Every session has an ordered log of `LogRecord`s (`seq`, `at`, `kind`, `by`, `body`), `seq` gap-free from 1. Driver
  records come from events; audit records (`user.message`, `permission.decision`, `interrupt`, `settings`, `close`,
  `log.truncated`, `cloud.*`) from what people or deadlines did, `by` `web`, `timeout`, `closed`, `driver` or `server`.
- Each record is built twice: the live copy (raw, within the caps) for subscribers in memory, the stored copy
  redacted with the event store's rule set. Text deltas never reach the store: a ring of at most 2,000 per session
  holds them for reconnects, superseded by the completed `text` record.
- Caps: 50,000 records or 32 MiB of text per session (16 records of headroom for the audit and terminal records),
  a tool result 64 KiB, an input summary 4 KiB, an error 2 KiB, a title 200 characters.
- `subscription.frames(after)` yields stored records after `seq`, then the ring's deltas after `n`, then live frames;
  a position it cannot resume gives a `reset`. At most 8 subscribers per session; one more detaches the oldest.

### State machine

| Status | Means | Moves to |
| --- | --- | --- |
| `idle` | no turn running (a new session without a prompt starts here) | `running` on a message |
| `running` | a turn is open | `waiting_permission`, `idle` on its `result` |
| `waiting_permission` | at least one request unanswered | `running` when all are answered |
| `ended` | closed, idle timeout, server stopped, log full | (terminal; Resume starts a new session) |
| `failed` | the CLI exited non-zero or broke the protocol | (terminal) |

`end_reason` is `closed`, `idle_timeout`, `server_stopped`, `failed` or `log_full`. A command on a terminal session
is refused (`terminal`, or `log-full` naming Resume); a command while an interrupted turn ends is `busy`.

### Commands and time

- `AgentSessionControl` (`control.py`) owns the live sessions in `hub web`'s event loop: `create`, `send` (queued
  while a turn runs), `interrupt`, `answer`, `change_settings`, `close` (idempotent), `delete` (ended only),
  `snapshot` (with the open request's raw summary), `events` (a page of the stored log), `subscribe`.
- No sleeps in core: `sweep(now)` applies permission deadlines (deny by `timeout`), the idle timeout and retention.
  The API's `SessionRuntime` sweeps every 0.5 s (no purge) and hourly (with purge), and on exit calls `shutdown()`:
  each session in parallel is interrupted, closed, its process group killed if needed, stored `ended` /
  `server_stopped`, all within 5 s. At start, rows a crash left open become `ended` / `server_stopped`.
- Workdirs: the registered hub, its repos (`hub.json` `repos[].dir`, siblings of the hub) and their
  `.claude/worktrees/*`, directories only, no link followed, at most 200 worktrees per repo; `workdir_id` is the first
  16 hex of SHA-256 over `kind\0realpath`, resolved only by lookup in a fresh listing.

- Title (ADR 0035): a driven session is named by its first prompt until Claude Code gives it a title (its
  `ai-title`, or the user's `/rename`), read through `session_title(cwd, claude_session_id)`. Acceptance criteria
  (AGH-267):
  - **AC-267.1** Given a live session not named yet whose first turn still runs, when `sweep` runs, then it reads the
    title at most once per `TITLE_POLL` (5 s) and stores it while the session keeps running.
  - **AC-267.2** Given a live session, when it ends (closed, idle timeout, server stopped), then its title is read once
    more before it is stored ended, so a session stopped during its first turn takes Claude Code's title.
  - **AC-267.3** Given stored sessions that ended unnamed (a server stopped before the title was read), when the first
    `sweep` of a new `hub web` runs, then each takes Claude Code's title; one whose project or workdir is gone keeps
    its own.
  - **AC-267.4** A title is still read at the end of each turn; a missing or failing reader keeps the current name.

### Limits (`SessionLimits`, `hub web` options and `AGENT_HUB_*` variables)

| Limit | Default | Range |
| --- | --- | --- |
| live sessions (`--sessions-max`) | 4 | 1-16 |
| idle seconds (`--session-idle-seconds`) | 1800 | 1-86400 |
| permission answer seconds (`--permission-timeout-seconds`) | 600 | 1-86400 |
| log records (`--session-log-records`) / bytes (`--session-log-bytes`) | 50000 / 32 MiB | 100-1000000 / 64 KiB-1 GiB |
| message bytes (`--message-max-bytes`) | 1048576 | 1024-4194304 |
| cloud command seconds (`--cloud-timeout-seconds`) | 60 | 5-600 |
| retention days after the end (`--session-retention-days`) | 30 | 1-3650 |

At the live-sessions limit, a start or a reopen first ends the local session idle the longest (no request open)
`idle_timeout`, `by: server`; a message reopens it in place. Only when every live session is running, waiting on a
request or a cloud one is the start refused (429 `limit`).

### Links

`AgentSessionLinks.link_of(project, claude_session_id)` (live sessions first, then the store) gives the folded
Session its `agent_session_id` and makes its live tile `waiting` while a request is open; the tile carries
`agent_session_id` too, so the web app links it to the chat (a hook-observed prompt links to Approvals).

## Chat behaviour

The chat at `/agent-sessions/:id` (`apps/web/src/screens/agent-session/`) is a full page
([ADR 0033](../adr/0033-sessions-and-chat-interaction-model.md)). Transport, access and storage stay as above.

- **Layout.** A fixed-height column: the header (title, status, cost, actions) and the composer stay on screen, the
  transcript is the only scroll container; messages and tool cards share one centred column (text about 80ch wide);
  the todo list collapses.
- **Scroll.** It opens at the latest entry, or at the oldest pending permission card when one exists. While the
  reader is within 24 px of the bottom, new entries and deltas keep it pinned; once they scroll up, nothing moves it.
  Send pins it again. A detached reader sees "Jump to latest" with the count of new entries ("3 new"); the button or
  End in the transcript scrolls to the bottom and hides it.
- **Streaming.** Deltas are batched per animation frame: one render and at most one Markdown parse of the streaming
  bubble per frame. The bubble shows a caret while it streams; while a turn runs with no text streaming, a "Claude is
  working · <tool>" row shows.
- **Stop.** Visible and enabled while `running` or `waiting_permission`. Esc in an empty composer with no menu open
  posts one interrupt; a "Turn interrupted" notice follows the turn's result.
- **Messages.** On hover or focus (always under `hover: none`) a row shows `<time datetime>` (relative text, absolute
  time in its title) and Copy, which copies the raw Markdown. Code blocks carry a language label and Copy; wide tables
  scroll in a wrapper; raw HTML stays inert text. A completed code block in a known language is syntax highlighted
  ([ADR 0034](../adr/0034-syntax-highlighting-in-the-chat.md)); one still streaming stays plain until its fence
  closes or the reply ends, and one over 2,000 lines or 64 KiB stays plain.
- **Tool calls.** Each card shows an icon and text: running, waiting for you, done, error or denied; a call with an
  open permission reads "Waiting for you". Output over 10,000 characters is cut with "Show all (N characters)". What
  Claude does between two messages (its calls and the thoughts between them) folds into one activity line that
  opens the Activity side panel (below). Thinking reads "Thought for N s" (from the previous record's `at`), else
  "Thinking"; thoughts with no call among them stay in the conversation.
- **Permission and question cards** (AGH-264). A pending card is raised, with a warning-tone halo, an icon tile and a
  "Waiting for you" badge; once answered it is flat and its outcome reads as a pill.
  - AC-264.1 A tool card shows what the call is for (the tool input's `description`) under its title, and the
    command as a terminal line (`$ ` before a Bash command) that wraps instead of scrolling sideways.
  - AC-264.2 "Always allow" names its rule on one line, cut with an ellipsis; the deny message field sits on its own
    row with Deny at its end; the `A` / `D` key hints show on Allow once and Deny only while the card itself has
    focus, and are not part of the buttons' names.
  - AC-264.3 An `AskUserQuestion` shows each option as a radio row (a checkbox row, with "Choose any", when several
    may be chosen) with Claude's description in view; a trailing "(Recommended)" becomes a Recommended tag and the
    answer sent keeps the label as Claude wrote it; "Other" reads "Write your own answer" and opens its field in place.
  - AC-264.4 Several questions show one page at a time: numbered steps above them (a tick, and "(answered)" in the
    step's name, once answered; the current one `aria-current="step"`), "N of M answered", Back and Next between
    pages, a single choice moving on to the next page, and Send answers on the last one, enabled once all are
    answered.
  - AC-264.5 A question card has no deny message and no red Deny: a neutral Skip question denies it plainly.
  - AC-264.6 An answered question keeps each question with the answer given, read from the `permission.decision`
    record's `answers`, and its outcome reads Answered or Skipped (not Allowed once); a plan reads "Plan approved ·
    <mode>" (the decision's `mode`) or "Kept planning".
- **Composer.** Grows up to 40% of the viewport. The draft is saved to `ah.chat.draft.<id>` in the browser after
  500 ms (not above 64 KiB), restored on reload, cleared once a send is accepted. It has focus on open unless a
  permission is pending and keeps it after Send. Enter does not send during IME composition or within 500 ms after
  `compositionend` or with Ctrl/Cmd+Alt (the allow chord; plain Alt+Enter sends); under `pointer: coarse` Enter is a
  newline. A send shows a "Sending…" bubble until the echoed
  record replaces it; during a running turn it reads "Queued: Claude reads it after this turn".
- **Ended.** A message to an ended local session resumes it in place
  ([ADR 0036](../adr/0036-live-playground-and-auto-mode.md)); its row and tile in Sessions carry a "Resume" link to
  this chat. Fork… in the header opens New session on its folder, mode and model, and starts a new conversation from
  it (`resume_session_id` with `fork`), keeping this one unchanged. Neither shows for a cloud or `log_full` session.
- **`/` menu.** `/` at the start of the composer lists the `init` record's slash commands and skills (at most 200,
  strings of at most 100 characters, de-duplicated; else "No commands"); typing filters, arrows move, Enter or Tab
  inserts, Esc closes, and Enter never sends while it is open. A polite live region announces its match count
  ("3 commands") or "No commands" when it opens and when the count changes.
- **Keys.** Ctrl/Cmd+Alt+Enter allows once and Ctrl/Cmd+Alt+Backspace denies the oldest pending tool permission
  (inert when none; a question or plan card ahead of it is skipped, and only the target's buttons carry
  `aria-keyshortcuts`); `a` / `d` do
  the same while a tool permission card has focus, except as the second key of a `g` sequence (`g a` goes to
  Approvals). The chords do nothing on a key repeat, during IME composition, when the `/` menu took the key or while a
  modal (`aria-modal`) is open;
  Shift+Esc focuses the composer; ArrowUp in an empty composer recalls the last prompt sent. The shortcut sheet has a
  "Chat" group. A new pending card never takes focus from a composer holding text.
- **Screenshots (AGH-266).**
  - AC-266.1: a screenshot thumbnail, in a chat message or in New session, opens it large in a lightbox; in the chat
    it only views (Download, close with Esc or the X).
  - AC-266.2: the chat shows the screenshot sent with the first message again after a reload: the browser keeps the
    latest 20 in IndexedDB (`agent-hub-screenshots`); the server still stores no image bytes. Without IndexedDB the
    copy lasts for the page only and a reload shows the record's "Screenshot attached" marker.
  - AC-266.3: in New session the lightbox is a markup editor: arrow, rectangle, ellipse, pen, highlighter and text
    (keys A, R, O, P, H, T), five colours, undo (Ctrl/Cmd+Z) and Clear. Done flattens the marks into the PNG that is
    sent and checks "Attach"; the chat then shows the image sent, marked up or not.
  - AC-266.4: a marked-up PNG over the screenshot limit (3,932,160 bytes decoded) is scaled down until it fits.
  - AC-266.5: Crop (key C) is one more entry of the edit history, so undo and Clear take it back; the area cut away is
    dimmed while editing, a crop under 10 image pixels is ignored, and the saved PNG keeps only the cropped area,
    marks included.
- **Images in a message (AGH-266).**
  - AC-266.6: an image pasted into the composer, dropped on it or picked with "Add an image" shows as a thumbnail
    above the text (open it to mark it up, or remove it); a message takes up to 10, more are refused with "A message
    takes up to 10 images."; the browser converts any image it decodes to a PNG scaled under the screenshot limit. A
    message with images needs text; a cloud session takes no image.
  - AC-266.7: `POST /{id}/messages` takes `screenshots[]` (1 to 10), each checked like the first prompt's screenshot
    before anything is logged or sent, and sent to Claude before the text.
  - AC-266.8: the `user.message` record keeps one marker per image, never its bytes; the chat shows the images this
    browser sent with each message (kept by the message's seq), else "N images attached".
  - AC-266.9: a message's text may be up to `--message-max-bytes`, 1 MiB by default (at most 4 MiB); the body caps
    are 64 MiB for a message and 16 MiB for a session's first prompt.
  - AC-266.10: the composer's toolbar shows mode and model as compact pills (icon, value, caret) over native selects,
    the mode tinting its pill; Stop shows only while a turn can be stopped; the hint sits under the bar.
- **Accessibility.** No serious or critical axe violation in any state (empty, streaming, waiting, detached, menu
  open, ended). The log keeps `role="log"` and `aria-busy` and has a visually hidden h2; under
  `prefers-reduced-motion` no caret, shimmer or smooth scroll animates.

### Activity and changed files (AGH-265)

- **AC-265.1** Given Claude made calls (and thought between them) between two messages, when the chat renders, then
  they read as one line counting the calls by kind, first seen first, then the time spent thinking ("Ran 3
  commands, read 2 files, thought 12 s"); Grep and Glob count together as searches, an unknown tool by its name.
- **AC-265.2** Given the session runs and the run has a call without a result, when the line renders, then it reads
  that call (name and summary) with a spinner instead of the summary; failed or denied calls add "N failed".
- **AC-265.3** Given an activity line, when it is pressed, then the Activity side panel opens with the run's steps in
  order (each thought and each call, expandable to its input and result); the line again, Close or Esc closes it
  and gives the focus back to the line. A step joining the run keeps the panel and an expanded call in place.
- **AC-265.4** Given a call of the run asks for a permission, when the run renders, then its card stays in the
  conversation under the line, answerable without opening the panel, and the call reads "Waiting for you".
- **AC-265.5** Given the panel opens, then it is a full-height drawer over the right of the page that never moves
  the chat: the free margin beside the centred column (400 to 520 px), the whole width when the chat is narrow;
  it slides in, not under `prefers-reduced-motion`.
- **AC-265.6** Given a session page's "What went wrong" panel, when every problem was dealt with, then it folds into
  one line, "Nothing needs you · the agent dealt with N problems: <count per kind, most frequent first>", with
  "Show N handled"; otherwise the problems that need the owner stay listed ("Needs attention") and the handled ones
  sit behind the same button. A row the agent recovered or continued past shows no badge.

- **AC-265.7** Given the session's calls changed files (Edit, MultiEdit, Write, NotebookEdit, subagents' included),
  when the header's Changed files chip is pressed, then a drawer lists every such file once, by folder like a
  source-control view, with its status (added or modified), lines added and removed and a Viewed mark; a change
  that was denied or failed stays listed but counts no lines.
- **AC-265.8** Given the list, when a file is opened, then it shows alone with every change to it as a diff in order,
  with previous and next file to step through; All files or Esc goes back to the list, and Esc on the list closes
  the drawer. On a wide page the list stays beside the open file.
- **AC-265.9** Given a file marked Viewed, when a later change touches it, then the mark goes; marks are kept per
  session in this browser (`ah.chat.reviewed.<id>`).
- **AC-265.10** Given the session changed files, then the header shows a chip with the file count and the lines added
  and removed in the diff colours, and how many files still wait for review (tinted); once all are viewed it is
  quiet with a check. Its accessible name says all of it.
- **AC-265.11** Given a turn whose calls edited files, then a card under its activity line reads "Edited N files +a
  −r" with a row per file (status, lines, viewed, the first few then "+N more"); a row opens that file in the
  drawer, Review opens the list.
- **AC-265.12** Given a drawer (Activity or Changed files), then its left edge resizes it by mouse, or by ←/→ when
  focused (Home resets, a double click goes back to the default), between 320 px and leaving the chat 280 px, and a
  button widens it to the page and back; the width is kept in this browser (`ah.chat.drawer.width`).
- **AC-265.13** Given one drawer is open, when the other is asked for (a run line, the chip), then it takes its place:
  one drawer at a time.

- **AC-265.14** Given a file tool ran and Claude reported its change (`tool_use_result.structuredPatch`, or a new
  file's content), when the driver maps its result, then the `tool.result` record carries that change as a unified
  `diff` with the file's real line numbers (capped like the call's diff, redacted like every stored string); a
  failed result, a message with several results or a report of another shape carries none, and a result without
  one keeps its body as before.
- **AC-265.15** Given a change with that reported diff, when the review or the activity panel shows it, then it shows
  git's two gutters (old and new line numbers) that stay in view while the code scrolls sideways; a change without
  one keeps the call's snippet diff, without numbers. A file's changes keep their height and its body scrolls
  through all of them.

- **AC-265.16** Given a change open in the review, when + beside a line is pressed (Shift+click another line takes
  the lines between) and a comment is written, then it is sent as a message to the session's own Claude: its first
  line anchors it ("Review comment on `<path>`, change N, lines a-b:"), then the code as a fenced diff, then the
  comment. It is kept in the session's log, reaches Claude and comes back after a reload. Without a way to send
  (an ended session that cannot resume) the review is read-only.
- **AC-265.17** Given a comment, then its thread shows under its last line with the comment, Claude's answers (its text
  after each message, up to your next one) and your replies ("Reply to review comment on …"); it reads as waiting
  for Claude while there is no answer, and Resolve folds it (kept per session in this browser,
  `ah.chat.resolved.<id>`). A thread whose lines left the diff is kept. The file list shows each file's open
  threads.
- **AC-265.18** Given a review comment in the chat, then it reads as one (file, lines, the comment) with a link that
  opens its file in the review.

## Invariants

- The platform implements no agent loop and calls no model; the children are the user's own `claude` with its own
  login. No platform code reads a token or opens `~/.claude/.credentials.json`.
- A child's environment is `hub web`'s own plus `AGENT_HUB_WEB_URL` (the bound address); never the token or the
  cookie name. Its stderr is discarded; no shell is used anywhere.
- Never a bypass mode (`bypassPermissions`, `dontAsk`); `auto` is accepted, but offered only by the dev app of
  `make playground` ([ADR 0036](../adr/0036-live-playground-and-auto-mode.md)); never a path from the browser.
- Stored text is redacted; the live view is not; no log line, problem detail or metric holds conversation text.
- Every request and decision is a record; an unanswered request is a deny, never an allow.
- No `claude` survives `hub web`; session control is off in the container (`AGENT_HUB_IN_CONTAINER=1`).
- The token is never on a command line: `--open` hands the browser a mode-0600 `file://` page that redirects to the
  token URL, removed when `hub web` stops.
- A workdir is listed only when its real path is owned by the current user and not group- or world-writable; the hub
  registry writes (`POST`/`DELETE /hubs`) need this server's exact `Origin`.
- "Always allow" applies only an `addRules` suggestion with behaviour `allow` and destination `localSettings`; every
  other suggestion is dropped before it is stored or shown, and refused (422).
- `claude_agent_sdk` is imported only by `claude_sessions`; core never imports it; `cli` never imports the adapter.

## Decisions

- [ADR 0031](../adr/0031-driving-claude-code-sessions-from-the-app.md): the engine, the token, the data exception,
  the cloud link-out; partially supersedes ADR 0017, 0019 and 0022.
- [ADR 0033](../adr/0033-sessions-and-chat-interaction-model.md): the chat's interaction model and the one Sessions
  screen that lists driven sessions with the observed ones.
- [ADR 0034](../adr/0034-syntax-highlighting-in-the-chat.md): syntax highlighting of completed code blocks with
  lowlight, rendered without an HTML path.
- [ADR 0019](../adr/0019-metadata-only-events-and-redaction.md): the redaction rule set the stored copy uses.
- [ADR 0024](../adr/0024-learning-actions-from-the-app.md): off in the container, as hubs are read-only there.

## Residual risks

- Cookies are not port-scoped on http: another local server on `127.0.0.1` (any port) receives the
  `agent_hub_<port>` cookie from the browser and could replay it here. The cookie lives for one launch only.
- The hook-observed copy of a session (the event store, the Phase 2 routes such as `/sessions/{id}/events` and
  Approvals) is readable without the token, like every route outside `/api/v1/agent-sessions/**`; it is metadata
  only (ADR 0019), never the drive log's conversation text.

## Open questions

- Firefox and WebKit: whether a same-origin `EventSource` sends an `Origin` (only Chromium is verified).
- The cloud follow-up: on once an owner run records the CLI's JSON answer (capability `cloud_followup`).
- The `/skill` list reads `<workdir>/.claude/skills/*/` names until the skills route of AGH-164 can serve it.
