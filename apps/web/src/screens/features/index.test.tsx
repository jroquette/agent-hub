import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aGoldenPath,
  aGoldenStep,
  aPage,
  aProblem,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { FeaturesScreen, issueId } from "./index";
import { FEATURES_REFRESH_MS } from "./queries";

const features = [
  aFeature({
    slug: "tracker-team-cap",
    phase: "plan",
    files: ["spec.md", "plan.md"],
    acs: { owner_steps: 0, passing: 0, total: 9 },
    size: "bounded",
    issues: ["AGH-112"],
    golden_path: aGoldenPath({
      phase: "plan",
      steps: [
        aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
        aGoldenStep({ name: "research", state: "skipped", meta: null, progress: null }),
        aGoldenStep({ name: "plan", state: "current", meta: "plan.md", progress: null }),
        aGoldenStep({ name: "tickets", state: "pending", meta: null, progress: null }),
        aGoldenStep({ name: "implement", state: "pending", meta: null, progress: null }),
        aGoldenStep({
          name: "review",
          state: "unknown",
          meta: null,
          reason: "Linear not connected",
          progress: null,
        }),
        aGoldenStep({
          name: "evaluate",
          state: "partial",
          meta: "partial: covers 2 of 9 ACs",
          reason: "Plan is not done",
          progress: { done: 2, total: 9 },
        }),
        aGoldenStep({ name: "shipped", state: "done", meta: null, progress: null }),
      ],
    }),
  }),
  aFeature(),
  aFeature({
    slug: "layered-memory",
    phase: "evaluate",
    files: ["spec.md", "research.md", "plan.md", "issues.md", "features.json", "eval.md"],
    acs: { owner_steps: 1, passing: 20, total: 21 },
    verdict: "SHIP-WITH-OWNER-STEPS",
    verdict_line: "Verdict: SHIP-WITH-OWNER-STEPS",
    issues: ["AGH-48", "AGH-49", "AGH-50"],
  }),
  aFeature({
    slug: "broken-record",
    project: "loki-trader",
    repos: ["tradeSentinel"],
    phase: "spec",
    acs: null,
    problem: "features.json could not be parsed (line 38: trailing comma)",
    size: "spike",
  }),
];
const routes: ApiRoutes = { "/api/v1/features": aPage(features) };

function open(extra: ApiRoutes = {}, connected = true, path = "/features") {
  const ui = connected ? (
    <GlobalStreamProvider project={null}>
      <FeaturesScreen />
    </GlobalStreamProvider>
  ) : (
    <FeaturesScreen />
  );
  return renderWithApi(ui, { routes: { ...routes, ...extra }, path });
}

function rowOf(slug: string): HTMLElement {
  const row = screen.getByRole("link", { name: slug }).closest("tr");
  if (!row) throw new Error(`no row ${slug}`);
  return row;
}

describe("FeaturesScreen", () => {
  it("lists features furthest along first", async () => {
    open();

    await screen.findByRole("link", { name: "layered-memory" });
    const slugs = screen
      .getAllByRole("link")
      .map((l) => l.textContent)
      .filter((t) => features.some((f) => f.slug === t));
    expect(slugs).toEqual(["layered-memory", "control-plane", "tracker-team-cap", "broken-record"]);
    expect(screen.getByText("4 features").parentElement).toHaveTextContent(
      "4 features · 4 in progress · 0 shipped · furthest along first",
    );
  });

  it("sorts shipped features last and counts them apart (order)", async () => {
    const done = aFeature({
      slug: "shipped-one",
      phase: "shipped",
      golden_path: aGoldenPath({ phase: "shipped" }),
    });
    open({ "/api/v1/features": aPage([done, ...features]) });

    await screen.findByRole("link", { name: "shipped-one" });
    const slugs = screen
      .getAllByRole("link")
      .map((l) => l.textContent)
      .filter((t) => t === "shipped-one" || features.some((f) => f.slug === t));
    expect(slugs.at(-1)).toBe("shipped-one");
    expect(screen.getByText("5 features").parentElement).toHaveTextContent("1 shipped");
  });

  it("opens the extra issues in a popover (issues)", async () => {
    open();

    const row = (await screen.findByRole("link", { name: "layered-memory" })).closest("tr");
    if (!row) throw new Error("no row");
    expect(within(row).getByText("AGH-48")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "2 more issues" }));

    const popover = within(row).getByLabelText("All issues");
    expect(popover).toHaveTextContent("AGH-48AGH-49AGH-50");
  });

  it("keeps only the tracker id of an issue with a note (issues)", () => {
    expect(issueId("AGH-200 (provisional id: the Linear connector was unreachable)")).toBe(
      "AGH-200",
    );
    expect(issueId("AGH-48")).toBe("AGH-48");
    expect(issueId("TBD")).toBe("TBD");
  });

  it("puts the verdict's scope under its badge while Evaluate is not done (verdict)", async () => {
    const held = aFeature({
      slug: "held",
      verdict: "SHIP-WITH-OWNER-STEPS",
      golden_path: aGoldenPath({
        phase: "evaluate",
        steps: [
          aGoldenStep({ name: "evaluate", state: "partial", meta: "partial: covers 2 of 9 ACs" }),
        ],
      }),
    });
    open({ "/api/v1/features": aPage([held]) });

    const row = (await screen.findByRole("link", { name: "held" })).closest("tr");
    if (!row) throw new Error("no row");
    const verdict = within(row).getAllByRole("cell").at(-1);
    expect(verdict).toHaveTextContent("SHIP-WITH-OWNER-STEPS");
    expect(verdict).toHaveTextContent("partial: covers 2 of 9 ACs");
  });

  it("reads the AC bar as N/M · K owner step with the owner segment hatched", async () => {
    open();

    await screen.findByRole("link", { name: "layered-memory" });
    const row = rowOf("layered-memory");
    expect(within(row).getByText("21/21").parentElement).toHaveTextContent("21/21 · 1 owner step");
    const owner = row.querySelector('[data-segment="owner"]');
    expect(owner).toHaveAttribute("data-hatched", "true");
    expect(
      within(row).getByRole("img", {
        name: "20 passing by command · 1 owner step · 0 not passing yet",
      }),
    ).toBeInTheDocument();
    expect(within(row).getByText("SHIP-WITH-OWNER-STEPS")).toBeInTheDocument();
  });

  it("draws the server's golden path with each state's text and reason (golden)", async () => {
    open();

    await screen.findByRole("link", { name: "tracker-team-cap" });
    const row = rowOf("tracker-team-cap");
    const bar = within(row).getByRole("img", { name: /^Golden path: Plan\./ });
    const name = bar.getAttribute("aria-label") ?? "";
    expect(name).toContain("Review: unknown (Linear not connected)");
    expect(name).toContain("Evaluate: partial · partial: covers 2 of 9 ACs (Plan is not done)");
    expect(name).toContain("Shipped: blocked (Plan is not done)");
    expect(
      [...bar.querySelectorAll("[data-state]")].map((s) => s.getAttribute("data-state")),
    ).toEqual([
      "done",
      "skipped",
      "current",
      "pending",
      "pending",
      "unknown",
      "partial",
      "blocked",
    ]);
    expect(within(row).getByText("plan.md")).toBeInTheDocument();
    expect(within(row).getByText("—", { selector: "td > span" })).toBeInTheDocument();
  });

  it("degrades only the malformed feature's ACs", async () => {
    open();

    await screen.findByRole("link", { name: "broken-record" });
    const row = rowOf("broken-record");
    expect(
      within(row).getByRole("img", {
        name: "features.json could not be parsed (line 38: trailing comma)",
      }),
    ).toBeInTheDocument();
    expect(row).toHaveTextContent("loki-trader · tradeSentinel");
  });

  it("filters by verdict through the URL", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: "Verdict: All" }));
    await userEvent.click(screen.getByRole("button", { name: "Not evaluated" }));

    expect(router.state.location.search).toBe("?verdict=none");
    expect(screen.queryByRole("link", { name: "layered-memory" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "control-plane" })).toBeInTheDocument();
  });

  it("says no feature matches and clears the filters", async () => {
    open({}, true, "/features?size=architectural&verdict=NO-SHIP");

    expect(await screen.findByText("No features match these filters.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByRole("link", { name: "control-plane" })).toBeInTheDocument();
  });

  it("opens the feature detail from its row", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("link", { name: "control-plane" }));

    expect(router.state.location.pathname).toBe("/features/agent-hub/control-plane");
  });

  it("asks for the scoped project's features", async () => {
    const { requests } = open({}, true, "/features?scope=agent-hub");

    await screen.findByRole("link", { name: "control-plane" });
    expect(new URL(requests[0]?.url ?? "").searchParams.get("project")).toBe("agent-hub");
  });

  describe("states", () => {
    it("shows skeleton rows while loading", async () => {
      const { container } = open({ "/api/v1/features": "pending" });

      await waitFor(() => {
        expect(container.querySelector(".ah-skel")).not.toBeNull();
      });
    });

    it("shows the design's empty copy when no feature is recorded", async () => {
      open({ "/api/v1/features": aPage([]) });

      expect(await screen.findByText("No feature records yet.")).toBeInTheDocument();
      expect(screen.getByText("/feature AGH-112")).toBeInTheDocument();
    });

    it("shows the problem in place with Try again", async () => {
      open({
        "/api/v1/features": aProblem({
          status: 503,
          title: "Hub not readable",
          detail: "The hub at /home/dev/agent-hub-hub is not readable.",
        }),
      });

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Hub not readable");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("shows the as-of stamp when the collector is offline", () => {
      open({}, false);

      expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    });
  });

  it("rereads the records every 30 s while open (refresh)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { requests } = open();
      await screen.findByRole("link", { name: "layered-memory" });
      const reads = () =>
        requests.filter((r) => new URL(r.url).pathname === "/api/v1/features").length;
      const before = reads();

      await vi.advanceTimersByTimeAsync(FEATURES_REFRESH_MS);

      await waitFor(() => {
        expect(reads()).toBeGreaterThan(before);
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByRole("link", { name: "layered-memory" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
