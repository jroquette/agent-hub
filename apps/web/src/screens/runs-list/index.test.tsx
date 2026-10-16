import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aWorkflowCatalog,
  aPage,
  aProblem,
  aRun,
  anEngineRun,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { RunsListScreen } from ".";

const failed = aRun({
  id: "01923f1e-aaaa-7000-8000-000000000001",
  issue: { key: "AGH-79", title: "Guard bypass", url: null },
  stage: "FAILED",
  failure: { stage: "VERIFYING", reason: "make check exited 2", failing_event_id: null },
  cost_usd: "6.8000",
  caps: { budget_usd: "10.0000", max_turns: 120, model: null, tracker_transport: null },
  started_at: at(-7200),
  ended_at: at(-3000),
  steps: [
    {
      attempt: 2,
      ended_at: at(-3000),
      key: "verify",
      max_attempts: 2,
      reason: "exit 2",
      session_ids: [],
      started_at: at(-3200),
      status: "failed",
    },
  ],
});
const running = aRun({
  id: "01923f9c-aaaa-7000-8000-000000000002",
  issue: { key: "AGH-112", title: null, url: null },
  stage: "IMPLEMENTING",
  cost_usd: "4.6000",
  caps: { budget_usd: "5.0000", max_turns: 80, model: null, tracker_transport: null },
  started_at: at(-600),
});
const done = aRun({
  id: "01922b10-aaaa-7000-8000-000000000003",
  issue: { key: "AGH-48", title: "Layered memory", url: null },
  stage: "REPORTED",
  cost_usd: "9.1200",
  caps: null,
  mode: "dry_run",
  pr_url: "https://example.invalid/pr/69",
  repo: "loki-trader-ui",
  started_at: at(-1000),
  ended_at: at(-100),
});

/** The element at `index`, failing the test when it is missing. */
function nth(elements: HTMLElement[], index: number): HTMLElement {
  const element = elements[index];
  if (!element) throw new Error(`No element at ${String(index)}`);
  return element;
}
const routes: ApiRoutes = { "/api/v1/workflow-runs": aPage([done, running, failed]) };

describe("RunsListScreen", () => {
  it("lists failed and running runs first with stage, attempt, cost and outcome", async () => {
    renderWithApi(<RunsListScreen />, { routes, path: "/runs" });

    await screen.findByText("Guard bypass");
    const table = screen.getByRole("table", { name: /Workflow runs/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByText(/^AGH-/)[0]?.textContent)).toEqual([
      "AGH-79",
      "AGH-112",
      "AGH-48",
    ]);
    expect(within(nth(rows, 0)).getByText("Failed · Verifying")).toBeInTheDocument();
    expect(within(nth(rows, 0)).getByText("attempt 2 of 2")).toBeInTheDocument();
    expect(
      within(nth(rows, 0)).getByRole("progressbar", { name: "Cost $6.80 of $10.00" }),
    ).toBeInTheDocument();
    expect(within(nth(rows, 1)).getByText("Running")).toBeInTheDocument();
    expect(within(nth(rows, 2)).getByText("dry run")).toBeInTheDocument();
    expect(within(nth(rows, 2)).getByRole("link", { name: /PR/ })).toHaveAttribute(
      "href",
      "https://example.invalid/pr/69",
    );
    expect(screen.getByText(/runs ·/).textContent).toBe(
      "3 runs · 1 reported · 1 failed · 1 in progress · median $7.96",
    );
  });

  it.each(["javascript:alert(1)", "data:text/html,x"])(
    "renders PR as plain text when the run's pr_url is %s",
    async (prUrl) => {
      renderWithApi(<RunsListScreen />, {
        routes: { "/api/v1/workflow-runs": aPage([{ ...done, pr_url: prUrl }]) },
        path: "/runs",
      });

      await screen.findByText("Layered memory");
      const table = screen.getByRole("table", { name: /Workflow runs/ });
      expect(within(table).queryByRole("link", { name: /PR/ })).not.toBeInTheDocument();
      expect(within(table).getByText("PR")).toBeInTheDocument();
    },
  );

  it.each([
    ["no_changes", "No changes", "no commit on the branch"],
    ["blocked", "Blocked", "the implementing session stopped: needs a plan"],
  ] as const)(
    "labels a reported run that opened no PR by its delivery (%s)",
    async (delivery, label, reason) => {
      const ended = { ...done, pr_url: null, delivery, delivery_reason: reason };
      renderWithApi(<RunsListScreen />, {
        routes: { "/api/v1/workflow-runs": aPage([ended]) },
        path: "/runs",
      });

      await screen.findByText("Layered memory");
      const table = screen.getByRole("table", { name: /Workflow runs/ });
      expect(within(table).getByText(label)).toBeInTheDocument();
      expect(within(table).queryByText("Done")).not.toBeInTheDocument();
      expect(within(table).getByText("no PR")).toBeInTheDocument();
    },
  );

  it("offers Start run without the P4 tag and opens its dialog", async () => {
    const user = userEvent.setup();
    renderWithApi(<RunsListScreen />, {
      routes: { ...routes, "/api/v1/workflows": aWorkflowCatalog() },
      path: "/runs",
    });

    const button = await screen.findByRole("button", { name: "Start run" });
    expect(button).toBeEnabled();
    expect(within(button).queryByText("P4")).toBeNull();
    expect(screen.queryByRole("button", { name: /Start run on an issue/ })).toBeNull();
    await user.click(button);
    expect(screen.getByRole("dialog", { name: "Start a workflow run" })).toBeInTheDocument();
  });

  it("opens the run when its row is clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderWithApi(<RunsListScreen />, { routes, path: "/runs" });

    await user.click(await screen.findByText("Guard bypass"));

    expect(router.state.location.pathname).toBe(`/runs/${failed.id}`);
  });

  it("filters through the URL and the API when a facet is toggled", async () => {
    const user = userEvent.setup();
    const { router, requests } = renderWithApi(<RunsListScreen />, { routes, path: "/runs" });

    const rail = await screen.findByRole("complementary", { name: "Filters" });
    await waitFor(() => {
      expect(within(rail).getByRole("group", { name: "Repo" })).toHaveTextContent("loki-trader-ui");
    });
    await user.click(
      within(within(rail).getByRole("group", { name: "Outcome" })).getByRole("checkbox", {
        name: /Failed/,
      }),
    );

    expect(router.state.location.search).toContain("outcome=failed");
    await waitFor(() => {
      expect(requests.some((r) => r.url.includes("outcome=failed"))).toBe(true);
    });
    await user.click(
      within(within(rail).getByRole("group", { name: "Outcome" })).getByRole("checkbox", {
        name: /Failed/,
      }),
    );
    expect(router.state.location.search).not.toContain("outcome");
  });

  it("filters by workflow and failure kind through the URL and the API", async () => {
    const user = userEvent.setup();
    const { router, requests } = renderWithApi(<RunsListScreen />, {
      routes: { "/api/v1/workflow-runs": aPage([done, anEngineRun()]) },
      path: "/runs",
    });

    const rail = await screen.findByRole("complementary", { name: "Filters" });
    await waitFor(() => {
      expect(within(rail).getByRole("group", { name: "Workflow" })).toHaveTextContent(
        "feature-flow",
      );
    });
    const workflows = within(rail).getByRole("group", { name: "Workflow" });
    expect(within(workflows).getByRole("checkbox", { name: /issue-to-pr/ })).toBeInTheDocument();
    await user.click(within(workflows).getByRole("checkbox", { name: /feature-flow/ }));
    expect(router.state.location.search).toContain("workflow=feature-flow");

    const kinds = within(rail).getByRole("group", { name: "Failure kind" });
    await user.click(within(kinds).getByRole("checkbox", { name: /Timeout/ }));
    expect(router.state.location.search).toContain("failure_kind=timeout");
    await waitFor(() => {
      expect(
        requests.some(
          (r) => r.url.includes("workflow=feature-flow") && r.url.includes("failure_kind=timeout"),
        ),
      ).toBe(true);
    });
  });

  it("ignores a failure kind the API does not know", async () => {
    const { requests } = renderWithApi(<RunsListScreen />, {
      routes,
      path: "/runs?failure_kind=bogus",
    });

    await screen.findByText("Guard bypass");
    expect(requests.some((r) => r.url.includes("failure_kind"))).toBe(false);
  });

  it("offers Clear filters when the filters exclude every run", async () => {
    const user = userEvent.setup();
    const { router } = renderWithApi(<RunsListScreen />, {
      routes: { "/api/v1/workflow-runs": aPage([]) },
      path: "/runs?stage=VERIFYING&repo=agent-hub&mode=live&failure_stage=VERIFYING&outcome=done&workflow=x&failure_kind=timeout",
    });

    expect(await screen.findByText("No runs match these filters.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(router.state.location.search).toBe("");
  });

  it("shows more rows when the API has another page", async () => {
    const user = userEvent.setup();
    const { requests } = renderWithApi(<RunsListScreen />, {
      routes: {
        "/api/v1/workflow-runs": { ...aPage([failed]), next_cursor: "c2", total_estimate: 80 },
      },
      path: "/runs",
    });

    expect(await screen.findByText(/Showing 1 of 80/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => {
      expect(requests.some((r) => r.url.includes("limit=100"))).toBe(true);
    });
  });

  describe("states", () => {
    it("shows skeleton rows after 300 ms while pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderWithApi(<RunsListScreen />, {
          routes: { "/api/v1/workflow-runs": "pending" },
          path: "/runs",
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });
        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(5);
        expect(screen.getByText("Loading runs…")).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows the empty copy with the dry-run command when no run exists", async () => {
      renderWithApi(<RunsListScreen />, {
        routes: { "/api/v1/workflow-runs": aPage([]) },
        path: "/runs",
      });

      expect(await screen.findByText("No workflow runs yet.")).toBeInTheDocument();
      expect(
        screen.getByText(/Runs appear when the executor picks an issue labelled agent-ready/),
      ).toBeInTheDocument();
      expect(screen.getByText("./hub run <issue> --dry-run")).toBeInTheDocument();
      expect(screen.queryByRole("complementary", { name: "Filters" })).not.toBeInTheDocument();
    });

    it("replaces the table with the problem when the request fails", async () => {
      renderWithApi(<RunsListScreen />, {
        routes: {
          "/api/v1/workflow-runs": aProblem({
            status: 503,
            title: "Busy",
            detail: "The collector database is locked by another process.",
          }),
        },
        path: "/runs",
      });

      expect(await screen.findByText("Could not load workflow runs")).toBeInTheDocument();
      expect(
        screen.getByText("The collector database is locked by another process."),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("stamps the header as stale when the collector is offline", async () => {
      renderWithApi(<RunsListScreen />, { routes, path: "/runs" });

      await screen.findByRole("table", { name: /Workflow runs/ });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderWithApi(<RunsListScreen />, { routes, path: "/runs" });

    await screen.findByText("Guard bypass");
    expect(await seriousViolations(container)).toEqual([]);
  });
});
