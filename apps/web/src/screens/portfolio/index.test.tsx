import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aNeedsYouItem,
  anActivityItem,
  aPage,
  aProblem,
  aProjectSummary,
  aStreamCounts,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { PortfolioScreen } from ".";

const twoProjects = aPage([
  aProjectSummary({
    name: "agent-hub",
    live_sessions: 2,
    runs_in_flight_by_stage: { IMPLEMENTING: 1, PR_OPEN: 1 },
  }),
  aProjectSummary({
    name: "loki-trader",
    hub_repo: "loki-trader-hub",
    live_sessions: 3,
    cost_period: "22.8000",
    cost_previous_period: "21.2600",
    runs_in_flight_by_stage: { VERIFYING: 1 },
    repos: ["tradeSentinel", "loki-trader-ui"],
    tracker_teams: ["LOK"],
  }),
]);

const sixNeeds = aPage([
  aNeedsYouItem({ kind: "learning", verb: "Triage 3 learnings", since: at(10) }),
  aNeedsYouItem({ kind: "failed", verb: "Look at failed run AGH-79", since: at(20) }),
  aNeedsYouItem({ kind: "approval", verb: "Approve plan for AGH-131", since: at(200) }),
  aNeedsYouItem({ kind: "approval", verb: "Allow edit under docs/adr/", since: at(100) }),
  aNeedsYouItem({ kind: "doctor", verb: "Fix doctor error in agent-hub", since: at(5) }),
  aNeedsYouItem({ kind: "blocked", verb: "Unblock session in tradeSentinel", since: at(30) }),
]);

const routes: ApiRoutes = {
  "/api/v1/projects": twoProjects,
  "/api/v1/needs-you": sixNeeds,
  "/api/v1/activity": aPage([
    anActivityItem({ kind: "failed", text: "Run AGH-79 failed at Verifying" }),
    anActivityItem({ kind: "learning", text: "Learning accepted", href: null }),
  ]),
};

describe("PortfolioScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("caps Needs you at 4 rows with Show N more when six items wait", async () => {
    renderWithApi(<PortfolioScreen />, { routes });

    await screen.findByText("Allow edit under docs/adr/");
    const needs = screen.getByRole("region", { name: "Needs you" });
    const rows = within(needs).getAllByRole("link");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Allow edit under docs/adr/"),
      expect.stringContaining("Approve plan for AGH-131"),
      expect.stringContaining("Unblock session in tradeSentinel"),
      expect.stringContaining("Look at failed run AGH-79"),
      expect.stringMatching(/^Show 2 more \(Fix doctor error in agent-hub, Triage 3 learnings\)/),
    ]);
    expect(within(needs).getByText("6")).toBeInTheDocument();
  });

  it("shows every item when the strip is expanded with needs=all", async () => {
    renderWithApi(<PortfolioScreen />, { routes, path: "/?needs=all" });

    await screen.findByText("Triage 3 learnings");
    const needs = screen.getByRole("region", { name: "Needs you" });
    expect(within(needs).getAllByRole("link")).toHaveLength(6);
  });

  it("shows live, runs in flight and estimated cost on cards with dashes for unconnected sources", async () => {
    renderWithApi(<PortfolioScreen />, { routes });

    const card = await screen.findByRole("article", { name: "Project agent-hub" });
    expect(within(card).getByText("Live sessions").nextSibling).toHaveTextContent("2");
    expect(within(card).getByText("Runs in progress · 2")).toBeInTheDocument();
    expect(within(card).getByText("$10.50")).toBeInTheDocument();
    const prs = within(card).getByText("Open PRs").nextElementSibling;
    expect(prs).toHaveTextContent("—CI —");
    expect(prs).toHaveAttribute("title", "GitHub is not connected in this version.");
    const ready = within(card).getByText("Ready issues").nextElementSibling;
    expect(ready).toHaveTextContent("—");
    expect(ready).toHaveAttribute("title", "Linear is not connected in this version.");
    expect(screen.getAllByText("Cost estimated from transcripts")).toHaveLength(2);
  });

  it("orders cards by items that need you, then live sessions", async () => {
    renderWithApi(<PortfolioScreen />, {
      routes: { ...routes, "/api/v1/needs-you": aPage([]) },
    });

    await screen.findByRole("article", { name: "Project agent-hub" });
    const names = screen.getAllByRole("article").map((card) => card.getAttribute("aria-label"));
    expect(names).toEqual(["Project loki-trader", "Project agent-hub"]);
  });

  it("switches to the dense table and remembers it in the URL", async () => {
    const user = userEvent.setup();
    const { router } = renderWithApi(<PortfolioScreen />, { routes });

    await user.click(await screen.findByRole("button", { name: "Dense table" }));

    expect(router.state.location.search).toContain("view=table");
    const table = await screen.findByRole("table", { name: "Projects" });
    expect(within(table).getByText("loki-trader")).toBeInTheDocument();
    expect(within(table).getAllByTitle("Linear is not connected in this version.")).toHaveLength(2);
    await user.click(within(table).getByText("loki-trader"));
    expect(router.state.location.pathname).toBe("/projects/loki-trader");
  });

  it("opens a project when its card is clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderWithApi(<PortfolioScreen />, { routes });

    await user.click(await screen.findByRole("article", { name: "Project agent-hub" }));

    expect(router.state.location.pathname).toBe("/projects/agent-hub");
  });

  it("filters the activity feed by kind and loads more when a cursor exists", async () => {
    const user = userEvent.setup();
    const { requests } = renderWithApi(<PortfolioScreen />, {
      routes: {
        ...routes,
        "/api/v1/activity": {
          ...aPage([
            anActivityItem({ kind: "failed", text: "Run AGH-79 failed" }),
            anActivityItem({ kind: "doctor", text: "New doctor error" }),
          ]),
          next_cursor: "c2",
        },
      },
    });

    expect(await screen.findByRole("link", { name: "Run AGH-79 failed" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await waitFor(() => {
      expect(requests.some((r) => r.url.includes("/activity") && r.url.includes("limit=40"))).toBe(
        true,
      );
    });
    await user.click(await screen.findByRole("button", { name: "Health" }));
    expect(screen.queryByText("Run AGH-79 failed")).not.toBeInTheDocument();
    expect(screen.getByText("New doctor error")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approvals" }));
    expect(screen.getByText("Nothing happened in this period.")).toBeInTheDocument();
  });

  it("passes the project scope to every request when a scope is chosen", async () => {
    const { requests } = renderWithApi(<PortfolioScreen />, { routes, path: "/?scope=agent-hub" });

    await screen.findByRole("region", { name: "Needs you" });
    const paths = ["/projects", "/needs-you", "/activity"];
    for (const path of paths) {
      expect(requests.find((r) => r.url.includes(path))?.url).toContain("project=agent-hub");
    }
  });

  it("refetches its regions when the global counts change", async () => {
    const { requests, stream } = renderWithApi(
      <GlobalStreamProvider project={null}>
        <PortfolioScreen />
      </GlobalStreamProvider>,
      { routes },
    );
    await screen.findByRole("region", { name: "Needs you" });
    const global = stream("/api/v1/events/stream");
    const before = requests.filter((r) => r.url.includes("/needs-you")).length;

    act(() => {
      global.open();
      global.emit("counts", aStreamCounts());
    });
    act(() => {
      global.emit("counts", aStreamCounts({ approvals_open: 3 }));
    });

    await waitFor(() => {
      expect(requests.filter((r) => r.url.includes("/needs-you")).length).toBeGreaterThan(before);
    });
  });

  describe("states", () => {
    it("shows skeletons after 300 ms while the requests are pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderWithApi(<PortfolioScreen />, {
          routes: {
            "/api/v1/projects": "pending",
            "/api/v1/needs-you": "pending",
            "/api/v1/activity": "pending",
          },
        });
        expect(document.querySelectorAll(".ah-skel")).toHaveLength(0);

        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });

        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(5);
        expect(screen.getByRole("region", { name: "Needs you" })).toHaveAttribute(
          "aria-busy",
          "true",
        );
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows the empty copy when nothing needs you and nothing runs", async () => {
      renderWithApi(<PortfolioScreen />, {
        routes: {
          "/api/v1/projects": aPage([
            aProjectSummary({
              live_sessions: 0,
              runs_in_flight_by_stage: {},
              failed_runs_7d: 0,
              cost_period: null,
              cost_previous_period: null,
              cost_daily: [],
            }),
          ]),
          "/api/v1/needs-you": aPage([]),
          "/api/v1/activity": aPage([]),
        },
      });

      expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
      expect(screen.getByText(/No session\s+is running\./)).toBeInTheDocument();
      expect(screen.getByText("Nothing happened in this period.")).toBeInTheDocument();
      expect(screen.getByText(/No sessions yet\. Start Claude Code in/)).toBeInTheDocument();
      expect(screen.getAllByText("No previous period to compare").length).toBeGreaterThan(0);
    });

    it("shows the live count in the empty copy when sessions run", async () => {
      renderWithApi(<PortfolioScreen />, { routes: { ...routes, "/api/v1/needs-you": aPage([]) } });

      expect(await screen.findByText(/5\s+sessions running\./)).toBeInTheDocument();
    });

    it("keeps each region's problem to itself when one request fails", async () => {
      const user = userEvent.setup();
      const { requests } = renderWithApi(<PortfolioScreen />, {
        routes: {
          ...routes,
          "/api/v1/projects": aProblem({
            status: 500,
            title: "Internal error",
            detail: "Reading hub.json failed.",
          }),
          "/api/v1/activity": aProblem({ status: 503, title: "Busy", detail: "Database busy." }),
        },
      });

      const alert = await screen.findByText("Could not load projects");
      expect(screen.getByText("Reading hub.json failed.")).toBeInTheDocument();
      expect(screen.getByText("Could not load activity")).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Needs you" })).toBeInTheDocument();
      const before = requests.filter((r) => r.url.includes("/projects")).length;
      await user.click(
        within(screen.getAllByRole("alert")[0] ?? alert).getByRole("button", {
          name: "Try again",
        }),
      );
      await waitFor(() => {
        expect(requests.filter((r) => r.url.includes("/projects")).length).toBe(before + 1);
      });
    });

    it("shows the needs-you problem in its region when it fails", async () => {
      renderWithApi(<PortfolioScreen />, {
        routes: {
          ...routes,
          "/api/v1/needs-you": aProblem({ title: "Internal error", detail: "Fold failed." }),
        },
      });

      expect(await screen.findByText("Could not load what needs you")).toBeInTheDocument();
      expect(await screen.findByRole("article", { name: "Project agent-hub" })).toBeInTheDocument();
    });

    it("stamps the header as stale when the collector is offline", async () => {
      renderWithApi(<PortfolioScreen />, { routes });

      await screen.findByRole("region", { name: "Needs you" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });

    it("has no stale stamp while the collector is connected", async () => {
      renderWithApi(
        <GlobalStreamProvider project={null}>
          <PortfolioScreen />
        </GlobalStreamProvider>,
        { routes },
      );

      await screen.findByRole("region", { name: "Needs you" });
      expect(screen.queryByText(/^Stale · as of/)).not.toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderWithApi(<PortfolioScreen />, { routes });

    await screen.findByRole("article", { name: "Project agent-hub" });
    await screen.findByText("Run AGH-79 failed at Verifying");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
