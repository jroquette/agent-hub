import { describe, expect, it } from "vitest";

import { toDocument, type BuilderNode } from "./model";
import {
  JOIN_RULE,
  insertAt,
  negateCondition,
  nodesOf,
  programOf,
  takeFrom,
  type Item,
} from "./program";

function nodes(list: unknown[]): BuilderNode[] {
  return toDocument({ nodes: list }).nodes;
}

const SHAPE = (items: readonly Item[]): unknown =>
  items.map((item) => {
    if (item.kind === "block") return item.node.id;
    if (item.kind === "repeat") return { repeat: item.node.id, body: SHAPE(item.body) };
    if (item.kind === "if")
      return { if: item.condition, then: SHAPE(item.then), else: SHAPE(item.otherwise) };
    return { together: item.lanes.map(SHAPE) };
  });

const tipple = nodes([
  { id: "create-order", type: "approval", capture_response: true },
  { id: "fetch", type: "action", action: "send", depends_on: ["create-order"] },
  {
    id: "quote",
    type: "expect",
    action: "read",
    depends_on: ["fetch"],
    every: "15s",
    timeout: "10m",
    until_when: "$self.output.cover != 'PENDING'",
    capture: { cover: "$self.output.cover" },
  },
  {
    id: "switch-fedex",
    type: "action",
    action: "db",
    depends_on: ["quote"],
    when: "$CTX.cover == 'QUOTED'",
  },
  { id: "reprocess", type: "action", action: "send", depends_on: ["switch-fedex"] },
  {
    id: "note-refused",
    type: "action",
    action: "note",
    depends_on: ["quote"],
    when: "$CTX.cover != 'QUOTED'",
  },
  {
    id: "invoice",
    type: "action",
    action: "send",
    depends_on: ["reprocess", "note-refused"],
    trigger_rule: JOIN_RULE,
  },
  {
    id: "poll",
    type: "loop_group",
    depends_on: ["invoice"],
    max_iterations: 3,
    until_when: "$check.output.cover == 'ACTIVATED'",
    nodes: [
      { id: "poller", type: "action", action: "send" },
      { id: "check", type: "action", action: "read", depends_on: ["poller"] },
    ],
  },
]);

describe("scenario block program", () => {
  it("reads a chain, an if / else, its join and a repeat as nested blocks", () => {
    const program = programOf(tipple);

    expect(program.loose).toEqual([]);
    expect(SHAPE(program.main)).toEqual([
      "create-order",
      "fetch",
      "quote",
      { if: "$CTX.cover == 'QUOTED'", then: ["switch-fedex", "reprocess"], else: ["note-refused"] },
      "invoice",
      { repeat: "poll", body: ["poller", "check"] },
    ]);
  });

  it("writes the same nodes back (a reading, not a second format)", () => {
    expect(nodesOf(programOf(tipple).main)).toEqual(tipple);
  });

  it("reads siblings without complementary conditions as paths at the same time", () => {
    const list = nodes([
      { id: "a", type: "action", action: "x" },
      { id: "b", type: "action", action: "x", depends_on: ["a"] },
      { id: "c", type: "action", action: "x", depends_on: ["a"] },
      { id: "d", type: "action", action: "x", depends_on: ["b", "c"] },
    ]);

    const program = programOf(list);

    expect(SHAPE(program.main)).toEqual(["a", { together: [["b"], ["c"]] }, "d"]);
    expect(nodesOf(program.main)).toEqual(list);
  });

  it("writes an if with no else so the next block runs after either path", () => {
    const items: Item[] = [
      { kind: "block", node: { id: "a", type: "action", action: "x" } },
      {
        kind: "if",
        key: "if-1",
        condition: "$a.output.ok == true",
        then: [{ kind: "block", node: { id: "b", type: "action", action: "x" } }],
        otherwise: [],
      },
      { kind: "block", node: { id: "c", type: "action", action: "x" } },
    ];

    const written = nodesOf(items);

    expect(written[1]).toMatchObject({ id: "b", depends_on: ["a"], when: "$a.output.ok == true" });
    expect(written[2]).toMatchObject({ id: "c", depends_on: ["b", "a"], trigger_rule: JOIN_RULE });
    expect(SHAPE(programOf(written).main)).toEqual([
      "a",
      { if: "$a.output.ok == true", then: ["b"], else: [] },
      "c",
    ]);
  });

  it("negates a condition in the grammar's shape", () => {
    expect(negateCondition("$x == 'A'")).toBe("$x != 'A'");
    expect(negateCondition("$x == 'A' || $y > 2")).toBe("$x != 'A' && $y <= 2");
    expect(negateCondition("$x == 'A' && $y > 2")).toBe("$x != 'A' || $y <= 2");
  });

  it("drags a block with the blocks under it into another path", () => {
    const program = programOf(tipple);
    const { rest, taken } = takeFrom(program.main, "reprocess");

    const moved = insertAt(rest, { in: "otherwise", owner: itemKey(rest) }, 0, taken);

    expect(SHAPE(moved)).toEqual([
      "create-order",
      "fetch",
      "quote",
      { if: "$CTX.cover == 'QUOTED'", then: ["switch-fedex"], else: ["reprocess", "note-refused"] },
      "invoice",
      { repeat: "poll", body: ["poller", "check"] },
    ]);
  });
});

function itemKey(items: readonly Item[]): string {
  const found = items.find((item) => item.kind === "if");
  return found?.kind === "if" ? found.key : "";
}
