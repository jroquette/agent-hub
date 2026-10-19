import { describe, expect, it } from "vitest";

import { aLogRecord } from "../../testing/builders";
import { elapsed, liveActivity, turnSteps } from "./liveActivity";
import {
  initialTranscript,
  reduceTranscript,
  type StreamItem,
  type TranscriptState,
} from "./model";

const record = (...args: Parameters<typeof aLogRecord>): StreamItem => ({
  type: "record",
  record: aLogRecord(...args),
});

function run(items: StreamItem[]): TranscriptState {
  return items.reduce(reduceTranscript, initialTranscript());
}

const running: StreamItem = { type: "status", status: { status: "running" } };
const message = record("user.message", { seq: 1, body: { text: "go" } });
const call = (seq: number, id: string, name: string, input: object, parent?: string) =>
  record("tool.call", {
    seq,
    body: { tool_use_id: id, name, input, ...(parent ? { parent_tool_use_id: parent } : {}) },
  });

describe("liveActivity", () => {
  it("is null while no turn runs", () => {
    expect(liveActivity(run([message]))).toBeNull();
  });

  it("reads thinking when a turn runs with no call open", () => {
    const activity = liveActivity(run([message, running]));
    expect(activity?.phase).toBe("thinking");
    expect(activity?.turnStartedAt).not.toBeNull();
  });

  it("lists the running calls, latest first, with a subagent's own calls nested", () => {
    const state = run([
      message,
      running,
      call(2, "a", "Agent", { subagent_type: "Explore", description: "find cost code" }),
      call(3, "b", "Bash", { command: "make test" }),
      call(4, "c", "Grep", { pattern: "cost" }, "a"),
    ]);
    const activity = liveActivity(state);
    expect(activity?.phase).toBe("subagents");
    expect(activity?.calls.map((c) => c.id)).toEqual(["b", "a"]);
    const agent = activity?.calls[1];
    expect(agent?.label).toBe("Explore · find cost code");
    expect(agent?.running.map((c) => c.label)).toEqual(["cost"]);
    expect(agent?.calls).toBe(1);
  });

  it("drops a call once its result arrives", () => {
    const state = run([
      message,
      running,
      call(2, "b", "Bash", { command: "ls" }),
      record("tool.result", { seq: 3, body: { tool_use_id: "b", content: "ok" } }),
    ]);
    expect(liveActivity(state)?.calls).toEqual([]);
  });

  it("reads waiting for you while a permission is open", () => {
    const state = run([message, { type: "status", status: { status: "waiting_permission" } }]);
    expect(liveActivity(state)?.phase).toBe("waiting");
  });
});

describe("background agents", () => {
  const idle: StreamItem = { type: "status", status: { status: "idle" } };
  const task = (seq: number, id: string, status: string, extra: object = {}) =>
    record("task", { seq, body: { task_id: id, status, ...extra } });
  const launched = [
    message,
    running,
    call(2, "a", "Agent", { subagent_type: "reviewer", description: "quality review" }),
    task(3, "t1", "running", { description: "quality review", tool_use_id: "a" }),
    record("tool.result", { seq: 4, body: { tool_use_id: "a", content: "launched" } }),
    task(5, "t2", "running", { description: "spec review" }),
    record("result", { seq: 6, body: { subtype: "success" } }),
    idle,
  ];

  it("reads an idle session with agents still running as working in the background", () => {
    const activity = liveActivity(run(launched));
    expect(activity?.phase).toBe("background");
    expect(activity?.calls.map((c) => c.label)).toEqual([
      "spec review",
      "reviewer · quality review",
    ]);
    expect(activity?.turnStartedAt).toBe(activity?.calls[1]?.startedAt);
  });

  it("is null again once every background agent ended", () => {
    const state = run([...launched, task(7, "t1", "completed"), task(8, "t2", "stopped")]);
    expect(liveActivity(state)).toBeNull();
  });

  it("forgets the agents when the process exits", () => {
    const state = run([...launched, record("exited", { seq: 7, body: { code: 0 } })]);
    expect(liveActivity(state)).toBeNull();
  });
});

describe("turn feed", () => {
  it("lists the turn's calls with the first lines of their output and how many more", () => {
    const output = ["a", "b", "c", "d", "e", "f"].join("\n");
    const state = run([
      message,
      running,
      call(2, "b", "Bash", { command: "ls" }),
      record("tool.result", { seq: 3, body: { tool_use_id: "b", content: output } }),
      call(4, "r", "Read", { file_path: "x.py" }),
      record("tool.result", { seq: 5, body: { tool_use_id: "r", content: "1\n2\n3" } }),
    ]);
    const feed = liveActivity(state)?.feed ?? [];
    expect(feed.map((item) => item.kind === "tool" && item.summary)).toEqual(["ls", "x.py"]);
    const [bash, read] = feed;
    expect(bash?.kind === "tool" && [bash.state, bash.preview, bash.more]).toEqual([
      "done",
      ["a", "b", "c", "d"],
      2,
    ]);
    expect(read?.kind === "tool" && read.preview).toEqual(["Read 3 lines"]);
  });

  it("nests a subagent's calls under it", () => {
    const state = run([
      message,
      running,
      call(2, "a", "Agent", { description: "explore" }),
      ...[3, 4, 5, 6].map((seq) => call(seq, `c${String(seq)}`, "Grep", { pattern: "p" }, "a")),
    ]);
    const agent = liveActivity(state)?.feed[0];
    expect(agent?.kind === "tool" && [agent.children.length, agent.childCount]).toEqual([4, 4]);
  });

  it("starts at the turn's message, not at an earlier turn's", () => {
    const state = run([
      record("user.message", { seq: 1, body: { text: "first" } }),
      call(2, "old", "Bash", { command: "old" }),
      record("tool.result", { seq: 3, body: { tool_use_id: "old", content: "" } }),
      record("result", { seq: 4, body: {} }),
      record("user.message", { seq: 5, body: { text: "second" } }),
      running,
      call(6, "new", "Bash", { command: "new" }),
    ]);
    const feed = liveActivity(state)?.feed ?? [];
    expect(feed.map((item) => item.key)).toEqual(["new"]);
  });
});

describe("turnSteps", () => {
  it("keeps the last turn's steps once it finished, and how long it took", () => {
    const state = run([
      message,
      running,
      call(2, "b", "Bash", { command: "ls" }),
      record("tool.result", { seq: 3, body: { tool_use_id: "b", content: "ok" } }),
      record("result", { seq: 4, body: {} }),
      { type: "status", status: { status: "idle" } },
    ]);
    const steps = turnSteps(state);
    expect([steps.activity, steps.end, steps.feed.length]).toEqual([null, "finished", 1]);
    expect(steps.tookMs).not.toBeNull();
  });

  it("has no turn before the first message", () => {
    expect(turnSteps(run([])).end).toBeNull();
  });
});

describe("elapsed", () => {
  it("reads seconds, minutes and hours", () => {
    expect(elapsed(8_400)).toBe("8 s");
    expect(elapsed(125_000)).toBe("2 min 05 s");
    expect(elapsed(3_780_000)).toBe("1 h 03 min");
  });
});
