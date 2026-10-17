import { describe, expect, it } from "vitest";

import { aLogRecord } from "../../testing/builders";
import { elapsed, liveActivity } from "./liveActivity";
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

describe("elapsed", () => {
  it("reads seconds, minutes and hours", () => {
    expect(elapsed(8_400)).toBe("8 s");
    expect(elapsed(125_000)).toBe("2 min 05 s");
    expect(elapsed(3_780_000)).toBe("1 h 03 min");
  });
});
