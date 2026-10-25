import { describe, expect, it } from "vitest";

import { TREE_FIXTURES, aTreeDocument } from "../../../testing/builders";
import { dependsOn, toDocument, type BuilderNode, type Json } from "./model";
import {
  JOIN_RULE,
  acceptChange,
  addressOfKey,
  addressed,
  decisionsAfter,
  findItem,
  idChanges,
  insertAt,
  isTree,
  itemId,
  keyPathOf,
  negateCondition,
  nodesOf,
  programOf,
  renameRefs,
  replaceItem,
  stagesOf,
  takeFrom,
  treeChanges,
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

// A synthetic tree holding the step keys the fixtures leave out, in the canonical key order.
const EVERY_KEY: Record<string, Json> = {
  version: 2,
  kind: "scenario",
  name: "every-key",
  revision: 3,
  description: "Every step key of the tree format",
  inputs: { order_id: { required: true } },
  stages: [
    {
      name: "Every key",
      description: "Each step with its optional keys",
      steps: [
        {
          do: "order-get",
          id: "get-order",
          description: "Reads the order",
          with: { order_id: "$INPUTS.order_id" },
          timeout: "5m",
          capture: { status: "$self.output.status" },
          retry: { max_attempts: 3, delay: "5s", on_error: "all" },
        },
        {
          wait_until: "order-state",
          until: "$self.output.status == 'DONE'",
          every: "15s",
          timeout: "10m",
          retry: { max_attempts: 1 },
        },
        {
          you: "Approve the order, or reject it.",
          description: "A person decides",
          decisions: [
            { id: "approve", label: "Approve" },
            { id: "reject", label: "Reject" },
          ],
          capture_response: true,
        },
        { wait: { until: "2030-01-01T00:00:00Z" } },
        {
          wait: {
            attention: "Pick a carrier",
            options: [
              { id: "fast", label: "Fast" },
              { id: "slow", label: "Slow" },
            ],
          },
          id: "pick-carrier",
          description: "Waits for a choice",
        },
        {
          include: "blocks-repeat",
          description: "Polls the review",
          with: { shop_order_id: "$INPUTS.order_id" },
        },
        {
          if: "$CTX.status == 'DONE'",
          description: "Only when done",
          then: [{ wait: { duration: "1m" } }],
        },
        { together: [[{ do: "order-a" }], [{ do: "order-b" }]], description: "Both at once" },
        {
          repeat: {
            max: 3,
            until: "$get-order.output.status == 'DONE'",
            steps: [{ do: "order-c" }],
          },
          id: "again",
          description: "Tries again",
        },
      ],
    },
  ],
};

describe("scenario block program, written as blocks (version 2)", () => {
  it.each(TREE_FIXTURES)(
    "round-trips the tree fixture %s: the document written back equals the server's parse",
    (name) => {
      const document = tree(name);

      expect(isTree(document)).toBe(true);
      expect(treeOf(document, stagesOf(document))).toStrictEqual(tree(name));
      // Its keys too, in the canonical order the fixtures are written in.
      expect(JSON.stringify(treeOf(document, stagesOf(document)))).toBe(JSON.stringify(tree(name)));
    },
  );

  it("round-trips a tree holding every step key the fixtures leave out", () => {
    expect(treeOf(EVERY_KEY, stagesOf(EVERY_KEY))).toStrictEqual(EVERY_KEY);
    expect(JSON.stringify(treeOf(EVERY_KEY, stagesOf(EVERY_KEY)))).toBe(JSON.stringify(EVERY_KEY));
  });

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

  it("follows each block a reference reads to its new place id when an edit moves the blocks", () => {
    const document: Record<string, Json> = {
      version: 2,
      kind: "scenario",
      name: "refs",
      stages: [
        {
          name: "Fetch order",
          steps: [
            { do: "get-order" },
            { do: "get-shipment" },
            {
              do: "use-order",
              with: {
                order_id: "$fetch-order--1.output.order_id",
                shipment: "$fetch-order--2.output",
                price: "$$fetch-order--1.output",
              },
            },
          ],
        },
        { name: "Ship", steps: [{ do: "ship", with: { at: "$LOOP_PREV.fetch-order--2.output" } }] },
      ],
    };
    const stages = stagesOf(document);
    const written = (next: Item[]) =>
      (
        renameRefs(treeOf(document, next), idChanges(stages, next)).stages as {
          steps: Record<string, Json>[];
        }[]
      ).map((stage) => stage.steps.map((step) => step.with ?? null));

    // Two blocks that swap places swap the references to them; a `$$` is no reference.
    const { rest, taken } = takeFrom(stages, "1.1", true);
    const swapped = insertAt(rest, { in: "stage", owner: "1" }, 1, taken);
    expect(idChanges(stages, swapped)).toEqual(
      new Map([
        ["fetch-order--2", "fetch-order--1"],
        ["fetch-order--1", "fetch-order--2"],
      ]),
    );
    expect(written(swapped)).toEqual([
      [
        null,
        null,
        {
          order_id: "$fetch-order--2.output.order_id",
          shipment: "$fetch-order--1.output",
          price: "$$fetch-order--1.output",
        },
      ],
      [{ at: "$LOOP_PREV.fetch-order--1.output" }],
    ]);

    // A block removed before the read ones: they follow, and a reference to it reads no block.
    const removed = takeFrom(stages, "1.1", true).rest;
    expect(written(removed)).toEqual([
      [
        null,
        {
          order_id: "$fetch-order--1-removed.output.order_id",
          shipment: "$fetch-order--1.output",
          price: "$$fetch-order--1.output",
        },
      ],
      [{ at: "$LOOP_PREV.fetch-order--1.output" }],
    ]);

    // A block moved to another stage, and a renamed stage: its blocks run under the new slug.
    const [, second] = stages;
    const moved = takeFrom(stages, "1.2", true);
    const renamed =
      second?.kind === "stage"
        ? replaceItem(moved.rest, "2", {
            ...second,
            name: "Dispatch",
            steps: [...moved.taken, ...second.steps],
          })
        : moved.rest;
    expect(idChanges(stages, renamed)).toEqual(
      new Map([
        ["fetch-order--2", "dispatch--1"],
        ["fetch-order--3", "fetch-order--2"],
        ["ship--1", "dispatch--2"],
      ]),
    );
  });

  it("leaves a block's own id and an id two blocks share out of what an edit changes", () => {
    const document = tree("blocks-repeat");
    const stages = stagesOf(document);
    // `poll` keeps its own id wherever it goes; the blocks after the moved one follow.
    const { rest, taken } = takeFrom(stages, "1.2.2", true);
    expect(idChanges(stages, insertAt(rest, { in: "stage", owner: "1" }, 0, taken))).toEqual(
      new Map([
        ["poll-review--1", "poll-review--2"],
        ["poll-review--2", "poll-review--3"],
        ["poll-review--2-1", "poll-review--3-1"],
      ]),
    );
    // A removed block with its own id leaves the references to it as written.
    expect(idChanges(stages, takeFrom(stages, "1.2.2", true).rest)).toEqual(new Map());
    // A block given the id another block has, then another id: no reference follows either.
    const given = (items: Item[], id: string) => {
      const block = findItem(items, "1.1");
      return block?.kind === "block"
        ? replaceItem(items, "1.1", { ...block, named: true, node: { ...block.node, id } })
        : items;
    };
    const shared = given(stages, "poll");
    expect(idChanges(stages, shared)).toEqual(new Map());
    expect(idChanges(shared, given(shared, "poll-first"))).toEqual(new Map());
    expect(idChanges(stages, given(stages, "poll-first"))).toEqual(
      new Map([["poll-review--1", "poll-first"]]),
    );
    // Two stages of one slug give two blocks one id: no reference to it can follow either.
    const two = stagesOf({
      version: 2,
      kind: "scenario",
      name: "two",
      stages: [
        { name: "Poll", steps: [{ do: "a" }] },
        { name: "Poll review", steps: [{ do: "b" }, { do: "c" }] },
      ],
    });
    const [, review] = two;
    const same =
      review?.kind === "stage" ? replaceItem(two, "2", { ...review, name: "Poll" }) : two;
    expect(idChanges(two, same)).toEqual(new Map([["poll-review--2", "poll--2"]]));
  });

  it("lists two blocks a proposal adds alike as two changes, each where the proposal puts it", () => {
    const mine = stagesOf(tree("blocks-together"));
    const proposed = tree("blocks-together");
    const [stage] = proposed.stages as { steps: Json[] }[];
    stage?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });

    const changes = treeChanges(mine, stagesOf(proposed));

    expect(changes.map((change) => [change.kind, change.address])).toEqual([
      ["new", "1.4"],
      ["new", "1.5"],
    ]);
    expect(new Set(changes.map((change) => change.id)).size).toBe(2);
  });

  it("lists each block a proposal removes as a change of its own, its decision kept while others are taken", () => {
    const mine = stagesOf(tree("demo-order-roundtrip"));
    // The proposal drops the two alike `queue-send demo.poll` blocks of Approval (7.1 and 7.3)
    // and the same block in Payment (8.3).
    const proposed = tree("demo-order-roundtrip");
    const [, , , , , , approval, payment] = proposed.stages as { steps: Json[] }[];
    approval?.steps.splice(2, 1);
    approval?.steps.splice(0, 1);
    payment?.steps.splice(2, 1);
    const theirs = stagesOf(proposed);

    const changes = treeChanges(mine, theirs);

    expect(changes.map((change) => [change.kind, change.address])).toEqual([
      ["removed", "7.1"],
      ["removed", "7.3"],
      ["removed", "8.3"],
    ]);
    expect(new Set(changes.map((change) => change.id)).size).toBe(3);
    // Block 7.1 taken out: its twin is block 7.2 now, still a change to decide.
    const [first, twin] = changes.map((change) => change.id);
    const { items, keys } = addressed(takeFrom(mine, "7.1", true).rest);
    const left = treeChanges(items, theirs);
    expect(left.map((change) => [change.kind, change.address])).toEqual([
      ["removed", "7.2"],
      ["removed", "8.3"],
    ]);
    // A decision on a block no longer in the draft goes with it.
    expect(decisionsAfter(new Set([first ?? ""]), changes, left, keys)).toEqual(new Set());
    // Its twin's removal rejected before: the rejection stays on it, at its new address.
    expect(decisionsAfter(new Set([first ?? "", twin ?? ""]), changes, left, keys)).toEqual(
      new Set([left[0]?.id]),
    );
  });

  it("lists what a proposal still changes by the blocks taken in from it, when two alike are taken later first", () => {
    const proposed = tree("blocks-together");
    const [stage] = proposed.stages as { steps: Json[] }[];
    stage?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });
    const theirs = stagesOf(proposed);
    const document = tree("blocks-together");
    const [earlier, later] = treeChanges(stagesOf(document), theirs);

    const one = acceptChange(document, theirs, new Map(), later?.id ?? "");

    const left = treeChanges(stagesOf(one?.written ?? {}), theirs, one?.taken);
    expect(left.map((change) => [change.kind, change.address])).toEqual([["new", "1.4"]]);
    // An accept is no decision on what is left: only a rejection is carried.
    expect(
      decisionsAfter(
        new Set(),
        [earlier, later].flatMap((c) => c ?? []),
        left,
        one?.keys ?? new Map(),
      ),
    ).toEqual(new Set());
    expect(
      decisionsAfter(
        new Set([earlier?.id ?? ""]),
        [earlier, later].flatMap((c) => c ?? []),
        left,
        one?.keys ?? new Map(),
      ),
    ).toEqual(new Set([left[0]?.id]));
    const both = acceptChange(
      one?.written ?? {},
      theirs,
      one?.taken ?? new Map(),
      left[0]?.id ?? "",
    );
    expect(both?.written).toStrictEqual(proposed);
    expect(treeChanges(stagesOf(both?.written ?? {}), theirs, both?.taken)).toEqual([]);
  });

  it("takes a proposal's block in as the proposal wrote it, its references read in the proposal's places", () => {
    const draft = {
      version: 2,
      kind: "scenario",
      name: "s",
      revision: 1,
      stages: [{ name: "S", steps: [{ do: "a" }, { do: "b" }] }],
    };
    // Y and Z after A; Z reads Y by the id Y's place gives (s--2).
    const proposed = {
      ...draft,
      stages: [
        {
          name: "S",
          steps: [
            { do: "a" },
            { do: "y" },
            { do: "z", with: { v: "$s--2.output.x" } },
            { do: "b" },
          ],
        },
      ],
    };
    const theirs = stagesOf(proposed);
    const z = treeChanges(stagesOf(draft), theirs).find((change) => change.address === "1.3");

    const one = acceptChange(draft, theirs, new Map(), z?.id ?? "");

    expect((one?.written.stages as { steps: Json[] }[])[0]?.steps).toStrictEqual([
      { do: "a" },
      { do: "z", with: { v: "$s--2.output.x" } },
      { do: "b" },
    ]);
    const left = treeChanges(stagesOf(one?.written ?? {}), theirs, one?.taken);
    expect(left.map((change) => [change.kind, change.address])).toEqual([["new", "1.2"]]);
    const both = acceptChange(
      one?.written ?? {},
      theirs,
      one?.taken ?? new Map(),
      left[0]?.id ?? "",
    );
    expect(both?.written).toStrictEqual(proposed);
    expect(treeChanges(stagesOf(both?.written ?? {}), theirs, both?.taken)).toEqual([]);
  });

  it("aligns a stage of more steps than the format runs without a table of every pair", () => {
    const steps = (n: number, from = 0) =>
      Array.from({ length: n }, (_, at) => ({ do: `a-${String(at + from)}` }));
    const draft = { version: 2, kind: "scenario", stages: [{ name: "S", steps: steps(3000) }] };
    const proposed = {
      ...draft,
      stages: [{ name: "S", steps: [...steps(1500), { do: "new" }, ...steps(1500, 1500)] }],
    };

    const changes = treeChanges(stagesOf(draft), stagesOf(proposed));

    expect(changes.map((change) => [change.kind, change.address])).toEqual([["new", "1.1501"]]);
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
