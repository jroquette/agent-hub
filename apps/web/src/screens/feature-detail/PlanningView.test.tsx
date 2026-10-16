import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import { aFeatureTickets, aTicketPlan, aTicketRow } from "../../testing/builders";
import { PlanningView, ticketAnchor } from "./PlanningView";

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
  it("draws each parallel group as a step, left to right, then the settled tickets (flow)", () => {
    const done = aTicketRow({
      ref: "T6",
      key: "T6",
      id: null,
      title: "Ticket T6",
      url: null,
      readiness: "done",
      state: { name: "Done", type: "completed" },
    });
    render(<PlanningView tickets={[...rows, done]} planning={plan} />);

    expect(screen.getByRole("heading", { name: "Ticket flow" })).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: "Ticket flow" }))
      .getAllByRole("listitem")
      .filter((li) => li.tagName === "SECTION");
    expect(steps.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Step 1 · in parallel",
      "Step 2 · after step 1",
      "Step 3 · after step 2",
      "Done · settled",
    ]);
    expect(
      within(nth(steps, 0))
        .getAllByRole("listitem")
        .map((li) => li.getAttribute("aria-label")),
    ).toEqual(["T1 · Ticket T1", "T2 · Ticket T2", "T4 · Ticket T4"]);
    expect(within(nth(steps, 3)).getByRole("listitem", { name: "T6 · Ticket T6" })).toHaveAttribute(
      "data-readiness",
      "done",
    );
    expect(screen.getByRole("listitem", { name: "T3 · Ticket T3" })).toHaveTextContent(
      "critical path",
    );
    expect(screen.getByRole("link", { name: "Ticket T1" })).toHaveAttribute(
      "href",
      `#${ticketAnchor("T1")}`,
    );
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
    expect(card).toHaveTextContent("In progress");
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
              id: "TIP-9",
              title: "Upgrade the runtime",
              state: { name: "In Progress", type: "started" },
              url: "https://linear.app/demo/issue/TIP-9",
              done: false,
            },
            { id: "TIP-8", title: null, state: null, url: null, done: false },
            {
              id: "TIP-7",
              title: "Done elsewhere",
              state: { name: "Done", type: "completed" },
              url: "javascript:x",
              done: true,
            },
          ],
          warnings: ["TIP-5 has more than 50 relations; the first 50 were read."],
        })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Dependency cycle: T1 → T2.");
    const outside = screen.getByText("Blocked from outside this feature:").closest("[role=status]");
    expect(outside).toHaveTextContent("Upgrade the runtime · In Progress (not done)");
    expect(outside).toHaveTextContent("TIP-8 · status unknown");
    expect(outside).toHaveTextContent("TIP-7 · Done elsewhere · done");
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

  it("has no serious axe violation (a11y)", async () => {
    const data = aFeatureTickets();
    const { container } = render(
      <PlanningView
        tickets={data.tickets}
        planning={{ ...data.planning, cycles: [["AGH-202", "AGH-203"]] }}
      />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});
