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
import { stackedOn } from "./PlanningView";
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

  it("tells /implement to build on the blocker's branch and stack its pull request", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...stacked, id: "AGH-3" }, [
      done,
      inReview,
      stacked,
    ]);

    expect(prompt).toContain("Its blockers are done: AGH-1.");
    expect(prompt).toContain(`Its blocker AGH-2 is not merged yet: it is in review in ${PR}.`);
    // AGH-381: the command names the pull request; hub worktree reads its repo and branch, so the
    // blocker's repo starts from its branch even when the ticket's own work is in another repo.
    expect(prompt).toContain(
      `\`./hub worktree agh-3 --stack-on ${PR}\`, with no --only and no --base`,
    );
    expect(prompt).not.toContain("gh pr view");
    expect(prompt).not.toContain("--base <");
    expect(prompt).toContain("Open this ticket's pull request against AGH-2's branch");
  });

  it("reads as startable on the blocker's branch and confirms the risk before starting", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e6"), status: "running" });
    const view = renderWithApi(
      <TicketsTab
        evals={[]}
        openerRef={{ current: null }}
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
      { routes: { ...driving, [`POST ${AGENT}`]: created }, path: "/?tickets=table" },
    );

    const row = within(rowOf("T3"));
    expect(row.getByText(/Can start on/)).toHaveTextContent("Can start on T2's branch");
    expect(row.getByText("AGH-2 is in review, not merged")).toBeInTheDocument();
    expect(row.queryByText(/Waiting on/)).toBe(null);
    const start = await row.findByRole("button", {
      name: "Start AGH-3 on AGH-2's branch (AGH-2 is in review, not merged)",
    });
    expect(start).toHaveTextContent("Start");
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
    await userEvent.click(start);

    const dialog = await screen.findByRole("alertdialog", {
      name: "Start AGH-3 on AGH-2's branch?",
    });
    expect(dialog).toHaveTextContent(
      "AGH-2 is in review and not merged: its code may still change.",
    );
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Start AGH-3" }));

    await waitFor(() => {
      expect(view.router.state.location.pathname).toBe(`/agent-sessions/${created.id}`);
    });
  });

  it("offers the stacked Start as a default button and starts nothing when the dialog is cancelled", async () => {
    const view = renderWithApi(
      <TicketsTab
        evals={[]}
        openerRef={{ current: null }}
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

    const start = await within(rowOf("T3")).findByRole("button", {
      name: "Start AGH-3 on AGH-2's branch (AGH-2 is in review, not merged)",
    });
    expect(start).not.toHaveClass("ah-btn-primary");
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
    await userEvent.click(start);
    const dialog = await screen.findByRole("alertdialog", {
      name: "Start AGH-3 on AGH-2's branch?",
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).toBe(null);
    expect(view.requests.some((r) => r.method === "POST")).toBe(false);
    expect(view.router.state.location.pathname).toBe("/");
  });

  it("runs /implement on a ticket free to start, so its context and preflight are recorded", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...ready, id: "AGH-2" }, [done, ready]);

    expect(prompt.split("\n")[0]).toBe("/implement AGH-2");
    expect(prompt).toContain("Ticket: AGH-2 · feat(api): add the claim endpoint");
    expect(prompt).toContain("`brain/features/claims/`");
    expect(prompt).toContain("Its blockers are done: AGH-1.");
    expect(prompt).toContain("Work on no other ticket.");
    // /implement conducts the steps: the prompt never sends the session in-line.
    expect(prompt).not.toMatch(/(^|\s)\/feature\b/);
    expect(prompt).not.toContain("step 6");
  });

  it("tells the session to conduct the ticket itself, stage by stage, and ask before the PR (AGH-579)", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...ready, id: "AGH-2" }, [done, ready]);

    expect(prompt).toContain("Repo: api.");
    expect(prompt).toContain(
      "Conduct the whole ticket in this session: run each stage as a subagent and tell me its result here.",
    );
    expect(prompt).toContain("Ask me before you push or open the pull request.");
    expect(prompt).not.toContain("workflow run");
  });

  it("starts a stacked ticket with /implement too, its worktree on the blocker's branch (AGH-579)", () => {
    const prompt = ticketPrompt("agent-hub", "claims", { ...stacked, id: "AGH-3" }, [
      done,
      inReview,
      stacked,
    ]);

    expect(prompt.split("\n")[0]).toBe("/implement AGH-3");
    expect(prompt).not.toMatch(/(^|\s)\/feature\b/);
    expect(prompt).not.toContain("step 6");
    expect(prompt).toContain(`For the workspace, create the worktrees with exactly`);
  });

  it("says in Start's tooltip what the one session does (AGH-579)", async () => {
    renderWithApi(
      <TicketsTab
        evals={[]}
        openerRef={{ current: null }}
        project="agent-hub"
        slug="claims"
        data={aFeatureTickets({
          tickets: [done, ready, waiting],
          planning: aTicketPlan({ layers: [["T1"], ["T2"], ["T3"]], can_start: ["T2"] }),
        })}
        onRefresh={() => undefined}
      />,
      { routes: driving, path: "/?tickets=table" },
    );

    const start = await within(rowOf("T2")).findByRole("button", { name: "Start AGH-2" });
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
    const wrap = start.closest(".ah-tip-wrap");
    if (!(wrap instanceof HTMLElement)) throw new Error("no tooltip around Start");
    expect(within(wrap).getByRole("tooltip", { hidden: true })).toHaveTextContent(
      "Start one Claude session that conducts AGH-2: context, preflight, build, review and eval as its own subagents, each reported in its chat. It asks you before the pull request.",
    );
  });

  it("starts a session in the hub folder and opens its chat", async () => {
    const created = anAgentSession({ id: anId(8, "0192a5e5"), status: "running" });
    const view = renderWithApi(
      <TicketsTab
        evals={[]}
        openerRef={{ current: null }}
        project="agent-hub"
        slug="claims"
        data={aFeatureTickets({
          tickets: [done, ready, waiting],
          planning: aTicketPlan({ layers: [["T1"], ["T2"], ["T3"]], can_start: ["T2"] }),
        })}
        onRefresh={() => undefined}
      />,
      { routes: { ...driving, [`POST ${AGENT}`]: created }, path: "/?tickets=table" },
    );

    const row = within(rowOf("T2"));
    expect(within(rowOf("T3")).queryByRole("button")).toBe(null);
    const start = await row.findByRole("button", { name: "Start AGH-2" });
    await waitFor(() => {
      expect(start).toBeEnabled();
    });
    // One Start per view (two-level-flows AC-1.11): the table shows it, the flow is not shown.
    expect(screen.getAllByRole("button", { name: "Start AGH-2" })).toHaveLength(1);
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
    expect(String(body.prompt)).toMatch(/^\/implement AGH-2\n/);
  });

  it("links the ticket's open session on its card instead of Start (sessions)", async () => {
    const card = () => {
      const found = document.querySelector('[data-node-id="T2"]');
      if (!(found instanceof HTMLElement)) throw new Error("no card T2");
      return within(found);
    };
    renderWithApi(
      <TicketsTab
        evals={[]}
        openerRef={{ current: null }}
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

    const link = await card().findByRole("link", { name: /^Session running: Waiting, started / });
    expect(link).toHaveAttribute("href", "/sessions/sess-2");
    expect(card().queryByRole("button", { name: "Start AGH-2" })).toBe(null);
  });
});
