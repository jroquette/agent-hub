import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { aLogRecord, at } from "../../testing/builders";
import { LiveActivityBar, StepsPanel } from "./LiveActivityBar";
import { turnSteps, type LiveActivity, type LiveCall } from "./liveActivity";
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

const CSS = readFileSync(join(__dirname, "agent-session.css"), "utf8");

/** The declarations of the CSS rule whose selector list is exactly `selector`. */
function rule(selector: string): string {
  const start = CSS.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`no rule ${selector}`);
  return CSS.slice(start, CSS.indexOf("}", start));
}

/** A running turn as the bar reads it; times are seconds after T0. */
function anActivity(overrides: Partial<LiveActivity> = {}): LiveActivity {
  return {
    phase: "thinking",
    calls: [],
    todo: null,
    turnStartedAt: at(0),
    lastEventAt: at(0),
    feed: [],
    earlier: 0,
    ...overrides,
  };
}

const aCall = (overrides: Partial<LiveCall> = {}): LiveCall => ({
  id: "b",
  name: "Bash",
  label: "make test",
  startedAt: at(0),
  subagent: false,
  running: [],
  calls: 0,
  ...overrides,
});

describe("LiveActivityBar", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("AC-PG-32.1: shows the phase, the running subagents, the elapsed time and the time since the last event, with one alive signal", () => {
    vi.setSystemTime(Date.parse(at(125)));
    const activity = anActivity({
      phase: "subagents",
      lastEventAt: at(75),
      calls: [aCall({ id: "a", name: "Agent", label: "Explore · find cost code", subagent: true })],
    });
    const { container } = render(
      <LiveActivityBar activity={activity} open={false} onToggle={vi.fn()} />,
    );

    const bar = screen.getByRole("button", { name: /Running subagents: 1 agent/ });
    expect(bar).toHaveTextContent("Explore · find cost code");
    expect(within(bar).getByTitle("Time since your message started this turn")).toHaveTextContent(
      "2 min 05 s",
    );
    expect(bar).toHaveTextContent("quiet for 50 s");
    expect(container.querySelectorAll(".as-live-pulse")).toHaveLength(1);
    expect(bar).toHaveAttribute("aria-expanded", "false");
    expect(bar).toHaveTextContent("Show steps");
  });

  it("AC-PG-32.1: renders nothing when no turn runs", () => {
    const { container } = render(
      <LiveActivityBar activity={null} open={false} onToggle={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("AC-PG-32.2: the bar toggles the Steps drawer and names its shortcut", async () => {
    vi.setSystemTime(Date.parse(at(5)));
    const onToggle = vi.fn();
    const { rerender } = render(
      <LiveActivityBar activity={anActivity()} open={false} onToggle={onToggle} />,
    );
    const bar = screen.getByRole("button", { name: /Thinking/ });
    expect(bar).toHaveAttribute("aria-keyshortcuts", "Control+Alt+Period Meta+Alt+Period");
    expect(bar).toHaveAttribute("title", "Show the turn's steps (Ctrl Alt .)");
    await userEvent.click(bar);
    expect(onToggle).toHaveBeenCalledTimes(1);

    rerender(<LiveActivityBar activity={anActivity()} open onToggle={onToggle} />);
    expect(bar).toHaveAttribute("aria-expanded", "true");
    expect(bar).toHaveAttribute("aria-controls", "as-live-panel");
    expect(bar).toHaveTextContent("Hide steps");
  });

  it("AC-PG-32.3: no new record for 5 minutes flags the turn as likely stuck, calmly", () => {
    vi.setSystemTime(Date.parse(at(301)));
    const { container } = render(
      <LiveActivityBar activity={anActivity()} open={false} onToggle={vi.fn()} />,
    );

    const notice = screen.getByText(/Claude has been quiet for 5 min 01 s/);
    expect(notice).toHaveTextContent("If it does not pick up again, press Stop");
    expect(notice).toHaveClass("as-live-stall");
    expect(screen.getByRole("region", { name: "Live activity" })).toHaveClass("as-live-stalled");
    // The quiet label gives way to the notice; nothing reads as an error.
    expect(screen.queryByText(/^quiet for/)).toBeNull();
    expect(container.querySelector("[role=alert], .ah-danger, .is-error")).toBeNull();
    // Calm: the notice is muted on a sunken surface, the pulse greys out and stops.
    expect(rule(".as-live-stall")).toContain("color: var(--text-muted)");
    expect(rule(".as-live-stall")).not.toMatch(/danger|error|red/);
    expect(rule(".as-live-stalled .as-live-pulse")).toContain("background: var(--idle)");
    expect(rule(".as-live-stalled .as-live-pulse")).toContain("animation: none");
  });

  it("AC-PG-32.3: under 5 minutes, or with a call still running, the turn reads quiet, not stuck", () => {
    vi.setSystemTime(Date.parse(at(299)));
    const { unmount } = render(
      <LiveActivityBar activity={anActivity()} open={false} onToggle={vi.fn()} />,
    );
    expect(screen.getByText("quiet for 4 min 59 s")).toBeInTheDocument();
    expect(screen.queryByText(/Claude has been quiet/)).toBeNull();
    unmount();

    // The bar reads the clock on mount, then every second.
    vi.setSystemTime(Date.parse(at(900)));
    render(
      <LiveActivityBar
        activity={anActivity({ phase: "tool", calls: [aCall()] })}
        open={false}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText("quiet for 15 min 00 s")).toBeInTheDocument();
    expect(screen.queryByText(/Claude has been quiet/)).toBeNull();
    expect(screen.getByRole("region", { name: "Live activity" })).not.toHaveClass(
      "as-live-stalled",
    );
  });

  it("AC-PG-32.3: a failed call is not shown in alarming red", () => {
    render(<StepsPanel steps={stepsOf(turn)} onClose={vi.fn()} />);
    const failed = screen.getByText("didn't work, Claude moved on");
    expect(failed).toHaveClass("ah-subtle");
    expect(failed.closest("li")).toHaveClass("as-feed-error");
    expect(
      rule(
        ".as-feed-error > .as-feed-call .as-feed-mark,\n.as-feed-denied > .as-feed-call .as-feed-mark",
      ),
    ).toContain("color: var(--text-subtle)");
  });

  it("AC-PG-32.4: while waiting on the owner the bar offers Show request, which goes to the request", async () => {
    vi.setSystemTime(Date.parse(at(10)));
    const waiting = stepsOf([
      ...turn.slice(0, 1),
      record("tool.call", {
        seq: 2,
        body: { tool_use_id: "req-1", name: "Bash", input: { command: "git status" } },
      }),
      record("permission.request", { seq: 3 }),
      { type: "status", status: { status: "waiting_permission" } },
    ]);
    const card = document.createElement("section");
    card.dataset.requestId = "req-1";
    const allow = document.createElement("button");
    allow.textContent = "Allow";
    card.append(allow);
    card.scrollIntoView = vi.fn();
    document.body.append(card);
    const onToggle = vi.fn();
    try {
      render(<LiveActivityBar activity={waiting.activity} open={false} onToggle={onToggle} />);
      const bar = screen.getByRole("button", { name: /Waiting for you/ });
      expect(bar).toHaveTextContent("Show request");
      expect(bar).not.toHaveAttribute("aria-expanded");
      await userEvent.click(bar);
      expect(onToggle).not.toHaveBeenCalled();
      expect(allow).toHaveFocus();
    } finally {
      card.remove();
    }
  });

  it("AC-PG-32.4: the drawer offers Show request on the call that waits", () => {
    const waiting = stepsOf([
      ...turn.slice(0, 1),
      record("tool.call", {
        seq: 2,
        body: { tool_use_id: "req-1", name: "Bash", input: { command: "git status" } },
      }),
      record("permission.request", { seq: 3 }),
      { type: "status", status: { status: "waiting_permission" } },
    ]);
    render(<StepsPanel steps={waiting} onClose={vi.fn()} />);
    const panel = screen.getByRole("complementary", { name: "Steps" });
    expect(within(panel).getByRole("button", { name: "Show request" })).toBeInTheDocument();
  });
});

describe("StepsPanel (turn ends)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(Date.parse(at(60)));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("AC-PG-32.4: once the turn ends the drawer says how it ended, with no running step left", () => {
    const { rerender } = render(<StepsPanel steps={stepsOf(turn)} onClose={vi.fn()} />);
    expect(screen.getByText(/Running subagents/)).toBeInTheDocument();

    rerender(
      <StepsPanel
        steps={stepsOf([...turn, { type: "status", status: { status: "idle" } }])}
        onClose={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Running subagents/)).toBeNull();
    expect(screen.getByText(/^Turn finished/)).toBeInTheDocument();
    expect(screen.queryByText(/running \d/)).toBeNull();
    expect(document.querySelector(".as-feed-running")).toBeNull();
  });

  it("AC-PG-32.4: restored on load or updated later, the drawer never takes the keyboard", () => {
    const box = document.createElement("textarea");
    document.body.append(box);
    box.focus();
    try {
      const { rerender } = render(
        <StepsPanel steps={stepsOf(turn)} onClose={vi.fn()} focusOnOpen={false} />,
      );
      expect(box).toHaveFocus();
      rerender(
        <StepsPanel
          steps={stepsOf([...turn, { type: "status", status: { status: "idle" } }])}
          onClose={vi.fn()}
          focusOnOpen
        />,
      );
      expect(box).toHaveFocus();
    } finally {
      box.remove();
    }
  });
});
