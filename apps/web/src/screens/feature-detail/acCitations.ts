/**
 * Where each acceptance criterion is cited across its feature's documents (spec, research, plan,
 * issues, evals, reviews). Read in the browser from the brain notes the app already serves: the
 * brain tree lists the feature folder, each note is fetched once and cached, and every line naming
 * an AC id is kept with the section it sits under.
 */
import { useQueries } from "@tanstack/react-query";

import { apiQuery } from "../../lib/api";
import { useBrainTree } from "../brain/queries";

export interface Citation {
  /** The note's path under `brain/`. */
  path: string;
  /** The heading the first mention sits under, as written (no `#`), or null before any heading. */
  section: string | null;
  /** The first line that names the AC, trimmed. */
  snippet: string;
  /** How many lines of the note name it. */
  count: number;
}

const HEADING = /^#{1,6}\s+(.*?)\s*#*\s*$/;
const MAX_SNIPPET = 220;

/** Every AC id a line names, including the "AC-10/11/12" short form. */
export function acIdsIn(line: string, known: ReadonlySet<string>): Set<string> {
  const found = new Set<string>();
  for (const m of line.matchAll(/(?<![\w.-])AC-(\d+(?:\.\d+)?)((?:\/\d+(?:\.\d+)?)+)?(?![\d])/g)) {
    const first = `AC-${m[1] ?? ""}`;
    if (known.has(first)) found.add(first);
    for (const more of (m[2] ?? "").split("/").filter(Boolean)) {
      if (known.has(`AC-${more}`)) found.add(`AC-${more}`);
    }
  }
  return found;
}

/** A line without the Markdown that makes it hard to read as a snippet. */
function plain(line: string): string {
  const text = line
    .replace(/^\s*(?:[-*+]|\d+\.)\s+(?:\[[ x]\]\s+)?/, "")
    .replace(/^\s*\|\s*|\s*\|\s*$/g, "")
    .replace(/\s*\|\s*/g, " · ")
    .replace(/\*\*|__|`/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .trim();
  return text.length > MAX_SNIPPET ? `${text.slice(0, MAX_SNIPPET - 1)}…` : text;
}

/** The citations of each known AC id in one note (`markdown` without frontmatter). */
export function citationsIn(
  path: string,
  markdown: string,
  known: ReadonlySet<string>,
): Map<string, Citation> {
  const out = new Map<string, Citation>();
  let section: string | null = null;
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    const heading = fenced ? null : HEADING.exec(line);
    if (heading) section = heading[1] ?? null;
    for (const id of acIdsIn(line, known)) {
      const seen = out.get(id);
      if (seen) seen.count += 1;
      else out.set(id, { path, section, snippet: plain(line), count: 1 });
    }
  }
  return out;
}

/** The order documents are listed in: the order a feature is written, then evals and reviews. */
const DOC_ORDER = ["spec.md", "research.md", "plan.md", "issues.md", "eval.md"];
function docRank(path: string): number {
  const name = path.split("/").pop() ?? "";
  const i = DOC_ORDER.indexOf(name);
  if (i >= 0) return i;
  if (path.includes("/evals/")) return DOC_ORDER.length;
  if (path.includes("/reviews/")) return DOC_ORDER.length + 1;
  return DOC_ORDER.length + 2;
}

export interface AcCitations {
  /** Each AC id's citations, one per document, in document order. */
  byAc: ReadonlyMap<string, readonly Citation[]>;
  /** The feature's documents that were read. */
  documents: number;
  loading: boolean;
}

/** The citations of the feature's AC ids, from the notes under `brain/features/<slug>/`. */
export function useAcCitations(project: string, slug: string, ids: readonly string[]): AcCitations {
  const tree = useBrainTree(project);
  const folder = `features/${slug}/`;
  const paths = (tree.data?.entries ?? [])
    .map((entry) => entry.path)
    .filter((path) => path.startsWith(folder) && path.endsWith(".md"))
    .sort((a, b) => docRank(a) - docRank(b) || a.localeCompare(b));
  const notes = useQueries({
    queries: paths.map((path) => ({
      ...apiQuery("/api/v1/projects/{project}/brain/note", { path: { project }, query: { path } }),
      staleTime: 60_000,
    })),
  });
  const known = new Set(ids);
  const byAc = new Map<string, Citation[]>();
  for (const note of notes) {
    if (!note.data) continue;
    for (const [id, citation] of citationsIn(note.data.path, note.data.markdown, known)) {
      const list = byAc.get(id) ?? [];
      list.push(citation);
      byAc.set(id, list);
    }
  }
  return {
    byAc,
    documents: notes.filter((n) => n.data).length,
    loading: tree.isPending || notes.some((n) => n.isPending),
  };
}
