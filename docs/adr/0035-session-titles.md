# 0035. A session's short title, from its transcript

- Status: proposed
- Date: 2026-10-16
- Deciders: José Henrique Roquette
- Partially supersedes: [ADR 0019](0019-metadata-only-events-and-redaction.md), for one new event type,
  `session.title` (0019 and [ADR 0023](0023-short-error-message.md) are not edited)

## Context and Problem Statement

Sessions are told apart by their label (issue, workflow, repo, branch). Most sessions have no issue in their branch,
many have no workflow, and several share one repo and `main`: the list then shows `/feature` three times, or a bare
short id (`3a145194`), and the owner cannot tell what a session was for without opening it. Claude Code already names
every interactive session: its transcript holds `ai-title` lines (a short title its model writes from the
conversation, repeated as the session goes on) and, after `/rename`, `custom-title` lines. How may agent-hub show
that name without opening the door to prompt text?

## Considered Options

1. Keep metadata only and build a name from it (branch slug, files edited, subagent descriptions): no privacy change,
   but the result reads like the label it replaces.
2. Ask a model for a title from the transcript, in agent-hub: a model call per session, its cost, and a second
   summary of the prompt that Claude Code already wrote.
3. Keep the title Claude Code wrote (or the user set) as a new event type, `session.title`: redacted, whitespace
   collapsed, cut at 80 characters, one event per distinct title of an origin.
4. Read the title from the transcript on every list read, never storing it (a list reads dozens of files; a
   transcript can be gone).

## Decision Outcome

Option 3. The closed list of event types gains `session.title`, with payload keys `text` (the title, the same
`short_text` as a skill or subagent description: redacted with `r1`, then 80 characters) and `origin` (`ai` for
`ai-title`, `custom` for `custom-title`). The transcript mapper maps each title line: the title's whitespace runs
collapse to one space; the event takes the timestamp of the last user or assistant line before it (a title before any
such line is skipped: Claude Code writes it again later). A title is kept only when it differs from the last one
kept of its origin, so a title repeated hundreds of times is one event and a rename back to an earlier title is kept
again; its `source_id` is `<sessionId>:title:<origin>:<n>:<first 16 hex of sha256(kept text)>`, `n` (six digits)
counting the titles of that origin kept so far, so titles that share a timestamp still sort in file order. The live
tail carries the titles kept and the last timestamp from one read to the next, so a file read whole or in pieces
gives the same events. The session's `label` gains `title`: the newest
`custom` title, else the newest `ai` title, else `null`; it is derived on read with the rest of the label. Lists and
tiles show the title as the session's name, with issue, workflow, repo and branch below it; without one they show the
label as before.

Sessions stored before this release get their titles when their transcript is read again: after a restart, the live
tail reads a session's file from the start, and `hub collect --transcript FILE` maps a finished one. The other events
of such a file are duplicates and are kept as stored.

Prompts, assistant text, reasoning, successful tool output, file contents and diffs remain never stored.

### Consequences

- Good: every interactive session reads as what it was for ("Invoices B2B emissor por sales_mode"), with no model call
  and no cost: the name exists already.
- Good: one new type, two keys, bounded like the other short texts and covered by the payload table's property test.
- Bad: up to 80 characters per distinct title, written by a model from the prompt, are stored; a secret in a format
  `r1` does not know could be kept. The cap and the redaction bound it, as for the subagent `description`.
- Bad: a session without a transcript title (a `claude -p` run, a hook-only session whose file is gone) keeps the
  label it had. The transcript format is internal to Claude Code: if it stops writing these lines, sessions fall back
  to the label, never to a guess.
