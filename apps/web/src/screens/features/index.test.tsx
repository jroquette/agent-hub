import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import { aFeature, aPage, aProblem, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { FeaturesScreen } from "./index";

const features = [
  aFeature({
    slug: "tracker-team-cap",
    phase: "plan",
    files: ["spec.md", "plan.md"],
    acs: { owner_steps: 0, passing: 0, total: 9 },
    size: "bounded",
    issues: ["AGH-112"],
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
      "4 features · 1 evaluated · 3 in progress",
    );
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

  it("shows the golden path phase and '--' without a verdict", async () => {
    open();

    await screen.findByRole("link", { name: "tracker-team-cap" });
    const row = rowOf("tracker-team-cap");
    expect(within(row).getByRole("img", { name: "Golden path: Plan" })).toBeInTheDocument();
    expect(within(row).getByText("--")).toBeInTheDocument();
    expect(row.querySelector('[data-state="skipped"]')).not.toBeNull();
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

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByRole("link", { name: "layered-memory" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
