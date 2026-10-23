import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fmtDateTime } from "../../lib/format";

import { seriousViolations } from "../../testing/axe";
import {
  aFeatureDetail,
  aFeatureTickets,
  aPage,
  aSession,
  aTicketFlow,
  aTicketRow,
  anAcRow,
  anEvalRecord,
  renderWithApi,
  type FeatureTickets,
} from "../../testing/builders";
import { FeatureDetailScreen } from "./index";
import { TicketsTab } from "./TicketsTab";

type EvalRecord = ReturnType<typeof anEvalRecord>;

/** The three tickets of `control-plane`, each with its own steps (AGH-202 at Review). */
function tickets(): FeatureTickets {
  const data = aFeatureTickets();
  return {
    ...data,
    tickets: data.tickets.map((row) => ({
      ...row,
      flow: aTicketFlow(
        row.ref === "AGH-202"
          ? {
              steps: aTicketFlow().steps.map((step) =>
                step.name === "review"
                  ? { ...step, state: "current", meta: "Changes requested" }
                  : step,
              ),
            }
          : {},
      ),
    })),
  };
}

function show(path: string, evals: EvalRecord[] = []) {
  return renderWithApi(
    <TicketsTab
      project="agent-hub"
      slug="control-plane"
      data={tickets()}
      error={null}
      onRefresh={() => undefined}
      acPasses={{ "AC-200.4": true }}
      evals={evals}
      openerRef={{ current: null }}
    />,
    {
      routes: {
        "/api/v1/sessions": aPage([aSession({ issue: "AGH-202" })]),
      },
      path,
    },
  );
}

/** AGH-202's eval, waiting on owner steps. */
const WAITING = anEvalRecord({
  delivery: "agh-202",
  path: "features/control-plane/evals/agh-202.md",
  verdict: "SHIP-WITH-OWNER-STEPS",
  tickets: ["AGH-202"],
  evaluated_at: "2026-10-11T10:00:00Z",
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function panel(): HTMLElement {
  return screen.getByRole("complementary", { name: /^Ticket AGH-/ });
}

describe("TicketPanel (AC-1.10)", () => {
  it("AC-1.10 opens with ?ticket=<id> (replace) from a card title", async () => {
    const { router } = show("/?doc=tickets");

    const title = screen.getByRole("link", { name: "Serve the ticket summaries" });
    expect(title).toHaveAttribute("href", "/?doc=tickets&ticket=AGH-202");
    await userEvent.click(title);

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202");
    expect(router.state.historyAction).toBe("REPLACE");
    expect(panel()).toHaveAccessibleName("Ticket AGH-202 · Serve the ticket summaries");
    expect(within(panel()).getByRole("heading", { level: 2 })).toHaveFocus();
  });

  it("AC-1.10 opens from a table row on Enter and o, the body one tab stop moved by j and k", async () => {
    const { router } = show("/?doc=tickets&tickets=table");

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => row.tabIndex)).toEqual([0, -1, -1]);
    rows[0]?.focus();
    await userEvent.keyboard("j");
    expect(rows[1]).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(router.state.location.search).toBe("?doc=tickets&tickets=table&ticket=AGH-202");
    expect(panel()).toHaveAccessibleName("Ticket AGH-202 · Serve the ticket summaries");

    rows[1]?.focus();
    await userEvent.keyboard("j");
    await userEvent.keyboard("o");
    expect(panel()).toHaveAccessibleName("Ticket AGH-203 · Show the planning view");
    rows[2]?.focus();
    await userEvent.keyboard("k");
    expect(rows[1]).toHaveFocus();
  });

  it("AC-425.5 has no header ticket chip; the panel opens from the Tickets tab and closes with another tab", async () => {
    const API = "/api/v1/features/agent-hub/control-plane";
    const { router } = renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({ issues: ["AGH-201", "AGH-202", "AGH-203"] }),
        [`${API}/tickets`]: tickets(),
        "/api/v1/sessions": aPage([]),
      },
      path: "/features/agent-hub/control-plane?doc=tickets",
      route: "features/:project/:slug",
    });

    const title = await screen.findByRole("link", { name: "Serve the ticket summaries" });
    expect(screen.queryByRole("group", { name: "Tickets of this feature" })).toBeNull();
    await userEvent.click(title);

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202");
    expect(await screen.findByRole("complementary", { name: /^Ticket AGH-202/ })).toBeVisible();

    // Switching tab closes the panel and drops ticket=.
    await userEvent.click(screen.getByRole("tab", { name: "Eval" }));
    expect(screen.queryByRole("complementary", { name: /^Ticket/ })).toBeNull();
    expect(router.state.location.search).not.toContain("ticket=");
  });

  it("AC-1.10 shows the seven steps with the current one disclosed, its ACs, blockers and sessions", async () => {
    show("/?doc=tickets&ticket=AGH-202");

    const steps = within(panel()).getByRole("list", { name: "Steps" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(7);
    expect(
      within(steps).getByRole("button", { name: /^Review, in progress, changes requested/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(within(steps).getByRole("button", { name: /^Context, not recorded/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    // The open step's evidence is in one card under the list, not inside it.
    expect(steps).not.toHaveTextContent("Open the review record in Brain");
    const card = within(panel()).getByRole("region", { name: /Review/ });
    expect(card).toHaveAccessibleName("Review · step 4 of 7");
    expect(card).toHaveTextContent("Open the review record in Brain");
    expect(panel()).toHaveTextContent("1/1 ACs passing");
    expect(within(panel()).getByRole("link", { name: /^AGH-201\b/ })).toBeInTheDocument();
    expect(within(panel()).getByRole("link", { name: /^AGH-203\b/ })).toBeInTheDocument();
    expect(await within(panel()).findByTitle(/^Open the session/)).toBeVisible();
    // Start stays on the card or row, once per view (A15).
    expect(within(panel()).queryByRole("button", { name: /Start/ })).toBeNull();
  });

  it("AC-1.10 Esc closes it and returns focus to the opener", async () => {
    const { router } = show("/?doc=tickets");
    const title = screen.getByRole("link", { name: "Serve the ticket summaries" });
    await userEvent.click(title);

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("complementary")).toBeNull();
    expect(router.state.location.search).toBe("?doc=tickets");
    expect(screen.getByRole("link", { name: "Serve the ticket summaries" })).toHaveFocus();
  });

  it("AC-1.10 ?ticket= naming no ticket shows '<id> is not a ticket of this feature.'", () => {
    show("/?doc=tickets&ticket=AGH-999");

    expect(
      within(screen.getByRole("complementary")).getByText(
        "AGH-999 is not a ticket of this feature.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close panel" })).toBeInTheDocument();
  });

  // AGH-330 Q6, Q7: an epic is the plan's, children or not; Close panel returns focus.
  it("AC-1.10 names the feature's epic by the plan, keeps its Linear link, Close panel restores focus", async () => {
    const data = tickets();
    const epic = aTicketRow({
      ref: "AGH-9",
      id: "AGH-9",
      key: "T0",
      url: "https://linear.app/demo/issue/AGH-9",
      blocked_by: [],
      blocks: [],
      readiness: "epic",
      children: [],
    });
    const opener = document.createElement("button");
    document.body.append(opener);
    renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="control-plane"
        data={{
          ...data,
          tickets: [...data.tickets, epic],
          planning: { ...data.planning, epics: ["AGH-9"] },
        }}
        error={null}
        onRefresh={() => undefined}
        evals={[]}
        openerRef={{ current: opener }}
      />,
      { routes: { "/api/v1/sessions": aPage([]) }, path: "/?doc=tickets&ticket=AGH-9" },
    );

    const aside = screen.getByRole("complementary");
    expect(aside).toHaveTextContent("AGH-9 is this feature's epic");
    expect(within(aside).getByRole("link", { name: /^AGH-9/ })).toHaveAttribute(
      "href",
      "https://linear.app/demo/issue/AGH-9",
    );
    await userEvent.click(within(aside).getByRole("button", { name: "Close panel" }));
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(opener).toHaveFocus();
    opener.remove();
  });

  it("AC-1.10 switches ticket in place when another card or a blocker is activated", async () => {
    const { router } = show("/?doc=tickets&ticket=AGH-202");

    await userEvent.click(screen.getByRole("link", { name: "Show the planning view" }));
    expect(panel()).toHaveAccessibleName("Ticket AGH-203 · Show the planning view");
    // Its "Blocked by" link (the readiness line's link points at the card instead).
    const blocker = within(panel())
      .getAllByRole("link", { name: /^AGH-202\b/ })
      .find((link) => link.dataset.ticketOpen === "AGH-202");
    if (!blocker) throw new Error("no Blocked by link");
    await userEvent.click(blocker);
    expect(panel()).toHaveAccessibleName("Ticket AGH-202 · Serve the ticket summaries");
    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202");
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
  });

  it("AC-1.10 points to the Eval tab when a ticket eval waits on owner steps (its one signal)", () => {
    show("/?doc=tickets&ticket=AGH-202", [
      anEvalRecord({
        delivery: "agh-202",
        path: "features/control-plane/evals/agh-202.md",
        verdict: "SHIP-WITH-OWNER-STEPS",
        tickets: ["AGH-202"],
      }),
    ]);

    expect(panel()).toHaveTextContent("Waiting for you: Eval 1 passed with owner steps");
    expect(
      within(panel()).getByRole("link", { name: "Settle them in the Eval tab" }),
    ).toHaveAttribute("href", "/?doc=eval&eval=agh-202");
  });

  // Structure, names and roles (A16): theme contrast is tokens.test.ts's.
  it("AC-1.10 has no serious axe violation, overlaid and docked, Flow and Table (a11y)", async () => {
    for (const width of [1280, 1600]) {
      vi.stubGlobal("matchMedia", (query: string) => ({
        matches: width >= 1600 && query === "(min-width: 1600px)",
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }));
      for (const view of ["", "&tickets=table"]) {
        const { container, unmount } = show(`/?doc=tickets${view}&ticket=AGH-202`);
        expect(await seriousViolations(container)).toEqual([]);
        unmount();
      }
    }
    // Four axe runs (two widths, two views): past 5 s when the fast gate runs its lanes at once.
  }, 20_000);

  // AGH-330 F5: the signal lands on its eval's group row.
  it("AC-1.10 lands the signal's link on the eval's group row in the Eval tab", async () => {
    const API = "/api/v1/features/agent-hub/control-plane";
    renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({
          issues: ["AGH-201", "AGH-202", "AGH-203"],
          evals: [WAITING],
        }),
        [`${API}/tickets`]: tickets(),
        "/api/v1/sessions": aPage([]),
      },
      path: "/features/agent-hub/control-plane?doc=tickets&ticket=AGH-202",
      route: "features/:project/:slug",
    });

    await userEvent.click(await screen.findByRole("link", { name: "Settle them in the Eval tab" }));

    expect(await screen.findByRole("button", { name: /^AGH-202\b.*1 eval/ })).toHaveFocus();
    // Long under the fast gate's parallel lanes, as the panel's axe test is.
  }, 20_000);

  // AGH-330 F8: the Eval step's date reads as the page writes date-times.
  it("AC-1.10 dates the Eval step as the page does", () => {
    show("/?doc=tickets&ticket=AGH-202&step=eval", [WAITING]);

    expect(panel()).toHaveTextContent(fmtDateTime(WAITING.evaluated_at ?? "", "local"));
  });
});

describe("TicketPanel layout (ux-change-ticket-panel)", () => {
  /** AGH-202 with `overrides`, the other two tickets as `tickets()` has them. */
  function showWith(
    overrides: Partial<FeatureTickets["tickets"][number]>,
    path: string,
    extra: {
      planning?: Partial<FeatureTickets["planning"]>;
      acPasses?: Record<string, boolean>;
      acRows?: ReturnType<typeof anAcRow>[];
      sessions?: ReturnType<typeof aSession>[];
    } = {},
  ) {
    const data = tickets();
    return renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="control-plane"
        data={{
          ...data,
          tickets: data.tickets.map((row) =>
            row.ref === "AGH-202" ? { ...row, ...overrides } : row,
          ),
          planning: { ...data.planning, ...extra.planning },
        }}
        error={null}
        onRefresh={() => undefined}
        acPasses={extra.acPasses ?? { "AC-200.4": true }}
        acRows={extra.acRows}
        evals={[]}
        openerRef={{ current: null }}
      />,
      {
        routes: { "/api/v1/sessions": aPage(extra.sessions ?? []) },
        path,
      },
    );
  }

  it("heads the panel with the id line, the title and the facts row", () => {
    show("/?doc=tickets&ticket=AGH-202");

    const heading = within(panel()).getByRole("heading", { level: 2 });
    expect(heading).toHaveAccessibleName("Ticket AGH-202 · Serve the ticket summaries");
    expect(heading.querySelector(".ah-ticket-panel-id")).toHaveTextContent("AGH-202");
    expect(heading.querySelector(".ah-ticket-panel-title")).toHaveTextContent(
      "Serve the ticket summaries",
    );
    const facts = panel().querySelector(".ah-ticket-panel-facts");
    if (!(facts instanceof HTMLElement)) throw new Error("no facts row");
    expect(facts).toHaveTextContent("In Progress");
    expect(within(facts).getByRole("link", { name: /^AGH-202/ })).toHaveAttribute(
      "href",
      "https://linear.app/demo/issue/AGH-202",
    );
    expect(facts).toHaveTextContent("Assignee: Ada Example");
    // AGH-202 heads the critical path (AGH-202 → AGH-203).
    expect(within(facts).getByText("Critical path")).toHaveAttribute(
      "title",
      "On the longest chain of tickets not done",
    );
  });

  it("shows the callout only when something waits on the owner, never as a live region", () => {
    const { unmount } = show("/?doc=tickets&ticket=AGH-202");
    expect(panel().querySelector(".ah-banner")).toBeNull();
    unmount();

    show("/?doc=tickets&ticket=AGH-202", [WAITING]);
    const line = within(panel()).getByText("Waiting for you: Eval 1 passed with owner steps");
    const callout = line.closest(".ah-banner");
    expect(callout).not.toBeNull();
    expect(callout).not.toHaveAttribute("role");
    expect(within(panel()).queryByRole("status")).toBeNull();
    expect(callout).toContainElement(
      within(panel()).getByRole("link", { name: "Settle them in the Eval tab" }),
    );
  });

  it("names the card region from every step button, and the card follows ?step= back to the current step", async () => {
    const { router } = show("/?doc=tickets&ticket=AGH-202&step=eval");

    const steps = within(panel()).getByRole("list", { name: "Steps" });
    expect(steps).toHaveAttribute("data-orientation", "horizontal");
    const card = within(panel()).getByRole("region", { name: "Eval · step 5 of 7" });
    expect(card).not.toHaveTextContent("Current step");
    expect(card).toHaveTextContent("Not reached");
    const region = card.parentElement;
    for (const button of within(steps).getAllByRole("button")) {
      expect(button).toHaveAttribute("aria-controls", region?.id);
    }

    await userEvent.click(
      within(card).getByRole("button", { name: "Show the current step (Review)" }),
    );

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202&step=review");
    const current = within(panel()).getByRole("region", { name: "Review · step 4 of 7" });
    expect(current).toHaveTextContent("Current step · Review · step 4 of 7");
    expect(current).toHaveTextContent("In progress");
    // The outcome is said once: the detail no longer opens with it.
    expect(current.querySelector(".ah-ticket-step-outcome")).toHaveTextContent("Changes requested");
    expect(current.querySelector(".ah-ticket-step-detail")).toHaveTextContent(
      /^Open the review record in Brain$/,
    );
    // The readiness line, on the current step only.
    expect(current.querySelector(".ah-ticket-step-ready")).toHaveTextContent("Can start now");
    await vi.waitFor(() => {
      expect(within(steps).getByRole("button", { name: /^Review,/ })).toHaveFocus();
    });

    // The open step clicked again closes it: the stepper alone.
    await userEvent.click(within(steps).getByRole("button", { name: /^Review,/ }));
    expect(within(panel()).queryByRole("region", { name: /step 4 of 7/ })).toBeNull();
  });

  it("lists the ACs with their state in words, the open work first, past six folded", () => {
    const ids = ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-6", "AC-7", "AC-8"];
    showWith({ acs: ids }, "/?doc=tickets&ticket=AGH-202", {
      acRows: [
        anAcRow({ id: "AC-1", passes: true }),
        anAcRow({
          id: "AC-2",
          passes: false,
          manual: true,
          description: "Given an owner, when it signs off, then the step settles",
        }),
        anAcRow({ id: "AC-3", passes: false }),
        ...ids.slice(3).map((id) => anAcRow({ id, passes: true })),
      ],
      acPasses: Object.fromEntries(ids.map((id) => [id, !["AC-2", "AC-3"].includes(id)])),
    });

    const section = within(panel()).getByRole("region", { name: "Acceptance criteria" });
    expect(section).toHaveTextContent("6/8 ACs passing");
    const rows = [...section.querySelectorAll(".ah-ticket-ac-row")] as HTMLElement[];
    expect(rows).toHaveLength(8);
    expect(rows.slice(0, 3).map((row) => row.textContent)).toEqual([
      expect.stringMatching(/^Not passingAC-3/),
      expect.stringMatching(/^Owner stepAC-2.*the step settles$/),
      expect.stringMatching(/^PassesAC-1/),
    ]);
    const fold = within(section).getByText("Show 2 more ACs");
    expect(fold.tagName).toBe("SUMMARY");
    expect(fold.closest("details")).toContainElement(rows[7] ?? null);
  });

  it("says when no AC names the ticket", () => {
    showWith({ acs: [] }, "/?doc=tickets&ticket=AGH-202");

    expect(within(panel()).getByRole("region", { name: "Acceptance criteria" })).toHaveTextContent(
      "No AC names this ticket.",
    );
  });

  it("lists the dependencies as rows with their status, done last, an outside blocker with its title", () => {
    showWith(
      {
        blocked_by: [
          { ref: "AGH-201", source: "both" },
          { ref: "OPS-7", source: "linear" },
        ],
      },
      "/?doc=tickets&ticket=AGH-202",
      {
        planning: {
          external_blockers: [
            {
              id: "OPS-7",
              title: "Rotate the deploy keys",
              state: { name: "In Review", type: "started" },
              done: false,
              url: "https://linear.app/demo/issue/OPS-7",
            },
          ],
        },
      },
    );

    const section = within(panel()).getByRole("region", { name: "Dependencies" });
    expect(section).toHaveTextContent("Blocked by · 1 of 2 not done");
    expect(section).toHaveTextContent("Blocks · 1, none started");
    const rows = [...section.querySelectorAll(".ah-ticket-dep-row")] as HTMLElement[];
    // Not done first: the outside issue, then AGH-201 (Done), then what it blocks.
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringMatching(/^In ReviewOPS-7.*Rotate the deploy keys$/),
      expect.stringMatching(/^DoneAGH-201 Collect the events$/),
      expect.stringMatching(/^TodoAGH-203 Show the planning view$/),
    ]);
    expect(rows[1]).toHaveAttribute("title", "In the plan and in Linear");
    const link = within(rows[1] ?? section).getByRole("link");
    expect(link).toHaveAccessibleName("AGH-201 Collect the events");
    expect(link.dataset.ticketOpen).toBe("AGH-201");
    expect(within(rows[0] ?? section).getByRole("link", { name: /^OPS-7/ })).toHaveAttribute(
      "href",
      "https://linear.app/demo/issue/OPS-7",
    );
  });

  it("lists the sessions as rows with their turns and cost", async () => {
    showWith({}, "/?doc=tickets&ticket=AGH-202", {
      sessions: [aSession({ issue: "AGH-202", turns: 41, cost_usd: "3.2" })],
    });

    const section = within(panel()).getByRole("region", { name: "Sessions" });
    const link = await within(section).findByTitle(/^Open the session/);
    expect(link).toHaveTextContent("41 turns");
    expect(link).toHaveTextContent("$3.20");
    expect(section.querySelector(".ah-ticket-panel-section-head")).toHaveTextContent("Sessions1");
  });

  it("says when no session names the ticket", async () => {
    showWith({}, "/?doc=tickets&ticket=AGH-202");

    expect(
      await within(panel()).findByText("No session's branch or run names AGH-202."),
    ).toBeInTheDocument();
  });

  it("falls back to the vertical steps in a panel narrower than 400 px", () => {
    // jsdom does not lay out: the fallback is read from the sheet.
    const sheet = readFileSync(
      join(process.cwd(), "src/screens/feature-detail/ticket-panel.css"),
      "utf8",
    );
    expect(sheet).toMatch(/\.ah-ticket-panel \{[^}]*container: ticket-panel \/ inline-size;/);
    expect(sheet).toMatch(
      /@container ticket-panel \(max-width: 399px\) \{\s*\.ah-golden\[data-orientation="horizontal"\]\[data-detail="below"\] \{\s*flex-direction: column;/,
    );
    show("/?doc=tickets&ticket=AGH-202");
    expect(panel().querySelector(".ah-ticket-panel")).toContainElement(
      within(panel()).getByRole("list", { name: "Steps" }),
    );
  });
});
