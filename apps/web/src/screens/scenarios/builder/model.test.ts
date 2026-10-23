import { describe, expect, it } from "vitest";

import {
  conditionFromWords,
  conditionWords,
  dependsOn,
  formatCondition,
  insertAfter,
  insertBranch,
  layersOf,
  newBlock,
  parseCondition,
  passesRunValue,
  removeBlock,
  toDocument,
  updateBlock,
  valueSources,
  withoutRunRepeats,
  type BuilderDocument,
  type BuilderNode,
} from "./model";

function chain(): BuilderDocument {
  return toDocument({
    version: 1,
    kind: "scenario",
    name: "order-to-cover",
    inputs: { webshop_id: { type: "string", required: true } },
    nodes: [
      { id: "create-order", type: "approval", message: "Create it", capture_response: true },
      {
        id: "fetch",
        type: "action",
        action: "send-queue-message",
        depends_on: ["create-order"],
      },
      {
        id: "on-hold",
        type: "expect",
        action: "get-order-state",
        depends_on: ["fetch"],
        capture: { order_id: "$self.output.order_id" },
      },
      { id: "resolve", type: "action", action: "send-queue-message", depends_on: ["on-hold"] },
    ],
  });
}

function nodeOf(document: BuilderDocument, id: string): BuilderNode {
  const found = document.nodes.find((node) => node.id === id);
  if (!found) throw new Error(`no block ${id}`);
  return found;
}

function waits(document: BuilderDocument, id: string): string[] {
  return dependsOn(nodeOf(document, id));
}

describe("scenario builder model", () => {
  it("lays blocks out in the engine's layers, branches side by side", () => {
    const branched = insertBranch(chain(), "on-hold", "$CTX.order_id", ["QUOTED", "REFUSED"]);

    const layers = layersOf(branched.nodes).map((layer) => layer.map((node) => node.id));

    expect(layers).toEqual([
      ["create-order"],
      ["fetch"],
      ["on-hold"],
      ["resolve", "if-quoted", "if-refused"],
    ]);
    const quoted = branched.nodes.find((node) => node.id === "if-quoted");
    expect(quoted?.when).toBe("$CTX.order_id == 'QUOTED'");
  });

  it("slides an inserted block into the chain and reconnects on removal", () => {
    const document = chain();
    const pause = newBlock(document, "wait");

    const inserted = insertAfter(document, pause, "fetch");

    expect(waits(inserted, "pause")).toEqual(["fetch"]);
    expect(waits(inserted, "on-hold")).toEqual(["pause"]);
    const removed = removeBlock(inserted, "pause");
    expect(waits(removed, "on-hold")).toEqual(["fetch"]);
  });

  it("appends after the last blocks and gives fresh ids", () => {
    const document = chain();
    const first = newBlock(document, "expect");
    const next = insertAfter(document, first, null);
    const second = newBlock(next, "expect");

    expect(first.id).toBe("check");
    expect(second.id).toBe("check-2");
    expect(waits(next, "check")).toEqual(["resolve"]);
  });

  it("renames a block where it is waited for and referenced", () => {
    const document = chain();
    const node = nodeOf(document, "create-order");

    const renamed = updateBlock(document, "create-order", { ...node, id: "place-order" });

    expect(waits(renamed, "fetch")).toEqual(["place-order"]);
  });

  it("offers inputs, kept values, typed answers and earlier outputs, upstream only", () => {
    const sources = valueSources(chain(), "resolve", (action) =>
      action === "get-order-state" ? ["order_status"] : [],
    );

    expect(sources.map((source) => source.ref)).toEqual([
      "$INPUTS.webshop_id",
      "$create-order.output.text",
      "$CTX.order_id",
      "$on-hold.output.order_status",
    ]);
    expect(valueSources(chain(), "fetch", () => []).map((source) => source.ref)).toEqual([
      "$INPUTS.webshop_id",
      "$create-order.output.text",
    ]);
  });

  it("reads and writes conditions as or-groups of and-rows", () => {
    const text =
      "$self.output.status == 'ON_HOLD' && $self.output.cover == 'PENDING' || $self.output.code > 2";

    const groups = parseCondition(text);

    expect(groups).toHaveLength(2);
    expect(formatCondition(groups ?? [])).toBe(text);
    expect(conditionWords(text)).toBe("status is ON_HOLD and cover is PENDING or code is above 2");
    expect(parseCondition("len($x) > 2")).toBeNull();
  });
});

describe("run values", () => {
  it("drops the with values that only repeat a run value, inside groups too", () => {
    const document = {
      version: 1,
      kind: "scenario",
      name: "walk",
      revision: 1,
      inputs: { account: { type: "string" }, ref: { type: "string" } },
      nodes: [
        { id: "a", type: "action", action: "x", with: { account: "$INPUTS.account" } },
        {
          id: "loop",
          type: "loop_group",
          nodes: [
            {
              id: "b",
              type: "action",
              action: "x",
              with: { account: "$INPUTS.account", ref: "$INPUTS.other", queue: "q" },
            },
          ],
        },
      ],
    } as BuilderDocument;

    const { document: clean, dropped } = withoutRunRepeats(document);

    expect(dropped).toBe(2);
    expect(clean.nodes[0]).toEqual({ id: "a", type: "action", action: "x" });
    expect((clean.nodes[1]?.nodes as BuilderNode[])[0]?.with).toEqual({
      ref: "$INPUTS.other",
      queue: "q",
    });
    expect(passesRunValue("account", "$INPUTS.account")).toBe(true);
    expect(passesRunValue("account", "$INPUTS.other")).toBe(false);
  });
});

describe("a condition typed in words", () => {
  const fields = [
    { ref: "$self.output.status", label: "status" },
    { ref: "$self.output.state", label: "state" },
    { ref: "$CTX.record_id", label: "record_id (kept by create)" },
  ];

  it("reads rows from words, matching the fields of this place", () => {
    const result = conditionFromWords(
      "status is 200 and state is not DONE or record id >= 3",
      fields,
    );

    expect(result).toEqual({
      ok: true,
      groups: [
        [
          { field: "$self.output.status", op: "==", value: "200" },
          { field: "$self.output.state", op: "!=", value: "DONE" },
        ],
        [{ field: "$CTX.record_id", op: ">=", value: "3" }],
      ],
    });
  });

  it("names what it cannot match, and guesses nothing", () => {
    expect(conditionFromWords("color is red", fields)).toEqual({
      ok: false,
      problem:
        "No field “color” here. Fields you can compare: status, state, record_id (kept by create).",
    });
    expect(conditionFromWords("status 200", fields).ok).toBe(false);
  });
});
