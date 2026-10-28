import { highlightable, useHighlight } from "./useHighlight";

/* Code shown coloured by its language (ADR 0034's lazy highlighter, the `hljs` scopes on design
 * tokens in Markdown.css): a file, a generated YAML, a command. A text over the highlighter's
 * bounds, a language it does not hold, or one shown before the chunk loads stays plain. Every
 * place that shows code uses this, so code reads the same everywhere. */

const LANGUAGES: Readonly<Record<string, string>> = {
  py: "python",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "typescript",
  jsx: "javascript",
  sql: "sql",
  go: "go",
  rs: "rust",
  md: "markdown",
  css: "css",
  html: "xml",
  xml: "xml",
};

const LANGUAGE_WORDS: Readonly<Record<string, string>> = {
  python: "Python",
  bash: "Bash",
  yaml: "YAML",
  json: "JSON",
  javascript: "JavaScript",
  typescript: "TypeScript",
  sql: "SQL",
  go: "Go",
  rust: "Rust",
  markdown: "Markdown",
  css: "CSS",
  xml: "HTML",
};

/** The language of a file by its extension, as the highlighter names it ("" when none fits). */
export function languageOf(path: string): string {
  const extension = /\.([a-z0-9]+)$/i.exec(path)?.[1]?.toLowerCase() ?? "";
  return LANGUAGES[extension] ?? "";
}

/** A language's name in words ("Python"), or "" for none. */
export function languageName(language: string): string {
  return language === "" ? "" : (LANGUAGE_WORDS[language] ?? language);
}

/** `text` in a `code` element, coloured as `lang` once the highlighter has loaded. */
export function HighlightedCode({ text, lang }: { text: string; lang: string }) {
  const nodes = useHighlight(text, lang, lang !== "" && highlightable(text));
  return <code className={nodes ? "hljs" : undefined}>{nodes ?? text}</code>;
}
