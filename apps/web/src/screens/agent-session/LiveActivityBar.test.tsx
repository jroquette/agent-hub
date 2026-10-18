import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { aLogRecord } from "../../testing/builders";
import { StepsPanel } from "./LiveActivityBar";
import { turnSteps } from "./liveActivity";
import { initialTranscript, reduceTranscript, type StreamItem } from "./model";

const record = (...args: Parameters<typeof aLogRecord>): StreamItem => ({
  type: "record",
  record: aLogRecord(...args),
});

function stepsOf(items: StreamItem[]) {
  return turnSteps(items.reduce(reduceTranscript, initialTranscript()));
}

const turn: StreamItem[] = [
  record("user.message", { seq: 1, body: { text: "go" } }),
  { type: "status", status: { status: "running" } },
  record("tool.call", {
    seq: 2,
    body: { tool_use_id: "b", name: "Bash", input: { command: "make test" } },
  }),
  record("tool.result", {
    seq: 3,
    body: { tool_use_id: "b", content: "1\n2\n3\n4\n5\n6", is_error: true },
  }),
  record("tool.call", {
    seq: 4,
    body: { tool_use_id: "a", name: "Agent", input: { description: "explore" } },
  }),
  record("tool.call", {
    seq: 5,
    body: {
      tool_use_id: "g",
      name: "Grep",
      input: { pattern: "cost" },
      parent_tool_use_id: "a",
    },
  }),
];

describe("StepsPanel", () => {
  it("shows each call with its output's first lines, the rest on demand", async () => {
    render(<StepsPanel steps={stepsOf(turn)} onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Steps" })).toHaveFocus();
    expect(screen.getByText("(make test)")).toBeInTheDocument();
    // A failed call reads calmly, not as an alarm.
    expect(screen.getByText("didn't work, Claude moved on")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "… +2 lines" }));
    expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
    expect(document.querySelector(".as-feed-full")?.textContent).toBe("1\n2\n3\n4\n5\n6");
  });

  it("opens a running subagent on its calls and folds it on demand", async () => {
    render(<StepsPanel steps={stepsOf(turn)} onClose={vi.fn()} />);
    const group = screen.getByRole("button", { name: /Agent/ });
    expect(group).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("(cost)")).toBeInTheDocument();
    await userEvent.click(group);
    expect(screen.queryByText("(cost)")).toBeNull();
  });

  it("closes on Esc", async () => {
    const onClose = vi.fn();
    render(<StepsPanel steps={stepsOf(turn)} onClose={onClose} />);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
