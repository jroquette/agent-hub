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
  const row = screen.getByRole("link", { name: slug }).closest("li");
  if (!row) throw new Error(`no row ${slug}`);
  return row;
}

function groupOf(title: RegExp): HTMLElement {
  const head = screen.getByRole("button", { name: title });
  const section = head.closest("section");
  if (!section) throw new Error(`no group ${title.source}`);
  return section;
}

const slugsIn = (el: HTMLElement) =>
  within(el)
    .queryAllByRole("link")
    .map((l) => l.textContent);

const waiting = aFeature({
  slug: "owner-held",
  verdict: "SHIP-WITH-OWNER-STEPS",
  acs: { owner_steps: 2, passing: 19, total: 21 },
  golden_path: aGoldenPath({
    phase: "evaluate",
    steps: [aGoldenStep({ name: "evaluate", state: "partial", meta: "waiting: owner steps" })],
  }),
  phase: "evaluate",
});

describe("FeaturesScreen", () => {
  it("groups features into Needs you, In progress and Shipped (groups)", async () => {
    const done = aFeature({
      slug: "shipped-one",
      phase: "shipped",
      verdict: "SHIP",
      golden_path: aGoldenPath({ phase: "shipped" }),
    });
    open({ "/api/v1/features": aPage([done, waiting, ...features]) });

    await screen.findByRole("link", { name: "layered-memory" });
    expect(slugsIn(groupOf(/^Needs you · 2$/))).toEqual(["broken-record", "owner-held"]);
    expect(slugsIn(groupOf(/^In progress · 3$/))).toEqual([
      "layered-memory",
      "control-plane",
      "tracker-team-cap",
    ]);
    expect(slugsIn(groupOf(/^Shipped · 1$/))).toEqual(["shipped-one"]);
  });

  it("says why a feature needs you and opens the tab that acts on it (needs)", async () => {
    const { router } = open({ "/api/v1/features": aPage([waiting, ...features]) });

    await screen.findByRole("link", { name: "owner-held" });
    expect(rowOf("owner-held")).toHaveTextContent("2 owner steps to do");
    expect(rowOf("broken-record")).toHaveTextContent(
      "features.json could not be parsed (line 38: trailing comma). Fix it in a hub PR.",
    );
    await userEvent.click(rowOf("owner-held"));
    expect(router.state.location.pathname).toBe("/features/agent-hub/owner-held");
    expect(router.state.location.search).toBe("?doc=acs");
  });

  it("names the current step on the row of a feature in progress (progress)", async () => {
    open();

    await screen.findByRole("link", { name: "tracker-team-cap" });
    expect(rowOf("tracker-team-cap")).toHaveTextContent("Plan · step 3 of 8 · plan.md");
  });

  it("shows five shipped features until asked for more (shipped)", async () => {
    const shipped = Array.from({ length: 7 }, (_, i) =>
      aFeature({
        slug: `shipped-${String(i)}`,
        phase: "shipped",
        golden_path: aGoldenPath({ phase: "shipped" }),
      }),
    );
    open({ "/api/v1/features": aPage(shipped) });

    await screen.findByRole("link", { name: "shipped-0" });
    expect(slugsIn(groupOf(/^Shipped · 7$/))).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Show 2 more shipped features" }));
    expect(slugsIn(groupOf(/^Shipped · 7$/))).toHaveLength(7);
  });

  it("collapses a group from its header (groups)", async () => {
    open();

    await screen.findByRole("link", { name: "control-plane" });
    await userEvent.click(screen.getByRole("button", { name: /^In progress/ }));
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^In progress/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await userEvent.click(screen.getByRole("button", { name: /^In progress/ }));
  });

  it("reads the owner step count from Evaluate's reason when the ACs do not carry it (needs)", async () => {
    const held = aFeature({
      slug: "held-by-reason",
      acs: { owner_steps: 0, passing: 12, total: 12 },
      golden_path: aGoldenPath({
        steps: [
          aGoldenStep({
            name: "evaluate",
            state: "partial",
            meta: "waiting: owner steps",
            reason: "3 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)",
          }),
        ],
      }),
    });
    open({ "/api/v1/features": aPage([held]) });

    await screen.findByRole("link", { name: "held-by-reason" });
    expect(rowOf("held-by-reason")).toHaveTextContent("3 owner steps to do");
  });

  it("shortens the Linear reason on the row of a feature in progress (progress)", async () => {
    const unread = aFeature({
      slug: "unread",
      golden_path: aGoldenPath({
        steps: [
          aGoldenStep({
            state: "unknown",
            meta: "33/33 ACs",
            reason: "Ticket status from Linear not loaded yet; open the Tickets tab.",
          }),
        ],
      }),
    });
    open({ "/api/v1/features": aPage([unread]) });

    await screen.findByRole("link", { name: "unread" });
    expect(rowOf("unread")).toHaveTextContent(
      "Implement · step 1 of 1 · ticket status not read from Linear yet",
    );
  });

  it("names every cell in the row's accessible name and moves with j and k (keyboard)", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    open();

    await screen.findByRole("link", { name: "layered-memory" });
    const row = rowOf("layered-memory");
    expect(row).toHaveAccessibleName(
      /^layered-memory\. .*\. golden path at Evaluate\. ACs 21 of 21\. verdict SHIP-WITH-OWNER-STEPS\. issues AGH-48, AGH-49, AGH-50$/,
    );
    await userEvent.keyboard("j");
    expect(rowOf("broken-record")).toHaveFocus();
    await userEvent.keyboard("j");
    expect(row).toHaveFocus();
  });

  it("finds features by name, issue or repo through the URL (search)", async () => {
    const { router } = open();

    await screen.findByRole("link", { name: "layered-memory" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "agh-49");

    expect(router.state.location.search).toBe("?q=agh-49");
    expect(screen.getByRole("link", { name: "layered-memory" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 4 features");
    expect(screen.queryByRole("button", { name: /^Needs you/ })).not.toBeInTheDocument();

    await userEvent.clear(screen.getByRole("searchbox", { name: "Find features" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "tradesentinel");
    expect(screen.getByRole("link", { name: "broken-record" })).toBeInTheDocument();
  });

  it("opens the extra issues in a popover (issues)", async () => {
    open();

    const row = rowOf((await screen.findByRole("link", { name: "layered-memory" })).textContent);
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
  });

  it("degrades only the malformed feature's ACs and tags its repo", async () => {
    open();

    await screen.findByRole("link", { name: "broken-record" });
    const row = rowOf("broken-record");
    expect(within(row).queryByRole("img", { name: /passing by command/ })).not.toBeInTheDocument();
    expect(within(row).getByText("tradeSentinel")).toBeInTheDocument();
    expect(within(row).getByText("loki-trader")).toBeInTheDocument();
  });

  it("filters by step through the URL (filters)", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: /^Step:/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Plan/ }));

    expect(router.state.location.search).toBe("?phase=plan");
    expect(screen.getByRole("link", { name: "tracker-team-cap" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
  });

  it("keeps an old verdict link as a removable chip (filters)", async () => {
    open({}, true, "/features?verdict=none");

    await screen.findByRole("link", { name: "control-plane" });
    expect(screen.queryByRole("link", { name: "layered-memory" })).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Remove filter Verdict Not evaluated" }),
    );
    expect(screen.getByRole("link", { name: "layered-memory" })).toBeInTheDocument();
  });

  it("says no feature matches and clears the filters", async () => {
    open({}, true, "/features?size=architectural&verdict=NO-SHIP");

    expect(await screen.findByText(/No features match these filters\./)).toBeInTheDocument();
    const [clear] = screen.getAllByRole("button", { name: "Clear filters" });
    if (!clear) throw new Error("no Clear filters");
    await userEvent.click(clear);
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
