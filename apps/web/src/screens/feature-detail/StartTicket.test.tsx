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
  anId,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { canStartTicket, ticketPrompt } from "./StartTicket";
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

function rowOf(ref: string): HTMLElement {
  const row = document.getElementById(`ticket-${ref}`);
  if (!row) throw new Error(`no row ${ref}`);
  return row;
}

describe("StartTicket", () => {
  it("offers Start only on a created ticket that can start now", () => {
    expect(canStartTicket(ready)).toBe(true);
    expect(canStartTicket(waiting)).toBe(false);
    expect(canStartTicket(done)).toBe(false);
    expect(canStartTicket({ ...ready, id: null })).toBe(false);
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
});
