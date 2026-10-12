import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aFeatureDetail,
  aFeatureRecord,
  aProblem,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { FeatureDetailScreen } from "./index";

const API = "/api/v1/features/agent-hub/layered-memory";
const NOTE = "/api/v1/projects/agent-hub/brain/note";

/** Answers each record with a note naming its path and linking the brain index. */
function records(request: Request) {
  const path = new URL(request.url).searchParams.get("path") ?? "";
  return aBrainNote({
    path,
    frontmatter: { status: "approved" },
    markdown: `# Record ${path}\n\n## Open questions\n\nSee [the index](../../index.md).\n`,
  });
}
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
  records: (["spec", "research", "plan", "eval", "issues"] as const).map((name) =>
    aFeatureRecord({
      name,
      path: `features/layered-memory/${name}.md`,
      present: name !== "research",
    }),
  ),
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
  return renderWithApi(ui, { routes: { [API]: detail, [NOTE]: records, ...extra }, path, route });
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
    expect(callout.closest('[role="status"]')).toHaveTextContent(
      "memory loads. Recorded in features.json",
    );
  });

  it("shows nine AC rows, then all of them on Show all", async () => {
    open();

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      9,
    );
    await userEvent.click(within(table).getByRole("button", { name: /Show all 13/ }));
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      13,
    );
  });

  it("filters the ACs to owner steps and marks them", async () => {
    open();

    await userEvent.click(await screen.findByRole("button", { name: "Owner step 1" }));

    const table = screen.getByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      1,
    );
    expect(within(table).getByText("owner")).toBeInTheDocument();
    expect(within(table).getByText("manual · see eval.md")).toBeInTheDocument();
  });

  it("opens the first owner step's row by default", async () => {
    open();

    expect(await screen.findByRole("button", { name: "Collapse AC-48.13" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
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

  describe("records", () => {
    it("has the Spec, Research, Plan, Eval and Criteria tabs (records)", async () => {
      open();

      const tabs = within(await screen.findByRole("tablist", { name: "Feature record" }));
      expect(tabs.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Spec",
        "Research",
        "Plan",
        "Eval",
        "Criteria13",
        "Issues2",
      ]);
      expect(tabs.getByRole("tab", { name: /Criteria/ })).toHaveAttribute("aria-selected", "true");
    });

    it("reads the plan from the brain and renders it (records)", async () => {
      const { requests } = open();

      await userEvent.click(await screen.findByRole("tab", { name: "Plan" }));

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Record features/layered-memory/plan.md",
        }),
      ).toBeInTheDocument();
      const asked = requests.find((r) => new URL(r.url).pathname === NOTE);
      expect(new URL(asked?.url ?? "").searchParams.get("path")).toBe(
        "features/layered-memory/plan.md",
      );
      expect(screen.getByRole("list", { name: "Frontmatter" })).toHaveTextContent(
        "status: approved",
      );
      expect(screen.getByRole("link", { name: "Open in Brain" })).toHaveAttribute(
        "href",
        "/projects/agent-hub/brain/features/layered-memory/plan.md",
      );
    });

    it("says No plan.md yet when the plan record is absent (records)", async () => {
      open({
        [API]: aFeatureDetail({
          slug: "layered-memory",
          records: [aFeatureRecord({ name: "plan", present: false })],
        }),
      });

      await userEvent.click(await screen.findByRole("tab", { name: "Plan" }));

      expect(screen.getByText("No plan.md yet.")).toBeInTheDocument();
    });

    it("says a missing research record is missing without asking the API (records)", async () => {
      const { requests } = open();

      await userEvent.click(await screen.findByRole("tab", { name: "Research" }));

      expect(screen.getByText("No research.md yet.")).toBeInTheDocument();
      expect(requests.some((r) => new URL(r.url).pathname === NOTE)).toBe(false);
    });

    it("opens a brain link of a record inside the app (records)", async () => {
      const { router } = open({}, "/features/agent-hub/layered-memory?doc=spec");

      await userEvent.click(await screen.findByRole("link", { name: "the index" }));

      expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/index.md");
    });

    it("shows the verdict above the eval record on the Eval tab (records)", async () => {
      open();

      await userEvent.click(await screen.findByRole("tab", { name: "Eval" }));

      expect(screen.getByText("Verdict: **SHIP-WITH-OWNER-STEPS**")).toBeInTheDocument();
      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Record features/layered-memory/eval.md",
        }),
      ).toBeInTheDocument();
    });

    it("expands an AC into its verification command and evidence (records)", async () => {
      const write = vi.fn(() => Promise.resolve());
      Object.defineProperty(navigator, "clipboard", {
        value: { writeText: write },
        configurable: true,
      });
      open();

      const table = await screen.findByRole("table", { name: "Acceptance criteria" });
      await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.2" }));

      const details = within(table).getByText("Verification").closest("dl");
      expect(details).toHaveTextContent("uv run pytest -k case_2");
      expect(details).toHaveTextContent("Evidencetest run 2");
      await userEvent.click(
        within(table).getByRole("button", { name: "Copy the verification of AC-48.2" }),
      );
      expect(write).toHaveBeenCalledWith("uv run pytest -k case_2");
    });

    it("marks a manual AC's verification as an owner step (records)", async () => {
      open();

      const details = (await screen.findByText("Verification")).closest("dl");
      expect(details).toHaveTextContent("Manual owner step.");
      expect(details).toHaveTextContent("eval.md §Owner steps");
    });

    it("says when an AC has no evidence or verification yet (records)", async () => {
      open({
        [API]: aFeatureDetail({
          slug: "layered-memory",
          acs: { owner_steps: 0, passing: 0, total: 1 },
          ac_rows: [
            {
              id: "AC-48.1",
              description: "Plain",
              repo: null,
              passes: false,
              manual: false,
              evidence: null,
              command: null,
            },
          ],
        }),
      });

      await userEvent.click(await screen.findByRole("button", { name: "Expand AC-48.1" }));

      expect(screen.getByText("No verification recorded.")).toBeInTheDocument();
      expect(screen.getByText("No evidence recorded yet.")).toBeInTheDocument();
    });

    it("has no serious a11y violations on a record tab (a11y)", async () => {
      const { container } = open({}, "/features/agent-hub/layered-memory?doc=plan");
      await screen.findByRole("heading", { level: 2, name: "Open questions" });

      expect(await seriousViolations(container)).toEqual([]);
    });
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
