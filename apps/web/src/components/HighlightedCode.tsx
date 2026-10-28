import { highlightable, useHighlight } from "./useHighlight";

/* Code shown coloured by its language (ADR 0034's lazy highlighter, the `hljs` scopes on design
 * tokens in Markdown.css): a file, a generated YAML, a command. A text over the highlighter's
 * bounds, a language it does not hold, or one shown before the chunk loads stays plain. Every
 * place that shows code uses this, so code reads the same everywhere. */

/* A language's name in words for its badge, by its highlighter name or any alias a file's
 * extension gives it (`languageOfPath` keeps `py`, `yml`, `tsx`…, which the grammars alias). */
const LANGUAGE_WORDS: Readonly<Record<string, string>> = {
  python: "Python",
  py: "Python",
  bash: "Bash",
  sh: "Bash",
  zsh: "Bash",
  yaml: "YAML",
  yml: "YAML",
  json: "JSON",
  javascript: "JavaScript",
  js: "JavaScript",
  jsx: "JavaScript",
  typescript: "TypeScript",
  ts: "TypeScript",
  tsx: "TypeScript",
  sql: "SQL",
  go: "Go",
  rust: "Rust",
  rs: "Rust",
  markdown: "Markdown",
  md: "Markdown",
  css: "CSS",
  xml: "HTML",
  html: "HTML",
};

/** A language's name in words ("Python"), or "" for none or one the app does not colour. */
export function languageName(language: string): string {
  return LANGUAGE_WORDS[language.toLowerCase()] ?? "";
}

/** `text` in a `code` element, coloured as `lang` once the highlighter has loaded. */
export function HighlightedCode({ text, lang }: { text: string; lang: string }) {
  const nodes = useHighlight(text, lang, lang !== "" && highlightable(text));
  return <code className={nodes ? "hljs" : undefined}>{nodes ?? text}</code>;
}
