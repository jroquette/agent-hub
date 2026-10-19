import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { aLogRecord } from "../../testing/builders";
import { BackgroundChip, BackgroundPanel } from "./BackgroundTasks";
import { backgroundTasks } from "./liveActivity";
import { initialTranscript, reduceTranscript, type StreamItem } from "./model";

const record = (...args: Parameters<typeof aLogRecord>): StreamItem => ({
  type: "record",
  record: aLogRecord(...args),
});
const task = (seq: number, id: string, status: string, extra: object = {}) =>
  record("task", { seq, body: { task_id: id, status, ...extra } });

const items: StreamItem[] = [
  record("user.message", { seq: 1, body: { text: "go" } }),
  record("tool.call", {
    seq: 2,
    body: {
      tool_use_id: "a",
      name: "Agent",
      input: { subagent_type: "reviewer", description: "quality review" },
    },
  }),
  task(3, "t1", "running", { tool_use_id: "a", task_type: "local_agent" }),
  record("tool.call", {
    seq: 4,
    body: { tool_use_id: "g", name: "Grep", input: { pattern: "cost" }, parent_tool_use_id: "a" },
  }),
  task(5, "t2", "running", { description: "Rerun full make check", task_type: "local_bash" }),
  task(6, "t3", "running", { description: "spec review", task_type: "local_agent" }),
  task(7, "t3", "completed"),
  task(8, "t4", "running", { description: "lint", task_type: "local_bash" }),
  task(9, "t4", "stopped"),
];
const tasks = () => backgroundTasks(items.reduce(reduceTranscript, initialTranscript()));

describe("backgroundTasks", () => {
  it("splits the running tasks, oldest first, from the ended ones, latest ended first", () => {
    const { running, done } = tasks();

    expect(running.map((row) => row.label)).toEqual([
      "reviewer · quality review",
      "Rerun full make check",
    ]);
    expect(running[0]?.call?.running.map((call) => call.label)).toEqual(["cost"]);
    expect(done.map((row) => [row.label, row.task.status])).toEqual([
      ["lint", "stopped"],
      ["spec review", "completed"],
    ]);
  });
});

describe("BackgroundChip", () => {
  it("counts the running tasks, else the ended ones, and hides with none", () => {
    const { rerender, container } = render(
      <BackgroundChip tasks={tasks()} open={false} onToggle={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Background tasks, 2 running" })).toBeInTheDocument();

    rerender(
      <BackgroundChip
        tasks={{ running: [], done: tasks().done }}
        open={false}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Background tasks, 2 done" })).toBeInTheDocument();

    rerender(<BackgroundChip tasks={{ running: [], done: [] }} open={false} onToggle={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("BackgroundPanel", () => {
  it("lists the running tasks with an agent's calls, and the ended ones folded", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<BackgroundPanel tasks={tasks()} onClose={onClose} />);
    expect(screen.getByRole("heading", { name: "Background tasks" })).toHaveFocus();

    const running = screen.getByRole("region", { name: "Running" });
    expect(within(running).getByText("Rerun full make check")).toBeInTheDocument();
    await user.click(within(running).getByRole("button", { name: /quality review/ }));
    expect(within(running).getByText("cost")).toBeInTheDocument();

    expect(screen.queryByText("lint")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Completed 2/ }));
    expect(screen.getByText("lint")).toBeInTheDocument();
    expect(screen.getByText("stopped")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("BackgroundPanel stop", () => {
  it("stops a running task and waits for its end, saying so when the stop fails", async () => {
    const user = userEvent.setup();
    const onStop = vi.fn().mockRejectedValueOnce(new Error("lost")).mockResolvedValue({});
    render(<BackgroundPanel tasks={tasks()} onClose={vi.fn()} onStop={onStop} />);

    const stop = screen.getByRole("button", { name: "Stop Rerun full make check" });
    await user.click(stop);
    expect(onStop).toHaveBeenCalledWith("t2");
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not stop it");

    await user.click(stop);
    expect(stop).toBeDisabled();
  });

  it("offers no stop without a way to stop", () => {
    render(<BackgroundPanel tasks={tasks()} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /^Stop / })).toBeNull();
  });
});
