import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aSession,
  aSessionCost,
  aSessionFile,
  aSessionSummary,
  aTimelineEvent,
  anId,
  at,
  manyEvents,
  renderWithApi,
  type ApiRoutes,
  type TimelineEventBody,
} from "../../testing/builders";
import { SessionDetailScreen } from "./index";
import { CONTENT_NOT_STORED, DIFF_NOT_STORED } from "./TraceRow";

const ID = anId(1, "5091b986");
const BASE = `/api/v1/sessions/${ID}`;

function routes(
  overrides: ApiRoutes = {},
  events: TimelineEventBody[] = defaultEvents(),
): ApiRoutes {
  return {
    [BASE]: aSession({ status: "ended", outcome: "done", ended_at: at(900) }),
    [`${BASE}/events`]: aPage(events),
    [`${BASE}/summary`]: aSessionSummary({
      lines: [{ event_id: anId(2, "0192aaaa"), text: "Ran make check-fast: passed" }],
    }),
    [`${BASE}/files`]: aPage([
      aSessionFile({ path: "brain/features/x/eval.md", ops: ["created"], added: 64, removed: 0 }),
      aSessionFile({ path: "packages/core/src/x.py", ops: ["read"], added: 0, removed: 0 }),
    ]),
    [`${BASE}/cost`]: aSessionCost(),
    ...overrides,
  };
}

function defaultEvents(): TimelineEventBody[] {
  return [
    aTimelineEvent({
      seq: 1,
      type: "session.start",
      payload: { trigger: "startup", cwd: "/home/dev/agent-hub" },
    }),
    aTimelineEvent({ seq: 2, type: "message", payload: { role: "user", chars: 1240 } }),
    aTimelineEvent({
      seq: 3,
      type: "tool.call",
      payload: { tool: "Bash", command: "make check-fast", tool_use_id: "t3" },
    }),
    aTimelineEvent({
      seq: 4,
      type: "tool.result",
      payload: { tool: "Bash", status: "ok", exit_code: 0, duration_ms: 12000, tool_use_id: "t3" },
    }),
    aTimelineEvent({
      seq: 5,
      type: "session.end",
      payload: { end_reason: "other", outcome: "done" },
    }),
  ];
}

function renderDetail(apiRoutes: ApiRoutes, search = "") {
  return renderWithApi(<SessionDetailScreen />, {
    routes: apiRoutes,
    path: `/sessions/${ID}${search}`,
    route: "/sessions/:sessionId",
  });
}

describe("SessionDetailScreen", () => {
  it("renders the header, summary and merged rows of an ended session", async () => {
    renderDetail(routes());

    expect(await screen.findByRole("heading", { name: "claude" })).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(await screen.findByText("Ran make check-fast: passed")).toBeInTheDocument();
    expect(await screen.findByText("make check-fast")).toBeInTheDocument();
    expect(screen.getByText("exit 0")).toBeInTheDocument();
    expect(screen.getByText("Session started")).toBeInTheDocument();
  });

  it("shows the long-session banner, collapses middle turns and renders few rows when the session is long", async () => {
    const events = manyEvents(5000, ID);
    const { container } = renderDetail(routes({}, events));

    expect(
      await screen.findByText(/Long session · 5,000 events in 1,000 turns/),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".ah-ev").length).toBeLessThan(200);
    expect(screen.getAllByRole("button", { name: /^Turn \d+ · 5 events/ }).length).toBeGreaterThan(
      0,
    );
  });

  it("shows redacted values as chips in the row, command and raw view, and never matches them in search", async () => {
    const events = [
      aTimelineEvent({
        seq: 1,
        type: "tool.call",
        payload: {
          tool: "Bash",
          command: "gh auth login --with-token [redacted: github token]",
          env: { GH_TOKEN: "[redacted: github token]" },
          tool_use_id: "t1",
        },
      }),
    ];
    renderDetail(routes({}, events));

    const row = (await screen.findByText(/gh auth login/)).closest<HTMLElement>(".ah-ev");
    if (!row) throw new Error("no row");
    expect(
      within(row).getAllByRole("note", {
        name: "Redacted github token",
      }),
    ).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /gh auth login/ }));
    expect(screen.getByRole("group", { name: "Command" })).toContainElement(
      screen.getAllByRole("note", { name: "Redacted github token" })[1] ?? null,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show raw event (redacted JSON)" }));
    expect(
      screen.getAllByRole("note", { name: "Redacted github token" }).length,
    ).toBeGreaterThanOrEqual(3);
    expect(screen.queryByRole("button", { name: /^reveal/i })).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Search in session (Ctrl F)" }), {
      target: { value: "github token" },
    });
    expect(
      await screen.findByText('No match for "github token" in this session.'),
    ).toBeInTheDocument();
  });

  it("says content is not stored with role, size and turn when a message or reasoning row expands", async () => {
    const events = [
      aTimelineEvent({ seq: 1, type: "message", payload: { role: "user", chars: 1240 } }),
      aTimelineEvent({
        seq: 2,
        type: "reasoning",
        source: "transcript",
        payload: { chars: 88, turn: 1 },
      }),
    ];
    renderDetail(routes({}, events));

    fireEvent.click(await screen.findByRole("button", { name: "1,240 characters" }));
    expect(screen.getByText("Role user · 1,240 characters · turn 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "88 characters" }));
    expect(
      screen.getByText("Recorded reasoning summary · 88 characters · turn 1"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(CONTENT_NOT_STORED)).toHaveLength(2);
  });

  it("has Timeline, Files, Cost and Raw events tabs with stored-content copy when the tabs render", async () => {
    renderDetail(routes());

    await screen.findByText("make check-fast");
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      "Timeline4",
      "Files and diffs3",
      "Cost",
      "Raw events5",
    ]);
    expect(screen.queryByRole("tab", { name: /Decisions|Context/ })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Files/ }));
    expect(
      await screen.findByText("2 files · 0 edited · 1 created · 1 read only"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("created").length).toBeGreaterThan(0);
    expect(screen.getAllByText("+64").length).toBeGreaterThan(0);
    expect(screen.getByText(DIFF_NOT_STORED)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Cost" }));
    expect((await screen.findAllByText("Estimated from transcript")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("tab", { name: /Raw events/ }));
    expect(await screen.findByText(/5 events · 4 timeline rows/)).toBeInTheDocument();
  });

  it("shows loading, error, not found, empty and stale states", async () => {
    const pending = renderDetail(routes({ [BASE]: "pending" }));
    await waitFor(() => {
      expect(pending.container.querySelector(".ah-skel")).not.toBeNull();
    });
    pending.unmount();

    const failed = renderDetail(
      routes({ [BASE]: aProblem({ status: 500, title: "Internal", detail: "Store busy" }) }),
    );
    expect(await screen.findByText("Could not load session")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    failed.unmount();

    const missing = renderDetail(routes({ [BASE]: aProblem({ status: 404, title: "Not found" }) }));
    expect(await screen.findByText("Session not found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open command palette" })).toBeInTheDocument();
    missing.unmount();

    const empty = renderDetail(
      routes({ [BASE]: aSession({ status: "live" }) }, [
        aTimelineEvent({ seq: 1, type: "session.start", payload: {} }),
      ]),
    );
    expect(await screen.findByText("No events yet")).toBeInTheDocument();
    expect(screen.getByText("Summary appears when the session ends")).toBeInTheDocument();
    expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    empty.unmount();

    renderDetail(
      routes({
        [`${BASE}/events`]: aProblem({ status: 503, title: "Busy", detail: "Store busy" }),
      }),
    );
    expect(await screen.findByText("Could not load events 1–200.")).toBeInTheDocument();
  });

  it("follows live events and shows the new events pill when follow is off", async () => {
    const { stream } = renderDetail(routes({ [BASE]: aSession({ status: "live" }) }));
    expect(await screen.findByText("make check-fast")).toBeInTheDocument();
    const source = stream(`${BASE}/events/stream`);
    act(() => {
      source.open();
      source.emit(
        "event",
        aTimelineEvent({
          seq: 9,
          type: "tool.call",
          payload: { tool: "Read", path: "README.md", tool_use_id: "t9" },
        }),
      );
    });
    expect(await screen.findByText("README.md")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Following live" }));
    act(() => {
      source.emit(
        "event",
        aTimelineEvent({
          seq: 10,
          type: "tool.call",
          payload: { tool: "Read", path: "NOTES.md", tool_use_id: "t10" },
        }),
      );
      source.emit("session", { turns: 9 });
    });
    expect(await screen.findByRole("button", { name: "1 new event" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1 new event" }));
    expect(screen.getByRole("button", { name: "Following live" })).toBeInTheDocument();
  });

  it("selects the event a summary line names when it is clicked", async () => {
    renderDetail(routes());

    fireEvent.click(await screen.findByRole("link", { name: /→/ }));
    await waitFor(() => {
      expect(document.querySelector('[aria-current="true"]')).toHaveAttribute(
        "id",
        `ev-${anId(2, "0192aaaa")}`,
      );
    });
  });

  it("filters to errors and decisions and switches the time axis", async () => {
    renderDetail(routes());
    await screen.findByText("make check-fast");

    fireEvent.click(screen.getByRole("checkbox", { name: "Errors and decisions only" }));
    expect(await screen.findByRole("button", { name: "2 events hidden" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2 events hidden" }));
    expect(await screen.findByText("make check-fast")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Turn" }));
    expect(screen.getAllByText("T1").length).toBeGreaterThan(0);
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderDetail(routes());
    await screen.findByText("make check-fast");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
