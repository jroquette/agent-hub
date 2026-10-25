import { describe, expect, it } from "vitest";

import { TREE_FIXTURES, aTreeDocument } from "../../../testing/builders";
import { dependsOn, toDocument, type BuilderNode, type Json } from "./model";
import {
  JOIN_RULE,
  addressOfKey,
  insertAt,
  isTree,
  itemId,
  keyPathOf,
  negateCondition,
  nodesOf,
  programOf,
  stagesOf,
  takeFrom,
  treeNodes,
  treeOf,
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
    if (item.kind === "stage") return { stage: item.name, steps: SHAPE(item.steps) };
    return { together: item.lanes.map(SHAPE) };
  });

const demo = nodes([
  { id: "create-order", type: "approval", capture_response: true },
  { id: "fetch", type: "action", action: "send", depends_on: ["create-order"] },
  {
    id: "review",
    type: "expect",
    action: "read",
    depends_on: ["fetch"],
    every: "15s",
    timeout: "10m",
    until_when: "$self.output.review_state != 'PENDING'",
    capture: { review_state: "$self.output.review_state" },
  },
  {
    id: "set-carrier",
    type: "action",
    action: "db",
    depends_on: ["review"],
    when: "$CTX.review_state == 'REVIEWED'",
  },
  { id: "reprocess", type: "action", action: "send", depends_on: ["set-carrier"] },
  {
    id: "note-refused",
    type: "action",
    action: "note",
    depends_on: ["review"],
    when: "$CTX.review_state != 'REVIEWED'",
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
    until_when: "$check.output.review_state == 'APPROVED'",
    nodes: [
      { id: "poll-again", type: "action", action: "send" },
      { id: "check", type: "action", action: "read", depends_on: ["poll-again"] },
    ],
  },
]);

describe("scenario block program", () => {
  it("reads a chain, an if / else, its join and a repeat as nested blocks", () => {
    const program = programOf(demo);

    expect(program.loose).toEqual([]);
    expect(SHAPE(program.main)).toEqual([
      "create-order",
      "fetch",
      "review",
      {
        if: "$CTX.review_state == 'REVIEWED'",
        then: ["set-carrier", "reprocess"],
        else: ["note-refused"],
      },
      "invoice",
      { repeat: "poll", body: ["poll-again", "check"] },
    ]);
  });

  it("writes the same nodes back (a reading, not a second format)", () => {
    expect(nodesOf(programOf(demo).main)).toEqual(demo);
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
    const program = programOf(demo);
    const { rest, taken } = takeFrom(program.main, "reprocess");

    const moved = insertAt(rest, { in: "otherwise", owner: itemKey(rest) }, 0, taken);

    expect(SHAPE(moved)).toEqual([
      "create-order",
      "fetch",
      "review",
      {
        if: "$CTX.review_state == 'REVIEWED'",
        then: ["set-carrier"],
        else: ["reprocess", "note-refused"],
      },
      "invoice",
      { repeat: "poll", body: ["poll-again", "check"] },
    ]);
  });
});

/** A tree fixture as the builder holds it (the JSON the API gives). */
function tree(name: string): Record<string, Json> {
  return aTreeDocument(name) as Record<string, Json>;
}

/** Each item's address, kind and, for a block that becomes a node, its node's type and id. */
const ADDRESSED = (items: readonly Item[]): unknown =>
  items.map((item) => {
    const key = itemId(item);
    if (item.kind === "stage") return { [key]: item.name, steps: ADDRESSED(item.steps) };
    if (item.kind === "block") return `${key} ${item.node.type} ${item.node.id}`;
    if (item.kind === "repeat") return { [`${key} repeat ${item.node.id}`]: ADDRESSED(item.body) };
    if (item.kind === "if")
      return { [`${key} if`]: { then: ADDRESSED(item.then), else: ADDRESSED(item.otherwise) } };
    return { [`${key} together`]: item.lanes.map(ADDRESSED) };
  });

describe("scenario block program, written as blocks (version 2)", () => {
  it.each(TREE_FIXTURES)(
    "round-trips the tree fixture %s: the document written back equals the server's parse",
    (name) => {
      const document = tree(name);

      expect(isTree(document)).toBe(true);
      expect(treeOf(document, stagesOf(document))).toStrictEqual(tree(name));
    },
  );

  it("reads the reference scenario's stages straight into blocks, in file order", () => {
    const stages = stagesOf(tree("demo-order-roundtrip"));

    expect(stages.map((stage) => (stage.kind === "stage" ? stage.name : null))).toEqual([
      "Fetch order",
      "Review",
      "Switch carrier",
      "Dispatch",
      "Invoice PDF",
      "Send invoice",
      "Approval",
      "Payment",
    ]);
    expect(stages.map((stage) => (stage.kind === "stage" ? stage.steps.length : 0))).toEqual([
      2, 2, 5, 2, 1, 2, 4, 4,
    ]);
    expect(ADDRESSED(stages.slice(0, 2))).toEqual([
      { "1": "Fetch order", steps: ["1.1 action fetch-order--1", "1.2 expect fetch-order--2"] },
      { "2": "Review", steps: ["2.1 action review--1", "2.2 expect review--2"] },
    ]);
    const [first] = stages;
    const wait = first?.kind === "stage" ? first.steps[1] : undefined;
    expect(wait?.kind === "block" ? wait.node : null).toEqual({
      id: "fetch-order--2",
      type: "expect",
      action: "order-state",
      until_when:
        "$self.output.order_status == 'ON_HOLD' && $self.output.review_status == 'PENDING'",
      every: "15s",
      timeout: "10m",
      capture: { order_id: "$self.output.order_id" },
    });
  });

  it("addresses the blocks inside an If, a Together and a Repeat as the translation does", () => {
    expect(ADDRESSED(stagesOf(tree("blocks-nested")))).toEqual([
      {
        "1": "Route order",
        steps: [
          "1.1 expect route-order--1",
          {
            "1.2 if": {
              then: [
                {
                  "1.2.then.1 if": {
                    then: ["1.2.then.1.then.1 action route-order--2-then-1-then-1"],
                    else: ["1.2.then.1.else.1 approval route-order--2-then-1-else-1"],
                  },
                },
                "1.2.then.2 action route-order--2-then-2",
                {
                  "1.2.then.3 if": {
                    then: ["1.2.then.3.then.1 action route-order--2-then-3-then-1"],
                    else: [],
                  },
                },
              ],
              else: ["1.2.else.1 action route-order--2-else-1"],
            },
          },
          "1.3 action route-order--3",
        ],
      },
    ]);
    expect(ADDRESSED(stagesOf(tree("blocks-together")))).toEqual([
      {
        "1": "Fix shipping",
        steps: [
          "1.1 expect fix-shipping--1",
          {
            "1.2 together": [
              ["1.2.p1.1 action fix-shipping--2-p1-1"],
              ["1.2.p2.1 action fix-shipping--2-p2-1", "1.2.p2.2 action fix-shipping--2-p2-2"],
            ],
          },
          "1.3 action fix-shipping--3",
        ],
      },
    ]);
    // A Repeat's steps are addressed under it; a block's own id is kept as written.
    expect(ADDRESSED(stagesOf(tree("blocks-repeat")))).toEqual([
      {
        "1": "Poll review",
        steps: [
          "1.1 expect poll-review--1",
          { "1.2 repeat poll-review--2": ["1.2.1 action poll-review--2-1", "1.2.2 expect poll"] },
        ],
      },
    ]);
  });

  it("writes a moved block at its new place with no id, and keeps an id the block gives", () => {
    const document = tree("blocks-repeat");
    const stages = stagesOf(document);
    const { rest, taken } = takeFrom(stages, "1.2.2", true);
    const moved = insertAt(rest, { in: "stage", owner: "1" }, 0, taken);

    const written = treeOf(document, moved);
    const steps = (written.stages as { steps: Record<string, Json>[] }[])[0]?.steps ?? [];

    expect(steps.map((step) => step.id ?? null)).toEqual(["poll", null, null]);
    expect(ADDRESSED(stagesOf(written))).toEqual([
      {
        "1": "Poll review",
        steps: [
          "1.1 expect poll",
          "1.2 expect poll-review--2",
          { "1.3 repeat poll-review--3": ["1.3.1 action poll-review--3-1"] },
        ],
      },
    ]);
  });

  it("draws the stages as one chain of nodes: a stage's first block runs after the last one before it", () => {
    const nodes = treeNodes(stagesOf(tree("demo-order-roundtrip")));

    expect(nodes).toHaveLength(22);
    expect(nodes.slice(0, 3).map((node) => [node.id, dependsOn(node)])).toEqual([
      ["fetch-order--1", []],
      ["fetch-order--2", ["fetch-order--1"]],
      ["review--1", ["fetch-order--2"]],
    ]);
  });

  it("finds the block a problem's key path is on, and a block's key path from its address", () => {
    expect(addressOfKey("stages[0].steps[1].together[1][0].do")).toBe("1.2.p2.1");
    expect(addressOfKey("stages[3].steps[0].repeat.steps[1].until")).toBe("4.1.2");
    expect(addressOfKey("stages[0].steps[1].then[0].else[2]")).toBe("1.2.then.1.else.3");
    expect(addressOfKey("stages[2].name")).toBe("3");
    expect(addressOfKey("inputs.shop_id")).toBeNull();
    expect(keyPathOf("1.2.p2.1")).toBe("stages[0].steps[1].together[1][0]");
    expect(keyPathOf("4.1.2")).toBe("stages[3].steps[0].repeat.steps[1]");
    expect(keyPathOf("3")).toBe("stages[2]");
  });

  it("tells a file written as blocks (version 2) from a graph it reads", () => {
    expect(isTree({ version: 2, kind: "scenario", stages: [] })).toBe(true);
    expect(isTree(toDocument({ version: 1, nodes: [] }))).toBe(false);
    // A file the page could not read is not one in blocks: the builder starts it empty.
    expect(isTree(null)).toBe(false);
    expect(isTree({ kind: "scenario", stages: [] })).toBe(false);
  });
});

function itemKey(items: readonly Item[]): string {
  const found = items.find((item) => item.kind === "if");
  return found?.kind === "if" ? found.key : "";
}
