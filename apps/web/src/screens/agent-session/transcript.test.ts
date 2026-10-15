import { describe, expect, it } from "vitest";

import {
  aDeltaFrame,
  aLogRecord,
  aPermissionRequest,
  anAgentSession,
} from "../../testing/builders";
import {
  applySnapshot,
  initialTranscript,
  keepSending,
  pendingPermissions,
  reduceTranscript,
  ruleLabel,
  toolDiff,
  toolSummary,
  unifiedDiff,
  type StreamItem,
  type TranscriptState,
} from "./transcript";

const record = (...args: Parameters<typeof aLogRecord>): StreamItem => ({
  type: "record",
  record: aLogRecord(...args),
});
const delta = (overrides: Parameters<typeof aDeltaFrame>[0]): StreamItem => ({
  type: "delta",
  delta: aDeltaFrame(overrides),
});

function run(items: StreamItem[], from: TranscriptState = initialTranscript()): TranscriptState {
  return items.reduce(reduceTranscript, from);
}

describe("reduceTranscript (transcript)", () => {
  it("appends deltas to one assistant bubble when they share a block", () => {
    const state = run([
      record("user.message", { seq: 1 }),
      delta({ after_seq: 1, block: 0, index: 0, text: "Hel" }),
      delta({ after_seq: 1, block: 0, index: 1, text: "lo **there**" }),
    ]);

    const bubbles = state.entries.filter((entry) => entry.kind === "assistant");
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toMatchObject({ text: "Hello **there**", streaming: true });
    expect(state.streaming).toBe(true);
  });

  it("replaces the streamed bubble with the text record when the block completes", () => {
    const state = run([
      delta({ after_seq: 1, block: 0, index: 0, text: "Hel" }),
      record("text", { seq: 2, body: { block: 0, text: "Hello, done." } }),
    ]);

    const bubbles = state.entries.filter((entry) => entry.kind === "assistant");
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]).toMatchObject({ text: "Hello, done.", streaming: false, seq: 2 });
    expect(state.streaming).toBe(false);
    expect(state.lastSeq).toBe(2);
  });

  it("ignores a replayed delta or record when it was already applied", () => {
    const once = run([
      record("user.message", { seq: 1 }),
      delta({ after_seq: 1, block: 0, index: 0, text: "A" }),
      delta({ after_seq: 1, block: 0, index: 1, text: "B" }),
    ]);
    const twice = run(
      [
        record("user.message", { seq: 1 }),
        delta({ after_seq: 1, block: 0, index: 1, text: "B" }),
        delta({ after_seq: 0, block: 0, index: 5, text: "stale" }),
      ],
      once,
    );

    expect(twice.entries.filter((entry) => entry.kind === "user")).toHaveLength(1);
    expect(twice.entries.find((entry) => entry.kind === "assistant")).toMatchObject({ text: "AB" });
  });

  it("starts a new bubble when the next block streams", () => {
    const state = run([
      record("text", { seq: 1, body: { block: 0, text: "First." } }),
      delta({ after_seq: 1, block: 1, index: 0, text: "Sec" }),
    ]);

    expect(
      state.entries.filter((entry) => entry.kind === "assistant").map((entry) => entry.text),
    ).toEqual(["First.", "Sec"]);
  });

  it("keeps thinking, todos and user messages when those records arrive", () => {
    const state = run([
      record("user.message", { seq: 1, body: { text: "Fix it." } }),
      record("thinking", { seq: 2 }),
      record("todos", {
        seq: 3,
        body: {
          items: [
            { content: "Read", status: "completed", active_form: null },
            { content: "Fix", status: "in_progress", active_form: "Fixing" },
          ],
        },
      }),
    ]);

    expect(state.entries.map((entry) => entry.kind)).toEqual(["user", "thinking"]);
    expect(state.todos).toEqual([
      { content: "Read", status: "completed", activeForm: null },
      { content: "Fix", status: "in_progress", activeForm: "Fixing" },
    ]);
  });

  it("pairs a tool result with its call and nests a subagent's call under its parent", () => {
    const state = run([
      record("tool.call", {
        seq: 1,
        body: { tool_use_id: "toolu_task", name: "Task", input: { description: "Scan" } },
      }),
      record("tool.call", {
        seq: 2,
        body: {
          tool_use_id: "toolu_read",
          name: "Read",
          input: { file_path: "a.py" },
          parent_tool_use_id: "toolu_task",
        },
      }),
      record("tool.result", {
        seq: 3,
        body: {
          tool_use_id: "toolu_read",
          content: "x".repeat(10),
          is_error: false,
          truncated: true,
          original_bytes: 70000,
        },
      }),
    ]);

    expect(state.entries.filter((entry) => entry.kind === "tool")).toHaveLength(1);
    expect(state.children.toolu_task).toEqual(["toolu_read"]);
    expect(state.tools.toolu_read?.result).toEqual({
      content: "xxxxxxxxxx",
      isError: false,
      truncated: true,
      originalBytes: 70000,
    });
  });

  it("adds up cost and tokens when turn results arrive", () => {
    const state = run([record("result", { seq: 1 }), record("result", { seq: 2 })]);

    expect(state.meter).toEqual({
      costUsd: 0.0024,
      usage: { input: 24, output: 10, cache_read: 0, cache_write: 0 },
      turns: 2,
    });
  });

  it("records a decision on the request when the permission is answered", () => {
    const state = run([
      record("permission.request", { seq: 1 }),
      record("permission.decision", {
        seq: 2,
        by: "timeout",
        body: { request_id: "req-1", decision: "deny" },
      }),
    ]);

    expect(state.permissions["req-1"]?.decision).toMatchObject({ decision: "deny", by: "timeout" });
    expect(pendingPermissions(state)).toEqual([]);
  });

  it("marks text as a stored copy when it holds a redaction marker", () => {
    const state = run([
      record("text", { seq: 1, body: { block: 0, text: "token [redacted: github-token]" } }),
    ]);

    expect(state.entries[0]).toMatchObject({ kind: "assistant", redacted: true });
  });

  it("turns audit and driver records into notices when they are not chat content", () => {
    const state = run([
      record("init", { seq: 1 }),
      record("settings", { seq: 2, body: { mode: "plan", model: "opus" } }),
      record("interrupt", { seq: 3 }),
      record("error", { seq: 4 }),
      record("log.truncated", { seq: 5 }),
      record("exited", { seq: 6, body: { code: 1 } }),
      record("close", { seq: 7 }),
    ]);

    expect(state.model).toBe("opus");
    expect(state.slashCommands).toEqual(["/feature"]);
    expect(
      state.entries.map((entry) => (entry.kind === "notice" ? entry.text : entry.kind)),
    ).toEqual([
      "Session started (model sonnet)",
      "Mode set to Plan, model set to opus",
      "You interrupted the turn",
      "claude exited with code 1",
      "The log is full (50,000 records): resume the session to continue",
      "claude exited with code 1",
      "Session closed",
    ]);
  });

  it("follows the status frames and starts over when the stream resets", () => {
    const running = run([
      record("user.message", { seq: 1 }),
      { type: "status", status: { status: "running", end_reason: null } },
    ]);
    expect(running.status).toBe("running");

    const reset = reduceTranscript(running, { type: "reset", reset: { reason: "unknown id" } });
    expect(reset.entries).toEqual([]);
    expect(reset.reset).toBe("unknown id");
  });
});

describe("applySnapshot (transcript)", () => {
  it("shows the raw open request from memory when the stored one is redacted", () => {
    const stored = run([
      record("permission.request", {
        seq: 1,
        body: {
          request_id: "req-1",
          request_kind: "tool",
          summary: "echo [redacted: github-token]",
          tool: "Bash",
          suggestions: [],
        },
      }),
    ]);
    const state = applySnapshot(
      stored,
      anAgentSession({
        status: "waiting_permission",
        open_permission: aPermissionRequest({ summary: "echo live-value" }),
      }),
    );

    expect(state.status).toBe("waiting_permission");
    expect(state.permissions["req-1"]).toMatchObject({
      summary: "echo live-value",
      redacted: false,
      deadlineAt: aPermissionRequest().deadline_at,
    });
    expect(state.entries.filter((entry) => entry.kind === "permission")).toHaveLength(1);
    expect(pendingPermissions(state)).toEqual(["req-1"]);
  });

  it("adds the open request when the log page has not reached it yet", () => {
    const state = applySnapshot(
      initialTranscript(),
      anAgentSession({ open_permission: aPermissionRequest() }),
    );

    expect(state.entries).toEqual([{ kind: "permission", key: "perm-req-1", requestId: "req-1" }]);
  });
});

describe("tool helpers (transcript)", () => {
  it("builds a unified diff when Edit replaces a string", () => {
    expect(unifiedDiff("src/app.py", "a = 1\nb = 2", "a = 1\nb = 3")).toBe(
      [
        "--- a/src/app.py",
        "+++ b/src/app.py",
        "@@ -1,2 +1,2 @@",
        " a = 1",
        "-b = 2",
        "+b = 3",
      ].join("\n"),
    );
  });

  it("shows a Write as all added lines and prefers the server's diff when given", () => {
    const write = toolDiff({
      id: "t",
      name: "Write",
      input: { file_path: "n.md", content: "x\ny" },
      parentId: null,
      diff: null,
      result: null,
    });
    expect(write).toBe(["--- /dev/null", "+++ b/n.md", "@@ -0,0 +1,2 @@", "+x", "+y"].join("\n"));

    expect(
      toolDiff({
        id: "t",
        name: "Edit",
        input: {},
        parentId: null,
        diff: "--- a/x\n+++ b/x",
        result: null,
      }),
    ).toBe("--- a/x\n+++ b/x");
    expect(
      toolDiff({ id: "t", name: "Bash", input: {}, parentId: null, diff: null, result: null }),
    ).toBeNull();
  });

  it("summarises a tool call by its most telling input", () => {
    expect(toolSummary({ command: "make check" })).toBe("make check");
    expect(toolSummary({ file_path: "src/a.py" })).toBe("src/a.py");
    expect(toolSummary({ pattern: "TODO" })).toBe("TODO");
    expect(toolSummary({ query: "q", n: 1 })).toBe("q");
    expect(toolSummary({ n: 1 })).toBe("");
    expect(toolSummary({ command: "x".repeat(300) })).toHaveLength(120);
  });

  it("names a suggested rule by its tool and content", () => {
    expect(
      ruleLabel({
        type: "addRules",
        rules: [{ toolName: "Bash", ruleContent: "git status" }],
        destination: "localSettings",
      }),
    ).toBe("Bash(git status)");
    expect(ruleLabel({ type: "setMode", mode: "acceptEdits" })).toBe("setMode acceptEdits");
    expect(ruleLabel("odd")).toBe("odd");
  });
});

describe("reduceTranscript (stop)", () => {
  const notices = (state: TranscriptState) =>
    state.entries.flatMap((entry) => (entry.kind === "notice" ? [entry.text] : []));
  const aborted = { body: { subtype: "error_during_execution", terminal_reason: "aborted_tools" } };

  it("follows an interrupted turn's result with one Turn interrupted notice", () => {
    const state = run([
      record("interrupt", { seq: 1 }),
      record("result", { seq: 2 }),
      record("result", { seq: 3 }),
      record("interrupt", { seq: 4 }),
      record("result", { seq: 5, ...aborted }),
      record("result", { seq: 6, ...aborted }),
    ]);

    expect(notices(state)).toEqual([
      "You interrupted the turn",
      "Turn interrupted",
      "You interrupted the turn",
      "Turn interrupted",
      "Turn interrupted",
    ]);
  });

  it("forgets an interrupt that landed on an idle session once the next message is sent", () => {
    const state = run([
      record("user.message", { seq: 1 }),
      record("result", { seq: 2 }),
      record("interrupt", { seq: 3 }),
      record("user.message", { seq: 4 }),
      record("result", { seq: 5 }),
    ]);

    expect(notices(state)).toEqual(["You interrupted the turn"]);
  });

  it("closes a bubble an interrupt cut short, so no caret stays", () => {
    const state = run([
      delta({ after_seq: 0, block: 0, index: 0, text: "Half a" }),
      record("interrupt", { seq: 1 }),
      record("result", { seq: 2, ...aborted }),
    ]);

    expect(state.entries[0]).toMatchObject({ kind: "assistant", text: "Half a", streaming: false });
  });
});

describe("reduceTranscript (sending-feedback)", () => {
  const sending = (key: string, text: string): StreamItem => ({ type: "sending", key, text });
  const accepted = (key: string, seq: number): StreamItem => ({ type: "accepted", key, seq });
  const user = (seq: number, text = "Next") => record("user.message", { seq, body: { text } });
  const users = (state: TranscriptState) =>
    state.entries.flatMap((entry) => (entry.kind === "user" ? [[entry.text, entry.queued]] : []));

  it("shows a sent message at once and swaps it for the echoed record of its seq", () => {
    const shown = run([sending("a", "Hi"), sending("b", "Again"), accepted("a", 3)]);
    expect(shown.sending).toEqual([
      { key: "a", text: "Hi", seq: 3 },
      { key: "b", text: "Again", seq: null },
    ]);

    const echoed = run([user(2, "Other"), user(3, "Hi")], shown);
    expect(echoed.sending.map((send) => send.key)).toEqual(["b"]);
  });

  it("drops a sent message whose record arrived before the answer to its POST", () => {
    const state = run([sending("a", "Hi"), user(3, "Hi"), accepted("a", 3)]);

    expect(state.sending).toEqual([]);
    expect(users(state)).toEqual([["Hi", false]]);
  });

  it("drops a sent message that failed", () => {
    const state = run([sending("a", "Hi"), { type: "failed", key: "a" }]);

    expect(state.sending).toEqual([]);
  });

  it("keeps the sent messages a reloaded log lacks", () => {
    const previous = run([sending("a", "A"), sending("b", "B"), sending("c", "C")]);
    const before = run([accepted("b", 5), accepted("c", 6)], previous);

    const kept = keepSending(before, run([user(5, "B")]));
    expect(kept.sending.map((send) => send.key)).toEqual(["a", "c"]);
  });

  it("keeps sent messages through a reset", () => {
    const state = run([sending("a", "Hi"), { type: "reset", reset: { reason: "gone" } }]);

    expect(state.sending).toHaveLength(1);
  });

  it("queues a message sent while a turn runs until that turn's result", () => {
    const queued = run([user(1, "First"), user(2, "Second")]);
    expect(users(queued)).toEqual([
      ["First", false],
      ["Second", true],
    ]);

    // Claude reads it in the next turn, which runs until its own result.
    const next = run([record("result", { seq: 3 }), user(4, "Third")], queued);
    expect(users(next)).toEqual([
      ["First", false],
      ["Second", false],
      ["Third", true],
    ]);
    const done = run([record("result", { seq: 5 }), record("result", { seq: 6 }), user(7)], next);
    expect(users(done).at(-1)).toEqual(["Next", false]);
  });

  it.each([
    [
      "an idle status",
      (s: TranscriptState) => run([{ type: "status", status: { status: "idle" } }], s),
    ],
    [
      "an idle snapshot",
      (s: TranscriptState) => applySnapshot(s, anAgentSession({ status: "idle" })),
    ],
  ])("ends the turn on %s", (_, end) => {
    const state = end(run([user(1), user(2)]));

    expect(users(state)).toEqual([
      ["Next", false],
      ["Next", false],
    ]);
    expect(users(run([user(3)], state)).at(-1)).toEqual(["Next", false]);
  });
});
