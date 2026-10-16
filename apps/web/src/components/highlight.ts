/**
 * Syntax highlighting of a completed code block (AC-234.31, ADR 0034), loaded as a lazy chunk by
 * `Markdown.tsx` the first time a block can be highlighted.
 *
 * lowlight (highlight.js grammars) returns a HAST tree; `toReact` turns it into React nodes itself:
 * a `span` with its class names and text, nothing else. No HTML string, no `innerHTML`, no other
 * element or attribute, so agent output stays inert whatever the tree holds.
 *
 * `highlight.js` and `hast` are not in package.json on purpose: lowlight depends on both (it pins
 * highlight.js ~11.11 and re-exports these grammars in its `common` set) and is our only declared
 * dependency (ADR 0034). We import the 14 grammars one by one so the chunk holds no other; declaring
 * highlight.js ourselves could install a second copy that drifts from lowlight's. A lowlight bump is
 * checked against these imports (typecheck, the highlight tests and the build).
 */
import type { ElementContent, RootContent } from "hast";
import bash from "highlight.js/lib/languages/bash";
import css from "highlight.js/lib/languages/css";
import diff from "highlight.js/lib/languages/diff";
import go from "highlight.js/lib/languages/go";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import markdown from "highlight.js/lib/languages/markdown";
import python from "highlight.js/lib/languages/python";
import rust from "highlight.js/lib/languages/rust";
import shell from "highlight.js/lib/languages/shell";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { createLowlight } from "lowlight";
import { Fragment, createElement, type ReactNode } from "react";

// Aliases come with each grammar: ts/tsx, js/jsx, py, sh/zsh, console, yml, patch, rs, html/svg, md.
const lowlight = createLowlight({
  bash,
  css,
  diff,
  go,
  javascript,
  json,
  markdown,
  python,
  rust,
  shell,
  sql,
  typescript,
  xml,
  yaml,
});

/** A class name the walker keeps: one plain word (highlight.js emits `hljs-keyword`, `function_`). */
const CLASS_NAME = /^[A-Za-z_][\w-]{0,63}$/;

function classOf(names: unknown): string | undefined {
  if (!Array.isArray(names)) return undefined;
  const kept = names.filter(
    (name): name is string => typeof name === "string" && CLASS_NAME.test(name),
  );
  return kept.length > 0 ? kept.join(" ") : undefined;
}

/** HAST to React: text, and `span` elements with their class only; any other element keeps only
 * its text, and comments, doctypes and every other property are dropped. */
export function toReact(nodes: readonly (RootContent | ElementContent)[]): ReactNode[] {
  return nodes.map((node, key) => {
    if (node.type === "text") return node.value;
    if (node.type !== "element") return null;
    const children = toReact(node.children);
    if (node.tagName !== "span") return createElement(Fragment, { key }, ...children);
    return createElement(
      "span",
      { key, className: classOf(node.properties.className) },
      ...children,
    );
  });
}

/** The code as highlighted React nodes, or null when the language is not one of ours. */
export function highlight(code: string, language: string): ReactNode[] | null {
  const name = language.toLowerCase();
  if (!lowlight.registered(name)) return null;
  return toReact(lowlight.highlight(name, code).children);
}
