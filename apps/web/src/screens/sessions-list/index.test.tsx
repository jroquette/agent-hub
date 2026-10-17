import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  aStreamCounts,
  anId,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { servedCheckout } from "../../lib/devCheckout";
import { GLOBAL_STREAM, GlobalStreamProvider } from "../../shell/GlobalStream";
import { SessionsListScreen } from "./index";

vi.mock("../../lib/devCheckout", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/devCheckout")>();
  return { ...actual, servedCheckout: vi.fn(() => null) };
});

// These tests read the list, the default view.
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "list");
});

afterEach(() => {
  vi.mocked(servedCheckout).mockReturnValue(null);
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
      label: aSessionLabel({ issue: "ACME-1511", repo: "storefront", branch: "main" }),
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

/** A group of the list, by its header. */
const group = (name: RegExp) => screen.getByRole("region", { name });
/** The groups' header buttons, as they read. */
const groupToggles = () =>
  [...document.querySelectorAll<HTMLButtonElement>("[data-group] h2 button[aria-expanded]")].map(
    (button) => button.textContent,
  );
const rowOf = (text: string) => screen.getByText(text).closest("li") as HTMLElement;
const lineOf = (text: string) => rowOf(text).querySelector(".sl-row-line")?.textContent;
const tagsOf = (text: string) =>
  [...rowOf(text).querySelectorAll(".sl-row-tag")].map((tag) => tag.textContent);

function renderList(apiRoutes: ApiRoutes, path = "/sessions") {
  return renderWithApi(<SessionsListScreen />, { routes: apiRoutes, path });
}

describe("SessionsListScreen", () => {
  it("lists each session as its title and one line, with its issue, cost and time on the right", async () => {
    renderList(routes());

    await screen.findByText("/evaluator");
    const live = group(/^Working/);
    const ended = group(/^Finished/);
    expect(within(live).getByText("/evaluator")).toBeInTheDocument();
    expect(lineOf("/evaluator")).toBe("Starting");
    expect(lineOf("ACME-1511 · /feature")).toBe("Failed · ran 30 min");
    // No column header and no status badge: the group says the status.
    expect(screen.queryByRole("columnheader")).toBeNull();
    expect(within(live).queryByText("Live")).toBeNull();
    // Two decimals on the row, four on hover.
    expect(within(live).getByText("$1.25")).toHaveAttribute("title", "$1.2500 USD");
    expect(within(ended).getByText("$1.25")).toBeInTheDocument();
    // The issue shows only where there is one; no "no issue" filler.
    expect(within(ended).getByText("ACME-1511")).toHaveClass("ah-issue");
    expect(screen.queryByText(/no issue|no run/)).toBeNull();
    // One time: last activity while open, the end once finished.
    expect(rowOf("/evaluator").querySelector("time")).toHaveAttribute("datetime", at(600));
    expect(rowOf("/evaluator").querySelector("time")?.getAttribute("title")).toMatch(
      /^Last activity /,
    );
    expect(rowOf("ACME-1511 · /feature").querySelector("time")).toHaveAttribute(
      "datetime",
      at(1800),
    );
    expect(rowOf("ACME-1511 · /feature").querySelector("time")?.getAttribute("title")).toMatch(
      /^Ended /,
    );
    // No transcript, turns or tokens in the list.
    expect(screen.queryByText("local file")).toBeNull();
    expect(screen.queryByText("6,400")).toBeNull();
  });

  it("names each session by its label, a repo only when it differs from the common one, never main (label, AC-201.4)", async () => {
    renderList(routes());

    await screen.findByText("ACME-1511 · /feature");
    // The common repo (agent-hub) is not repeated; storefront is, without its main branch.
    expect(tagsOf("ACME-1511 · /feature")).toEqual([
      "Terminal",
      "Run AGH-48 · implement",
      "storefront",
    ]);
    expect(tagsOf("/evaluator")).toEqual(["Terminal", "dev/agh-48-live-tiles"]);
    expect(screen.queryByText(/\bmain\b/)).toBeNull();
    // The title is a real link to the session.
    expect(
      within(group(/^Finished/)).getByRole("link", { name: "ACME-1511 · /feature" }),
    ).toHaveAttribute("href", `/sessions/${anId(2, "aaaa0002")}`);
  });

  it("sends filters from the URL and the Filters popover to the API", async () => {
    const { requests, router } = renderList(routes(), "/sessions?outcome=error&period=24 h");
    // An outcome asks only the Finished section.
    await screen.findByText("ACME-1511 · /feature");
    expect(screen.queryByText("/evaluator")).toBeNull();

    const asked = requests.filter((r) => new URL(r.url).pathname === SESSIONS);
    expect(asked).toHaveLength(1);
    const first = new URL(asked[0]?.url ?? "");
    expect(first.searchParams.get("status")).toBe("ended");
    expect(first.searchParams.get("outcome")).toBe("error");
    expect(first.searchParams.get("from")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Remove filter Outcome Error" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Period: Last 24 hours" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Filters · 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Had a guard denial/ }));
    expect(router.state.location.search).toContain("guard_denial=1");
    fireEvent.click(screen.getByRole("button", { name: "Bash" }));
    expect(router.state.location.search).toContain("tool=Bash");
    await waitFor(() => {
      const last = new URL(requests.at(-1)?.url ?? "");
      expect([last.searchParams.get("tool"), last.searchParams.get("guard_denial")]).toEqual([
        "Bash",
        "true",
      ]);
    });
    expect(screen.getByRole("button", { name: "Filters · 3" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(router.state.location.search).toBe("");
  });

  it("loads the next page in a group and opens a session when its row is clicked", async () => {
    const { router, requests } = renderList(
      routes({
        [SESSIONS]: (request: Request) =>
          new URL(request.url).searchParams.get("cursor") === "c2"
            ? aPage([aSession({ id: anId(3, "aaaa0003"), label: named("third"), status: "live" })])
            : aSessionsByStatus(sessions(), { next_cursor: "c2" })(request),
      }),
    );
    const live = await screen.findByRole("region", { name: /^Working/ });
    expect(await within(live).findByText("Showing 1 of ~1")).toBeInTheDocument();
    fireEvent.click(await within(live).findByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(requests.map((r) => r.url).join(" ")).toContain("cursor=c2");
    });
    expect(await within(live).findByText("/third")).toBeInTheDocument();
    expect(within(live).queryByRole("button", { name: "Load more" })).toBeNull();

    fireEvent.click(rowOf("/evaluator"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(1, "aaaa0001")}`);
  });

  it("shows loading, empty, filtered empty, error and stale states", async () => {
    const pending = renderList(routes({ [SESSIONS]: "pending" }));
    await waitFor(() => {
      expect(pending.container.querySelector(".ah-skel")).not.toBeNull();
    });
    // The group counts wait for their sections.
    expect(screen.getByRole("button", { name: "Needs you · …" })).toBeInTheDocument();
    expect(screen.queryByText(/needs? you\./)).toBeNull();
    pending.unmount();

    const empty = renderList(routes({ [SESSIONS]: aPage([]) }));
    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    empty.unmount();

    const filtered = renderList(routes({ [SESSIONS]: aPage([]) }), "/sessions?outcome=error");
    expect(await screen.findByText("No sessions match these filters.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show last 30 days" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Clear filters" }).length).toBeGreaterThan(0);
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
    failed.unmount();

    renderList(routes());
    expect(await screen.findByText(/Stale · as of/)).toBeInTheDocument();
  });

  it("empty: says how to start a session with claude when there has never been one", async () => {
    renderList(routes({ [SESSIONS]: aPage([]) }), "/sessions?period=All");

    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Each Claude Code session in a registered hub is listed here after its first event\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("cd ~/agent-hub-hub && claude")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all time" })).not.toBeInTheDocument();
    // New session stays in the header.
    expect(
      await screen.findByRole("button", { name: "New session" }, { timeout: 5000 }),
    ).toBeInTheDocument();
  });

  it("offline: shows the collector's as-of stamp only while the collector is offline", async () => {
    // Without the shell's stream the collector has never answered: offline.
    const offline = renderList(routes());
    await screen.findByText("/evaluator");
    expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    offline.unmount();

    const { stream } = renderWithApi(
      <GlobalStreamProvider project={null}>
        <SessionsListScreen />
      </GlobalStreamProvider>,
      { routes: routes(), path: "/sessions" },
    );
    await screen.findByText("/evaluator");
    act(() => {
      stream(GLOBAL_STREAM).open();
      stream(GLOBAL_STREAM).emit("counts", aStreamCounts());
    });

    expect(screen.queryByText(/Stale · as of/)).not.toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderList(routes());
    await screen.findByText("/evaluator");

    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious or critical a11y violation in the grid, grouped by run", async () => {
    const waiting = aSession({
      id: anId(4, "aaaa0004"),
      label: named("asks"),
      status: "waiting",
      outcome: null,
      waiting_reason: "Permission prompt",
      agent_session_id: anId(11, "0192a5e5"),
    });
    const { container } = renderList(
      routes({ [SESSIONS]: aSessionsByStatus([...sessions(), waiting]) }),
      "/sessions?view=grid&within=run",
    );
    const tile = await screen.findByRole("article", { name: /^\/asks in / });
    expect(within(tile).getByRole("link", { name: "Open chat" })).toBeInTheDocument();
    expect(within(tile).getByText("Chat")).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: "Not in a run" }).length).toBeGreaterThan(0);

    expect(await seriousViolations(container)).toEqual([]);
  });
});

async function bodyOf(request: Request | undefined): Promise<unknown> {
  if (!request) throw new Error("no request");
  return JSON.parse(await request.clone().text()) as unknown;
}

describe("SessionsListScreen agent sessions (new-session)", () => {
  it("starts New session in the served checkout's project, folder and Auto (make playground)", async () => {
    // The same vector as devCheckout.test.ts and core's test_workdirs.py (E6).
    vi.mocked(servedCheckout).mockReturnValue("/srv/demo/agent-hub");
    const view = renderList(
      routes({
        "/api/v1/projects": aPage([
          aProjectSummary({ name: "storefront" }),
          aProjectSummary({ name: "agent-hub" }),
        ]),
        [`${AGENT}/workdirs`]: (request: Request) =>
          new URL(request.url).searchParams.get("project") === "agent-hub"
            ? {
                items: [
                  aWorkdir(),
                  aWorkdir({ label: "agent-hub", kind: "repo", workdir_id: "5703fef9dd5a3894" }),
                ],
                warnings: [],
              }
            : {
                items: [aWorkdir({ label: "storefront-hub", workdir_id: "0000000000000001" })],
                warnings: [],
              },
      }),
      "/sessions?scope=storefront",
    );

    await waitFor(
      () => {
        const asked = view.requests
          .filter((r) => new URL(r.url).pathname === `${AGENT}/workdirs`)
          .map((r) => new URL(r.url).searchParams.get("project"));
        expect(asked).toContain("agent-hub");
        expect(screen.getByRole("button", { name: "New session" })).toBeInTheDocument();
      },
      { timeout: 3000 },
    );
    await userEvent.click(screen.getByRole("button", { name: "New session" }));
    const dialog = screen.getByRole("dialog", { name: "New session" });
    // "Where" may leave the served project for the scope's (AGH-262, AC-234.14).
    expect(within(dialog).getByRole("combobox", { name: "Project" })).toHaveValue("agent-hub");
    expect(within(dialog).getByRole("combobox", { name: "Working folder" })).toHaveValue(
      "5703fef9dd5a3894",
    );
    expect(within(dialog).getByRole("button", { name: "Options" })).toHaveAccessibleDescription(
      /^Auto ·/,
    );
  });

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
    await userEvent.type(within(dialog).getByRole("textbox", { name: "Prompt" }), "Run the tests");
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

  it("new-session-dialog: no project select on the page; Where picks the project and its folders", async () => {
    const created = anAgentSession({ id: anId(9, "0192a5e5"), status: "running" });
    const view = renderList(
      routes({
        [`POST ${AGENT}`]: created,
        [`${AGENT}/workdirs`]: (request: Request) => ({
          items: [
            aWorkdir(
              new URL(request.url).searchParams.get("project") === "loki-trader"
                ? { label: "loki-hub", workdir_id: "00000000000000bb" }
                : {},
            ),
          ],
          warnings: [],
        }),
      }),
    );

    await userEvent.click(
      await screen.findByRole("button", { name: "New session" }, { timeout: 5000 }),
    );
    expect(screen.queryByText("Start sessions in")).toBeNull();
    const dialog = screen.getByRole("dialog", { name: "New session" });
    const project = within(dialog).getByRole("combobox", { name: "Project" });
    expect(screen.getAllByRole("combobox", { name: "Project" })).toEqual([project]);
    await userEvent.selectOptions(project, "loki-trader");
    expect(
      await within(dialog).findByRole("option", { name: "loki-hub (hub)" }),
    ).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Start session" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    expect(await bodyOf(post)).toMatchObject({
      project: "loki-trader",
      workdir_id: "00000000000000bb",
    });
    expect(view.requests.some((r) => new URL(r.url).pathname === `${AGENT}/resumable`)).toBe(false);
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

describe("SessionsListScreen driven sessions in the list (driven-in-list)", () => {
  it("shows a twin once as a chat, and twinless ones in their group with their counts", async () => {
    const view = renderList(drivenFixture());

    await screen.findByText("Fix the build");
    // The twin reads its driven session's prompt until Claude Code's title reaches its label.
    const live = group(/^Working/);
    expect(within(live).getByText("Twin chat")).toBeInTheDocument();
    const twin = rowOf("Twin chat");
    // A chat carries no mark; only a terminal session does.
    expect(within(twin).queryByText("Terminal")).toBeNull();
    expect(within(twin).getByRole("link", { name: "Twin chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${anId(11, "0192a5e5")}`,
    );
    expect(screen.getAllByText("Twin chat")).toHaveLength(1);
    // A long first prompt stays on one line, the whole of it on hover.
    expect(within(live).getByRole("link", { name: "Fix the build" })).toHaveAttribute(
      "title",
      "Fix the build",
    );
    expect(lineOf("Fix the build")).toBe("Working on your message");
    expect(within(group(/^Needs you/)).getByText("Approve me")).toBeInTheDocument();
    expect(lineOf("Approve me")).toBe("Asks to use Bash: git status");
    expect(within(group(/^Finished/)).getByText("Broke")).toBeInTheDocument();
    expect(lineOf("Broke")).toBe("Failed");
    const idle = within(group(/^In progress/))
      .getAllByText(/idle$/)
      .map((node) => node.textContent);
    expect(idle).toEqual(["Newer idle", "Older idle"]);
    expect(groupToggles()).toEqual([
      "Needs you · 1",
      "Working · 3",
      "In progress · 2",
      "Finished · last 7 days · 2",
    ]);

    fireEvent.click(twin);
    expect(view.router.state.location.pathname).toBe(`/agent-sessions/${anId(11, "0192a5e5")}`);
  });

  it("bounds Finished's twinless driven sessions by the period, rows and count alike", async () => {
    const view = renderList(drivenFixture());

    await screen.findByText("Broke");
    expect(screen.queryByText("Ancient")).toBeNull();
    expect(groupToggles()).toContain("Finished · last 7 days · 2");
    // Needs you, Working and Paused are not bounded (O-4): the idle one from T0 still shows.
    expect(screen.getByText("Older idle")).toBeInTheDocument();
    view.unmount();

    renderList(drivenFixture(), "/sessions?period=All");
    expect(await screen.findByText("Ancient")).toBeInTheDocument();
    expect(groupToggles()).toContain("Finished · 3");
  });

  it("resume: ended or failed driven rows and twins offer Resume, a link to the chat that resumes them", async () => {
    const twin = aSession({
      id: anId(3, "aaaa0003"),
      label: named("twin"),
      status: "ended",
      agent_session_id: anId(11, "0192a5e5"),
    });
    const fixture = drivenFixture();
    const view = renderList({
      ...fixture,
      [SESSIONS]: aSessionsByStatus([...sessions(), twin]),
      [AGENT]: {
        items: [
          anAgentSession({
            id: anId(11, "0192a5e5"),
            title: "Twin chat",
            status: "ended",
            observed_session_id: twin.id,
          }),
          anAgentSession({ id: anId(12, "0192a5e5"), title: "Fix the build", status: "running" }),
          anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" }),
          anAgentSession({
            id: anId(18, "0192a5e5"),
            title: "In the cloud",
            status: "ended",
            kind: "cloud",
          }),
        ],
      },
    });

    await screen.findByText("Broke");
    const resumes = within(group(/^Finished/)).getAllByRole("link", { name: /^Resume/ });
    // Finished is newest first: the twin was active last.
    expect(
      resumes.map((link) => [link.getAttribute("aria-label"), link.getAttribute("href")]),
    ).toEqual([
      ["Resume Twin chat", `/agent-sessions/${anId(11, "0192a5e5")}`],
      ["Resume Broke", `/agent-sessions/${anId(16, "0192a5e5")}`],
    ]);
    expect(within(rowOf("Fix the build")).queryByRole("link", { name: /^Resume/ })).toBeNull();
    expect(within(rowOf("In the cloud")).queryByRole("link", { name: /^Resume/ })).toBeNull();
    expect(within(rowOf("/evaluator")).queryByRole("link", { name: /^Resume/ })).toBeNull();

    expect(await seriousViolations(view.container)).toEqual([]);

    await userEvent.click(screen.getByRole("link", { name: "Resume Twin chat" }));
    expect(view.router.state.location.pathname).toBe(`/agent-sessions/${anId(11, "0192a5e5")}`);
  });

  it("resume: no Resume on a log-full row, or on any row where sessions cannot start", async () => {
    const broke = anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" });
    const full = anAgentSession({
      id: anId(17, "0192a5e5"),
      title: "Full",
      status: "ended",
      end_reason: "log_full",
    });
    const view = renderList({ ...drivenFixture(), [AGENT]: { items: [broke, full] } });
    await screen.findByText("Full");
    expect(within(rowOf("Broke")).getByRole("link", { name: "Resume Broke" })).toBeInTheDocument();
    expect(within(rowOf("Full")).queryByRole("link", { name: /^Resume/ })).toBeNull();
    expect(lineOf("Full")).toBe("Closed: the conversation is full");
    view.unmount();

    renderList({
      ...drivenFixture(),
      [AGENT]: { items: [broke] },
      [`${AGENT}/capabilities`]: aCapabilities({ available: false }),
    });
    await screen.findByText("Broke");
    expect(within(rowOf("Broke")).queryByRole("link", { name: /^Resume/ })).toBeNull();
  });

  it("resume: an ended twin whose driven session is not listed shows its row without Resume", async () => {
    const twin = aSession({
      id: anId(3, "aaaa0003"),
      label: named("orphan"),
      status: "ended",
      agent_session_id: anId(19, "0192a5e5"),
    });
    const broke = anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" });
    renderList({
      ...drivenFixture(),
      [SESSIONS]: aSessionsByStatus([...sessions(), twin]),
      [AGENT]: { items: [broke] },
    });

    await screen.findByText("Broke");
    expect(within(rowOf("Broke")).getByRole("link", { name: "Resume Broke" })).toBeInTheDocument();
    expect(within(rowOf("/orphan")).queryByRole("link", { name: /^Resume/ })).toBeNull();
  });

  it("shows a twinless row's cost and line, its mode and model once paused, its folder when it differs", async () => {
    renderList(drivenFixture());

    await screen.findByText("Fix the build");
    expect(within(rowOf("Fix the build")).getByText("$0.00")).toHaveAttribute(
      "title",
      "$0.0012 USD",
    );
    expect(lineOf("Newer idle")).toBe("Ask before edits mode · sonnet");
    // Most loaded rows run in agent-hub-hub: it is not repeated; the observed rows name agent-hub.
    expect(tagsOf("Fix the build")).toEqual([]);
    expect(tagsOf("/evaluator")).toEqual(["Terminal", "agent-hub · dev/agh-48-live-tiles"]);
  });

  it("adds placed rows and drops moved ones once in the paged footer, the group counts and the attention line", async () => {
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
    // Working: 120 observed, + "Fix the build", - the twin moved to Needs you; 2 rows loaded.
    expect(groupToggles()).toContain("Working · ~120");
    expect(within(group(/^Working/)).getByText("Showing 2 of ~120")).toBeInTheDocument();
    expect(groupToggles()).toContain("Needs you · 2");
    expect(document.querySelector(".sl-attention")).toHaveTextContent(
      "2 sessions need you· 120 working · 2 in progress",
    );
  });

  it("opens a twinless driven session's chat from its row", async () => {
    const view = renderList(drivenFixture());

    fireEvent.click((await screen.findByText("Fix the build")).closest("li") as HTMLElement);
    expect(view.router.state.location.pathname).toBe(`/agent-sessions/${anId(12, "0192a5e5")}`);
  });

  it("moves a twin whose driven session waits on a permission into Needs you, out of Working's count", async () => {
    renderList(drivenFixture("waiting_permission"));

    await screen.findByText("Twin chat");
    expect(within(group(/^Needs you/)).getByText("Twin chat")).toBeInTheDocument();
    const twin = rowOf("Twin chat");
    expect(lineOf("Twin chat")).toBe("Asks for a permission");
    expect(within(twin).getByRole("link", { name: "Answer Twin chat" })).toHaveAttribute(
      "href",
      `/agent-sessions/${anId(11, "0192a5e5")}`,
    );
    expect(within(group(/^Working/)).queryByText("Twin chat")).toBeNull();
    expect(groupToggles()).toEqual([
      "Needs you · 2",
      "Working · 2",
      "In progress · 2",
      "Finished · last 7 days · 2",
    ]);
  });

  it("leaves twinless driven sessions out while a filter they cannot match is on", async () => {
    renderList(drivenFixture(), "/sessions?repo=agent-hub");

    await screen.findByText("Twin chat");
    expect(within(rowOf("Twin chat")).queryByText("Terminal")).toBeNull();
    expect(screen.queryByText("Fix the build")).toBeNull();
    expect(screen.queryByText("Approve me")).toBeNull();
  });

  it("has New session in the page header, no driven region, and cloud guidance closed below the groups", async () => {
    renderList(routes({ [AGENT]: { items: [anAgentSession()] } }));

    // New session waits on three queries (list, capabilities, folders); a loaded runner needs > 1 s.
    const button = await screen.findByRole("button", { name: "New session" }, { timeout: 5000 });
    const heading = screen.getByRole("heading", { level: 1, name: "Sessions" });
    expect(heading.parentElement).toContainElement(button);
    expect(screen.queryByRole("region", { name: "Driven from hub web" })).toBeNull();
    const cloud = screen.getByText("Cloud sessions").closest("details");
    expect(cloud).not.toHaveAttribute("open");
    expect(
      group(/^Finished/).compareDocumentPosition(cloud as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
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
    expect(await screen.findByRole("region", { name: /^Working/ })).toBeInTheDocument();
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
  const shows = async (view: "grid" | "list") => {
    await screen.findByText("/evaluator");
    if (view === "grid") {
      expect(tiles().length).toBeGreaterThan(0);
      expect(document.querySelector(".sl-inbox")).toBeNull();
    } else {
      expect(document.querySelectorAll(".sl-inbox")).toHaveLength(1);
      expect(tiles()).toHaveLength(0);
    }
  };

  beforeEach(() => {
    window.localStorage.removeItem(VIEW);
  });

  it("shows the list when neither the URL nor the stored preference sets a view", async () => {
    renderList(routes());

    await shows("list");
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Grid" })).toHaveAttribute("title", "Grid view (v)");
  });

  it("uses the stored view, and a URL view wins over it", async () => {
    window.localStorage.setItem(VIEW, "grid");
    const stored = renderList(routes());
    await shows("grid");
    stored.unmount();

    renderList(routes(), "/sessions?view=list");
    await shows("list");
    expect(window.localStorage.getItem(VIEW)).toBe("grid");
  });

  it("reads table, the list's old name, from old links and stored values", async () => {
    const url = renderList(routes(), "/sessions?view=table");
    await shows("list");
    url.unmount();

    window.localStorage.setItem(VIEW, "table");
    renderList(routes());
    await shows("list");
  });

  it("falls back to the list on an unknown view in the URL or in storage", async () => {
    const url = renderList(routes(), "/sessions?view=cards");
    await shows("list");
    url.unmount();

    window.localStorage.setItem(VIEW, "cards");
    renderList(routes());
    await shows("list");
  });

  it("switches from the control and the v key, writing the URL and the stored view", async () => {
    const { router } = renderList(routes(), "/sessions?status=live");
    await shows("list");

    fireEvent.click(screen.getByRole("button", { name: "Grid" }));
    await shows("grid");
    expect(router.state.location.search).toBe("?status=live&view=grid");
    expect(window.localStorage.getItem(VIEW)).toBe("grid");
    // The Group menu is the grid's only.
    expect(screen.getByRole("button", { name: "Group: None" })).toBeInTheDocument();

    fireEvent.keyDown(document.body, { key: "v" });
    await shows("list");
    expect(new URLSearchParams(router.state.location.search).get("view")).toBe("list");
    expect(window.localStorage.getItem(VIEW)).toBe("list");
    expect(screen.queryByRole("button", { name: /^Group:/ })).toBeNull();
  });

  it("ignores v while typing, with a modifier, or when another handler took it", async () => {
    renderList(routes());
    await shows("list");
    const input = screen.getByRole("searchbox", { name: "Find sessions" });

    fireEvent.keyDown(input, { key: "v" });
    fireEvent.keyDown(document.body, { key: "v", ctrlKey: true });
    fireEvent.keyDown(document.body, { key: "v", metaKey: true });
    const taken = new KeyboardEvent("keydown", { key: "v", bubbles: true, cancelable: true });
    taken.preventDefault();
    document.body.dispatchEvent(taken);

    await shows("list");
    expect(window.localStorage.getItem(VIEW)).toBeNull();
  });

  it("ignores v with Alt, and from a control inside an open dialog", async () => {
    renderList(routes());
    await shows("list");

    fireEvent.keyDown(document.body, { key: "v", altKey: true });
    fireEvent.click(await screen.findByRole("button", { name: "New session" }));
    const dialog = await screen.findByRole("dialog", { name: "New session" });
    const close = within(dialog).getAllByRole("button")[0];
    if (!close) throw new Error("the dialog has no button");
    close.focus();
    fireEvent.keyDown(close, { key: "v" });

    await shows("list");
    expect(window.localStorage.getItem(VIEW)).toBeNull();
  });
});
