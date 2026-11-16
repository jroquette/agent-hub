import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../lib/api";
import { AppShell } from "../../shell/AppShell";
import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aFeature,
  aFeatureTickets,
  aPage,
  aProblem,
  aSession,
  aSessionLabel,
  aTicketRow,
  aSessionCost,
  aSessionDetailView,
  aSessionFile,
  aSessionProblem,
  aSessionProblems,
  aSessionSummary,
  aShellView,
  aTimelineEvent,
  anId,
  at,
  manyEvents,
  renderWithApi,
  type ApiRoutes,
  type SessionDetailView,
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

    expect(await screen.findByRole("heading", { name: "AGH-48: live-tiles" })).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(await screen.findByText("Ran make check-fast: passed")).toBeInTheDocument();
    expect(await screen.findByText("make check-fast")).toBeInTheDocument();
    expect(screen.getByText("exit 0")).toBeInTheDocument();
    expect(screen.getByText("Started the session in")).toBeInTheDocument();
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

    fireEvent.click(
      await screen.findByRole("button", { name: "Sent a prompt (1,240 characters)" }),
    );
    expect(screen.getByText("Role user · 1,240 characters · turn 1")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Recorded a reasoning summary (88 characters)" }),
    );
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
    expect(await screen.findByText("Could not load events 1–1000.")).toBeInTheDocument();
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

describe("SessionDetailScreen what-went-wrong", () => {
  it("shows the problems panel and opens the failed row at its moment when the session has problems", async () => {
    const failure = anId(4, "0192aaaa");
    const { router } = renderDetail(
      routes({
        [BASE]: aSession({
          status: "ended",
          outcome: "done",
          ended_at: at(900),
          problems: { needs_you: 1, open: 0, handled: 0, by_you: 0 },
        }),
        [`${BASE}/problems`]: aSessionProblems({
          summary: [{ event_id: failure, text: "Needs you: make check-fast failed" }],
          items: [aSessionProblem({ event_id: failure, at: at(4) })],
        }),
      }),
    );

    const panel = await screen.findByRole("region", { name: "What went wrong" });
    expect(within(panel).getByText("Needs you: make check-fast failed")).toBeInTheDocument();
    const row = await waitFor(() => {
      const found = document.getElementById(`ev-${anId(3, "0192aaaa")}`);
      if (!found) throw new Error("no row");
      return found;
    });
    expect(within(row).getByText("Needs you")).toBeInTheDocument();

    fireEvent.click(within(panel).getByRole("link", { name: /^Open moment: Command failed/ }));
    await waitFor(() => {
      expect(router.state.location.search).toContain(failure);
    });
    await waitFor(() => {
      expect(document.getElementById(`ev-${anId(3, "0192aaaa")}`)).toHaveAttribute(
        "aria-current",
        "true",
      );
    });
  });

  it("asks for the problems again when a live session's counts change over the stream", async () => {
    const { requests, stream } = renderDetail(
      routes({
        [BASE]: aSession({
          status: "live",
          problems: { needs_you: 0, open: 1, handled: 0, by_you: 0 },
        }),
        [`${BASE}/problems`]: aSessionProblems({
          items: [aSessionProblem({ resolution: "open" })],
        }),
      }),
    );
    expect(await screen.findByRole("region", { name: "What went wrong" })).toBeInTheDocument();
    const asked = () => requests.filter((request) => request.url.endsWith("/problems")).length;
    expect(asked()).toBe(1);

    act(() => {
      const source = stream(`${BASE}/events/stream`);
      source.open();
      source.emit("session", { problems: { needs_you: 1, open: 0, handled: 0, by_you: 0 } });
    });
    await waitFor(() => {
      expect(asked()).toBe(2);
    });
  });

  it("does not ask for problems when the session has none", async () => {
    const { requests } = renderDetail(routes());
    await screen.findByText("make check-fast", { selector: "code" });

    expect(requests.some((request) => request.url.endsWith("/problems"))).toBe(false);
    expect(screen.queryByRole("region", { name: "What went wrong" })).not.toBeInTheDocument();
  });
});

describe("SessionDetailScreen (session-name)", () => {
  it("names a session on a ticket by the ticket's title once read, with its feature linked", async () => {
    const onTicket = aSession({
      status: "ended",
      outcome: "done",
      ended_at: at(900),
      project: "agent-hub",
      label: aSessionLabel({ issue: "AGH-202", branch: "dev/agh-202-summaries" }),
    });
    const view = renderDetail(
      routes({
        [BASE]: onTicket,
        "/api/v1/features": aPage([aFeature({ issues: ["AGH-202"] })]),
        "/api/v1/features/agent-hub/control-plane/tickets": aFeatureTickets({
          tickets: [aTicketRow()],
        }),
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "AGH-202: Serve the ticket summaries" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /control-plane/ })).toHaveAttribute(
      "href",
      "/features/agent-hub/control-plane",
    );
    const tickets = view.requests.filter((r) => r.url.endsWith("/control-plane/tickets"));
    expect(tickets).toHaveLength(1);
  });
});

const READ = `/api/v1/screens/session-detail/${ID}`;
const TICKETS = "/api/v1/features/agent-hub/control-plane/tickets";
const CAPABILITIES = "/api/v1/agent-sessions/capabilities";

/** The routes whose answers the detail read (ADR 0056) carries. */
const readResources = [
  BASE,
  `${BASE}/events`,
  `${BASE}/summary`,
  `${BASE}/problems`,
  "/api/v1/features",
  CAPABILITIES,
];

/** What the session is about: AGH-202, an issue of feature `control-plane`. */
const onTicket = aSessionLabel({ issue: "AGH-202", branch: "dev/agh-202-summaries" });

/** The detail read of an ended session on AGH-202: its events, its summary, its project's feature
 * that lists the issue, and a machine that can drive sessions. */
function aDetailRead(overrides: Partial<SessionDetailView> = {}): SessionDetailView {
  return aSessionDetailView({
    session: aSession({ status: "ended", outcome: "done", ended_at: at(900), label: onTicket }),
    events: aPage(defaultEvents()),
    summary: aSessionSummary({
      lines: [{ event_id: anId(2, "0192aaaa"), text: "Ran make check-fast: passed" }],
    }),
    features: aPage([aFeature({ issues: ["AGH-202"] })]),
    capabilities: aCapabilities(),
    ...overrides,
  });
}

/** Renders the screen inside the shell on the app's own query client (under its 10 s staleTime a
 * seeded query does not fetch), with the shell read and the feature's tickets answered. */
function renderFromRead(apiRoutes: ApiRoutes, queryClient = createQueryClient()) {
  return renderWithApi(
    <AppShell>
      <SessionDetailScreen />
    </AppShell>,
    {
      routes: {
        "/api/v1/screens/shell": aShellView(),
        [TICKETS]: aFeatureTickets({ tickets: [aTicketRow()] }),
        ...apiRoutes,
      },
      path: `/sessions/${ID}`,
      route: "/sessions/:sessionId",
      queryClient,
    },
  );
}

describe("SessionDetailScreen screen read", () => {
  it.each([
    {
      session: "ended, with a problem",
      read: aDetailRead({
        session: aSession({
          status: "ended",
          outcome: "done",
          ended_at: at(900),
          label: onTicket,
          problems: { needs_you: 1, open: 0, handled: 0, by_you: 0 },
        }),
        problems: aSessionProblems({
          summary: [{ event_id: anId(4, "0192aaaa"), text: "Needs you: make check-fast failed" }],
        }),
      }),
      // Its summary, its problems and the chat it can go on in come from the read.
      shows: [
        "Ran make check-fast: passed",
        "Needs you: make check-fast failed",
        "Continue in chat",
      ],
      live: false,
    },
    {
      // No summary and no problem yet; the session's own stream is the fifth request.
      session: "live",
      read: aDetailRead({ session: aSession({ status: "live", label: onTicket }), summary: null }),
      shows: ["Summary appears when the session ends"],
      live: true,
    },
  ])(
    "AC-36 loads in at most 5 API requests with the shell mounted ($session)",
    async ({ read, shows, live }) => {
      const { calls } = renderFromRead({ [READ]: read });

      // The header names the session by its ticket: the feature comes from the read, the title
      // from that feature's own tickets read.
      expect(
        await screen.findByRole("heading", { name: "AGH-202: Serve the ticket summaries" }),
      ).toBeInTheDocument();
      expect(await screen.findByText("Started the session in")).toBeInTheDocument();
      for (const text of shows) {
        expect(await screen.findByText(text)).toBeInTheDocument();
      }
      const asked = calls();
      expect(asked.filter((p) => readResources.includes(p))).toEqual([]);
      expect(asked.filter((p) => p === READ)).toHaveLength(1);
      expect(asked.filter((p) => p === TICKETS)).toHaveLength(1);
      expect(asked.includes(`${BASE}/events/stream`)).toBe(live);
      expect(asked.length).toBeLessThanOrEqual(5);
    },
  );

  it("reads the capabilities itself when the detail read carries none", async () => {
    const { calls } = renderFromRead({
      [READ]: aDetailRead({ capabilities: null }),
      [CAPABILITIES]: aCapabilities(),
    });

    // A null part is not seeded: its route answers, so the ended session can go on in a chat.
    expect(await screen.findByRole("button", { name: "Continue in chat" })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: "AGH-202: Serve the ticket summaries" }),
    ).toBeInTheDocument();
    const asked = calls();
    expect(asked.filter((p) => p === READ)).toHaveLength(1);
    expect(asked.filter((p) => readResources.includes(p))).toEqual([CAPABILITIES]);
    expect(asked.length).toBeLessThanOrEqual(5);
  });

  it("reads the further event pages from the events route", async () => {
    const next = aTimelineEvent({
      seq: 6,
      type: "tool.call",
      payload: { tool: "Bash", command: "npm test", tool_use_id: "t6" },
    });
    const { calls, requests } = renderFromRead({
      [READ]: aDetailRead({ events: aPage(defaultEvents(), { next_cursor: "page-2" }) }),
      // Only the second page holds this event: a first page read again answers none.
      [`${BASE}/events`]: (request: Request) =>
        aPage(new URL(request.url).searchParams.get("cursor") === "page-2" ? [next] : []),
    });

    expect(await screen.findByText("npm test")).toBeInTheDocument();
    expect(screen.getByText("Started the session in")).toBeInTheDocument();
    const pages = requests
      .map((r) => new URL(r.url))
      .filter((url) => url.pathname === `${BASE}/events`);
    expect(pages).toHaveLength(1);
    expect(Object.fromEntries(pages[0]?.searchParams ?? [])).toEqual({
      cursor: "page-2",
      limit: "1000",
    });
    expect(calls().filter((p) => p === READ)).toHaveLength(1);
  });

  it("keeps the loaded event pages when the session is opened again", async () => {
    const next = aTimelineEvent({
      seq: 6,
      type: "tool.call",
      payload: { tool: "Bash", command: "npm test", tool_use_id: "t6" },
    });
    const apiRoutes: ApiRoutes = {
      [READ]: aDetailRead({ events: aPage(defaultEvents(), { next_cursor: "page-2" }) }),
      [`${BASE}/events`]: (request: Request) =>
        aPage(new URL(request.url).searchParams.get("cursor") === "page-2" ? [next] : []),
    };
    const queryClient = createQueryClient();
    const first = renderFromRead(apiRoutes, queryClient);
    // Both pages loaded: the read's first, then the second from the events route.
    expect(await screen.findByText("npm test")).toBeInTheDocument();
    first.unmount();

    // Opened again: its read answers the first page only, as on the first visit.
    const { calls } = renderFromRead(apiRoutes, queryClient);
    await waitFor(() => {
      expect(calls()).toContain(READ);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });

    // The second page is kept, not dropped and read again.
    expect(calls().filter((p) => p === `${BASE}/events`)).toEqual([]);
    expect(screen.queryByText("npm test")).toBeInTheDocument();
  });

  it("opens the parent session from its own read when its crumb is followed", async () => {
    const PARENT = anId(2, "9c4e12aa");
    const PARENT_BASE = `/api/v1/sessions/${PARENT}`;
    const PARENT_READ = `/api/v1/screens/session-detail/${PARENT}`;
    const parent = aSession({
      id: PARENT,
      status: "ended",
      outcome: "done",
      ended_at: at(900),
      label: onTicket,
    });
    const parentSummary = aSessionSummary({
      session_id: PARENT,
      lines: [{ event_id: anId(3, "0192aaaa"), text: "Planned the ticket summaries" }],
    });
    const { calls } = renderFromRead({
      // A subagent's session, whose header links the session that started it.
      [READ]: aDetailRead({
        session: aSession({
          status: "ended",
          outcome: "done",
          ended_at: at(900),
          label: onTicket,
          parent_session_id: PARENT,
        }),
      }),
      [PARENT_READ]: aDetailRead({ session: parent, summary: parentSummary }),
      // The parent's own routes answer as its read does: only the calls tell them apart.
      [PARENT_BASE]: parent,
      [`${PARENT_BASE}/events`]: aPage(defaultEvents()),
      [`${PARENT_BASE}/summary`]: parentSummary,
    });
    expect(await screen.findByText("Ran make check-fast: passed")).toBeInTheDocument();
    const before = calls().length;

    // The crumb moves to the parent in place: the screen stays mounted.
    fireEvent.click(screen.getByRole("link", { name: "Session 9c4e12aa" }));
    expect(await screen.findByText("Planned the ticket summaries")).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });

    const asked = calls().slice(before);
    const parentResources = [
      PARENT_BASE,
      `${PARENT_BASE}/events`,
      `${PARENT_BASE}/summary`,
      `${PARENT_BASE}/problems`,
      "/api/v1/features",
      CAPABILITIES,
    ];
    expect(asked.filter((p) => p === PARENT_READ)).toHaveLength(1);
    expect(asked.filter((p) => parentResources.includes(p))).toEqual([]);
    expect(asked.length).toBeLessThanOrEqual(5);
  });
});
