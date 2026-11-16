import { describe, expect, it } from "vitest";

import { centreOn, fitView, zoomAround } from "../../lib/canvasView";
import {
  bodyLayers,
  canvasModel,
  chainOf,
  columnWidth,
  runOrder,
  visibleEdges,
  downPath,
  wrapPath,
  wrapRows,
  type Edge,
} from "./graphModel";

const GROUP = {
  id: "fixing",
  type: "loop_group",
  max_iterations: 3,
  nodes: [
    { id: "fix", type: "agent" },
    { id: "fixing__check", type: "shell", depends_on: ["fixing__fix"] },
    { id: "spec", type: "agent", depends_on: ["check", "outside"] },
    { id: "quality", type: "agent", depends_on: ["check"] },
  ],
};

describe("bodyLayers", () => {
  it("lays a group's own steps out by longest path, keyed under the group, bare or keyed in the file", () => {
    const layers = bodyLayers("fixing", GROUP);

    expect(layers.map((layer) => layer.map((step) => step.id))).toEqual([
      ["fixing__fix"],
      ["fixing__check"],
      ["fixing__spec", "fixing__quality"],
    ]);
    expect(layers[2]?.[0]).toMatchObject({
      bare: "spec",
      group: "fixing",
      depends_on: ["fixing__check"],
    });
  });

  it("keeps a cycle in the order written instead of looping", () => {
    const layers = bodyLayers("g", {
      nodes: [
        { id: "a", type: "agent", depends_on: ["b"] },
        { id: "b", type: "agent", depends_on: ["a"] },
      ],
    });

    expect(
      layers
        .flat()
        .map((step) => step.bare)
        .sort(),
    ).toEqual(["a", "b"]);
  });
});

describe("canvasModel and the drawn edges", () => {
  const layers = [
    [{ id: "plan", type: "agent", depends_on: [] }],
    [{ id: "fixing", type: "loop_group", depends_on: ["plan"] }],
    [{ id: "ship", type: "shell", depends_on: ["fixing"] }],
  ];
  const model = canvasModel(layers, {
    nodes: [{ id: "plan", type: "agent", description: "Plans." }, GROUP],
  });

  it("takes a description from the file and lists a group's own steps", () => {
    expect(model.steps.get("plan")?.description).toBe("Plans.");
    expect(model.groups.get("fixing")?.flat()).toHaveLength(4);
    expect(model.steps.get("fixing__quality")?.group).toBe("fixing");
  });

  it("draws a group's inner edges only while it is open, and its steps follow it in run order", () => {
    const closed = visibleEdges(layers, model, new Set());
    const open = visibleEdges(layers, model, new Set(["fixing"]));

    expect(closed).toEqual([
      ["plan", "fixing"],
      ["fixing", "ship"],
    ]);
    expect(open).toContainEqual(["fixing__check", "fixing__spec"]);
    expect(runOrder(layers, model, new Set(["fixing"]))).toEqual([
      "plan",
      "fixing",
      "fixing__fix",
      "fixing__check",
      "fixing__spec",
      "fixing__quality",
      "ship",
    ]);
  });

  it("measures an open group's column as its frame around its own columns", () => {
    expect(columnWidth(layers[1] ?? [], model, new Set())).toBe(216);
    expect(columnWidth(layers[1] ?? [], model, new Set(["fixing"]))).toBe(3 * 216 + 2 * 56 + 34);
  });
});

describe("chainOf", () => {
  it("collects every step upstream and downstream, and only their edges", () => {
    const edges: Edge[] = [
      ["a", "b"],
      ["b", "c"],
      ["x", "c"],
      ["c", "d"],
      ["y", "z"],
    ];

    const chain = chainOf(edges, "b");

    expect([...chain.nodes].sort()).toEqual(["a", "b", "c", "d"]);
    expect([...chain.edges].sort()).toEqual(["a→b", "b→c", "c→d"]);
  });
});

describe("wrapRows and wrapPath", () => {
  it("packs layers into rows that fit the width, one layer at least per row", () => {
    expect(wrapRows([216, 216, 216, 216], 0)).toEqual([[0, 1, 2, 3]]);
    // 64 of padding + 216 + 56 + 216 = 552 fits 600; a third does not.
    expect(wrapRows([216, 216, 216, 216], 600)).toEqual([
      [0, 1],
      [2, 3],
    ]);
    expect(wrapRows([900, 216], 600)).toEqual([[0], [1]]);
  });

  it("routes an edge to the next row through the gap, and one that skips rows down the gutter", () => {
    const a = { right: 500, mid: 30 };
    const b = { left: 32, mid: 200 };

    expect(wrapPath(a, b, 100, 0)).toBe(
      "M 500 30 L 520 30 Q 520 30, 520 30 L 520 100 Q 520 100, 520 100 L 12 100 Q 12 100, 12 100 L 12 200 Q 12 200, 12 200 L 32 200",
    );
    expect(wrapPath(a, b, 100, 0, { gapAbove: 160, gutter: 16 })).toContain("L 16 160");
  });
});

describe("the canvas view", () => {
  it("fits a world in the viewport, never above 100%", () => {
    expect(fitView({ width: 200, height: 100 }, { width: 1000, height: 600 })).toEqual({
      k: 1,
      x: 400,
      y: 250,
    });
    expect(fitView({ width: 1872, height: 100 }, { width: 1000, height: 600 }).k).toBe(0.5);
    expect(fitView({ width: 0, height: 0 }, { width: 1000, height: 600 })).toEqual({
      x: 0,
      y: 0,
      k: 1,
    });
  });

  it("centres a box and zooms around a point, within the limits", () => {
    expect(
      centreOn({ left: 0, right: 100, top: 0, bottom: 50 }, { width: 400, height: 200 }, 1),
    ).toEqual({
      k: 1,
      x: 150,
      y: 75,
    });
    expect(zoomAround({ x: 0, y: 0, k: 1 }, 2, { x: 100, y: 100 })).toEqual({
      k: 2,
      x: -100,
      y: -100,
    });
    expect(zoomAround({ x: 0, y: 0, k: 1 }, 10, { x: 0, y: 0 }).k).toBe(2);
  });
});

describe("downPath", () => {
  const a = { left: 0, right: 200, top: 0, bottom: 40 };
  const b = { left: 100, right: 300, top: 120, bottom: 160 };

  it("curves from the bottom middle of the source to the top middle of the next layer", () => {
    expect(downPath(a, b)).toBe("M 100 40 C 100 80, 200 80, 200 120");
  });

  it("routes an edge that skips layers down the left gutter", () => {
    const path = downPath(a, b, { gapBelow: 60, gapAbove: 100, gutter: 16 }, 0);
    expect(path).toContain("L 16 60");
    expect(path).toContain("L 16 100");
    expect(path.endsWith("200 120")).toBe(true);
  });
});
