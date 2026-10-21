import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aFeatureDetail,
  aFeatureTickets,
  aPage,
  aSession,
  aTicketFlow,
  aTicketRow,
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

  it("AC-1.10 opens from a header ticket chip, on the Tickets tab", async () => {
    const API = "/api/v1/features/agent-hub/control-plane";
    const { router } = renderWithApi(<FeatureDetailScreen />, {
      routes: {
        [API]: aFeatureDetail({ issues: ["AGH-201", "AGH-202", "AGH-203"] }),
        [`${API}/tickets`]: tickets(),
        "/api/v1/sessions": aPage([]),
      },
      path: "/features/agent-hub/control-plane?doc=acs",
      route: "features/:project/:slug",
    });

    const chips = await screen.findByRole("group", { name: "Tickets of this feature" });
    const chip = within(chips).getByRole("link", { name: "AGH-202" });
    expect(chip).toHaveAccessibleDescription(/AGH-202 · .*show its steps$/);
    await userEvent.click(chip);

    expect(router.state.location.search).toBe("?doc=tickets&ticket=AGH-202");
    expect(await screen.findByRole("complementary", { name: /^Ticket AGH-202/ })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Tickets/ })).toHaveAttribute("aria-selected", "true");

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
    expect(steps).toHaveTextContent("Open the review record in Brain");
    expect(panel()).toHaveTextContent("1/1 ACs passing");
    expect(within(panel()).getByRole("link", { name: "AGH-201" })).toBeInTheDocument();
    expect(within(panel()).getByRole("link", { name: "AGH-203" })).toBeInTheDocument();
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
      .getAllByRole("link", { name: "AGH-202" })
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

    expect(panel()).toHaveTextContent("Waiting on you: Eval 1 passed with owner steps");
    expect(
      within(panel()).getByRole("link", { name: "Settle them in the Eval tab" }),
    ).toHaveAttribute("href", "/?doc=eval&eval=agh-202");
  });

  // Structure, names and roles (A16): theme contrast is tokens.test.ts's.
  it("AC-1.10 has no serious axe violation, overlaid and docked, Flow and Table (a11y)", async () => {
    {
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
      vi.unstubAllGlobals();
    }
  });
});
