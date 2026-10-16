# 0034. Syntax highlighting of code blocks with lowlight

- Status: accepted. Accepted 2026-10-14 by the owner (AGH-234 plan approval, P-c).
- Date: 2026-10-14
- Deciders: José Henrique Roquette
- Supersedes: none. Completes the code-block part of
  [ADR 0033](0033-sessions-and-chat-interaction-model.md), which left highlighting to its own decision.

## Context and Problem Statement

Agent output is full of code: diffs, commands, snippets. Our renderer (`apps/web/src/components/Markdown.tsx`) is
dependency-free, builds React elements only and keeps raw HTML inert; after ADR 0033 its code blocks have a language
label and Copy, but no colours. `apps/web` has no highlighting library. [ADR 0020](0020-web-stack-and-committed-build.md)
asks that every runtime dependency be justified, and the app loads nothing from another host. Agent output is
untrusted, so the highlighter must not open an HTML injection path. Do we add highlighting, and with what?

## Considered Options

1. **lowlight 3** (MIT): highlight.js grammars (highlight.js 11 is BSD-3-Clause), returns a HAST tree; we map it to
   React elements with a small walker of our own (element and text nodes, `className` only). About a dozen
   registered languages, in a lazy chunk.
2. highlight.js core directly: returns an HTML string, which needs `dangerouslySetInnerHTML` (escaped by
   highlight.js, but it reopens the door our renderer keeps shut).
3. Shiki: best fidelity, but a WASM or large JS engine and async grammars; heavier than this need.
4. Prism or react-syntax-highlighter: a lighter core, but a second grammar ecosystem and a wrapper that ships many
   languages by default.
5. No highlighting (status quo).

## Decision Outcome

Chosen: option 1, lowlight with our own HAST-to-React walker (`apps/web/src/components/highlight.ts`).

- **Lazy.** The chunk is loaded with a dynamic `import()` the first time a code block can be highlighted; pages
  without one never load it. A failed load leaves every block plain.
- **Languages.** The grammars of TypeScript (`ts`, `tsx`), JavaScript (`js`, `jsx`), Python, Bash (`sh`, `zsh`),
  shell sessions (`console`), JSON, YAML, diff (`patch`), Go, Rust, SQL, CSS, HTML/XML (`html`, `svg`) and Markdown,
  with their highlight.js aliases. An unknown or missing language renders plain; no auto-detection.
- **Completed blocks only.** A block whose fence is still open while the text streams stays plain; it is highlighted
  once its fence closes or the message ends. Blocks over 2,000 lines or 64 KiB (UTF-8 bytes) stay plain.
- **No HTML path.** No `innerHTML` or `dangerouslySetInnerHTML`: the walker emits `<span className>` and text only,
  drops every other property, and keeps only the text of any other element. Tests feed `<script>` and
  `<img onerror>` in a code block and a hostile HAST tree, and check they render as text.
- **Colours from design tokens** (`syntax-keyword`, `syntax-title`, `syntax-comment` added next to `syntax-key`,
  `syntax-string`, `syntax-number`, and `diff-add`, `diff-del`), light and dark, each at least 4.5:1 on `code-bg`
  (a test checks it); no highlight.js theme file.
- **Bundle.** The lazy chunk stays under 40 kB gzipped (measured in the PR); the main chunk grows by at most 2 kB.
- **Licences.** lowlight is MIT and highlight.js BSD-3-Clause, both compatible with our Apache-2.0 distribution;
  `NOTICE` names highlight.js and lowlight with their copyright lines, since the committed build bundles them.

### Consequences

- Good: code in agent replies, plans and notes is easier to read; no HTML injection path.
- Bad: one runtime dependency (with highlight.js under it) to keep current through Renovate or `/upgrade`.
- Bad: a small lazy chunk to keep in `web_dist`.

## More Information

- Open WebUI uses highlight.js with one theme and highlights a growing block again on every frame; we take the idea
  of highlighting and leave the per-frame cost (design study only, as ADR 0033 records).
- Related: [ADR 0020](0020-web-stack-and-committed-build.md) (web stack, committed build),
  [ADR 0033](0033-sessions-and-chat-interaction-model.md) (chat interaction model). Tracker: AGH-252 (AC-234.31).
