import { describe, expect, it } from "vitest";

import { buildTree, countNotes, matchNotes, noteName } from "./tree";

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
