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

/** Opens the Filters popover and returns its panel. */
function openMore(): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: /^Filters/ }));
  return screen.getByRole("dialog", { name: "Filters" });
}
/** One choice section of the Filters popover (Repo, Outcome, Workflow, Used tool). */
const choices = (panel: HTMLElement, name: string) => within(panel).getByRole("group", { name });

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
      screen.getByRole("region", { name: /^Finished/ }).compareDocumentPosition(exportButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(exportButton);
    expect(create).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:sessions");
  });

  it("writes Repo, Workflow and the period into the URL, each set filter as a chip", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions?sort=cost",
    });
    await screen.findByText("/waiter");
    const search = () => new URLSearchParams(router.state.location.search);

    // Repo, Outcome and Workflow live in the one Filters popover, not as menus of their own.
    expect(screen.queryByRole("button", { name: /^Repo/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Outcome/ })).toBeNull();
    const panel = openMore();
    fireEvent.click(within(choices(panel, "Repo")).getByRole("button", { name: "agent-hub" }));
    expect(search().get("repo")).toBe("agent-hub");
    expect(
      within(choices(panel, "Repo")).getByRole("button", { name: "agent-hub" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: "Remove filter Repo agent-hub" }),
    ).toBeInTheDocument();

    // The workflows offered are the loaded sessions' own.
    expect(
      within(choices(panel, "Workflow"))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["/a,b", "/idler", "/waiter"]);
    fireEvent.click(within(choices(panel, "Workflow")).getByRole("button", { name: "/waiter" }));
    expect(search().get("workflow")).toBe("/waiter");
    expect(screen.getByRole("button", { name: "Filters · 2" })).toBeInTheDocument();
    // A second press on a chosen chip clears it.
    fireEvent.click(within(choices(panel, "Workflow")).getByRole("button", { name: "/waiter" }));
    expect(search().has("workflow")).toBe(false);
    fireEvent.click(within(choices(panel, "Workflow")).getByRole("button", { name: "/idler" }));
    fireEvent.keyDown(document.body, { key: "Escape" });

    fireEvent.click(screen.getByRole("button", { name: "Period: Last 7 days" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Last 30 days" }));
    expect(search().get("period")).toBe("30 d");
    // Back to the default period (the menu stays open), the URL drops it.
    expect(screen.getByRole("button", { name: "Period: Last 30 days" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Last 7 days" }));
    expect(search().has("period")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Remove filter Repo agent-hub" }));
    expect(search().has("repo")).toBe(false);
    // Clear filters keeps the sort, which is not a filter.
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect([...search().keys()]).toEqual(["sort"]);
  });

  it("asks only Finished for an outcome, and clears it from its chip", async () => {
    const { router, requests } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions",
    });
    await screen.findByText("/waiter");

    const panel = openMore();
    fireEvent.click(within(choices(panel, "Outcome")).getByRole("button", { name: "Error" }));
    expect(router.state.location.search).toBe("?outcome=error");
    await waitFor(() => {
      expect(screen.queryByText("/waiter")).toBeNull();
    });
    const last = requests.at(-1);
    expect(new URL(last?.url ?? "").searchParams.get("status")).toBe("ended");
    // Only Finished is asked: the other groups do not show.
    expect(screen.queryByRole("region", { name: /^Needs you/ })).toBeNull();
    expect(screen.getByRole("region", { name: /^Finished/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove filter Outcome Error" }));
    expect(router.state.location.search).toBe("");
  });

  it("sets the Filters popover's fields into the URL, shows each as a removable chip, and counts them", async () => {
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
      panel = screen.getByRole("dialog", { name: "Filters" });
    }
    fireEvent.click(within(choices(panel, "Used tool")).getByRole("button", { name: "Bash" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: /Had a guard denial/ }));
    // The Outcome section has a "Done" chip of its own: the close button is the one outside it.
    const done = within(panel)
      .getAllByRole("button", { name: "Done" })
      .find((button) => !button.closest("fieldset"));
    if (!done) throw new Error("no Done button");
    fireEvent.click(done);
    expect(screen.queryByRole("dialog", { name: "Filters" })).toBeNull();
    expect(Object.fromEntries(search())).toEqual({
      agent: "Explore",
      file: "a.py",
      cost_min: "2",
      tool: "Bash",
      guard_denial: "1",
    });

    expect(screen.getByRole("button", { name: "Filters · 5" })).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Filters · 4" })).toBeInTheDocument();

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

  it("keeps Filters open while the owner moves from one field to the next", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });
    await screen.findByText("/waiter");

    const panel = openMore();
    const agent = within(panel).getByRole("textbox", { name: "Agent type" });
    fireEvent.change(agent, { target: { value: "Explore" } });
    fireEvent.blur(agent);
    expect(router.state.location.search).toBe("?agent=Explore");
    const file = within(screen.getByRole("dialog", { name: "Filters" })).getByRole("textbox", {
      name: "Touched file",
    });
    fireEvent.change(file, { target: { value: "a.py" } });
    fireEvent.blur(file);
    expect(new URLSearchParams(router.state.location.search).get("file")).toBe("a.py");
    expect(screen.getByRole("textbox", { name: "Agent type" })).toHaveValue("Explore");
  });

  it("closes Filters on Escape, back on its button", async () => {
    renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });
    await screen.findByText("/waiter");

    openMore();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Filters" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Filters/ }));
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
    // The toolbar and the empty state both offer it: the empty state's comes last.
    await screen.findByText("No sessions match these filters.");
    const clear = screen.getAllByRole("button", { name: "Clear filters" }).at(-1);
    if (!clear) throw new Error("no Clear filters");
    fireEvent.click(clear);
    expect(filtered.router.state.location.search).toBe("");
    filtered.unmount();

    const never = renderWithApi(<SessionsListScreen />, { routes: empty, path: "/sessions" });
    fireEvent.click(await screen.findByRole("button", { name: "Show all time" }));
    expect(never.router.state.location.search).toBe("?period=All");
  });

  it("says a status link's group has no session, with all time offered on Finished only", async () => {
    const live = renderWithApi(<SessionsListScreen />, { routes, path: "/sessions?status=live" });
    expect(await screen.findByText("No session is working.")).toBeInTheDocument();
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
    expect(await screen.findByText("No session finished in the last 7 days.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all time" }));
    expect(router.state.location.search).toBe("?status=ended&period=All");
  });
});
