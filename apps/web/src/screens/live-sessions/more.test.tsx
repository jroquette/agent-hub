import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  aLiveTile,
  aPage,
  aSessionLabel,
  anId,
  at,
  renderWithApi,
  type LiveTile,
} from "../../testing/builders";
import { LiveSessionsScreen } from "./index";

const LIVE = "/api/v1/live-sessions";

function named(name: string) {
  return aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
}

function many(n: number): LiveTile[] {
  return Array.from({ length: n }, (_, i) =>
    aLiveTile({
      id: anId(i + 1, "bbbb0000"),
      label: named(`agent-${String(i)}`),
      started_at: at(-i),
    }),
  );
}

describe("LiveSessionsScreen details", () => {
  it("caps groups at six tiles with a Show more button when more than 24 sessions run", async () => {
    renderWithApi(<LiveSessionsScreen />, { routes: { [LIVE]: aPage(many(26)) }, path: "/live" });

    const more = await screen.findByRole("button", {
      name: "Show 20 more in agent-hub › agent-hub",
    });
    fireEvent.click(more);
    expect(screen.getByText("/agent-25")).toBeInTheDocument();
  });

  it("shows run lines, the approval link and ended rows that open on Enter", async () => {
    const tiles = [
      aLiveTile({
        id: anId(1, "cccc0001"),
        label: named("waiter"),
        group: "waiting",
        status: "waiting",
        waiting_reason: "Guard ask",
        run_id: "a1b2c3d4e5f6",
        step: "implement",
        attempt: 1,
      }),
      aLiveTile({
        id: anId(2, "cccc0002"),
        label: named("idler"),
        group: "idle",
        status: "idle",
        last_action: null,
        last_tool: null,
      }),
      aLiveTile({
        id: anId(3, "cccc0003"),
        label: named("child"),
        is_subagent: true,
        last_tool: "Read",
      }),
      aLiveTile({
        id: anId(4, "cccc0004"),
        label: named("gone"),
        group: "ended_recently",
        status: "ended",
        outcome: null,
        ended_at: at(0),
      }),
    ];
    const { router } = renderWithApi(<LiveSessionsScreen />, {
      routes: { [LIVE]: aPage(tiles) },
      path: "/live?group=run",
    });

    expect(await screen.findByText(/Run AGH-48 › implement · attempt 1/)).toBeInTheDocument();
    expect(screen.getByText(/Last: no tool call yet/)).toBeInTheDocument();
    expect(screen.getByText("Ended · no end event")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Open approval" }));
    expect(router.state.location.pathname).toBe("/approvals");
  });

  it("opens an ended session on Enter and cycles grouping with v", async () => {
    const tiles = [
      aLiveTile({ id: anId(1, "dddd0001"), label: named("runner") }),
      aLiveTile({
        id: anId(2, "dddd0002"),
        label: named("gone"),
        group: "ended_recently",
        status: "ended",
        outcome: "done",
        ended_at: at(0),
      }),
    ];
    const { router } = renderWithApi(<LiveSessionsScreen />, {
      routes: { [LIVE]: aPage(tiles) },
      path: "/live",
    });

    await screen.findByText("/runner");
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "v" }));
    });
    expect(router.state.location.search).toBe("?group=run");
    fireEvent.keyDown(screen.getByRole("link", { name: /\/gone in agent-hub/ }), { key: "Enter" });
    expect(router.state.location.pathname).toBe(`/sessions/${anId(2, "dddd0002")}`);
  });

  it("announces a new waiting session politely when the stream adds one", async () => {
    const { stream } = renderWithApi(<LiveSessionsScreen />, {
      routes: { [LIVE]: aPage([aLiveTile({ label: named("runner") })]) },
      path: "/live",
    });
    await screen.findByText("/runner");

    act(() => {
      stream("/api/v1/live-sessions/stream").emit(
        "tile.upsert",
        aLiveTile({
          id: anId(7, "eeee0007"),
          label: named("planner"),
          group: "waiting",
          status: "waiting",
          issue: "AGH-131",
        }),
      );
    });
    expect(
      await screen.findByText("1 session waiting for approval: /planner."),
    ).toBeInTheDocument();
  });
});
