import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import { aFeatureDetail, aProblem, renderWithApi, type ApiRoutes } from "../../testing/builders";
import { FeatureDetailScreen } from "./index";

const API = "/api/v1/features/agent-hub/layered-memory";
const route = "features/:project/:slug";

const rows = Array.from({ length: 12 }, (_, i) => ({
  id: `AC-48.${String(i + 1)}`,
  description: `Given case ${String(i + 1)}, when it runs, then it passes`,
  repo: "agent-hub",
  passes: i < 10,
  manual: false,
  evidence: i < 10 ? `test run ${String(i + 1)}` : null,
  command: `uv run pytest -k case_${String(i + 1)}`,
}));
rows.push({
  id: "AC-48.13",
  description: "Given the feature is merged, when the owner opens a session, then memory loads",
  repo: "agent-hub",
  passes: false,
  manual: true,
  evidence: "eval.md §Owner steps",
  command: "manual: open a session in the hub",
});

const detail = aFeatureDetail({
  slug: "layered-memory",
  phase: "evaluate",
  files: ["spec.md", "plan.md", "issues.md", "features.json", "eval.md"],
  verdict: "SHIP-WITH-OWNER-STEPS",
  verdict_line: "Verdict: **SHIP-WITH-OWNER-STEPS**",
  issues: ["AGH-48", "AGH-49"],
  acs: { owner_steps: 1, passing: 10, total: 13 },
  ac_rows: rows,
});

function open(
  extra: ApiRoutes = {},
  path = "/features/agent-hub/layered-memory",
  connected = true,
) {
  const ui = connected ? (
    <GlobalStreamProvider project={null}>
      <FeatureDetailScreen />
    </GlobalStreamProvider>
  ) : (
    <FeatureDetailScreen />
  );
  return renderWithApi(ui, { routes: { [API]: detail, ...extra }, path, route });
}

describe("FeatureDetailScreen", () => {
  it("shows the header with verdict, issues and the AC bar", async () => {
    open();

    expect(
      await screen.findByRole("heading", { level: 1, name: "layered-memory" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("SHIP-WITH-OWNER-STEPS").length).toBeGreaterThan(0);
    expect(screen.getByText("AGH-49")).toBeInTheDocument();
    expect(screen.getByText("11/13").parentElement).toHaveTextContent("11/13 · 1 owner step");
  });

  it("derives the golden path from the record files", async () => {
    open();

    const path = await screen.findByRole("list", { name: "Golden path" });
    const steps = within(path).getAllByRole("listitem");
    expect(steps.map((s) => s.dataset.state)).toEqual([
      "done",
      "skipped",
      "done",
      "done",
      "done",
      "unknown",
      "done",
      "unknown",
    ]);
    expect(steps[7]).toHaveTextContent("GitHub not connected");
  });

  it("calls out the owner steps left", async () => {
    open();

    const callout = await screen.findByText("1 owner step left: AC-48.13");
    expect(callout.closest('[role="status"]')).toHaveTextContent("memory loads");
  });

  it("shows nine AC rows, then all of them on Show all", async () => {
    open();

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^Expand AC-/ })).toHaveLength(9);
    await userEvent.click(within(table).getByRole("button", { name: /Show all 13/ }));
    expect(within(table).getAllByRole("button", { name: /^Expand AC-/ })).toHaveLength(13);
  });

  it("filters the ACs to owner steps and marks them", async () => {
    open();

    await userEvent.click(await screen.findByRole("button", { name: "Owner step 1" }));

    const table = screen.getByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^Expand AC-/ })).toHaveLength(1);
    expect(within(table).getByText("owner")).toBeInTheDocument();
    expect(within(table).getByText("manual · see eval.md")).toBeInTheDocument();
  });

  it("expands an AC into Given / When / Then when asked by ?ac=", async () => {
    open({}, "/features/agent-hub/layered-memory?ac=AC-48.12");

    const term = await screen.findByText("Given");
    const list = term.closest("dl");
    expect(list).toHaveTextContent("Givencase 12Whenit runsThenit passes");
  });

  it("copies every non-manual command, each under its AC id", async () => {
    const write = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: write },
      configurable: true,
    });
    open();

    await userEvent.click(await screen.findByRole("button", { name: "Copy all commands" }));

    const copied = String((write.mock.calls[0] as unknown[] | undefined)?.[0]);
    expect(copied.split("\n").slice(0, 2)).toEqual(["# AC-48.1", "uv run pytest -k case_1"]);
    expect(copied).not.toContain("manual");
  });

  it("shows the verdict line on the Evaluation tab and a missing document as missing", async () => {
    open();

    await userEvent.click(await screen.findByRole("tab", { name: "Evaluation" }));
    expect(screen.getByText("Verdict: **SHIP-WITH-OWNER-STEPS**")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Research" }));
    expect(screen.getByText("No research.md for this feature.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Spec" }));
    expect(screen.getByText("brain/features/layered-memory/spec.md")).toBeInTheDocument();
  });

  it("lists the issues on the Issues tab", async () => {
    open();

    await userEvent.click(await screen.findByRole("tab", { name: /Issues/ }));
    expect(screen.getByRole("table", { name: "Issues" })).toHaveTextContent("AGH-48");
  });

  it("shows the parse problem in the AC tab only", async () => {
    open(
      {
        [API]: aFeatureDetail({
          acs: null,
          ac_rows: [],
          problem: "features.json could not be parsed (line 38: trailing comma)",
        }),
      },
      "/features/agent-hub/layered-memory",
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("features.json could not be parsed");
    expect(screen.getByRole("tablist")).toBeInTheDocument();
  });

  it("explains a feature without features.json", async () => {
    open({ [API]: aFeatureDetail({ acs: null, ac_rows: [] }) });

    expect(await screen.findByText("No features.json yet.")).toBeInTheDocument();
  });

  it("shows the 404 page with the feature line when it does not exist", async () => {
    open({
      [API]: aProblem({ status: 404, title: "Not found", detail: "No feature agent-hub/x" }),
    });

    expect(await screen.findByText("No feature layered-memory in agent-hub.")).toBeInTheDocument();
  });

  describe("states", () => {
    it("shows a skeleton while the record loads", async () => {
      const { container } = open({ [API]: "pending" });

      await waitFor(() => {
        expect(container.querySelector(".ah-skel")).not.toBeNull();
      });
    });

    it("shows the problem with Try again when the record cannot be read", async () => {
      open({ [API]: aProblem({ status: 503, title: "Hub not readable", detail: "Gone." }) });

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Hub not readable");
      expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("shows the as-of stamp when the collector is offline", async () => {
      open({}, "/features/agent-hub/layered-memory", false);

      await screen.findByRole("heading", { level: 1, name: "layered-memory" });
      expect(screen.getByText(/Stale · as of/)).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = open();
    await screen.findByRole("table", { name: "Acceptance criteria" });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
