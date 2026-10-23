import { describe, expect, it } from "vitest";

import type { NodeBox } from "../../lib/nodeBoxes";
import { GUTTER_MIN, LANE, PORT_TOP, orderUnderBlockers, routeFlow } from "./flowRoutes";

const WIDTH = 288;

/** Cards stacked in columns, 72 px apart, 12 px between cards, with the given heights. */
function layout(columns: readonly (readonly [string, number][])[]): Record<string, NodeBox> {
  const boxes: Record<string, NodeBox> = {};
  columns.forEach((cards, c) => {
    let top = 76;
    const left = 32 + c * (WIDTH + GUTTER_MIN);
    for (const [ref, height] of cards) {
      boxes[ref] = { left, right: left + WIDTH, top, bottom: top + height, mid: top + height / 2 };
      top += height + 12;
    }
  });
  return boxes;
}

/** A path's start, its corners (the rounded corners' control points) and its end. */
function points(d: string | undefined): [number, number][] {
  const path = d ?? "";
  const num = (m: RegExpMatchArray | null | undefined): [number, number] | null =>
    m ? [Number(m[1]), Number(m[2])] : null;
  const start = num(/^M (-?[\d.]+) (-?[\d.]+)/.exec(path));
  const corners = [...path.matchAll(/Q (-?[\d.]+) (-?[\d.]+),/g)].map((m) => num(m));
  const end = num([...path.matchAll(/L (-?[\d.]+) (-?[\d.]+)$/g)].at(-1));
  return [start, ...corners, end].filter((p): p is [number, number] => p !== null);
}

// The TIP-1576 example: 1579 holds back five tickets; 1578 → 1580 skips group 2.
const columns = [
  ["1577", "1578"],
  ["1579", "1584"],
  ["1581", "1582", "1583", "1585", "1580"],
  ["1586"],
];
const boxes = layout([
  [
    ["1577", 160],
    ["1578", 190],
  ],
  [
    ["1579", 160],
    ["1584", 130],
  ],
  [
    ["1581", 160],
    ["1582", 160],
    ["1583", 140],
    ["1585", 140],
    ["1580", 160],
  ],
  [["1586", 140]],
]);
const edges = [
  { from: "1577", to: "1579" },
  { from: "1578", to: "1584" },
  { from: "1578", to: "1580" },
  { from: "1579", to: "1580" },
  { from: "1579", to: "1581" },
  { from: "1579", to: "1582" },
  { from: "1579", to: "1583" },
  { from: "1579", to: "1585" },
  { from: "1581", to: "1586" },
];

describe("routeFlow", () => {
  const routes = routeFlow(columns, boxes, edges);

  it("draws a level single line straight", () => {
    expect(routes.paths.get("1577→1579")).toBe(`M 320 96 L 392 96`);
    expect(routes.paths.get("1581→1586")).not.toContain(" Q ");
  });

  it("lands every line on its ticket's left side, in the id-row band", () => {
    for (const e of edges) {
      const end = points(routes.paths.get(`${e.from}→${e.to}`)).at(-1);
      const b = boxes[e.to];
      expect(end?.[0]).toBe(b?.left);
      expect(end?.[1]).toBeGreaterThanOrEqual((b?.top ?? 0) + PORT_TOP);
      expect(end?.[1]).toBeLessThanOrEqual((b?.bottom ?? 0) - 16 + 0.001);
    }
  });

  it("gives a blocker's lines one trunk, with a dot at each inner branch", () => {
    const xs = ["1580", "1581", "1582", "1583", "1585"].map(
      (to) => points(routes.paths.get(`1579→${to}`))[1]?.[0],
    );
    expect(new Set(xs).size).toBe(1);
    const onTrunk = routes.junctions.filter((j) => j.x === xs[0]);
    expect(onTrunk).toHaveLength(4);
  });

  it("runs a skip under the group it passes, a lane clear of its cards", () => {
    const [, , channel] = points(routes.paths.get("1578→1580"));
    const under = Math.max(boxes["1579"]?.bottom ?? 0, boxes["1584"]?.bottom ?? 0);
    expect(channel?.[1]).toBeGreaterThanOrEqual(under + 2 * LANE);
    expect(routes.room.bottom).toBe(0);
  });

  it("keeps the verticals in one gutter a lane apart", () => {
    const trunk = points(routes.paths.get("1579→1581"))[1]?.[0] ?? 0;
    const drop = points(routes.paths.get("1578→1580"))[3]?.[0] ?? 0;
    expect(Math.abs(trunk - drop)).toBeGreaterThanOrEqual(LANE);
    expect(routes.gutters[2]).toBe(GUTTER_MIN);
  });

  it("draws nothing for edges whose cards are not measured", () => {
    expect(routeFlow(columns, {}, edges).paths.size).toBe(0);
  });
});

describe("orderUnderBlockers", () => {
  it("orders group 1 by id and later groups under their blockers, then by id", () => {
    const blockers: Record<string, string[]> = {
      "1579": ["1577"],
      "1584": ["1578"],
      "1580": ["1578", "1579"],
      "1581": ["1579"],
      "1582": ["1579"],
    };
    const ordered = orderUnderBlockers(
      [
        ["1578", "1577"],
        ["1584", "1579"],
        ["1580", "1582", "1581"],
      ],
      (ref) => blockers[ref] ?? [],
    );
    expect(ordered).toEqual([
      ["1577", "1578"],
      ["1579", "1584"],
      ["1581", "1582", "1580"],
    ]);
  });
});
