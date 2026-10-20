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
| live sessions (`--sessions-max`) | 4 | 0-16 (0: no limit) |
| idle seconds (`--session-idle-seconds`) | 1800 | 1-86400 |
| permission answer seconds (`--permission-timeout-seconds`) | 600 | 1-86400 |
| log records (`--session-log-records`) / bytes (`--session-log-bytes`) | 50000 / 32 MiB | 100-1000000 / 64 KiB-1 GiB |
| message bytes (`--message-max-bytes`) | 1048576 | 1024-4194304 |
| cloud command seconds (`--cloud-timeout-seconds`) | 60 | 5-600 |
| retention days after the end (`--session-retention-days`) | 30 | 1-3650 |

At the live-sessions limit, a start or a reopen first ends the local session idle the longest (no request open)
`idle_timeout`, `by: server`; a message reopens it in place. Only when every live session is running, waiting on a
request or a cloud one is the start refused (429 `limit`). With `--sessions-max 0` (the playground's conductor) no
session is ended or refused for the limit.

**No live-session limit (AGH-383, [ADR 0042](../adr/0042-no-live-session-limit-in-the-playground.md))**

**Session limits (core)**

- **AC-383.1** Given `SessionLimits`, when `sessions_max` is 0, then it is accepted and means no limit on live
  sessions.
- **AC-383.2** Given `sessions_max` 1 to 16, when the limits are built, then they are accepted as before; -1 and 17
  are refused.
- **AC-383.3** Given no limit (`sessions_max` 0) and an idle session beside running ones, when another session starts,
  then none is ended for the limit: the idle one stays idle and the running ones keep running.
- **AC-383.4** Given no limit and 17 running sessions (more than the 16 ceiling), when another session starts, then it
  is not refused and starts idle.
- **AC-383.5** Given a limit of 2 with both sessions running, when a third starts, then it is refused
  (`LiveLimitError`, limit 2), and starts once one closes (unchanged behavior).

**hub web (cli)**

- **AC-383.6** Given `hub web --sessions-max 0`, when it starts, then it serves with no session limit (`sessions_max`
  0); its help says "Live agent sessions; 0: no limit."
- **AC-383.7** Given `AGENT_HUB_SESSIONS_MAX=0`, when `hub web` starts, then it serves with no session limit.
- **AC-383.8** Given `--sessions-max -1` or `17`, when `hub web` starts, then it refuses the value.

**make playground**

- **AC-383.9** Given `make playground`, when it starts the conductor, then it passes `AGENT_HUB_SESSIONS_MAX=0` (with
  `AGENT_HUB_SESSION_IDLE_SECONDS=86400`).

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

### Session review: changed files and pull requests (AGH-377)

**Review drawer (Changed files)**

**Kinds of file**

- **AC-377.1** Given a session that changed code, a plan under `~/.claude/plans/`, a brain note and a file in a
  temporary folder, when the review drawer opens, then the changed files are split into tabs `Code`, `Plans`,
  `Learnings` and `Scratch` (each with its count), the code first and Claude's scratch last, and the Code tab lists
  only the code.
- **AC-377.2** Given a markdown file in the review, when it is opened, then it opens rendered with its frontmatter
  apart (labelled "Frontmatter"), and the diff is one click away (`Each change`).
- **AC-377.3** Given a diff was shown for a code file in the drawer, when the next file is a markdown file, then it
  opens rendered (`Preview` pressed), not as a diff.
- **AC-377.4** Given a card in the conversation asks for a file of another kind (a plan), when the drawer opens on it,
  then the drawer is on that file's tab (`Plans` selected) with the file open.
- **AC-377.5** Given a feature's records under `brain/features/` (spec, plan, research, evals, the workflow's spec and
  quality reviews), when the drawer opens, then they have their own tab named `Reviews & specs`, out of the Code tab
  and its review count, and the brain's other notes (decisions, inbox…) are in `Learnings`.
- **AC-377.6** Given the Code tab is shown and git compared the repositories, when the tab's note reads, then it says
  "What the pull request has, whoever changed it (<branch> against <base> · <n> commits)."

**Viewed marks**

- **AC-377.7** Given a session with code and Claude's plans, learnings and scratch, when the drawer lists them, then
  only the code has a `Viewed` checkbox and an "N of M viewed" progress; Claude's files have none, in the list or the
  open file.

**Names, root line and the file list**

- **AC-377.8** Given files in a worktree (`<repo>/.claude/worktrees/<name>/…`), when the list shows its root, then the
  root line shows the repo and the worktree's name in bold, the rest of the path after it, the whole path on hover,
  and a `Copy folder path` button.
- **AC-377.9** Given a session whose folder label is `<repo>` and files under it, when the root line shows, then the
  label is in bold followed by the rest of the path.
- **AC-377.10** Given files outside a worktree and the session's folder, when the root line shows, then it shows the
  full root with the home folder as `~`.
- **AC-377.11** Given a long file or folder name in the list, when it does not fit, then it stays on one line, cut in
  the middle, the file keeping its extension (a folder its last name), and its whole name shows on hover.
- **AC-377.12** Given a file is open, when its header shows, then it shows its whole path (wrapping, not cut) and a
  `Copy file path` button copies the full path.
- **AC-377.13** Given `CopyButton` in its compact form, when it shows, then it shows the icon alone with its label as
  the tooltip, and the same "Copied"/"Copy failed" feedback, announced.
- **AC-377.14** Given the drawer is wide enough for the list beside the open file, when the list's edge is focused and
  → / ← / Home are pressed, then the list widens, narrows, resets to its default, and the width is kept in this
  browser.
- **AC-377.15** Given any drawer width, when the list is resized, then the open file never gets under 360px and the
  list never over 60% of the drawer; when the drawer narrows, the open file gets its room back.

**Files read from git (the pull request)**

- **AC-377.16** Given git read the session's repository, when the Code tab lists files, then it lists every file git
  says the branch changes against the base it forked from (committed or not, untracked included, deleted with `D`),
  whoever changed them, then the session's other files.
- **AC-377.17** Given a file git read, when it opens, then it opens on `Final result`, git's diff "Against <base>:
  every commit and uncommitted change, as the pull request shows it", with Claude's changes still under `Each change
  (n)`.
- **AC-377.18** Given a file git read, when `Commits (n)` is chosen, then it lists "Uncommitted changes" first (when
  there are), then the commits that touched the file newest first, each with its short sha, subject and lines.
- **AC-377.19** Given a comment on git's diff of a file, when it is sent, then it anchors to the file's final diff
  (change 0) with the file's real line numbers.
- **AC-377.20** Given a file the session changed that git lists nowhere, when it opens, then it says the file ends as
  it is on the base; a file with no diff to show reads as binary or too big.
- **AC-377.21** Given a commit row in a file's Commits view, when it is pressed, then it opens on what that commit
  changed in the file, read from git (`repo-changes/commit`), and opening it again does not read it again.

**Repositories and pull requests**

- **AC-377.22** Given git read a repository, when the Code tab shows, then it lists the repository with its branch,
  its base and how many commits (`dem-1 → origin/main · 0 commits`), a link to its pull request (`PR #7`, opens in a
  new tab) and where it stands; the list shows on the Code tab only.
- **AC-377.23** Given a repository's pull request and its state, when the state is read, then it says "In sync with
  the pull request", "N file(s) changed since the pull request", "Commits not in the pull request yet", "N files not
  committed", "Pull request merged", "Pull request closed", "Worktree removed: its recorded commits" or "No pull
  request yet".

**Totals**

- **AC-377.24** Given a session that changed code and Claude's brain notes, feature records or scratch, when the
  drawer's header totals the change, then it counts the code alone ("1 code file · +1−0"), and says "No code changes"
  when there is no code.

**Header chip and sessions list**

- **AC-377.25** Given code and Claude's own files changed, when the header chip reads, then its files and lines are
  the code alone and only the code waits for review ("Review changes: 1 file, 1 lines added, 0 removed, 1 to review").
- **AC-377.26** Given a session's changed files in the sessions list, when it counts what to review, then Claude's
  plans and scratch are neither counted nor waiting for review.

**The turn's files card**

- **AC-377.27** Given a turn that only edits files an earlier turn created, when its files card shows, then it says
  "Edited N file(s)", not created.
- **AC-377.28** Given a turn that changed code, a plan and scratch, when its files card shows, then the code comes
  first labelled as what "goes in the pull request", then Claude's plans, learnings and scratch under their own
  labels, the scratch "not for review" (no review dot).

**Review threads**

- **AC-377.29** Given a review thread with your comment, Claude's answer and a reply being sent, when it shows, then
  it reads like a GitHub conversation: a header with its lines and "N comments", each comment with its avatar, author
  ("You" / "Claude" with an `Agent` badge) and "commented" (first), "replied" or "sending…"/"writing…", and a footer
  with `Reply…` and `Resolve`.
- **AC-377.30** Given an open thread, when `Resolve` is pressed, then it folds to its header "Resolved conversation on
  <lines>", `Show` opens it again (read-only, no reply), and `Reopen` brings back `Resolve`.

**API: repo-changes (`GET /api/v1/agent-sessions/{id}/repo-changes`, `…/repo-changes/commit`)**

- **AC-377.31** Given a session that changed files in a repository's worktree (not the hub), when repo-changes is
  read, then each repository the session worked in is read by git once (its own repo first), the hub never is, and a
  repository git cannot read is named in `warnings`.
- **AC-377.32** Given a checkout on a branch with commits, staged, unstaged and untracked changes, when git reads it,
  then every file that differs from the fork point is listed with its status, lines, final diff, its commits and
  whether it is uncommitted, and each file's fingerprint changes when its diff does.
- **AC-377.33** Given a session whose calls name a listed worktree (a command run there, a subagent sent there) but
  whose file tools changed nothing there, when repo-changes is read, then that worktree is read; a repo's main
  checkout named in passing is not, nor a text that only starts like a worktree path.
- **AC-377.34** Given a worktree started from another branch, when git reads it, then its base is the branch it was
  started from (its reflog's `Created from`, else an upstream that is not its own pushed copy), the remote's default
  only without either, and nothing without any base.
- **AC-377.35** Given a commit diff is asked, when the file is in one of the session's repositories, then git shows
  what the commit (7–40 hex digits) changed in the file and its name before a rename; an empty diff when the commit
  did not touch it.
- **AC-377.36** Given a commit diff is asked, when the file is outside the session's repositories or git does not know
  the commit, then the answer is not found.
- **AC-377.37** Given a commit diff is asked with a ref (`HEAD`, `origin/main`), an option (`--output=x`), fewer than
  7 or more than 40 hex digits, a relative path or no path, when the route reads it, then it answers 400 and never
  calls the session control; given the adapter is called with an option-like sha, then it refuses.
- **AC-377.38** Given repo-changes is read, when git read a repository, then the session records it in
  `review_targets` (repo, folder, branch, base, fork and head commits, pull request number and URL), kept by the
  store.
- **AC-377.39** Given a recorded worktree that is gone, when repo-changes is read, then it is read from its recorded
  commits in the repo's own checkout (else `origin/<branch>`), named under the old folder, its source `recorded`;
  unless the session now works on that repo elsewhere, then it is left out. Recorded commits git no longer has, or
  that read as options, cannot be read.
- **AC-377.40** Given a branch, when its pull request is read, then it comes from `gh pr list --head <branch>`, asked
  at most once a minute; when GitHub does not answer, the recorded pull request shows (state `UNKNOWN`); a branch that
  reads as an option names no pull request.
- **AC-377.41** Given migration 0007 (after 0006), when the database is upgraded and downgraded, then `agent_sessions`
  gains `review_targets` (`[]` for existing rows) and loses it again, rows kept.
- **AC-377.42** Given the OpenAPI document, when it is built, then the two repo-changes routes are listed with the
  agent-session paths and are behind the same access check as the others.

### Chat: opening, answers, links and the slash menu (AGH-379)

**Chat (agent session)**

**Where the chat opens**

- **AC-379.1** Given a chat that follows the bottom and has nothing waiting for you, when the earlier entries load a
  frame after the first render, then the chat stays at its latest message and is not detached (the position read
  before the stick-to-bottom hook's first write is not restored).
- **AC-379.2** Given a pending card inside an activity group (a settled, contained entry that becomes the card's
  offsetParent), when the chat opens, then it opens on that card, measured against the scroller, not near the top.

**Links in Claude's replies**

- **AC-379.3** Given Claude's reply names a bare URL at the end of a sentence, when it renders, then the URL is a link
  without the sentence's full stop.
- **AC-379.4** Given Claude's reply names `owner/repo#n`, or `repo#n` for a repo of the project, when it renders, then
  each is a link to that pull request on GitHub; `repo#n` for a repo outside the project stays text.
- **AC-379.5** Given Claude's reply names a ticket of the project's tracker teams, when Linear's workspace is known,
  then the ticket links to it in Linear; else it opens its feature's page here; a ticket of another team, or one no
  feature names without Linear, stays text.
- **AC-379.6** Given Claude's reply names a file of the session's review by its full path, or by a tail that names one
  file only, when it is clicked, then the file opens in the review drawer; a path that is not a file of the review
  stays text.
- **AC-379.7** Given a reply with nothing to link (a fraction, `and/or`), when it renders, then it is left as text.
- **AC-379.8** Given Markdown with a refs finder, when the text names a ref in prose, in a whole code span, or inside
  an existing link, then prose and the whole code span become links and the existing link is kept as it is; an action
  ref renders as a button that opens it in the page.
- **AC-379.9** Given a session whose project tracks team `AGH` and whose Linear workspace is known, when Claude's
  reply names `AGH-7` and your own message names it too, then only Claude's mention is a link (to
  `https://linear.app/<workspace>/issue/AGH-7`).

**Slash menu**

- **AC-379.10** Given the CLI's init lists subagents, when the `/` menu opens, then they follow the slash commands and
  skills, each once, as `/agent-<name>`.
- **AC-379.11** Given the CLI's init names `agents`, when the driver maps it, then the init event carries those
  agents.
- **AC-379.12** Given a `/word` at the caret, when it starts the text or follows a space, then the `/` menu opens on
  it; past the start only when something matches, so a path such as `see /tmp/x` keeps its Enter and sends; picking a
  command inserts it in place.
- **AC-379.13** Given the project's hub catalog, when the menu lists options, then the hub's skills a user may call
  show as `/name` and its agents as `/agent-name` (hooks and model-only skills left out), tagged "hub" ("…, from the
  hub"), first; the session's own commands the hub does not offer follow (a plugin-prefixed copy of a hub item is not
  listed twice).
- **AC-379.14** Given a session in a repo or a worktree, when the workdirs are listed, then each such workdir carries
  the hub's plugin folders (those holding `.claude-plugin/`, real path inside the hub); the hub's own workdir carries
  none.
- **AC-379.15** Given a workdir with the hub's plugins, when a session starts there or is reopened by a message, then
  the CLI is started with those plugins (`plugins: [{type: "local", path}]`); with none, no plugin is passed.
- **AC-379.16** Given the session knows a command or agent only by its plugin name, when a message uses the short name
  (`/fix`, `/agent-researcher`), then it reaches the CLI as `/hub-workflow:fix` and `@agent-hub-workflow:researcher`;
  a name the session knows as is, an ambiguous or unknown name, and `/agent-` not at the start or after a space are
  left as typed (an unknown `/agent-x` still becomes `@agent-x`).
- **AC-379.17** Given the CLI's `initialize` answer, when its names are read, then `commands` and `agents` are taken
  by `name` and anything missing or malformed is ignored.
- **AC-379.18** Given a hub item in the open menu, when its open icon is clicked or Ctrl/Cmd+Enter is pressed on the
  active option, then its skill or agent page opens in a new tab and nothing is inserted.
- **AC-379.19** Given the menu's options, when they render, then the command column keeps one width and the
  description takes the rest, cut with an ellipsis. (CSS only.)

**Feature detail (record approval)**

- **AC-379.20** Given a spec whose open question lists options under it, when it is opened, then its answer is a
  choice of those options, the one marked `(recommended)` tagged Recommended and picked by default, and picking
  another sends it as the answer (`- Q1 (Cache): On disk`).
- **AC-379.21** Given an open question without options, when it is opened, then the choices are Take the
  recommendation (picked when the record recommends one) or Let Claude decide (picked otherwise), and Other, which
  opens a box for a free answer ("Your own answer to Q…") and focuses it.
- **AC-379.22** Given an option list in the record, when it is read, then each nested item gives a label, a
  description and whether it is recommended; a wrapped line continues the last option; the marked option is the
  recommendation when the prose names none, and the prose wins otherwise.
- **AC-379.23** Given the chat's option row moved to the shared components, when a chat question card is answered,
  then it behaves as before (option, Other text, Recommended tag).
- **AC-379.24** Given the requirements analyst's template, when a hub is rendered, then it asks for one list item per
  question and, when the answer is a choice, 2 to 4 options as a nested list with the recommended one marked; the
  rendered goldens and lock hashes match.

### Background agents and session names (AGH-380)

**Sessions engine (core, claude_sessions)**

- **AC-380.1** Given the SDK sends `task_started`, when it is mapped, then it becomes a running task record (task id,
  description, the calling tool use, the CLI's `task_type`).
- **AC-380.2** Given a `task_notification` with completed, failed or stopped, or a `task_updated` with killed, when it
  is mapped, then the task's end is recorded (killed reads stopped); a `task_updated` that is not terminal or names no
  task, and `task_progress`, map to nothing.
- **AC-380.3** Given a `task_updated` saying `running` (a finished agent resumed by a message), when it is mapped,
  then the task runs again.
- **AC-380.4** Given an idle session with a task running, when the idle limit passes, then the session is not ended;
  the idle timeout counts from the last task's end.
- **AC-380.5** Given the live-session limit is reached and the only idle session has a task running, when a new
  session is started, then that session is not ended to free a slot (the start is refused).
- **AC-380.6** Given a running task, when it is stopped, then the CLI is asked to stop it (the SDK's `stop_task`); a
  task not running here is left alone, with no error.

**API**

- **AC-380.7** Given a session, when `POST /agent-sessions/{id}/tasks/{task_id}/stop` is called, then it answers 202
  with the session and calls the control's stop once; an unknown session answers the 404 problem; without session
  control it answers not implemented.
- **AC-380.8** Given the stop route, when it is called without the session cookie, with a wrong cookie or one of
  another port, without the server's own Origin (missing, foreign, cross-site), with a body that is not JSON, or in
  container mode with sessions off, then it is refused before any port is called, as the other session write routes
  are.
- **AC-380.9** Given a task id that is not 1-64 of `[A-Za-z0-9_-]`, when the stop route is called, then it is refused
  and no port is called.
- **AC-380.10** Given the OpenAPI document, when it is built, then the stop route is one of the agent-session paths
  (18).

**Chat (agent session)**

- **AC-380.11** Given an idle session with background tasks running, when the header shows its status, then it reads
  "Background · N agents" (and ", N commands" for commands), not Idle.
- **AC-380.12** Given an idle session with tasks running, when the live bar shows, then it lists them oldest first as
  working in the background ("Running in the background: 1 command"), its timer from the oldest task's start; once
  every task ended, or the process exited, the bar is gone.
- **AC-380.13** Given tasks ran, when the header chip shows, then it reads "Background tasks, N running" (else "N
  done") and is hidden with none; clicking it, or the live bar between turns, opens the Background drawer.
- **AC-380.14** Given the Background drawer, when it opens, then it lists the running tasks (agents with their calls
  so far, commands) and folds the ended ones under Completed with their status; Esc closes it.
- **AC-380.15** Given a running task in the drawer, when Stop is clicked, then `POST …/tasks/{task_id}/stop` is sent
  with an empty JSON body and the button waits for the task's end; a failed stop says "Could not stop it"; without a
  way to stop (cloud, ended) no Stop is offered.
- **AC-380.16** Given a finished agent resumed by a message, when its task runs again, then it reads as running from
  that moment.
- **AC-380.17** Given tasks run, or one ended since the last message, when the conversation ends, then a card after
  the last entry says it ("2 background tasks done, 2 running", "1 background command running") and opens the drawer;
  with nothing new it is hidden.
- **AC-380.18** Given a log without task records, when it holds a background `Agent` call (`run_in_background`) and
  its subagent's calls, then the agent reads as running until its last call is a SubagentHandback (completed), a
  TaskStop of its agent id (stopped) or the process restarts (stopped); a SendMessage to it after its end runs it
  again; a recorded task is counted once.
- **AC-380.19** Given the stream, when task records arrive, then the chat listens for them (every record kind of the
  API is streamed, checked at typecheck).

**Session names (sessions list, session detail, chat header)**

- **AC-380.20** Given a session whose label has a ticket, when it is named, then it reads `<ticket>: <what>`: the
  ticket's title once read, else the hub feature's slug for the ticket, else what the branch or worktree says after
  the whole ticket id, else Claude's title; without a ticket, the title rule is unchanged.
- **AC-380.21** Given the sessions list, when a row is on a ticket a feature works on, then it is named by the
  feature's slug, the feature shows as a label that opens its panel, and the list never reads the feature's tickets
  (no `/tickets` request); a title already in the cache names it.
- **AC-380.22** Given the session detail of a session on a ticket, when it opens, then the feature's tickets are read
  once and the heading reads the ticket's title, with the feature label linking to its panel.
- **AC-380.23** Given a chat whose observed twin is on a ticket, when it opens, then its header and breadcrumb read
  the ticket's name from the twin's label (the title once read) and show the feature label.

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
