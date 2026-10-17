import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aPage,
  aPermissionRequest,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anAgentSession,
  anId,
  at,
  renderWithApi,
  type ApiRoutes,
  type Session,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

const SESSIONS = "/api/v1/sessions";
const AGENT = "/api/v1/agent-sessions";
const NO_PROBLEMS = { by_you: 0, handled: 0, needs_you: 0, open: 0 };

const named = (name: string, extra: Partial<Parameters<typeof aSessionLabel>[0]> = {}) =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`], ...extra });
const one = (n: number, status: Session["status"], name: string, extra: Partial<Session> = {}) =>
  aSession({
    id: anId(n, `dddd${String(n).padStart(4, "0")}`),
    status,
    label: named(name),
    ...(status === "ended" ? { ended_at: at(600) } : {}),
    ...extra,
  });

const SAMPLE: [Session, Session, Session, Session] = [
  one(1, "waiting", "asker", { waiting_reason: "Permission prompt" }),
  one(2, "live", "runner", { last_action: "make check-fast", last_tool: "Bash" }),
  one(3, "idle", "rester"),
  one(4, "ended", "done", { outcome: "done" }),
];

function routes(sessions: ApiRoutes[string] = aSessionsByStatus(SAMPLE), agents: unknown[] = []) {
  return {
    [SESSIONS]: sessions,
    "/api/v1/projects": aPage([aProjectSummary()]),
    [AGENT]: { items: agents },
    [`${AGENT}/capabilities`]: aCapabilities(),
  };
}

function renderList(apiRoutes: ApiRoutes = routes(), path = "/sessions") {
  return renderWithApi(<SessionsListScreen />, { routes: apiRoutes, path });
}

const tabs = () =>
  within(screen.getByRole("group", { name: "Status" }))
    .getAllByRole("button")
    .map((tab) => tab.textContent);
const tab = (name: RegExp) =>
  within(screen.getByRole("group", { name: "Status" })).getByRole("button", { name });
const groups = () =>
  screen.queryAllByRole("rowgroup").flatMap((g) => (g.dataset.group ? [g.dataset.group] : []));
/** The focused element, where a key press lands. */
function focused(): Element {
  if (!document.activeElement) throw new Error("nothing is focused");
  return document.activeElement;
}
const scrolls = vi.fn();
const rowOf = (text: string) => screen.getByText(text).closest("tr") as HTMLElement;
const sessionRequests = (requests: Request[]) =>
  requests.filter((r) => new URL(r.url).pathname === SESSIONS).map((r) => new URL(r.url));

beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "list");
  // jsdom has no layout: the keys and the attention line scroll the row they focus into view.
  Element.prototype.scrollIntoView = scrolls;
});

afterEach(() => {
  window.localStorage.clear();
});

describe("SessionsListScreen status-tabs", () => {
  it("counts every section in the tabs and shows only the chosen one, writing status to the URL", async () => {
    const { router, requests } = renderList();
    await screen.findByText("/runner");

    expect(tabs()).toEqual(["All · 4", "Waiting for you · 1", "Live · 1", "Idle · 1", "Ended · 1"]);
    expect(tab(/^All/)).toHaveAttribute("aria-pressed", "true");
    expect(groups()).toEqual(["waiting", "live", "idle", "ended"]);
    const asked = sessionRequests(requests).length;

    fireEvent.click(tab(/^Live/));
    expect(router.state.location.search).toBe("?status=live");
    expect(tab(/^Live/)).toHaveAttribute("aria-pressed", "true");
    expect(groups()).toEqual(["live"]);
    expect(screen.queryByText("/asker")).toBeNull();
    // The other tabs keep their counts: the tab asks for nothing new.
    expect(tabs()).toEqual(["All · 4", "Waiting for you · 1", "Live · 1", "Idle · 1", "Ended · 1"]);
    expect(sessionRequests(requests)).toHaveLength(asked);

    fireEvent.click(tab(/^All/));
    expect(router.state.location.search).toBe("");
    expect(groups()).toEqual(["waiting", "live", "idle", "ended"]);
  });

  it("shows a tab's group from the URL, even an empty one, which cannot collapse", async () => {
    window.localStorage.setItem("ah.sessions.collapsed", JSON.stringify(["live"]));
    renderList(
      routes(aSessionsByStatus(SAMPLE.filter((s) => s.status !== "idle"))),
      "/sessions?status=live",
    );
    await screen.findByText("/runner");

    const live = screen.getByRole("rowgroup", { name: "Live · 1" });
    expect(within(live).queryByRole("button", { name: /^Live/ })).toBeNull();
    expect(within(live).getByText("/runner")).toBeInTheDocument();

    fireEvent.click(tab(/^Idle/));
    expect(await screen.findByText("No idle session.")).toBeInTheDocument();
    expect(tab(/^Idle/)).toHaveTextContent("Idle · 0");
  });

  it("marks a count that has more pages as approximate", async () => {
    const live = { ...aPage([SAMPLE[1]], { next_cursor: "c2" }), total_estimate: 40 };
    renderList(
      routes((request: Request) =>
        new URL(request.url).searchParams.get("status") === "live"
          ? live
          : aSessionsByStatus(SAMPLE)(request),
      ),
    );
    await screen.findByText("/runner");

    expect(tabs()).toEqual([
      "All · ~43",
      "Waiting for you · 1",
      "Live · ~40",
      "Idle · 1",
      "Ended · 1",
    ]);
  });
});

describe("SessionsListScreen attention-line", () => {
  it("says one session waits for the owner, and its button focuses that row", async () => {
    renderList();
    await screen.findByText("/asker");

    const waiting = screen.getByRole("button", { name: "1 session is waiting for you" });
    expect(screen.queryByText(/problem/)).toBeNull();
    fireEvent.click(waiting);
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/asker"));
    });
  });

  it("names sessions with problems that need the owner, and focuses the first such row", async () => {
    const problem = { ...NO_PROBLEMS, needs_you: 1 };
    const sessions = [
      one(2, "live", "runner"),
      one(5, "live", "stuck", { problems: problem, needs_you_problem: "Needs you: Bash failed" }),
      one(6, "ended", "broken", { outcome: "error", problems: problem }),
    ];
    renderList(routes(aSessionsByStatus(sessions)));
    await screen.findByText("/stuck");

    expect(screen.queryByText(/waiting for you$/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "2 sessions have problems that need you" }));
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/stuck"));
    });
    // The red edge marks those rows only.
    expect(rowOf("/stuck")).toHaveAttribute("data-trouble", "true");
    expect(rowOf("/broken")).toHaveAttribute("data-trouble", "true");
    expect(rowOf("/runner")).not.toHaveAttribute("data-trouble");
    expect(within(rowOf("/stuck")).getByText("Needs you: Bash failed")).toBeInTheDocument();
  });

  it("joins both, and leaves a tab that hides the waiting row for All", async () => {
    const sessions = [
      ...SAMPLE,
      one(5, "waiting", "asker-2"),
      one(6, "live", "stuck", { problems: { ...NO_PROBLEMS, needs_you: 1 } }),
    ];
    const { router } = renderList(routes(aSessionsByStatus(sessions)), "/sessions?status=ended");
    await screen.findByText("/done");

    expect(screen.getByRole("button", { name: "2 sessions are waiting for you" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "1 session has a problem that needs you" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "2 sessions are waiting for you" }));
    expect(router.state.location.search).toBe("");
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/asker"));
    });
  });

  it("says nothing needs the owner, with how many are live", async () => {
    const calm = renderList(routes(aSessionsByStatus(SAMPLE.slice(1))));
    expect(await screen.findByText("Nothing needs you. 1 session live.")).toBeInTheDocument();
    calm.unmount();

    renderList(routes(aSessionsByStatus([SAMPLE[3]])));
    expect(await screen.findByText("Nothing needs you. No session is live.")).toBeInTheDocument();
  });
});

describe("SessionsListScreen search", () => {
  const SEARCHABLE = [
    one(1, "live", "x", {
      label: named("x", { title: "Layout da página de sessões", branch: "dev/agh-48-layout" }),
    }),
    one(2, "live", "other", { label: named("other", { issue: "AGH-52" }) }),
    one(3, "ended", "done", { outcome: "done", repo: "storefront" }),
  ];

  it("finds loaded sessions by name without accents or case, and writes q to the URL", async () => {
    const { router, requests } = renderList(routes(aSessionsByStatus(SEARCHABLE)));
    await screen.findByText("AGH-52 · /other");
    const asked = sessionRequests(requests).length;
    const search = screen.getByRole("searchbox", { name: "Find sessions" });

    fireEvent.change(search, { target: { value: "PAGINA DE SESSOES" } });
    expect(router.state.location.search).toBe("?q=PAGINA+DE+SESSOES");
    expect(screen.getByText("Layout da página de sessões")).toBeInTheDocument();
    expect(screen.queryByText("AGH-52 · /other")).toBeNull();
    expect(screen.queryByText("/done")).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("1 match");
    // Search runs on the loaded rows: no new request.
    expect(sessionRequests(requests)).toHaveLength(asked);

    // By issue, by repo; the export follows the matches.
    fireEvent.change(search, { target: { value: "agh-52" } });
    expect(screen.getByText("AGH-52 · /other")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export 1 session as CSV" })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "storefront" } });
    expect(screen.getByText("/done")).toBeInTheDocument();
    expect(groups()).toEqual(["ended"]);

    fireEvent.change(search, { target: { value: "nothing like it" } });
    expect(screen.getByText("No sessions match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(router.state.location.search).toBe("");
    expect(search).toHaveValue("");
  });

  it("focuses on /, clears on Escape, then leaves on a second Escape", async () => {
    const { router } = renderList(routes(aSessionsByStatus(SEARCHABLE)), "/sessions?q=other");
    await screen.findByText("AGH-52 · /other");
    const search = screen.getByRole("searchbox", { name: "Find sessions" });
    expect(search).toHaveValue("other");
    expect(screen.queryByText("/done")).toBeNull();

    fireEvent.keyDown(document.body, { key: "/" });
    expect(document.activeElement).toBe(search);
    fireEvent.keyDown(search, { key: "Escape" });
    expect(router.state.location.search).toBe("");
    expect(screen.getByText("/done")).toBeInTheDocument();
    expect(document.activeElement).toBe(search);
    fireEvent.keyDown(search, { key: "Escape" });
    expect(document.activeElement).not.toBe(search);
  });

  it("says it looks only through the loaded sessions while a section has more pages", async () => {
    renderList(routes(aSessionsByStatus(SEARCHABLE, { next_cursor: "c2" })), "/sessions?q=other");
    await screen.findByText("AGH-52 · /other");

    expect(
      screen.getByText(
        "Search looks through the loaded sessions only. Load more to search older ones.",
      ),
    ).toBeInTheDocument();
  });
});

describe("SessionsListScreen row-actions", () => {
  it("offers Answer on a waiting row, Open chat on a chat, Open otherwise, and Resume on a resumable chat", async () => {
    const twin = one(5, "live", "twin", { agent_session_id: anId(11, "0192a5e5") });
    const agents = [
      anAgentSession({ id: anId(11, "0192a5e5"), observed_session_id: twin.id, status: "running" }),
      anAgentSession({
        id: anId(13, "0192a5e5"),
        title: "Approve me",
        status: "waiting_permission",
        open_permission: aPermissionRequest(),
      }),
      anAgentSession({ id: anId(14, "0192a5e5"), title: "Ready", status: "idle" }),
      anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" }),
    ];
    const { container } = renderList(routes(aSessionsByStatus([...SAMPLE, twin]), agents));
    await screen.findByText("Broke");

    const action = (text: string) =>
      within(rowOf(text))
        .getAllByRole("link")
        .slice(1)
        .map((link) => [
          link.getAttribute("aria-label") ?? link.textContent,
          link.getAttribute("href"),
        ]);
    expect(action("/asker")).toEqual([["Answer /asker", `/sessions/${anId(1, "dddd0001")}`]]);
    expect(action("Approve me")).toEqual([
      ["Answer Approve me", `/agent-sessions/${anId(13, "0192a5e5")}`],
    ]);
    expect(action("/runner")).toEqual([["Open /runner", `/sessions/${anId(2, "dddd0002")}`]]);
    expect(action("Run the tests")).toEqual([
      ["Open chat Run the tests", `/agent-sessions/${anId(11, "0192a5e5")}`],
    ]);
    expect(action("Ready")).toEqual([
      ["Open chat Ready", `/agent-sessions/${anId(14, "0192a5e5")}`],
    ]);
    expect(action("Broke")).toEqual([
      ["Resume Broke", `/agent-sessions/${anId(16, "0192a5e5")}`],
      ["Open chat Broke", `/agent-sessions/${anId(16, "0192a5e5")}`],
    ]);
    expect(action("/done")).toEqual([["Open /done", `/sessions/${anId(4, "dddd0004")}`]]);
    // Only the waiting rows' action is the accent.
    expect(within(rowOf("/asker")).getByRole("link", { name: "Answer /asker" })).toHaveClass(
      "ah-btn-primary",
    );
    expect(within(rowOf("/runner")).getByRole("link", { name: "Open /runner" })).not.toHaveClass(
      "ah-btn-primary",
    );
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("opens the row's action, not the row, from its link", async () => {
    const { router } = renderList();
    await screen.findByText("/asker");

    fireEvent.click(within(rowOf("/runner")).getByRole("link", { name: "Open /runner" }));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(2, "dddd0002")}`);
  });
});

describe("SessionsListScreen row-keys", () => {
  it("moves with j and k across the groups, and opens with o", async () => {
    const { router } = renderList();
    await screen.findByText("/done");

    fireEvent.keyDown(document.body, { key: "j" });
    expect(document.activeElement).toBe(rowOf("/asker"));
    fireEvent.keyDown(focused(), { key: "j" });
    fireEvent.keyDown(focused(), { key: "j" });
    expect(document.activeElement).toBe(rowOf("/rester"));
    fireEvent.keyDown(focused(), { key: "j" });
    fireEvent.keyDown(focused(), { key: "j" });
    // The last row stays the last.
    expect(document.activeElement).toBe(rowOf("/done"));
    fireEvent.keyDown(focused(), { key: "k" });
    expect(document.activeElement).toBe(rowOf("/rester"));
    expect(scrolls).toHaveBeenCalledWith({ block: "nearest" });

    fireEvent.keyDown(focused(), { key: "o" });
    expect(router.state.location.pathname).toBe(`/sessions/${anId(3, "dddd0003")}`);
  });

  it("starts from the last row on k, skips a collapsed group, and ignores keys while typing or with a modifier", async () => {
    window.localStorage.setItem("ah.sessions.collapsed", JSON.stringify(["ended"]));
    renderList();
    await screen.findByText("/rester");

    fireEvent.keyDown(document.body, { key: "k" });
    expect(document.activeElement).toBe(rowOf("/rester"));
    fireEvent.keyDown(focused(), { key: "j", ctrlKey: true });
    expect(document.activeElement).toBe(rowOf("/rester"));
    const search = screen.getByRole("searchbox", { name: "Find sessions" });
    search.focus();
    fireEvent.keyDown(search, { key: "j" });
    expect(document.activeElement).toBe(search);
  });

  it("loads more in the focused row's group with l", async () => {
    const page = Array.from({ length: 50 }, (_, i) =>
      one(100 + i, "ended", `e${String(i)}`, { outcome: "done" }),
    );
    const { requests } = renderList(
      routes((request: Request) => {
        const url = new URL(request.url);
        if (url.searchParams.get("cursor") === "e2")
          return aPage([one(9, "ended", "older", { outcome: "done" })]);
        const status = url.searchParams.get("status");
        const answer = aSessionsByStatus([SAMPLE[1], ...page], {
          next_cursor: status === "ended" ? "e2" : null,
        })(request);
        return status === "ended" ? { ...answer, total_estimate: 51 } : answer;
      }),
    );
    await screen.findByText("/e49");

    // l on a row of a group without more pages does nothing.
    rowOf("/runner").focus();
    fireEvent.keyDown(rowOf("/runner"), { key: "l" });
    rowOf("/e3").focus();
    fireEvent.keyDown(rowOf("/e3"), { key: "l" });
    await waitFor(() => {
      expect(
        sessionRequests(requests)
          .filter((url) => url.searchParams.has("cursor"))
          .map((url) => url.searchParams.get("status")),
      ).toEqual(["ended"]);
    });
    expect(await screen.findByText("/older")).toBeInTheDocument();
  });
});

describe("SessionsListScreen a11y (list)", () => {
  it("has no serious or critical a11y violation with tabs, toolbar, groups and More filters open", async () => {
    const { container } = renderList(routes(aSessionsByStatus(SAMPLE, { next_cursor: "c2" })));
    await screen.findByText("/done");
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "More filters" }));
    });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
