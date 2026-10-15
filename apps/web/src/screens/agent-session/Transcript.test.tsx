import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { aDeltaFrame, aLogRecord } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { CostMeter } from "./CostMeter";
import { TodoList } from "./TodoList";
import { FIRST_ENTRIES, Transcript } from "./Transcript";
import { initialTranscript, reduceTranscript, type StreamItem } from "./transcript";

/** Renders of Markdown (each parses its source) and of tool cards. */
const renders = vi.hoisted(() => ({ markdown: 0, tool: 0 }));
vi.mock("../../components/Markdown", async (original) => {
  const real = await original<typeof import("../../components/Markdown")>();
  return {
    ...real,
    Markdown: (props: Parameters<typeof real.Markdown>[0]) => {
      renders.markdown += 1;
      return real.Markdown(props);
    },
  };
});
vi.mock("./ToolCallCard", async (original) => {
  const real = await original<typeof import("./ToolCallCard")>();
  return {
    ...real,
    ToolCallCard: (props: Parameters<typeof real.ToolCallCard>[0]) => {
      renders.tool += 1;
      return real.ToolCallCard(props);
    },
  };
});

/** A scripted stream: a message, thinking, two deltas, an Edit and its result, todos, a result. */
function scripted(extra: StreamItem[] = []): StreamItem[] {
  return [
    { type: "record", record: aLogRecord("user.message", { seq: 1 }) },
    { type: "record", record: aLogRecord("thinking", { seq: 2 }) },
    { type: "delta", delta: aDeltaFrame({ after_seq: 2, index: 0, text: "Hello **bold** " }) },
    {
      type: "delta",
      delta: aDeltaFrame({ after_seq: 2, index: 1, text: "<img src=x onerror=alert(1)>" }),
    },
    { type: "record", record: aLogRecord("tool.call", { seq: 3 }) },
    { type: "record", record: aLogRecord("tool.result", { seq: 4 }) },
    { type: "record", record: aLogRecord("todos", { seq: 5 }) },
    { type: "record", record: aLogRecord("result", { seq: 6 }) },
    ...extra,
  ];
}

function show(items: StreamItem[]) {
  const state = items.reduce(reduceTranscript, initialTranscript());
  const view = render(
    <>
      <Transcript state={state} />
      <TodoList items={state.todos} />
      <CostMeter meter={state.meter} />
    </>,
  );
  return { state, ...view };
}

describe("Transcript (transcript)", () => {
  it("appends deltas to one assistant bubble and renders markdown without raw HTML", () => {
    const { container } = show(scripted());

    const bubble = screen.getByRole("article", { name: "Claude" });
    expect(within(bubble).getByText("bold").tagName).toBe("STRONG");
    expect(bubble).toHaveTextContent("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Run the tests.")).toBeInTheDocument();
  });

  it("collapses thinking when it arrives", () => {
    show(scripted());

    expect(screen.getByText("Check the failing test first.")).not.toBeVisible();
    expect(screen.getByText("Thinking").closest("details")).not.toHaveAttribute("open");
  });

  it("expands a tool call to its diff and result when clicked and collapses it again", async () => {
    show(scripted());

    const head = screen.getByRole("button", { name: /Edit src\/app\.py/ });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("edited")).toBeNull();

    await userEvent.click(head);

    expect(head).toHaveAttribute("aria-expanded", "true");
    const diff = screen.getByLabelText("Diff of src/app.py");
    expect(diff.tagName).toBe("PRE");
    expect(diff).toHaveTextContent("--- a/src/app.py");
    expect(within(diff).getByText("-a = 1")).toHaveClass("as-diff-del");
    expect(within(diff).getByText("+a = 2")).toHaveClass("as-diff-add");
    expect(screen.getByText("edited")).toBeInTheDocument();

    await userEvent.click(head);
    expect(screen.queryByText("edited")).toBeNull();
  });

  it("updates the todo list and the cost meter labelled estimate", () => {
    show(scripted());

    const todos = screen.getByRole("region", { name: "Todo list" });
    expect(todos).toHaveTextContent("Fix the test");
    expect(todos).toHaveTextContent("0 of 1 done");
    const meter = screen.getByRole("group", { name: "Cost and tokens (estimate)" });
    expect(meter).toHaveTextContent("$0.0012");
    expect(meter).toHaveTextContent("12 in");
    expect(meter).toHaveTextContent("5 out");
    expect(meter).toHaveTextContent("estimate");
  });

  it("labels replayed text as the stored, redacted copy", () => {
    show([
      {
        type: "record",
        record: aLogRecord("text", { seq: 1, body: { block: 0, text: "key [redacted: lin-key]" } }),
      },
    ]);

    expect(screen.getByText("stored copy, redacted")).toBeInTheDocument();
  });

  it("nests a subagent's calls under the calling tool and shows notices", () => {
    show([
      {
        type: "record",
        record: aLogRecord("tool.call", {
          seq: 1,
          body: { tool_use_id: "t1", name: "Task", input: { description: "Scan the repo" } },
        }),
      },
      {
        type: "record",
        record: aLogRecord("tool.call", {
          seq: 2,
          body: {
            tool_use_id: "t2",
            name: "Bash",
            input: { command: "ls" },
            parent_tool_use_id: "t1",
          },
        }),
      },
      { type: "record", record: aLogRecord("error", { seq: 3 }) },
    ]);

    const nested = screen.getByRole("list", { name: "Calls made by Task" });
    expect(within(nested).getByRole("button", { name: /Bash ls/ })).toBeInTheDocument();
    expect(screen.getByText("claude exited with code 1")).toBeInTheDocument();
  });

  it("shows a pending permission card inline and posts its answer with the request id", async () => {
    const onAnswer = vi.fn(() => Promise.resolve());
    const state = [{ type: "record", record: aLogRecord("permission.request", { seq: 1 }) }]
      .map((item) => item as StreamItem)
      .reduce(reduceTranscript, initialTranscript());
    render(<Transcript state={state} onAnswerPermission={onAnswer} />);

    await userEvent.click(screen.getByRole("button", { name: "Allow once" }));

    expect(onAnswer).toHaveBeenCalledWith("req-1", { decision: "allow" });
  });

  it("marks the region polite and busy while a block streams (a11y)", async () => {
    const { container } = show(scripted().slice(0, 4));

    const log = screen.getByRole("log", { name: "Conversation" });
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-busy", "true");
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("invites the first message when the transcript is empty", () => {
    render(<Transcript state={initialTranscript()} />);

    expect(screen.getByText(/No messages yet/)).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "false");
  });
});

describe("Transcript (streaming-batch) working row", () => {
  const running: StreamItem = { type: "status", status: { status: "running" } };
  const call: StreamItem = { type: "record", record: aLogRecord("tool.call", { seq: 1 }) };
  const result: StreamItem = { type: "record", record: aLogRecord("tool.result", { seq: 2 }) };
  const delta: StreamItem = { type: "delta", delta: aDeltaFrame({ after_seq: 2, block: 1 }) };
  const row = () => screen.queryByRole("status");

  it.each([
    ["a running tool", [running, call], "Claude is working · Edit"],
    ["a finished tool", [running, call, result], "Claude is working"],
    ["streaming text", [running, call, result, delta], ""],
    ["an idle session", [call], ""],
    ["a waiting permission", [{ type: "status", status: { status: "waiting_permission" } }], ""],
  ] as const)("shows the working row for %s only while running with no text", (_, items, text) => {
    render(<Transcript state={items.reduce(reduceTranscript, initialTranscript())} />);

    expect(row()).toHaveTextContent(new RegExp(`^${text}$`));
  });

  it("keeps one status region mounted while live and changes only its text (a11y)", () => {
    const idle: StreamItem = { type: "status", status: { status: "idle" } };
    const ended: StreamItem = { type: "status", status: { status: "ended" } };
    const steps = [[idle], [running], [delta], [idle]].reduce<StreamItem[][]>(
      (acc, items) => [...acc, [...(acc.at(-1) ?? []), ...items]],
      [],
    );
    const at = (items: StreamItem[]) => items.reduce(reduceTranscript, initialTranscript());
    const { rerender } = render(<Transcript state={at(steps[0] ?? [])} />);
    const region = row();

    const texts = steps.map((items) => {
      rerender(<Transcript state={at(items)} />);
      expect(row()).toBe(region);
      return row()?.textContent;
    });
    rerender(<Transcript state={at([...(steps.at(-1) ?? []), ended])} />);

    expect(texts).toEqual(["", "Claude is working", "", ""]);
    expect(row()).toBeNull();
  });

  it("shows a caret on the streaming bubble only", () => {
    render(<Transcript state={[running, delta].reduce(reduceTranscript, initialTranscript())} />);

    const bubble = screen.getByRole("article", { name: "Claude" });
    expect(bubble.querySelector(".as-caret")).toHaveAttribute("aria-hidden", "true");
  });
});

// Building and fully rendering 2,000 entries takes seconds in jsdom; only the first render is timed.
describe("Transcript (long-transcript)", { timeout: 30_000 }, () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  /** Animation frames run when the test says so. */
  function manualFrames() {
    let due: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => due.push(callback));
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
    return () => {
      const run = due;
      due = [];
      act(() => {
        for (const callback of run) callback(0);
      });
    };
  }

  /** 2,000 entries: a message, a reply and a tool call per turn, then `last`. */
  function longState(last: StreamItem) {
    const items: StreamItem[] = [];
    for (let seq = 1; seq < 2000; seq += 3) {
      items.push(
        { type: "record", record: aLogRecord("user.message", { seq }) },
        {
          type: "record",
          record: aLogRecord("text", { seq: seq + 1, body: { text: `Reply ${String(seq)}` } }),
        },
        {
          type: "record",
          record: aLogRecord("tool.call", {
            seq: seq + 2,
            body: { tool_use_id: `t${String(seq)}`, name: "Bash", input: { command: "ls" } },
          }),
        },
      );
    }
    return [...items, last].reduce(reduceTranscript, initialTranscript());
  }
  const delta = (index: number, text: string): StreamItem => ({
    type: "delta",
    delta: aDeltaFrame({ after_seq: 2001, block: 1, index, text }),
  });

  it("renders 2,000 entries in under a second and a delta re-renders only the streaming entry", () => {
    const runFrame = manualFrames();
    const state = longState(delta(0, "Wor"));
    expect(state.entries).toHaveLength(2002);

    const started = performance.now();
    const view = render(<Transcript state={state} />);
    expect(performance.now() - started).toBeLessThan(1000);
    const log = screen.getByRole("log");
    expect(log.children).toHaveLength(FIRST_ENTRIES);
    expect(log).toHaveAttribute("aria-busy", "true");
    runFrame();
    expect(log.children).toHaveLength(2002);

    renders.markdown = 0;
    renders.tool = 0;
    view.rerender(<Transcript state={reduceTranscript(state, delta(1, "king"))} />);

    expect(renders).toEqual({ markdown: 1, tool: 0 });
    const streaming = screen.getAllByRole("article", { name: "Claude" }).at(-1);
    expect(streaming).toHaveTextContent("Working");
    expect(streaming?.querySelector(".as-caret")).not.toBeNull();
    expect(streaming?.parentElement).not.toHaveClass("as-settled");
    expect(screen.getAllByRole("article", { name: "Claude" })[0]?.parentElement).toHaveClass(
      "as-settled",
    );
  });

  it("first renders from the oldest pending card and keeps it in view as earlier entries come", () => {
    const runFrame = manualFrames();
    const request = aLogRecord("permission.request", { seq: 2002 });
    const state = longState({ type: "record", record: request });
    const moved = { ...state, entries: [...state.entries] };
    const card = moved.entries.pop();
    if (!card) throw new Error("no card");
    moved.entries.splice(100, 0, card);
    // 10 px per entry shown; the card sits at its index, the scroller writes are recorded.
    const shown = () => document.querySelectorAll(".as-entry").length;
    vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(() => shown() * 10);
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.dataset.requestId ? (shown() - 1902) * 10 + 1000 : 0;
    });
    const top = { value: 0 };
    vi.spyOn(Element.prototype, "scrollTop", "get").mockImplementation(() => top.value);
    vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation((value) => {
      top.value = value;
    });
    const follow = { atBottom: false, pin: vi.fn(), release: vi.fn() };

    render(<Transcript state={moved} follow={follow} />);
    expect(screen.getByRole("log").children).toHaveLength(1902);
    expect(top.value).toBe(984);
    runFrame();

    expect(screen.getByRole("log").children).toHaveLength(2002);
    expect(top.value).toBe(1984);
  });
});

describe("Transcript (sending-feedback)", () => {
  it("shows a sent message as Sending… and a queued one with when Claude reads it", () => {
    show([
      { type: "record", record: aLogRecord("user.message", { seq: 1 }) },
      { type: "record", record: aLogRecord("user.message", { seq: 2, body: { text: "Also" } }) },
      { type: "sending", key: "s-1", text: "One more" },
    ]);

    const sending = screen.getByText("One more").closest(".as-msg");
    expect(sending).toHaveTextContent("Sending…");
    expect(screen.getByText("Also").closest(".as-msg")).toHaveTextContent(
      "Queued: Claude reads it after this turn",
    );
    expect(screen.getByText("Run the tests.").closest(".as-msg")).not.toHaveTextContent("Queued");
  });
});
