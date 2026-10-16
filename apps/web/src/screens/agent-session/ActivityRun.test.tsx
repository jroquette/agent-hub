import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityRun, activitySummary, type ActivityStep } from "./ActivityRun";
import type { ToolView } from "./model";

function aCall(
  id: string,
  name: string,
  result: ToolView["result"] = null,
  input: ToolView["input"] = {},
): ActivityStep {
  const tool: ToolView = { id, name, input, parentId: null, diff: null, result };
  return { kind: "tool", key: `tool-${id}`, tool };
}

const done = (isError: boolean): ToolView["result"] => ({
  content: "ok",
  isError,
  truncated: false,
  originalBytes: null,
});

function aThought(key: string, seconds: number | null): ActivityStep {
  return {
    kind: "thinking",
    key,
    entry: { kind: "thinking", key, seq: 1, text: "Hmm", redacted: false, seconds },
  };
}

describe("activitySummary (activity-panel, AC-265.1)", () => {
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

describe("ActivityRun (activity-panel)", () => {
  const renderRun = (steps: ActivityStep[], live: boolean) => {
    const onToggle = vi.fn();
    render(
      <ActivityRun
        runKey="tool-a"
        steps={steps}
        selected={false}
        live={live}
        onToggle={onToggle}
        onAnswerPermission={vi.fn()}
      />,
    );
    return onToggle;
  };

  it("reads the call it is on while the session runs (AC-265.2)", () => {
    renderRun(
      [aCall("a", "Read", done(false)), aCall("b", "Bash", null, { command: "make check" })],
      true,
    );

    const line = screen.getByRole("button", { name: "Bash make check" });
    expect(line).toHaveAttribute("aria-expanded", "false");
  });

  it("counts the failed calls next to the summary and opens the run when pressed (AC-265.2, AC-265.3)", () => {
    const onToggle = renderRun(
      [
        aCall("a", "Bash", done(true)),
        aCall("b", "Bash", done(false)),
        aCall("c", "Read", done(true)),
      ],
      false,
    );

    const line = screen.getByRole("button", { name: "Ran 2 commands, read 1 file, 2 failed" });
    fireEvent.click(line);
    expect(onToggle).toHaveBeenCalledWith("tool-a");
  });
});
