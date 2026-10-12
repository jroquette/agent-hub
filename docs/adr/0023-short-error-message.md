# 0023. A short, redacted error message on failed tool results

- Status: accepted
- Date: 2026-10-12
- Deciders: José Henrique Roquette (D1; design delegated to the lead for AGH-201)
- Partially supersedes: [ADR 0019](0019-metadata-only-events-and-redaction.md), for `tool.result` events only (0019
  is not edited)

## Context and Problem Statement

ADR 0019 keeps metadata only; for a failed tool it keeps `error_line`, the first non-blank line of the error (200
characters). On a real project the owner could not tell what failed or why: most tool errors put the reason after the
first line (a stack, a test name, a compiler message), and an error count with no text says nothing about whether he
must act. How much of a tool's error text may the store keep, and how, without opening the door to bodies?

## Considered Options

1. Keep `error_line` only and show it better (no privacy change; the reason is often not on the first line).
2. Keep a short error message on `tool.result` events with `status: error`: the error text redacted with rule set
   `r1`, whitespace runs collapsed, then capped at 300 characters.
3. Keep the error text whole, redacted (an error can quote a file, a command's output or a secret in any format).
4. Read the error from the transcript on demand, never storing it (the transcript of a hook-only session can be gone,
   and a read per row is too slow for lists).

## Decision Outcome

Option 2. `tool.result` gains one payload key, `error_message`, set only when `status` is `error` and the tool was not
interrupted, by the hook mapper (PostToolUseFailure's `error`) and the transcript mapper (a `tool_result` block with
`is_error`). One function in the collector builds it, `agent_hub.collector.tool_metadata.error_message`: redact the
whole text with `r1` (so a secret spread over lines, a PEM block, is seen whole), collapse every whitespace run to one
space, redact again (joining lines must not reveal a pattern), strip, then cut at 300 characters with `clip`, which
never cuts inside a redaction marker. A non-string or blank error gives no key; an error over the sensor's 64 KiB
arrives as `{"_omitted_bytes": n}` and gets none either. `IngestEvents` redacts and trims it again like every payload
string. Nothing else widens for errors: the place of the error (`where`: the command's first 120 characters, the
pattern, URL, MCP tool, skill or repo-relative path of the paired `tool.call`) is derived on read by the problems fold,
never stored twice. `error_line` stays, unchanged, so events stored before this ADR keep their message.

Re-ingesting an event that was stored before this key existed would be a conflict under ADR 0019's rule. A release that
widens the allow-list declares the keys it adds (`ADDED_KEYS_V2` in `agent_hub.core.events.payload_keys`:
`error_message`, `skill`, `git_branch`, `to`); in core's one append rule (`plan_append`), two events with the same
identity that are equal once those keys are removed from both are duplicates, and the stored row is kept. Any other
difference stays a conflict.

The same release adds three short names under the same rules: `tool.call` keeps the Skill tool's `skill` and
SendMessage's recipient `to` (80 characters each, redacted), and every event of a transcript line that names a
`gitBranch` keeps it as `git_branch` (200 characters, redacted).

Prompts, assistant text, reasoning, successful tool output, file contents and diffs remain never stored.

### Consequences

- Good: each problem says what failed in the tool's own words; the Live and Session screens can tell "needs you" from
  "handled by the agent" with evidence.
- Good: the widening is one key, bounded, property-tested (secrets of every `r1` kind at random offsets, including
  across the 300-character cut, never survive) and covered by the privacy sentinel test.
- Bad: up to 300 characters of tool output per failure are stored; a secret in a format `r1` does not know can be kept.
  The cap and the error-only rule bound the exposure; a rule-set change is a release note, as in ADR 0019.
- Bad: events stored before this release never gain `error_message` (the stored row wins); they show `error_line`.

## More Information

Control-plane clarity spec (AGH-201) D1, L1 to L3, AC-201.6 to AC-201.12; [SPEC](../SPEC.md#data-sources-and-event-model)
"Privacy: metadata only, redacted"; [event-derivations.md](../design/event-derivations.md) "Session" (problem kinds).
