import type { components } from "../../api/schema";

type BrainEntry = components["schemas"]["BrainEntry"];

/** A folder of the brain tree: its notes, then its subfolders, both in path order. */
export interface BrainFolder {
  /** The folder's name; "" for the brain's root. */
  name: string;
  /** The folder's path under `brain/` with a trailing `/`; "" for the root. */
  path: string;
  notes: BrainEntry[];
  folders: BrainFolder[];
}

/** Groups the flat, path-sorted listing into folders (D3 Brain browser). */
export function buildTree(entries: readonly BrainEntry[]): BrainFolder {
  const root: BrainFolder = { name: "", path: "", notes: [], folders: [] };
  for (const entry of entries) {
    const segments = entry.path.split("/");
    let folder = root;
    for (const name of segments.slice(0, -1)) {
      let next = folder.folders.find((child) => child.name === name);
      if (!next) {
        next = { name, path: `${folder.path}${name}/`, notes: [], folders: [] };
        folder.folders.push(next);
      }
      folder = next;
    }
    folder.notes.push(entry);
  }
  return root;
}

/** The note's file name: the last segment of its path. */
export function noteName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/**
 * Each folder's count, kept with the folder object: the tree's rows are listed again on every open
 * and close, while a listing's folders never change once built. A new listing has new folders.
 */
const noteCounts = new WeakMap<BrainFolder, number>();

/** How many notes a folder holds, its subfolders included, counted once per folder of a listing. */
export function countNotes(folder: BrainFolder): number {
  let count = noteCounts.get(folder);
  if (count === undefined) {
    count = folder.notes.length + folder.folders.reduce((sum, child) => sum + countNotes(child), 0);
    noteCounts.set(folder, count);
  }
  return count;
}

/** The root notes every brain starts from, by the name the tree shows them under. */
export const START_NOTES: Readonly<Record<string, string>> = {
  "index.md": "Index",
  "now.md": "Now",
};

/** The folder of unreviewed proposals: listed apart, since nothing there is authoritative. */
export const INBOX_FOLDER = "_inbox";

/** The notes whose path contains the query, case-insensitive. */
export function matchNotes<T extends { path: string }>(entries: readonly T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  return needle === ""
    ? [...entries]
    : entries.filter((entry) => entry.path.toLowerCase().includes(needle));
}

/** One row of the Brain tree, in the flat list the virtual tree renders. */
export interface TreeRow {
  kind: "note" | "folder";
  /** A note's path, or a folder's path with its trailing `/`. */
  path: string;
  /** The name the row shows: a start note's ("Index"), a note's file name or a folder's name. */
  name: string;
  /** 0 for the top rows of a section, one more per folder level. */
  depth: number;
  /** The section that lists the row: "Start here", "Folders" or "Inbox · unreviewed". */
  group: "start" | "folders" | "inbox";
  /** How many rows share the row's folder (at depth 0, its section). */
  setSize: number;
  /** The row's place among them, from 1. */
  posInSet: number;
  /** A folder's notes, its subfolders' included; 0 on a note's row. */
  count: number;
}

/** The name a root note is shown under in "Start here", when it is one of the start notes. */
function startName(path: string): string | undefined {
  return Object.hasOwn(START_NOTES, path) ? START_NOTES[path] : undefined;
}

/** Notes and folders that share a parent: an open folder's content, or a section's top rows. */
interface Siblings {
  notes: readonly BrainEntry[];
  folders: readonly BrainFolder[];
}

/** The siblings' rows at one level: the notes, then the folders, each open folder with its rows. */
function siblingRows(
  siblings: Siblings,
  open: ReadonlySet<string>,
  level: Pick<TreeRow, "group" | "depth">,
): TreeRow[] {
  const setSize = siblings.notes.length + siblings.folders.length;
  const rows = siblings.notes.map((note, index): TreeRow => ({
    kind: "note",
    path: note.path,
    name: startName(note.path) ?? noteName(note.path),
    ...level,
    setSize,
    posInSet: index + 1,
    count: 0,
  }));
  siblings.folders.forEach((folder, index) => {
    rows.push({
      kind: "folder",
      path: folder.path,
      name: folder.name,
      ...level,
      setSize,
      posInSet: siblings.notes.length + index + 1,
      count: countNotes(folder),
    });
    if (open.has(folder.path)) {
      rows.push(...siblingRows(folder, open, { group: level.group, depth: level.depth + 1 }));
    }
  });
  return rows;
}

/**
 * The rows of the tree's three sections, in order: each folder in `open` lists its notes, then its
 * subfolders.
 */
export function treeRows(root: BrainFolder, open: ReadonlySet<string>): TreeRow[] {
  const start = [
    ...root.notes.filter((note) => startName(note.path) !== undefined),
    ...root.notes.filter((note) => startName(note.path) === undefined),
  ];
  const folders = root.folders.filter((folder) => folder.name !== INBOX_FOLDER);
  const inbox = root.folders.filter((folder) => folder.name === INBOX_FOLDER);
  return [
    ...siblingRows({ notes: start, folders: [] }, open, { group: "start", depth: 0 }),
    ...siblingRows({ notes: [], folders }, open, { group: "folders", depth: 0 }),
    ...siblingRows({ notes: [], folders: inbox }, open, { group: "inbox", depth: 0 }),
  ];
}

/**
 * The folders a note sits in, as folder paths with their trailing `/`: the tree opens them for the
 * selected note.
 */
export function foldersOf(path: string): string[] {
  const folders: string[] = [];
  for (let end = path.indexOf("/"); end !== -1; end = path.indexOf("/", end + 1)) {
    folders.push(path.slice(0, end + 1));
  }
  return folders;
}
