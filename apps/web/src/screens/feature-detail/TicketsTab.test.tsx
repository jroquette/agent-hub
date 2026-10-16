import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import {
  aFeatureTickets,
  aPage,
  aSession,
  aTicketPlan,
  aTicketRow,
  renderWithApi,
  type ApiRoutes,
  type FeatureTickets,
} from "../../testing/builders";
import { TicketsTab } from "./TicketsTab";

function show(
  data: FeatureTickets | undefined,
  extra: {
    error?: ApiProblem | null;
    acPasses?: Record<string, boolean>;
    routes?: ApiRoutes;
  } = {},
) {
  const onRefresh = vi.fn();
  const result = renderWithApi(
    <TicketsTab
      project="agent-hub"
      slug="control-plane"
      data={data}
      error={extra.error ?? null}
      onRefresh={onRefresh}
      acPasses={extra.acPasses}
    />,
    { routes: { "/api/v1/sessions": aPage([]), ...extra.routes } },
  );
  return { ...result, onRefresh };
}

/** The `index`th item, failing the test when there is none. */
function nth<T>(items: readonly T[], index: number): T {
  const item = items[index];
  if (item === undefined) throw new Error(`no item ${String(index)}`);
  return item;
}

function rowOf(ref: string): HTMLElement {
  const row = document.getElementById(`ticket-${ref}`);
  if (!row) throw new Error(`no row ${ref}`);
  return row;
}

describe("TicketsTab", () => {
  it("lists the epic first, tagged, with its children under it", () => {
    const epic = aTicketRow({
      ref: "AGH-9",
      key: "T0",
      id: "AGH-9",
      readiness: "epic",
      blocked_by: [],
      children: ["AGH-202"],
    });
    const data = aFeatureTickets();
    show({
      ...data,
      tickets: [
        ...data.tickets.map((t) => (t.ref === "AGH-202" ? { ...t, parent: "AGH-9" } : t)),
        epic,
      ],
      planning: { ...data.planning, epics: ["AGH-9"] },
    });

    const rows = within(screen.getByRole("table", { name: "Tickets" })).getAllByRole("row");
    expect(nth(rows, 1)).toHaveAttribute("id", "ticket-AGH-9");
    expect(nth(rows, 1)).toHaveTextContent("Epic");
    expect(nth(rows, 1)).toHaveTextContent("Epic · 0/1 done");
    expect(nth(rows, 2)).toHaveAttribute("id", "ticket-AGH-202");
    expect(rowOf("AGH-202")).toHaveAttribute("data-child", "true");
  });

  it("shows each ticket's id, title, status, assignee, blockers, ACs and readiness (tickets)", () => {
    show(aFeatureTickets());

    const table = screen.getByRole("table", { name: "Tickets" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);

    const done = within(rowOf("AGH-201"));
    expect(done.getByRole("link", { name: /AGH-201/ })).toBeInTheDocument();
    expect(done.getByText("Collect the events")).toBeInTheDocument();
    expect(done.getByText("Done", { selector: ".ah-badge" })).toBeInTheDocument();

    const ready = within(rowOf("AGH-202"));
    expect(ready.getByText("Serve the ticket summaries")).toBeInTheDocument();
    expect(ready.getByText("In Progress", { selector: ".ah-badge" })).toBeInTheDocument();
    expect(ready.getByText("Ada Example")).toBeInTheDocument();
    expect(ready.getByRole("link", { name: "Blocked by AGH-201" })).toHaveAttribute(
      "href",
      "#ticket-AGH-201",
    );
    expect(ready.getByRole("link", { name: "AC-200.4" })).toHaveAttribute("href", "/?ac=AC-200.4");
    expect(ready.getByText("Can start now")).toBeInTheDocument();

    const waiting = within(rowOf("AGH-203"));
    expect(waiting.getByText("Unassigned")).toBeInTheDocument();
    expect(waiting.getByText(/Waiting on/)).toHaveTextContent("Waiting on AGH-202");
  });

  it("names every blocker it waits on and marks done and canceled tickets (tickets)", () => {
    show(
      aFeatureTickets({
        tickets: [
          aTicketRow({
            ref: "TIP-1520",
            id: "TIP-1520",
            blocked_by: [
              { ref: "TIP-1521", source: "linear" },
              { ref: "TIP-1522", source: "plan" },
            ],
            readiness: "waiting",
            waiting_on: ["TIP-1521", "TIP-1522"],
          }),
          aTicketRow({
            ref: "TIP-1521",
            id: "TIP-1521",
            blocked_by: [],
            state: { name: "Canceled", type: "canceled" },
            readiness: "canceled",
          }),
          aTicketRow({
            ref: "TIP-1522",
            id: "TIP-1522",
            blocked_by: [],
            state: { name: "Done", type: "completed" },
            readiness: "done",
          }),
        ],
        planning: aTicketPlan({ layers: [], can_start: [], order: [], critical_path: [] }),
      }),
    );

    expect(within(rowOf("TIP-1520")).getByText(/Waiting on/)).toHaveTextContent(
      "Waiting on TIP-1521, TIP-1522",
    );
    expect(within(rowOf("TIP-1521")).getByText("Canceled", { selector: "b" })).toBeInTheDocument();
    expect(within(rowOf("TIP-1522")).getByText("Done", { selector: "b" })).toBeInTheDocument();
    expect(
      within(rowOf("TIP-1520")).getByRole("link", { name: "Blocked by TIP-1522" }),
    ).toHaveAttribute("title", "From the plan only");
  });

  it("shows unknown status and the plan's title when the data is from the plan (tickets)", () => {
    show(
      aFeatureTickets({
        source: "plan",
        tickets: [
          aTicketRow({
            ref: "T1",
            key: "T1",
            id: null,
            title: "Draft ticket",
            state: null,
            assignee: null,
            url: null,
            blocked_by: [],
            readiness: "unknown",
          }),
        ],
        planning: aTicketPlan({
          layers: [["T1"]],
          can_start: [],
          order: ["T1"],
          critical_path: [],
        }),
      }),
    );

    const row = within(rowOf("T1"));
    expect(row.getByText("T1")).toBeInTheDocument();
    expect(row.getByText("not created")).toBeInTheDocument();
    expect(row.getByText("Unknown", { selector: ".ah-badge" })).toBeInTheDocument();
    expect(row.getByText("Draft ticket")).toBeInTheDocument();
  });

  it("links only https://linear.app/ urls, in a new tab (linear-link)", () => {
    const urls = [
      "https://linear.app/acme/issue/TIP-1",
      "https://evil.example/x",
      "javascript:x",
      "http://linear.app/x",
    ];
    show(
      aFeatureTickets({
        tickets: urls.map((url, i) =>
          aTicketRow({
            ref: `TIP-${String(i + 1)}`,
            id: `TIP-${String(i + 1)}`,
            url,
            blocked_by: [],
          }),
        ),
      }),
    );

    const link = within(rowOf("TIP-1")).getByRole("link", { name: /TIP-1/ });
    expect(link).toHaveAttribute("href", urls[0]);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    for (const ref of ["TIP-2", "TIP-3", "TIP-4"]) {
      expect(within(rowOf(ref)).queryByRole("link", { name: new RegExp(ref) })).toBeNull();
      expect(within(rowOf(ref)).getByText(ref)).toBeInTheDocument();
    }
  });

  it("links an external blocker to Linear when its url is safe (linear-link)", () => {
    show(
      aFeatureTickets({
        tickets: [
          aTicketRow({
            blocked_by: [{ ref: "OPS-9", source: "linear" }],
            readiness: "waiting",
            waiting_on: ["OPS-9"],
          }),
        ],
        planning: aTicketPlan({
          external_blockers: [
            {
              id: "OPS-9",
              title: "Open the firewall",
              state: { name: "Todo", type: "unstarted" },
              url: "https://linear.app/demo/issue/OPS-9",
              done: false,
            },
          ],
        }),
      }),
    );

    const link = within(rowOf("AGH-202")).getByRole("link", { name: "Blocked by OPS-9" });
    expect(link).toHaveAttribute("href", "https://linear.app/demo/issue/OPS-9");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows the notice and refetches on Refresh (notice)", async () => {
    const { onRefresh } = show(aFeatureTickets({ source: "plan", notice: "From the plan." }));

    expect(screen.getByRole("status")).toHaveTextContent("From the plan.");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("shows the ticket flow above the table (planning)", () => {
    show(aFeatureTickets());

    const flow = screen.getByRole("heading", { name: "Ticket flow" });
    const table = screen.getByRole("table", { name: "Tickets" });
    expect(flow.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says a started ticket is in progress, and when it was reviewed (readiness)", () => {
    const data = aFeatureTickets();
    const first = nth(data.tickets, 0);
    const second = nth(data.tickets, 1);
    show(
      aFeatureTickets({
        tickets: [
          {
            ...first,
            state: { name: "In Review", type: "started" },
            readiness: "in_progress",
            reviewed: true,
          },
          {
            ...second,
            state: { name: "In Progress", type: "started" },
            readiness: "in_progress",
            reviewed: false,
            waiting_on: [first.ref],
          },
        ],
      }),
    );

    const rows = within(screen.getByRole("table", { name: "Tickets" })).getAllByRole("row");
    expect(nth(rows, 1)).toHaveTextContent("Reviewed · waiting for Done");
    expect(nth(rows, 2)).toHaveTextContent(`In progressstarted before ${first.ref} was done`);
    expect(screen.getByRole("listitem", { name: /in progress/ })).toHaveTextContent(
      "2 in progress",
    );
  });

  it("folds a long AC list into how many pass (tickets)", () => {
    const data = aFeatureTickets();
    const row = { ...nth(data.tickets, 0), acs: ["AC-1", "AC-2", "AC-3", "AC-4"] };
    show(aFeatureTickets({ tickets: [row] }), {
      acPasses: { "AC-1": true, "AC-2": true, "AC-3": true, "AC-4": false },
    });

    const table = within(screen.getByRole("table", { name: "Tickets" }));
    expect(table.getByText("3/4 passing")).toBeInTheDocument();
    expect(screen.getByText("3/4 ACs passing")).toBeInTheDocument();
  });

  it("shows the title's scope in its own column, apart from the words (tickets)", () => {
    const data = aFeatureTickets();
    show({
      ...data,
      tickets: data.tickets.map((t) =>
        t.ref === "AGH-201" ? { ...t, title: "feat(brand-api): add the bank details" } : t,
      ),
    });

    const cells = within(rowOf("AGH-201")).getAllByRole("cell");
    expect(nth(cells, 1)).toHaveTextContent(/^brand-api$/);
    expect(nth(cells, 2)).toHaveTextContent(/^add the bank details$/);
  });

  it("links the sessions that worked on each ticket, asked by its issue (sessions)", async () => {
    const { requests } = show(aFeatureTickets(), {
      routes: {
        "/api/v1/sessions": (request: Request) =>
          new URL(request.url).searchParams.get("issue") === "AGH-201"
            ? aPage([aSession({ id: "sess-1", status: "ended", outcome: "done" })])
            : aPage([]),
      },
    });

    const link = await within(rowOf("AGH-201")).findByRole("link", { name: /Done/ });
    expect(link).toHaveAttribute("href", "/sessions/sess-1");
    expect(await within(rowOf("AGH-202")).findByText("none")).toBeInTheDocument();
    const asked = requests.map((r) => new URL(r.url).searchParams);
    expect(
      asked.some((q) => q.get("issue") === "AGH-201" && q.get("project") === "agent-hub"),
    ).toBe(true);
  });

  it("shows a skeleton while loading (states)", () => {
    const { container } = show(undefined);

    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("shows the problem with a retry when the route failed (states)", async () => {
    const { onRefresh } = show(undefined, {
      error: new ApiProblem({ status: 500, title: "Internal server error" }),
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Internal server error");
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(onRefresh).toHaveBeenCalledOnce();
  });

  it("says there are no tickets when the feature has none (states)", () => {
    show(
      aFeatureTickets({
        tickets: [],
        planning: aTicketPlan({
          layers: [],
          can_start: [],
          order: [],
          waiting: [],
          critical_path: [],
        }),
      }),
    );

    expect(screen.getByText("No tickets for this feature yet.")).toBeInTheDocument();
  });

  it("has no serious axe violation (a11y)", async () => {
    const { container } = show(aFeatureTickets({ source: "plan", notice: "From the plan." }));

    await screen.findByRole("table", { name: "Tickets" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
