import { describe, expect, it } from "vitest";

import {
  aTimelineEvent,
  anActor,
  at,
  manyEvents,
  type TimelineEventBody,
} from "../../testing/builders";
import {
  LONG_SESSION_EVENTS,
  buildTrace,
  flattenTrace,
  lineOf,
  minimapOf,
  renderParts,
  rowIdOf,
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

function flatLines(rows: ReturnType<typeof flattenTrace>): string[] {
  return rows.flatMap((row) => {
    if (row.t === "event") return [`${"  ".repeat(row.depth)}${lineOf(row.row)}`];
    if (row.t === "lane")
      return [
        `lane ${row.lane.actor.label}${row.lane.description ? `: ${row.lane.description}` : ""}`,
      ];
    if (row.t === "group") return [`${"  ".repeat(row.depth)}group ${row.group.summary}`];
    return [row.t];
  });
}

function subagentSession() {
  const skill = ev("tool.call", {
    tool: "Skill",
    skill: "hub-workflow:feature",
    tool_use_id: "sk",
  });
  const agent = ev("tool.call", {
    tool: "Agent",
    subagent_type: "Explore",
    description: "map the collector",
    tool_use_id: "ag",
  });
  const read = ev(
    "tool.call",
    { tool: "Read", path: "packages/collector/src/x.py", tool_use_id: "r1", agent_id: "sub1" },
    { agent: "Explore" },
  );
  const main = ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "b1" });
  const done = ev("tool.result", { tool: "Agent", status: "ok", tool_use_id: "ag" });
  return { events: [skill, agent, read, main, done], agent };
}

describe("actors", () => {
  it("names the main agent and nests a subagent's rows under the Agent call that started it when the session links them", () => {
    const { events, agent } = subagentSession();
    const trace = buildTrace(events, [
      anActor(),
      anActor({
        kind: "subagent",
        agent_id: "sub1",
        type: "Explore",
        description: "map the collector",
        started_by_event_id: agent.event_id,
      }),
    ]);

    expect(flatLines(flattenTrace(trace, {}))).toEqual([
      "turn",
      "Main agent · Ran skill /feature",
      "Main agent · Started subagent Explore: map the collector",
      "lane Subagent · Explore: map the collector",
      "  Subagent · Explore · Read packages/collector/src/x.py",
      "Main agent · Ran `make check`",
    ]);
    const lane = trace.turns[0]?.items.find((item) => item.kind === "lane");
    expect(lane).toMatchObject({ startedBy: agent.event_id, agent: "Explore" });
  });

  it("links a subagent to the only matching Agent call when the session has no actors", () => {
    const { events, agent } = subagentSession();
    const trace = buildTrace(events);

    const lane = trace.turns[0]?.items.find((item) => item.kind === "lane");
    expect(lane).toMatchObject({ startedBy: agent.event_id, description: "map the collector" });
    expect(trace.turns[0]?.items.map((item) => item.kind)).toEqual([
      "event",
      "event",
      "lane",
      "event",
    ]);
  });

  it("leaves a subagent unlinked when two Agent calls of its type could have started it", () => {
    const events = [
      ev("tool.call", {
        tool: "Agent",
        subagent_type: "Explore",
        description: "a",
        tool_use_id: "a1",
      }),
      ev("tool.call", {
        tool: "Agent",
        subagent_type: "Explore",
        description: "b",
        tool_use_id: "a2",
      }),
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "b" }),
      ev(
        "tool.call",
        { tool: "Read", path: "x.py", tool_use_id: "r", agent_id: "sub9" },
        { agent: "Explore" },
      ),
    ];
    const trace = buildTrace(events);

    const lane = trace.turns[0]?.items[3];
    expect(lane).toMatchObject({ kind: "lane", startedBy: null, description: null });
    expect((lane as TraceLane).actor.label).toBe("Subagent · Explore");
  });

  it("names you as the actor of a prompt and the run as the actor of its steps", () => {
    const trace = buildTrace([
      ev("message", { role: "user", chars: 40, slash_command: "/feature" }),
      ev("step.start", { run: "r1", stage: "IMPLEMENTING" }, { step: "implement" }),
      ev("session.start", { trigger: "startup", model: "claude-model-a" }, { agent: "main" }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? []).map(lineOf)).toEqual([
      "You · Prompted /feature (40 characters)",
      "Workflow run · Started step implement",
      "Main agent · Started the session in agent-hub · claude-model-a",
    ]);
  });

  it("finds the row of an event id when the id is a result folded into its call", () => {
    const call = ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "t1" });
    const result = ev("tool.result", { tool: "Bash", status: "error", tool_use_id: "t1" });
    const trace = buildTrace([call, result]);

    expect(rowIdOf(trace, result.event_id)).toBe(call.event_id);
    expect(rowIdOf(trace, call.event_id)).toBe(call.event_id);
    expect(rowIdOf(trace, "nope")).toBeNull();
  });
});

describe("grouping", () => {
  function busySession(): TimelineEventBody[] {
    const reads = Array.from({ length: 12 }, (_, i) =>
      ev("tool.call", { tool: "Read", path: `pkg/f${String(i)}.py`, tool_use_id: `r${String(i)}` }),
    );
    return [
      ...reads,
      ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "b" }),
      ev("tool.result", { tool: "Bash", status: "error", exit_code: 2, tool_use_id: "b" }),
      ev("gate.request", { gate_id: "g", kind: "plan", name: "plan" }),
      ev("gate.result", { gate_id: "g", kind: "plan", name: "plan", result: "passed" }),
      ev("tool.call", { tool: "Bash", command: "git push", tool_use_id: "d" }),
      ev("tool.result", { tool: "Bash", status: "denied", rule: "no-push", tool_use_id: "d" }),
      ev("tool.call", { tool: "Skill", skill: "review", tool_use_id: "s" }),
      ev("tool.call", { tool: "Agent", subagent_type: "reviewer", tool_use_id: "a" }),
      ev(
        "tool.call",
        { tool: "Read", path: "x.py", tool_use_id: "x", agent_id: "q" },
        { agent: "reviewer" },
      ),
      ev("learning.proposed", { text: "Run the gate first" }),
    ];
  }

  it("collapses twelve reads into one expandable row and never collapses errors, gates, guards, skills, subagents or learnings by default", () => {
    const rows = flattenTrace(buildTrace(busySession()), {});

    expect(flatLines(rows)).toEqual([
      "turn",
      "group Read 12 files in pkg/",
      "Main agent · Ran `make check`",
      "Main agent · Gate plan passed",
      "Main agent · Guard blocked Bash (rule no-push)",
      "Main agent · Ran skill /review",
      "Main agent · Started subagent reviewer",
      "lane Subagent · reviewer",
      "  Subagent · reviewer · Read x.py",
      "Main agent · Proposed a learning: Run the gate first",
    ]);
    expect(rows.find((row) => row.t === "group")).toMatchObject({ open: false });
  });

  it("keeps errors, guards and learnings of a collapsed long-session turn and of a closed lane on show", () => {
    seq = 0;
    const events: TimelineEventBody[] = [];
    for (let turn = 1; turn <= 8; turn += 1) {
      events.push(ev("message", { role: "user", chars: 5 }));
      events.push(
        ev("tool.call", {
          tool: "Bash",
          command: `step ${String(turn)}`,
          tool_use_id: `c${String(turn)}`,
        }),
      );
      if (turn === 4) {
        events.push(ev("tool.result", { tool: "Bash", status: "error", tool_use_id: "c4" }));
        events.push(
          ev(
            "tool.call",
            { tool: "Grep", pattern: "x", tool_use_id: "g", agent_id: "q" },
            { agent: "reviewer" },
          ),
        );
        events.push(
          ev("learning.proposed", { text: "In a lane", agent_id: "q" }, { agent: "reviewer" }),
        );
      }
    }
    const trace = buildTrace(events);
    const lines = flatLines(flattenTrace(trace, { long: true, closedLanes: new Set(["q"]) }));

    const at4 = lines.indexOf("turnSummary", 3);
    expect(lines.slice(at4, at4 + 4)).toEqual([
      "turnSummary",
      "Main agent · Ran `step 4`",
      "lane Subagent · reviewer",
      "  Subagent · reviewer · Proposed a learning: In a lane",
    ]);
    expect(lines).not.toContain('  Subagent · reviewer · Searched for "x"');

    const open = flatLines(
      flattenTrace(trace, { openTurns: new Set([4]), long: true, closedLanes: new Set(["q"]) }),
    );
    expect(open).toContain("lane Subagent · reviewer");
    expect(open).toContain("  Subagent · reviewer · Proposed a learning: In a lane");
    expect(open).not.toContain('  Subagent · reviewer · Searched for "x"');
  });
});

describe("verbs", () => {
  it("phrases one row per verb with its actor when the session has one event of each", () => {
    const trace = buildTrace([
      ev("message", { role: "user", chars: 40, slash_command: "/feature" }),
      ev("tool.call", { tool: "Read", path: "a/spec.md", tool_use_id: "1" }),
      ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "2" }),
      ev("tool.call", {
        tool: "Edit",
        path: "a/x.py",
        lines_added: 3,
        lines_removed: 1,
        tool_use_id: "3",
      }),
      ev("tool.call", { tool: "Write", path: "a/y.py", lines_added: 9, tool_use_id: "4" }),
      ev("tool.call", { tool: "Grep", pattern: "AC-48", tool_use_id: "5" }),
      ev("tool.call", { tool: "Bash", command: "ls", tool_use_id: "6" }),
      ev("tool.call", { tool: "Glob", pattern: "**/*.md", tool_use_id: "7" }),
      ev("tool.call", { tool: "WebFetch", url: "https://example.com/", tool_use_id: "8" }),
      ev("tool.call", {
        tool: "mcp__linear__get_issue",
        mcp_server: "linear",
        mcp_tool: "get_issue",
        tool_use_id: "9",
      }),
      ev("tool.call", { tool: "Skill", skill: "feature", tool_use_id: "10" }),
      ev("tool.call", {
        tool: "Agent",
        subagent_type: "Explore",
        description: "map it",
        tool_use_id: "11",
      }),
      ev("gate.request", { gate_id: "g", kind: "check", name: "check-fast" }),
      ev("gate.result", {
        gate_id: "g",
        kind: "check",
        name: "check-fast",
        result: "failed",
        exit_code: 2,
      }),
      ev("tool.call", { tool: "Bash", command: "git push origin main", tool_use_id: "12" }),
      ev("tool.result", {
        tool: "Bash",
        status: "denied",
        rule: "no-push-main",
        tool_use_id: "12",
      }),
      ev("learning.proposed", { text: "Run make check before the PR" }),
      ev("gate.request", { gate_id: "13", kind: "guard_ask", path: "docs/adr/0009.md" }),
      ev("gate.result", {
        gate_id: "s",
        kind: "stop_gate",
        command: "make check-fast",
        result: "failed",
      }),
      ev("decision", { text: "Keep the line match" }),
      ev("session.end", { outcome: "done", end_reason: "other" }),
    ]);

    expect(eventsOf(trace.turns[0]?.items ?? []).map(lineOf)).toEqual([
      "You · Prompted /feature (40 characters)",
      "Main agent · Read a/spec.md",
      "Main agent · Ran `make check`",
      "Main agent · Edited a/x.py (+3 −1)",
      "Main agent · Wrote a/y.py (+9)",
      'Main agent · Searched for "AC-48"',
      "Main agent · Ran `ls`",
      'Main agent · Listed files matching "**/*.md"',
      "Main agent · Fetched https://example.com/",
      "Main agent · Called linear.get_issue",
      "Main agent · Ran skill /feature",
      "Main agent · Started subagent Explore: map it",
      "Main agent · Gate check-fast failed",
      "Main agent · Guard blocked Bash (rule no-push-main)",
      "Main agent · Proposed a learning: Run make check before the PR",
      "Main agent · Guard asked you to approve a change to docs/adr/0009.md",
      "Main agent · Blocked the stop: `make check-fast` failing",
      "Main agent · Decided: Keep the line match",
      "Main agent · Ended the session: done · other",
    ]);
  });
});
