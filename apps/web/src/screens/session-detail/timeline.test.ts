import { describe, expect, it } from "vitest";

import { aTimelineEvent, at, manyEvents, type TimelineEventBody } from "../../testing/builders";
import {
  LONG_SESSION_EVENTS,
  buildTrace,
  flattenTrace,
  minimapOf,
  renderParts,
  searchable,
  type TraceEvent,
  type TraceGroup,
  type TraceLane,
} from "./timeline";

let seq = 0;
function ev(
  type: TimelineEventBody["type"],
  payload: TimelineEventBody["payload"],
  extra: Partial<TimelineEventBody> = {},
) {
  seq += 1;
  return aTimelineEvent({ seq, timestamp: at(seq), type, payload, ...extra });
}

function eventsOf(items: readonly unknown[]): TraceEvent[] {
  return items.filter((item): item is TraceEvent => (item as { kind?: string }).kind === "event");
}

describe("buildTrace", () => {
  it("merges a tool result into its call when both share a tool use id", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Bash", command: "make check-fast", tool_use_id: "t1" }),
      ev("tool.result", {
        tool: "Bash",
        status: "ok",
        exit_code: 0,
        duration_ms: 192000,
        tool_use_id: "t1",
      }),
    ]);

    const [row] = eventsOf(trace.turns[0]?.items ?? []);
    expect(row).toMatchObject({
      cat: "tool",
      tool: "Bash",
      text: "make check-fast",
      exit: 0,
      durationS: 192,
    });
    expect(trace.total).toBe(1);
  });

  it("shows a failed call as an error row with its first error line when the result is an error", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "t1" }),
      ev("tool.result", {
        tool: "Bash",
        status: "error",
        exit_code: 2,
        error_line: "3 failed",
        tool_use_id: "t1",
      }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? [])[0]).toMatchObject({
      cat: "error",
      label: "Tool result · error",
      note: "3 failed",
      exit: 2,
    });
  });

  it("shows a denied call as a guard row when the guard denies it", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Bash", command: "git push origin main", tool_use_id: "t1" }),
      ev("tool.result", {
        tool: "Bash",
        status: "denied",
        rule: "no push to main",
        hook: "guard",
        tool_use_id: "t1",
      }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? [])[0]).toMatchObject({
      cat: "guard",
      label: "Denied by guard",
      text: "git push origin main",
      note: "rule: no push to main",
    });
    expect(trace.counts.guard).toBe(1);
  });

  it("drops conflict losers and usage carriers when building rows", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Read", path: "a.py", tool_use_id: "t1" }),
      ev(
        "tool.call",
        { tool: "Read", path: "a.py", tool_use_id: "t1" },
        { conflict: true, source: "transcript" },
      ),
      ev(
        "message",
        { role: "assistant", chars: 0, message_id: "m1", input_tokens: 10 },
        { source: "transcript" },
      ),
    ]);

    expect(trace.total).toBe(1);
  });

  it("starts a new turn at each prompt and keeps hook and transcript copies of a prompt as one when they arrive together", () => {
    const trace = buildTrace([
      ev("session.start", { trigger: "startup", model: "claude-model-a" }),
      ev("message", { role: "user", chars: 40 }),
      ev("message", { role: "user", chars: 40, turn: 1 }, { source: "transcript" }),
      ev("tool.call", { tool: "Read", path: "a.py", tool_use_id: "t1" }),
      ev("message", { role: "user", chars: 12 }),
      ev("message", { role: "assistant", chars: 300 }, { source: "transcript" }),
    ]);

    expect(trace.turns.map((turn) => turn.n)).toEqual([1, 2]);
    expect(eventsOf(trace.turns[0]?.items ?? []).map((row) => row.cat)).toEqual([
      "lifecycle",
      "prompt",
      "tool",
    ]);
    expect(eventsOf(trace.turns[1]?.items ?? []).map((row) => row.cat)).toEqual([
      "prompt",
      "message",
    ]);
  });

  it("groups consecutive reads and searches in one turn and lane when there are two or more", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Read", path: "brain/features/x/spec.md", tool_use_id: "a" }),
      ev("tool.call", { tool: "Read", path: "brain/features/x/plan.md", tool_use_id: "b" }),
      ev("tool.call", {
        tool: "Grep",
        pattern: "AC-48",
        path: "brain/features/x",
        tool_use_id: "c",
      }),
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "d" }),
    ]);

    const [group, bash] = trace.turns[0]?.items ?? [];
    expect(group).toMatchObject({
      kind: "group",
      summary: "Read 2 files, searched 1 time in brain/features/x/",
    });
    expect((group as TraceGroup).items).toHaveLength(3);
    expect(bash).toMatchObject({ kind: "event", tool: "Bash" });
  });

  it("pulls an error out of a group when a read fails", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Read", path: "a/x.py", tool_use_id: "a" }),
      ev("tool.call", { tool: "Read", path: "a/y.py", tool_use_id: "b" }),
      ev("tool.result", {
        tool: "Read",
        status: "error",
        error_line: "no such file",
        tool_use_id: "b",
      }),
      ev("tool.call", { tool: "Read", path: "a/z.py", tool_use_id: "c" }),
    ]);

    expect((trace.turns[0]?.items ?? []).map((item) => item.kind)).toEqual([
      "event",
      "event",
      "event",
    ]);
  });

  it("gathers a subagent's events into one contiguous lane when they carry its agent id", () => {
    const trace = buildTrace([
      ev("tool.call", {
        tool: "Agent",
        subagent_type: "quality-reviewer",
        description: "Review",
        tool_use_id: "a",
      }),
      ev(
        "tool.call",
        { tool: "Read", path: "x.py", tool_use_id: "s1", agent_id: "sub1" },
        { agent: "quality-reviewer" },
      ),
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "m1" }),
      ev(
        "message",
        { role: "assistant", chars: 20, agent_id: "sub1" },
        { agent: "quality-reviewer", source: "transcript" },
      ),
      ev("tool.result", { tool: "Agent", status: "ok", tool_use_id: "a", duration_ms: 64000 }),
    ]);

    const items = trace.turns[0]?.items ?? [];
    expect(items.map((item) => item.kind)).toEqual(["event", "lane", "event"]);
    const lane = items[1] as TraceLane;
    expect(lane).toMatchObject({ id: "sub1", agent: "quality-reviewer", eventCount: 2 });
    expect(trace.lanes).toEqual([{ id: "sub1", agent: "quality-reviewer" }]);
  });

  it("resolves a guard ask as approved when its tool ran", () => {
    const trace = buildTrace([
      ev("gate.request", {
        gate_id: "t9",
        kind: "guard_ask",
        path: "docs/adr/0009.md",
        rule: "ask_before_edit",
      }),
      ev("tool.result", { tool: "Edit", status: "ok", tool_use_id: "t9" }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? [])[0]).toMatchObject({
      cat: "guard",
      label: "Guard asks",
      text: "docs/adr/0009.md needs approval",
      note: "approved in terminal",
    });
  });

  it("shows a blocked Stop as a guard row when the stop gate fails", () => {
    const trace = buildTrace([
      ev("gate.result", {
        gate_id: "g1",
        kind: "stop_gate",
        command: "make check-fast",
        exit_code: 2,
        result: "failed",
      }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? [])[0]).toMatchObject({
      cat: "guard",
      label: "Stop blocked",
      text: "make check-fast",
      exit: 2,
    });
  });

  it("describes messages and reasoning by size, never by content", () => {
    const trace = buildTrace([
      ev("message", { role: "user", chars: 1240, slash_command: "/feature" }),
      ev("reasoning", { chars: 88, turn: 1 }, { source: "transcript" }),
    ]);

    const [prompt, reasoning] = eventsOf(trace.turns[0]?.items ?? []);
    expect(prompt).toMatchObject({
      label: "Prompt · /feature",
      text: "1,240 characters",
      content: { role: "user", chars: 1240 },
    });
    expect(reasoning).toMatchObject({
      label: "Recorded reasoning summary",
      content: { chars: 88 },
    });
  });

  it("labels later session starts as resumed segments", () => {
    const trace = buildTrace([
      ev("session.start", { trigger: "startup" }),
      ev("session.end", { end_reason: "clear", outcome: null }),
      ev("session.start", { trigger: "resume" }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? []).map((row) => row.label)).toEqual([
      "Session started",
      "Session ended",
      "Session resumed · segment 2",
    ]);
  });

  it("covers the other event kinds with a row each", () => {
    const trace = buildTrace([
      ev("decision", { text: "Keep the line match" }),
      ev("learning.proposed", { text: "Compare render impact", target: "brain/learnings/" }),
      ev("gate.request", { gate_id: "g2", kind: "plan", name: "plan" }),
      ev("gate.result", { gate_id: "g2", kind: "plan", name: "plan", result: "passed" }),
      ev("gate.request", { gate_id: "g3", kind: "permission" }),
      ev("step.start", { run: "r1", stage: "IMPLEMENTING" }, { step: "implement" }),
      ev("step.end", { run: "r1", status: "ok" }, { step: "implement" }),
      ev("run.end", { run: "r1", status: "failed" }),
      ev("tool.call", { tool: "WebFetch", url: "https://example.com/a", tool_use_id: "w" }),
      ev("tool.call", {
        tool: "mcp__linear__get_issue",
        mcp_server: "linear",
        mcp_tool: "get_issue",
        tool_use_id: "m",
      }),
      ev("tool.call", {
        tool: "Write",
        path: "brain/_inbox/n.md",
        lines_added: 12,
        tool_use_id: "x",
      }),
      ev("tool.call", { tool: "Glob", pattern: "**/*.py", tool_use_id: "g" }),
      ev("tool.result", { tool: "Bash", status: "ok", tool_use_id: "orphan" }),
      ev("session.summary", { lines: [] }),
    ]);

    const rows = eventsOf(trace.turns[0]?.items ?? []);
    expect(rows.map((row) => row.label)).toEqual([
      "Decision",
      "Learning proposed",
      "Gate",
      "Permission prompt",
      "Step implement started",
      "Step implement ended",
      "Run ended",
      "Tool call",
      "Tool call",
      "Tool call",
      "Tool call",
      "Tool result",
    ]);
    expect(rows[2]?.note).toBe("passed");
    expect(rows[3]?.note).toBe("waiting");
    expect(rows[8]).toMatchObject({ tool: "MCP", text: "linear.get_issue" });
    expect(rows[9]).toMatchObject({ plus: 12, text: "brain/_inbox/n.md" });
  });
});

describe("searchable", () => {
  it("never matches a redaction marker when the text holds one", () => {
    expect(searchable("curl -H [redacted: github token] x")).toBe("curl -h  x");
  });
});

describe("renderParts", () => {
  it("splits text into plain parts and redaction kinds when markers are present", () => {
    expect(renderParts("a [redacted: github token] b")).toEqual([
      { text: "a " },
      { redacted: "github token" },
      { text: " b" },
    ]);
  });
});

describe("flattenTrace", () => {
  it("collapses turns beyond the first and last three when the session is long", () => {
    const trace = buildTrace(manyEvents(LONG_SESSION_EVENTS));
    const rows = flattenTrace(trace, { long: true });

    const summaries = rows.filter((row) => row.t === "turnSummary");
    expect(summaries).toHaveLength(trace.turns.length - 6);
    expect(rows.length).toBeLessThan(trace.turns.length + 120);
  });

  it("keeps errors, guard rows, decisions and lifecycle with a hidden divider when only errors and decisions are asked for", () => {
    const trace = buildTrace([
      ev("session.start", {}),
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "1" }),
      ev("tool.call", { tool: "Bash", command: "pwd", tool_use_id: "2" }),
      ev("decision", { text: "Keep it" }),
    ]);

    const rows = flattenTrace(trace, { errorsOnly: true });
    expect(rows.map((row) => row.t)).toEqual(["turn", "event", "hidden", "event"]);
    expect(rows[2]).toMatchObject({ count: 2 });
  });

  it("returns the matching event ids and opens their group when searching", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Read", path: "a/x.py", tool_use_id: "a" }),
      ev("tool.call", { tool: "Read", path: "a/needle.py", tool_use_id: "b" }),
      ev("tool.call", { tool: "Bash", command: "echo needle", tool_use_id: "c" }),
    ]);

    const rows = flattenTrace(trace, { query: "needle" });
    expect(rows.filter((row) => row.t === "event").length).toBe(2);
    expect(rows.find((row) => row.t === "group")).toMatchObject({ open: true });
  });

  it("filters by type and tool and lane when facets are chosen", () => {
    const trace = buildTrace([
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "1" }),
      ev("message", { role: "assistant", chars: 3 }),
      ev(
        "tool.call",
        { tool: "Read", path: "x", tool_use_id: "2", agent_id: "s" },
        { agent: "reviewer" },
      ),
    ]);

    expect(
      flattenTrace(trace, { types: new Set(["message"]) }).filter((row) => row.t === "event"),
    ).toHaveLength(1);
    expect(
      flattenTrace(trace, { tools: new Set(["Bash"]) }).filter((row) => row.t === "event"),
    ).toHaveLength(1);
    const laneOnly = flattenTrace(trace, { lanes: new Set(["s"]), openLanes: new Set(["s"]) });
    expect(laneOnly.map((row) => row.t)).toEqual(["turn", "hidden", "lane", "event"]);
  });

  it("shows a gap divider when two rows are more than two minutes apart", () => {
    const trace = buildTrace([
      aTimelineEvent({
        seq: 1,
        timestamp: at(0),
        type: "tool.call",
        payload: { tool: "Bash", command: "a" },
      }),
      aTimelineEvent({
        seq: 2,
        timestamp: at(400),
        type: "tool.call",
        payload: { tool: "Bash", command: "b" },
      }),
    ]);

    expect(flattenTrace(trace, {}).map((row) => row.t)).toEqual(["turn", "event", "gap", "event"]);
  });
});

describe("minimapOf", () => {
  it("bins events by time and marks errors, guard and decisions with their own kinds", () => {
    const trace = buildTrace([
      aTimelineEvent({ seq: 1, timestamp: at(0), type: "decision", payload: { text: "d" } }),
      aTimelineEvent({
        seq: 2,
        timestamp: at(50),
        type: "tool.call",
        payload: { tool: "Bash", command: "x", tool_use_id: "1" },
      }),
      aTimelineEvent({
        seq: 3,
        timestamp: at(51),
        type: "tool.result",
        payload: { tool: "Bash", status: "denied", tool_use_id: "1" },
      }),
      aTimelineEvent({
        seq: 4,
        timestamp: at(100),
        type: "tool.call",
        payload: { tool: "Bash", command: "y", tool_use_id: "2" },
      }),
      aTimelineEvent({
        seq: 5,
        timestamp: at(101),
        type: "tool.result",
        payload: { tool: "Bash", status: "error", tool_use_id: "2" },
      }),
    ]);

    const map = minimapOf(trace, "time", 10);
    expect(map.bins).toHaveLength(10);
    expect(map.marks.map((mark) => mark.kind)).toEqual(["decision", "guard", "error"]);
    expect(map.marks[2]?.at).toBeCloseTo(1, 1);
    expect(minimapOf(trace, "turn", 4).bins).toHaveLength(4);
  });
});
