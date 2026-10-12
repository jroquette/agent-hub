import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aLiveTile,
  aPage,
  aProblem,
  aSessionLabel,
  anId,
  at,
  renderWithApi,
  type ApiRoutes,
  type LiveTile,
} from "../../testing/builders";
import { LiveSessionsScreen } from "./index";
import { groupTiles, sortTiles } from "./tiles";

const LIVE = "/api/v1/live-sessions";

/** A tile label whose title is `/<name>` (no issue). */
function named(name: string) {
  return aSessionLabel({ issue: null, workflow: `/${name}`, workflows: [`/${name}`] });
}

function tiles(): LiveTile[] {
  return [
    aLiveTile({
      id: anId(1, "aaaa0001"),
      label: named("planner"),
      group: "waiting",
      status: "waiting",
      waiting_reason: "Plan approval",
      issue: "AGH-131",
    }),
    aLiveTile({
      id: anId(2, "aaaa0002"),
      label: named("idle-one"),
      group: "idle",
      status: "idle",
      started_at: at(-3000),
      last_action: "Edited src/OrderBook.tsx",
    }),
    aLiveTile({
      id: anId(3, "aaaa0003"),
      label: named("failing-one"),
      group: "live",
      status: "live",
      errors: 4,
      failing_notice: "make check-fast failed 2 times in a row",
      problems: { by_you: 0, handled: 1, needs_you: 1, open: 0 },
      needs_you_problem: "Needs you: command_exit in make check-fast",
      started_at: at(-60),
      budget_usd: "10.0000",
      cost_usd: "8.6200",
    }),
    aLiveTile({
      id: anId(4, "aaaa0004"),
      label: named("healthy-one"),
      group: "live",
      status: "live",
      started_at: at(-900),
    }),
    aLiveTile({
      id: anId(5, "aaaa0005"),
      label: named("evaluator"),
      group: "ended_recently",
      status: "ended",
      outcome: "done",
      ended_at: new Date(Date.now() - 60_000).toISOString(),
    }),
  ];
}

function renderLive(apiRoutes: ApiRoutes, path = "/live") {
  return renderWithApi(<LiveSessionsScreen />, { routes: apiRoutes, path });
}

describe("LiveSessionsScreen", () => {
  it("puts waiting first, edges the failing tile, keeps idle last and lists the ended tile when sessions vary", async () => {
    renderLive({ [LIVE]: aPage(tiles()) });

    const waiting = await screen.findByRole("region", { name: "Waiting for you" });
    expect(within(waiting).getByText("/planner")).toBeInTheDocument();
    const sections = screen
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(sections[0]).toBe("Waiting for you");

    const running = screen.getByRole("region", { name: "Running sessions" });
    const agents = within(running)
      .getAllByRole("article")
      .map((tile) => tile.querySelector(".ah-tile-agent")?.textContent);
    expect(agents).toEqual(["/failing-one", "/healthy-one", "/idle-one"]);
    const [failing] = within(running).getAllByRole("article");
    if (!failing) throw new Error("no tile");
    expect(failing).toHaveAttribute("data-trouble", "true");
    expect(
      within(failing).getByText("make check-fast failed 2 times in a row"),
    ).toBeInTheDocument();

    const ended = screen.getByRole("region", { name: "Ended in the last 2 min" });
    expect(within(ended).getByText("/evaluator")).toBeInTheDocument();
    expect(within(ended).getByText(/leaves this list 2 min after it ends/)).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === "1 waiting"),
    ).toBeInTheDocument();
  });

  it("orders tiles idle last and troubled first inside a group", () => {
    const [waiting, idle, failing, healthy] = tiles();
    if (!waiting || !idle || !failing || !healthy) throw new Error("tiles");
    expect(sortTiles([idle, healthy, failing]).map((tile) => tile.label?.workflow)).toEqual([
      "/failing-one",
      "/healthy-one",
      "/idle-one",
    ]);
    expect(groupTiles([idle, failing], "run").map((group) => group.label)).toEqual([
      "Not in a run",
    ]);
    expect(groupTiles([idle, failing], "workflow").map((group) => group.label)).toEqual([
      "/failing-one",
      "/idle-one",
    ]);
    expect(
      groupTiles([aLiveTile({ label: null }), idle], "workflow").map((group) => group.label),
    ).toEqual(["/idle-one", "No workflow"]);
  });

  it("opens the session with follow tail when a tile is clicked", async () => {
    const { router } = renderLive({ [LIVE]: aPage(tiles()) });

    fireEvent.click(await screen.findByText("/healthy-one"));
    expect(router.state.location.pathname).toBe(`/sessions/${anId(4, "aaaa0004")}`);
    expect(router.state.location.search).toBe("?follow=1");
  });

  it("regroups by run, workflow or flat when the grouping changes", async () => {
    const { router } = renderLive({ [LIVE]: aPage(tiles()) });

    expect(screen.queryByRole("button", { name: "Agent" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Workflow" }));
    expect(router.state.location.search).toBe("?group=workflow");
    expect(screen.getByText("/idle-one · 1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(screen.getByText("Not in a run · 3")).toBeInTheDocument();
  });

  it("applies tile.upsert and tile.remove from the stream", async () => {
    const { stream } = renderLive({ [LIVE]: aPage(tiles()) });
    await screen.findByText("/healthy-one");
    const source = stream("/api/v1/live-sessions/stream");

    act(() => {
      source.open();
      source.emit("tile.upsert", aLiveTile({ id: anId(9, "aaaa0009"), label: named("newcomer") }));
      source.emit("tile.upsert", { ...tiles()[3], last_action: "Ran make lint" });
      source.emit("tile.remove", { id: anId(2, "aaaa0002") });
    });

    expect(await screen.findByText("/newcomer")).toBeInTheDocument();
    expect(screen.getByText("Ran make lint")).toBeInTheDocument();
    expect(screen.queryByText("/idle-one")).not.toBeInTheDocument();
  });

  it("shows loading, empty, scoped empty, only ended, error and stale states", async () => {
    const pending = renderLive({ [LIVE]: "pending" });
    await waitFor(() => {
      expect(pending.container.querySelector(".ah-skel")).not.toBeNull();
    });
    pending.unmount();

    const empty = renderLive({ [LIVE]: aPage([]) });
    expect(await screen.findByText("No session is running")).toBeInTheDocument();
    expect(screen.getByText("cd ~/agent-hub-hub && claude")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See recent sessions" })).toHaveAttribute(
      "href",
      "/sessions",
    );
    empty.unmount();

    const scoped = renderLive(
      {
        [LIVE]: (request: Request) =>
          new URL(request.url).searchParams.get("project") ? aPage([]) : aPage(tiles().slice(0, 2)),
      },
      "/live?scope=loki-trader",
    );
    expect(
      await screen.findByText(
        "Nothing running in loki-trader. 2 sessions are running in other projects.",
      ),
    ).toBeInTheDocument();
    scoped.unmount();

    const ended = renderLive({ [LIVE]: aPage(tiles().slice(4)) });
    expect(await screen.findByText("No session is running. Recently ended:")).toBeInTheDocument();
    ended.unmount();

    const failed = renderLive({
      [LIVE]: aProblem({ status: 503, title: "Store busy", detail: "Try later" }),
    });
    expect(await screen.findByText("Could not load live sessions")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    failed.unmount();

    renderLive({ [LIVE]: aPage(tiles()) });
    expect((await screen.findAllByText(/Stale · as of/)).length).toBeGreaterThan(0);
  });

  it("shows the session label over repo · branch and never the agent when a main agent runs (label, AC-201.4)", async () => {
    renderLive({
      [LIVE]: aPage([
        aLiveTile({
          agent: "main",
          label: aSessionLabel({ issue: "DEMO-1511", repo: "demo", branch: "main" }),
        }),
      ]),
    });

    const tile = await screen.findByRole("article", { name: /^DEMO-1511 · \/feature in agent-hub/ });
    expect(within(tile).getByText("DEMO-1511 · /feature")).toBeInTheDocument();
    expect(within(tile).getByText("demo · main")).toBeInTheDocument();
    const texts = [...tile.querySelectorAll("*")]
      .flatMap((element) => [...element.childNodes])
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent ?? "");
    expect(texts.filter((text) => /\bmain\b/.test(text))).toEqual(["demo · main"]);
  });

  it("edges only the tile whose problem needs you and says why (problems, AC-201.14)", async () => {
    renderLive({
      [LIVE]: aPage([
        aLiveTile({
          id: anId(1, "ffff0001"),
          label: named("handled"),
          errors: 2,
          problems: { by_you: 0, handled: 2, needs_you: 0, open: 0 },
          failing_notice: "make check-fast failed 2 times in a row",
        }),
        aLiveTile({
          id: anId(2, "ffff0002"),
          label: named("stuck"),
          errors: 1,
          problems: { by_you: 0, handled: 0, needs_you: 1, open: 0 },
          needs_you_problem: "Needs you: command_exit in make check-fast",
        }),
        aLiveTile({
          id: anId(3, "ffff0003"),
          label: named("busy"),
          problems: { by_you: 1, handled: 0, needs_you: 0, open: 1 },
        }),
      ]),
    });

    const handled = await screen.findByRole("article", { name: /^\/handled/ });
    expect(handled).not.toHaveAttribute("data-trouble");
    expect(within(handled).getByText("2 problems, handled by the agent")).toBeInTheDocument();
    expect(
      within(handled).getByText("make check-fast failed 2 times in a row"),
    ).toBeInTheDocument();
    const stuck = screen.getByRole("article", { name: /^\/stuck/ });
    expect(stuck).toHaveAttribute("data-trouble", "true");
    expect(
      within(stuck).getByText("Needs you: command_exit in make check-fast"),
    ).toBeInTheDocument();
    const busy = screen.getByRole("article", { name: /^\/busy/ });
    expect(busy).not.toHaveAttribute("data-trouble");
    expect(
      within(busy).getByText("1 problem, agent is on it · 1 interrupted by you"),
    ).toBeInTheDocument();
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderLive({ [LIVE]: aPage(tiles()) });
    await screen.findByText("/healthy-one");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
