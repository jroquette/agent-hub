import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

describe("SessionsListScreen controls", () => {
  it("exports the loaded rows as CSV metadata", async () => {
    const create = vi.fn(() => "blob:sessions");
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    renderWithApi(<SessionsListScreen />, { routes, path: "/sessions" });

    await screen.findByText("/waiter");
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(create).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:sessions");
  });

  it("writes text filters, statuses and sorts into the URL and clears them from chips", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions?sort=cost",
    });
    await screen.findByText("/waiter");

    expect(
      screen.getByText("Use the project switcher in the top bar to scope this list."),
    ).toBeInTheDocument();
    for (const [name, value] of [
      ["Repo", "agent-hub"],
      ["Agent type", "Explore"],
      ["Touched file (path or glob)", "a.py"],
    ] as const) {
      const input = screen.getByRole("textbox", { name });
      fireEvent.change(input, { target: { value } });
      fireEvent.blur(input);
    }
    const min = screen.getByRole("textbox", { name: "Minimum cost" });
    fireEvent.change(min, { target: { value: "2" } });
    fireEvent.blur(min);
    fireEvent.click(screen.getByRole("checkbox", { name: "waiting" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "issue-to-pr" }));
    const search = router.state.location.search;
    for (const part of [
      "repo=agent-hub",
      "agent=Explore",
      "file=a.py",
      "cost_min=2",
      "status=waiting",
      "workflow=issue-to-pr",
    ]) {
      expect(search).toContain(part);
    }
    fireEvent.click(screen.getByRole("button", { name: "Remove filter Cost from $2" }));
    expect(router.state.location.search).not.toContain("cost_min");
    fireEvent.click(
      within(screen.getByRole("table", { name: "Waiting sessions" })).getByRole("button", {
        name: /^Cost/,
      }),
    );
    expect(router.state.location.search).toContain("sort=-cost");
    fireEvent.click(screen.getByRole("button", { name: "30 d" }));
    expect(router.state.location.search).toContain("period=30+d");
  });

  it("picks a saved view and resets the columns", async () => {
    const { router } = renderWithApi(<SessionsListScreen />, {
      routes,
      path: "/sessions?outcome=error",
    });
    // An outcome asks only the Ended section.
    await screen.findByText("/a,b");

    fireEvent.click(screen.getByRole("button", { name: "Unsaved view" }));
    fireEvent.click(screen.getByRole("button", { name: /Guard denials/ }));
    expect(router.state.location.search).toContain("guard_denial=1");
    expect(router.state.location.search).toContain("period=30+d");
    expect(router.state.location.search).not.toContain("outcome");
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Repo" }));
    expect(screen.queryAllByRole("columnheader", { name: "Repo" })).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(screen.getAllByRole("columnheader", { name: "Repo" }).length).toBeGreaterThan(0);
    // Each section shows its own rows; a lookup inside one table stays cheap while others load.
    for (const [section, badge] of [
      ["Ended or failed", "Ended"],
      ["Waiting", "Waiting"],
      ["Idle", "Idle"],
    ] as const) {
      const table = await screen.findByRole("table", { name: `${section} sessions` });
      expect(await within(table).findByText(badge)).toBeInTheDocument();
    }
  });

  it("widens the period and shows all time from the empty states", async () => {
    const empty = { ...routes, "/api/v1/sessions": aPage([]) };
    const filtered = renderWithApi(<SessionsListScreen />, {
      routes: empty,
      path: "/sessions?outcome=error",
    });
    fireEvent.click(await screen.findByRole("button", { name: "Widen to 30 d" }));
    expect(filtered.router.state.location.search).toContain("period=30+d");
    filtered.unmount();

    const never = renderWithApi(<SessionsListScreen />, { routes: empty, path: "/sessions" });
    fireEvent.click(await screen.findByRole("button", { name: "Show all time" }));
    expect(never.router.state.location.search).toBe("?period=All");
  });
});
