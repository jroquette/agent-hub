import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aFeatureDetail,
  aFeatureRecord,
  aFeatureTickets,
  aGoldenPath,
  aGoldenStep,
  aProblem,
  aTicketRow,
  anEvalRecord,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { FeatureDetailScreen } from "./index";

const API = "/api/v1/features/agent-hub/layered-memory";
const TICKETS = `${API}/tickets`;
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
  golden_path: aGoldenPath({
    phase: "evaluate",
    steps: [
      aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "research", state: "skipped", meta: null, progress: null }),
      aGoldenStep({ name: "plan", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "tickets", state: "done", meta: "2 of 2 created", progress: null }),
      aGoldenStep({ name: "implement", state: "done", meta: "2/2 tickets", progress: null }),
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
        meta: "partial: covers 3 of 13 ACs",
        reason: "Review is not done",
        progress: { done: 3, total: 13 },
      }),
      aGoldenStep({ name: "shipped", state: "done", meta: null, reason: null, progress: null }),
    ],
  }),
  evals: [
    anEvalRecord({
      delivery: "agh-48",
      path: "features/layered-memory/evals/agh-48.md",
      tickets: ["AGH-48"],
    }),
    anEvalRecord({
      delivery: "agh-49",
      path: "features/layered-memory/evals/agh-49.md",
      verdict: "NO-SHIP",
      tickets: ["AGH-49"],
    }),
  ],
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

  it("draws the server's golden path with partial, blocked and unknown as text (golden)", async () => {
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
      "partial",
      "blocked",
    ]);
    expect(steps[5]).toHaveTextContent("Unknown");
    expect(steps[5]).toHaveTextContent("Linear not connected");
    expect(steps[6]).toHaveTextContent("Partial");
    expect(steps[6]).toHaveTextContent("partial: covers 3 of 13 ACs");
    expect(steps[7]).toHaveTextContent("Blocked");
    expect(steps[7]).toHaveTextContent("Review is not done");
  });

  it("calls out the owner steps left", async () => {
    open();

    const callout = await screen.findByText("1 owner step left: AC-48.13");
    expect(callout.closest('[role="status"]')).toHaveTextContent(
      "memory loads. Recorded in features.json",
    );
  });

  it("shows every AC row at once, with no Show all fold", async () => {
    open();

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      13,
    );
    expect(within(table).queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("filters the ACs to owner steps and marks them", async () => {
    open();

    await userEvent.click(await screen.findByRole("button", { name: "Owner step 1" }));

    const table = screen.getByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      1,
    );
    expect(within(table).getAllByText("Owner step").length).toBeGreaterThan(0);
    expect(within(table).getByText(/Manual owner step/)).toBeInTheDocument();
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
        "Acceptance criteria13",
        "Tickets2",
      ]);
      expect(tabs.getByRole("tab", { name: /Acceptance criteria/ })).toHaveAttribute(
        "aria-selected",
        "true",
      );
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

    it("lists every delivery's eval on the Eval tab (golden)", async () => {
      open();

      await userEvent.click(await screen.findByRole("tab", { name: "Eval" }));

      const table = screen.getByRole("table", { name: "Evals" });
      expect(table).toHaveTextContent("agh-48");
      expect(table).toHaveTextContent("agh-49");
      expect(table).toHaveTextContent("NO-SHIP");
      expect(
        within(table).getByRole("link", { name: "agh-49.md, the eval of agh-49" }),
      ).toHaveAttribute(
        "href",
        "/projects/agent-hub/brain/features/layered-memory/evals/agh-49.md",
      );
    });

    it("reads the eval ?eval= names in place and keeps a new choice in the URL (AC-269.4)", async () => {
      open({}, "/features/agent-hub/layered-memory?doc=eval&eval=agh-48");

      expect(await screen.findByRole("article", { name: "Eval agh-48" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^agh-49,/ }));
      expect(await screen.findByRole("article", { name: "Eval agh-49" })).toBeInTheDocument();
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

      const check = within(table).getByRole("region", { name: "Check it yourself" });
      expect(check).toHaveTextContent("uv run pytest -k case_2");
      const proven = within(table).getByRole("region", { name: "How it was proven" });
      expect(proven).toHaveTextContent("test run 2");
      await userEvent.click(within(check).getByRole("button", { name: "Copy command" }));
      expect(write).toHaveBeenCalledWith("uv run pytest -k case_2");
    });

    it("marks a manual AC's verification as an owner step (records)", async () => {
      open();

      const check = await screen.findByRole("region", { name: "Check it yourself" });
      expect(check).toHaveTextContent("Manual owner step:");
      const proven = screen.getByRole("region", { name: "How it was proven" });
      expect(proven).toHaveTextContent("eval.md §Owner steps");
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

  describe("tickets", () => {
    const tickets = aFeatureTickets({
      slug: "layered-memory",
      tickets: [
        aTicketRow({
          ref: "AGH-48",
          id: "AGH-48",
          key: "T1",
          title: "Load the memory layers",
          url: "https://linear.app/demo/issue/AGH-48",
          blocked_by: [],
          blocks: ["AGH-49"],
          readiness: "can_start",
        }),
        aTicketRow({
          ref: "AGH-49",
          id: "AGH-49",
          key: "T2",
          title: "Show the layers",
          url: "https://evil.example/AGH-49",
          blocked_by: [{ ref: "AGH-48", source: "plan" }],
          blocks: [],
          readiness: "waiting",
          waiting_on: ["AGH-48"],
        }),
      ],
      planning: {
        layers: [["AGH-48"], ["AGH-49"]],
        can_start: ["AGH-48"],
        order: ["AGH-48", "AGH-49"],
        waiting: ["AGH-49"],
        cycles: [],
        external_blockers: [],
        critical_path: ["AGH-48", "AGH-49"],
        warnings: [],
      },
    });
    const asked = (requests: Request[], path: string) =>
      requests.filter((r) => new URL(r.url).pathname === path).length;

    it("does not ask the tickets route before the Tickets tab opens (tickets)", async () => {
      const { requests } = open({ [TICKETS]: tickets });

      await screen.findByRole("table", { name: "Acceptance criteria" });

      expect(asked(requests, TICKETS)).toBe(0);
    });

    it("shows the tickets and the planning view on the Tickets tab (tickets)", async () => {
      const { requests, router } = open({ [TICKETS]: tickets });

      await userEvent.click(await screen.findByRole("tab", { name: /Tickets/ }));

      const table = await screen.findByRole("table", { name: "Tickets" });
      expect(table).toHaveTextContent("Load the memory layers");
      expect(within(table).getByText("Can start now")).toBeInTheDocument();
      expect(within(table).getByText(/Waiting on/)).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");
      expect(router.state.location.search).toBe("?doc=tickets");
      expect(asked(requests, TICKETS)).toBe(1);
    });

    it("opens the Tickets tab from an old ?doc=issues link (tickets)", async () => {
      open({ [TICKETS]: tickets }, "/features/agent-hub/layered-memory?doc=issues");

      expect(await screen.findByRole("table", { name: "Tickets" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");
    });

    it("names the header chips with ticket titles once the tickets load, linking to Linear (tickets)", async () => {
      open({ [TICKETS]: tickets }, "/features/agent-hub/layered-memory?doc=tickets");

      await screen.findByRole("table", { name: "Tickets" });

      const header = screen.getByRole("group", { name: "Tickets of this feature" });
      expect(header).toHaveTextContent("AGH-48Load the memory layers");
      expect(header).toHaveTextContent("AGH-49Show the layers");
      expect(within(header).getByRole("link", { name: /AGH-48/ })).toHaveAttribute(
        "href",
        "https://linear.app/demo/issue/AGH-48",
      );
      expect(within(header).queryByRole("link", { name: /AGH-49/ })).toBeNull();
    });

    it("shows the ticket ids in the header until the tickets load (tickets)", async () => {
      open();

      await screen.findByRole("heading", { level: 1, name: "layered-memory" });

      const header = screen.getByRole("group", { name: "Tickets of this feature" });
      expect(header).toHaveTextContent("AGH-48AGH-49");
      expect(within(header).queryByRole("link")).toBeNull();
    });

    it("refetches the tickets route on Refresh (notice)", async () => {
      const { requests } = open(
        { [TICKETS]: { ...tickets, source: "plan", notice: "Linear not connected." } },
        "/features/agent-hub/layered-memory?doc=tickets",
      );

      expect(await screen.findByText("Linear not connected.")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

      await waitFor(() => {
        expect(asked(requests, TICKETS)).toBe(2);
      });
    });

    it("refetches the golden path after the tickets load (notice)", async () => {
      let reads = 0;
      const loaded = aGoldenPath({
        phase: "evaluate",
        steps: detail.golden_path.steps.map((step) =>
          step.name === "review"
            ? { ...step, state: "done", reason: null, meta: "2/2 reviewed" }
            : step,
        ),
      });
      const { requests } = open(
        {
          [API]: () => {
            reads += 1;
            return reads === 1 ? detail : { ...detail, golden_path: loaded };
          },
          [TICKETS]: tickets,
        },
        "/features/agent-hub/layered-memory?doc=tickets",
      );

      await screen.findByRole("table", { name: "Tickets" });

      await waitFor(() => {
        const path = screen.getByRole("list", { name: "Golden path" });
        expect(within(path).getAllByRole("listitem")[5]).toHaveAttribute("data-state", "done");
      });
      expect(asked(requests, API)).toBe(2);
    });

    it("shows a skeleton while the tickets load (states)", async () => {
      const { container } = open(
        { [TICKETS]: "pending" },
        "/features/agent-hub/layered-memory?doc=tickets",
      );

      await screen.findByRole("tab", { name: /Tickets/ });
      await waitFor(() => {
        expect(container.querySelector('[aria-busy="true"] .ah-skel')).not.toBeNull();
      });
    });

    it("shows the tickets problem with a retry that asks again (states)", async () => {
      const { requests } = open(
        { [TICKETS]: aProblem({ status: 400, title: "Bad slug", detail: "Too long." }) },
        "/features/agent-hub/layered-memory?doc=tickets",
      );

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Bad slug");
      await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));

      await waitFor(() => {
        expect(asked(requests, TICKETS)).toBe(2);
      });
    });

    it("has no serious a11y violations on the Tickets tab (a11y)", async () => {
      const { container } = open(
        { [TICKETS]: tickets },
        "/features/agent-hub/layered-memory?doc=tickets",
      );
      await screen.findByRole("table", { name: "Tickets" });

      expect(await seriousViolations(container)).toEqual([]);
    });

    it("has no serious a11y violations on the Eval tab (a11y)", async () => {
      const { container } = open({}, "/features/agent-hub/layered-memory?doc=eval");
      await screen.findByRole("table", { name: "Evals" });

      expect(await seriousViolations(container)).toEqual([]);
    });
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
