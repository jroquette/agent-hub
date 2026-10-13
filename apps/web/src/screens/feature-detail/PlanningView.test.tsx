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

function section(name: string) {
  return within(screen.getByRole("region", { name }));
}

describe("PlanningView", () => {
  it("shows what can start, the numbered layers, the order and the critical path (planning)", () => {
    render(<PlanningView tickets={rows} planning={plan} />);

    expect(screen.getByRole("heading", { name: "Planning" })).toBeInTheDocument();
    expect(
      section("Can start now")
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["T1", "T2", "T4"]);
    const layers = section("Parallel groups").getAllByRole("listitem");
    expect(layers.map((li) => li.textContent)).toEqual([
      "Layer 1T1, T2, T4",
      "Layer 2T3",
      "Layer 3T5",
    ]);
    expect(
      section("Recommended order")
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "T1 · Ticket T1",
      "T2 · Ticket T2",
      "T4 · Ticket T4",
      "T3 · Ticket T3",
      "T5 · Ticket T5",
    ]);
    expect(section("Critical path").getByText(/longest chain/).parentElement).toHaveTextContent(
      "T1 → T3 → T5 (3 tickets, the longest chain not done)",
    );
    expect(section("Can start now").getByRole("link", { name: "T1" })).toHaveAttribute(
      "href",
      `#${ticketAnchor("T1")}`,
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

  it("says when nothing can start and nothing is left (planning states)", () => {
    render(
      <PlanningView
        tickets={rows}
        planning={aTicketPlan({
          layers: [],
          can_start: [],
          order: [],
          waiting: [],
          critical_path: [],
        })}
      />,
    );

    expect(screen.getByText("Nothing can start now.")).toBeInTheDocument();
    expect(screen.getByText("No ticket left to plan.")).toBeInTheDocument();
    expect(screen.getByText("No chain left: every ticket is done.")).toBeInTheDocument();
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
