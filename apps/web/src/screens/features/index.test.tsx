import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aFeatureTickets,
  aGoldenPath,
  aGoldenStep,
  aLiveTile,
  aPage,
  aProblem,
  aSessionLabel,
  aShellView,
  renderWithApi,
  type ApiRoutes,
  type FeatureView,
} from "../../testing/builders";
import { noteLaunchCookie } from "../../lib/launchCookie";
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
        aGoldenStep({ name: "ux_design", state: "skipped", meta: null, progress: null }),
        aGoldenStep({ name: "research", state: "skipped", meta: null, progress: null }),
        aGoldenStep({ name: "plan", state: "current", meta: "plan.md", progress: null }),
        aGoldenStep({ name: "tickets", state: "pending", meta: null, progress: null }),
        aGoldenStep({
          name: "build",
          state: "unknown",
          meta: null,
          reason: "Linear not connected",
          progress: null,
        }),
        aGoldenStep({
          name: "acceptance",
          state: "partial",
          meta: "Ticket evals cover 2 of 9 ACs",
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
    phase: "acceptance",
    files: ["spec.md", "research.md", "plan.md", "issues.md", "features.json", "eval.md"],
    acs: { owner_steps: 1, passing: 20, total: 21 },
    verdict: "SHIP-WITH-OWNER-STEPS",
    verdict_line: "Verdict: SHIP-WITH-OWNER-STEPS",
    issues: ["AGH-48", "AGH-49", "AGH-50"],
  }),
  aFeature({
    slug: "broken-record",
    project: "acme-market",
    repos: ["marketService"],
    phase: "spec",
    acs: null,
    problem: "features.json could not be parsed (line 38: trailing comma)",
    size: "spike",
  }),
];
const routes: ApiRoutes = { "/api/v1/features": aPage(features) };

/** Where the list keeps which groups are folded; each test starts from the defaults. */
const COLLAPSED = "ah.features.collapsed.v2";
afterEach(() => {
  window.localStorage.removeItem(COLLAPSED);
});

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
    phase: "acceptance",
    steps: [
      aGoldenStep({
        name: "acceptance",
        state: "waiting",
        meta: "Waiting for you: sign off 2 ACs",
      }),
    ],
  }),
  phase: "acceptance",
  waiting_on_owner: { kind: "owner_signoff", tickets: [] },
});

describe("FeaturesScreen", () => {
  it("groups features into Needs you, Active and Ready to close, with Shipped and closed folded (groups)", async () => {
    const done = aFeature({
      slug: "shipped-one",
      phase: "shipped",
      verdict: "SHIP",
      golden_path: aGoldenPath({ phase: "shipped" }),
    });
    open({ "/api/v1/features": aPage([done, waiting, ...features]) });

    await screen.findByRole("link", { name: "layered-memory" });
    expect(slugsIn(groupOf(/^Needs you · 1$/))).toEqual(["broken-record"]);
    expect(slugsIn(groupOf(/^Active · 2$/))).toEqual(["control-plane", "tracker-team-cap"]);
    expect(slugsIn(groupOf(/^Ready to close · 2$/))).toEqual(["owner-held", "layered-memory"]);
    expect(rowOf("broken-record")).toHaveAttribute("data-tone", "blocked");
    expect(rowOf("owner-held")).not.toHaveAttribute("data-tone");
    expect(rowOf("layered-memory")).not.toHaveAttribute("data-tone");
    expect(groupOf(/^Needs you · 1$/)).toHaveTextContent("1 record cannot be read");
    const shipped = screen.getByRole("button", { name: /^Shipped and closed · 1$/ });
    expect(shipped).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "shipped-one" })).not.toBeInTheDocument();
    await userEvent.click(shipped);
    expect(slugsIn(groupOf(/^Shipped and closed · 1$/))).toEqual(["shipped-one"]);
    expect(rowOf("shipped-one")).toHaveAttribute("data-muted", "true");
  });

  it("says why a feature sits in its group and opens the tab that acts on it (needs)", async () => {
    const { router } = open({ "/api/v1/features": aPage([waiting, ...features]) });

    await screen.findByRole("link", { name: "owner-held" });
    expect(rowOf("owner-held")).toHaveTextContent("Sign off 2 checks of yours, or close it");
    expect(rowOf("broken-record")).toHaveTextContent(
      "features.json could not be parsed (line 38: trailing comma). Fix it in a hub PR.",
    );
    await userEvent.click(rowOf("owner-held"));
    expect(router.state.location.pathname).toBe("/features/agent-hub/owner-held");
    expect(router.state.location.search).toBe("?doc=acs");
  });

  // two-level-flows AC-2.8: a plan change ranks the feature in Needs you and opens the ticket
  // panel at the asking ticket's request.
  it("ranks a plan change first among the waits and opens its ticket panel (AC-2.8)", async () => {
    const asking = aFeature({
      slug: "plan-change",
      waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] },
    });
    const { router } = open({ "/api/v1/features": aPage([waiting, asking, ...features]) });

    await screen.findByRole("link", { name: "plan-change" });
    expect(rowOf("plan-change")).toHaveTextContent("Plan change waits for you · from DEM-8");
    expect(rowOf("plan-change")).toHaveAttribute("data-tone", "waiting");
    expect(slugsIn(groupOf(/^Needs you · 2$/))).toEqual(["broken-record", "plan-change"]);
    expect(slugsIn(groupOf(/^Ready to close · 2$/))).toContain("owner-held");
    expect(groupOf(/^Needs you · 2$/)).toHaveTextContent("1 plan change waits for you");
    await userEvent.click(rowOf("plan-change"));
    expect(router.state.location.search).toBe("?doc=tickets&ticket=DEM-8&step=preflight");
  });

  // U9: the hint counts in words that agree with the count.
  it("says several waits in the plural in the group hint (needs)", async () => {
    const asking = (slug: string) =>
      aFeature({ slug, waiting_on_owner: { kind: "change_request", tickets: ["DEM-8"] } });
    open({ "/api/v1/features": aPage([asking("plan-a"), asking("plan-b")]) });

    await screen.findByRole("link", { name: "plan-a" });
    expect(groupOf(/^Needs you · 2$/)).toHaveTextContent("2 plan changes wait for you");
  });

  it("names the current step on the row of an active feature (progress)", async () => {
    open();

    await screen.findByRole("link", { name: "tracker-team-cap" });
    const row = rowOf("tracker-team-cap");
    expect(row.querySelector(".ft-stage")).toHaveTextContent(/^Plan$/);
    expect(row.querySelector(".ft-row-line")).toHaveTextContent(/^Next: write the plan$/);
  });

  it("shows five shipped or closed features until asked for more (shipped)", async () => {
    const shipped = Array.from({ length: 7 }, (_, i) =>
      aFeature({
        slug: `shipped-${String(i)}`,
        phase: "shipped",
        golden_path: aGoldenPath({ phase: "shipped" }),
      }),
    );
    open({ "/api/v1/features": aPage(shipped) });

    await userEvent.click(await screen.findByRole("button", { name: /^Shipped and closed · 7$/ }));
    expect(slugsIn(groupOf(/^Shipped and closed · 7$/))).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Show 2 more features" }));
    expect(slugsIn(groupOf(/^Shipped and closed · 7$/))).toHaveLength(7);
  });

  it("collapses a group from its header (groups)", async () => {
    open();

    await screen.findByRole("link", { name: "control-plane" });
    await userEvent.click(screen.getByRole("button", { name: /^Active/ }));
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Active/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await userEvent.click(screen.getByRole("button", { name: /^Active/ }));
  });

  it("reads the owner step count from Acceptance's reason when the ACs do not carry it (needs)", async () => {
    const held = aFeature({
      slug: "held-by-reason",
      acs: { owner_steps: 0, passing: 12, total: 12 },
      waiting_on_owner: { kind: "owner_signoff", tickets: [] },
      golden_path: aGoldenPath({
        steps: [
          aGoldenStep({
            name: "acceptance",
            state: "waiting",
            meta: "Waiting for you: sign off 3 ACs",
            reason: "3 ACs wait on owner steps (SHIP-WITH-OWNER-STEPS)",
          }),
        ],
      }),
    });
    open({ "/api/v1/features": aPage([held]) });

    await screen.findByRole("link", { name: "held-by-reason" });
    expect(rowOf("held-by-reason")).toHaveTextContent("Sign off 3 checks of yours, or close it");
  });

  it("says the Linear gap once above the list, not on each row (progress)", async () => {
    const unread = aFeature({
      slug: "unread",
      golden_path: aGoldenPath({
        steps: [
          aGoldenStep({
            state: "unknown",
            meta: "Linear not loaded yet",
            reason: "Ticket status from Linear not loaded yet; open the Tickets tab.",
          }),
        ],
      }),
    });
    open({ "/api/v1/features": aPage([unread]) });

    await screen.findByRole("link", { name: "unread" });
    expect(rowOf("unread").querySelector(".ft-row-line")).toHaveTextContent(/^Building$/);
    expect(screen.getByRole("note")).toHaveTextContent(
      "This list doesn't load ticket status from Linear, so some features can't show how many tickets are merged. Open a feature to see its tickets.",
    );
  });

  it("names every cell in the row's accessible name and moves with j and k (keyboard)", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    open();

    await screen.findByRole("link", { name: "layered-memory" });
    const row = rowOf("layered-memory");
    expect(row).toHaveAccessibleName(
      /^layered-memory\. .*\. golden path at Acceptance, step 7 of 8, Acceptance: partial · .*\. ACs 21 of 21\. verdict SHIP-WITH-OWNER-STEPS\. issues AGH-48, AGH-49, AGH-50$/,
    );
    // Needs you, then Active, then Ready to close, in the order on the page.
    await userEvent.keyboard("j");
    expect(rowOf("broken-record")).toHaveFocus();
    await userEvent.keyboard("jjj");
    expect(row).toHaveFocus();
    await userEvent.keyboard("k");
    expect(rowOf("tracker-team-cap")).toHaveFocus();
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
    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "marketservice");
    expect(screen.getByRole("link", { name: "broken-record" })).toBeInTheDocument();
  });

  it("shows the first issue id and how many more, with every issue in its title (issues)", async () => {
    open();

    const row = rowOf((await screen.findByRole("link", { name: "layered-memory" })).textContent);
    expect(within(row).getByText("AGH-48 +2")).toHaveAttribute("title", "AGH-48, AGH-49, AGH-50");
    expect(within(row).queryByRole("button", { name: /more issue/ })).not.toBeInTheDocument();
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
    expect(within(row).getByText("21 of 21").parentElement).toHaveTextContent(
      "21 of 21 · 1 owner step",
    );
    const owner = row.querySelector('[data-segment="owner"]');
    expect(owner).toHaveAttribute("data-hatched", "true");
    expect(
      within(row).getByRole("img", {
        name: "20 pass their check · 1 owner step (checked by you) · 0 not passing yet",
      }),
    ).toBeInTheDocument();
    expect(row).toHaveTextContent("Evaluator says ship · records still show Acceptance");
  });

  it("names the stage a row is at, with its state when not simply in progress, and 'Shipped' alone once shipped (AC-1.12)", async () => {
    const shipped = aFeature({
      slug: "shipped-one",
      phase: "shipped",
      // A shipped feature has every step done (the phase is the first step not done).
      golden_path: aGoldenPath({
        phase: "shipped",
        steps: aGoldenPath().steps.map((step) => ({ ...step, state: "done", reason: null })),
      }),
    });
    open({ "/api/v1/features": aPage([shipped, waiting, ...features]) });

    await screen.findByRole("link", { name: "control-plane" });
    expect(rowOf("control-plane").querySelector(".ft-stage")).toHaveTextContent(/^Build$/);
    expect(rowOf("owner-held").querySelector(".ft-stage")).toHaveTextContent(
      /^Acceptance\s*waiting for you$/,
    );
    await userEvent.click(screen.getByRole("button", { name: /^Shipped and closed/ }));
    expect(rowOf("shipped-one").querySelector(".ft-stage")).toHaveTextContent(/^Shipped$/);
  });

  it("offers the eight feature steps in the Step filter (AC-1.12)", async () => {
    open();

    await userEvent.click(await screen.findByRole("button", { name: /^Step:/ }));
    expect(
      within(screen.getByRole("dialog", { name: "Step filter" }))
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")?.querySelector("span:not(.ah-count)")?.textContent),
    ).toEqual([
      "Spec",
      "UX design",
      "Research",
      "Plan",
      "Tickets",
      "Build",
      "Acceptance",
      "Shipped",
    ]);
  });

  it("turns old ?phase=implement and review into build and evaluate into acceptance, replacing the URL (AC-1.12)", async () => {
    const { router } = open({}, true, "/features?phase=implement,review,evaluate&q=a");

    await waitFor(() => {
      expect(new URLSearchParams(router.state.location.search).get("phase")).toBe(
        "build,acceptance",
      );
    });
    expect(new URLSearchParams(router.state.location.search).get("q")).toBe("a");
    expect(router.state.historyAction).toBe("REPLACE");
    expect(await screen.findByRole("link", { name: "layered-memory" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "control-plane" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "tracker-team-cap" })).not.toBeInTheDocument();
  });

  it("reads the position and the current step's summary in the row's accessible name (AC-1.12)", async () => {
    open();

    await screen.findByRole("link", { name: "control-plane" });
    expect(rowOf("control-plane")).toHaveAccessibleName(
      /\. golden path at Build, step 6 of 8, Build: in progress · 1 of 3 merged · 1 in progress\. /,
    );
  });

  it("filters by the new step on the first render of an old ?phase= link, with no empty flash (AC-1.12)", async () => {
    const { router } = open();
    await screen.findByRole("link", { name: "control-plane" });
    const seen: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const record of records)
        for (const node of record.addedNodes) seen.push(node.textContent ?? "");
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    await act(() => router.navigate("/features?phase=implement"));
    await waitFor(() => {
      expect(router.state.location.search).toBe("?phase=build");
    });
    observer.disconnect();

    expect(seen.join(" ")).not.toMatch(/No features match|0 of \d/);
    expect(screen.getByRole("link", { name: "control-plane" })).toBeInTheDocument();
  });

  it("drops old ?phase= ids that are not feature steps, replacing the URL (AC-1.12)", async () => {
    const { router } = open({}, true, "/features?phase=implement,bogus&q=a");

    await waitFor(() => {
      expect(router.state.location.search).toBe("?phase=build&q=a");
    });
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("drops a ?phase= of only unknown ids, so the list is not filtered (AC-1.12)", async () => {
    const { router } = open({}, true, "/features?phase=bogus");

    await waitFor(() => {
      expect(router.state.location.search).toBe("");
    });
    expect(await screen.findByRole("link", { name: "layered-memory" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Step:/ })).toHaveAccessibleName(/Any/);
  });

  it("degrades only the malformed feature's ACs and tags its repo", async () => {
    open();

    await screen.findByRole("link", { name: "broken-record" });
    const row = rowOf("broken-record");
    expect(within(row).queryByRole("img", { name: /pass their check/ })).not.toBeInTheDocument();
    expect(within(row).getByText("marketService")).toBeInTheDocument();
    expect(within(row).getByText("acme-market")).toBeInTheDocument();
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

  it("opens New feature from the title row (AC-420.1)", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: "New feature" }));

    expect(router.state.location.pathname).toBe("/features/new");
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
      // AC-420.1: the empty state points at New feature too.
      expect(screen.getByText(/one here with/)).toHaveTextContent("New feature");
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

    it("shows no session working on a feature while the collector is offline (AC-521.8.6)", async () => {
      const busy = aLiveTile({
        id: "s-busy",
        group: "live",
        issue: "AGH-49",
        last_action: "Edited eval.md",
      });
      open({ "/api/v1/live-sessions": aPage([busy]) }, false);

      const row = await waitFor(() => rowOf("layered-memory"));
      expect(row).not.toHaveTextContent("A session is working");
      expect(row.querySelector(".ft-row-lead .ah-pulse")).toBeNull();
      expect(document.querySelector('.ft-summary [data-group="working"]')).toBeNull();
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

  it("locks renaming, saying why, without the launch cookie (names)", async () => {
    noteLaunchCookie("missing");
    const { requests } = open({
      "/api/v1/screens/shell": aShellView({ launch_cookie: "missing" }),
    });

    const rename = await screen.findByRole("button", { name: "Give control-plane a name" });
    expect(rename).toBeDisabled();
    expect(rename).toHaveAttribute("title", expect.stringMatching(/hub web printed/));
    expect(requests.some((r) => r.method === "PUT")).toBe(false);
  });

  it("shows a feature's nickname with its slug, and renames it inline (names)", async () => {
    const saved: unknown[] = [];
    const names = [{ project: "agent-hub", slug: "layered-memory", name: "Layered memory" }];
    const { requests } = open({
      "/api/v1/feature-names": () => ({ items: names }),
      "PUT /api/v1/feature-names": (request: Request) => {
        void request
          .clone()
          .json()
          .then((body) => saved.push(body));
        names.push({ project: "agent-hub", slug: "control-plane", name: "Control plane" });
        return names[1];
      },
    });

    const named = await screen.findByRole("link", { name: "Layered memory" });
    expect(named.closest("li")).toHaveTextContent("layered-memory");

    await userEvent.click(screen.getByRole("button", { name: "Give control-plane a name" }));
    const field = screen.getByRole("textbox", { name: "Name for control-plane" });
    await userEvent.type(field, "Control plane{Enter}");

    expect(await screen.findByRole("link", { name: "Control plane" })).toBeInTheDocument();
    await waitFor(() => {
      expect(requests.some((r) => r.method === "PUT")).toBe(true);
    });
    await waitFor(() => {
      expect(saved).toEqual([
        { project: "agent-hub", slug: "control-plane", name: "Control plane" },
      ]);
    });
  });

  it("finds a feature by its nickname (names)", async () => {
    open(
      {
        "/api/v1/feature-names": {
          items: [{ project: "agent-hub", slug: "layered-memory", name: "Brain layers" }],
        },
      },
      true,
      "/features?q=brain",
    );

    expect(await screen.findByRole("link", { name: "Brain layers" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
  });

  it("lists a ship verdict whose records are not done under Ready to close, naming the records' step: no Evaluated group (AC-1.15)", async () => {
    const evaluated = aFeature({
      slug: "evaluated-one",
      verdict: "SHIP",
      verdict_line: "**Verdict: SHIP.** All 9 ACs pass on main.",
      acs: { owner_steps: 0, passing: 9, total: 9 },
    });
    const { container } = open({ "/api/v1/features": aPage([evaluated, waiting, ...features]) });

    await screen.findByRole("link", { name: "evaluated-one" });
    expect(
      [...container.querySelectorAll("section[data-group]")].map((s) =>
        s.getAttribute("data-group"),
      ),
    ).toEqual(["needs", "active", "ready", "quiet", "paused", "done"]);
    expect(screen.queryByRole("button", { name: /^Evaluated/ })).not.toBeInTheDocument();
    expect(slugsIn(groupOf(/^Ready to close · 3$/))).toContain("evaluated-one");
    expect(rowOf("evaluated-one")).not.toHaveAttribute("data-tone");
    expect(rowOf("evaluated-one").querySelector(".ft-row-line")).toHaveTextContent(
      /^Evaluator says ship · records still show Build · 1 of 3 tickets merged$/,
    );
    expect(container.querySelector(".ft-summary")).toHaveTextContent(
      /^1 need you\s*2 active\s*3 ready to close\s*0 quiet\s*0 paused\s*0 shipped or closed/,
    );
  });

  it("drops a stored id that is no longer a group from the folded groups (AC-1.15)", async () => {
    window.localStorage.setItem(COLLAPSED, JSON.stringify(["evaluated", "done"]));
    open();

    await screen.findByRole("link", { name: "control-plane" });
    expect(screen.getByRole("button", { name: /^Shipped and closed/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    await userEvent.click(screen.getByRole("button", { name: /^Shipped and closed/ }));
    expect(JSON.parse(window.localStorage.getItem(COLLAPSED) ?? "")).toEqual([]);
  });

  it("folds Quiet, Paused and Shipped and closed until opened, whatever the old key stored (groups)", async () => {
    window.localStorage.setItem("ah.features.collapsed", JSON.stringify([]));
    try {
      open();

      await screen.findByRole("link", { name: "control-plane" });
      const expanded = (title: RegExp) =>
        screen.getByRole("button", { name: title }).getAttribute("aria-expanded");
      expect(
        [
          /^Needs you/,
          /^Active/,
          /^Ready to close/,
          /^Quiet/,
          /^Paused/,
          /^Shipped and closed/,
        ].map(expanded),
      ).toEqual(["true", "true", "true", "false", "false", "false"]);
      await userEvent.click(screen.getByRole("button", { name: /^Quiet/ }));
      expect(JSON.parse(window.localStorage.getItem(COLLAPSED) ?? "")).toEqual(["paused", "done"]);
    } finally {
      window.localStorage.removeItem("ah.features.collapsed");
    }
  });

  it("puts a feature whose session waits on you at the top of Needs you and opens the feature, not the chat (session)", async () => {
    const permission = aLiveTile({
      id: "s-perm",
      group: "waiting",
      status: "waiting",
      issue: null,
      label: aSessionLabel({ issue: "AGH-112", branch: "dev/agh-112-team-cap" }),
      waiting_reason: "Permission prompt",
      agent_session_id: "a-perm",
    });
    const yourTurn = aLiveTile({
      id: "s-turn",
      group: "idle",
      status: "idle",
      issue: null,
      label: aSessionLabel({ issue: null, title: "layered-memory review" }),
      last_action: "Edited plan.md",
    });
    const busy = aLiveTile({
      id: "s-busy",
      group: "live",
      issue: null,
      label: aSessionLabel({ issue: null, title: "control-plane build" }),
      last_action: "Edited eval.md",
    });
    const { router } = open({
      "/api/v1/live-sessions": aPage([permission, yourTurn, busy]),
    });

    await waitFor(() => {
      expect(slugsIn(groupOf(/^Needs you · 3$/))).toEqual([
        "tracker-team-cap",
        "layered-memory",
        "broken-record",
      ]);
    });
    expect(rowOf("tracker-team-cap")).toHaveTextContent(
      "A session waits on you · Permission prompt",
    );
    expect(rowOf("layered-memory")).toHaveTextContent("Your turn in a session · Edited plan.md");
    expect(slugsIn(groupOf(/^Active · 1$/))).toEqual(["control-plane"]);
    expect(rowOf("control-plane")).not.toHaveAttribute("data-tone");
    expect(rowOf("control-plane")).toHaveTextContent("A session is working · Edited eval.md");
    expect(rowOf("control-plane").querySelector(".ft-row-lead .ah-pulse")).not.toBeNull();
    expect(rowOf("control-plane").querySelector(".ft-col-activity")).toHaveTextContent(/^now$/);
    expect(rowOf("control-plane")).toHaveAccessibleName(
      /^control-plane\. A session is working · Edited eval\.md\. Building · 1 of 3 tickets merged/,
    );
    expect(document.querySelector('.ft-summary [data-group="working"]')).toHaveTextContent(
      "1 working now",
    );
    expect(groupOf(/^Needs you · 3$/)).toHaveTextContent(
      "1 session waits on you · 1 your turn in a session",
    );

    await userEvent.click(rowOf("tracker-team-cap"));
    expect(router.state.location.pathname).toBe("/features/agent-hub/tracker-team-cap");
    expect(router.state.location.search).toBe("");
  });

  it("flags a NO-SHIP row as failed in Needs you and counts the rows that need you (needs)", async () => {
    const noShip = aFeature({
      slug: "no-ship-one",
      verdict: "NO-SHIP",
      verdict_line: "**Verdict: NO-SHIP.** The export drops the last row.",
    });
    open({ "/api/v1/features": aPage([noShip, waiting, ...features]) });

    await screen.findByRole("link", { name: "no-ship-one" });
    expect(rowOf("no-ship-one")).toHaveAttribute("data-tone", "failed");
    expect(rowOf("no-ship-one")).toHaveTextContent(
      "Evaluator says no ship: The export drops the last row.",
    );
    expect(slugsIn(groupOf(/^Needs you · 2$/))).toEqual(["broken-record", "no-ship-one"]);
    expect(groupOf(/^Needs you · 2$/)).toHaveTextContent(
      "Work that stops until you act: a session waiting, a plan change, a no-ship verdict, a broken record · 1 no ship · 1 record cannot be read",
    );
    expect(document.querySelector('.ft-summary [data-group="needs"]')).toHaveTextContent(
      "2 need you",
    );
  });
});

// Vitest runs from apps/web and does not process CSS imports, so the rules are read as files.
const cssOf = (path: string) => readFileSync(join(process.cwd(), path), "utf8");
const ruleOf = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(css);
  if (!rule?.[1]) throw new Error(`no rule ${selector}`);
  return rule[1];
};

function facetCount(option: RegExp): string | null | undefined {
  return screen.getByRole("checkbox", { name: option }).closest("label")?.querySelector(".ah-count")
    ?.textContent;
}

describe("FeaturesScreen (playground delivery)", () => {
  const noted = aFeature({
    slug: "noted",
    issues: ["AGH-200 (provisional id: the Linear connector was unreachable)", "AGH-201"],
  });

  it("shows only the tracker id of the first issue on the row, with every full entry in its title (AC-PG-6.1)", async () => {
    open({ "/api/v1/features": aPage([noted, aFeature({ slug: "plain", issues: ["AGH-7"] })]) });

    await screen.findByRole("link", { name: "noted" });
    const id = within(rowOf("noted")).getByText("AGH-200 +1");
    expect(id).toHaveAttribute(
      "title",
      "AGH-200 (provisional id: the Linear connector was unreachable), AGH-201",
    );
    expect(within(rowOf("plain")).getByText("AGH-7")).toHaveAttribute("title", "AGH-7");
  });

  it("does not make the issue id a focus stop, so Tab moves from the row to its rename button and out (AC-PG-6.1)", async () => {
    open({ "/api/v1/features": aPage([noted]) });

    await screen.findByRole("link", { name: "noted" });
    const row = rowOf("noted");
    const id = within(row).getByText("AGH-200 +1");
    expect(id).not.toHaveAttribute("tabindex");

    row.focus();
    await userEvent.tab();
    expect(within(row).getByRole("button", { name: "Give noted a name" })).toHaveFocus();
    await userEvent.tab();
    expect(row.contains(document.activeElement)).toBe(false);
    // The keyboard user reads the ids, in the row's name.
    expect(row).toHaveAccessibleName(/issues AGH-200, AGH-201$/);
  });

  it("keeps a very long slug inside the Feature column, cut with an ellipsis, with the full slug in its title (AC-PG-6.3)", async () => {
    const slug = `very-long-${"slug-".repeat(24)}end`;
    open({ "/api/v1/features": aPage([aFeature({ slug })]) });

    const link = await screen.findByRole("link", { name: slug });
    expect(link).toHaveClass("ft-row-title");
    expect(link).toHaveAttribute("title", slug);
    expect(link.closest(".ft-row-main")).not.toBeNull();
    expect(link.closest("li")).not.toHaveAttribute("style");

    const css = cssOf("src/screens/features/features.css");
    expect(ruleOf(css, ".ft-row")).toMatch(/grid-template-columns: 16px minmax\(0, 1fr\) auto;/);
    expect(ruleOf(css, ".ft-row-main")).toMatch(/min-width: 0;/);
    const title = ruleOf(css, ".ft-row-title");
    expect(title).toMatch(/min-width: 0;/);
    expect(title).toMatch(/white-space: nowrap;/);
    expect(title).toMatch(/text-overflow: ellipsis;/);
  });

  it("narrows the list by Step and counts each step under the current search (AC-PG-16.2)", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: /^Step:/ }));
    expect(facetCount(/^Plan/)).toBe("1");
    expect(facetCount(/^Acceptance/)).toBe("1");
    expect(facetCount(/^Shipped/)).toBe("0");

    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "agh-49");
    await userEvent.click(screen.getByRole("button", { name: /^Step:/ }));
    expect(facetCount(/^Plan/)).toBe("0");
    expect(facetCount(/^Acceptance/)).toBe("1");

    await userEvent.click(screen.getByRole("checkbox", { name: /^Acceptance/ }));
    expect(router.state.location.search).toBe("?q=agh-49&phase=acceptance");
    expect(screen.getByRole("link", { name: "layered-memory" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "tracker-team-cap" })).not.toBeInTheDocument();
  });

  it("narrows the list by Repo, with counts that follow the search (AC-PG-16.2)", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: /^Repo:/ }));
    expect(facetCount(/^agent-hub/)).toBe("3");
    expect(facetCount(/^marketService/)).toBe("1");

    await userEvent.click(screen.getByRole("checkbox", { name: /^marketService/ }));
    expect(router.state.location.search).toBe("?repo=marketService");
    expect(screen.getByRole("link", { name: "broken-record" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 of 4 features");

    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "layered");
    await userEvent.click(screen.getByRole("button", { name: /^Repo:/ }));
    expect(facetCount(/^agent-hub/)).toBe("1");
    expect(facetCount(/^marketService/)).toBe("0");
  });

  it("shows the Repo filter only when the features span more than one repo (AC-PG-16.2)", async () => {
    open({
      "/api/v1/features": aPage([aFeature(), aFeature({ slug: "other", size: "spike" })]),
    });

    await screen.findByRole("link", { name: "other" });
    expect(screen.getByRole("button", { name: /^Step:/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Size:/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Repo:/ })).not.toBeInTheDocument();
  });

  it("narrows the list by Size, with counts that follow the search (AC-PG-16.2)", async () => {
    const { router } = open();

    await userEvent.click(await screen.findByRole("button", { name: /^Size:/ }));
    expect(facetCount(/^spike/)).toBe("1");
    expect(facetCount(/^bounded/)).toBe("1");
    expect(facetCount(/^architectural/)).toBe("2");

    await userEvent.click(screen.getByRole("checkbox", { name: /^bounded/ }));
    expect(router.state.location.search).toBe("?size=bounded");
    expect(screen.getByRole("link", { name: "tracker-team-cap" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "control-plane" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: /^bounded/ }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "agh-49");
    await userEvent.click(screen.getByRole("button", { name: /^Size:/ }));
    expect(facetCount(/^architectural/)).toBe("1");
    expect(facetCount(/^bounded/)).toBe("0");
  });

  it("titles a named feature with its nickname in the UI font and puts its fixed label beside it (AC-PG-28.2, AC-425.7)", async () => {
    open({
      "/api/v1/feature-names": {
        items: [{ project: "agent-hub", slug: "layered-memory", name: "Layered memory" }],
      },
    });

    const title = await screen.findByRole("link", { name: "Layered memory" });
    expect(title).toHaveClass("ft-row-title");
    expect(title).toHaveAttribute("data-named");
    expect(title.nextElementSibling).toHaveAccessibleName("Feature label layered-memory");
    expect(title.nextElementSibling).toHaveTextContent("layered-memory");
    const unnamed = screen.getByRole("link", { name: "control-plane" });
    expect(unnamed).not.toHaveAttribute("data-named");
    expect(unnamed.nextElementSibling).toHaveAccessibleName("Feature label control-plane");

    const css = cssOf("src/screens/features/features.css");
    expect(ruleOf(css, ".ft-row-title")).toMatch(/font-family: var\(--font-mono\);/);
    expect(ruleOf(css, ".ft-row-title[data-named]")).toMatch(/font-family: var\(--font-sans\);/);
  });

  describe("renaming inline (AC-PG-28.3)", () => {
    function withNames() {
      const names = [{ project: "agent-hub", slug: "layered-memory", name: "Layered memory" }];
      const saved: unknown[] = [];
      const view = open({
        "/api/v1/feature-names": () => ({ items: names }),
        // Only the emptying case saves: the API then forgets the name.
        "PUT /api/v1/feature-names": (request: Request) => {
          void request
            .clone()
            .json()
            .then((body) => saved.push(body));
          names.splice(0);
          return { project: "agent-hub", slug: "layered-memory", name: "" };
        },
      });
      return { ...view, saved };
    }

    it("shows the pencil on hover or focus and reaches it with Tab from the row (AC-PG-28.3)", async () => {
      open();

      await screen.findByRole("link", { name: "layered-memory" });
      const row = rowOf("layered-memory");
      row.focus();
      await userEvent.tab();
      expect(within(row).getByRole("button", { name: "Give layered-memory a name" })).toHaveFocus();

      const css = cssOf("src/screens/features/names.css");
      expect(ruleOf(css, ".ft-row .ft-rename")).toMatch(/opacity: 0;/);
      expect(css).toMatch(
        /\.ft-row:hover \.ft-rename,\n\.ft-row:focus-within \.ft-rename,\n\.ft-row \.ft-rename:focus-visible \{\n {2}opacity: 1;/,
      );
    });

    it("cancels the edit with Esc and saves nothing (AC-PG-28.3)", async () => {
      const { requests } = withNames();

      await screen.findByRole("link", { name: "Layered memory" });
      await userEvent.click(screen.getByRole("button", { name: "Rename layered-memory" }));
      const field = screen.getByRole("textbox", { name: "Name for layered-memory" });
      expect(field).toHaveValue("Layered memory");
      await userEvent.type(field, " changed{Escape}");

      expect(
        screen.queryByRole("textbox", { name: "Name for layered-memory" }),
      ).not.toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Layered memory" })).toBeInTheDocument();
      expect(requests.some((r) => r.method === "PUT")).toBe(false);
    });

    it("goes back to the slug when the name is emptied and saved with Enter (AC-PG-28.3)", async () => {
      const { saved } = withNames();

      await screen.findByRole("link", { name: "Layered memory" });
      await userEvent.click(screen.getByRole("button", { name: "Rename layered-memory" }));
      await userEvent.clear(screen.getByRole("textbox", { name: "Name for layered-memory" }));
      await userEvent.keyboard("{Enter}");

      const link = await screen.findByRole("link", { name: "layered-memory" });
      expect(link).not.toHaveAttribute("data-named");
      expect(screen.queryByRole("link", { name: "Layered memory" })).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Give layered-memory a name" }),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(saved).toEqual([{ project: "agent-hub", slug: "layered-memory", name: "" }]);
      });
    });
  });
});

describe("FeaturesScreen (owner status)", () => {
  const dayBefore = (days: number) =>
    new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);
  const checkout = aFeature({
    slug: "checkout",
    project: "demo",
    repos: ["demo", "demo-api", "demo-web"],
    issues: ["DEM-3"],
    last_activity_on: dayBefore(0),
  });
  const refunds = aFeature({
    slug: "refunds",
    project: "demo-shop",
    repos: ["demo-shop", "demo-api"],
    issues: ["DEM-5"],
    last_activity_on: dayBefore(2),
  });
  const search = aFeature({
    slug: "search",
    project: "demo",
    repos: ["demo"],
    issues: ["DEM-9"],
    last_activity_on: dayBefore(30),
  });
  const wishlist = aFeature({
    slug: "wishlist",
    project: "demo-shop",
    repos: ["demo-shop"],
    issues: ["DEM-11"],
    owner_status: {
      status: "paused",
      decided_at: "2026-11-02T10:00:00Z",
      note: "Waiting on the design",
    },
  });
  const coupons = aFeature({
    slug: "coupons",
    project: "demo",
    repos: ["demo"],
    issues: ["DEM-12"],
    verdict: "NO-SHIP",
    owner_status: { status: "closed", decided_at: "2026-11-03T10:00:00Z", note: null },
  });
  const demoList = [checkout, refunds, search, wishlist, coupons];
  const STATUS = "/api/v1/features/{project}/{slug}/status";
  const statusOf = (f: FeatureView) =>
    STATUS.replace("{project}", f.project).replace("{slug}", f.slug);

  function openDemo(extra: ApiRoutes = {}, path = "/features") {
    return open({ "/api/v1/features": aPage(demoList), ...extra }, true, path);
  }

  const bulkBar = () => screen.queryByRole("region", { name: "Selected features" });

  it("puts a feature with no activity for 14 days in the folded Quiet group, its last activity in days (quiet)", async () => {
    openDemo();

    const quiet = await screen.findByRole("button", { name: /^Quiet · 1$/ });
    expect(quiet).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "search" })).not.toBeInTheDocument();
    await userEvent.click(quiet);

    const row = rowOf("search");
    expect(row.querySelector(".ft-row-line")).toHaveTextContent(/^No activity for 30 days · /);
    const activity = row.querySelector(".ft-col-activity");
    expect(activity).toHaveTextContent(/^30 days ago$/);
    expect(activity).toHaveAttribute("data-quiet");
  });

  it("puts a paused feature in the folded Paused group, muted, saying when and why (paused)", async () => {
    openDemo();

    const paused = await screen.findByRole("button", { name: /^Paused · 1$/ });
    expect(paused).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(paused);

    expect(rowOf("wishlist")).toHaveAttribute("data-muted", "true");
    expect(rowOf("wishlist").querySelector(".ft-row-line")).toHaveTextContent(
      /^Paused by you on 2026-11-02 · Waiting on the design$/,
    );
  });

  it("puts a closed feature in Shipped and closed, whatever its verdict says (closed)", async () => {
    openDemo();

    await userEvent.click(await screen.findByRole("button", { name: /^Shipped and closed · 1$/ }));

    expect(rowOf("coupons")).not.toHaveAttribute("data-tone");
    expect(rowOf("coupons").querySelector(".ft-row-line")).toHaveTextContent(
      /^Closed without shipping by you on 2026-11-03$/,
    );
    expect(screen.queryByRole("button", { name: /^Needs you · [1-9]/ })).not.toBeInTheDocument();
  });

  it("shows the Project and Last activity columns when the features span several projects (columns)", async () => {
    openDemo();

    await screen.findByRole("link", { name: "checkout" });
    const card = rowOf("checkout").closest(".ft-card");
    if (!(card instanceof HTMLElement)) throw new Error("no card");
    expect(card).toHaveAttribute("data-select");
    expect(card).toHaveAttribute("data-project");
    expect(card.querySelector(".ft-cols-meta")).toHaveTextContent(
      /^ProjectStage.*Criteria met.*Last activity/,
    );
    expect(rowOf("checkout").querySelector(".ft-col-project")).toHaveTextContent(/^demo$/);
    expect(rowOf("refunds").querySelector(".ft-col-project")).toHaveTextContent(/^demo-shop$/);
    expect(rowOf("checkout").querySelector(".ft-col-activity")).toHaveTextContent(/^today$/);
    expect(rowOf("refunds").querySelector(".ft-col-activity")).toHaveTextContent(/^2 days ago$/);
  });

  it("leaves the Project column and the Project filter out when every feature is in one project (columns)", async () => {
    open({ "/api/v1/features": aPage([checkout, search]) });

    await screen.findByRole("link", { name: "checkout" });
    const card = rowOf("checkout").closest(".ft-card");
    expect(card).toHaveAttribute("data-select");
    expect(card).not.toHaveAttribute("data-project");
    expect(rowOf("checkout").querySelector(".ft-col-project")).toBeNull();
    expect(card?.querySelector(".ft-cols-meta")).not.toHaveTextContent("Project");
    expect(screen.queryByRole("button", { name: /^Project:/ })).not.toBeInTheDocument();
  });

  it("keeps the feature label and the other repos as chips on the row (row)", async () => {
    openDemo({
      "/api/v1/feature-names": { items: [{ project: "demo", slug: "checkout", name: "Checkout" }] },
    });

    const row = rowOf((await screen.findByRole("link", { name: "Checkout" })).textContent);
    expect(within(row).getByLabelText("Feature label checkout")).toBeInTheDocument();
    expect([...row.querySelectorAll(".ft-row-tag")].map((t) => t.textContent)).toEqual([
      "demo-api",
      "demo-web",
    ]);
    expect(within(rowOf("refunds")).getByLabelText("Feature label refunds")).toBeInTheDocument();
    expect([...rowOf("refunds").querySelectorAll(".ft-row-tag")].map((t) => t.textContent)).toEqual(
      ["demo-api"],
    );
  });

  it("filters by Project through the URL, with counts that follow the search (filters)", async () => {
    const { router } = openDemo();

    await userEvent.click(await screen.findByRole("button", { name: /^Project:/ }));
    expect(facetCount(/^demo-shop/)).toBe("2");
    expect(facetCount(/^demo\d/)).toBe("3");

    await userEvent.click(screen.getByRole("checkbox", { name: /^demo-shop/ }));
    expect(router.state.location.search).toBe("?project=demo-shop");
    expect(screen.getByRole("link", { name: "refunds" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "checkout" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 of 5 features");

    await userEvent.type(screen.getByRole("searchbox", { name: "Find features" }), "dem-3");
    await userEvent.click(screen.getByRole("button", { name: /^Project:/ }));
    expect(facetCount(/^demo\d/)).toBe("1");
    expect(facetCount(/^demo-shop/)).toBe("0");
  });

  it("selects a row with its checkbox, without opening it, and offers the decisions in a bulk bar (select)", async () => {
    const { router } = openDemo();

    await userEvent.click(await screen.findByRole("checkbox", { name: "Select checkout" }));

    expect(router.state.location.pathname).toBe("/features");
    expect(rowOf("checkout")).toHaveAttribute("data-selected", "true");
    const bar = bulkBar();
    if (!bar) throw new Error("no bulk bar");
    expect(bar).toHaveTextContent("1 selected");
    expect(
      within(bar)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Mark shipped", "Close without shipping", "Pause", "Reopen", "Clear"]);
    await userEvent.click(within(bar).getByRole("button", { name: "Clear" }));
    expect(bulkBar()).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select checkout" })).not.toBeChecked();
  });

  it("selects and unselects the focused row with x (select)", async () => {
    openDemo();

    await screen.findByRole("link", { name: "checkout" });
    rowOf("checkout").focus();
    await userEvent.keyboard("x");
    expect(screen.getByRole("checkbox", { name: "Select checkout" })).toBeChecked();
    expect(bulkBar()).toHaveTextContent("1 selected");
    await userEvent.keyboard("x");
    expect(screen.getByRole("checkbox", { name: "Select checkout" })).not.toBeChecked();
    expect(bulkBar()).not.toBeInTheDocument();
  });

  it("selects every row of a group from its column head (select)", async () => {
    openDemo();

    await screen.findByRole("link", { name: "checkout" });
    await userEvent.click(
      within(groupOf(/^Active · 2$/)).getByRole("checkbox", {
        name: "Select every feature in this group",
      }),
    );

    expect(bulkBar()).toHaveTextContent("2 selected");
    expect(screen.getByRole("checkbox", { name: "Select checkout" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select refunds" })).toBeChecked();
  });

  it("marks each selected feature shipped with one POST per feature and a note, then clears the selection (bulk)", async () => {
    const { requests } = openDemo({
      [`POST ${statusOf(checkout)}`]: {},
      [`POST ${statusOf(refunds)}`]: {},
    });

    await userEvent.click(await screen.findByRole("checkbox", { name: "Select checkout" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select refunds" }));
    const bar = bulkBar();
    if (!bar) throw new Error("no bulk bar");
    await userEvent.click(within(bar).getByRole("button", { name: "Mark shipped" }));

    const dialog = screen.getByRole("dialog", { name: "Mark shipped 2 features?" });
    expect(dialog).toHaveTextContent("checkoutdemo");
    expect(dialog).toHaveTextContent("refundsdemo-shop");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Why (optional)" }),
      "Released to demo-shop",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Mark shipped 2" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: /^Mark shipped/ })).not.toBeInTheDocument();
    });
    const posts = requests.filter((r) => r.method === "POST");
    expect(posts.map((r) => new URL(r.url).pathname)).toEqual([
      statusOf(checkout),
      statusOf(refunds),
    ]);
    expect(await Promise.all(posts.map((r) => r.json()))).toEqual([
      { status: "shipped", note: "Released to demo-shop" },
      { status: "shipped", note: "Released to demo-shop" },
    ]);
    expect(bulkBar()).not.toBeInTheDocument();
  });

  it("says which feature the server refused and keeps only that one selected (bulk)", async () => {
    openDemo({
      [`POST ${statusOf(checkout)}`]: {},
      [`POST ${statusOf(refunds)}`]: aProblem({
        status: 409,
        title: "Conflict",
        detail: "status.md of refunds is not readable",
      }),
    });

    await userEvent.click(await screen.findByRole("checkbox", { name: "Select checkout" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select refunds" }));
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    const dialog = screen.getByRole("dialog", { name: "Pause 2 features?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Pause 2" }));

    expect(await within(dialog).findByText("status.md of refunds is not readable")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "Pause 2" })).not.toBeInTheDocument();
    expect(bulkBar()).toHaveTextContent("1 selected");
    expect(screen.getByRole("checkbox", { name: "Select refunds" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select checkout" })).not.toBeChecked();
  });

  it("locks the decision, saying why, and sends nothing without the launch cookie (bulk)", async () => {
    noteLaunchCookie("missing");
    const { requests } = openDemo({
      "/api/v1/screens/shell": aShellView({ launch_cookie: "missing" }),
    });

    await userEvent.click(await screen.findByRole("checkbox", { name: "Select checkout" }));
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));

    const dialog = screen.getByRole("dialog", { name: "Pause checkout?" });
    const confirm = within(dialog).getByRole("button", { name: "Pause" });
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveAttribute("title", expect.stringMatching(/hub web printed/));
    expect(dialog).toHaveTextContent(
      /Changes are locked in this browser\. Open the link hub web printed/,
    );
    await userEvent.click(confirm);
    expect(requests.some((r) => r.method === "POST")).toBe(false);
  });
});

describe("FeaturesScreen requests", () => {
  // 30 features with issues; a server that would answer each feature's tickets.
  const thirty = (shape: Partial<FeatureView>): FeatureView[] =>
    Array.from({ length: 30 }, (_, i) =>
      aFeature({
        slug: `feature-${String(i).padStart(2, "0")}`,
        issues: [`AGH-${String(300 + i)}`],
        ...shape,
      }),
    );
  const notConnected = thirty({
    tickets_source: "plan",
    golden_path: aGoldenPath({
      steps: aGoldenPath().steps.map((step) =>
        step.name === "build"
          ? aGoldenStep({
              state: "unknown",
              meta: null,
              reason: "Linear not connected",
              progress: null,
            })
          : step,
      ),
    }),
  });
  const shippedFromLinear = thirty({
    tickets_source: "linear",
    phase: "shipped",
    golden_path: aGoldenPath({
      phase: "shipped",
      steps: aGoldenPath().steps.map((step) => ({ ...step, state: "done", reason: null })),
    }),
  });
  const linearNotice = "This list doesn't load ticket status from Linear";
  const REFRESHED = ["/api/v1/features", "/api/v1/live-sessions", "/api/v1/feature-names"];

  function serving(list: FeatureView[]): ApiRoutes {
    const served: ApiRoutes = {
      "/api/v1/features": aPage(list),
      "/api/v1/live-sessions": aPage([]),
      "/api/v1/feature-names": { items: [] },
    };
    for (const f of list) {
      served[`/api/v1/features/${f.project}/${f.slug}/tickets`] = aFeatureTickets({
        project: f.project,
        slug: f.slug,
      });
    }
    return served;
  }

  const pathsOf = (requests: Request[]) => requests.map((r) => new URL(r.url).pathname);

  it.each<[string, FeatureView[], RegExp, number]>([
    ["not connected", notConnected, /^Active · 30$/, 1],
    ["connected", shippedFromLinear, /^Shipped and closed · 30$/, 0],
  ])(
    "AC-30 requests /features once and never a feature's tickets, Linear %s",
    async (_linear, list, group, notices) => {
      const { requests, queryClient } = open(serving(list));

      await screen.findByRole("button", { name: group });
      await waitFor(() => {
        expect(queryClient.isFetching()).toBe(0);
      });
      // The list is the case named: the screen says Linear is missing only when it is.
      expect(
        screen.queryAllByRole("note").filter((note) => note.textContent.includes(linearNotice)),
      ).toHaveLength(notices);
      const paths = pathsOf(requests);
      expect(paths.filter((p) => p.endsWith("/tickets"))).toEqual([]);
      expect(paths.filter((p) => p === "/api/v1/features")).toHaveLength(1);
    },
  );

  it("AC-32 sends only its refresh requests while open for 60 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { requests } = open(serving(notConnected));
      await screen.findByRole("button", { name: /^Active · 30$/ });
      expect(screen.getByRole("note")).toHaveTextContent(linearNotice);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      const paths = pathsOf(requests);
      expect(paths.filter((p) => !REFRESHED.includes(p))).toEqual([]);
      // The first read, then one every 30 s.
      expect(paths.filter((p) => p === "/api/v1/features")).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
