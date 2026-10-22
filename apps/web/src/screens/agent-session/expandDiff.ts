/**
 * A pull request's diff with more of the file around it, as GitHub expands one: the lines between
 * its hunks (and after the last) come from the file as the base has it, since a line the diff
 * leaves out is the same on both sides. The result is a unified diff again, the revealed lines
 * as context and hunks that now touch merged, so its numbers, colours and review comments work
 * as on any other diff.
 */

/** How many lines one press reveals. */
export const EXPAND_STEP = 20;

/** The lines revealed in one gap: after the hunk above it (`top`), before the hunk below it
 * (`bottom`). */
export interface GapReveal {
  top: number;
  bottom: number;
}

/** A gap that still hides lines: which one it is (from 0, the gap before the first hunk; the last
 * is after the last hunk) and how many it hides. `first` and `last` say it has no hunk above or
 * below, so it only grows one way. */
export interface HiddenGap {
  gap: number;
  hidden: number;
  first: boolean;
  last: boolean;
}

export interface ExpandedDiff {
  diff: string;
  /** The gap above each hunk header of `diff`, in order (null: it hides nothing). */
  headers: (HiddenGap | null)[];
  /** The gap after the last hunk, when it hides lines. */
  trailing: HiddenGap | null;
}

interface Hunk {
  oldStart: number;
  newStart: number;
  suffix: string;
  body: string[];
}

const HUNK = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$/;

/** Lines of the old and new file a hunk's body holds. */
function spans(body: readonly string[]): { old: number; new: number } {
  let old = 0;
  let added = 0;
  for (const line of body) {
    if (line.startsWith("-")) old += 1;
    else if (line.startsWith("+")) added += 1;
    else if (line.startsWith(" ")) {
      old += 1;
      added += 1;
    }
  }
  return { old, new: added };
}

/** A hunk's first line in each file; a hunk that holds no line of a side names the line before
 * it (git's `-5,0`), so its first is the next one. */
function starts(hunk: Hunk): { old: number; new: number } {
  const span = spans(hunk.body);
  return {
    old: span.old === 0 ? hunk.oldStart + 1 : hunk.oldStart,
    new: span.new === 0 ? hunk.newStart + 1 : hunk.newStart,
  };
}

function parse(diff: string): { head: string[]; hunks: Hunk[] } | null {
  const head: string[] = [];
  const hunks: Hunk[] = [];
  const text = diff.endsWith("\n") ? diff.slice(0, -1) : diff;
  for (const line of text.split("\n")) {
    const match = HUNK.exec(line);
    if (match) {
      hunks.push({
        oldStart: Number(match[1]),
        newStart: Number(match[3]),
        suffix: match[5] ?? "",
        body: [],
      });
    } else if (hunks.length > 0) hunks[hunks.length - 1]?.body.push(line);
    else head.push(line);
  }
  return hunks.length > 0 ? { head, hunks } : null;
}

function header(hunk: Hunk): string {
  const span = spans(hunk.body);
  const old = span.old === 0 ? hunk.oldStart - 1 : hunk.oldStart;
  const added = span.new === 0 ? hunk.newStart - 1 : hunk.newStart;
  return `@@ -${String(old)},${String(span.old)} +${String(added)},${String(span.new)} @@${hunk.suffix}`;
}

/**
 * `diff` with the lines `reveal` asks for in each gap, read from `base` (the file's lines as the
 * base has them). Null when the diff has no hunk to expand around.
 */
export function expandDiff(
  diff: string,
  base: readonly string[],
  reveal: ReadonlyMap<number, GapReveal>,
): ExpandedDiff | null {
  const parsed = parse(diff);
  if (!parsed) return null;
  const out: Hunk[] = [];
  const headers: (HiddenGap | null)[] = [];
  let oldEnd = 0; // The last old line shown so far.
  parsed.hunks.forEach((hunk, gap) => {
    const start = starts(hunk);
    const size = Math.max(0, start.old - oldEnd - 1);
    const asked = reveal.get(gap) ?? { top: 0, bottom: 0 };
    const top = gap === 0 ? 0 : Math.min(asked.top, size);
    const bottom = Math.min(asked.bottom, size - top);
    const hidden = size - top - bottom;
    const above = out[out.length - 1];
    if (above) {
      for (let n = oldEnd + 1; n <= oldEnd + top; n++) above.body.push(` ${base[n - 1] ?? ""}`);
    }
    const before = Array.from(
      { length: bottom },
      (_, i) => ` ${base[start.old - bottom + i - 1] ?? ""}`,
    );
    const offset = start.new - start.old;
    if (above && hidden === 0) {
      above.body.push(...before, ...hunk.body);
    } else {
      const firstOld = start.old - bottom;
      out.push({
        oldStart: firstOld,
        newStart: firstOld + offset,
        suffix: hunk.suffix,
        body: [...before, ...hunk.body],
      });
      headers.push(hidden > 0 ? { gap, hidden, first: gap === 0, last: false } : null);
    }
    oldEnd = start.old + spans(hunk.body).old - 1;
  });
  const gap = parsed.hunks.length;
  const size = Math.max(0, base.length - oldEnd);
  const top = Math.min(reveal.get(gap)?.top ?? 0, size);
  const last = out[out.length - 1];
  if (last)
    for (let n = oldEnd + 1; n <= oldEnd + top; n++) last.body.push(` ${base[n - 1] ?? ""}`);
  const hidden = size - top;
  return {
    diff: [...parsed.head, ...out.flatMap((hunk) => [header(hunk), ...hunk.body])].join("\n"),
    headers,
    trailing: hidden > 0 ? { gap, hidden, first: false, last: true } : null,
  };
}

/** A file's text as lines, its final newline not counted as a line of its own. */
export function fileLines(text: string): string[] {
  const body = text.endsWith("\n") ? text.slice(0, -1) : text;
  return body === "" ? [] : body.split("\n");
}

/** `reveal` after one press on `gap`: up (lines above the hunk below), down (lines below the
 * hunk above), or all of it. */
export function revealMore(
  reveal: ReadonlyMap<number, GapReveal>,
  target: HiddenGap,
  direction: "up" | "down" | "all",
): Map<number, GapReveal> {
  const next = new Map(reveal);
  const now = next.get(target.gap) ?? { top: 0, bottom: 0 };
  if (direction === "all") {
    // The rest goes to the side that can always take it: below the hunk above, else above the
    // hunk below.
    next.set(
      target.gap,
      target.first
        ? { ...now, bottom: now.bottom + target.hidden }
        : { ...now, top: now.top + target.hidden },
    );
  } else if (direction === "down") {
    next.set(target.gap, { ...now, top: now.top + EXPAND_STEP });
  } else {
    next.set(target.gap, { ...now, bottom: now.bottom + EXPAND_STEP });
  }
  return next;
}
