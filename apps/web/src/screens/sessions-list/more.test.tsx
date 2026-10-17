import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  aPage,
  aProjectSummary,
  aSession,
  aSessionLabel,
  aSessionsByStatus,
  anId,
  at,
  renderWithApi,
} from "../../testing/builders";
import { SessionsListScreen } from "./index";

// These tests read the list, the default view.
beforeEach(() => {
  window.localStorage.setItem("ah.sessions.view", "list");
});

function named(name: string) {
  return aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
}

const routes = {
  "/api/v1/sessions": aSessionsByStatus([
    aSession({
      id: anId(1, "ffff0001"),
      label: named("a,b"),
      status: "ended",
      outcome: null,
      ended_at: at(60),
      segments: [],
    }),
    aSession({
      id: anId(2, "ffff0002"),
      label: named("waiter"),
      status: "waiting",
      tokens: null,
      end_inferred: true,
    }),
    aSession({ id: anId(3, "ffff0003"), label: named("idler"), status: "idle" }),
  ]),
  "/api/v1/projects": aPage([aProjectSummary(), aProjectSummary({ name: "loki-trader" })]),
};

/** Opens More filters and returns its panel. */
function openMore(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: /^More filters/ }));
  return screen.getByRole("dialog", { name: "More filters" });
}

describe("SessionsListScreen controls", () => {
  it("exports the loaded rows as CSV metadata from the foot of the list", async () => {
    const create = vi.fn(() => "blob:sessions");
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });

    await screen.findByText("/waiter");
    const exportButton = screen.getByRole("button", { name: "Export 3 sessions as CSV" });
    expect(
      screen.getByRole("table").compareDocumentPosition(exportButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(exportButton);
    expect(create).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:sessions");
  });

  it("writes the toolbar's menus and the sort into the URL", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions?sort=cost",
    });
    await screen.findByText("/waiter");
    const search = () => new URLSearchParams(router.state.location.search);

    fireEvent.click(screen.getByRole("button", { name: "Repo: All" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "agent-hub" }));
    expect(search().get("repo")).toBe("agent-hub");
    expect(screen.getByRole("button", { name: "Repo: agent-hub" })).toBeInTheDocument();

    // The workflows offered are the loaded sessions' own.
    fireEvent.click(screen.getByRole("button", { name: "Workflow: Any" }));
    expect(
      within(screen.getByRole("dialog", { name: "Workflow filter" }))
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")?.textContent),
    ).toEqual(["/a,b", "/idler", "/waiter"]);
    fireEvent.click(screen.getByRole("checkbox", { name: "/waiter" }));
    expect(search().get("workflow")).toBe("/waiter");

    fireEvent.click(screen.getByRole("button", { name: "Period: Last 7 days" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Last 30 days" }));
    expect(search().get("period")).toBe("30 d");
    // Back to the default period (the menu stays open), the URL drops it.
    expect(screen.getByRole("button", { name: "Period: Last 30 days" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Last 7 days" }));
    expect(search().has("period")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: /^Cost/ }));
    expect(search().get("sort")).toBe("-cost");

    fireEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect([...search().keys()]).toEqual(["sort"]);
  });

  it("asks only Ended for an outcome, and clears it from its menu", async () => {
    const { router, requests } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions",
    });
    await screen.findByText("/waiter");

    fireEvent.click(screen.getByRole("button", { name: "Outcome: Any" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Error" }));
    expect(router.state.location.search).toBe("?outcome=error");
    await waitFor(() => {
      expect(screen.queryByText("/waiter")).toBeNull();
    });
    const last = requests.at(-1);
    expect(new URL(last?.url ?? "").searchParams.get("status")).toBe("ended");
    expect(screen.getByRole("button", { name: "Waiting for you · —" })).toBeInTheDocument();

    // The menu stays open, now offering to clear the outcome.
    expect(screen.getByRole("button", { name: "Outcome: Error" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear outcome" }));
    expect(router.state.location.search).toBe("");
  });

  it("sets More filters into the URL, shows each as a removable chip, and counts them", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });
    await screen.findByText("/waiter");
    const search = () => new URLSearchParams(router.state.location.search);

    let panel = openMore();
    for (const [name, value] of [
      ["Agent type", " Explore "],
      ["Touched file", "a.py"],
      ["Cost from", "2"],
    ] as const) {
      const input = within(panel).getByRole("textbox", { name });
      fireEvent.change(input, { target: { value } });
      fireEvent.keyDown(input, { key: "Enter" });
      panel = screen.getByRole("dialog", { name: "More filters" });
    }
    fireEvent.click(within(panel).getByRole("button", { name: "Bash" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: /Had a guard denial/ }));
    fireEvent.click(within(panel).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog", { name: "More filters" })).toBeNull();
    expect(Object.fromEntries(search())).toEqual({
      agent: "Explore",
      file: "a.py",
      cost_min: "2",
      tool: "Bash",
      guard_denial: "1",
    });

    expect(screen.getByRole("button", { name: "More filters · 5" })).toBeInTheDocument();
    for (const chip of [
      "Remove filter Agent type Explore",
      "Remove filter Touched file a.py",
      "Remove filter Used tool Bash",
      "Remove filter Had a guard denial",
    ]) {
      expect(screen.getByRole("button", { name: chip })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Remove filter Cost from $2" }));
    expect(search().has("cost_min")).toBe(false);
    expect(screen.getByRole("button", { name: "More filters · 4" })).toBeInTheDocument();

    // A bad decimal is said, not sent.
    panel = openMore();
    const to = within(panel).getByRole("textbox", { name: "Cost to" });
    fireEvent.change(to, { target: { value: "1,5" } });
    fireEvent.blur(to);
    expect(within(panel).getByText("Use a decimal with a dot, e.g. 1.5")).toBeInTheDocument();
    expect(search().has("cost_max")).toBe(false);

    fireEvent.click(within(panel).getByRole("button", { name: "Clear these filters" }));
    expect(router.state.location.search).toBe("");
  });

  it("keeps More filters open while the owner moves from one field to the next", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });
    await screen.findByText("/waiter");

    const panel = openMore();
    const agent = within(panel).getByRole("textbox", { name: "Agent type" });
    fireEvent.change(agent, { target: { value: "Explore" } });
    fireEvent.blur(agent);
    expect(router.state.location.search).toBe("?agent=Explore");
    const file = within(screen.getByRole("dialog", { name: "More filters" })).getByRole("textbox", {
      name: "Touched file",
    });
    fireEvent.change(file, { target: { value: "a.py" } });
    fireEvent.blur(file);
    expect(new URLSearchParams(router.state.location.search).get("file")).toBe("a.py");
    expect(screen.getByRole("textbox", { name: "Agent type" })).toHaveValue("Explore");
  });

  it("closes More filters on Escape, back on its button", async () => {
    renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });
    await screen.findByText("/waiter");

    openMore();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "More filters" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^More filters/ }));
  });

  it("widens the period and shows all time from the empty states", async () => {
    const empty = { ...routes, "/api/v1/sessions": aPage([]) };
    const filtered = renderWithApi(<SessionsListScreen />, {
      routes: empty,
      path: "/sessions?outcome=error",
    });
    expect(await screen.findByText("No sessions match these filters.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show last 30 days" }));
    expect(filtered.router.state.location.search).toContain("period=30+d");
    fireEvent.click(await screen.findByRole("button", { name: "Clear filters" }));
    expect(filtered.router.state.location.search).toBe("");
    filtered.unmount();

    const never = renderWithApi(<SessionsListScreen />, { routes: empty, path: "/sessions" });
    fireEvent.click(await screen.findByRole("button", { name: "Show all time" }));
    expect(never.router.state.location.search).toBe("?period=All");
  });

  it("says a tab with no session in it, with all time offered on Ended only", async () => {
    const live = renderWithApi(<SessionsListScreen />, { routes, path: "/sessions?status=live" });
    expect(await screen.findByText("No session is live.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all time" })).toBeNull();
    live.unmount();

    const ended = renderWithApi(<SessionsListScreen />, {
      routes: { ...routes, "/api/v1/sessions": aSessionsByStatus([]) },
      path: "/sessions?status=ended",
    });
    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    ended.unmount();

    const { router } = renderWithApi(<SessionsListScreen />, {
      routes: {
        ...routes,
        "/api/v1/sessions": aSessionsByStatus([
          aSession({ id: anId(3, "ffff0003"), label: named("idler"), status: "idle" }),
        ]),
      },
      path: "/sessions?status=ended",
    });
    expect(await screen.findByText("No session ended in the last 7 days.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all time" }));
    expect(router.state.location.search).toBe("?status=ended&period=All");
  });
});
