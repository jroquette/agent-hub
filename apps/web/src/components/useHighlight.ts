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

/** `text` as highlighted nodes once the chunk has loaded and `enabled` holds; null means plain. */
export function useHighlight(text: string, lang: string, enabled: boolean): ReactNode[] | null {
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
  return useMemo(
    () => (enabled && module ? module.highlight(text, lang) : null),
    [enabled, module, text, lang],
  );
}
