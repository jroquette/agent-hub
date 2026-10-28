import type { MatcherFunction } from "@testing-library/react";

/** A code element whose whole text is `text`, even when syntax highlighting splits it into
 * coloured spans (`HighlightedCode`). */
export function codeText(text: string): MatcherFunction {
  return (_content, element) => element?.tagName === "CODE" && element.textContent === text;
}
