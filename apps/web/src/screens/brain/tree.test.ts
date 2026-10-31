import { describe, expect, it } from "vitest";

import { aBrainTree, aBrainTreeOf } from "../../testing/builders";
import { buildTree, countNotes, foldersOf, matchNotes, noteName, treeRows } from "./tree";
import type { TreeRow } from "./tree";

describe("buildTree", () => {
  it("nests the notes in their folders when paths have folders", () => {
    const root = buildTree([
      { path: "decisions/index.md", size: 1 },
      { path: "features/a/plan.md", size: 2 },
      { path: "features/a/spec.md", size: 3 },
      { path: "index.md", size: 4 },
    ]);

    expect(root.notes.map((n) => n.path)).toEqual(["index.md"]);
    expect(root.folders.map((f) => f.path)).toEqual(["decisions/", "features/"]);
    const features = root.folders[1];
    expect(features?.folders[0]?.path).toBe("features/a/");
    expect(features?.folders[0]?.notes.map((n) => n.path)).toEqual([
      "features/a/plan.md",
      "features/a/spec.md",
    ]);
  });

  it("returns an empty root when the brain has no notes", () => {
    expect(buildTree([])).toEqual({ name: "", path: "", notes: [], folders: [] });
  });
});

describe("noteName", () => {
  it.each([
    ["index.md", "index.md"],
    ["features/a/plan.md", "plan.md"],
  ])("names %s %s", (path, name) => {
    expect(noteName(path)).toBe(name);
  });
});

describe("countNotes and matchNotes", () => {
  it("counts a folder's notes with its subfolders' and matches paths case-insensitively", () => {
    const entries = [
      { path: "features/a/spec.md", size: 1 },
      { path: "features/a/plan.md", size: 1 },
      { path: "features/b.md", size: 1 },
      { path: "index.md", size: 1 },
    ];
    const features = buildTree(entries).folders[0];
    if (features === undefined) throw new Error("no folder");

    expect(countNotes(features)).toBe(3);
    expect(matchNotes(entries, " PLAN ").map((entry) => entry.path)).toEqual([
      "features/a/plan.md",
    ]);
    expect(matchNotes(entries, "")).toHaveLength(4);
  });
});

/** Start notes, a folder holding a note and a subfolder of two notes, and two inbox notes. */
const NESTED = aBrainTree({
  entries: [
    { path: "_inbox/a.md", size: 1 },
    { path: "_inbox/b.md", size: 1 },
    { path: "decisions/index.md", size: 1 },
    { path: "features/b.md", size: 1 },
    { path: "features/control-plane/plan.md", size: 1 },
    { path: "features/control-plane/spec.md", size: 1 },
    { path: "index.md", size: 1 },
    { path: "now.md", size: 1 },
  ],
}).entries;

/** The paths `aBrainTreeOf` gives the notes of its folder `tree-<folder>/`, in path order. */
function notesIn(folder: number, count: number): string[] {
  return Array.from(
    { length: count },
    (_, note) => `tree-${String(folder)}/note-${String(note + 1).padStart(3, "0")}.md`,
  );
}

function paths(rows: readonly TreeRow[]): string[] {
  return rows.map((row) => row.path);
}

function folderCounts(rows: readonly TreeRow[]): [string, number][] {
  return rows.flatMap((row): [string, number][] =>
    row.kind === "folder" ? [[row.path, row.count]] : [],
  );
}

describe("treeRows", () => {
  it("lists start notes, folders and the inbox as rows in tree order, with depth, set size and position", () => {
    const open = new Set(["_inbox/", "decisions/", "features/", "features/control-plane/"]);

    const rows = treeRows(buildTree(NESTED), open).map((row) => [
      row.kind,
      row.path,
      row.name,
      row.depth,
      row.group,
      row.setSize,
      row.posInSet,
    ]);

    // kind, path, name, depth, section, set size, position in the set
    expect(rows).toEqual([
      ["note", "index.md", "Index", 0, "start", 2, 1],
      ["note", "now.md", "Now", 0, "start", 2, 2],
      ["folder", "decisions/", "decisions", 0, "folders", 2, 1],
      ["note", "decisions/index.md", "index.md", 1, "folders", 1, 1],
      ["folder", "features/", "features", 0, "folders", 2, 2],
      ["note", "features/b.md", "b.md", 1, "folders", 2, 1],
      ["folder", "features/control-plane/", "control-plane", 1, "folders", 2, 2],
      ["note", "features/control-plane/plan.md", "plan.md", 2, "folders", 2, 1],
      ["note", "features/control-plane/spec.md", "spec.md", 2, "folders", 2, 2],
      ["folder", "_inbox/", "_inbox", 0, "inbox", 1, 1],
      ["note", "_inbox/a.md", "a.md", 1, "inbox", 2, 1],
      ["note", "_inbox/b.md", "b.md", 1, "inbox", 2, 2],
    ]);
  });

  it.each([
    {
      closed: "every folder of a 600-note brain",
      entries: aBrainTreeOf(600).entries,
      size: 605,
      open: new Set<string>(),
      rows: [
        "index.md",
        "now.md",
        "tree-1/",
        "tree-2/",
        "tree-3/",
        "tree-4/",
        "tree-5/",
        "tree-6/",
        "_inbox/",
      ],
    },
    {
      closed: "a folder whose subfolder is in the open set",
      entries: NESTED,
      size: 8,
      open: new Set(["features/control-plane/"]),
      rows: ["index.md", "now.md", "decisions/", "features/", "_inbox/"],
    },
  ])(
    "lists no row of a closed folder's notes or subfolders ($closed)",
    ({ entries, size, open, rows }) => {
      expect(entries).toHaveLength(size);

      expect(paths(treeRows(buildTree(entries), open))).toEqual(rows);
    },
  );

  it.each([
    {
      selected: "tree-3/note-050.md",
      entries: aBrainTreeOf(600).entries,
      rows: [
        "index.md",
        "now.md",
        "tree-1/",
        "tree-2/",
        "tree-3/",
        ...notesIn(3, 100),
        "tree-4/",
        "tree-5/",
        "tree-6/",
        "_inbox/",
      ],
    },
    {
      selected: "features/control-plane/plan.md",
      entries: NESTED,
      rows: [
        "index.md",
        "now.md",
        "decisions/",
        "features/",
        "features/b.md",
        "features/control-plane/",
        "features/control-plane/plan.md",
        "features/control-plane/spec.md",
        "_inbox/",
      ],
    },
    {
      selected: "_inbox/b.md",
      entries: NESTED,
      rows: [
        "index.md",
        "now.md",
        "decisions/",
        "features/",
        "_inbox/",
        "_inbox/a.md",
        "_inbox/b.md",
      ],
    },
    {
      selected: "index.md",
      entries: NESTED,
      rows: ["index.md", "now.md", "decisions/", "features/", "_inbox/"],
    },
  ])("opens the selected note's folders in the seed ($selected)", ({ selected, entries, rows }) => {
    expect(entries.map((entry) => entry.path)).toContain(selected);

    expect(paths(treeRows(buildTree(entries), new Set(foldersOf(selected))))).toEqual(rows);
  });

  it.each([
    {
      earlier: "tree-1/note-010.md",
      picked: "tree-4/note-020.md",
      entries: aBrainTreeOf(600).entries,
      rows: [
        "index.md",
        "now.md",
        "tree-1/",
        ...notesIn(1, 100),
        "tree-2/",
        "tree-3/",
        "tree-4/",
        ...notesIn(4, 100),
        "tree-5/",
        "tree-6/",
        "_inbox/",
      ],
    },
    {
      earlier: "features/control-plane/plan.md",
      picked: "decisions/index.md",
      entries: NESTED,
      rows: [
        "index.md",
        "now.md",
        "decisions/",
        "decisions/index.md",
        "features/",
        "features/b.md",
        "features/control-plane/",
        "features/control-plane/plan.md",
        "features/control-plane/spec.md",
        "_inbox/",
      ],
    },
  ])(
    "keeps folders opened earlier when another note is selected ($earlier, then $picked)",
    ({ earlier, picked, entries, rows }) => {
      const listed = entries.map((entry) => entry.path);
      expect(listed).toContain(earlier);
      expect(listed).toContain(picked);
      const open = new Set([...foldersOf(earlier), ...foldersOf(picked)]);

      expect(paths(treeRows(buildTree(entries), open))).toEqual(rows);
    },
  );

  it("counts each folder's notes once per listing", () => {
    const root = buildTree(aBrainTreeOf(600).entries);
    const tree3 = root.folders.find((folder) => folder.path === "tree-3/");
    if (tree3 === undefined) throw new Error("the 600-note brain has no tree-3/ folder");
    expect(tree3.notes).toHaveLength(100);
    const counted = [
      ["tree-1/", 100],
      ["tree-2/", 100],
      ["tree-3/", 100],
      ["tree-4/", 100],
      ["tree-5/", 100],
      ["tree-6/", 100],
      ["_inbox/", 3],
    ];

    expect(folderCounts(treeRows(root, new Set<string>()))).toEqual(counted);

    tree3.notes.push({ path: "tree-3/note-101.md", size: 120 });
    expect(countNotes(tree3)).toBe(100);
    expect(folderCounts(treeRows(root, new Set<string>()))).toEqual(counted);

    const next = buildTree(aBrainTreeOf(606).entries);
    expect(folderCounts(treeRows(next, new Set<string>()))).toEqual([
      ["tree-1/", 101],
      ["tree-2/", 101],
      ["tree-3/", 101],
      ["tree-4/", 101],
      ["tree-5/", 101],
      ["tree-6/", 101],
      ["_inbox/", 3],
    ]);
  });
});
