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
