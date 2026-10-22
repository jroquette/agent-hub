import { useMemo, type ReactNode } from "react";

import { highlightable, languageOfPath, useHighlightLines } from "../../components";
import type { DiffLine } from "./ToolCallCard";

/** A code line of the diff: a sign (`+`, `-`, space) then the code. Hunk headers, file headers
 * and notes such as "... diff truncated" are not. */
const isCode = (line: DiffLine) =>
  (line.kind === "add" && line.text.startsWith("+")) ||
  (line.kind === "del" && line.text.startsWith("-")) ||
  (line.kind === "ctx" && line.text.startsWith(" "));

/**
 * Each line's code coloured in the file's language, as a pull request shows it: the old side
 * (context and removed lines) and the new side (context and added lines) are each highlighted as
 * one text, so a string or comment that spans lines reads right, then split back into the rows.
 * An entry is null for a row that is not code, and the whole list is null while the highlighter
 * loads, for an unknown language, or for a diff over the highlight bounds: the rows stay plain.
 */
export function useDiffSyntax(
  lines: readonly DiffLine[],
  path: string | undefined,
): (ReactNode[] | null)[] | null {
  const sides = useMemo(() => {
    const oldSide: string[] = [];
    const newSide: string[] = [];
    // Each row's line in the old and new side's text, -1 when it is not on that side.
    const at = lines.map((line) => {
      if (!isCode(line)) return { old: -1, new: -1 };
      const code = line.text.slice(1);
      const old = line.kind === "add" ? -1 : oldSide.push(code) - 1;
      const next = line.kind === "del" ? -1 : newSide.push(code) - 1;
      return { old, new: next };
    });
    return { old: oldSide.join("\n"), new: newSide.join("\n"), at };
  }, [lines]);
  const language = path ? languageOfPath(path) : "";
  const enabled =
    language !== "" && highlightable(sides.old) && highlightable(sides.new) && sides.at.length > 0;
  const oldLines = useHighlightLines(sides.old, language, enabled);
  const newLines = useHighlightLines(sides.new, language, enabled);
  return useMemo(() => {
    if (!oldLines || !newLines) return null;
    return sides.at.map((row) =>
      row.new >= 0
        ? (newLines[row.new] ?? null)
        : row.old >= 0
          ? (oldLines[row.old] ?? null)
          : null,
    );
  }, [sides, oldLines, newLines]);
}
