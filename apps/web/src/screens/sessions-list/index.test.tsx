import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aCloudSession,
  aPage,
  aPermissionRequest,
  aProblem,
  aWorkdir,
  anAgentSession,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anId,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

// These tests read the tables; the grid is the default view (AC-234.3).
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "table");
});

const SESSIONS = "/api/v1/sessions";
const AGENT = "/api/v1/agent-sessions";

function named(name: string) {
  return aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
}

function sessions() {
  return [
    aSession({
      id: anId(1, "aaaa0001"),
      label: named("evaluator"),
      status: "live",
      outcome: null,
    }),
    aSession({
      id: anId(2, "aaaa0002"),
      agent: "main",
      label: aSessionLabel({ issue: "TIP-1511", repo: "tipple", branch: "main" }),
      status: "ended",
      outcome: "error",
      ended_at: at(1800),
      errors: 2,
      guard_denials: 1,
      run_id: "a1b2c3d4e5f6",
      step: "implement",
      attempt: 2,
      has_transcript: false,
    }),
  ];
}

function routes(overrides: ApiRoutes = {}): ApiRoutes {
  return {
    [SESSIONS]: aSessionsByStatus(sessions(), { next_cursor: "c2" }),
    "/api/v1/projects": aPage([aProjectSummary(), aProjectSummary({ name: "loki-trader" })]),
    [AGENT]: { items: [] },
    [`${AGENT}/capabilities`]: aCapabilities(),
    [`${AGENT}/workdirs`]: { items: [aWorkdir()], warnings: [] },
    [`${AGENT}/resumable`]: { items: [] },
    [`${AGENT}/cloud`]: { items: [] },
    ...overrides,
  };
}

function renderList(apiRoutes: ApiRoutes, path = "/sessions") {
  return renderWithApi(<SessionsListScreen />, { routes: apiRoutes, path });
}

describe("SessionsListScreen", () => {
  it("lists sessions with outcome, cost, errors and transcript columns", async () => {
    renderList(routes());

    await screen.findByText("/evaluator");
    const live = screen.getByRole("table", { name: "Live sessions" });
    const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
    const inTables = (text: string) =>
      [live, ended].flatMap((table) => within(table).queryAllByText(text));
    expect(within(live).getByText("Live")).toBeInTheDocument();
    expect(within(ended).getByText("Error")).toBeInTheDocument();
    expect(inTables("$1.2500")).toHaveLength(2);
    expect(inTables("3")).toHaveLength(3);
    expect(inTables("—")).toHaveLength(1);
    expect(screen.getByText(/Showing 2 of ~2 · Ended: last 7 d · 1 project/)).toBeInTheDocument();
  });

  it("names each session by its label over repo · branch and has no Agent column (label, AC-201.4)", async () => {
    renderList(routes());

    await screen.findByText("TIP-1511 · /feature");
    const ended = screen.getByRole("table", { name: "Ended or failed sessions" });
    expect(within(ended).getByText("tipple · main")).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: "Live sessions" })).getByText(
        "agent-hub · dev/agh-48-live-tiles",
      ),
    ).toBeInTheDocument();
    const headers = () =>
      within(screen.getByRole("table", { name: "Live sessions" }))
        .getAllByRole("columnheader")
        .map((th) => th.textContent);
    expect(headers()).toContain("Session");
    expect(headers()).not.toContain("Agent");
    expect(
      screen
        .getAllByRole("table")
        .flatMap((table) => within(table).queryAllByText(/\bmain\b/))
        .map((node) => node.textContent),
    ).toEqual(["tipple · main"]);

    fireEvent.click(screen.getByRole("button", { name: "Compact rows" }));
    expect(headers()).toContain("Session");
    expect(headers()).not.toContain("Agent");
    expect(screen.getByText("TIP-1511 · /feature")).toBeInTheDocument();
  });

  it("sends filters from the URL and the rail to the API", async () => {
    const { requests, router } = renderList(routes(), "/sessions?outcome=error&period=24 h");
    // An outcome asks only the Ended section.
    await screen.findByText("TIP-1511 · /feature");
    expect(screen.queryByText("/evaluator")).toBeNull();

    const first = new URL(requests.find((r) => new URL(r.url).pathname === SESSIONS)?.url ?? "");
    expect(first.searchParams.get("outcome")).toBe("error");
    expect(first.searchParams.get("from")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Remove filter Outcome error" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Had a guard denial/ }));
    expect(router.state.location.search).toContain("guard_denial=1");
    fireEvent.click(screen.getByRole("button", { name: "Bash" }));
    expect(router.state.location.search).toContain("tool=Bash");
    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(router.state.location.search).toBe("");
  });

  it("loads the next page, sorts by cost and opens a session when its row is clicked", async () => {
    const { router, requests } = renderList(
      routes({
        [SESSIONS]: (request: Request) =>
          new URL(request.url).searchParams.get("cursor") === "c2"
            ? aPage([aSession({ id: anId(3, "aaaa0003"), label: named("third"), status: "live" })])
            : aSessionsByStatus(sessions(), { next_cursor: "c2" })(request),
      }),
    );
    const live = await screen.findByRole("region", { name: /^Live/ });
    fireEvent.click(await within(live).findByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(requests.map((r) => r.url).join(" ")).toContain("cursor=c2");
    });
    expect(await within(live).findByText("/third")).toBeInTheDocument();
    expect(within(live).getByText("Showing all 2")).toBeInTheDocument();

    fireEvent.click(within(live).getByRole("button", { name: /^Cost/ }));
    expect(router.state.location.search).toBe("?sort=-cost");
    await waitFor(() => {
      expect(requests.some((r) => new URL(r.url).searchParams.get("sort") === "-cost")).toBe(true);
    });

    fireEvent.click(await screen.findByText("/evaluator"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(1, "aaaa0001")}`);
  });

  it("selects two sessions with Compare disabled for Phase 3, and changes columns and density", async () => {
    renderList(routes());
    await screen.findByText("/evaluator");

    const boxes = screen.getAllByRole("checkbox", { name: "Select row" });
    boxes.forEach((box) => fireEvent.click(box));
    const compare = screen.getByRole("button", { name: /Compare 2 sessions/ });
    expect(compare).toBeDisabled();
    expect(compare).toHaveAttribute("title", "Available in Phase 3. This version is read-only.");

    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Model" }));
    expect(screen.getAllByRole("columnheader", { name: "Model" })).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Compact rows" }));
    expect(document.querySelector('[data-density="compact"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Default" }));
    fireEvent.click(screen.getByRole("button", { name: /Live now/ }));
    expect(screen.getByRole("button", { name: "Live now" })).toBeInTheDocument();
  });

  it("shows loading, empty, filtered empty, error and stale states", async () => {
    const pending = renderList(routes({ [SESSIONS]: "pending" }));
    await waitFor(() => {
      expect(pending.container.querySelector(".ah-skel")).not.toBeNull();
    });
    pending.unmount();

    const empty = renderList(routes({ [SESSIONS]: aPage([]) }));
    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Each Claude Code session in a registered hub is listed here after its first event.",
      ),
    ).toBeInTheDocument();
    empty.unmount();

    const filtered = renderList(routes({ [SESSIONS]: aPage([]) }), "/sessions?outcome=error");
    expect(await screen.findByText("No sessions match these filters.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Widen to 30 d" })).toBeInTheDocument();
    filtered.unmount();

    const failed = renderList(
      routes({
        [SESSIONS]: aProblem({
          status: 400,
          title: "Bad filter",
          detail: "Filter `cost_min` must be a decimal (status 400).",
        }),
      }),
    );
    // Each section reports its own error (four sections asked).
    expect(await screen.findAllByText(/^Could not load .+ sessions$/)).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: "Try again" })).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: "Clear filters" })).toHaveLength(4);
    failed.unmount();

    renderList(routes());
    expect(await screen.findByText(/Stale · as of/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Minimum cost" }), {
      target: { value: "1,5" },
    });
    expect(screen.getByText("Use a decimal with a dot, e.g. 1.5")).toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderList(routes());
    await screen.findByText("/evaluator");

    expect(await seriousViolations(container)).toEqual([]);
  });
});

async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as unknown;
}

describe("SessionsListScreen agent sessions (new-session)", () => {
  it("starts a session from New session and opens its chat", async () => {
    const created = anAgentSession({ id: anId(7, "0192a5e5"), status: "running" });
    const view = renderList(
      routes({
        [`POST ${AGENT}`]: created,
        [`${AGENT}/workdirs`]: {
          items: [
            aWorkdir(),
            aWorkdir({ label: "agent-hub", kind: "repo", workdir_id: "0123456789abcdef" }),
          ],
          warnings: [],
        },
      }),
      "/sessions?scope=agent-hub",
    );

    await userEvent.click(await screen.findByRole("button", { name: "New session" }));
    const dialog = screen.getByRole("dialog", { name: "New session" });
    expect(
      within(within(dialog).getByRole("combobox", { name: "Working folder" }))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["agent-hub-hub (hub)", "agent-hub (repo)"]);
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "First prompt (optional)" }),
      "Run the tests",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(await bodyOf(post)).toMatchObject({
      project: "agent-hub",
      workdir_id: aWorkdir().workdir_id,
      mode: "default",
      prompt: "Run the tests",
    });
    const workdirs = view.requests.find((r) => new URL(r.url).pathname === `${AGENT}/workdirs`);
    expect(new URL(workdirs?.url ?? "").searchParams.get("project")).toBe("agent-hub");
  });
});

/** Observed rows plus a twin of driven session A; driven B..F have no twin (AC-234.8). */
/** An ISO time `days` before now: the period bounds Ended against the real clock. */
const daysAgo = (days: number) => new Date(Date.now() - days * 86_400_000).toISOString();

function drivenFixture(
  twinStatus: "idle" | "waiting_permission" = "idle",
  observed: ApiRoutes[string] | null = null,
) {
  const twin = aSession({
    id: anId(3, "aaaa0003"),
    label: named("twin"),
    status: "live",
    outcome: null,
    agent_session_id: anId(11, "0192a5e5"),
  });
  const driven = [
    anAgentSession({
      id: anId(11, "0192a5e5"),
      title: "Twin chat",
      status: twinStatus,
      observed_session_id: twin.id,
    }),
    anAgentSession({ id: anId(12, "0192a5e5"), title: "Fix the build", status: "running" }),
    anAgentSession({
      id: anId(13, "0192a5e5"),
      title: "Approve me",
      status: "waiting_permission",
      open_permission: aPermissionRequest(),
    }),
    anAgentSession({ id: anId(14, "0192a5e5"), title: "Older idle", created_at: at(10) }),
    anAgentSession({ id: anId(15, "0192a5e5"), title: "Newer idle", created_at: at(200) }),
    anAgentSession({
      id: anId(16, "0192a5e5"),
      title: "Broke",
      status: "failed",
      created_at: daysAgo(1),
    }),
    anAgentSession({
      id: anId(17, "0192a5e5"),
      title: "Ancient",
      status: "failed",
      created_at: daysAgo(30),
    }),
  ];
  return routes({
    [SESSIONS]: observed ?? aSessionsByStatus([...sessions(), twin]),
    [AGENT]: { items: driven },
  });
}

const table = (name: string) => screen.getByRole("table", { name: `${name} sessions` });
const rowOf = (text: string) => screen.getByText(text).closest("tr");

describe("SessionsListScreen driven sessions in the list (driven-in-list)", () => {
  it("shows a twin once with a Chat badge, and twinless ones in their section with their counts", async () => {
    const view = renderList(drivenFixture());

    await screen.findByText("Fix the build");
    expect(within(table("Live")).getByText("/twin")).toBeInTheDocument();
    expect(within(rowOf("/twin") ?? document.body).getByText("Chat")).toBeInTheDocument();
    expect(screen.queryByText("Twin chat")).toBeNull();
    expect(within(table("Live")).getByText("Fix the build")).toBeInTheDocument();
    expect(within(table("Waiting")).getByText("Approve me")).toBeInTheDocument();
    expect(within(table("Ended or failed")).getByText("Broke")).toBeInTheDocument();
    const idle = within(table("Idle"))
      .getAllByText(/idle$/)
      .map((node) => node.textContent);
    expect(idle).toEqual(["Newer idle", "Older idle"]);
    expect(screen.getByRole("button", { name: "Waiting · 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Live · 3" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Idle · 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ended or failed · 2" })).toBeInTheDocument();

    fireEvent.click(rowOf("/twin") as HTMLElement);
    expect(view.router.state.location.pathname).toBe(`/agent-sessions/${anId(11, "0192a5e5")}`);
  });

  it("bounds Ended's twinless driven sessions by the period, rows and count alike", async () => {
    const view = renderList(drivenFixture());

    await screen.findByText("Broke");
    expect(screen.queryByText("Ancient")).toBeNull();
    expect(screen.getByRole("button", { name: "Ended or failed · 2" })).toBeInTheDocument();
    // Waiting, Live and Idle are not bounded (O-4): the idle one from T0 still shows.
    expect(screen.getByText("Older idle")).toBeInTheDocument();
    view.unmount();

    renderList(drivenFixture(), "/sessions?period=All");
    expect(await screen.findByText("Ancient")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ended or failed · 3" })).toBeInTheDocument();
  });

  it("shows a twinless row's folder, mode, model and cost", async () => {
    renderList(drivenFixture());

    const row = (await screen.findByText("Fix the build")).closest("tr") as HTMLElement;
    expect(within(row).getByText("agent-hub-hub · Ask before edits · sonnet")).toBeInTheDocument();
    expect(within(row).getByText("$0.0012")).toBeInTheDocument();
  });

  it("adds placed rows and drops moved ones once in the paged footer and the count line", async () => {
    const twin = aSession({
      id: anId(3, "aaaa0003"),
      label: named("twin"),
      status: "live",
      outcome: null,
      agent_session_id: anId(11, "0192a5e5"),
    });
    const others = aSessionsByStatus(sessions());
    const observed = (request: Request) =>
      new URL(request.url).searchParams.get("status") === "live"
        ? { items: [sessions()[0], twin], next_cursor: "c2", total_estimate: 120 }
        : others(request);
    renderList(drivenFixture("waiting_permission", observed));

    await screen.findByText("Fix the build");
    // Live: 120 observed, + "Fix the build", - the twin moved to Waiting; 2 rows loaded.
    expect(screen.getByRole("button", { name: "Live · ~120" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Live · ~120" })).getByText("Showing 2 of ~120"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Waiting · 2" })).toBeInTheDocument();
    // Waiting 2 + Live 2 + Idle 2 + Ended 2 rows; 2 + 120 + 2 + 2 counted.
    expect(screen.getByText(/^Showing 8 of ~126 ·/)).toBeInTheDocument();
  });

  it("opens a twinless driven session's chat from its row", async () => {
    const view = renderList(drivenFixture());

    fireEvent.click((await screen.findByText("Fix the build")).closest("tr") as HTMLElement);
    expect(view.router.state.location.pathname).toBe(`/agent-sessions/${anId(12, "0192a5e5")}`);
  });

  it("moves a twin whose driven session waits on a permission into Waiting, out of Live's count", async () => {
    renderList(drivenFixture("waiting_permission"));

    await screen.findByText("/twin");
    expect(within(table("Waiting")).getByText("/twin")).toBeInTheDocument();
    expect(within(rowOf("/twin") ?? document.body).getByText("Waiting")).toBeInTheDocument();
    expect(within(table("Live")).queryByText("/twin")).toBeNull();
    expect(screen.getByRole("button", { name: "Waiting · 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Live · 2" })).toBeInTheDocument();
  });

  it("leaves twinless driven sessions out while a filter they cannot match is on", async () => {
    renderList(drivenFixture(), "/sessions?repo=agent-hub");

    await screen.findByText("/twin");
    expect(within(rowOf("/twin") ?? document.body).getByText("Chat")).toBeInTheDocument();
    expect(screen.queryByText("Fix the build")).toBeNull();
    expect(screen.queryByText("Approve me")).toBeNull();
  });

  it("has New session in the page header, no driven region, and cloud guidance closed below the sections", async () => {
    renderList(routes({ [AGENT]: { items: [anAgentSession()] } }));

    // New session waits on three queries (list, capabilities, folders); a loaded runner needs > 1 s.
    const button = await screen.findByRole("button", { name: "New session" }, { timeout: 5000 });
    const heading = screen.getByRole("heading", { level: 1, name: "Sessions" });
    expect(heading.parentElement).toContainElement(button);
    expect(screen.queryByRole("region", { name: "Driven from hub web" })).toBeNull();
    const cloud = screen.getByText("Cloud sessions").closest("details");
    expect(cloud).not.toHaveAttribute("open");
    expect(
      table("Live").compareDocumentPosition(cloud as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it.each([
    [aProblem({ status: 401, title: "Locked" }), "Session control is locked in this browser."],
    [
      aProblem({ status: 404, title: "Off", type: "urn:agent-hub:problem:agent-sessions-off" }),
      "Session control is off in the container.",
    ],
    [
      aProblem({ status: 503, title: "Unavailable", detail: "Install agent-hub[sessions]" }),
      "Sessions cannot start here. Install agent-hub[sessions]",
    ],
  ])("shows the existing banner instead of New session on %#", async (problem, text) => {
    renderList(routes({ [AGENT]: problem, [`${AGENT}/capabilities`]: problem }));

    expect(await screen.findByRole("status")).toHaveTextContent(text);
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
    expect(screen.getByRole("table", { name: "Live sessions" })).toBeInTheDocument();
  });

  it("offers a retry when the agent list fails otherwise, and the retry asks again", async () => {
    const { requests } = renderList(routes({ [AGENT]: aProblem({ status: 500, title: "Boom" }) }));
    const asked = (path: string) => requests.filter((r) => new URL(r.url).pathname === path).length;

    expect(await screen.findByText("Could not load the agent sessions")).toBeInTheDocument();
    const [list, caps] = [asked(AGENT), asked(`${AGENT}/capabilities`)];
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect([asked(AGENT), asked(`${AGENT}/capabilities`)]).toEqual([list + 1, caps + 1]);
    });
  });
});

describe("SessionsListScreen agent sessions (cloud)", () => {
  it("shows the cloud guidance and never posts a cloud start or follow-up", async () => {
    const view = renderList(
      routes({ [`${AGENT}/cloud`]: { items: [aCloudSession()] } }),
      "/sessions?scope=agent-hub",
    );

    await userEvent.click(await screen.findByText("Cloud sessions"));
    expect((await screen.findAllByText("cloud: limited control")).length).toBeGreaterThan(0);
    expect(screen.getByText("claude --teleport cse_01synthetic")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Task" }), "Upgrade the linter");

    expect(screen.getByRole("group", { name: "Cloud start command" })).toHaveTextContent(
      "claude --cloud 'Upgrade the linter'",
    );
    expect(screen.queryByRole("button", { name: "Start in the cloud" })).toBeNull();
    expect(
      view.requests.filter(
        (r) => r.method === "POST" && new URL(r.url).pathname.startsWith(`${AGENT}/cloud`),
      ),
    ).toEqual([]);
  });

  it("shows guidance only when the CLI has no cloud command", async () => {
    renderList(routes({ [`${AGENT}/capabilities`]: aCapabilities({ cloud: false }) }));

    await userEvent.click(await screen.findByText("Cloud sessions"));
    expect(screen.getByText(/does not offer cloud sessions/)).toBeInTheDocument();
  });
});

describe("SessionsListScreen agent sessions (unavailable)", () => {
  it("shows the cause instead of New session when claude is missing", async () => {
    renderList(
      routes({
        [`${AGENT}/capabilities`]: aCapabilities({
          available: false,
          reason: "claude was not found on PATH",
        }),
      }),
    );

    expect(await screen.findByText(/claude was not found on PATH/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
  });

  it("tells the user to open the token link once when the cookie is missing", async () => {
    const locked = aProblem({ status: 401, title: "Session control is locked" });
    renderList(routes({ [AGENT]: locked, [`${AGENT}/capabilities`]: locked }));

    expect(await screen.findByText(/it ends with \?token=/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
  });

  it("says session control is off in the container", async () => {
    const off = aProblem({
      status: 404,
      title: "Session control is off",
      type: "urn:agent-hub:problem:agent-sessions-off",
    });
    renderList(routes({ [AGENT]: off, [`${AGENT}/capabilities`]: off }));

    expect(await screen.findByText(/off in the container/)).toBeInTheDocument();
  });
});

describe("SessionsListScreen view-toggle", () => {
  const VIEW = "ah.sessions.view";
  const tiles = () => screen.queryAllByRole("article");
  const shows = async (view: "grid" | "table") => {
    await screen.findByText("/evaluator");
    if (view === "grid") {
      expect(tiles().length).toBeGreaterThan(0);
      expect(screen.queryByRole("table")).toBeNull();
    } else {
      expect(screen.getAllByRole("table").length).toBeGreaterThan(0);
      expect(tiles()).toHaveLength(0);
    }
  };

  beforeEach(() => {
    window.localStorage.removeItem(VIEW);
  });

  it("shows the grid when neither the URL nor the stored preference sets a view", async () => {
    renderList(routes());

    await shows("grid");
    expect(screen.getByRole("button", { name: "Grid" })).toHaveAttribute("aria-pressed", "true");
  });

  it("uses the stored view, and a URL view wins over it", async () => {
    window.localStorage.setItem(VIEW, "table");
    const stored = renderList(routes());
    await shows("table");
    stored.unmount();

    renderList(routes(), "/sessions?view=grid");
    await shows("grid");
    expect(window.localStorage.getItem(VIEW)).toBe("table");
  });

  it("falls back to the grid on an unknown view in the URL or in storage", async () => {
    const url = renderList(routes(), "/sessions?view=cards");
    await shows("grid");
    url.unmount();

    window.localStorage.setItem(VIEW, "cards");
    renderList(routes());
    await shows("grid");
  });

  it("switches from the control and the v key, writing the URL and the stored view", async () => {
    const { router } = renderList(routes(), "/sessions?status=live");
    await shows("grid");

    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    await shows("table");
    expect(router.state.location.search).toBe("?status=live&view=table");
    expect(window.localStorage.getItem(VIEW)).toBe("table");

    fireEvent.keyDown(document.body, { key: "v" });
    await shows("grid");
    expect(new URLSearchParams(router.state.location.search).get("view")).toBe("grid");
    expect(window.localStorage.getItem(VIEW)).toBe("grid");
  });

  it("ignores v while typing, with a modifier, or when another handler took it", async () => {
    renderList(routes());
    await shows("grid");
    const input = screen.getByRole("textbox", { name: "Repo" });

    fireEvent.keyDown(input, { key: "v" });
    fireEvent.keyDown(document.body, { key: "v", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "v", metaKey: true });
    const taken = new KeyboardEvent("keydown", { key: "v", bubbles: true, cancelable: true });
    taken.preventDefault();
    document.body.dispatchEvent(taken);

    await shows("grid");
    expect(window.localStorage.getItem(VIEW)).toBeNull();
  });

  it("ignores v with Alt, and from a control inside an open dialog", async () => {
    renderList(routes());
    await shows("grid");

    fireEvent.keyDown(document.body, { key: "v", altKey: true });
    fireEvent.click(await screen.findByRole("button", { name: "New session" }));
    const dialog = await screen.findByRole("dialog", { name: "New session" });
    const close = within(dialog).getAllByRole("button")[0];
    if (!close) throw new Error("the dialog has no button");
    close.focus();
    fireEvent.keyDown(close, { key: "v" });

    await shows("grid");
    expect(window.localStorage.getItem(VIEW)).toBeNull();
  });
});
