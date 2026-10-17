/**
 * A file's net diff: what all of the session's changes to it add up to, as one unified diff,
 * so the review reads the end result instead of each edit in turn.
 *
 * A file the session wrote whole (Write first) is fully known: its text is replayed (Write sets
 * it, Edit and MultiEdit replace in it) and the net diff is that text, every line added. Any other
 * file is known only through the hunks of its changes: they are laid on top of each other, by the
 * file's line numbers when the changes carry them, else by finding their lines. A line added and
 * later removed cancels out; a line removed stays removed. When the changes cannot be laid
 * together with certainty (a hunk whose lines are not where it says, a truncated diff), there is
 * no net diff (null) and the review shows each change instead.
 */

/** One change to the file, as the net diff needs it. */
export interface NetInput {
  /** The tool that made it (Write, Edit, MultiEdit, NotebookEdit). */
  name: string;
  input: Readonly<Record<string, unknown>>;
  diff: string;
  /** The diff carries the file's real line numbers. */
  numbered: boolean;
}

export interface NetDiff {
  diff: string;
  /** The net diff carries the file's real line numbers. */
  numbered: boolean;
  added: number;
  removed: number;
}

type Kind = "same" | "add" | "del";
interface Row {
  text: string;
  kind: Kind;
}
interface Chunk {
  /** The original file's line its first row stands at (for a chunk of additions only: the line
   * they go before); null for a chunk found by its lines, at no known place. */
  start: number | null;
  rows: Row[];
}
interface Hunk {
  oldStart: number;
  oldLines: number;
  lines: string[];
}

/** Context lines kept around each change. */
const CONTEXT = 3;
const HUNK = /^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@/;

const str = (input: Readonly<Record<string, unknown>>, key: string): string | null => {
  const value = input[key];
  return typeof value === "string" ? value : null;
};

const splitLines = (text: string): string[] => {
  if (text === "") return [];
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
};

/** The hunks of a unified diff; null when it holds anything else (a truncated or omitted diff). */
function parseHunks(diff: string): Hunk[] | null {
  const hunks: Hunk[] = [];
  let current: Hunk | null = null;
  const text = diff.endsWith("\n") ? diff.slice(0, -1) : diff;
  for (const line of text.split("\n")) {
    const head = HUNK.exec(line);
    if (head) {
      current = {
        oldStart: Number(head[1]),
        oldLines: head[2] === undefined ? 1 : Number(head[2]),
        lines: [],
      };
      hunks.push(current);
      continue;
    }
    if (current === null) {
      if (line.startsWith("---") || line.startsWith("+++")) continue;
      return null;
    }
    if (line.startsWith("\\")) continue; // "\ No newline at end of file"
    const sign = line[0];
    if (sign === " " || sign === "-" || sign === "+") current.lines.push(line);
    else if (line === "") current.lines.push(" ");
    else return null;
  }
  return hunks;
}

const current = (rows: readonly Row[]) => rows.filter((row) => row.kind !== "del");
const origLen = (rows: readonly Row[]) => rows.filter((row) => row.kind !== "add").length;
const delta = (rows: readonly Row[]) => current(rows).length - origLen(rows);

/**
 * `lines` (a hunk's) laid on `rows`, whose current lines start at `lo`, the hunk's first old line
 * at `at`: a kept line stays, a removed one is struck (or dropped, if it was added), an added one
 * goes in. Null when a line is not what the hunk says.
 */
function applyRows(rows: readonly Row[], lo: number, at: number, lines: readonly string[]) {
  const out: Row[] = [];
  let i = 0;
  let cur = lo;
  const next = (): Row | undefined => {
    for (let row = rows[i]; row?.kind === "del"; row = rows[++i]) out.push(row);
    return rows[i];
  };
  while (cur < at) {
    const row = next();
    if (!row) return null;
    out.push(row);
    i++;
    cur++;
  }
  for (const line of lines) {
    const sign = line[0];
    const text = line.slice(1);
    if (sign === "+") {
      out.push({ text, kind: "add" });
      continue;
    }
    const row = next();
    if (row?.text !== text) return null;
    i++;
    cur++;
    if (sign === " ") out.push(row);
    else if (row.kind === "same") out.push({ text, kind: "del" });
  }
  out.push(...rows.slice(i));
  return out;
}

/** The hunk laid by the file's line numbers; false when it does not fit. */
function placeNumbered(chunks: Chunk[], hunk: Hunk): boolean {
  const before = hunk.lines.filter((line) => !line.startsWith("+")).map((line) => line.slice(1));
  const from = hunk.oldLines === 0 ? hunk.oldStart + 1 : hunk.oldStart;
  const to = from + before.length;
  chunks.sort((a, b) => (a.start ?? 0) - (b.start ?? 0));
  let shift = 0;
  let shiftBefore = 0;
  const involved: { chunk: Chunk; at: number }[] = [];
  for (const chunk of chunks) {
    const at = (chunk.start ?? 0) + shift;
    const length = current(chunk.rows).length;
    if (at + length < from) shiftBefore += delta(chunk.rows);
    else if (at <= to) involved.push({ chunk, at });
    shift += delta(chunk.rows);
  }
  const lo = Math.min(from, involved[0]?.at ?? from);
  const merged: Row[] = [];
  let pos = lo;
  const fill = (until: number) => {
    for (; pos < until; pos++) {
      const text = before[pos - from];
      if (text === undefined) return false;
      merged.push({ text, kind: "same" });
    }
    return true;
  };
  for (const { chunk, at } of involved) {
    if (!fill(at)) return false;
    merged.push(...chunk.rows);
    pos = at + current(chunk.rows).length;
  }
  if (!fill(to)) return false;
  const rows = applyRows(merged, lo, from, hunk.lines);
  if (!rows) return false;
  const kept = chunks.filter((chunk) => !involved.some((one) => one.chunk === chunk));
  chunks.splice(0, chunks.length, ...kept, { start: lo - shiftBefore, rows });
  return true;
}

/** The hunk laid where its lines are; a new chunk when they are nowhere; false when ambiguous. */
function placeByLines(chunks: Chunk[], hunk: Hunk): boolean {
  const before = hunk.lines.filter((line) => !line.startsWith("+")).map((line) => line.slice(1));
  if (before.length === 0) return false;
  const found: { chunk: Chunk; at: number }[] = [];
  for (const chunk of chunks) {
    const lines = current(chunk.rows).map((row) => row.text);
    for (let at = 0; at + before.length <= lines.length; at++) {
      if (before.every((text, k) => lines[at + k] === text)) found.push({ chunk, at });
    }
  }
  if (found.length > 1) return false;
  const [hit] = found;
  if (!hit) {
    chunks.push({
      start: null,
      rows: hunk.lines.map((line) => ({
        text: line.slice(1),
        kind: line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : "same",
      })),
    });
    return true;
  }
  const rows = applyRows(hit.chunk.rows, 0, hit.at, hunk.lines);
  if (!rows) return false;
  hit.chunk.rows = rows;
  return true;
}

/** The text of a file written whole and then edited; null when an edit does not apply. */
function replay(changes: readonly NetInput[]): string | null {
  let text = "";
  for (const change of changes) {
    if (change.name === "Write") {
      text = str(change.input, "content") ?? "";
      continue;
    }
    const edits =
      change.name === "Edit"
        ? [change.input]
        : change.name === "MultiEdit" && Array.isArray(change.input.edits)
          ? (change.input.edits as unknown[]).filter(
              (edit): edit is Record<string, unknown> => typeof edit === "object" && edit !== null,
            )
          : null;
    if (edits === null) return null;
    for (const edit of edits) {
      const old = str(edit, "old_string");
      const replacement = str(edit, "new_string") ?? "";
      if (!old || !text.includes(old)) return null;
      text =
        edit.replace_all === true
          ? text.split(old).join(replacement)
          : text.replace(old, () => replacement);
    }
  }
  return text;
}

/** The chunks as a unified diff, `CONTEXT` lines around each change. */
function render(path: string, chunks: readonly Chunk[], numbered: boolean): string {
  const out = [`--- a/${path}`, `+++ b/${path}`];
  let shift = 0;
  for (const chunk of chunks) {
    const rows = chunk.rows;
    const changed = rows.flatMap((row, i) => (row.kind === "same" ? [] : [i]));
    let oldNo = numbered ? (chunk.start ?? 1) : 1;
    let newNo = oldNo + shift;
    let i = 0;
    for (let first = changed.shift(); first !== undefined; first = changed.shift()) {
      let last = first;
      while (changed[0] !== undefined && changed[0] - last <= CONTEXT * 2 + 1) {
        last = changed[0];
        changed.shift();
      }
      const from = Math.max(i, first - CONTEXT);
      const to = Math.min(rows.length, last + CONTEXT + 1);
      for (; i < from; i++) {
        oldNo++;
        newNo++;
      }
      const body = rows.slice(from, to);
      const olds = body.filter((row) => row.kind !== "add").length;
      const news = body.filter((row) => row.kind !== "del").length;
      out.push(`@@ -${String(oldNo)},${String(olds)} +${String(newNo)},${String(news)} @@`);
      for (const row of body) {
        out.push(`${row.kind === "add" ? "+" : row.kind === "del" ? "-" : " "}${row.text}`);
      }
      oldNo += olds;
      newNo += news;
      i = to;
    }
    shift += delta(rows);
  }
  return out.join("\n");
}

function stats(chunks: readonly Chunk[]) {
  const rows = chunks.flatMap((chunk) => chunk.rows);
  return {
    added: rows.filter((row) => row.kind === "add").length,
    removed: rows.filter((row) => row.kind === "del").length,
  };
}

/**
 * What the applied `changes` to `path` add up to, oldest first; `created`: the first one wrote the
 * whole file. Null when they cannot be added up with certainty.
 */
export function netDiff(
  path: string,
  changes: readonly NetInput[],
  created: boolean,
): NetDiff | null {
  if (changes.length === 0) return null;
  if (created && changes[0]?.name === "Write") {
    const text = replay(changes);
    if (text === null) return null;
    const lines = splitLines(text);
    const chunks: Chunk[] = [
      { start: 1, rows: lines.map((line) => ({ text: line, kind: "add" })) },
    ];
    return {
      diff: [
        "--- /dev/null",
        `+++ b/${path}`,
        `@@ -0,0 +1,${String(lines.length)} @@`,
        ...lines.map((line) => `+${line}`),
      ].join("\n"),
      numbered: true,
      ...stats(chunks),
    };
  }
  if (changes.some((change) => change.name === "Write")) return null;
  const chunks: Chunk[] = [];
  for (const change of changes) {
    const hunks = parseHunks(change.diff);
    if (hunks === null) return null;
    for (const hunk of hunks) {
      const numbered = change.numbered && chunks.every((chunk) => chunk.start !== null);
      if (!(numbered ? placeNumbered(chunks, hunk) : placeByLines(chunks, hunk))) return null;
    }
  }
  const numbered = chunks.every((chunk) => chunk.start !== null);
  if (numbered) chunks.sort((a, b) => (a.start ?? 0) - (b.start ?? 0));
  return { diff: render(path, chunks, numbered), numbered, ...stats(chunks) };
}
