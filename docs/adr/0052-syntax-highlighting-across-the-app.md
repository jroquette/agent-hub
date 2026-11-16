# 0052. Syntax highlighting of every code and file the app shows

- Status: proposed
- Date: 2026-10-28
- Deciders: José Henrique Roquette (the owner validated the colouring in the playground, snapshot `3df1fa457` on
  v0.26.0, for AGH-596)
- Widens: [ADR 0034](0034-syntax-highlighting-in-the-chat.md), from the chat's Markdown code blocks to every code and
  file the app shows. 0034 is not edited: its library, bounds, HTML rule, tokens and licences stay as decided.

## Context and Problem Statement

ADR 0034 colours the completed code blocks of the chat's Markdown with lowlight, from a lazy chunk, through our own
HAST-to-React walker. The rest of the app still showed code plain: the scenario builder's generated YAML, the Migrate
preview, an action's script and file, every command in a `CodeBlock`, a hook's command, a skill's raw text and
bundled files, and a Studio draft's files. Some screens had started to call the highlighter on their own, each in its
own way. The owner wants code to read the same everywhere. Do we colour all of it, and how, without a second
highlighter or a new dependency?

## Considered Options

1. **One component over ADR 0034's highlighter.** `HighlightedCode` (`apps/web/src/components/HighlightedCode.tsx`)
   takes a text and a language and renders a `code` element, coloured once the lazy chunk has loaded. A file's
   language comes from its extension (`languageOfPath`), a command's is shell. Every place that shows code uses it.
2. **Each screen calls the highlighter itself.** It works, but every screen repeats the bounds, the language rule and
   the plain fallback, and they drift apart.
3. **Keep the scope of ADR 0034.** Code outside the chat stays plain, so a script reads coloured in a chat reply and
   plain on the action's own page.

## Decision Outcome

Chosen: option 1.

- **One component.** `HighlightedCode` is the one way the app shows code outside the chat's Markdown (whose code
  blocks keep ADR 0034's own path, and the diffs their line by line one). It uses the same lazy hook (`useHighlight`)
  and the same chunk, so a page with no code still loads no highlighter.
- **Languages by extension.** A file's language is its extension (`py`, `yml`, `ts`… are aliases the grammars hold),
  with a short map for the few they do not alias. A file with no extension, or one in a language ADR 0034 does not
  register, stays plain; nothing is guessed. A badge may name the language in words (`languageName`: Python, Bash,
  YAML…).
- **Where.** The scenario builder's YAML view and the Migrate preview as YAML; an action's files in the action panel
  and the open step by their language; every `CodeBlock` with the `$` prompt as shell (one with no prompt stays
  plain, unless a language is given); a hook's command and the agent session's Bash commands as shell; a skill's Raw
  view as Markdown; a skill's bundled files and a Studio draft's files by their path.
- **Kept from ADR 0034.** No new dependency and no new grammar; the bounds (2,000 lines, 64 KiB) and a failed load
  leave the text plain; no `innerHTML`, the walker emits spans and text only; the colours are the `syntax-*` design
  tokens in both themes. The text itself never changes: a test that reads a coloured command finds it by its whole
  text.

### Consequences

- Good: code reads the same on every screen, and a new screen gets colours by using one component.
- Good: no new dependency, licence or chunk; the lazy chunk loads on more pages, but only where code shows.
- Bad: a screen that shows code and does not use `HighlightedCode` is not caught by a check; review has to catch it.
- Bad: colouring by extension can be wrong for a file whose extension lies; it then reads with the wrong colours,
  never with other text.

## More Information

AGH-596, part 5 (snapshot commit `3df1fa457`). The component is `apps/web/src/components/HighlightedCode.tsx`, the
language rule `languageOfPath` in `apps/web/src/components/useHighlight.ts`, the grammars and walker in
`apps/web/src/components/highlight.ts` (ADR 0034). The screens: [spec 23](../design/control-plane/specs/23-scenarios.md)
(the builder, its YAML view, Migrate, the action files), [spec 19](../design/control-plane/specs/19-brain-and-skills.md)
(§ Code in colour) and the design system's departures ([README](../design/control-plane/README.md)).
