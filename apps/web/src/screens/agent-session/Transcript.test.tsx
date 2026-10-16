import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { aDeltaFrame, aLogRecord, at } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { CostMeter } from "./CostMeter";
import { TodoList } from "./TodoList";
import { FIRST_ENTRIES, Transcript } from "./Transcript";
import { initialTranscript, reduceTranscript, type StreamItem } from "./model";

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

const SHOT = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";
const withShot = (seq: number): StreamItem => ({
  type: "record",
  record: aLogRecord("user.message", {
    seq,
    body: {
      text: "What is on this screen?",
      attachments: [{ kind: "screenshot", media_type: "image/png", bytes: 16 }],
    },
  }),
});

describe("Transcript (screenshot-thumbnail)", () => {
  it("screenshot-thumbnail: the copy shows as an image under the message", () => {
    const state = [withShot(1)].reduce(reduceTranscript, initialTranscript());
    render(<Transcript state={state} screenshotUrl={SHOT} />);

    expect(screen.getByRole("img", { name: "Screenshot sent with this message" })).toHaveAttribute(
      "src",
      SHOT,
    );
    expect(screen.queryByText("Screenshot attached")).toBeNull();
  });

  it("screenshot-thumbnail: without the copy (after a reload) the label shows", () => {
    const state = [withShot(1)].reduce(reduceTranscript, initialTranscript());
    const { container } = render(<Transcript state={state} />);

    expect(screen.getByText("Screenshot attached")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("screenshot-thumbnail: a message without the marker shows neither", () => {
    const state = scripted().reduce(reduceTranscript, initialTranscript());
    const { container } = render(<Transcript state={state} screenshotUrl={SHOT} />);

    expect(screen.queryByText("Screenshot attached")).toBeNull();
    expect(container.querySelector("img.as-shot")).toBeNull();
  });
});

describe("Transcript (pasted-images)", () => {
  const twoShots = (seq: number): StreamItem => ({
    type: "record",
    record: aLogRecord("user.message", {
      seq,
      body: {
        text: "Compare these.",
        attachments: [
          { kind: "screenshot", media_type: "image/png", bytes: 16 },
          { kind: "screenshot", media_type: "image/png", bytes: 20 },
        ],
      },
    }),
  });

  it("shows a later message's own images, never the first prompt's screenshot", () => {
    const state = [withShot(1), twoShots(2)].reduce(reduceTranscript, initialTranscript());
    render(
      <Transcript
        state={state}
        screenshotUrl={SHOT}
        messageScreenshots={{ 2: ["data:image/png;base64,A", "data:image/png;base64,B"] }}
      />,
    );

    expect(screen.getByRole("img", { name: "Screenshot sent with this message" })).toHaveAttribute(
      "src",
      SHOT,
    );
    expect(
      screen
        .getAllByRole("img", { name: /^Image \d sent with this message$/ })
        .map((img) => img.getAttribute("src")),
    ).toEqual(["data:image/png;base64,A", "data:image/png;base64,B"]);
  });

  it("says how many images went with a message whose copies this browser lacks", () => {
    const state = [withShot(1), twoShots(2)].reduce(reduceTranscript, initialTranscript());
    render(<Transcript state={state} screenshotUrl={SHOT} />);

    expect(screen.getByText("2 images attached")).toBeInTheDocument();
  });

  it("shows the images of a message while it sends", () => {
    const state = reduceTranscript(initialTranscript(), {
      type: "sending",
      key: "send-1",
      text: "Look.",
      screenshots: ["data:image/png;base64,P"],
    });
    render(<Transcript state={state} />);

    expect(screen.getByRole("img", { name: "Screenshot sent with this message" })).toHaveAttribute(
      "src",
      "data:image/png;base64,P",
    );
    expect(screen.getByText("Sending…")).toBeInTheDocument();
  });
});

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
    expect(screen.getByText("Thought for 1 s").closest("details")).not.toHaveAttribute("open");
  });

  it("keeps a tool call out of the conversation, one line that opens it in the side panel", async () => {
    show(scripted());

    expect(screen.queryByRole("button", { name: /Edit src\/app\.py/ })).toBeNull();
    const line = screen.getByRole("button", { name: "Edited 1 file" });
    expect(line).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(line);

    expect(line).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByRole("complementary", { name: "Activity" });
    expect(screen.getByRole("heading", { name: "Activity" })).toHaveFocus();
    expect(within(panel).getByRole("button", { name: /Edit src\/app\.py/ })).toBeInTheDocument();
  });

  it("closes the side panel on Esc, Close or its line again, focus back on the line", async () => {
    show(scripted());
    const line = screen.getByRole("button", { name: "Edited 1 file" });

    await userEvent.click(line);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Activity" })).toBeNull();
    expect(line).toHaveFocus();

    await userEvent.click(line);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("complementary", { name: "Activity" })).toBeNull();
    expect(line).toHaveFocus();

    await userEvent.click(line);
    await userEvent.click(line);
    expect(screen.queryByRole("complementary", { name: "Activity" })).toBeNull();
  });

  it("expands a tool call in the side panel to its diff and result and collapses it again", async () => {
    show(scripted());
    await userEvent.click(screen.getByRole("button", { name: "Edited 1 file" }));

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
    act(() => {
      screen.getByRole("button", { name: "1 subagent" }).click();
    });

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
    manualFrames();
    const state = longState(delta(0, "Wor"));
    expect(state.entries).toHaveLength(2002);
    // A first mount warms the module and JIT caches up, so the budget times the render alone.
    render(<Transcript state={state} />).unmount();
    const runFrame = manualFrames();

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

  it("first renders from the tool call an attached pending card shows under (tool-cards)", () => {
    manualFrames();
    const request = aLogRecord("permission.request", {
      seq: 2002,
      body: { request_id: "t301", tool: "Bash", request_kind: "tool", summary: "ls" },
    });

    render(<Transcript state={longState({ type: "record", record: request })} />);

    // t301 is entry 302 of 2,002; its card leaves its own place for the call's.
    expect(screen.getByRole("log").children).toHaveLength(2002 - 302 - 1);
    const card = document.querySelector("[data-request-id='t301']");
    expect(card?.closest(".as-entry")?.querySelector(".as-activity-head")).toHaveTextContent(
      "Ran 1 command",
    );
  });

  it("keeps a run's node when its earlier calls join it a frame later (tool-cards)", () => {
    const runFrame = manualFrames();
    const items: StreamItem[] = [{ type: "record", record: aLogRecord("text", { seq: 1 }) }];
    for (let seq = 2; seq < 2 + FIRST_ENTRIES + 100; seq += 1) {
      items.push({
        type: "record",
        record: aLogRecord("tool.call", {
          seq,
          body: { tool_use_id: `t${String(seq)}`, name: "Read", input: { file_path: "a" } },
        }),
      });
    }

    render(<Transcript state={items.reduce(reduceTranscript, initialTranscript())} />);
    const log = screen.getByRole("log");
    const head = within(log).getByRole("button", { name: /^Read \d+ files/ });
    expect(head).toHaveTextContent(`Read ${String(FIRST_ENTRIES)} files`);
    expect(log.children).toHaveLength(1);
    runFrame();

    expect(log.children).toHaveLength(2);
    expect(within(log).getByRole("button", { name: /^Read \d+ files/ })).toBe(head);
    expect(head).toHaveTextContent(`Read ${String(FIRST_ENTRIES + 100)} files`);
  });

  it("first renders at most FIRST_ENTRIES calls of a long run that waits for you, its card kept (tool-cards)", () => {
    const runFrame = manualFrames();
    const items: StreamItem[] = [{ type: "record", record: aLogRecord("text", { seq: 1 }) }];
    for (let seq = 2; seq < 2002; seq += 1) {
      items.push({
        type: "record",
        record: aLogRecord("tool.call", {
          seq,
          body: { tool_use_id: `t${String(seq)}`, name: "Bash", input: { command: "ls" } },
        }),
      });
    }
    const request = aLogRecord("permission.request", {
      seq: 2002,
      body: { request_id: "t2001", tool: "Bash", request_kind: "tool", summary: "ls" },
    });
    items.push({ type: "record", record: request });

    render(<Transcript state={items.reduce(reduceTranscript, initialTranscript())} />);
    const log = screen.getByRole("log");
    const head = within(log).getByRole("button", { name: /^Ran \d+ commands/ });
    const card = document.querySelector("[data-request-id='t2001']");
    expect(Number(/Ran (\d+) commands/.exec(head.textContent)?.[1])).toBeLessThanOrEqual(
      FIRST_ENTRIES,
    );
    expect(log.querySelectorAll(".as-tool")).toHaveLength(0);
    expect(card).not.toBeNull();
    runFrame();

    expect(head).toHaveTextContent("Ran 2000 commands");
    expect(within(log).getByRole("button", { name: /^Ran \d+ commands/ })).toBe(head);
    expect(document.querySelector("[data-request-id='t2001']")).toBe(card);
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

describe("Transcript (tool-cards) attached permission", () => {
  const call = (seq: number, id: string, name = "Bash"): StreamItem => ({
    type: "record",
    record: aLogRecord("tool.call", {
      seq,
      body: { tool_use_id: id, name, input: { command: "make check" } },
    }),
  });
  const ask = (seq: number, id: string): StreamItem => ({
    type: "record",
    record: aLogRecord("permission.request", {
      seq,
      body: { request_id: id, tool: "Bash", request_kind: "tool", summary: "make check" },
    }),
  });
  const text = (seq: number): StreamItem => ({
    type: "record",
    record: aLogRecord("text", { seq, body: { block: 0, text: "Between" } }),
  });

  it("renders the permission card under its run's line; the call reads Waiting for you", async () => {
    show([call(1, "toolu_9"), text(2), ask(3, "toolu_9")]);

    const line = screen.getByRole("button", { name: "Ran 1 command" });
    const card = document.querySelector("[data-request-id='toolu_9']");
    expect(card?.closest(".as-entry")).toBe(line.closest(".as-entry"));
    expect(line.nextElementSibling).toBe(card);
    expect(screen.getByRole("log").children).toHaveLength(2);

    await userEvent.click(line);
    const panel = screen.getByRole("complementary", { name: "Activity" });
    expect(
      within(panel).getByRole("button", { name: "Bash make check (Waiting for you)" }),
    ).toBeInTheDocument();
    expect(panel.querySelector("[data-request-id]")).toBeNull();
  });

  it("keeps a permission with no matching call where it arrived", () => {
    show([call(1, "toolu_9"), text(2), ask(3, "req-other")]);

    const log = screen.getByRole("log");
    expect(log.children).toHaveLength(3);
    expect(log.lastElementChild?.querySelector("[data-request-id='req-other']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Ran 1 command" })).toBeInTheDocument();
  });

  it("reads the call a live run is on, then the run's summary once it ends", () => {
    const running: StreamItem = { type: "status", status: { status: "running" } };
    const { rerender } = render(
      <Transcript state={[running, call(1, "a")].reduce(reduceTranscript, initialTranscript())} />,
    );
    expect(screen.getByRole("button", { name: "Bash make check" })).toBeInTheDocument();

    rerender(<Transcript state={[call(1, "a")].reduce(reduceTranscript, initialTranscript())} />);
    expect(screen.getByRole("button", { name: "Ran 1 command" })).toBeInTheDocument();
  });

  it("groups calls and the thoughts between them into one run; text starts a new run", () => {
    const thought = (seq: number): StreamItem => ({
      type: "record",
      record: aLogRecord("thinking", { seq }),
    });
    show([
      thought(1),
      call(2, "a", "Read"),
      thought(3),
      call(4, "b", "Grep"),
      call(5, "c", "Read"),
      text(6),
      thought(7),
      text(8),
      call(9, "d"),
    ]);

    const log = screen.getByRole("log");
    expect(log.children).toHaveLength(5);
    expect(
      within(log).getByRole("button", { name: /^Read 2 files, 1 search, thought/ }),
    ).toHaveAttribute("aria-expanded", "false");
    // A thought with no call beside it stays where it is.
    expect(log.children[2]?.querySelector("details.as-thinking")).not.toBeNull();
    expect(log.lastElementChild).toHaveTextContent("Ran 1 command");
  });

  it("opens a group whose call waits for you, its card under the call, where the chat opens", () => {
    const state = [
      call(1, "a", "Read"),
      call(2, "b"),
      ask(3, "b"),
      call(4, "c", "Read"),
      text(5),
      ask(6, "req-later"),
    ].reduce(reduceTranscript, initialTranscript());
    // Each card its own offset: opening on the wrong one lands elsewhere.
    const offsets: Record<string, number> = { b: 400, "req-later": 900 };
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (
      this: HTMLElement,
    ) {
      return offsets[this.dataset.requestId ?? ""] ?? 0;
    });
    const top = { value: 0 };
    vi.spyOn(Element.prototype, "scrollTop", "set").mockImplementation((value) => {
      top.value = value;
    });

    render(
      <Transcript state={state} follow={{ atBottom: false, pin: vi.fn(), release: vi.fn() }} />,
    );

    const log = screen.getByRole("log");
    expect(log.children).toHaveLength(3);
    const line = within(log).getByRole("button", { name: "Read 2 files, ran 1 command" });
    expect(line.nextElementSibling).toHaveAttribute("data-request-id", "b");
    expect(top.value).toBe(384);
    vi.restoreAllMocks();
  });

  it("keeps the panel and an expanded call, the same node with the focus, when a call joins the run", async () => {
    const one = [call(1, "a")].reduce(reduceTranscript, initialTranscript());
    const { rerender } = render(<Transcript state={one} />);
    await userEvent.click(screen.getByRole("button", { name: "Ran 1 command" }));
    const head = screen.getByRole("button", { name: "Bash make check (Running)" });
    await userEvent.click(head);
    expect(head).toHaveAttribute("aria-expanded", "true");

    rerender(<Transcript state={reduceTranscript(one, call(2, "b", "Read"))} />);

    expect(screen.getByRole("button", { name: "Ran 1 command, read 1 file" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getAllByRole("button", { name: "Bash make check (Running)" })).toEqual([head]);
    expect(head).toHaveAttribute("aria-expanded", "true");
    expect(head).toHaveFocus();
  });

  it("keeps a pending card and the focus in its message when a second call joins its run", async () => {
    const one = [call(1, "a"), ask(2, "a")].reduce(reduceTranscript, initialTranscript());
    const answer = vi.fn();
    const { rerender } = render(<Transcript state={one} onAnswerPermission={answer} />);
    const card = document.querySelector("[data-request-id='a']");
    const message = screen.getByRole("textbox", { name: /Message to Claude if you deny/ });
    await userEvent.click(message);

    rerender(
      <Transcript
        state={reduceTranscript(one, call(3, "b", "Read"))}
        onAnswerPermission={answer}
      />,
    );

    expect(document.querySelector("[data-request-id='a']")).toBe(card);
    expect(message).toHaveFocus();
  });

  it("reads a subagent's call Waiting for you while its permission is open, its card where it arrived", () => {
    const nested: StreamItem = {
      type: "record",
      record: aLogRecord("tool.call", {
        seq: 2,
        body: {
          tool_use_id: "n1",
          name: "Bash",
          input: { command: "ls" },
          parent_tool_use_id: "t1",
        },
      }),
    };
    show([call(1, "t1", "Task"), nested, text(3), ask(4, "n1")]);
    act(() => {
      screen.getByRole("button", { name: "1 subagent" }).click();
    });

    const calls = screen.getByRole("list", { name: "Calls made by Task" });
    expect(within(calls).getByRole("button", { name: "Bash ls (Waiting for you)" })).toBeVisible();
    const log = screen.getByRole("log");
    expect(log.lastElementChild?.querySelector("[data-request-id='n1']")).not.toBeNull();
  });

  it("re-renders no call in the open panel when text streams below the run", () => {
    const grouped = [call(1, "a", "Read"), call(2, "b", "Read")].reduce(
      reduceTranscript,
      initialTranscript(),
    );
    const { rerender } = render(<Transcript state={grouped} />);
    act(() => {
      screen.getByRole("button", { name: "Read 2 files" }).click();
    });
    const streaming = reduceTranscript(grouped, {
      type: "delta",
      delta: aDeltaFrame({ after_seq: 2, block: 0, index: 0, text: "Hi" }),
    });
    rerender(<Transcript state={streaming} />);

    renders.tool = 0;
    rerender(
      <Transcript
        state={reduceTranscript(streaming, {
          type: "delta",
          delta: aDeltaFrame({ after_seq: 2, block: 0, index: 1, text: " there" }),
        })}
      />,
    );

    const panel = screen.getByRole("complementary", { name: "Activity" });
    expect(within(panel).getAllByRole("button", { name: /^Read/ })).toHaveLength(2);
    expect(renders.tool).toBe(0);
  });
});

describe("Transcript (thinking) duration", () => {
  const thinking = (at: string): StreamItem => ({
    type: "record",
    record: aLogRecord("thinking", { seq: 3, at }),
  });
  const before: StreamItem = {
    type: "record",
    record: aLogRecord("user.message", { seq: 2, at: "2026-01-01T10:00:00.000Z" }),
  };

  it.each([
    [
      "from the previous record's time",
      [before, thinking("2026-01-01T10:00:07.400Z")],
      "Thought for 7 s",
    ],
    ["at least a second", [before, thinking("2026-01-01T10:00:00.200Z")], "Thought for 1 s"],
    ["without a previous record", [thinking("2026-01-01T10:00:07.000Z")], "Thinking"],
    ["when the times run backwards", [before, thinking("2026-01-01T09:59:00.000Z")], "Thinking"],
  ] as const)("reads the thinking time %s", (_, items, label) => {
    show([...items]);

    expect(document.querySelector(".as-thinking summary")).toHaveTextContent(
      new RegExp(`^${label}$`),
    );
  });

  it("counts from the previous record, not from text deltas after it", () => {
    show([
      before,
      { type: "delta", delta: aDeltaFrame({ after_seq: 2, index: 0, text: "Hm" }) },
      thinking("2026-01-01T10:00:03.000Z"),
    ]);

    expect(screen.getByText("Thought for 3 s")).toBeInTheDocument();
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

  it("keeps a Sending… bubble out of the live log, just after it (a11y)", () => {
    show([
      { type: "record", record: aLogRecord("user.message", { seq: 1 }) },
      { type: "sending", key: "s-1", text: "One more" },
    ]);

    const log = screen.getByRole("log", { name: "Conversation" });
    const sending = screen.getByText("One more");
    expect(log).not.toContainElement(sending);
    expect(log.compareDocumentPosition(sending) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(log).getByText("Run the tests.")).toBeInTheDocument();
  });
});

describe("Transcript (message-meta)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  const reply = (seq: number, text: string): StreamItem => ({
    type: "record",
    record: aLogRecord("text", { seq, body: { block: 0, text } }),
  });

  it("gives your messages and Claude's replies a time and Copy, not a streaming reply (AC-234.22)", () => {
    const user = aLogRecord("user.message", { seq: 1 });
    const text = aLogRecord("text", { seq: 2, body: { block: 0, text: "Done **now**." } });
    show([
      { type: "record", record: user },
      { type: "record", record: text },
      { type: "delta", delta: aDeltaFrame({ after_seq: 2, block: 1, index: 0, text: "More" }) },
    ]);

    const [done, streaming] = screen.getAllByRole("article", { name: "Claude" });
    if (!done) throw new Error("no finished reply");
    expect(done.querySelector("time")).toHaveAttribute("datetime", text.at);
    expect(within(done).getByRole("button", { name: "Copy message" })).toBeVisible();
    expect(streaming?.querySelector(".as-meta")).toBeNull();
    const mine = screen.getByText("Run the tests.").closest<HTMLElement>(".as-msg");
    if (!mine) throw new Error("no message");
    expect(mine.querySelector("time")).toHaveAttribute("datetime", user.at);
    expect(within(mine).getByRole("button", { name: "Copy message" })).toBeInTheDocument();
  });

  it("re-renders no Markdown when the minute ticks", () => {
    // At 14:01:30 the minute clock reads 14:01:00: the first reply (14:00:01) is 59 s old, "just now";
    // the 14:02:00 tick makes it 119 s old, which reads "2 min ago".
    vi.useFakeTimers({ now: Date.parse(at(90)) });
    show([reply(1, "One"), reply(2, "Two")]);
    const [first] = screen.getAllByRole("article", { name: "Claude" });
    if (!first) throw new Error("no reply");
    const label = () => first.querySelector("time")?.textContent;
    expect(label()).toBe("just now");
    renders.markdown = 0;

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(label()).toBe("2 min ago");
    expect(renders.markdown).toBe(0);
  });
});
