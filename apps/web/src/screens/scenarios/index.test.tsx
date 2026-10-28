import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aPage,
  aProblem,
  aRun,
  anApproval,
  aScenarioCatalog,
  aScenarioRunRef,
  aScenarioSummary,
  aWorkflowProblem,
  renderWithApi,
  SCENARIO_RUN,
  type ApiRoutes,
} from "../../testing/builders";
import { ScenariosScreen } from ".";

const waitingGate = anApproval({
  id: `${SCENARIO_RUN}:order-processed__investigation:1`,
  gate_id: `${SCENARIO_RUN}:order-processed__investigation:1`,
  session_id: `run:${SCENARIO_RUN}`,
  kind: "human_gate",
  project: "demo",
  gate_kind: "investigation",
  path: null,
  rule: null,
});

const catalog = aScenarioCatalog({
  items: [
    aScenarioSummary({ last_run: aScenarioRunRef() }),
    aScenarioSummary({
      name: "invoice-pdf",
      description: "An invoice gets its PDF",
      node_count: 4,
      last_run: aScenarioRunRef({
        run_id: "9b0d1f37",
        status: "done",
        ended_at: "2026-10-21T17:03:00.000Z",
      }),
    }),
    aScenarioSummary({
      name: "refund-flow",
      pack: "payments",
      description: null,
      node_count: 6,
      last_run: aScenarioRunRef({ run_id: "01c2e4aa", status: "cancelled" }),
    }),
    aScenarioSummary({
      name: "stock-sync",
      pack: "payments",
      description: "Stock counts match after a sync",
      node_count: 3,
    }),
  ],
  problems: [
    {
      ...aWorkflowProblem(),
      project: "demo",
      file: "scenarios/orders/returns.yaml",
      line: 14,
      key: "nodes[2].type",
      message: "shell nodes are not allowed in a scenario",
    },
  ],
});

const routes: ApiRoutes = {
  "/api/v1/scenarios": catalog,
  "/api/v1/approvals": aPage([waitingGate]),
  "/api/v1/workflow-runs": aPage([
    aRun({ id: SCENARIO_RUN, workflow: "scenario:order-lifecycle", project: "demo" }),
  ]),
};

function renderList(extra: ApiRoutes = {}, path = "/scenarios") {
  return renderWithApi(<ScenariosScreen />, { routes: { ...routes, ...extra }, path });
}

// Vitest runs from apps/web and does not process CSS imports, so the rules are read as files.
const cssOf = (path: string) => readFileSync(join(process.cwd(), path), "utf8");
const ruleOf = (css: string, selector: string): string => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rule = new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`).exec(css);
  if (!rule?.[1]) throw new Error(`no rule ${selector}`);
  return rule[1];
};
/** The rules of one `@media` block, up to the next top-level rule or block. */
const mediaOf = (css: string, query: string): string => {
  const start = css.indexOf(`@media ${query} {`);
  if (start < 0) throw new Error(`no @media ${query}`);
  const end = css.indexOf("\n}\n", start);
  return css.slice(start, end < 0 ? undefined : end);
};

describe("ScenariosScreen (scenarios list)", () => {
  it("scenarios list renders each scenario with its pack, steps and last scenario run", async () => {
    renderList();

    const table = await screen.findByRole("list", { name: "Scenarios" });
    const rows = within(table).getAllByRole("listitem");
    // The one waiting for you first, then by name.
    expect(rows.map((row) => row.dataset.rowKey)).toEqual([
      "demo/order-lifecycle",
      "demo/invoice-pdf",
      "demo/refund-flow",
      "demo/stock-sync",
    ]);
    expect(rows[0]).toHaveAttribute("data-tone", "waiting");
    expect(rows[2]).toHaveTextContent("payments");
    expect(within(table).getByRole("link", { name: "order-lifecycle" })).toHaveAttribute(
      "href",
      "/scenarios/demo/order-lifecycle",
    );
    expect(within(table).getByText("One order from fetch to an active cover")).toBeInTheDocument();
    expect(within(table).getByText("No description.")).toBeInTheDocument();
    expect(within(table).getByText("Never run")).toBeInTheDocument();
    expect(within(table).getByText("Done")).toBeInTheDocument();
    expect(within(table).getByText("Cancelled")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "Open scenario run 9b0d1f37" })).toHaveAttribute(
      "href",
      "/scenarios/demo/invoice-pdf/runs/9b0d1f37",
    );
    // AC-596.1.10: the summary's parts, each exact.
    expect(
      [...(document.querySelector(".ft-summary")?.children ?? [])].map((part) => part.textContent),
    ).toEqual(["4 scenarios", "2 packs", "1 waits for you"]);
    const problems = screen.getByRole("table", { name: "Files that do not load (1)" });
    expect(within(problems).getByText("scenarios/orders/returns.yaml:14")).toBeInTheDocument();
    expect(
      within(problems).getByText("shell nodes are not allowed in a scenario"),
    ).toBeInTheDocument();
  });

  it("scenarios list shows the waiting card for a scenario run paused at an investigation", async () => {
    renderList();

    const card = await screen.findByRole("region", { name: "Waiting for you" });
    expect(card).toHaveTextContent(
      `order-lifecycle · scenario run ${SCENARIO_RUN} paused at order-processed since`,
    );
    expect(
      within(card).getByRole("link", { name: `Open scenario run ${SCENARIO_RUN}` }),
    ).toHaveAttribute("href", `/scenarios/demo/order-lifecycle/runs/${SCENARIO_RUN}`);
    const table = screen.getByRole("list", { name: "Scenarios" });
    expect(within(table).getByText("Waiting for you")).toBeInTheDocument();
  });

  it("scenarios list says a policy ask waits for your approval at its step", async () => {
    renderList({
      "/api/v1/approvals": aPage([
        {
          ...waitingGate,
          id: `${SCENARIO_RUN}:fetch-order__ask:1`,
          gate_id: `${SCENARIO_RUN}:fetch-order__ask:1`,
          gate_kind: "policy",
        },
      ]),
    });

    const card = await screen.findByRole("region", { name: "Waiting for you" });
    expect(card).toHaveTextContent("waits for your approval at fetch-order since");
  });

  it("scenarios list shows the empty state", async () => {
    renderList({
      "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
      "/api/v1/approvals": aPage([]),
    });

    expect(await screen.findByText("No scenarios yet.")).toBeInTheDocument();
    expect(
      screen.getByText(/Scenarios are YAML files in the hub's scenarios\/<pack>\/ folder/),
    ).toBeInTheDocument();
    expect(screen.getByText("./hub scenario list")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Waiting for you" })).toBeNull();
  });

  it("scenarios list opens New scenario from its header and from its empty state", async () => {
    const user = userEvent.setup();
    const listed = renderList();
    await user.click(await screen.findByRole("button", { name: "New scenario" }));
    expect(listed.router.state.location.pathname).toBe("/scenarios/new");
    listed.unmount();

    const empty = renderList({
      "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
      "/api/v1/approvals": aPage([]),
    });
    await screen.findByText("No scenarios yet.");
    const [header, inEmptyState] = screen.getAllByRole("button", { name: "New scenario" });
    expect(header).toBeInTheDocument();
    if (!inEmptyState) throw new Error("the empty state offers no New scenario");
    await user.click(inEmptyState);
    expect(empty.router.state.location.pathname).toBe("/scenarios/new");
  });

  it("scenarios list names the project in scope when it holds none", async () => {
    renderList(
      {
        "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: [] }),
        "/api/v1/approvals": aPage([]),
      },
      "/scenarios?scope=demo",
    );

    expect(await screen.findByText("No scenarios in demo yet.")).toBeInTheDocument();
  });

  it("scenarios list filters by name or description and clears the filter", async () => {
    const user = userEvent.setup();
    const { router } = renderList();
    const filter = await screen.findByRole("searchbox", {
      name: "Filter scenarios by name or description",
    });

    await user.type(filter, "pdf");
    expect(router.state.location.search).toBe("?q=pdf");
    const table = screen.getByRole("list", { name: "Scenarios" });
    expect(within(table).getAllByRole("listitem")).toHaveLength(1);
    await user.clear(filter);
    await user.type(filter, "refnd");
    expect(screen.getByText(/No scenarios match "refnd"\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filter" }));
    expect(router.state.location.search).toBe("");
    await user.keyboard("/");
    expect(filter).toHaveFocus();
  });

  describe("states", () => {
    it("scenarios list states: shows a skeleton after 300 ms while loading", () => {
      vi.useFakeTimers();
      try {
        const { container } = renderList({ "/api/v1/scenarios": "pending" });
        expect(container.querySelector('[aria-busy="true"]')).toBeNull();
        act(() => {
          vi.advanceTimersByTime(1100);
        });
        expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
        expect(screen.getByText("Loading scenarios")).toBeInTheDocument();
      } finally {
        vi.useRealTimers();
      }
    });

    it("scenarios list states: only files that do not load", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({ items: [], problems: catalog.problems }),
      });

      expect(await screen.findByText("No scenario loads.")).toBeInTheDocument();
      expect(screen.getByRole("table", { name: "Files that do not load (1)" })).toBeInTheDocument();
    });

    it("scenarios list states: a problem with Try again", async () => {
      renderList({
        "/api/v1/scenarios": aProblem({
          status: 409,
          title: "Conflict",
          detail: "The hub registry cannot be read.",
        }),
      });

      expect(await screen.findByText("Could not load scenarios")).toBeInTheDocument();
      expect(screen.getByText("The hub registry cannot be read.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    });

    it("scenarios list states: no waiting card when the open gates cannot be read", async () => {
      renderList({ "/api/v1/approvals": aProblem({ status: 500 }) });

      const table = await screen.findByRole("list", { name: "Scenarios" });
      expect(screen.queryByRole("region", { name: "Waiting for you" })).toBeNull();
      expect(within(table).getByText("Running")).toBeInTheDocument();
    });

    it("scenarios list states: stamps the header as stale when the collector is offline", async () => {
      renderList();

      await screen.findByRole("list", { name: "Scenarios" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("scenarios list has no serious a11y violation (a11y)", async () => {
    const { container } = renderList();

    await screen.findByRole("region", { name: "Waiting for you" });
    expect(await seriousViolations(container)).toEqual([]);
  });
  it("scenarios list heads the files that do not load and draws no colored card border", async () => {
    renderList();

    expect(
      await screen.findByRole("heading", { name: "Files that do not load (1)" }),
    ).toBeInTheDocument();
    const card = screen.getByRole("region", { name: "Waiting for you" });
    expect(card.style.borderLeft).toBe("");
  });

  describe("delete scenario", () => {
    const openDelete = async (name: string) => {
      const user = userEvent.setup();
      await user.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
      await user.click(screen.getByRole("button", { name: "Delete scenario…" }));
      return user;
    };

    it("deletes a scenario from its row menu after confirming, toasts and moves focus on", async () => {
      const { requests } = renderList({
        "DELETE /api/v1/scenarios/demo/invoice-pdf": {},
      });

      const user = await openDelete("invoice-pdf");
      const dialog = screen.getByRole("alertdialog", { name: "Delete scenario invoice-pdf?" });
      expect(dialog).toHaveTextContent("scenarios/orders/invoice-pdf.yaml");
      expect(dialog).toHaveTextContent("Its recorded scenario runs stay.");
      expect(dialog).toHaveTextContent("git restore scenarios/orders/invoice-pdf.yaml");
      await user.click(within(dialog).getByRole("button", { name: "Delete scenario" }));

      expect(await screen.findByText("Deleted scenario invoice-pdf.")).toBeInTheDocument();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Copy restore command" })).toBeInTheDocument();
      const deleted = requests.find((r) => r.method === "DELETE");
      expect(new URL(deleted?.url ?? "").pathname).toBe("/api/v1/scenarios/demo/invoice-pdf");
      expect(document.activeElement).toHaveAttribute("data-row-key", "demo/refund-flow");
    });

    it("keeps the dialog open with the server's reason when the delete is refused", async () => {
      renderList({
        "DELETE /api/v1/scenarios/demo/stock-sync": aProblem({
          status: 409,
          title: "Conflict",
          detail: "the scenario path holds a link",
        }),
      });

      const user = await openDelete("stock-sync");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not delete the scenario. the scenario path holds a link Nothing was deleted.",
      );
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    });

    it("counts a scenario already gone as deleted", async () => {
      renderList({
        "DELETE /api/v1/scenarios/demo/stock-sync": aProblem({ status: 404, title: "Not found" }),
      });

      const user = await openDelete("stock-sync");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      expect(
        await screen.findByText("stock-sync was already gone from the hub folder."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });

    it("offers no delete while a scenario run of it waits for you", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(await screen.findByRole("button", { name: "Actions for order-lifecycle" }));

      expect(screen.queryByRole("button", { name: "Delete scenario…" })).toBeNull();
      expect(
        screen.getByText("A scenario run of it is in progress. Let it end or cancel it first."),
      ).toBeInTheDocument();
    });
  });
  describe("rows and menus", () => {
    const rowOf = (key: string) => {
      const row = screen.getAllByRole("listitem").find((item) => item.dataset.rowKey === key);
      if (!row) throw new Error(`no row ${key}`);
      return row;
    };

    it("scenarios list shows each row's step count, singular for one step", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({
          items: [
            aScenarioSummary({ name: "invoice-pdf", node_count: 4 }),
            aScenarioSummary({ name: "ping", node_count: 1 }),
          ],
        }),
      });

      await screen.findByRole("list", { name: "Scenarios" });
      // AC-596.1.7: the Steps column holds the count; the row's name says it in words.
      expect(rowOf("demo/invoice-pdf").querySelector(".sc-steps")).toHaveTextContent(/^4$/);
      expect(rowOf("demo/invoice-pdf").getAttribute("aria-label")).toContain("4 steps");
      expect(rowOf("demo/ping").getAttribute("aria-label")).toContain("1 step.");
    });

    it("scenarios list tags each row with its project only when several projects hold scenarios", async () => {
      const listed = renderList({
        "/api/v1/scenarios": aScenarioCatalog({
          items: [
            aScenarioSummary({ name: "invoice-pdf" }),
            aScenarioSummary({ project: "demo-shop", name: "checkout" }),
          ],
        }),
      });

      // AC-596.1.8: two projects, so each row names its own.
      await screen.findByRole("list", { name: "Scenarios" });
      expect(within(rowOf("demo/invoice-pdf")).getByTitle("Project demo")).toHaveTextContent(
        "demo",
      );
      expect(within(rowOf("demo-shop/checkout")).getByTitle("Project demo-shop")).toHaveTextContent(
        "demo-shop",
      );
      expect(within(rowOf("demo-shop/checkout")).getByTitle("Pack orders")).toBeInTheDocument();
      listed.unmount();

      // AC-596.1.8: one project, no project tag.
      renderList();
      await screen.findByRole("list", { name: "Scenarios" });
      expect(document.querySelector('[title^="Project "]')).toBeNull();
    });

    it("scenarios list puts waiting, then running, then failed rows first, each by name, with their tones", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({
          items: [
            aScenarioSummary({
              name: "alpha-done",
              last_run: aScenarioRunRef({ run_id: "a1", status: "done" }),
            }),
            aScenarioSummary({
              name: "beta-failed",
              last_run: aScenarioRunRef({ run_id: "b1", status: "failed" }),
            }),
            aScenarioSummary({
              name: "gamma-running",
              last_run: aScenarioRunRef({ run_id: "c1" }),
            }),
            aScenarioSummary({ name: "order-lifecycle", last_run: aScenarioRunRef() }),
            aScenarioSummary({
              name: "aaa-failed",
              last_run: aScenarioRunRef({ run_id: "d1", status: "failed" }),
            }),
            aScenarioSummary({ name: "aaa-never" }),
          ],
        }),
      });

      const list = await screen.findByRole("list", { name: "Scenarios" });
      // AC-596.1.9: waiting, running, failed, then the rest, each group by name.
      const rows = within(list).getAllByRole("listitem");
      expect(rows.map((row) => row.dataset.rowKey)).toEqual([
        "demo/order-lifecycle",
        "demo/gamma-running",
        "demo/aaa-failed",
        "demo/beta-failed",
        "demo/aaa-never",
        "demo/alpha-done",
      ]);
      // AC-596.1.9: waiting and failed rows carry their tone; the others none.
      expect(rows.map((row) => row.dataset.tone)).toEqual([
        "waiting",
        undefined,
        "failed",
        "failed",
        undefined,
        undefined,
      ]);
    });

    it("scenarios list says one scenario in one pack and hides the waiting part when none waits", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({ items: [aScenarioSummary()] }),
        "/api/v1/approvals": aPage([]),
      });

      await screen.findByRole("list", { name: "Scenarios" });
      // AC-596.1.10: singular forms, and no "wait for you" when nothing waits.
      expect(
        [...(document.querySelector(".ft-summary")?.children ?? [])].map(
          (part) => part.textContent,
        ),
      ).toEqual(["1 scenario", "1 pack"]);
    });

    it("scenarios list sits in a centred box capped at 1440 px and its search clears, then leaves, on Escape", async () => {
      const user = userEvent.setup();
      renderList();

      const filter = await screen.findByRole("searchbox", {
        name: "Filter scenarios by name or description",
      });
      // AC-596.1.11: the page is the sc-page box, at most 1440 px, centred.
      expect(filter.closest(".sc-page")).not.toBeNull();
      const page = ruleOf(cssOf("src/screens/scenarios/scenarios.css"), ".sc-page");
      expect(page).toMatch(/max-width: 1440px;/);
      expect(page).toMatch(/margin: 0 auto;/);

      // AC-596.1.11: '/' focuses the search; Escape clears it, then blurs it.
      await user.keyboard("/");
      expect(filter).toHaveFocus();
      await user.keyboard("pdf");
      expect(filter).toHaveValue("pdf");
      await user.keyboard("{Escape}");
      expect(filter).toHaveValue("");
      expect(filter).toHaveFocus();
      await user.keyboard("{Escape}");
      expect(filter).not.toHaveFocus();
    });

    it("scenarios list hides Steps below 1280 px, then the time below 1100 px, where the row head wraps", () => {
      const css = cssOf("src/screens/scenarios/scenarios.css");
      // AC-596.1.13: the narrower screens' rules.
      const below1280 = mediaOf(css, "(max-width: 1279px)");
      expect(below1280).toMatch(/\.sc-list \.sc-steps \{\s*display: none;/);
      expect(below1280).toMatch(/--ft-meta: 240px 28px;/);
      const below1100 = mediaOf(css, "(max-width: 1099px)");
      expect(below1100).toMatch(/\.sc-list \.sc-last-time \{\s*display: none;/);
      expect(below1100).toMatch(/\.sc-list \.ft-row-head \{\s*flex-wrap: wrap;/);
    });

    it("scenarios list opens a scenario on a row click or Enter, and its links open their own pages", async () => {
      const user = userEvent.setup();
      const { router } = renderList();

      await screen.findByRole("list", { name: "Scenarios" });
      // AC-596.1.12: a click on the row opens the scenario.
      await user.click(within(rowOf("demo/refund-flow")).getByText("No description."));
      expect(router.state.location.pathname).toBe("/scenarios/demo/refund-flow");

      await act(() => router.navigate("/scenarios"));
      // AC-596.1.12: so does Enter on the focused row.
      rowOf("demo/stock-sync").focus();
      await user.keyboard("{Enter}");
      expect(router.state.location.pathname).toBe("/scenarios/demo/stock-sync");

      await act(() => router.navigate("/scenarios"));
      // AC-596.1.12: the run id link opens the scenario run, not the scenario.
      await user.click(screen.getByRole("link", { name: "Open scenario run 9b0d1f37" }));
      expect(router.state.location.pathname).toBe("/scenarios/demo/invoice-pdf/runs/9b0d1f37");

      await act(() => router.navigate("/scenarios"));
      // AC-596.1.12: the name is a real link to the scenario.
      await user.click(screen.getByRole("link", { name: "invoice-pdf" }));
      expect(router.state.location.pathname).toBe("/scenarios/demo/invoice-pdf");
    });

    it("scenarios list row menu offers Open scenario and closes on Escape or a click outside", async () => {
      const user = userEvent.setup();
      const { router } = renderList();

      const button = await screen.findByRole("button", { name: "Actions for invoice-pdf" });
      await user.click(button);
      // AC-596.1.14: the menu offers Open scenario and Delete scenario….
      const menu = screen.getByRole("dialog", { name: "Actions for invoice-pdf" });
      expect(within(menu).getByRole("link", { name: "Open scenario" })).toHaveAttribute(
        "href",
        "/scenarios/demo/invoice-pdf",
      );
      expect(within(menu).getByRole("button", { name: "Delete scenario…" })).toBeInTheDocument();

      // AC-596.1.14: Escape closes it and focus goes back to its button.
      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog", { name: "Actions for invoice-pdf" })).toBeNull();
      expect(button).toHaveFocus();
      expect(button).toHaveAttribute("aria-expanded", "false");

      // AC-596.1.14: a click outside closes it, and opens nothing.
      await user.click(button);
      expect(screen.getByRole("dialog", { name: "Actions for invoice-pdf" })).toBeInTheDocument();
      await user.click(screen.getByRole("heading", { name: "Scenarios", level: 1 }));
      expect(screen.queryByRole("dialog", { name: "Actions for invoice-pdf" })).toBeNull();
      expect(router.state.location.pathname).toBe("/scenarios");

      // AC-596.1.14: Open scenario goes to the scenario.
      await user.click(button);
      await user.click(screen.getByRole("link", { name: "Open scenario" }));
      expect(router.state.location.pathname).toBe("/scenarios/demo/invoice-pdf");
    });
  });

  describe("delete scenario (more)", () => {
    const openDelete = async (name: string) => {
      const user = userEvent.setup();
      await user.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
      await user.click(screen.getByRole("button", { name: "Delete scenario…" }));
      return user;
    };

    it("scenarios list confirm says the actions stay and gives the git restore command", async () => {
      renderList();

      await openDelete("refund-flow");
      const dialog = screen.getByRole("alertdialog", { name: "Delete scenario refund-flow?" });
      // AC-596.1.15: what goes, what stays and how to get it back.
      expect(dialog).toHaveTextContent(
        "This removes scenarios/payments/refund-flow.yaml from the demo hub folder.",
      );
      expect(dialog).toHaveTextContent("Its recorded scenario runs stay.");
      expect(dialog).toHaveTextContent("The actions it calls in actions/payments/ stay.");
      expect(
        within(dialog).getByText("git restore scenarios/payments/refund-flow.yaml"),
      ).toHaveClass("ah-mono");
    });

    it("scenarios list moves focus to the previous row after deleting the last one", async () => {
      renderList({ "DELETE /api/v1/scenarios/demo/stock-sync": {} });

      const user = await openDelete("stock-sync");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      // AC-596.1.15: no next row, so the previous one.
      expect(await screen.findByText("Deleted scenario stock-sync.")).toBeInTheDocument();
      await vi.waitFor(() => {
        expect(document.activeElement).toHaveAttribute("data-row-key", "demo/refund-flow");
      });
    });

    it("scenarios list moves focus to the filter after deleting its only scenario", async () => {
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({ items: [aScenarioSummary({ name: "ping" })] }),
        "/api/v1/approvals": aPage([]),
        "DELETE /api/v1/scenarios/demo/ping": {},
      });

      const user = await openDelete("ping");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      // AC-596.1.15: no other row, so the filter.
      expect(await screen.findByText("Deleted scenario ping.")).toBeInTheDocument();
      await vi.waitFor(() => {
        expect(
          screen.getByRole("searchbox", { name: "Filter scenarios by name or description" }),
        ).toHaveFocus();
      });
    });

    it("scenarios list hides the deleted toast after 6 s", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderList({ "DELETE /api/v1/scenarios/demo/stock-sync": {} });
        const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
        await user.click(await screen.findByRole("button", { name: "Actions for stock-sync" }));
        await user.click(screen.getByRole("button", { name: "Delete scenario…" }));
        await user.click(screen.getByRole("button", { name: "Delete scenario" }));

        // AC-596.1.15: the toast shows, then goes after 6 s.
        expect(await screen.findByText("Deleted scenario stock-sync.")).toBeInTheDocument();
        act(() => {
          vi.advanceTimersByTime(5900);
        });
        expect(screen.getByText("Deleted scenario stock-sync.")).toBeInTheDocument();
        act(() => {
          vi.advanceTimersByTime(200);
        });
        expect(screen.queryByText("Deleted scenario stock-sync.")).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it("scenarios list says deleting is locked in this browser when the server answers 401", async () => {
      renderList({
        "DELETE /api/v1/scenarios/demo/stock-sync": aProblem({
          status: 401,
          title: "Unauthorized",
        }),
      });

      const user = await openDelete("stock-sync");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      // AC-596.1.16: the locked copy with the ?token=… hint, and the dialog stays.
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Deleting is locked in this browser. Open the link hub web printed when it started (it ends with ?token=…) once in this browser.",
      );
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    });

    it("scenarios list offers no restore command for a scenario already gone", async () => {
      renderList({
        "DELETE /api/v1/scenarios/demo/stock-sync": aProblem({ status: 404, title: "Not found" }),
      });

      const user = await openDelete("stock-sync");
      await user.click(screen.getByRole("button", { name: "Delete scenario" }));

      // AC-596.1.17: already gone, so nothing to restore.
      expect(
        await screen.findByText("stock-sync was already gone from the hub folder."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Copy restore command" })).toBeNull();
    });

    it("scenarios list offers no delete while a scenario run of it is running", async () => {
      const user = userEvent.setup();
      renderList({
        "/api/v1/scenarios": aScenarioCatalog({
          items: [aScenarioSummary({ name: "ping", last_run: aScenarioRunRef({ run_id: "c1" }) })],
        }),
        "/api/v1/approvals": aPage([]),
      });

      await user.click(await screen.findByRole("button", { name: "Actions for ping" }));

      // AC-596.1.18: running, not waiting: Delete scenario… is off too.
      expect(screen.queryByRole("button", { name: "Delete scenario…" })).toBeNull();
      expect(
        screen.getByText("A scenario run of it is in progress. Let it end or cancel it first."),
      ).toBeInTheDocument();
    });
  });
});
