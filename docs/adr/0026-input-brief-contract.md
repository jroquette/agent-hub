# 0026. The input brief as a contract for `hub run` and `/feature`

- Status: proposed
- Date: 2026-10-13
- Deciders: José Henrique Roquette (the source, the sections, hard refusal and core as the single source; the
  remaining details approved with the AGH-138 spec on 2026-10-13)

## Context and Problem Statement

`hub run` takes any tracker issue to a live implementing session that may spend up to `--budget` USD unattended. An
issue whose description is empty or says only "fix X" spends that session on a guess, and the reviewer of the PR it
opens has no acceptance criteria to check it against. The generated `/feature` skill starts at "Size it" from a bare
idea, so the problem, the motivation, the invariants and the acceptance criteria surface only later, at the spec step,
which spikes skip. There is no single definition of what a ready issue states, so the CLI and the skill cannot agree on
one. What must an issue state before work starts, where is that defined, and what happens when it does not?

## Considered Options

1. No contract: keep `hub run` reading the description only for the prompt, and leave readiness to `/triage` and the
   `agent-ready` label.
2. A brief file or a `--brief` flag next to the issue (a second source that can disagree with the tracker).
3. Six fixed Markdown headings in the tracker issue's description, defined once in core, checked by a pure function;
   `hub run` refuses an incomplete brief with no bypass, and `/feature` drafts the missing sections first.
4. As 3, but with the sections configurable per project in `hub.json`.
5. As 3, but a warning, or a refusal with a bypass flag.

## Decision Outcome

Option 3.

- **Source:** the tracker issue's `Issue.description`, untrusted Markdown (`""` when the issue has none).
- **Sections**, canonical order: `Problem`, `Why`, `Why now`, `Outcome`, `Invariants`, `Acceptance criteria`. A
  spike's acceptance criteria may be the questions it answers.
- **Matching:** ATX headings only (`#` to `######`, then a space or tab), case-insensitive, surrounding whitespace and
  one trailing `:` ignored; no aliases. A heading inside a fenced code block (backticks or tildes, closed by a fence
  of the same character at least as long) or indented four or more spaces is not a heading; setext headings do not
  count.
- **Body:** a section's body runs to the next heading of the same or a higher level, so its subheadings belong to it.
  A section is missing when it has no heading, or when every occurrence's body is empty, whitespace only, or only one
  of the placeholders `TBD`, `N/A`, `-`, `TODO` (case-insensitive, the whole body after stripping). Section order and
  extra sections are free.
- **Single source:** `agent_hub.core.runner.brief` holds `BRIEF_SECTIONS`, `PLACEHOLDERS` and
  `check_brief(markdown) -> tuple[str, ...]` (the missing names, in canonical order). It imports only the standard
  library, does no I/O and runs in time linear in its input. The CLI and the generator import it from core; the
  generator renders `/feature`'s step 0 checklist from the two constants, so no template repeats the names.
- **`hub run`:** right after its one issue read, dry and live, `--from verify` included, and before any worktree,
  session, tracker write, push or PR, an incomplete brief exits 1 with one line,
  `hub run: <ISSUE> brief is missing: <Name>, <Name> (add these headings to the issue description)`, where `<ISSUE>`
  is the validated argument and the names are the canonical constants. A live run also records `failed` at stage
  `PICKED` with the same text minus `hub run: ` as its reason, as a failed read does. Neither the line nor the record
  holds any issue text. Nothing is written to the tracker.
- **`/feature`:** a step 0 "Brief" for every size, spikes included: given an issue id it checks the description;
  given only an idea, or with sections missing, it drafts each missing section with the user, one question at a time,
  writes them into the tracker issue (creating it if there is none; appending only the missing sections to an
  existing one, after showing the change), then sizes the work.
- No `hub.json` key, no schema change, no bypass flag ([ADR 0010](0010-hub-json-config-contract.md) is unchanged).

### Consequences

- Good: an unattended run never spends a session on an issue that does not state its outcome and checks; the PR's
  reviewer reads the criteria in the issue.
- Good: one definition, in core, read by the CLI and by the rendered skill; changing the sections is one edit plus
  regenerated goldens, and the error names only constants, so it is short and leaks no issue text.
- Good: the check is pure and offline, so a refusal is deterministic and costs one tracker read.
- Bad: every existing ready issue without the six headings is refused by `hub run` once a hub moves to the release
  carrying this; the owner fills them in (the error names what is missing).
- Bad: strict matching refuses near misses (`## Expected outcome`, `## Why now?`, `## AC`); the skill names the exact
  headings. With `tracker.transport: "mcp"` a model copies the description and could drop a heading: a false refusal
  is visible and names the section.
- Bad: the check validates presence, not quality; a one-word section passes.

## More Information

Input brief spec (AGH-138) D1 to D10 and AC-138.1 to AC-138.21; [SPEC](../SPEC.md) (`hub run`);
[ADR 0008](0008-cli-as-composition-root.md) and [ADR 0002](0002-lean-hexagonal-architecture.md) (core depends on
nothing internal); [ADR 0009](0009-hub-sync-by-file-ownership.md) and [ADR 0011](0011-templates-as-package-data.md)
(the managed `feature/SKILL.md` reaches hubs through `hub sync`). The one-line, bounded error follows the spirit of
[ADR 0023](0023-short-error-message.md), whose own scope is `tool.result` events, not CLI errors.
