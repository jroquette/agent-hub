import { describe, expect, it } from "vitest";

import { TREE_FIXTURES, aTreeDocument, anEveryKeyTree } from "../../../testing/builders";
import { dependsOn, toDocument, type BuilderNode, type Json } from "./model";
import {
  JOIN_RULE,
  addressOfKey,
  applyReview,
  decideReview,
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
  treeNodes,
  treeOf,
  treeReview,
  type Decision,
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

// A synthetic tree holding every key the scenario writer orders, as the writer writes it.
const EVERY_KEY = anEveryKeyTree() as Record<string, Json>;

/** The steps of each stage of a document written as blocks. */
function stepsOf(document: Record<string, Json>): Json[][] {
  return (document.stages as { steps: Json[] }[]).map((stage) => stage.steps);
}

/** `draft` with all of `proposal` taken, as Accept all takes it: its stages, and its inputs and
 * description when it gives them. */
function takenAll(
  draft: Record<string, Json>,
  proposal: Record<string, Json>,
): Record<string, Json> {
  const out: Record<string, Json> = {
    ...draft,
    stages: Array.isArray(proposal.stages) ? proposal.stages : [],
  };
  if (proposal.inputs !== undefined) out.inputs = proposal.inputs;
  if (typeof proposal.description === "string") out.description = proposal.description;
  return out;
}

/** A seeded source of numbers in [0, 1) (mulberry32): the same seed, the same cases. */
function random(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(next: () => number, items: readonly T[], fallback: T): T {
  return items[Math.floor(next() * items.length)] ?? fallback;
}

function shuffled<T>(next: () => number, items: readonly T[]): T[] {
  const out = [...items];
  for (let at = out.length - 1; at > 0; at -= 1) {
    const other = Math.floor(next() * (at + 1));
    const here = out[at];
    const there = out[other];
    if (here === undefined || there === undefined) continue;
    out[at] = there;
    out[other] = here;
  }
  return out;
}

// Steps a generated draft or proposal is made of: alike ones, ones that read a block by the id
// its place gives (`$s--1`, `$LOOP_PREV.t--1`, inside an If), one with an id of its own and
// one that reads it, and containers.
const STEP_POOL: readonly Json[] = [
  { do: "a" },
  { do: "b" },
  { wait: { duration: "1m" } },
  { do: "c", with: { v: "$s--1.output.x" } },
  { do: "c", with: { v: "$s--2.output.x" } },
  { do: "d", with: { v: "$LOOP_PREV.t--1.output" } },
  { do: "e", id: "own" },
  { do: "f", with: { v: "$own.output" } },
  { if: "$CTX.x == 'y'", then: [{ do: "a" }, { do: "c", with: { v: "$s--1-then-1.output" } }] },
  { repeat: { max: 2, steps: [{ do: "b" }, { do: "c", with: { v: "$t--2.output" } }] } },
];

function aStep(next: () => number): Json {
  return JSON.parse(JSON.stringify(pick(next, STEP_POOL, { do: "a" }))) as Json;
}

/** A small draft written as blocks: up to three stages of up to four steps. */
function aDraft(next: () => number): Record<string, Json> {
  return {
    version: 2,
    kind: "scenario",
    name: "generated",
    revision: 1,
    description: "A generated draft",
    inputs: { x: { required: true } },
    stages: ["S", "T", "U"]
      .filter(() => next() < 0.7)
      .map((name) => ({
        name,
        steps: Array.from({ length: Math.floor(next() * 5) }, () => aStep(next)),
      })),
  };
}

/** `draft` changed one to four times: a step added, removed or replaced, a stage renamed (its
 * slug kept), given a description, moved, removed or added, the inputs or the description. */
function aProposal(draft: Record<string, Json>, next: () => number): Record<string, Json> {
  const proposal = JSON.parse(JSON.stringify(draft)) as Record<string, Json>;
  const stages = proposal.stages as { name: string; description?: string; steps: Json[] }[];
  for (let n = Math.floor(next() * 4); n >= 0; n -= 1) {
    const what = Math.floor(next() * 8);
    const stage = pick(next, stages, undefined);
    const at = (list: readonly unknown[], end = 0) => Math.floor(next() * (list.length + end));
    if (what === 0 && stage) stage.steps.splice(at(stage.steps, 1), 0, aStep(next));
    else if (what === 1 && stage) stage.steps.splice(at(stage.steps), 1);
    else if (what === 2 && stage && stage.steps.length > 0)
      stage.steps[at(stage.steps)] = aStep(next);
    else if (what === 3 && stage) {
      if (next() < 0.5) stage.name = stage.name.toLowerCase();
      else stage.description = "Changed by the proposal";
    } else if (what === 4 && stage) {
      stages.splice(stages.indexOf(stage), 1);
      stages.splice(at(stages, 1), 0, stage);
    } else if (what === 5 && stage) stages.splice(stages.indexOf(stage), 1);
    else if (what === 6) {
      const used = new Set(stages.map((item) => item.name.toLowerCase()));
      const name = ["V", "W", "S", "T"].find((item) => !used.has(item.toLowerCase()));
      if (name !== undefined) {
        stages.splice(at(stages, 1), 0, {
          name,
          steps: Array.from({ length: Math.floor(next() * 3) }, () => aStep(next)),
        });
      }
    } else if (what === 7) {
      if (next() < 0.5) proposal.inputs = { x: { required: true }, y: { default: "1" } };
      else proposal.description = "A changed description";
    }
  }
  return proposal;
}

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

  it("round-trips a tree holding every key in the order the scenario writer writes them", () => {
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
    const proposed = tree("blocks-together");
    const [stage] = proposed.stages as { steps: Json[] }[];
    stage?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });

    const { changes } = treeReview(tree("blocks-together"), proposed);

    expect(changes.map((change) => [change.kind, change.address])).toEqual([
      ["new", "1.4"],
      ["new", "1.5"],
    ]);
    expect(changes.map((change) => change.id)).toEqual(["new block 1.4", "new block 1.5"]);
  });

  it("takes or leaves each of two alike blocks a proposal removes by its own decision, the list as it opened", () => {
    const draft = tree("demo-order-roundtrip");
    // The proposal drops the two alike `queue-send demo.poll` blocks of Approval (7.1 and 7.3)
    // and the same block in Payment (8.3).
    const dropped = (approval: number[], payment: number[]) => {
      const changed = tree("demo-order-roundtrip");
      const stages = changed.stages as { steps: Json[] }[];
      for (const at of [...approval].reverse()) stages[6]?.steps.splice(at - 1, 1);
      for (const at of [...payment].reverse()) stages[7]?.steps.splice(at - 1, 1);
      return changed;
    };
    const review = treeReview(draft, dropped([1, 3], [3]));

    expect(review.changes.map((change) => change.id)).toEqual([
      "removed block 7.1",
      "removed block 7.3",
      "removed block 8.3",
    ]);
    // Each removal is its own: taking one leaves its twin in the draft.
    expect(applyReview(review, new Set(["removed block 7.1"]))).toStrictEqual(dropped([1], []));
    expect(applyReview(review, new Set(["removed block 7.3"]))).toStrictEqual(dropped([3], []));
    // Decided one by one, the list stays the one the review opened with.
    let decided = decideReview(review, new Map(), ["removed block 7.1"], "accept");
    expect(decided.closed).toBe(false);
    decided = decideReview(review, decided.decisions, ["removed block 7.3"], "reject");
    expect(decided.closed).toBe(false);
    expect(decided.draft).toStrictEqual(dropped([1], []));
    decided = decideReview(review, decided.decisions, ["removed block 8.3"], "accept");
    expect(decided.closed).toBe(true);
    expect(decided.draft).toStrictEqual(dropped([1], [3]));
  });

  it("keeps the earlier of two alike blocks a proposal adds to decide when the later one is accepted first", () => {
    const draft = tree("blocks-together");
    const proposed = tree("blocks-together");
    const [stage] = proposed.stages as { steps: Json[] }[];
    stage?.steps.push({ wait: { duration: "30s" } }, { wait: { duration: "30s" } });
    const one = tree("blocks-together");
    (one.stages as { steps: Json[] }[])[0]?.steps.push({ wait: { duration: "30s" } });
    const review = treeReview(draft, proposed);

    const later = decideReview(review, new Map(), ["new block 1.5"], "accept");

    expect(later.closed).toBe(false);
    expect(later.draft).toStrictEqual(one);
    const both = decideReview(review, later.decisions, ["new block 1.4"], "accept");
    expect(both.closed).toBe(true);
    expect(both.draft).toStrictEqual(proposed);
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
    const review = treeReview(draft, proposed);
    expect(review.changes.map((change) => change.id)).toEqual(["new block 1.2", "new block 1.3"]);

    // Z alone: as Claude wrote it, reading whatever runs at its place in the draft.
    expect(stepsOf(applyReview(review, new Set(["new block 1.3"])))).toStrictEqual([
      [{ do: "a" }, { do: "z", with: { v: "$s--2.output.x" } }, { do: "b" }],
    ]);
    // Both, in either order: the proposal.
    for (const order of [
      ["new block 1.3", "new block 1.2"],
      ["new block 1.2", "new block 1.3"],
    ]) {
      let decisions: ReadonlyMap<string, Decision> = new Map();
      let closed = false;
      let written: Record<string, Json> = draft;
      for (const id of order) {
        ({ decisions, closed, draft: written } = decideReview(review, decisions, [id], "accept"));
      }
      expect(closed).toBe(true);
      expect(written).toStrictEqual(proposed);
    }
  });

  it("keeps a rejected block as the draft wrote it, reading the block it read when one is taken in before it", () => {
    const draft = {
      version: 2,
      kind: "scenario",
      name: "s",
      stages: [
        { name: "S", steps: [{ do: "a" }, { do: "b" }, { do: "c", with: { v: "$s--2.output" } }] },
      ],
    };
    // A new first block, and C changed to read B at its new place.
    const proposed = {
      ...draft,
      stages: [
        {
          name: "S",
          steps: [{ do: "n" }, { do: "a" }, { do: "b" }, { do: "c2", with: { v: "$s--3.output" } }],
        },
      ],
    };
    const review = treeReview(draft, proposed);
    expect(review.changes.map((change) => change.id)).toEqual([
      "new block 1.1",
      "changed block 1.3",
    ]);

    // C's change rejected: C follows B to its new place.
    expect(stepsOf(applyReview(review, new Set(["new block 1.1"])))).toStrictEqual([
      [{ do: "n" }, { do: "a" }, { do: "b" }, { do: "c", with: { v: "$s--3.output" } }],
    ]);
    // C's change alone: as Claude wrote it (it reads itself, which the check names).
    expect(stepsOf(applyReview(review, new Set(["changed block 1.3"])))).toStrictEqual([
      [{ do: "a" }, { do: "b" }, { do: "c2", with: { v: "$s--3.output" } }],
    ]);
    expect(applyReview(review, new Set())).toStrictEqual(draft);
    expect(applyReview(review, new Set(review.changes.map((change) => change.id)))).toStrictEqual(
      proposed,
    );
  });

  it("keeps what a block both hold reads when a removal before an addition is taken, the one or the other", () => {
    // K reads E (third in both); J reads A in the draft and N in the proposal (second in both).
    const k = { do: "k", with: { v: "$s--3.output" } };
    const j = { do: "j", with: { v: "$LOOP_PREV.s--2.output" } };
    const draft = {
      version: 2,
      kind: "scenario",
      name: "s",
      stages: [{ name: "S", steps: [{ do: "r" }, { do: "a" }, { do: "e" }, k, j] }],
    };
    const proposed = {
      ...draft,
      stages: [{ name: "S", steps: [{ do: "a" }, { do: "n" }, { do: "e" }, k, j] }],
    };
    const review = treeReview(draft, proposed);
    expect(review.changes.map((change) => change.id)).toEqual([
      "removed block 1.1",
      "new block 1.2",
    ]);

    // The removal alone: K follows E, and J reads A, the one of its two the draft still holds.
    expect(stepsOf(applyReview(review, new Set(["removed block 1.1"])))).toStrictEqual([
      [
        { do: "a" },
        { do: "e" },
        { do: "k", with: { v: "$s--2.output" } },
        { do: "j", with: { v: "$LOOP_PREV.s--1.output" } },
      ],
    ]);
    // The addition alone: K follows E; J's two are both in the draft, so it reads as written.
    expect(stepsOf(applyReview(review, new Set(["new block 1.2"])))).toStrictEqual([
      [
        { do: "r" },
        { do: "a" },
        { do: "n" },
        { do: "e" },
        { do: "k", with: { v: "$s--4.output" } },
        j,
      ],
    ]);
    expect(applyReview(review, new Set())).toStrictEqual(draft);
    expect(applyReview(review, new Set(["new block 1.2", "removed block 1.1"]))).toStrictEqual(
      proposed,
    );
  });

  it("follows a block the proposal gives an id of its own in the blocks the draft keeps, and renames or moves a stage on its own change", () => {
    const draft = {
      version: 2,
      kind: "scenario",
      name: "s",
      stages: [
        {
          name: "Fetch order",
          steps: [{ do: "a" }, { do: "b", with: { v: "$fetch-order--1.output" } }],
        },
        { name: "Ship", steps: [{ do: "s" }] },
      ],
    };
    const proposed = {
      ...draft,
      stages: [
        { name: "Ship", steps: [{ do: "s" }] },
        {
          name: "Fetch Order",
          description: "Reads the order",
          steps: [
            { do: "a", id: "fetch" },
            { do: "b", with: { v: "$fetch.output" } },
          ],
        },
      ],
    };
    const review = treeReview(draft, proposed);
    const ids = review.changes.map((change) => change.id);
    expect(ids).toEqual(["changed stage 1", "changed block 1.1", "changed block 1.2"]);

    // A's new id alone: B, as the draft wrote it, follows A to it.
    expect(applyReview(review, new Set(["changed block 1.1"]))).toStrictEqual({
      ...draft,
      stages: [
        {
          name: "Fetch order",
          steps: [
            { do: "a", id: "fetch" },
            { do: "b", with: { v: "$fetch.output" } },
          ],
        },
        { name: "Ship", steps: [{ do: "s" }] },
      ],
    });
    // The stage's own change: its name, what it is for and its place, its steps as the draft's.
    expect(applyReview(review, new Set(["changed stage 1"]))).toStrictEqual({
      ...draft,
      stages: [
        { name: "Ship", steps: [{ do: "s" }] },
        {
          name: "Fetch Order",
          description: "Reads the order",
          steps: [{ do: "a" }, { do: "b", with: { v: "$fetch-order--1.output" } }],
        },
      ],
    });
    expect(applyReview(review, new Set(ids))).toStrictEqual(proposed);
  });

  it("leaves a reference to a block as written when the proposal gives its place an id no reference can name", () => {
    const b = { do: "b", with: { v: "$s--1.output", w: 'say "$s--1.output"' } };
    const draft = {
      version: 2,
      kind: "scenario",
      name: "s",
      stages: [{ name: "S", steps: [{ do: "a" }, b, { do: "c" }] }],
    };
    for (const id of ['k","injected":"z', 'k"q', "k\\", "k.output"]) {
      const proposed = {
        ...draft,
        stages: [{ name: "S", steps: [{ do: "a2", id }, { do: "c" }] }],
      };
      const review = treeReview(draft, proposed);
      expect(
        review.changes.map((change) => change.id),
        id,
      ).toEqual(["changed block 1.1", "removed block 1.2"]);

      // B, kept, reads exactly as the draft wrote it: no key added, nothing thrown.
      expect(stepsOf(applyReview(review, new Set(["changed block 1.1"]))), id).toStrictEqual([
        [{ do: "a2", id }, b, { do: "c" }],
      ]);
      expect(
        decideReview(review, new Map(), ["changed block 1.1"], "accept").draft,
        id,
      ).toStrictEqual({
        ...draft,
        stages: [{ name: "S", steps: [{ do: "a2", id }, b, { do: "c" }] }],
      });
    }
  });

  it("follows a reference inside a value holding quotes and backslashes, and only in values", () => {
    const document = {
      stages: [
        {
          name: "S",
          steps: [
            {
              do: "b",
              with: {
                "$s--1.output": 'say "\\$s--1.output\\" $$s--1.output',
                n: ["$s--1.output.x"],
              },
            },
          ],
        },
      ],
    };

    expect(renameRefs(document, new Map([["s--1", "fetch"]]))).toStrictEqual({
      stages: [
        {
          name: "S",
          steps: [
            {
              do: "b",
              with: {
                "$s--1.output": 'say "\\$fetch.output\\" $$s--1.output',
                n: ["$fetch.output.x"],
              },
            },
          ],
        },
      ],
    });
  });

  it("lists the scenario's inputs and description a proposal changes as changes of their own", () => {
    const draft = tree("blocks-together");
    const proposed = {
      ...tree("blocks-together"),
      description: "Fixes shipping, then checks it",
      inputs: { shop_order_id: { required: true }, carrier: { default: "fedex" } },
    };
    const review = treeReview(draft, proposed);

    expect(review.changes.map((change) => change.id)).toEqual([
      "changed inputs",
      "changed description",
    ]);
    expect(applyReview(review, new Set(["changed inputs"]))).toStrictEqual({
      ...draft,
      inputs: proposed.inputs,
    });
    expect(applyReview(review, new Set(["changed inputs", "changed description"]))).toStrictEqual(
      proposed,
    );
  });

  it("writes the inputs and description a proposal adds where the scenario writer puts them, and keeps a draft's own order otherwise", () => {
    const draft = { version: 2, kind: "scenario", name: "s", stages: [{ name: "S", steps: [] }] };
    const proposed = { ...draft, description: "Fetch it", inputs: { ref: { required: true } } };
    const review = treeReview(draft, proposed);
    const every = new Set(review.changes.map((change) => change.id));

    expect(Object.keys(applyReview(review, every))).toEqual([
      "version",
      "kind",
      "name",
      "description",
      "inputs",
      "stages",
    ]);
    // A draft in an order of its own, which gains no key: its keys stay where they are.
    const own = {
      stages: draft.stages,
      name: "s",
      kind: "scenario",
      version: 2,
      description: "Old",
    };
    const again = treeReview(own, { ...own, description: "New" });
    const keys = Object.keys(own);
    expect(Object.keys(applyReview(again, new Set(["changed description"])))).toEqual(keys);
    expect(Object.keys(applyReview(again, new Set()))).toEqual(keys);
  });

  it("gives the draft each decision's order over the list it opened with: everything taken is the proposal, nothing taken the draft (property)", () => {
    for (let seed = 1; seed <= 400; seed += 1) {
      const next = random(seed);
      const draft = aDraft(next);
      const proposed = aProposal(draft, next);
      const review = treeReview(draft, proposed);
      const ids = review.changes.map((change) => change.id);
      const context = `seed ${String(seed)}: ${JSON.stringify({ draft, proposed })}`;

      expect(new Set(ids).size, context).toBe(ids.length);
      expect(JSON.stringify(applyReview(review, new Set())), context).toBe(JSON.stringify(draft));
      expect(applyReview(review, new Set(ids)), context).toStrictEqual(takenAll(draft, proposed));
      // Accept all and Reject all: every change at once, the review closed.
      const all = decideReview(review, new Map(), ids, "accept");
      expect([all.closed, all.draft], context).toStrictEqual([true, takenAll(draft, proposed)]);
      const none = decideReview(review, new Map(), ids, "reject");
      expect([none.closed, JSON.stringify(none.draft)], context).toStrictEqual([
        true,
        JSON.stringify(draft),
      ]);
      // One by one, in any order, each accepted or rejected.
      const order = shuffled(next, ids);
      let decisions: ReadonlyMap<string, Decision> = new Map();
      const accepted = new Set<string>();
      for (const [at, id] of order.entries()) {
        const decision: Decision = next() < 0.5 ? "accept" : "reject";
        if (decision === "accept") accepted.add(id);
        const decided = decideReview(review, decisions, [id], decision);
        decisions = decided.decisions;
        expect(decided.closed, context).toBe(at === order.length - 1);
        expect(decided.draft, context).toStrictEqual(applyReview(review, accepted));
      }
      if (accepted.size === ids.length && ids.length > 0) {
        expect(applyReview(review, accepted), context).toStrictEqual(takenAll(draft, proposed));
      }
    }
  });

  it("aligns a stage of more steps than the format runs by the steps alike at its ends, the rest each changed", () => {
    const steps = (n: number, from = 0) =>
      Array.from({ length: n }, (_, at) => ({ do: `a-${String(at + from)}` }));
    const stage = (list: Json[]) => ({
      version: 2,
      kind: "scenario",
      stages: [{ name: "S", steps: list }],
    });
    const draft = stage(steps(3000));
    const proposed = stage([...steps(1500), { do: "new" }, ...steps(1500, 1500)]);

    // The steps alike at either end are kept, so one block added in the middle is one change.
    const { changes } = treeReview(draft, proposed);
    expect(changes.map((change) => [change.kind, change.address])).toEqual([["new", "1.1501"]]);

    // Both ends changed: up to 512 steps a side are aligned in full (two changes); past it, each
    // step between the ends alike is a change of its own.
    const ends = (n: number, first: string, last: string) =>
      stage([{ do: first }, ...steps(n - 2), { do: last }]);
    const full = treeReview(ends(512, "p", "q"), ends(512, "r", "s")).changes;
    expect(full.map((change) => change.id)).toEqual(["changed block 1.1", "changed block 1.512"]);
    const past = treeReview(ends(513, "p", "q"), ends(513, "r", "s")).changes;
    expect(past).toHaveLength(513);
    expect(past.every((change) => change.kind === "changed")).toBe(true);
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
