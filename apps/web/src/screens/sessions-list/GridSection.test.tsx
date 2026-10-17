import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aCapabilities,
  aPage,
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

const named = (name: string, repo = "agent-hub") =>
  aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`], repo });

function routes(sessions: ApiRoutes[string], agents: unknown[] = []): ApiRoutes {
  return {
    [SESSIONS]: sessions,
    "/api/v1/projects": aPage([aProjectSummary()]),
    [AGENT]: { items: agents },
    [`${AGENT}/capabilities`]: aCapabilities(),
  };
}

const section = (name: RegExp) => screen.getByRole("region", { name });
const tilesIn = (region: HTMLElement) => within(region).queryAllByRole("article");
function tileOf(text: string): HTMLElement {
  const tile = screen.getByText(text).closest("article");
  if (!tile) throw new Error(`no tile holds ${text}`);
  return tile;
}

// The list is the default view: these tests read the grid.
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "grid");
});
afterEach(() => {
  window.localStorage.clear();
});

describe("SessionsListScreen grid", () => {
  it("shows each session as a tile with its fields, and the red edge only when it needs you", async () => {
    const sessions = [
      aSession({
        id: anId(1, "aaaa0001"),
        label: named("waiter"),
        status: "waiting",
        waiting_reason: "Guard ask",
        problems: { ...NO_PROBLEMS, needs_you: 1 },
        needs_you_problem: "Needs you: guard_ask_open in docs/adr",
      }),
      aSession({
        id: anId(2, "aaaa0002"),
        label: named("runner"),
        status: "live",
        last_action: "make check-fast",
        sparkline_60s: [0, 1, 2],
        problems: { ...NO_PROBLEMS, handled: 2 },
      }),
      aSession({
        id: anId(3, "aaaa0003"),
        label: named("done"),
        status: "ended",
        outcome: "done",
        ended_at: at(300),
      }),
    ];
    renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus(sessions)),
      path: "/sessions",
    });

    await screen.findByText("/waiter");
    const waiter = tileOf("/waiter");
    expect(waiter).toHaveAttribute("data-trouble", "true");
    expect(within(waiter).getByText("Waiting · Guard ask")).toBeInTheDocument();
    expect(within(waiter).getByText("Needs you: guard_ask_open in docs/adr")).toBeInTheDocument();
    expect(within(waiter).getByRole("link", { name: "Open session" })).toBeInTheDocument();
    const runner = tileOf("/runner");
    expect(runner).not.toHaveAttribute("data-trouble");
    expect(within(runner).getByText("make check-fast")).toBeInTheDocument();
    expect(within(runner).getByText("2 problems, handled by the agent")).toBeInTheDocument();
    expect(within(runner).getByText("Turns")).toBeInTheDocument();
    expect(within(runner).getByRole("img", { name: /Events per 5 s/ })).toBeInTheDocument();
    const done = tileOf("/done");
    expect(within(done).getByText("Ended · done")).toBeInTheDocument();
    expect(within(done).queryByRole("img", { name: /Events per 5 s/ })).toBeNull();
    expect(tilesIn(section(/^Finished · last 7 days/))).toEqual([done]);
  });

  it("shows 50 tiles in a section, then Load more fetches the next cursor page", async () => {
    const page = Array.from({ length: 50 }, (_, n) =>
      aSession({ id: anId(n + 1, "bbbb0000"), label: named(`s${String(n + 1)}`), status: "live" }),
    );
    const next = aSession({ id: anId(51, "bbbb0000"), label: named("s51"), status: "live" });
    const { requests } = renderWithApi(<SessionsListScreen />, {
      routes: routes((request: Request) =>
        new URL(request.url).searchParams.get("cursor") === "c2"
          ? aPage([next])
          : aSessionsByStatus(page, { next_cursor: "c2" })(request),
      ),
      path: "/sessions",
    });

    await screen.findByText("/s50");
    const live = section(/^Working/);
    expect(tilesIn(live)).toHaveLength(50);
    expect(within(live).queryByText("/s51")).toBeNull();
    fireEvent.click(within(live).getByRole("button", { name: "Load more" }));

    expect(await within(live).findByText("/s51")).toBeInTheDocument();
    expect(tilesIn(live)).toHaveLength(51);
    expect(requests.some((r) => new URL(r.url).searchParams.get("cursor") === "c2")).toBe(true);
    expect(within(live).getByText("Showing all 51")).toBeInTheDocument();
    expect(within(live).queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("groups the tiles of each section within repo, run or workflow, ungrouped ones last", async () => {
    const sessions: Session[] = [
      aSession({
        id: anId(1),
        label: named("a", "storefront"),
        repo: "storefront",
        status: "live",
      }),
      aSession({
        id: anId(2),
        label: named("b"),
        status: "live",
        run_id: "run-1",
        issue: "AGH-9",
        step: "implement",
      }),
      aSession({ id: anId(3), label: named("c"), status: "live" }),
      aSession({ id: anId(4), label: named("d"), status: "idle" }),
    ];
    const heads = (region: HTMLElement) =>
      within(region)
        .queryAllByRole("heading", { level: 3 })
        .map((h) => h.textContent);
    const repo = renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus(sessions)),
      path: "/sessions?within=repo",
    });
    await screen.findByText("/a");
    expect(heads(section(/^Working/))).toEqual([
      "agent-hub › storefront · 1",
      "agent-hub › agent-hub · 2",
    ]);
    expect(heads(section(/^Paused/))).toEqual(["agent-hub › agent-hub · 1"]);
    repo.unmount();

    const run = renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus(sessions)),
      path: "/sessions?within=run",
    });
    await screen.findByText("/a");
    expect(heads(section(/^Working/))).toEqual(["Run AGH-9 · implement · 1", "Not in a run · 2"]);
    expect(within(section(/^Working/)).getByRole("group", { name: "Not in a run" })).toContainElement(
      tileOf("/c"),
    );
    run.unmount();

    renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus(sessions)),
      path: "/sessions?within=flat",
    });
    await screen.findByText("/a");
    expect(heads(section(/^Working/))).toEqual([]);
    expect(tilesIn(section(/^Working/))).toHaveLength(3);
  });

  it("resume: an ended driven tile offers Resume, a link to its chat, where a message resumes it", async () => {
    const driven = [
      anAgentSession({ id: anId(12, "0192a5e5"), title: "Fix the build", status: "running" }),
      anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" }),
    ];
    const { router, container } = renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus([]), driven),
      path: "/sessions",
    });

    await screen.findByText("Broke");
    expect(within(tileOf("Fix the build")).queryByRole("link", { name: /^Resume/ })).toBeNull();
    const resume = within(tileOf("Broke")).getByRole("link", { name: "Resume Broke" });
    expect(resume).toHaveAttribute("href", `/agent-sessions/${anId(16, "0192a5e5")}`);
    // The link sits inside a focusable tile (article tabIndex=0).
    expect(await seriousViolations(container)).toEqual([]);
    resume.focus();
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(16, "0192a5e5")}`);
  });

  it("resume: no Resume on a log-full tile, or where sessions cannot start", async () => {
    const full = anAgentSession({
      id: anId(17, "0192a5e5"),
      title: "Full",
      status: "ended",
      end_reason: "log_full",
    });
    const broke = anAgentSession({ id: anId(16, "0192a5e5"), title: "Broke", status: "failed" });
    const view = renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus([]), [full, broke]),
      path: "/sessions",
    });
    await screen.findByText("Broke");
    expect(within(tileOf("Full")).queryByRole("link", { name: /^Resume/ })).toBeNull();
    view.unmount();

    renderWithApi(<SessionsListScreen />, {
      routes: {
        ...routes(aSessionsByStatus([]), [broke]),
        [`${AGENT}/capabilities`]: aCapabilities({ available: false }),
      },
      path: "/sessions",
    });
    await screen.findByText("Broke");
    expect(within(tileOf("Broke")).queryByRole("link", { name: /^Resume/ })).toBeNull();
  });

  it("shows a driven session without a twin as a Chat tile, a twin by its prompt, and opens tiles where their rows open", async () => {
    const twin = aSession({
      id: anId(3, "aaaa0003"),
      label: named("twin"),
      status: "live",
      agent_session_id: anId(11, "0192a5e5"),
    });
    const plain = aSession({ id: anId(4, "aaaa0004"), label: named("plain"), status: "live" });
    const driven = [
      anAgentSession({
        id: anId(11, "0192a5e5"),
        observed_session_id: twin.id,
        title: "Run the tests",
        status: "running",
      }),
      anAgentSession({ id: anId(12, "0192a5e5"), title: "Fix the build", status: "running" }),
    ];
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes: routes(aSessionsByStatus([twin, plain]), driven),
      path: "/sessions",
    });

    await screen.findByText("Fix the build");
    const live = section(/^Working · 3/);
    expect(tilesIn(live)).toHaveLength(3);
    expect(within(tileOf("Fix the build")).getByText("Chat")).toBeInTheDocument();
    // The twin has no title of its own yet: its tile reads the driven session's prompt.
    expect(within(tileOf("Run the tests")).getByText("Chat")).toBeInTheDocument();
    expect(within(tileOf("/plain")).queryByText("Chat")).toBeNull();

    fireEvent.click(tileOf("Fix the build"));
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(12, "0192a5e5")}`);
    fireEvent.click(tileOf("Run the tests"));
    expect(router.state.location.pathname).toBe(`/agent-sessions/${anId(11, "0192a5e5")}`);
    fireEvent.keyDown(tileOf("/plain"), { key: "Enter" });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/sessions/${anId(4, "aaaa0004")}`);
    });
  });
});
