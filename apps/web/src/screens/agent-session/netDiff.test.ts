import { describe, expect, it } from "vitest";

import { netDiff, type NetInput } from "./netDiff";

const edit = (diff: string, numbered = true): NetInput => ({
  name: "Edit",
  input: {},
  diff,
  numbered,
});

describe("netDiff", () => {
  it("replays a written file's edits into one all-added diff", () => {
    const net = netDiff(
      "a.md",
      [
        { name: "Write", input: { content: "one\ntwo\nthree\n" }, diff: "", numbered: false },
        { name: "Edit", input: { old_string: "two", new_string: "2" }, diff: "", numbered: false },
        {
          name: "Edit",
          input: { old_string: "three\n", new_string: "three\nfour\n" },
          diff: "",
          numbered: false,
        },
      ],
      true,
    );
    expect(net).toEqual({
      diff: "--- /dev/null\n+++ b/a.md\n@@ -0,0 +1,4 @@\n+one\n+2\n+three\n+four",
      numbered: true,
      added: 4,
      removed: 0,
    });
  });

  it("lays numbered hunks on top of each other: an added line removed later cancels out", () => {
    const first = edit("--- a/f\n+++ b/f\n@@ -2,3 +2,3 @@\n b\n-c\n+C\n d");
    const second = edit("--- a/f\n+++ b/f\n@@ -3,2 +3,3 @@\n C\n-d\n+D\n+E");
    const third = edit("--- a/f\n+++ b/f\n@@ -4,2 +4,1 @@\n D\n-E");
    const net = netDiff("f", [first, second, third], false);
    expect(net?.diff).toBe("--- a/f\n+++ b/f\n@@ -2,3 +2,3 @@\n b\n-c\n+C\n-d\n+D");
    expect(net?.added).toBe(2);
    expect(net?.removed).toBe(2);
  });

  it("keeps far-apart changes as separate hunks with shifted new numbers", () => {
    const top = edit("--- a/f\n+++ b/f\n@@ -1,1 +1,2 @@\n a\n+new");
    const bottom = edit("--- a/f\n+++ b/f\n@@ -51,1 +51,1 @@\n-x\n+y");
    const net = netDiff("f", [top, bottom], false);
    expect(net?.diff).toBe(
      "--- a/f\n+++ b/f\n@@ -1,1 +1,2 @@\n a\n+new\n@@ -50,1 +51,1 @@\n-x\n+y",
    );
  });

  it("gives up on a hunk whose lines are not where it says", () => {
    const first = edit("--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+b");
    const wrong = edit("--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+c");
    expect(netDiff("f", [first, wrong], false)).toBeNull();
  });

  it("finds unnumbered hunks by their lines", () => {
    const first = edit("--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n+B", false);
    const second = edit("--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-B\n+bee", false);
    const net = netDiff("f", [first, second], false);
    expect(net?.diff).toBe("--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n a\n-b\n+bee");
    expect(net?.numbered).toBe(false);
  });
});
