import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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
  anId,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

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
      label: aSessionLabel({ issue: "DEMO-1511", repo: "demo", branch: "main" }),
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
    [SESSIONS]: aPage(sessions(), { next_cursor: "c2" }),
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
    const table = screen.getByRole("table", { name: "Sessions" });
    expect(within(table).getByText("Live")).toBeInTheDocument();
    expect(within(table).getByText("Error")).toBeInTheDocument();
    expect(within(table).getAllByText("$1.2500")).toHaveLength(2);
    expect(within(table).getAllByText("3")).toHaveLength(3);
    expect(within(table).getByText("—")).toBeInTheDocument();
    expect(screen.getByText(/Showing 2 of ~2 · 7 d · 1 project/)).toBeInTheDocument();
  });

  it("names each session by its label over repo · branch and has no Agent column (label, AC-201.4)", async () => {
    renderList(routes());

    await screen.findByText("DEMO-1511 · /feature");
    const table = screen.getByRole("table", { name: "Sessions" });
    expect(within(table).getByText("demo · main")).toBeInTheDocument();
    expect(within(table).getByText("agent-hub · dev/agh-48-live-tiles")).toBeInTheDocument();
    const headers = () =>
      within(screen.getByRole("table", { name: "Sessions" }))
        .getAllByRole("columnheader")
        .map((th) => th.textContent);
    expect(headers()).toContain("Session");
    expect(headers()).not.toContain("Agent");
    expect(
      within(table)
        .queryAllByText(/\bmain\b/)
        .map((node) => node.textContent),
    ).toEqual(["demo · main"]);

    fireEvent.click(screen.getByRole("button", { name: "Compact rows" }));
    expect(headers()).toContain("Session");
    expect(headers()).not.toContain("Agent");
    expect(screen.getByText("DEMO-1511 · /feature")).toBeInTheDocument();
  });

  it("sends filters from the URL and the rail to the API", async () => {
    const { requests, router } = renderList(routes(), "/sessions?outcome=error&period=24 h");
    await screen.findByText("/evaluator");

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
            ? aPage([aSession({ id: anId(3, "aaaa0003"), label: named("third") })])
            : aPage(sessions(), { next_cursor: "c2" }),
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(requests.map((r) => r.url).join(" ")).toContain("cursor=c2");
    });
    expect(await screen.findByText("/third")).toBeInTheDocument();
    expect(screen.getByText("Showing all 3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
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
    expect(screen.getByRole("columnheader", { name: "Model" })).toBeInTheDocument();
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
    expect(await screen.findByText("Could not load sessions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
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

  it("lists the agent sessions with their status and links to each chat", async () => {
    renderList(routes({ [AGENT]: { items: [anAgentSession({ status: "idle" })] } }));

    const link = await screen.findByRole("link", { name: "Run the tests" });
    expect(link).toHaveAttribute("href", `/agent-sessions/${anAgentSession().id}`);
    expect(
      within(screen.getByRole("list", { name: "Agent sessions" })).getByText("Idle"),
    ).toBeInTheDocument();
  });
});

describe("SessionsListScreen agent sessions (permission)", () => {
  it("highlights a session waiting for a permission answer", async () => {
    renderList(
      routes({
        [AGENT]: {
          items: [
            anAgentSession({
              status: "waiting_permission",
              open_permission: aPermissionRequest(),
            }),
          ],
        },
      }),
    );

    expect(await screen.findByText("1 waiting for you")).toBeInTheDocument();
    expect(screen.getByText(/Waiting for you: Bash/)).toBeInTheDocument();
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
