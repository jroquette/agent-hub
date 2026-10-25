import { describe, expect, it } from "vitest";

import { describeMessage } from "./claude";

const ASKED = {
  text: "Send the order, then wait until it is on hold.",
  scope: "whole" as const,
  after: null,
  scenario: "order-lifecycle",
  pack: "orders",
  draftYaml: "version: 2\n",
  proposalPath: ".agent-runs/proposals/scenarios/orders/order-lifecycle.yaml",
  actions: [],
};

describe("what the builder asks Claude", () => {
  it("teaches the graph's keys for a scenario written as a graph (version 1)", () => {
    const message = describeMessage(ASKED);

    expect(message).toContain("trigger_rule: none_failed_min_one_success");
    expect(message).toContain("(version, kind: scenario, name, description, inputs, nodes)");
  });

  it("teaches the tree's keys for a scenario written as blocks (version 2), with no graph keys", () => {
    const message = describeMessage({ ...ASKED, tree: true, after: "1.2" });

    expect(message).toContain("(version: 2, kind: scenario, name, description, inputs, stages)");
    for (const key of ["`do:", "`wait_until:", "`you:", "`repeat:", "`if:", "`together:"]) {
      expect(message).toContain(key);
    }
    expect(message).toContain("No `nodes`, `depends_on`, `trigger_rule` or `when`");
    expect(message).not.toContain("trigger_rule: none_failed_min_one_success");
  });

  it("names the block new steps go after by its address in a scenario written as blocks", () => {
    const message = describeMessage({ ...ASKED, tree: true, scope: "after", after: "1.2" });

    expect(message).toContain("right after block 1.2");
  });
});
