/**
 * The readable view of a note: the same file the agents read, shown for a person.
 *
 * The note on disk never changes. Only what the page renders does: the bookkeeping written for
 * agents (the "Path shorthand" legend, "(research 1.2)" and "(verified for this spec)" markers)
 * is left out, and a code reference (`order_cover_service.py:157-165`, `OCS:157-165`) becomes a
 * compact chip with the file's name, its full path and lines on hover. The agent view shows it all.
 */

/** A shorthand of the note's legend (`OCS` → its full path), longest key first. */
export type Shorthand = readonly (readonly [key: string, path: string])[];

export interface ReadableNote {
  /** The markdown to render, without the agent-only bookkeeping. */
  source: string;
  /** The note's path shorthand, used to expand a code reference to its full path. */
  shorthand: Shorthand;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/;
const LEGEND = /^\s*(?:[-*+]\s+)?path shorthand\b/i;
const LEGEND_ITEM = /^\s*[-*+]\s+`[^`]+`\s*=\s*`[^`]+`\s*[,.;]?\s*$/;
const PAIR = /`([^`]+)`\s*=\s*`([^`]+)`/g;
/**
 * "(research 1.2, 3)", "(research 7.1 option A)", "(verified for this spec)": evidence markers. A
 * quoted one ("marked \"(verified for this spec)\"") is the note talking about them, and stays.
 */
const MARKER = /[ \t]*(?<!["'“‘])\((?:research\b|verified\s+for\s+this\s+spec)[^()`]*\)/gi;

function shorthandOf(text: string): Shorthand {
  const pairs = [...text.matchAll(PAIR)].map(([, key = "", path = ""]) => [key, path] as const);
  return pairs.sort((a, b) => b[0].length - a[0].length);
}

/** The note for a person: legend and evidence markers dropped, code blocks left as written. */
export function readableNote(markdown: string): ReadableNote {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const kept: string[] = [];
  const legend: string[] = [];
  // Prose is cleaned as a whole, since a marker may wrap onto the next line.
  let prose: string[] = [];
  const flush = () => {
    if (prose.length) kept.push(...prose.join("\n").replace(MARKER, "").split("\n"));
    prose = [];
  };
  let fence: string | null = null;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const open = FENCE.exec(line)?.[1];
    if (fence !== null) {
      if (open?.startsWith(fence)) fence = null;
      kept.push(line);
      i++;
      continue;
    }
    if (open) {
      flush();
      fence = open;
      kept.push(line);
      i++;
      continue;
    }
    if (LEGEND.test(line)) {
      // The legend's paragraph, then the list of `KEY` = `path` items that may follow it.
      while (i < lines.length && (lines[i] ?? "").trim() !== "") legend.push(lines[i++] ?? "");
      let next = i;
      while (next < lines.length && (lines[next] ?? "").trim() === "") next++;
      if (LEGEND_ITEM.test(lines[next] ?? "")) {
        i = next;
        while (i < lines.length && LEGEND_ITEM.test(lines[i] ?? "")) legend.push(lines[i++] ?? "");
      }
      continue;
    }
    prose.push(line);
    i++;
  }
  flush();
  return { source: kept.join("\n"), shorthand: shorthandOf(legend.join("\n")) };
}

/** A code span that points at code: where (expanded) and which lines, and the chip's label. */
export interface CodeReference {
  label: string;
  title: string;
}

const LINES = /^([^\s:]*):(\d+(?:-\d+)?(?:,\s*:?\d+(?:-\d+)?)*)$/;
const PATH = /^[^\s/][^\s]*\/[^\s]*\.[A-Za-z]{1,5}$/;

function expand(path: string, shorthand: Shorthand): string {
  let out = path;
  for (let round = 0; round < 5; round++) {
    const hit = shorthand.find(([key]) =>
      key.endsWith("/") ? out.startsWith(key) : out === key || out.startsWith(`${key}/`),
    );
    if (!hit) return out;
    out = hit[1] + out.slice(hit[0].length);
  }
  return out;
}

function baseName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/**
 * The code reference a code span holds (`file.py:12-30`, `OCS:157`, `:223-235`, `a/b/c.tsx`), or
 * null when it is code of another kind (a name, a value, a route), which stays as written.
 */
export function codeReference(code: string, shorthand: Shorthand): CodeReference | null {
  const text = code.trim();
  const lines = LINES.exec(text);
  if (lines) {
    const [, place = "", range = ""] = lines;
    const known = shorthand.some(([key]) => key === place || place.startsWith(key));
    if (place && !known && !/[./]/.test(place)) return null;
    const where = place ? expand(place, shorthand) : "";
    const span = range.replace(/\s*,\s*:?/g, ", ");
    return {
      label: where ? baseName(where) : `lines ${span}`,
      title: where ? `${where}:${range}` : `Lines ${span}`,
    };
  }
  if (PATH.test(text)) {
    const where = expand(text, shorthand);
    return { label: baseName(where), title: where };
  }
  return null;
}

/** The frontmatter fields that only say what the file is, already shown by the page. */
const HIDDEN_FIELDS = new Set(["type", "feature", "spec", "research", "plan"]);

const FIELD_LABELS: Readonly<Record<string, string>> = {
  process_size: "Size",
  linear: "Tickets",
  last_verified: "Last checked",
  provenance: "Written by",
  repos: "Repositories",
};

/** The fields a person reads, with a label in words: `last_verified` → "Last checked". */
export function readableFields<V>(frontmatter: Readonly<Record<string, V>>): [string, V][] {
  return Object.entries(frontmatter)
    .filter(([key]) => !HIDDEN_FIELDS.has(key))
    .map(([key, value]) => {
      const label = FIELD_LABELS[key] ?? key.replace(/[_-]+/g, " ");
      return [label.charAt(0).toUpperCase() + label.slice(1), value];
    });
}
