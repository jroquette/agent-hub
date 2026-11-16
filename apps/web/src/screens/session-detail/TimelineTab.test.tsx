import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aSession,
  aSessionSummary,
  aTimelineEvent,
  anActor,
  anId,
  at,
  manyEvents,
  renderWithApi,
  type TimelineEventBody,
} from "../../testing/builders";
import { SessionDetailScreen } from "./index";

const ID = anId(1, "5091b986");
const BASE = `/api/v1/sessions/${ID}`;

function trace(): TimelineEventBody[] {
  let seq = 0;
  const ev = (
    type: TimelineEventBody["type"],
    payload: TimelineEventBody["payload"],
    extra: Partial<TimelineEventBody> = {},
  ) => {
    seq += 1;
    return aTimelineEvent({ seq, timestamp: at(seq * 10), type, payload, ...extra });
  };
  return [
    ev("session.start", { trigger: "startup" }),
    ev("message", { role: "user", chars: 30 }),
    ev("tool.call", { tool: "Read", path: "a/one.py", tool_use_id: "r1" }),
    ev("tool.call", { tool: "Read", path: "a/two.py", tool_use_id: "r2" }),
    ev("tool.call", { tool: "Agent", subagent_type: "reviewer", tool_use_id: "ag" }),
    ev(
      "tool.call",
      { tool: "Grep", pattern: "needle", tool_use_id: "s1", agent_id: "sub1" },
      { agent: "reviewer" },
    ),
    ev("message", { role: "assistant", chars: 12, agent_id: "sub1" }, { agent: "reviewer" }),
    ev("tool.call", { tool: "Bash", command: "make check", tool_use_id: "b1" }),
    ev("tool.result", {
      tool: "Bash",
      status: "error",
      exit_code: 2,
      error_line: "1 failed",
      tool_use_id: "b1",
    }),
    ev("decision", { text: "Keep the line match" }),
    ev("tool.call", { tool: "Bash", command: "echo needle", tool_use_id: "b2" }),
  ];
}

function renderTrace(
  events: TimelineEventBody[],
  session = aSession({ status: "ended", outcome: "done" }),
  search = "",
) {
  return renderWithApi(<SessionDetailScreen />, {
    routes: {
      [BASE]: session,
      [`${BASE}/events`]: aPage(events),
      [`${BASE}/summary`]: aSessionSummary(),
    },
    path: `/sessions/${ID}${search}`,
    route: "/sessions/:sessionId",
  });
}

function key(k: string, extra: KeyboardEventInit = {}) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, ...extra }));
  });
}

describe("TimelineTab", () => {
  it("names one turn in the singular when a long session has a single turn", async () => {
    const events = Array.from({ length: 5000 }, (_, index) =>
      aTimelineEvent({
        seq: index + 1,
        timestamp: at(index + 1),
        type: index === 0 ? "session.start" : "tool.call",
        payload:
          index === 0 ? { trigger: "startup" } : { tool: "Bash", tool_use_id: `t${String(index)}` },
      }),
    );
    renderTrace(events);

    expect(await screen.findByText(/Long session · 5,000 events in 1 turn\./)).toBeInTheDocument();
  });

  it("expands a group and closes and reopens a lane in place when their toggles are pressed", async () => {
    renderTrace(trace());

    const group = await screen.findByRole(
      "button",
      { name: /Read 2 files in a\// },
      { timeout: 5000 },
    );
    fireEvent.click(group);
    expect(await screen.findByText("a/one.py")).toBeInTheDocument();

    const lane = screen.getByRole("button", { name: /Subagent · reviewer/ });
    expect(lane).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText('"needle"')).toBeInTheDocument();
    fireEvent.click(lane);
    expect(screen.queryByText('"needle"')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Subagent · reviewer/ }));
    expect(await screen.findByText('"needle"')).toBeInTheDocument();
  }, 20_000);

  it("moves through rows, errors and decisions with the keyboard", async () => {
    const { router } = renderTrace(trace());
    await screen.findByText("make check");

    key("j");
    await waitFor(() => {
      expect(router.state.location.search).toContain("event=");
    });
    key("e");
    await waitFor(() => {
      expect(router.state.location.search).toContain(anId(8, "0192aaaa"));
    });
    key("d");
    await waitFor(() => {
      expect(router.state.location.search).toContain(anId(10, "0192aaaa"));
    });
    key("k");
    key("/");
    expect(document.activeElement).toHaveAttribute("aria-label", "Search in session (Ctrl F)");
    key("f", { ctrlKey: true });
    key("2");
    await waitFor(() => {
      expect(router.state.location.search).toContain("tab=files");
    });
  });

  it("counts matches and steps through them when searching", async () => {
    const { router } = renderTrace(trace());
    await screen.findByText("make check");
    const search = screen.getByRole("textbox", { name: "Search in session (Ctrl F)" });

    fireEvent.change(search, { target: { value: "needle" } });
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    fireEvent.keyDown(search, { key: "Enter" });
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
    fireEvent.keyDown(search, { key: "Enter", shiftKey: true });
    search.blur();
    key("n");
    key("N");
    expect(router.state.location.search).toContain("q=needle");
  });

  it("filters by type, tool and lane from the rail, and collapses the rail", async () => {
    renderTrace(trace());
    await screen.findByText("make check");

    fireEvent.click(screen.getByRole("checkbox", { name: /Decisions/ }));
    expect(await screen.findByText("Keep the line match")).toBeInTheDocument();
    expect(screen.queryByText("make check")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Bash/ }));
    expect(await screen.findByText("make check")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /^Bash/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /^Subagent · reviewer/ }));
    expect(await screen.findByText('"needle"')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse filters" }));
    fireEvent.click(screen.getByRole("button", { name: /Filters/ }));
    expect(screen.getByRole("group", { name: "Lane" })).toBeInTheDocument();
  });

  it("opens a collapsed turn, expands all and jumps with the minimap in a long session", async () => {
    renderTrace(manyEvents(5000, ID));
    const summary = (await screen.findAllByRole("button", { name: /^Turn \d+ · 5 events/ }))[0];
    if (!summary) throw new Error("no collapsed turn");
    const turn = /^Turn (\d+)/.exec(summary.textContent)?.[1] ?? "";
    fireEvent.click(summary);
    expect(await screen.findByText(`Turn ${turn}`)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    const minimap = screen.getByRole("slider", { name: "Session minimap: click to jump" });
    fireEvent.click(minimap, { clientY: 200 });
    fireEvent.keyDown(minimap, { key: "PageDown" });
    fireEvent.click(screen.getByRole("button", { name: "Turn" }));
    fireEvent.click(minimap, { clientY: 10 });
    expect(screen.getAllByText("T1").length).toBeGreaterThan(0);
  }, 20_000);

  it("opens the lane and row a deep link names", async () => {
    renderTrace(trace(), undefined, `?event=${anId(6, "0192aaaa")}&lane=sub1`);

    expect(await screen.findByText('"needle"')).toBeInTheDocument();
    await waitFor(() => {
      expect(document.getElementById(`ev-${anId(6, "0192aaaa")}`)).toHaveAttribute(
        "aria-current",
        "true",
      );
    });
  });

  it("shows waiting, idle and inferred-end notes in live and ended sessions", async () => {
    const waiting = renderTrace(trace(), aSession({ status: "waiting", issue: "AGH-48" }));
    expect(await screen.findByText(/Waiting for approval · AGH-48/)).toBeInTheDocument();
    key("f");
    key("G", { shiftKey: true });
    waiting.unmount();

    const idle = renderTrace(trace(), aSession({ status: "idle" }));
    expect(await screen.findByText(/No activity since/)).toBeInTheDocument();
    idle.unmount();

    renderTrace(trace(), aSession({ status: "ended", outcome: null, end_inferred: true }));
    expect(await screen.findByText(/Ended · no end event received/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse" }));
    expect(screen.getByRole("button", { name: /Show 0 more/ })).toBeInTheDocument();
  });
});

function line(element: Element | null | undefined): string {
  const kind = element?.querySelector(".ah-ev-kind")?.textContent ?? "";
  const main = element?.querySelector(".ah-ev-main")?.textContent ?? "";
  return `${kind}${main}`;
}

describe("TimelineTab actors", () => {
  it("names the actor of each row and nests a subagent's rows under the Agent call that started it", async () => {
    let seq = 0;
    const ev = (
      type: TimelineEventBody["type"],
      payload: TimelineEventBody["payload"],
      extra: Partial<TimelineEventBody> = {},
    ) => {
      seq += 1;
      return aTimelineEvent({ seq, timestamp: at(seq * 10), type, payload, ...extra });
    };
    const skill = ev("tool.call", { tool: "Skill", skill: "feature", tool_use_id: "sk" });
    const agent = ev("tool.call", {
      tool: "Agent",
      subagent_type: "Explore",
      description: "map the collector",
      tool_use_id: "ag",
    });
    const read = ev(
      "tool.call",
      { tool: "Read", path: "packages/collector/src/x.py", tool_use_id: "r", agent_id: "s1" },
      { agent: "Explore" },
    );
    const session = aSession({
      status: "ended",
      outcome: "done",
      actors: [
        anActor(),
        anActor({
          kind: "subagent",
          agent_id: "s1",
          type: "Explore",
          description: "map the collector",
          started_by_event_id: agent.event_id,
        }),
      ],
    });
    renderTrace([skill, agent, read], session);

    const readRow = (await screen.findByText("packages/collector/src/x.py")).closest(".ah-ev");
    // Calls without a result also show "Running" after the sentence.
    expect(line(document.getElementById(`ev-${skill.event_id}`))).toMatch(
      /^Main agent · Ran skill \/feature(Running)?$/,
    );
    expect(line(document.getElementById(`ev-${agent.event_id}`))).toMatch(
      /^Main agent · Started subagent Explore: map the collector(Running)?$/,
    );
    expect(line(readRow)).toMatch(
      /^Subagent · Explore · Read packages\/collector\/src\/x\.py(Running)?$/,
    );
    expect(readRow?.closest(".sd-depth-1")).not.toBeNull();
    const lane = screen.getByRole("group", { name: "Subagent · Explore: map the collector" });
    const agentRow = document.getElementById(`ev-${agent.event_id}`);
    expect(
      agentRow && lane.compareDocumentPosition(agentRow) & Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy();
    expect(
      readRow && lane.compareDocumentPosition(readRow) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

describe("TimelineTab verbs", () => {
  it("shows the verb and its object in each row with the command in code", async () => {
    renderTrace(trace());

    const row = (await screen.findByText("make check")).closest(".ah-ev");
    expect(line(row)).toContain("Main agent · Ran make check");
    expect(screen.getByText("make check").tagName).toBe("CODE");
    expect(line(screen.getByText("Keep the line match").closest(".ah-ev"))).toContain(
      "Main agent · Decided: Keep the line match",
    );
  });
});

describe("TimelineTab grouping", () => {
  it("collapses twelve reads into an expandable row and keeps the error, gate and guard rows on show", async () => {
    const events = [
      ...Array.from({ length: 12 }, (_, i) =>
        aTimelineEvent({
          seq: i + 1,
          timestamp: at(i + 1),
          type: "tool.call",
          payload: { tool: "Read", path: `pkg/f${String(i)}.py`, tool_use_id: `r${String(i)}` },
        }),
      ),
      aTimelineEvent({
        seq: 13,
        timestamp: at(13),
        type: "tool.call",
        payload: { tool: "Bash", command: "make check", tool_use_id: "b" },
      }),
      aTimelineEvent({
        seq: 14,
        timestamp: at(14),
        type: "tool.result",
        payload: { tool: "Bash", status: "error", exit_code: 2, tool_use_id: "b" },
      }),
      aTimelineEvent({
        seq: 15,
        timestamp: at(15),
        type: "gate.result",
        payload: { gate_id: "g", kind: "check", name: "check-fast", result: "passed" },
      }),
      aTimelineEvent({
        seq: 16,
        timestamp: at(16),
        type: "tool.call",
        payload: { tool: "Bash", command: "git push", tool_use_id: "d" },
      }),
      aTimelineEvent({
        seq: 17,
        timestamp: at(17),
        type: "tool.result",
        payload: { tool: "Bash", status: "denied", rule: "no-push", tool_use_id: "d" },
      }),
    ];
    renderTrace(events);

    const group = await screen.findByRole("button", { name: /Read 12 files/ });
    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("pkg/f0.py")).not.toBeInTheDocument();
    expect(screen.getByText("make check")).toBeInTheDocument();
    expect(screen.getByText("check-fast")).toBeInTheDocument();
    expect(screen.getByText("Guard blocked Bash")).toBeInTheDocument();
    fireEvent.click(group);
    expect(await screen.findByText("pkg/f0.py")).toBeInTheDocument();
  });
});

describe("TimelineTab legend", () => {
  it("explains actor badges, status badges and icons with no serious or critical a11y violation", async () => {
    const { container } = renderTrace(trace());
    await screen.findByText("make check");

    fireEvent.click(screen.getByText("Legend"));
    const legend = screen.getByText("Legend").closest("details");
    if (!legend) throw new Error("no legend");
    expect(legend).toHaveAttribute("open");
    expect(await within(legend).findByText("Who acted")).toBeInTheDocument();
    for (const text of [
      "Who acted",
      "Main agent",
      "Subagent · <type>",
      "You",
      "Needs you",
      "Agent is on it",
      "Handled by the agent",
      "You interrupted",
      "Icons",
      "Ran a skill",
      "Started a subagent",
      "Guard event",
    ]) {
      expect(within(legend).getByText(text)).toBeInTheDocument();
    }
    expect(await seriousViolations(container)).toEqual([]);
  }, 20_000);
});
