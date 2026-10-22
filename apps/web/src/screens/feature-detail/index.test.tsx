import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GlobalStreamProvider } from "../../shell/GlobalStream";
import { fmtDateTime } from "../../lib/format";
import { seriousViolations } from "../../testing/axe";
import {
  aBrainNote,
  aBrainTree,
  aCapabilities,
  aWorkdir,
  anAgentSession,
  anId,
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
import { FeatureDetailScreen, ticketIds } from "./index";
import { FEATURE_REFRESH_MS, TICKETS_REFRESH_MS } from "./queries";

const API = "/api/v1/features/agent-hub/layered-memory";
const TICKETS = `${API}/tickets`;
const NOTE = "/api/v1/projects/agent-hub/brain/note";

const RECORD_HASH = "a".repeat(64);

/** A record's human summary, written from the record version `source`. */
function summaryNote(path: string, source = RECORD_HASH) {
  return aBrainNote({
    path,
    frontmatter: { type: "summary", source_sha256: source, written_at: "2026-10-16" },
    markdown:
      "# Layered memory, in short\n\n**Bottom line:** it ships in phase 1.\n\n## Open questions\n\n" +
      "- Who owns the cache? ([Open questions](../plan.md#open-questions))\n",
  });
}

/** Answers each record with a note naming its path and linking the brain index, and its summary. */
function records(request: Request) {
  const path = new URL(request.url).searchParams.get("path") ?? "";
  if (path.includes("/summaries/")) return summaryNote(path);
  return aBrainNote({
    path,
    sha256: RECORD_HASH,
    frontmatter: { status: "approved" },
    markdown: `# Record ${path}\n\n## Open questions\n\nSee [the index](../../index.md).\n`,
  });
}

/** `records`, with the summaries answered by `summary` instead. */
function recordsWithSummary(summary: (path: string) => unknown) {
  return (request: Request) => {
    const path = new URL(request.url).searchParams.get("path") ?? "";
    return path.includes("/summaries/") ? summary(path) : records(request);
  };
}
const route = "features/:project/:slug";

/** Matches the one element whose whole text is the plan's version line. */
function versionLine(text: string) {
  return (_: string, element: Element | null) =>
    element?.tagName === "P" && element.textContent === text;
}

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
  phase: "acceptance",
  files: ["spec.md", "plan.md", "issues.md", "features.json", "eval.md"],
  verdict: "SHIP-WITH-OWNER-STEPS",
  verdict_line: "Verdict: **SHIP-WITH-OWNER-STEPS**",
  issues: ["AGH-48", "AGH-49"],
  golden_path: aGoldenPath({
    phase: "acceptance",
    steps: [
      aGoldenStep({ name: "spec", state: "done", meta: null, progress: null }),
      aGoldenStep({ name: "ux_design", state: "skipped", meta: null, progress: null }),
      aGoldenStep({ name: "research", state: "skipped", meta: null, progress: null }),
      aGoldenStep({ name: "plan", state: "done", meta: "v1", progress: null }),
      aGoldenStep({ name: "tickets", state: "done", meta: "2 of 2 created", progress: null }),
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
        meta: "Ticket evals cover 3 of 13 ACs",
        reason: "Build is unknown",
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

describe("ticketIds", () => {
  it("keeps the bare id once when the spec notes prose beside it", () => {
    expect(
      ticketIds(["AGH-200 (provisional id: renumber if Linear assigns another)", "AGH-200"]),
    ).toEqual(["AGH-200"]);
    expect(ticketIds(["AGH-48", " AGH-49 ", "not an id"])).toEqual([
      "AGH-48",
      "AGH-49",
      "not an id",
    ]);
  });
});

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
      "skipped",
      "done",
      "done",
      "unknown",
      "partial",
      "blocked",
    ]);
    expect(steps[5]).toHaveTextContent("Unknown");
    expect(steps[5]).toHaveTextContent("Linear not connected");
    expect(steps[6]).toHaveTextContent("Partial");
    expect(steps[6]).toHaveTextContent("Ticket evals cover 3 of 13 ACs");
    expect(steps[7]).toHaveTextContent("Blocked");
    expect(steps[7]).toHaveTextContent("Build is not done");
  });

  it("calls out the owner steps left", async () => {
    open();

    const callout = await screen.findByText("Waiting for you: 1 owner step left");
    expect(callout.closest('[role="status"]')).toHaveTextContent("AC-48.13");
    expect(callout.closest('[role="status"]')).toHaveTextContent("memory loads.");
  });

  it("names the evals waiting on owner steps and opens the first in Eval", async () => {
    const waiting = anEvalRecord({
      delivery: "agh-48",
      path: "features/layered-memory/evals/agh-48.md",
      verdict: "SHIP-WITH-OWNER-STEPS",
      tickets: ["AGH-48"],
    });
    const { router } = open({ [API]: { ...detail, evals: [waiting] } });

    const banner = (await screen.findByText("AGH-48: Eval 1 passed with owner steps")).closest(
      '[role="status"]',
    );
    expect(banner).not.toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Review owner steps of Eval 1" }));
    expect(router.state.location.search).toContain("doc=eval");
    expect(router.state.location.search).toContain("eval=agh-48");
  });

  // AGH-330 (ux-change-waiting-prompts.md, A15): one prompt per wait, the banner its signpost.
  describe("owner waits", () => {
    const whole = (delivery: string, evaluated_at: string) =>
      anEvalRecord({
        delivery,
        path: `features/layered-memory/evals/${delivery}.md`,
        verdict: "SHIP-WITH-OWNER-STEPS",
        tickets: [],
        acs: "all",
        evaluated_at,
      });
    const waiting = {
      ...detail,
      evals: [
        whole("feature", "2026-10-10T10:00:00Z"),
        whole("feature-r2", "2026-10-12T10:00:00Z"),
        anEvalRecord({
          delivery: "agh-48",
          path: "features/layered-memory/evals/agh-48.md",
          verdict: "SHIP-WITH-OWNER-STEPS",
          tickets: ["AGH-48"],
          acs: ["AC-48.1"],
          evaluated_at: "2026-10-11T10:00:00Z",
        }),
      ],
      acceptance_eval: {
        delivery: "feature-r2",
        verdict: "SHIP-WITH-OWNER-STEPS" as const,
        owner_wait: {
          state: "sign_off" as const,
          acs: ["AC-48.11", "AC-48.12", "AC-48.13"],
          reopened: [],
        },
      },
      golden_path: aGoldenPath({
        phase: "acceptance",
        steps: detail.golden_path.steps.map((step) =>
          step.name === "acceptance"
            ? { ...step, state: "waiting", meta: "Waiting for you: sign off 3 ACs", reason: null }
            : step,
        ),
      }),
    };

    it("signposts every wait in one banner, the Acceptance wait first, and no sign-off banner", async () => {
      const { router } = open({ [API]: waiting });

      const banner = (await screen.findByText("Acceptance: sign off 3 ACs (Eval 2)")).closest(
        '[role="status"]',
      );
      if (!(banner instanceof HTMLElement)) throw new Error("no banner");
      expect(
        within(banner).getByRole("link", { name: "AGH-48: Eval 1 passed with owner steps" }),
      ).toHaveAttribute("href", "/features/agent-hub/layered-memory?doc=eval&eval=agh-48");
      // One banner title; the Acceptance step says it too, as its typed state (A18).
      expect(screen.getAllByText("Waiting for you", { selector: "b" })).toHaveLength(1);
      expect(screen.getByRole("list", { name: "Golden path" })).toHaveTextContent(
        "Waiting for you: sign off 3 ACs",
      );
      expect(screen.queryByRole("region", { name: "Owner steps" })).toBeNull();
      expect(screen.queryByText(/owner steps? left/)).toBeNull();
      await userEvent.click(
        within(banner).getByRole("button", { name: "Review owner steps of Eval 2" }),
      );
      expect(router.state.location.search).toBe("?doc=eval&eval=feature-r2");
    });

    it("opens the acceptance eval from the Acceptance step", async () => {
      const { router } = open({ [API]: waiting });

      await userEvent.click(
        await screen.findByRole("button", { name: "Open Eval 2, the acceptance eval" }),
      );

      expect(router.state.location.search).toBe("?doc=eval&eval=feature-r2");
      // A signpost lands on its eval: focus goes to its group's row (AGH-330 UX blocker).
      expect(screen.getByRole("button", { name: /^Whole feature\b.*2 evals/ })).toHaveFocus();
    });

    it("moves focus to the eval's group row from the banner's button and lines", async () => {
      open({ [API]: waiting });

      await userEvent.click(
        await screen.findByRole("button", { name: "Review owner steps of Eval 2" }),
      );
      expect(screen.getByRole("button", { name: /^Whole feature\b.*2 evals/ })).toHaveFocus();

      await userEvent.click(
        screen.getByRole("link", { name: "AGH-48: Eval 1 passed with owner steps" }),
      );
      expect(screen.getByRole("button", { name: /^AGH-48\b.*1 eval/ })).toHaveFocus();
    });

    it("says the future-dated wait the same way on the step and in the prompt (future)", async () => {
      const after = "2026-11-21T09:01:00Z";
      open(
        {
          [API]: {
            ...waiting,
            acceptance_eval: {
              ...waiting.acceptance_eval,
              owner_wait: {
                ...waiting.acceptance_eval.owner_wait,
                state: "future" as const,
                signable_after: after,
              },
            },
            golden_path: aGoldenPath({
              phase: "acceptance",
              steps: detail.golden_path.steps.map((step) =>
                step.name === "acceptance"
                  ? {
                      ...step,
                      state: "current",
                      meta: "Sign-off possible after 21 Nov 2026, 09:01:00 UTC",
                      reason: null,
                    }
                  : step,
              ),
            }),
          },
        },
        "/features/agent-hub/layered-memory?doc=eval&eval=feature-r2",
      );

      const line = `Sign-off possible after ${fmtDateTime(after, "local")}`;
      expect(
        await screen.findByRole("button", { name: "Open Eval 2, the acceptance eval" }),
      ).toHaveAccessibleDescription(expect.stringContaining(line));
      expect(screen.getByText(line, { selector: "b" })).toBeInTheDocument();
    });

    it("drops the Acceptance line while no sign-off can be recorded (undated)", async () => {
      open({
        [API]: {
          ...waiting,
          acceptance_eval: {
            ...waiting.acceptance_eval,
            owner_wait: { ...waiting.acceptance_eval.owner_wait, state: "undated" as const },
          },
        },
      });

      expect(await screen.findByText("AGH-48: Eval 1 passed with owner steps")).toBeInTheDocument();
      expect(screen.queryByText(/^Acceptance: sign off/)).toBeNull();
    });

    it("has no serious a11y violations with the banner (a11y)", async () => {
      const { container } = open({ [API]: waiting });
      await screen.findByText("Acceptance: sign off 3 ACs (Eval 2)");

      expect(await seriousViolations(container)).toEqual([]);
      // Long under the fast gate's parallel lanes, as the panel's axe test is.
    }, 20_000);
  });

  it("shows every AC row at once, with no Show all fold (AC-269.12)", async () => {
    open();

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByRole("button", { name: /^(Expand|Collapse) AC-/ })).toHaveLength(
      13,
    );
    expect(within(table).queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("reads each criterion as status, evidence in plain words, citations and Discuss (AC-269.10, AC-269.11)", async () => {
    const proven = {
      ...rows[0],
      id: "AC-48.1",
      evidence:
        "agent-hub@0a1b2c3d4 (PR #80), 2026-10-11, whole-feature eval: exit 0, 4 passed, 9 deselected; red on merge base 9f8e7d6c5 (ImportError on brief). evals/agh-48.md",
    };
    const cited = (request: Request) => {
      const path = new URL(request.url).searchParams.get("path") ?? "";
      return aBrainNote({
        path,
        markdown: path.endsWith("spec.md")
          ? "# Spec\n\n## Acceptance criteria\n\n**AC-48.1: workspace ignored**\n"
          : `# Record ${path}\n`,
      });
    };
    open({
      [API]: { ...detail, ac_rows: [proven, ...rows.slice(1)] },
      [NOTE]: cited,
      "/api/v1/projects/agent-hub/brain": aBrainTree({
        entries: [
          { path: "features/layered-memory/spec.md", size: 90 },
          { path: "features/layered-memory/plan.md", size: 90 },
        ],
      }),
    });

    const table = await screen.findByRole("table", { name: "Acceptance criteria" });
    expect(within(table).getAllByText("Passes").length).toBeGreaterThan(0);
    expect(within(table).getByText("4 tests passed")).toHaveAttribute(
      "title",
      expect.stringContaining("4 tests that check this criterion ran and passed."),
    );
    expect(
      within(table).getByRole("button", { name: "Discuss AC-48.1 with Claude" }),
    ).toHaveTextContent("Discuss");

    await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.1" }));
    const how = within(table).getByRole("region", { name: "How it was proven" });
    expect(how).toHaveTextContent("PR");
    expect(how).toHaveTextContent("#80");
    expect(how).toHaveTextContent("red on merge base 9f8e7d6c5 (ImportError on brief)");
    expect(within(how).getByRole("link", { name: /agh-48/ })).toHaveAttribute(
      "href",
      expect.stringContaining("doc=eval&eval=agh-48"),
    );
    const where = within(table).getByRole("region", { name: "Where it is cited" });
    expect(await within(where).findByRole("link", { name: "Spec" })).toHaveAttribute(
      "href",
      expect.stringContaining("doc=spec"),
    );
    expect(where).toHaveTextContent("Acceptance criteria");
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

  it("moves keyboard focus to the asked AC's toggle when it opens by ?ac=", async () => {
    open({}, "/features/agent-hub/layered-memory?doc=acs&ac=AC-48.12");

    const toggle = await screen.findByRole("button", { name: "Collapse AC-48.12" });
    await waitFor(() => {
      expect(toggle).toHaveFocus();
    });
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
    it("has the Spec, Research, Plan, Eval and Acceptance criteria tabs (AC-269.9, records)", async () => {
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

    it("opens the plan on its human summary, read from the brain (AC-269.13, records)", async () => {
      const { requests } = open();

      await userEvent.click(await screen.findByRole("tab", { name: "Plan" }));

      expect(
        await screen.findByRole("heading", { level: 1, name: "Layered memory, in short" }),
      ).toBeInTheDocument();
      const asked = requests
        .filter((r) => new URL(r.url).pathname === NOTE)
        .map((r) => new URL(r.url).searchParams.get("path"));
      expect(asked).toContain("features/layered-memory/summaries/plan.md");
      expect(await screen.findByText(/\(the current version\)/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /For humans/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByRole("link", { name: "Open in Brain" })).toHaveAttribute(
        "href",
        "/projects/agent-hub/brain/features/layered-memory/plan.md",
      );
    });

    it("shows the record as the agents wrote it on Agent markdown (AC-269.13, records)", async () => {
      const { router } = open();
      await userEvent.click(await screen.findByRole("tab", { name: "Plan" }));

      await userEvent.click(screen.getByRole("button", { name: /Agent markdown/ }));

      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Record features/layered-memory/plan.md",
        }),
      ).toBeInTheDocument();
      expect(screen.getByRole("list", { name: "Frontmatter" })).toHaveTextContent(
        "status: approved",
      );
      expect(router.state.location.search).toContain("view=agent");
    });

    it("opens the record at the section a summary point comes from (AC-269.14, records)", async () => {
      const scroll = vi.fn();
      Element.prototype.scrollIntoView = scroll;
      const { router } = open({}, "/features/agent-hub/layered-memory?doc=plan");

      await userEvent.click(await screen.findByRole("link", { name: "Open questions" }));

      expect(router.state.location.search).toContain("view=agent");
      expect(router.state.location.hash).toBe("#open-questions");
      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Record features/layered-memory/plan.md",
        }),
      ).toBeInTheDocument();
      await waitFor(() => {
        expect(scroll).toHaveBeenCalled();
      });
    });

    it("warns when the record changed after its summary was written (AC-269.15, records)", async () => {
      open(
        { [NOTE]: recordsWithSummary((path) => summaryNote(path, "b".repeat(64))) },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(
        await screen.findByText("plan.md changed after this summary was written."),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ask Claude to update it" })).toBeInTheDocument();
    });

    it("offers Claude and the full record when a record has no summary (AC-269.16, records)", async () => {
      open(
        { [NOTE]: recordsWithSummary(() => aProblem({ status: 404, title: "Not found" })) },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(await screen.findByText("No human summary of plan.md yet.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ask Claude to write it" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Read the full plan.md" }));
      expect(
        await screen.findByRole("heading", {
          level: 1,
          name: "Record features/layered-memory/plan.md",
        }),
      ).toBeInTheDocument();
    });

    it("asks for no summary the brain does not list, so no 404 reaches the console (AC-269.16, records)", async () => {
      const { requests } = open(
        {
          "/api/v1/projects/agent-hub/brain": aBrainTree({
            entries: [{ path: "features/layered-memory/plan.md", size: 90 }],
          }),
        },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(await screen.findByText("No human summary of plan.md yet.")).toBeInTheDocument();
      expect(
        requests.some(
          (r) =>
            new URL(r.url).pathname === NOTE &&
            new URL(r.url).searchParams.get("path")?.includes("/summaries/") === true,
        ),
      ).toBe(false);
    });

    it("shows the plan version line with one link per amendment (two-level-flows AC-1.4)", async () => {
      const amendment = (id: string, title: string) => ({
        id,
        date: "2026-10-20",
        who: "Ana",
        title,
        anchor: "Amendments",
      });
      const { router } = open(
        {
          [API]: {
            ...detail,
            plan: {
              version: 3,
              amendments: [amendment("A1", "Split the ticket"), amendment("A2", "Drop the export")],
              problem: null,
            },
          },
        },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(
        await screen.findByText(versionLine("Plan v3 · amendments A1, A2")),
      ).toBeInTheDocument();
      const second = screen.getByRole("link", { name: "A2" });
      expect(second).toHaveAttribute("title", "A2 (2026-10-20, Ana): Drop the export");
      await userEvent.click(second);

      expect(router.state.location.search).toContain("view=agent");
      expect(router.state.location.hash).toBe("#Amendments");
    });

    it("shows v1 when the plan has no amendments (two-level-flows AC-1.4)", async () => {
      open(
        { [API]: { ...detail, plan: { version: 1, amendments: [], problem: null } } },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(await screen.findByText(versionLine("Plan v1 · no amendments"))).toBeInTheDocument();
    });

    it("says why the plan version is unknown when plan.md is too large (two-level-flows AC-1.4)", async () => {
      const problem = "plan.md is larger than 256 KiB; its version could not be read.";
      open(
        { [API]: { ...detail, plan: { version: null, amendments: [], problem } } },
        "/features/agent-hub/layered-memory?doc=plan",
      );

      expect(await screen.findByText(problem)).toBeInTheDocument();
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
      const { router } = open({}, "/features/agent-hub/layered-memory?doc=spec&view=agent");

      await userEvent.click(await screen.findByRole("link", { name: "the index" }));

      expect(router.state.location.pathname).toBe("/projects/agent-hub/brain/index.md");
    });

    it("lists every delivery's eval on the Eval tab (golden)", async () => {
      open();

      await userEvent.click(await screen.findByRole("tab", { name: "Eval" }));

      const table = screen.getByRole("table", { name: "Evals" });
      for (const toggle of within(table).queryAllByRole("button", { expanded: false })) {
        await userEvent.click(toggle);
      }
      expect(within(table).getByRole("button", { name: /^agh-48,/ })).toBeInTheDocument();
      expect(table).toHaveTextContent("NO-SHIP");
      expect(within(table).getByRole("button", { name: /^agh-49,/ })).toHaveAttribute(
        "title",
        "brain/features/layered-memory/evals/agh-49.md",
      );
    });

    it("reads the eval ?eval= names in place and keeps a new choice in the URL (AC-269.4)", async () => {
      open({}, "/features/agent-hub/layered-memory?doc=eval&eval=agh-48");

      expect(await screen.findByRole("article", { name: "Eval agh-48" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^AGH-49\b.*1 eval/ }));
      await userEvent.click(screen.getByRole("button", { name: /^agh-49,/ }));
      expect(await screen.findByRole("article", { name: "Eval agh-49" })).toBeInTheDocument();
    });

    it("expands an AC into its verification command and evidence (AC-269.11, records)", async () => {
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

    const failedRun = {
      [`POST ${API}/acs/AC-48.2/check-runs`]: {
        ac: "AC-48.2",
        command: "uv run pytest -k case_2",
        repo: "agent-hub",
        branch: "main",
        commit: "0f4d1f7",
        exit_code: 1,
        passed: false,
        timed_out: false,
        duration_ms: 4200,
        output: "1 failed in 0.4s",
        truncated: false,
      },
    };

    async function runCheck() {
      window.localStorage.clear();
      const table = await screen.findByRole("table", { name: "Acceptance criteria" });
      await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.2" }));
      const check = within(table).getByRole("region", { name: "Check it yourself" });
      await userEvent.click(
        within(check).getByRole("button", { name: "Choose how to run the check" }),
      );
      await userEvent.click(within(check).getByRole("button", { name: /^Run in terminal/ }));
      await within(check).findByText("Failed · exit 1");
      return check;
    }

    it("runs an AC's check with Claude by default, in the AC's repo folder (playground)", async () => {
      window.localStorage.clear();
      const created = anAgentSession({ id: anId(9, "0192a5e5"), status: "running" });
      const repo = aWorkdir({
        kind: "repo",
        label: "agent-hub",
        repo: "agent-hub",
        workdir_id: "w-repo",
      });
      const view = open({
        "/api/v1/agent-sessions/capabilities": aCapabilities(),
        "/api/v1/agent-sessions/workdirs": { items: [aWorkdir(), repo], warnings: [] },
        "POST /api/v1/agent-sessions": created,
        [`/api/v1/agent-sessions/${created.id}`]: created,
      });

      const table = await screen.findByRole("table", { name: "Acceptance criteria" });
      await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.2" }));
      const check = within(table).getByRole("region", { name: "Check it yourself" });
      const run = await within(check).findByRole("button", { name: "Run with Claude" });
      await waitFor(() => {
        expect(run).toBeEnabled();
      });
      await userEvent.click(run);

      const post = await waitFor(() => {
        const found = view.requests.find(
          (r) => r.method === "POST" && new URL(r.url).pathname === "/api/v1/agent-sessions",
        );
        if (!found) throw new Error("no POST");
        return found;
      });
      const body = JSON.parse(await post.clone().text()) as Record<string, unknown>;
      expect(body).toMatchObject({ project: "agent-hub", workdir_id: "w-repo", mode: "default" });
      expect(String(body.prompt)).toContain("uv run pytest -k case_2");
      expect(await within(check).findByText("Claude is running the check")).toBeInTheDocument();
      expect(within(check).getByRole("link", { name: /Open chat/ })).toHaveAttribute(
        "href",
        `/agent-sessions/${created.id}`,
      );
    });

    it("runs an AC's check and shows this run's result, not the record's (playground)", async () => {
      open(failedRun);

      const check = await runCheck();

      expect(check).toHaveTextContent("This run");
      expect(check).toHaveTextContent("main @ 0f4d1f7");
      expect(check).toHaveTextContent("Not recorded.");
      expect(within(check).getByLabelText("Output of AC-48.2's check")).toHaveTextContent(
        "1 failed in 0.4s",
      );
      expect(within(check).getByText("AC-48.2's check failed, exit 1, 4.2 s.")).toHaveAttribute(
        "aria-live",
        "polite",
      );
      expect(within(check).getByRole("button", { name: "Run in terminal" })).toBeInTheDocument();
    });

    it("keeps an AC's last run when its card closes and opens again (playground)", async () => {
      open(failedRun);
      await runCheck();
      const table = screen.getByRole("table", { name: "Acceptance criteria" });

      await userEvent.click(within(table).getByRole("button", { name: "Collapse AC-48.2" }));
      await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.2" }));

      expect(within(table).getByText("Failed · exit 1")).toBeInTheDocument();
    });

    it("says before any click that checks are locked in this browser (playground)", async () => {
      window.localStorage.clear();
      open({
        "/api/v1/agent-sessions/capabilities": aProblem({
          status: 401,
          title: "Session cookie required",
        }),
      });

      const table = await screen.findByRole("table", { name: "Acceptance criteria" });
      await userEvent.click(within(table).getByRole("button", { name: "Expand AC-48.2" }));
      const check = within(table).getByRole("region", { name: "Check it yourself" });

      expect(
        await within(check).findByRole("button", {
          name: /^Run with Claude\. Locked in this browser/,
        }),
      ).toBeDisabled();
    });

    it("has no serious axe violations with a run's result open (a11y, playground)", async () => {
      const { container } = open(failedRun);
      await runCheck();

      expect(await seriousViolations(container)).toEqual([]);
    });

    it("marks a manual AC's verification as an owner step (records)", async () => {
      open();

      const check = await screen.findByRole("region", { name: "Check it yourself" });
      expect(check).toHaveTextContent("Manual owner step:");
      const proven = screen.getByRole("region", { name: "How it was proven" });
      expect(proven).toHaveTextContent("eval.md §Owner steps");
    });

    it("says when an AC has no evidence or verification yet (records)", async () => {
      open(
        {
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
        },
        "/features/agent-hub/layered-memory?doc=acs",
      );

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
        epics: [],
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

      // The Flow view opens first (AC-1.11); its cards say what each ticket waits on.
      const flow = await screen.findByRole("region", { name: "Ticket flow" });
      expect(flow).toHaveTextContent("Load the memory layers");
      expect(within(flow).getByText("Can start now")).toBeInTheDocument();
      expect(within(flow).getByText(/Waiting on/)).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");
      expect(router.state.location.search).toBe("?doc=tickets");
      expect(asked(requests, TICKETS)).toBe(1);
    });

    it("rereads the record every 15 s and Linear every 30 s while the Tickets tab is open (refresh)", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        const { requests } = open(
          { [TICKETS]: tickets },
          "/features/agent-hub/layered-memory?doc=tickets",
        );
        await screen.findByRole("region", { name: "Ticket flow" });
        const record = asked(requests, API);
        const linear = asked(requests, TICKETS);

        await vi.advanceTimersByTimeAsync(FEATURE_REFRESH_MS);
        await waitFor(() => {
          expect(asked(requests, API)).toBeGreaterThan(record);
        });
        await vi.advanceTimersByTimeAsync(TICKETS_REFRESH_MS - FEATURE_REFRESH_MS);
        await waitFor(() => {
          expect(asked(requests, TICKETS)).toBeGreaterThan(linear);
        });
        expect(screen.getByText(/Live from Linear · read/)).toHaveTextContent(
          "updates every 30 s while this tab is open",
        );
      } finally {
        vi.useRealTimers();
      }
    });

    it("opens the Tickets tab from an old ?doc=issues link (tickets)", async () => {
      open({ [TICKETS]: tickets }, "/features/agent-hub/layered-memory?doc=issues");

      expect(await screen.findByRole("region", { name: "Ticket flow" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");
    });

    it("shows each header chip with its Linear status and title on hover, and no PR placeholder (tickets)", async () => {
      open({ [TICKETS]: tickets }, "/features/agent-hub/layered-memory?doc=tickets");

      await screen.findByRole("region", { name: "Ticket flow" });

      const header = screen.getByRole("group", { name: "Tickets of this feature" });
      const link = within(header).getByRole("link", { name: "AGH-48" });
      expect(link).toHaveTextContent(/^AGH-48$/);
      expect(link).toHaveAttribute(
        "href",
        "/features/agent-hub/layered-memory?doc=tickets&ticket=AGH-48",
      );
      // Its destination is its description (AGH-330 UX F6).
      expect(link).toHaveAccessibleDescription("AGH-48 · Load the memory layers · show its steps");
      expect(within(header).getAllByText("In Progress")).toHaveLength(2);
      expect(screen.queryByText("PR —")).toBeNull();
    });

    it("opens on the Tickets tab while the feature is in Build (tabs)", async () => {
      const { requests } = open({ [API]: { ...detail, phase: "build" }, [TICKETS]: tickets });

      expect(await screen.findByRole("region", { name: "Ticket flow" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");
      expect(asked(requests, TICKETS)).toBe(1);
    });

    it("opens a step's tab from the golden path (golden path)", async () => {
      const { router } = open({ [TICKETS]: tickets });

      await userEvent.click(
        await screen.findByRole("button", { name: "Open the ticket plan of build" }),
      );

      expect(await screen.findByRole("region", { name: "Ticket flow" })).toBeInTheDocument();
      expect(router.state.location.search).toBe("?doc=tickets");
      await userEvent.click(screen.getByRole("button", { name: "Open the eval of acceptance" }));
      // Without an acceptance eval, the step names the tab it opens.
      expect(screen.getByRole("tab", { name: "Eval" })).toHaveAttribute("aria-selected", "true");
    });

    it("shows the ticket ids in the header until the tickets load (tickets)", async () => {
      open();

      await screen.findByRole("heading", { level: 1, name: "layered-memory" });

      const header = screen.getByRole("group", { name: "Tickets of this feature" });
      expect(within(header).getByRole("link", { name: "AGH-48" })).toBeInTheDocument();
      expect(within(header).getByRole("link", { name: "AGH-49" })).toHaveAccessibleDescription(
        "AGH-49 · show its steps",
      );
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
        phase: "acceptance",
        steps: detail.golden_path.steps.map((step) =>
          step.name === "build"
            ? { ...step, state: "done", reason: null, meta: "2 of 2 merged" }
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

      await screen.findByRole("region", { name: "Ticket flow" });

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
      await screen.findByRole("region", { name: "Ticket flow" });

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
      "/features/agent-hub/layered-memory?doc=acs",
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("features.json could not be parsed");
    expect(screen.getByRole("tablist")).toBeInTheDocument();
  });

  it("explains a feature without features.json", async () => {
    open(
      { [API]: aFeatureDetail({ acs: null, ac_rows: [] }) },
      "/features/agent-hub/layered-memory?doc=acs",
    );

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

describe("FeatureDetailScreen and the feature's own session (AGH-422)", () => {
  it("AC-422.1 names the session that wrote the spec in the header, one click from the panel", async () => {
    const writer = anAgentSession({
      id: anId(9, "0192a5e9"),
      title: "Write the layered memory spec",
    });
    open({
      "/api/v1/agent-sessions": (request: Request) => ({
        items: new URL(request.url).searchParams.get("wrote")?.endsWith("/spec.md") ? [writer] : [],
      }),
    });

    const chip = await screen.findByRole("button", { name: "Write the layered memory spec" });
    expect(chip).toHaveAttribute(
      "title",
      "Talk with the session that wrote this feature's records: Write the layered memory spec",
    );
  });
});
