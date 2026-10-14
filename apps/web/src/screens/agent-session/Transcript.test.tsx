import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { aDeltaFrame, aLogRecord } from "../../testing/builders";
import { seriousViolations } from "../../testing/axe";
import { CostMeter } from "./CostMeter";
import { TodoList } from "./TodoList";
import { Transcript } from "./Transcript";
import { initialTranscript, reduceTranscript, type StreamItem } from "./transcript";

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
