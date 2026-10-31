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

/** How many notes a folder holds, its subfolders included. */
export function countNotes(folder: BrainFolder): number {
  return folder.notes.length + folder.folders.reduce((sum, child) => sum + countNotes(child), 0);
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

/** One row of the Brain tree, in the flat list the virtual tree renders (AGH-617). */
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
  /** A folder's notes, its subfolders' included. */
  count: number;
}

/**
 * The rows of the tree's three sections, in order: each folder in `open` lists its notes, then its
 * subfolders.
 */
export function treeRows(root: BrainFolder, open: ReadonlySet<string>): TreeRow[] {
  throw new Error(`treeRows is not implemented yet (${root.path}, ${String(open.size)} open)`);
}

/**
 * The folders a note sits in, as folder paths with their trailing `/`: the tree opens them for the
 * selected note.
 */
export function foldersOf(path: string): string[] {
  throw new Error(`foldersOf is not implemented yet (${path})`);
}
