import { describe, expect, it } from "vitest";

import { EXPAND_STEP, expandDiff, fileLines, revealMore, type GapReveal } from "./expandDiff";

// The base file: 60 lines, "l1" to "l60". The diff changes line 30 and line 50.
const BASE = Array.from({ length: 60 }, (_, i) => `l${String(i + 1)}`);
const DIFF = [
  "--- a/f.py",
  "+++ b/f.py",
  "@@ -29,3 +29,3 @@ def f():",
  " l29",
  "-l30",
  "+L30",
  " l31",
  "@@ -49,3 +49,4 @@",
  " l49",
  "-l50",
  "+L50",
  "+extra",
  " l51",
].join("\n");

const none = new Map<number, GapReveal>();

// AC-424.7: the gaps a diff hides around its hunks, and the lines each press reveals.
describe("expandDiff", () => {
  it("names what each gap hides before anything is revealed", () => {
    const expanded = expandDiff(DIFF, BASE, none);

    expect(expanded?.diff).toBe(DIFF);
    expect(expanded?.headers).toEqual([
      { gap: 0, hidden: 28, first: true, last: false },
      { gap: 1, hidden: 17, first: false, last: false },
    ]);
    expect(expanded?.trailing).toEqual({ gap: 2, hidden: 9, first: false, last: true });
  });

  it("reveals lines above a hunk and moves its header up", () => {
    const expanded = expandDiff(DIFF, BASE, new Map([[0, { top: 0, bottom: 2 }]]));

    const lines = expanded?.diff.split("\n") ?? [];
    expect(lines.slice(2, 5)).toEqual(["@@ -27,5 +27,5 @@ def f():", " l27", " l28"]);
    expect(expanded?.headers[0]?.hidden).toBe(26);
  });

  it("reveals lines below a hunk, numbered on the new side after an added line", () => {
    const expanded = expandDiff(DIFF, BASE, new Map([[2, { top: 2, bottom: 0 }]]));

    const lines = expanded?.diff.split("\n") ?? [];
    expect(lines.slice(-3)).toEqual([" l51", " l52", " l53"]);
    expect(lines).toContain("@@ -49,5 +49,6 @@");
    expect(expanded?.trailing?.hidden).toBe(7);
  });

  it("merges two hunks once the gap between them is all shown", () => {
    const expanded = expandDiff(DIFF, BASE, new Map([[1, { top: 17, bottom: 0 }]]));

    const lines = expanded?.diff.split("\n") ?? [];
    expect(lines.filter((line) => line.startsWith("@@"))).toEqual(["@@ -29,23 +29,24 @@ def f():"]);
    expect(expanded?.headers).toEqual([{ gap: 0, hidden: 28, first: true, last: false }]);
  });

  it("returns null for a diff without hunks", () => {
    expect(expandDiff("", BASE, none)).toBeNull();
  });
});

describe("revealMore", () => {
  it("adds a step up or down, or the whole gap", () => {
    const gap = { gap: 1, hidden: 17, first: false, last: false };

    expect(revealMore(none, gap, "up").get(1)).toEqual({ top: 0, bottom: EXPAND_STEP });
    expect(revealMore(none, gap, "down").get(1)).toEqual({ top: EXPAND_STEP, bottom: 0 });
    expect(revealMore(none, gap, "all").get(1)).toEqual({ top: 17, bottom: 0 });
    expect(revealMore(none, { ...gap, gap: 0, first: true }, "all").get(0)).toEqual({
      top: 0,
      bottom: 17,
    });
  });
});

describe("fileLines", () => {
  it("does not count the final newline as a line", () => {
    expect(fileLines("a\nb\n")).toEqual(["a", "b"]);
    expect(fileLines("")).toEqual([]);
  });
});
