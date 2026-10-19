import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  aCapabilities,
  aFeatureTickets,
  aPage,
  aTicketPlan,
  aTicketRow,
  aWorkdir,
  anAgentSession,
  aSession,
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { canStartTicket, stackedOn, ticketPrompt } from "./StartTicket";
import { TicketsTab } from "./TicketsTab";

const AGENT = "/api/v1/agent-sessions";

const driving: ApiRoutes = {
  "/api/v1/sessions": aPage([]),
  [`${AGENT}/capabilities`]: aCapabilities(),
  [`${AGENT}/workdirs`]: { items: [aWorkdir()], warnings: [] },
};

const done = aTicketRow({ ref: "T1", key: "T1", id: "AGH-1", readiness: "done" });
const ready = aTicketRow({
  ref: "T2",
  key: "T2",
  id: "AGH-2",
  title: "feat(api): add the claim endpoint",
  readiness: "can_start",
  acs: ["AC-1.1", "AC-1.2"],
  blocked_by: [{ ref: "T1", source: "both" }],
  repo: "api",
});
const waiting = aTicketRow({
  ref: "T3",
  key: "T3",
  id: "AGH-3",
  readiness: "waiting",
  waiting_on: ["T2"],
});

const PR = "https://github.com/acme/api/pull/12";
const inReview = aTicketRow({
  ...ready,
  readiness: "in_progress",
  reviewed: true,
  pr_url: PR,
});
const stacked = aTicketRow({
  ref: "T3",
  key: "T3",
  id: "AGH-3",
  readiness: "waiting",
  blocked_by: [
    { ref: "T1", source: "plan" },
    { ref: "T2", source: "plan" },
  ],
  waiting_on: ["T2"],
});

function rowOf(ref: string): HTMLElement {
  const row = document.getElementById(`ticket-${ref}`);
  if (!row) throw new Error(`no row ${ref}`);
  return row;
}

describe("StartTicket", () => {
  it("offers Start only on a created ticket that can start now", () => {
    const rows = [done, ready, waiting];
    expect(canStartTicket(ready, rows)).toBe(true);
    expect(canStartTicket(waiting, rows)).toBe(false);
    expect(canStartTicket(done, rows)).toBe(false);
    expect(canStartTicket({ ...ready, id: null }, rows)).toBe(false);
  });

  it("offers Start on a ticket whose only blocker left is in review with a pull request", () => {
    const rows = [done, inReview, stacked];

    expect(stackedOn(stacked, rows)?.id).toBe("AGH-2");
    expect(canStartTicket(stacked, rows)).toBe(true);
    // No pull request yet: nothing to build on.
    expect(canStartTicket(stacked, [done, { ...inReview, pr_url: null }, stacked])).toBe(false);
    // Waiting on two tickets: one branch cannot hold both.
    expect(canStartTicket({ ...stacked, waiting_on: ["T2", "T9"] }, rows)).toBe(false);
  });

  it("tells /feature to build on the blocker's branch and stack its pull request", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...stacked, id: "AGH-3" }, [
      done,
      inReview,
      stacked,
    ]);

    expect(prompt).toContain("Its blockers are done: AGH-1.");
    expect(prompt).toContain(`Its blocker AGH-2 is not merged yet: it is in review in ${PR}.`);
    expect(prompt).toContain(`gh pr view ${PR} --json headRefName -q .headRefName`);
    expect(prompt).toContain("./hub worktree <name> --only api --base <that branch>");
    expect(prompt).toContain("Open this ticket's pull request against AGH-2's branch");
  });

  it("labels the stacked Start with the blocker it builds on", async () => {
    renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="claims"
        data={aFeatureTickets({
          tickets: [done, inReview, stacked],
          planning: aTicketPlan({
            layers: [["T1"], ["T2"], ["T3"]],
            can_start: [],
            waiting: ["T3"],
          }),
        })}
        onRefresh={() => undefined}
      />,
      { routes: driving },
    );

    const start = await within(rowOf("T3")).findByRole("button", { name: "Start AGH-3 on AGH-2" });
    expect(start).toHaveTextContent("Start on AGH-2");
  });

  it("asks /feature to work this one ticket from its workspace step, with its context", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...ready, id: "AGH-2" }, [done, ready]);

    expect(prompt.split("\n")[0]).toBe("/feature AGH-2");
    expect(prompt).toContain("Ticket: AGH-2 · feat(api): add the claim endpoint");
    expect(prompt).toContain("`brain/features/claims/`");
    expect(prompt).toContain("Repo: api.");
    expect(prompt).toContain("AC-1.1, AC-1.2");
    expect(prompt).toContain("Its blockers are done: AGH-1.");
    expect(prompt).toContain("begin at step 5 (Workspace), for this ticket only");
  });

  it("starts a session in the hub folder and opens its chat", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e5"), status: "running" });
    const view = renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="claims"
        data={aFeatureTickets({
          tickets: [done, ready, waiting],
          planning: aTicketPlan({ layers: [["T1"], ["T2"], ["T3"]], can_start: ["T2"] }),
        })}
        onRefresh={() => undefined}
      />,
      { routes: { ...driving, [`POST ${AGENT}`]: created } },
    );

    const row = within(rowOf("T2"));
    expect(within(rowOf("T3")).queryByRole("button")).toBe(null);
    const start = await row.findByRole("button", { name: "Start AGH-2" });
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
    expect(screen.getAllByRole("button", { name: "Start AGH-2" })).toHaveLength(2);
    await userEvent.click(start);

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
    const post = view.requests.find(
      (r) => r.method === "POST" && new URL(r.url).pathname === AGENT,
    );
    const body = JSON.parse(await (post ?? new Request("about:blank")).clone().text()) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({ project: "agent-hub", mode: "acceptEdits", fork: false });
    expect(String(body.prompt)).toMatch(/^\/feature AGH-2\n/);
  });

  it("links the ticket's open session on its card instead of Start (sessions)", async () => {
    const card = () => {
      const found = document.querySelector('[data-node-id="T2"]');
      if (!(found instanceof HTMLElement)) throw new Error("no card T2");
      return within(found);
    };
    renderWithApi(
      <TicketsTab
        project="agent-hub"
        slug="claims"
        data={aFeatureTickets({
          tickets: [done, ready, waiting],
          planning: aTicketPlan({ layers: [["T1"], ["T2"], ["T3"]], can_start: ["T2"] }),
        })}
        onRefresh={() => undefined}
      />,
      {
        routes: {
          ...driving,
          "/api/v1/sessions": (request: Request) =>
            new URL(request.url).searchParams.get("issue") === "AGH-2"
              ? aPage([aSession({ id: "sess-2", status: "waiting" })])
              : aPage([]),
        },
      },
    );

    const link = await card().findByRole("link", { name: /Waiting/ });
    expect(link).toHaveAttribute("href", "/sessions/sess-2");
    expect(card().queryByRole("button", { name: "Start AGH-2" })).toBe(null);
  });
});
