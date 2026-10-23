import { describe, expect, it } from "vitest";

import { assignLanes } from "./canvasView";

describe("assignLanes", () => {
  it("gives overlapping spans their own lanes, the shortest nearest", () => {
    const lanes = assignLanes([
      { id: "long", start: 0, end: 6 },
      { id: "short", start: 1, end: 3 },
      { id: "after", start: 3, end: 5 },
    ]);
    expect(lanes.get("short")).toBe(0);
    // Ends where `short` starts: the same lane.
    expect(lanes.get("after")).toBe(0);
    expect(lanes.get("long")).toBe(1);
  });

  it("puts spans of one trunk in one lane over their whole range", () => {
    const lanes = assignLanes([
      { id: "a", start: 0, end: 2, trunk: "src" },
      { id: "b", start: 0, end: 5, trunk: "src" },
      { id: "c", start: 3, end: 4 },
    ]);
    expect(lanes.get("a")).toBe(lanes.get("b"));
    expect(lanes.get("c")).toBe(0);
    expect(lanes.get("a")).toBe(1);
  });
});
