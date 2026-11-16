import { useMemo, type ReactNode } from "react";

import { highlightable, languageOfPath, useHighlightBlocks } from "../../components";
import type { DiffLine } from "./ToolCallCard";

/** A code line of the diff: a sign (`+`, `-`, space) then the code. Hunk headers, file headers
 * and notes such as "... diff truncated" are not. */
const isCode = (line: DiffLine) =>
  (line.kind === "add" && line.text.startsWith("+")) ||
  (line.kind === "del" && line.text.startsWith("-")) ||
  (line.kind === "ctx" && line.text.startsWith(" "));

/** Where a row's code sits in the highlighted blocks of one side: its block, then its line. */
type At = { block: number; line: number } | null;

/** The code of each side of the diff in blocks, one per hunk, and where each row sits in them. */
function splitSides(lines: readonly DiffLine[]) {
  const oldBlocks: string[][] = [];
  const newBlocks: string[][] = [];
  let oldBlock: string[] = [];
  let newBlock: string[] = [];
  // A side's code lines go into its current block; a hunk header closes it, if it has any.
  const place = (blocks: string[][], block: string[], code: string): At => {
    if (block.length === 0) blocks.push(block);
    return { block: blocks.length - 1, line: block.push(code) - 1 };
  };
  const at: { old: At; new: At }[] = [];
  for (const line of lines) {
    if (line.kind === "hunk") {
      if (oldBlock.length > 0) oldBlock = [];
      if (newBlock.length > 0) newBlock = [];
    }
    if (!isCode(line)) {
      at.push({ old: null, new: null });
      continue;
    }
    const code = line.text.slice(1);
    at.push({
      old: line.kind === "add" ? null : place(oldBlocks, oldBlock, code),
      new: line.kind === "del" ? null : place(newBlocks, newBlock, code),
    });
  }
  const join = (blocks: string[][]) => blocks.map((block) => block.join("\n"));
  return { old: join(oldBlocks), new: join(newBlocks), at };
}

/**
 * Each line's code coloured in the file's language, as a pull request shows it: within each hunk,
 * the old side (context and removed lines) and the new side (context and added lines) are each
 * highlighted as one text, so a string or comment that spans lines reads right, then split back
 * into the rows. Hunks are highlighted apart: the lines hidden between two hunks may open or close
 * a string, so carrying one hunk's state into the next would colour the rest of the file wrongly.
 * An entry is null for a row that is not code, and the whole list is null while the highlighter
 * loads, for an unknown language, or for a diff over the highlight bounds: the rows stay plain.
 */
export function useDiffSyntax(
  lines: readonly DiffLine[],
  path: string | undefined,
): (ReactNode[] | null)[] | null {
  const sides = useMemo(() => splitSides(lines), [lines]);
  const language = path ? languageOfPath(path) : "";
  const enabled =
    language !== "" &&
    highlightable(sides.old.join("\n")) &&
    highlightable(sides.new.join("\n")) &&
    sides.at.length > 0;
  const oldBlocks = useHighlightBlocks(sides.old, language, enabled);
  const newBlocks = useHighlightBlocks(sides.new, language, enabled);
  return useMemo(() => {
    if (!oldBlocks || !newBlocks) return null;
    return sides.at.map((row) =>
      row.new
        ? (newBlocks[row.new.block]?.[row.new.line] ?? null)
        : row.old
          ? (oldBlocks[row.old.block]?.[row.old.line] ?? null)
          : null,
    );
  }, [sides, oldBlocks, newBlocks]);
}
