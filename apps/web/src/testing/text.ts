import type { MatcherFunction } from "@testing-library/react";

/** A code element whose whole text is `text`, even when syntax highlighting splits it into
 * coloured spans (`HighlightedCode`). */
export function codeText(text: string): MatcherFunction {
  return (_content, element) => element?.tagName === "CODE" && element.textContent === text;
}

/** The innermost element whose text, its children's included, reads `text` (runs of whitespace
 * read as one space), however inline markup splits it. */
export function wholeText(text: string): MatcherFunction {
  const read = (element: Element) => element.textContent.replace(/\s+/g, " ").trim();
  return (_content, element) =>
    element !== null &&
    read(element) === text &&
    Array.from(element.children).every((child) => read(child) !== text);
}
