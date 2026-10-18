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
  T0,
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
  one(2, "live", "runner", { last_action: "Ran make check-fast", last_tool: "Bash" }),
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

const groups = () =>
  [...document.querySelectorAll<HTMLElement>("section[data-group]")].map(
    (g) => g.dataset.group ?? "",
  );
const group = (name: RegExp | string) => screen.getByRole("region", { name });
const headers = () =>
  [...document.querySelectorAll<HTMLElement>("section[data-group] h2")].map((h) => h.textContent);
/** The focused element, where a key press lands. */
function focused(): Element {
  if (!document.activeElement) throw new Error("nothing is focused");
  return document.activeElement;
}
const scrolls = vi.fn();
const rowOf = (text: string) => screen.getByText(text).closest("tr") as HTMLElement;
/** What the row says it does or did, without the exact command or path. */
const lineOf = (text: string) => rowOf(text).querySelector(".sl-row-say")?.textContent;
const detailOf = (text: string) => rowOf(text).querySelector(".sl-row-detail")?.textContent;
const badgeOf = (text: string) => rowOf(text).querySelector(".sl-cell-status")?.textContent;
/** The session rows of a group's table (its column header row is for screen readers only). */
const rowsIn = (el: HTMLElement) => [...el.querySelectorAll<HTMLElement>("tbody tr[data-nav-row]")];
const sessionRequests = (requests: Request[]) =>
  requests.filter((r) => new URL(r.url).pathname === SESSIONS).map((r) => new URL(r.url));

beforeEach(() => {
  // The default period counts back from now: pin the clock a day after the builders' T0.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(Date.parse(T0) + 86_400_000);
  window.localStorage.setItem("ah.sessions.view", "list");
  // jsdom has no layout: the keys and the attention line scroll the row they focus into view.
  Element.prototype.scrollIntoView = scrolls;
});

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("SessionsListScreen inbox-groups", () => {
  it("shows the four groups with their counts and hints, one table each, a status on every row", async () => {
    renderList();
    await screen.findByText("/runner");

    expect(groups()).toEqual(["waiting", "live", "idle", "ended"]);
    expect(headers()).toEqual([
      "Needs you · 1Answer so the agent can continue · oldest first",
      "Working · 1Claude is on it, nothing to do yet · latest first",
      "Your turn · 1Claude finished its turn: check the work or send your next message · latest first",
      "Finished · last 7 days · 1Newest first",
    ]);
    expect(screen.queryByRole("group", { name: "Status" })).toBeNull();
    // One table per group, named for readers; the shared column header is hidden from them.
    expect(
      screen.getAllByRole("table").map((t) => t.querySelector("caption")?.textContent),
    ).toEqual([
      "Needs you sessions",
      "Working sessions",
      "Your turn sessions",
      "Finished · last 7 days sessions",
    ]);
    const shared = document.querySelector(".sl-table-head");
    expect(shared).toHaveAttribute("aria-hidden", "true");
    expect(shared?.textContent).toBe("StatusSessionWhereCostLast activity");
    expect(
      within(group(/^Needs you/))
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["Status", "Session", "Where", "Cost", "Last activity", "Action"]);
    // Each row says its status in the same words, and one useful line.
    expect(badgeOf("/asker")).toBe("Waiting for you");
    expect(badgeOf("/runner")).toBe("Working");
    expect(badgeOf("/rester")).toBe("Your turn");
    expect(badgeOf("/done")).toBe("Done");
    expect(lineOf("/asker")).toBe("Asks for a permission in the terminal");
    expect(lineOf("/runner")).toBe("Running a command");
    expect(detailOf("/runner")).toBe("make check-fast");
    expect(lineOf("/rester")).toBe("Turn finished");
    expect(lineOf("/done")).toBe("Ran 10 min");
    // Each group's body holds its rows.
    expect(rowsIn(group(/^Needs you/))).toEqual([rowOf("/asker")]);
  });

  it("shows a status link's group from the URL, even collapsed or empty, which cannot collapse", async () => {
    window.localStorage.setItem("ah.sessions.collapsed", JSON.stringify(["live"]));
    const { router } = renderList(
      routes(aSessionsByStatus(SAMPLE.filter((s) => s.status !== "idle"))),
      "/sessions?status=live",
    );
    await screen.findByText("/runner");

    expect(groups()).toEqual(["live"]);
    const live = group("Working · 1");
    expect(within(live).queryByRole("button", { name: /^Working/ })).toBeNull();
    expect(within(live).getByText("/runner")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove filter Status Working" })).toBeVisible();

    await act(async () => {
      await router.navigate("/sessions?status=idle");
    });
    expect(await screen.findByText("No session waits for a reply.")).toBeInTheDocument();
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

    expect(screen.getByRole("button", { name: "Working · ~40" })).toBeInTheDocument();
    expect(within(group(/^Working/)).getByText("Showing 1 of ~40")).toBeInTheDocument();
  });

  it("orders Needs you oldest wait first, and Working and Your turn latest activity first", async () => {
    const sessions = [
      one(1, "waiting", "new-ask", { last_activity_at: at(500) }),
      one(2, "waiting", "old-ask", { last_activity_at: at(100) }),
      one(3, "idle", "rested-long", { last_activity_at: at(100) }),
      one(4, "idle", "just-rested", { last_activity_at: at(900) }),
    ];
    renderList(routes(aSessionsByStatus(sessions)));
    await screen.findByText("/old-ask");

    const titles = (name: RegExp) =>
      rowsIn(group(name)).map((row) => row.querySelector(".sl-row-title")?.textContent);
    expect(titles(/^Needs you/)).toEqual(["/old-ask", "/new-ask"]);
    expect(titles(/^Your turn/)).toEqual(["/just-rested", "/rested-long"]);
  });

  it("shows Finished's five latest, then the rest on Show more", async () => {
    const ended = Array.from({ length: 7 }, (_, i) =>
      one(100 + i, "ended", `e${String(i)}`, { outcome: "done", ended_at: at(1000 - i) }),
    );
    renderList(routes(aSessionsByStatus([SAMPLE[1], ...ended])));
    await screen.findByText("/e0");

    const finished = group(/^Finished/);
    expect(rowsIn(finished)).toHaveLength(5);
    expect(screen.queryByText("/e5")).toBeNull();
    // Finished rows read muted.
    expect(rowOf("/e0")).toHaveAttribute("data-muted", "true");
    expect(rowOf("/runner")).not.toHaveAttribute("data-muted");
    fireEvent.click(
      within(finished).getByRole("button", { name: "Show 2 more finished sessions" }),
    );
    expect(rowsIn(finished)).toHaveLength(7);
    expect(within(finished).queryByRole("button", { name: /^Show/ })).toBeNull();
  });
});

const tileValue = (id: string) =>
  document.querySelector(`[data-tile="${id}"] .sl-summary-value`)?.textContent;
const needsTile = () => screen.getByRole("button", { name: /^Needs you, / });

describe("SessionsListScreen summary strip", () => {
  it("counts each group in a tile; Needs you shows only that group and focuses its first row", async () => {
    const { router } = renderList();
    await screen.findByText("/asker");

    expect(screen.getByRole("group", { name: "Sessions summary" })).toBeInTheDocument();
    expect([tileValue("waiting"), tileValue("live"), tileValue("idle")]).toEqual(["1", "1", "1"]);
    expect(needsTile()).toHaveAccessibleName("Needs you, 1 session. Show only these.");
    expect(needsTile()).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(needsTile());
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/asker"));
    });
    expect(scrolls).toHaveBeenCalledWith({ block: "nearest" });
    expect(router.state.location.search).toBe("?status=waiting");
    expect(needsTile()).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("/runner")).toBeNull();

    // Pressed again, every group shows.
    fireEvent.click(needsTile());
    expect(router.state.location.search).toBe("");
    expect(await screen.findByText("/runner")).toBeInTheDocument();
  });

  it("moves an open session with a problem that needs the owner into Needs you, with Review problem", async () => {
    const problem = { ...NO_PROBLEMS, needs_you: 1 };
    const sessions = [
      one(2, "live", "runner"),
      one(5, "live", "stuck", { problems: problem, needs_you_problem: "Needs you: Bash failed" }),
      one(6, "ended", "broken", { outcome: "error", problems: problem }),
    ];
    renderList(routes(aSessionsByStatus(sessions)));
    await screen.findByText("/stuck");

    expect(within(group("Needs you · 1")).getByText("/stuck")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Working · 1" })).toBeInTheDocument();
    // A finished session stays in Finished, its line in the failed tone.
    expect(within(group(/^Finished/)).getByText("/broken")).toBeInTheDocument();
    expect(tileValue("waiting")).toBe("1");
    expect(rowOf("/stuck")).toHaveAttribute("data-trouble", "true");
    expect(rowOf("/broken")).toHaveAttribute("data-trouble", "true");
    expect(rowOf("/runner")).not.toHaveAttribute("data-trouble");
    expect(lineOf("/stuck")).toBe("Needs you: Bash failed");
    expect(badgeOf("/stuck")).toBe("Problem");
    expect(badgeOf("/broken")).toBe("Failed");
    expect(lineOf("/broken")).toBe("1 problem needs you · Ran 10 min");
    fireEvent.click(needsTile());
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/stuck"));
    });
    expect(
      within(rowOf("/stuck")).getByRole("link", { name: "Review problem in /stuck" }),
    ).toHaveAttribute("href", `/sessions/${anId(5, "dddd0005")}`);
  });

  it("moves from another status link to Needs you alone, then focuses its first row", async () => {
    const sessions = [...SAMPLE, one(5, "waiting", "asker-2", { last_activity_at: at(900) })];
    const { router } = renderList(routes(aSessionsByStatus(sessions)), "/sessions?status=ended");
    await screen.findByText("/done");
    expect(screen.getByRole("button", { name: /^Finished, / })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(needsTile());
    expect(router.state.location.search).toBe("?status=waiting");
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/asker"));
    });
  });

  it("opens a collapsed Needs you group to focus its first row", async () => {
    window.localStorage.setItem("ah.sessions.collapsed", JSON.stringify(["waiting"]));
    renderList();
    await screen.findByText("/runner");
    expect(screen.queryByText("/asker")).toBeNull();

    fireEvent.click(needsTile());
    await waitFor(() => {
      expect(document.activeElement).toBe(rowOf("/asker"));
    });
  });

  it("says calmly when nothing needs the owner or works", async () => {
    const calm = renderList(routes(aSessionsByStatus(SAMPLE.slice(1))));
    expect(await screen.findByText("Nothing needs you")).toBeInTheDocument();
    expect(tileValue("waiting")).toBe("0");
    expect(screen.getByText("Claude is on it")).toBeInTheDocument();
    calm.unmount();

    renderList(routes(aSessionsByStatus([SAMPLE[3]])));
    expect(await screen.findByText("No session is working")).toBeInTheDocument();
    expect(screen.getByText("last 7 days")).toBeInTheDocument();
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
    // The toolbar and the empty state both offer it: the empty state's comes last.
    const clear = screen.getAllByRole("button", { name: "Clear filters" }).at(-1);
    if (!clear) throw new Error("no Clear filters");
    fireEvent.click(clear);
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
  const twin = one(5, "live", "twin", { agent_session_id: anId(11, "0192a5e5") });
  const AGENTS = [
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
  /** The row's action: its last column. */
  const links = (text: string) =>
    [...(rowOf(text).querySelector(".sl-cell-action")?.querySelectorAll("a") ?? [])].map((link) => [
      link.getAttribute("aria-label"),
      link.getAttribute("href"),
    ]);

  it("offers Answer where the owner is needed, Resume on a resumable chat, Open or Open chat elsewhere", async () => {
    const { container } = renderList(routes(aSessionsByStatus([...SAMPLE, twin]), AGENTS));
    await screen.findByText("Broke");

    expect(links("/asker")).toEqual([["Answer /asker", `/sessions/${anId(1, "dddd0001")}`]]);
    expect(links("Approve me")).toEqual([
      ["Answer Approve me", `/agent-sessions/${anId(13, "0192a5e5")}`],
    ]);
    expect(lineOf("Approve me")).toBe("Asks to use Bash: git status");
    expect(links("Broke")).toEqual([["Resume Broke", `/agent-sessions/${anId(16, "0192a5e5")}`]]);
    // Every other row says where it opens: the chat, or the session.
    expect(links("/runner")).toEqual([
      ["Open session /runner", `/sessions/${anId(2, "dddd0002")}`],
    ]);
    expect(links("/rester")).toEqual([
      ["Open session /rester", `/sessions/${anId(3, "dddd0003")}`],
    ]);
    expect(links("/done")).toEqual([["Open session /done", `/sessions/${anId(4, "dddd0004")}`]]);
    expect(links("Run the tests")).toEqual([
      ["Open chat Run the tests", `/agent-sessions/${anId(11, "0192a5e5")}`],
    ]);
    expect(links("Ready")).toEqual([
      ["Open chat Ready", `/agent-sessions/${anId(14, "0192a5e5")}`],
    ]);
    expect(within(rowOf("Ready")).getByRole("link", { name: "Open chat Ready" })).toHaveTextContent(
      "Open chat",
    );
    expect(
      within(rowOf("/runner")).getByRole("link", { name: "Open session /runner" }),
    ).toHaveTextContent(/^Open$/);
    // The title link goes where the row opens.
    expect(
      within(rowOf("Run the tests")).getByRole("link", { name: "Run the tests" }),
    ).toHaveAttribute("href", `/agent-sessions/${anId(11, "0192a5e5")}`);
    // Only the Answer buttons are the accent.
    expect(within(rowOf("/asker")).getByRole("link", { name: "Answer /asker" })).toHaveClass(
      "ah-btn-primary",
    );
    expect(within(rowOf("Broke")).getByRole("link", { name: "Resume Broke" })).not.toHaveClass(
      "ah-btn-primary",
    );
    // Every row says where it started: a chat from hub web, or a terminal.
    expect(within(rowOf("/runner")).getByText("Terminal")).toBeInTheDocument();
    expect(within(rowOf("Run the tests")).getByText("Chat")).toBeInTheDocument();
    expect(within(rowOf("Ready")).getByText("Chat")).toBeInTheDocument();
    expect(within(rowOf("Run the tests")).queryByText("Terminal")).toBeNull();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("offers no Resume where sessions cannot start", async () => {
    renderList({
      ...routes(aSessionsByStatus(SAMPLE), AGENTS),
      [`${AGENT}/capabilities`]: aCapabilities({ available: false }),
    });
    await screen.findByText("Broke");
    expect(links("Broke")).toEqual([
      ["Open chat Broke", `/agent-sessions/${anId(16, "0192a5e5")}`],
    ]);
  });

  it("opens the row where it leads on click and Enter, and its button where the button leads", async () => {
    const { router } = renderList(routes(aSessionsByStatus([...SAMPLE, twin]), AGENTS));
    await screen.findByText("Broke");

    fireEvent.click(rowOf("/runner"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(2, "dddd0002")}`);
    fireEvent.keyDown(rowOf("Run the tests"), { key: "Enter" });
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(11, "0192a5e5")}`);
    fireEvent.click(rowOf("Ready"));
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(14, "0192a5e5")}`);
    // Enter on a control inside the row is the control's, not the row's.
    fireEvent.keyDown(within(rowOf("/asker")).getByRole("link", { name: "Answer /asker" }), {
      key: "Enter",
    });
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(14, "0192a5e5")}`);
    fireEvent.click(within(rowOf("Approve me")).getByRole("link", { name: "Answer Approve me" }));
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(13, "0192a5e5")}`);
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

  it("shows the rest of Finished, then loads more in the focused row's group with l", async () => {
    const page = Array.from({ length: 50 }, (_, i) =>
      one(100 + i, "ended", `e${String(i)}`, { outcome: "done", ended_at: at(5000 - i) }),
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
    await screen.findByText("/e4");
    expect(screen.queryByText("/e49")).toBeNull();

    // l on a row of a group without more pages does nothing.
    rowOf("/runner").focus();
    fireEvent.keyDown(rowOf("/runner"), { key: "l" });
    expect(screen.queryByText("/e49")).toBeNull();
    // In Finished, l first shows the loaded rows it holds back, then asks the next page.
    rowOf("/e3").focus();
    fireEvent.keyDown(rowOf("/e3"), { key: "l" });
    expect(screen.getByText("/e49")).toBeInTheDocument();
    expect(sessionRequests(requests).some((url) => url.searchParams.has("cursor"))).toBe(false);
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
  it("has no serious or critical a11y violation with the toolbar, the groups and Filters open", async () => {
    const problem = { ...NO_PROBLEMS, needs_you: 1 };
    const { container } = renderList(
      routes(
        aSessionsByStatus([...SAMPLE, one(6, "live", "stuck", { problems: problem })], {
          next_cursor: "c2",
        }),
        [anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" })],
      ),
    );
    await screen.findByText("Broke");
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Filters" }));
    });
    expect(screen.getByRole("dialog", { name: "Filters" })).toBeInTheDocument();

    expect(await seriousViolations(container)).toEqual([]);
  });
});
