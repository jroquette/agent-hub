import { describe, expect, it } from "vitest";

import { activitySummary, type ActivityStep } from "./ActivityRun";
import type { ToolView } from "./model";

function aCall(id: string, name: string): ActivityStep {
  const tool: ToolView = { id, name, input: {}, parentId: null, diff: null, result: null };
  return { kind: "tool", key: `tool-${id}`, tool };
}

function aThought(key: string, seconds: number | null): ActivityStep {
  return {
    kind: "thinking",
    key,
    entry: { kind: "thinking", key, seq: 1, text: "Hmm", redacted: false, seconds },
  };
}

describe("activitySummary (activity-panel)", () => {
  it("counts the calls by kind, first seen first, then the time spent thinking", () => {
    const steps = [
      aCall("a", "Bash"),
      aThought("t1", 3),
      aCall("b", "Read"),
      aCall("c", "Bash"),
      aThought("t2", 9),
    ];

    expect(activitySummary(steps)).toBe("Ran 2 commands, read 1 file, thought 12 s");
  });

  it("counts Grep and Glob as searches together and names an unknown tool as is", () => {
    const steps = [aCall("a", "Grep"), aCall("b", "Glob"), aCall("c", "mcp__linear__get_issue")];

    expect(activitySummary(steps)).toBe("2 searches, 1 mcp__linear__get_issue");
  });

  it("says thought without a duration when none is known", () => {
    expect(activitySummary([aCall("a", "Edit"), aThought("t", null)])).toBe(
      "Edited 1 file, thought",
    );
  });
});
