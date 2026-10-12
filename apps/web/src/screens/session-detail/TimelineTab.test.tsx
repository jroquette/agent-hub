import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  aPage,
  aSession,
  aSessionSummary,
  aTimelineEvent,
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

  it("expands a group and a lane in place when their toggles are pressed", async () => {
    renderTrace(trace());

    const group = await screen.findByRole("button", { name: /Read 2 files in a\// });
    fireEvent.click(group);
    expect(await screen.findByText("a/one.py")).toBeInTheDocument();

    const lane = screen.getByRole("button", { name: /Subagent reviewer/ });
    expect(lane).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(lane);
    expect(await screen.findByText('"needle"')).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Subagent reviewer/ }));
    expect(screen.queryByText('"needle"')).not.toBeInTheDocument();
  });

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
    fireEvent.click(screen.getByRole("checkbox", { name: /^reviewer/ }));
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
  });

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
