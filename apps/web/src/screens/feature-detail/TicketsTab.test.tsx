import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiProblem } from "../../lib/api";
import { seriousViolations } from "../../testing/axe";
import {
  aFeatureTickets,
  aPage,
  aTicketFlow,
  aSession,
  aTicketPlan,
  aTicketRow,
  anAcRow,
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
    acRows?: ReturnType<typeof anAcRow>[];
    routes?: ApiRoutes;
    /** Where the tab opens; most cases read the Table view. */
    path?: string;
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
      acRows={extra.acRows}
    />,
    {
      routes: { "/api/v1/sessions": aPage([]), ...extra.routes },
      path: extra.path ?? "/?tickets=table",
    },
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
    expect(ready.getByRole("link", { name: "AC-200.4" })).toHaveAttribute(
      "href",
      "/?doc=acs&ac=AC-200.4",
    );
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
            ref: "ACME-1520",
            id: "ACME-1520",
            blocked_by: [
              { ref: "ACME-1521", source: "linear" },
              { ref: "ACME-1522", source: "plan" },
            ],
            readiness: "waiting",
            waiting_on: ["ACME-1521", "ACME-1522"],
          }),
          aTicketRow({
            ref: "ACME-1521",
            id: "ACME-1521",
            blocked_by: [],
            state: { name: "Canceled", type: "canceled" },
            readiness: "canceled",
          }),
          aTicketRow({
            ref: "ACME-1522",
            id: "ACME-1522",
            blocked_by: [],
            state: { name: "Done", type: "completed" },
            readiness: "done",
          }),
        ],
        planning: aTicketPlan({ layers: [], can_start: [], order: [], critical_path: [] }),
      }),
    );

    expect(within(rowOf("ACME-1520")).getByText(/Waiting on/)).toHaveTextContent(
      "Waiting on ACME-1521, ACME-1522",
    );
    expect(within(rowOf("ACME-1521")).getByText("Canceled", { selector: "b" })).toBeInTheDocument();
    expect(within(rowOf("ACME-1522")).getByText("Done", { selector: "b" })).toBeInTheDocument();
    expect(
      within(rowOf("ACME-1520")).getByRole("link", { name: "Blocked by ACME-1522" }),
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
      "https://linear.app/acme/issue/ACME-1",
      "https://evil.example/x",
      "javascript:x",
      "http://linear.app/x",
    ];
    show(
      aFeatureTickets({
        tickets: urls.map((url, i) =>
          aTicketRow({
            ref: `ACME-${String(i + 1)}`,
            id: `ACME-${String(i + 1)}`,
            url,
            blocked_by: [],
          }),
        ),
      }),
    );

    const link = within(rowOf("ACME-1")).getByRole("link", { name: /ACME-1/ });
    expect(link).toHaveAttribute("href", urls[0]);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    for (const ref of ["ACME-2", "ACME-3", "ACME-4"]) {
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

  // two-level-flows AC-1.11: Flow and Table are two views of one list (AC-268.2 stacked them).
  it("shows one view at a time, Flow first, the choice kept in ?tickets= (views)", async () => {
    const { router } = show(aFeatureTickets(), { path: "/?doc=tickets" });

    const toggle = screen.getByRole("group", { name: "Show the tickets as" });
    expect(within(toggle).getByRole("button", { name: "Flow" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("heading", { name: "Ticket flow" })).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Tickets" })).not.toBeInTheDocument();

    await userEvent.click(within(toggle).getByRole("button", { name: "Table" }));

    expect(screen.getByRole("table", { name: "Tickets" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Ticket flow" })).not.toBeInTheDocument();
    expect(router.state.location.search).toBe("?doc=tickets&tickets=table");
    expect(router.state.historyAction).toBe("REPLACE");

    await userEvent.click(within(toggle).getByRole("button", { name: "Flow" }));

    expect(router.state.location.search).toBe("?doc=tickets");
    expect(screen.getByRole("heading", { name: "Ticket flow" })).toBeInTheDocument();
  });

  it("shows each ticket's step bar and step line on its card and its row (views)", async () => {
    const data = aFeatureTickets();
    const flowing = data.tickets.map((t) => ({ ...t, flow: aTicketFlow() }));
    show({ ...data, tickets: flowing }, { path: "/" });

    const card = screen.getByRole("listitem", { name: /^AGH-202 · / });
    expect(within(card).getByRole("img", { name: /^Ticket steps: Review\. / })).toBeInTheDocument();
    expect(card).toHaveTextContent("Review · 4/7");

    await userEvent.click(screen.getByRole("button", { name: "Table" }));

    expect(screen.getByRole("columnheader", { name: "Stage" })).toBeInTheDocument();
    const row = within(rowOf("AGH-202"));
    expect(
      row.getByRole("img", { name: /^Ticket steps: Review\. Context: not recorded; / }),
    ).toBeInTheDocument();
    expect(rowOf("AGH-202")).toHaveTextContent("Review · 4/7");
  });

  it("says the current step's state or meta on the step line (views)", () => {
    const data = aFeatureTickets();
    const review = aTicketFlow({
      steps: aTicketFlow().steps.map((step) =>
        step.name === "review" ? { ...step, state: "current", meta: "Changes requested" } : step,
      ),
    });
    const evalBlocked = aTicketFlow({
      current: "eval",
      steps: aTicketFlow().steps.map((step) =>
        step.name === "eval" ? { ...step, state: "blocked", meta: "NO-SHIP" } : step,
      ),
    });
    const [first, second, third] = data.tickets;
    if (!first || !second || !third) throw new Error("three tickets");
    show(
      { ...data, tickets: [first, { ...second, flow: review }, { ...third, flow: evalBlocked }] },
      { path: "/" },
    );

    expect(screen.getByRole("listitem", { name: /^AGH-202 · / })).toHaveTextContent(
      "Review · 4/7 · Changes requested",
    );
    expect(screen.getByRole("listitem", { name: /^AGH-203 · / })).toHaveTextContent(
      "Eval · 5/7 · NO-SHIP",
    );
  });

  it("leads every blocker link on a card to its card, an epic's too (views)", () => {
    const epic = aTicketRow({
      ref: "AGH-9",
      key: "T0",
      id: "AGH-9",
      readiness: "epic",
      blocked_by: [],
      children: ["AGH-210"],
    });
    const child = aTicketRow({
      ref: "AGH-210",
      key: "T9",
      id: "AGH-210",
      parent: "AGH-9",
      blocked_by: [],
    });
    const afterEpic = aTicketRow({
      ref: "AGH-204",
      key: "T4",
      id: "AGH-204",
      blocked_by: [{ ref: "AGH-9", source: "plan" }],
    });
    const data = aFeatureTickets();
    show(
      {
        ...data,
        tickets: [...data.tickets, epic, child, afterEpic],
        planning: aTicketPlan({
          layers: [["AGH-202", "AGH-204", "AGH-210"], ["AGH-203"]],
          epics: ["AGH-9"],
        }),
      },
      { path: "/" },
    );

    const hrefs = [
      ...document.querySelectorAll<HTMLAnchorElement>('.ah-flow-card a[href^="#ticket-"]'),
    ].map((a) => a.getAttribute("href") ?? "");
    expect(hrefs).toEqual(expect.arrayContaining(["#ticket-AGH-202", "#ticket-AGH-9"]));
    for (const href of hrefs) expect(document.getElementById(href.slice(1))).not.toBeNull();
  });

  it("offers Start once per view (views)", async () => {
    show(aFeatureTickets(), { path: "/" });

    expect(await screen.findAllByRole("button", { name: /^Start AGH-202/ })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Table" }));

    expect(screen.getAllByRole("button", { name: /^Start AGH-202/ })).toHaveLength(1);
  });

  it("says a started ticket is in progress, and when it was reviewed (readiness)", async () => {
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
    await userEvent.click(screen.getByRole("button", { name: "Flow" }));
    expect(screen.getByRole("listitem", { name: /in progress/ })).toHaveTextContent(
      "2 in progress",
    );
  });

  it("describes each AC id with what must be true and marks an owner step (tickets)", () => {
    const data = aFeatureTickets();
    show(aFeatureTickets({ tickets: [{ ...nth(data.tickets, 0), acs: ["AC-1", "AC-2"] }] }), {
      acPasses: { "AC-1": true, "AC-2": false },
      acRows: [
        anAcRow({
          id: "AC-1",
          description: "Given a ticket, when its ACs are listed, then each shows its text",
        }),
        anAcRow({
          id: "AC-2",
          description: "The owner checks the PDF",
          passes: false,
          manual: true,
        }),
      ],
    });

    const table = within(screen.getByRole("table", { name: "Tickets" }));
    const gwt = table.getByRole("link", { name: /^AC-1\s*Passes$/, hidden: true });
    expect(gwt).toHaveAttribute("href", "/?doc=acs&ac=AC-1");
    expect(gwt).toHaveAccessibleDescription("each shows its text");
    expect(gwt).not.toHaveAttribute("title");
    expect(
      table.getByRole("link", { name: /^AC-2\s*Owner step$/, hidden: true }),
    ).toHaveAccessibleDescription("The owner checks the PDF");
  });

  it("shows the same AC meter whatever the number of ACs, ids folded under it (tickets)", () => {
    const data = aFeatureTickets();
    const many = { ...nth(data.tickets, 0), acs: ["AC-1", "AC-2", "AC-3", "AC-4"] };
    const one = { ...nth(data.tickets, 1), acs: ["AC-8"] };
    show(aFeatureTickets({ tickets: [many, one] }), {
      acPasses: { "AC-1": true, "AC-2": true, "AC-3": true, "AC-4": false, "AC-8": true },
    });

    const table = within(screen.getByRole("table", { name: "Tickets" }));
    expect(table.getByText("3/4 ACs passing")).toBeInTheDocument();
    expect(table.getByText("1/1 ACs passing")).toBeInTheDocument();
    expect(table.getByRole("link", { name: /^AC-8\s*Passes$/, hidden: true })).toHaveAttribute(
      "href",
      "/?doc=acs&ac=AC-8",
    );
    expect(
      table.getByRole("link", { name: /^AC-4\s*Not passing$/, hidden: true }),
    ).toBeInTheDocument();
  });

  it("links each ticket's pull request, else says there is none (tickets)", () => {
    const data = aFeatureTickets();
    const withPr = { ...nth(data.tickets, 0), pr_url: "https://github.com/acme/demo-api/pull/69" };
    const unsafe = { ...nth(data.tickets, 1), pr_url: "https://evil.example/acme/demo-api/pull/7" };
    show(aFeatureTickets({ tickets: [withPr, unsafe, nth(data.tickets, 2)] }));

    const table = within(screen.getByRole("table", { name: "Tickets" }));
    const link = table.getByRole("link", {
      name: `PR #69 of ${withPr.ref} (opens GitHub in a new tab)`,
    });
    expect(link).toHaveAttribute("href", "https://github.com/acme/demo-api/pull/69");
    expect(link).toHaveAttribute("target", "_blank");
    expect(table.getByText("PR #7")).toHaveAttribute(
      "title",
      "Link not shown: only GitHub pull request links are opened",
    );
    const cells = within(rowOf(nth(data.tickets, 2).ref)).getAllByRole("cell");
    expect(cells.at(-1)).toHaveTextContent(/^—$/);
    expect(within(rowOf(withPr.ref)).getAllByRole("cell").at(-1)).toContainElement(link);
  });

  it("shows the title's words without its conventional prefix, and no Scope column (tickets)", () => {
    const data = aFeatureTickets();
    show({
      ...data,
      tickets: data.tickets.map((t) =>
        t.ref === "AGH-201" ? { ...t, title: "feat(brand-api): add the bank details" } : t,
      ),
    });

    expect(screen.queryByRole("columnheader", { name: "Scope" })).not.toBeInTheDocument();
    const cells = within(rowOf("AGH-201")).getAllByRole("cell");
    expect(nth(cells, 1)).toHaveTextContent(/^add the bank details$/);
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

  it("has no serious axe violation in the Flow view (a11y)", async () => {
    const data = aFeatureTickets();
    const flowing = data.tickets.map((t) => ({ ...t, flow: aTicketFlow() }));
    const { container } = show({ ...data, tickets: flowing }, { path: "/" });

    await screen.findByRole("region", { name: "Ticket flow" });
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("has no serious axe violation (a11y)", async () => {
    const data = aFeatureTickets({ source: "plan", notice: "From the plan." });
    const flowing = data.tickets.map((t) => ({ ...t, flow: aTicketFlow() }));
    const { container } = show({ ...data, tickets: flowing });

    await screen.findByRole("table", { name: "Tickets" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
