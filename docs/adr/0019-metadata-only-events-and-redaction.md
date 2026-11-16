# 0019. Metadata-only event payloads and redaction before append

- Status: accepted
- Date: 2026-10-11
- Deciders: José Henrique Roquette (delegated to the lead for AGH-200)

## Context and Problem Statement

Real Claude Code sessions carry prompts, model output, tool output, file contents and secrets. The SPEC requires
redaction before any write; no redaction exists. What does the store keep, and where does redaction run?

## Considered Options

1. Store bodies, redacted, with a retention policy (blob store).
2. Store metadata only (types, ids, sizes, counts, a few short allowed texts), redacted in core before append.
3. Redact in each adapter.

## Decision Outcome

Option 2. Each event type keeps only the payload keys of one table in core, `agent_hub.core.events.payload_keys`
(the spec's "Payload kept", D11, plus `run`, `step`, `attempt` and `agent_id` on any type). The collector's mappers
build payloads from it, and `IngestEvents` trims every payload to it after redaction, for every entry point, so a
canonical JSON Lines file for `hub collect` cannot store a body under another key either: such keys are dropped,
never rejected; allowed short texts (Bash
command 500 chars, patterns 200, first error line 200, subagent type/description 80, slash-command name, learning title
120, WebFetch scheme+host+path) are redacted, then truncated. `IngestEvents` (core) applies
`agent_hub.core.redaction.redact_value` to every string of `payload` (recursively) and to `repo`, `agent`, `workflow`,
`step` for every entry point, before the trim and the append. Rule set `r1`: github token, linear key, anthropic key, openai key,
aws access key, aws secret, bearer token, private key (PEM block), url credentials, secret assignments; the whole
value is replaced by `[redacted: <kind>]`; idempotent. A rule change is a release note; re-ingesting an event whose
redaction or trim changed is a conflict, as today (so re-collecting a Phase 0 JSONL event that held keys outside the
table conflicts with its stored copy).

### Consequences

- Good: a leak needs both a regex miss and an allowed field; the transcript stays in Claude Code's folder.
- Bad: no message text in the UI ("Content not stored"); regex false negatives and positives remain (Hypothesis tests
  bound them).

## More Information

Control-plane feature spec (AGH-200) D10, D11, AC-200.17 to 21; [SPEC](../SPEC.md#data-sources-and-event-model)
"Privacy: metadata only, redacted".
