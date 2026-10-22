import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aFeatureTickets, aTicketFlow, aTicketPlan, aTicketRow } from "../../testing/builders";
import { PlanningView, splitTitle, ticketAnchor } from "./PlanningView";

const rows = ["T1", "T2", "T3", "T4", "T5"].map((ref) =>
  aTicketRow({ ref, key: ref, id: null, title: `Ticket ${ref}`, url: null }),
);

const plan = aTicketPlan({
  layers: [["T1", "T2", "T4"], ["T3"], ["T5"]],
  can_start: ["T1", "T2", "T4"],
  order: ["T1", "T2", "T4", "T3", "T5"],
  waiting: ["T3", "T5"],
  critical_path: ["T1", "T3", "T5"],
});

/** The `index`th item, failing the test when there is none. */
function nth<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`no item ${String(index)}`);
  return item;
}

describe("PlanningView", () => {
  it("heads the flow with the epic and its children's progress, never as a step", () => {
    const epic = aTicketRow({
      ref: "ACME-1",
      key: "T0",
      id: "ACME-1",
      title: "The epic",
      url: null,
      readiness: "epic",
      state: { name: "Backlog", type: "backlog" },
      acs: [],
      blocked_by: [],
      children: ["ACME-2", "ACME-3"],
    });
    const child = (ref: string, readiness: "done" | "in_progress") =>
      aTicketRow({
        ref,
        key: ref,
        id: ref,
        title: `Child ${ref}`,
        url: null,
        readiness,
        blocked_by: [],
        acs: [`AC-${ref}`],
        parent: "ACME-1",
      });
    render(
      <PlanningView
        tickets={[epic, child("ACME-2", "done"), child("ACME-3", "in_progress")]}
        planning={aTicketPlan({
          layers: [["ACME-3"]],
          can_start: [],
          order: ["ACME-3"],
          waiting: [],
          critical_path: ["ACME-3"],
          epics: ["ACME-1"],
        })}
        acPasses={{ "AC-ACME-2": true, "AC-ACME-3": false }}
      />,
    );

    const card = screen.getByRole("region", { name: "Epic ACME-1 · The epic" });
    expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    expect(card).toHaveTextContent("1/2 child tickets done");
    expect(card).toHaveTextContent("1 in progress");
    expect(card).toHaveTextContent("1/2 ACs passing");
    const flow = screen.getByRole("group", { name: "Ticket flow" });
    expect(within(flow).queryByRole("listitem", { name: /ACME-1 ·/ })).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Tickets by readiness" })).not.toHaveTextContent(
      "epic",
    );
  });

  it("draws each parallel group as a column, left to right (flow)", () => {
    render(<PlanningView tickets={rows} planning={plan} />);

    expect(screen.getByRole("heading", { name: "Ticket flow" })).toBeInTheDocument();
    const steps = within(screen.getByRole("group", { name: "Ticket flow" })).getAllByRole("region");
    expect(steps.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Group 1 · in parallel",
      "Group 2 · after group 1",
      "Group 3 · after group 2",
    ]);
    expect(
      within(nth(steps, 0))
        .getAllByRole("listitem")
        .map((li) => li.getAttribute("aria-label")),
    ).toEqual(["T1 · Ticket T1", "T2 · Ticket T2", "T4 · Ticket T4"]);
    expect(screen.getByRole("listitem", { name: "T3 · Ticket T3" })).toHaveTextContent(
      "Critical path",
    );
    // The card is where the flow's ticket links lead (the table is the other view, AC-1.11).
    expect(screen.getByRole("listitem", { name: "T1 · Ticket T1" })).toHaveAttribute(
      "id",
      ticketAnchor("T1"),
    );
    expect(screen.queryByRole("link", { name: "Ticket T1" })).not.toBeInTheDocument();
  });

  it("keeps a done ticket in its group, so the groups after it do not move (flow)", () => {
    const first = aTicketRow({
      ref: "T1",
      key: "T1",
      id: null,
      title: "Ticket T1",
      url: null,
      readiness: "done",
      state: { name: "Done", type: "completed" },
      blocked_by: [],
    });
    const second = aTicketRow({
      ref: "T2",
      key: "T2",
      id: null,
      title: "Ticket T2",
      url: null,
      readiness: "in_progress",
      blocked_by: [{ ref: "T1", source: "both" }],
    });
    const canceled = aTicketRow({
      ref: "T3",
      key: "T3",
      id: null,
      title: "Ticket T3",
      url: null,
      readiness: "canceled",
      blocked_by: [],
    });
    render(
      <PlanningView
        tickets={[first, second, canceled]}
        planning={aTicketPlan({
          layers: [["T2"]],
          can_start: [],
          order: ["T2"],
          waiting: [],
          critical_path: ["T2"],
        })}
      />,
    );

    const steps = within(screen.getByRole("group", { name: "Ticket flow" })).getAllByRole("region");
    expect(steps.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Group 1 · done",
      "Group 2 · after group 1",
      "Done · settled",
    ]);
    expect(nth(steps, 0)).toHaveAttribute("data-kind", "done");
    expect(within(nth(steps, 0)).getByRole("listitem", { name: "T1 · Ticket T1" })).toHaveAttribute(
      "data-readiness",
      "done",
    );
    expect(
      within(nth(steps, 1)).getByRole("listitem", { name: "T2 · Ticket T2" }),
    ).toBeInTheDocument();
    expect(
      within(nth(steps, 2)).getByRole("listitem", { name: "T3 · Ticket T3" }),
    ).toBeInTheDocument();
  });

  it("shows a started ticket as in progress, never as can start (flow)", () => {
    const started = rows.map((row) =>
      row.ref === "T1"
        ? {
            ...row,
            readiness: "in_progress" as const,
            state: { name: "In Review", type: "started" as const },
          }
        : row,
    );
    render(<PlanningView tickets={started} planning={{ ...plan, can_start: ["T2", "T4"] }} />);

    const card = screen.getByRole("listitem", { name: "T1 · Ticket T1" });
    expect(card).toHaveAttribute("data-readiness", "in_progress");
    expect(card).toHaveTextContent("In Review");
    // The badge says the status; the card does not repeat it as readiness.
    expect(card).not.toHaveTextContent("In progress");
    expect(card).not.toHaveTextContent("Can start now");
    expect(screen.getByRole("list", { name: "Tickets by readiness" })).toHaveTextContent(
      "1 in progress",
    );
  });

  it("shows a banner for a cycle and for blockers outside the feature (planning)", () => {
    render(
      <PlanningView
        tickets={rows}
        planning={aTicketPlan({
          layers: [["T4"]],
          can_start: ["T4"],
          order: ["T4"],
          cycles: [["T1", "T2"]],
          external_blockers: [
            {
              id: "ACME-9",
              title: "Upgrade the runtime",
              state: { name: "In Progress", type: "started" },
              url: "https://linear.app/demo/issue/ACME-9",
              done: false,
            },
            { id: "ACME-8", title: null, state: null, url: null, done: false },
            {
              id: "ACME-7",
              title: "Done elsewhere",
              state: { name: "Done", type: "completed" },
              url: "javascript:x",
              done: true,
            },
          ],
          warnings: ["ACME-5 has more than 50 relations; the first 50 were read."],
        })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Dependency cycle: T1 → T2.");
    const outside = screen.getByText("Blocked from outside this feature:").closest("[role=status]");
    expect(outside).toHaveTextContent("Upgrade the runtime · In Progress (not done)");
    expect(outside).toHaveTextContent("ACME-8 · status unknown");
    expect(outside).toHaveTextContent("ACME-7 · Done elsewhere · done");
    expect(within(outside as HTMLElement).getAllByRole("link")).toHaveLength(1);
    expect(screen.getByText(/more than 50 relations/)).toBeInTheDocument();
  });

  it("says when there is no ticket to show (flow states)", () => {
    render(
      <PlanningView
        tickets={[]}
        planning={aTicketPlan({
          layers: [],
          can_start: [],
          order: [],
          waiting: [],
          critical_path: [],
        })}
      />,
    );

    expect(screen.getByText("No ticket to show.")).toBeInTheDocument();
  });

  it("draws an edge from each blocker to the ticket it holds back (flow graph)", () => {
    const linked = rows.map((row) => {
      if (row.ref === "T3") {
        return {
          ...row,
          blocked_by: [
            { ref: "T1", source: "both" as const },
            { ref: "T2", source: "plan" as const },
          ],
        };
      }
      if (row.ref === "T5") {
        return {
          ...row,
          readiness: "in_progress" as const,
          blocked_by: [{ ref: "T3", source: "linear" as const }],
          waiting_on: ["T3"],
        };
      }
      return row;
    });
    const { container } = render(<PlanningView tickets={linked} planning={plan} />);

    const edge = (id: string) => container.querySelector(`[data-edge="${id}"]`);
    expect(edge("T1→T3")).toHaveAttribute("data-critical", "true");
    expect(edge("T2→T3")).toHaveAttribute("data-source", "plan");
    expect(edge("T2→T3")).not.toHaveAttribute("data-critical");
    expect(edge("T3→T5")).toHaveAttribute("data-early", "true");
    // A blocker drawn as an edge is not repeated in words on the card.
    expect(screen.getByRole("listitem", { name: "T3 · Ticket T3" })).not.toHaveTextContent(
      /after/i,
    );
  });

  it("says on a card only what its readiness adds to the Linear status (card)", () => {
    const cards = [
      aTicketRow({
        ref: "R1",
        key: "R1",
        id: "AGH-1",
        title: "Reviewed one",
        readiness: "waiting",
        waiting_on: [],
        reviewed: true,
        state: { name: "Todo", type: "unstarted" },
      }),
      aTicketRow({
        ref: "R2",
        key: "R2",
        id: "AGH-2",
        title: "Early one",
        readiness: "in_progress",
        waiting_on: ["AGH-9"],
        blocked_by: [{ ref: "AGH-9", source: "linear" }],
        state: { name: "In Progress", type: "started" },
      }),
      aTicketRow({
        ref: "R3",
        key: "R3",
        id: "AGH-3",
        title: "Done one",
        readiness: "done",
        state: { name: "Done", type: "completed" },
      }),
      aTicketRow({
        ref: "R4",
        key: "R4",
        id: null,
        url: null,
        title: "Planned one",
        readiness: "can_start",
        state: null,
      }),
    ];
    render(
      <PlanningView
        tickets={cards}
        planning={aTicketPlan({
          layers: [["R1", "R2", "R3", "R4"]],
          can_start: ["R4"],
          order: ["R1", "R2", "R3", "R4"],
          waiting: [],
          critical_path: [],
        })}
      />,
    );

    const card = (name: string) => screen.getByRole("listitem", { name: new RegExp(name) });
    expect(card("Reviewed one")).toHaveTextContent("Reviewed");
    expect(card("Early one")).toHaveTextContent("Started before AGH-9 was done");
    expect(card("Early one")).not.toHaveTextContent(/After AGH-9/);
    expect(card("Done one").querySelector(".ah-flow-card-status")).toBeNull();
    expect(card("Planned one")).toHaveTextContent("Not created");
    expect(card("Planned one")).toHaveTextContent("Can start now");
  });

  it("links the ticket's pull request in the card's progress row (card)", () => {
    const row = aTicketRow({
      ref: "R1",
      key: "R1",
      id: "AGH-1",
      title: "Reviewed one",
      readiness: "in_progress",
      waiting_on: [],
      blocked_by: [],
      pr_url: "https://github.com/acme/demo-api/pull/69",
    });
    render(
      <PlanningView
        tickets={[row]}
        planning={aTicketPlan({
          layers: [["R1"]],
          can_start: [],
          order: ["R1"],
          waiting: [],
          critical_path: [],
        })}
      />,
    );

    const card = screen.getByRole("listitem", { name: "R1 · Reviewed one" });
    const link = within(card).getByRole("link", {
      name: "PR #69 of AGH-1 (opens GitHub in a new tab)",
    });
    expect(link).toHaveAttribute("href", "https://github.com/acme/demo-api/pull/69");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveTextContent("PR #69");
    expect(link.closest(".ah-flow-card-facts")).not.toBeNull();
  });

  it("reads a ticket whose only blocker is in review as startable on its branch (card)", () => {
    const blocker = aTicketRow({
      ref: "T2",
      key: "T2",
      id: "AGH-2",
      title: "Blocker",
      readiness: "in_progress",
      waiting_on: [],
      blocked_by: [],
      pr_url: "https://github.com/acme/demo-api/pull/12",
    });
    const stacked = aTicketRow({
      ref: "T3",
      key: "T3",
      id: "AGH-3",
      title: "Stacked",
      readiness: "waiting",
      state: { name: "Todo", type: "unstarted" },
      blocked_by: [{ ref: "T2", source: "plan" }],
      waiting_on: ["T2"],
    });
    render(
      <PlanningView
        tickets={[blocker, stacked]}
        planning={aTicketPlan({
          layers: [["T2"], ["T3"]],
          can_start: [],
          order: ["T2", "T3"],
          waiting: ["T3"],
          critical_path: [],
        })}
      />,
    );

    const card = screen.getByRole("listitem", { name: "T3 · Stacked" });
    expect(card).toHaveTextContent("Can start on T2's branch");
    expect(card).not.toHaveTextContent("Waiting on");
    expect(screen.getByLabelText("Legend")).toHaveTextContent(
      "Can start on a blocker's branch: its only blocker is in review",
    );
  });

  it("splits a conventional title into its type, scope and words (title)", () => {
    expect(splitTitle("feat(brand-api): generate the iban")).toEqual({
      type: "feat",
      scope: "brand-api",
      text: "generate the iban",
    });
    expect(splitTitle("fix: a typo")).toEqual({ type: "fix", scope: null, text: "a typo" });
    expect(splitTitle("Ticket T1")).toEqual({ type: null, scope: null, text: "Ticket T1" });
  });

  it("has no serious axe violation (a11y)", async () => {
    const data = aFeatureTickets();
    const { container } = render(
      <PlanningView
        tickets={data.tickets.map((t) => ({ ...t, flow: aTicketFlow() }))}
        planning={{ ...data.planning, cycles: [["AGH-202", "AGH-203"]] }}
      />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });

  describe("on the canvas", () => {
    // T3 waits on T1 and T2; T5 waits on T3 and T4.
    const linked = rows.map((row) => {
      if (row.ref === "T3") {
        return {
          ...row,
          blocked_by: [
            { ref: "T1", source: "both" as const },
            { ref: "T2", source: "both" as const },
          ],
        };
      }
      if (row.ref === "T5") {
        return {
          ...row,
          blocked_by: [
            { ref: "T3", source: "both" as const },
            { ref: "T4", source: "both" as const },
          ],
        };
      }
      return row;
    });

    it("AC-TF.1 lights the chosen ticket's whole chain above the cards and fades the rest", () => {
      const { container } = render(<PlanningView tickets={linked} planning={plan} chosen="T3" />);

      const edge = (id: string) => container.querySelector(`.ah-flow-edges [data-edge="${id}"]`);
      for (const id of ["T1→T3", "T2→T3", "T3→T5"]) expect(edge(id)).toHaveAttribute("data-hot");
      expect(edge("T4→T5")).toHaveAttribute("data-dim");
      expect(container.querySelectorAll(".ah-flow-edges-top path")).toHaveLength(3);
      expect(screen.getByRole("listitem", { name: "T3 · Ticket T3" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      expect(screen.getByRole("listitem", { name: "T5 · Ticket T5" })).toHaveAttribute(
        "data-chain",
        "true",
      );
      expect(screen.getByRole("listitem", { name: "T4 · Ticket T4" })).not.toHaveAttribute(
        "data-chain",
      );
    });

    it("draws no edge into or inside Held back, whose cards name what they wait on", () => {
      const cycle = [
        ...rows.slice(0, 2),
        aTicketRow({
          ref: "C1",
          key: "C1",
          id: null,
          title: "Cycle one",
          url: null,
          readiness: "in_cycle",
          blocked_by: [
            { ref: "C2", source: "plan" },
            { ref: "T1", source: "plan" },
          ],
          waiting_on: ["C2"],
        }),
        aTicketRow({
          ref: "C2",
          key: "C2",
          id: null,
          title: "Cycle two",
          url: null,
          readiness: "in_cycle",
          blocked_by: [{ ref: "C1", source: "plan" }],
          waiting_on: ["C1"],
        }),
      ];
      const { container } = render(
        <PlanningView
          tickets={cycle}
          planning={aTicketPlan({
            layers: [["T1", "T2"]],
            can_start: ["T1", "T2"],
            order: ["T1", "T2"],
            waiting: [],
            critical_path: [],
            cycles: [["C1", "C2"]],
          })}
        />,
      );

      expect(screen.getByRole("region", { name: /^Held back/ })).toBeInTheDocument();
      expect(container.querySelectorAll("[data-edge]")).toHaveLength(0);
      expect(screen.getByRole("listitem", { name: "C1 · Cycle one" })).toHaveTextContent(
        "Waiting: cycle with C2",
      );
    });

    it("AC-TF.3 is one Tab stop whose arrows follow the edges and the columns", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <PlanningView tickets={linked} planning={plan} onOpenTicket={() => undefined} />
        </MemoryRouter>,
      );

      const title = (ref: string) =>
        document.querySelector<HTMLElement>(`[data-node-id="${ref}"] [data-ticket-open]`);
      expect(title("T1")?.tabIndex).toBe(0);
      expect(title("T2")?.tabIndex).toBe(-1);
      title("T1")?.focus();
      await user.keyboard("{ArrowRight}");
      expect(title("T3")).toHaveFocus();
      await user.keyboard("{ArrowRight}");
      expect(title("T5")).toHaveFocus();
      await user.keyboard("{ArrowLeft}");
      expect(title("T3")).toHaveFocus();
      await user.keyboard("{ArrowLeft}");
      await user.keyboard("{ArrowDown}");
      expect(title("T2")).toHaveFocus();
      expect(title("T2")?.tabIndex).toBe(0);
      await user.keyboard("k");
      expect(title("T1")).toHaveFocus();
    });

    it("AC-TF.2 zooms from the toolbar and keeps the legend in the canvas", async () => {
      const user = userEvent.setup();
      render(<PlanningView tickets={linked} planning={plan} />);

      const controls = screen.getByRole("toolbar", { name: "Graph view" });
      await user.click(within(controls).getByRole("button", { name: "Zoom in (+)" }));
      expect(
        within(controls).getByRole("button", { name: "Reset zoom to 100%" }),
      ).toHaveTextContent("120%");
      expect(screen.getByText("How to read").closest(".ah-canvas")).not.toBeNull();
    });

    it("has no serious axe violation with a ticket chosen (a11y)", async () => {
      const { container } = render(
        <MemoryRouter>
          <PlanningView
            tickets={linked}
            planning={plan}
            chosen="T3"
            onOpenTicket={() => undefined}
          />
        </MemoryRouter>,
      );

      expect(await seriousViolations(container)).toEqual([]);
    });
  });
});
