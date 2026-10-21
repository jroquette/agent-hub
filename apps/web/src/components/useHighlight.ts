/**
 * The lazy syntax highlighter (ADR 0034), shared by Markdown code blocks and tool call cards: the
 * `highlight` chunk loads once, the first time a text can be highlighted, and a text over the
 * bounds, or shown before the chunk loads (or after it failed), stays plain.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

/** A longer text is shown plain, never highlighted (ADR 0034). */
export const MAX_HIGHLIGHT_LINES = 2000;
export const MAX_HIGHLIGHT_BYTES = 64 * 1024;

type Highlighter = typeof import("./highlight");
let highlighter: Highlighter | null = null;
let loading: Promise<Highlighter | null> | null = null;

/** The lazy chunk, loaded once; a failed load leaves every text plain until the page reloads. */
function loadHighlighter(): Promise<Highlighter | null> {
  loading ??= import("./highlight").then(
    (loaded) => (highlighter = loaded),
    () => null,
  );
  return loading;
}

/** Within the bounds a text is highlighted at (lines, then UTF-8 bytes). */
export function highlightable(text: string): boolean {
  if (text.length > MAX_HIGHLIGHT_BYTES) return false;
  let lines = 1;
  for (let at = text.indexOf("\n"); at !== -1; at = text.indexOf("\n", at + 1)) {
    if (++lines > MAX_HIGHLIGHT_LINES) return false;
  }
  return new TextEncoder().encode(text).length <= MAX_HIGHLIGHT_BYTES;
}

/** The highlighter once its chunk has loaded and `enabled` holds (it starts loading then). */
function useHighlighter(enabled: boolean): Highlighter | null {
  const [module, setModule] = useState(highlighter);
  useEffect(() => {
    if (!enabled || module) return;
    let live = true;
    void loadHighlighter().then((loaded) => {
      if (live && loaded) setModule(loaded);
    });
    return () => {
      live = false;
    };
  }, [enabled, module]);
  return enabled ? module : null;
}

/** `text` as highlighted nodes once the chunk has loaded and `enabled` holds; null means plain. */
export function useHighlight(text: string, lang: string, enabled: boolean): ReactNode[] | null {
  const module = useHighlighter(enabled);
  return useMemo(() => (module ? module.highlight(text, lang) : null), [module, text, lang]);
}

/** `text` as highlighted nodes, one list per line; null means plain. */
export function useHighlightLines(
  text: string,
  lang: string,
  enabled: boolean,
): ReactNode[][] | null {
  const module = useHighlighter(enabled);
  return useMemo(() => (module ? module.highlightLines(text, lang) : null), [module, text, lang]);
}

/** File extensions whose name is not already a grammar name or alias of the highlighter. */
const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  mjs: "javascript",
  cjs: "javascript",
  mts: "typescript",
  cts: "typescript",
  pyi: "python",
  htm: "xml",
  vue: "xml",
  mdx: "markdown",
  jsonc: "json",
  bash: "bash",
};

/** The language to highlight a file in, from its path: its extension (`ts`, `py`, `yml`… are
 * grammar aliases), or a few extensions the grammars do not alias. The highlighter
 * shows an unknown one plain. */
export function languageOfPath(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1).toLowerCase();
  const dot = name.lastIndexOf(".");
  if (dot <= 0) return "";
  const extension = name.slice(dot + 1);
  return LANGUAGE_BY_EXTENSION[extension] ?? extension;
}
