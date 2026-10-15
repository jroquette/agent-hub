import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  anApproval,
  anId,
  aPage,
  aProblem,
  at,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { ApprovalsScreen } from ".";

const guard = anApproval({
  id: anId(1, "0192bbbb"),
  kind: "guard_ask",
  title: "Allow edit under docs/adr/",
  path: "docs/adr/0012-tracker-team-cap.md",
  requested_at: at(3000),
  how_to_decide:
    "cd /home/dev/agent-hub-hub && claude --resume 7d93a2e4-1c0b-7a9f-8e7d-6c5b4a392817",
});
const plan = anApproval({
  id: anId(2, "0192bbbb"),
  kind: "plan",
  title: "Approve plan for AGH-48",
  path: null,
  rule: null,
  requested_by: "hub-workflow:planner",
  feature: "layered-memory",
  requested_at: at(100),
  session_id: "5f21c0aa-6d1e-7b20-9a4c-3e2f1d0c9b8a",
  how_to_decide:
    "cd /home/dev/agent-hub-hub && claude --resume 5f21c0aa-6d1e-7b20-9a4c-3e2f1d0c9b8a",
});

function routesWith(items = [guard, plan]): ApiRoutes {
  return {
    "/api/v1/approvals": (request: Request) =>
      new URL(request.url).searchParams.get("status") === "decided"
        ? aPage([
            anApproval({
              id: anId(5),
              status: "approved",
              decided: true,
              decided_at: at(900),
              title: "Approve plan for AGH-101",
            }),
            anApproval({
              id: anId(6),
              status: "declined",
              decided: true,
              inferred: true,
              decided_at: null,
              title: "Allow edit under docs/adr/",
            }),
          ])
        : aPage(items),
    [`/api/v1/approvals/${guard.id}`]: guard,
    [`/api/v1/approvals/${plan.id}`]: plan,
  };
}

function renderApprovals(path = "/approvals", routes = routesWith()) {
  return renderWithApi(<ApprovalsScreen />, { routes, path, route: "/approvals/:approvalId?" });
}

describe("ApprovalsScreen", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("sorts oldest first and selects the oldest open item with how to decide and P4 actions", async () => {
    renderApprovals();

    const list = await screen.findByRole("list", { name: "Open approvals" });
    const rows = within(list).getAllByRole("link");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Approve plan for AGH-48"),
      expect.stringContaining("Allow edit under docs/adr/"),
    ]);
    expect(rows[0]).toHaveAttribute("aria-current", "true");

    const panel = await screen.findByRole("region", { name: "Approve plan for AGH-48" });
    const how = within(panel).getByRole("group", { name: "How to decide" });
    expect(how).toHaveTextContent(
      "cd /home/dev/agent-hub-hub && claude --resume 5f21c0aa-6d1e-7b20-9a4c-3e2f1d0c9b8a",
    );
    for (const name of ["Approve plan", "Request changes", "Reject"]) {
      const button = within(panel).getByRole("button", { name: new RegExp(`^${name}`) });
      expect(button).toBeDisabled();
      expect(within(button).getByText("P4")).toHaveClass("ah-phase");
      expect(button).toHaveAttribute("title", "Available in Phase 4. This version is read-only.");
    }
    expect(within(panel).getByRole("link", { name: /Open feature record/ })).toHaveAttribute(
      "href",
      "/features/agent-hub/layered-memory",
    );
  });

  it("opens the guard ask with why it asks and no stored diff when its row is chosen", async () => {
    const user = userEvent.setup();
    const { router } = renderApprovals();

    const list = await screen.findByRole("list", { name: "Open approvals" });
    await user.click(within(list).getByRole("link", { name: /Allow edit under docs\/adr\// }));

    expect(router.state.location.pathname).toBe(`/approvals/${guard.id}`);
    const panel = await screen.findByRole("region", { name: "Allow edit under docs/adr/" });
    expect(within(panel).getByText(/matches/)).toHaveTextContent(
      "docs/adr/0012-tracker-team-cap.md matches guard.ask_before_edit in hub.json (rule ask_before_edit).",
    );
    expect(
      within(panel).getByText("Diff content is not stored in this version."),
    ).toBeInTheDocument();
    expect(within(panel).getByText("What changes if I allow")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /^Allow this edit/ })).toBeDisabled();
    expect(within(panel).getByText(/Answer the permission prompt/)).toBeInTheDocument();
  });

  it("builds the command from the hub path when the API gives none", async () => {
    const bare = anApproval({
      id: anId(3, "0192bbbb"),
      kind: "spec",
      title: "Approve spec for LOK-311",
      how_to_decide: null,
      hub_path: "/srv/hub",
      session_id: "abc",
    });
    renderApprovals(`/approvals/${bare.id}`, {
      ...routesWith([bare]),
      [`/api/v1/approvals/${bare.id}`]: bare,
    });

    const panel = await screen.findByRole("region", { name: "Approve spec for LOK-311" });
    expect(within(panel).getByRole("group", { name: "How to decide" })).toHaveTextContent(
      "cd /srv/hub && claude --resume abc",
    );
  });

  it("lists decided requests with their outcome when Decided is chosen", async () => {
    const user = userEvent.setup();
    const { requests } = renderApprovals();

    await user.click(await screen.findByRole("button", { name: "Decided" }));

    const list = await screen.findByRole("list", { name: "Decided approvals" });
    expect(within(list).getByText("Approved")).toBeInTheDocument();
    expect(within(list).getByText(/Declined/)).toBeInTheDocument();
    expect(within(list).getByText(/time unknown/)).toBeInTheDocument();
    expect(requests.some((r) => r.url.includes("status=decided"))).toBe(true);
  });

  it("asks the API for one kind when the kind filter is set", async () => {
    const user = userEvent.setup();
    const { requests } = renderApprovals();

    await user.selectOptions(await screen.findByRole("combobox", { name: "Kind" }), "Guard ask");

    await waitFor(() => {
      expect(requests.some((r) => r.url.includes("kind=guard_ask"))).toBe(true);
    });
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind" }), "All");
  });

  describe("states", () => {
    it("shows list and panel skeletons after 300 ms while pending", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      try {
        renderApprovals("/approvals", { "/api/v1/approvals": "pending" });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(350);
        });
        expect(document.querySelectorAll(".ah-skel").length).toBeGreaterThan(3);
      } finally {
        vi.useRealTimers();
      }
    });

    it("shows the empty copy when nothing waits", async () => {
      renderApprovals("/approvals", routesWith([]));

      expect(await screen.findByText("Nothing waits for you.")).toBeInTheDocument();
      expect(
        screen.getByText(/appear here when an agent asks\. No session is running\./),
      ).toBeInTheDocument();
      expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: /Approve/ })).not.toBeInTheDocument();
    });

    it("shows a problem in the list region when the list fails", async () => {
      const user = userEvent.setup();
      const { requests } = renderApprovals("/approvals", {
        "/api/v1/approvals": aProblem({ status: 503, title: "Busy", detail: "Database busy." }),
      });

      expect(await screen.findByText("Could not load approvals")).toBeInTheDocument();
      expect(screen.getByText("Database busy.")).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Try again" }));
      await waitFor(() => {
        expect(requests.filter((r) => r.url.includes("/approvals")).length).toBe(2);
      });
    });

    it("keeps the list usable when the selected approval cannot be loaded", async () => {
      const missing = anId(9, "0192bbbb");
      renderApprovals(`/approvals/${missing}`, {
        ...routesWith(),
        [`/api/v1/approvals/${missing}`]: aProblem({
          status: 404,
          title: "Not found",
          detail: "Approval not found. It may have been decided.",
        }),
      });

      expect(await screen.findByText("Could not load this approval")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Back to inbox" })).toHaveAttribute(
        "href",
        "/approvals",
      );
      expect(screen.getByRole("list", { name: "Open approvals" })).toBeInTheDocument();
    });

    it("stamps the header as stale when the collector is offline", async () => {
      renderApprovals();

      await screen.findByRole("list", { name: "Open approvals" });
      expect(screen.getByText(/^Stale · as of/)).toBeInTheDocument();
    });
  });

  it("decides a workflow gate here with its declared decisions instead of P4 actions", async () => {
    const gate = anApproval({
      id: "run-9:ship:1",
      kind: "human_gate",
      title: "Human gate needs approval",
      gate_id: "run-9:ship:1",
      session_id: "run:run-9",
      path: null,
      rule: null,
      requested_at: at(50),
      how_to_decide: "cd /home/dev/agent-hub-hub && hub workflow approve|reject|respond run-9",
    });
    const encoded = encodeURIComponent(gate.id);
    const { requests } = renderApprovals(`/approvals/${encoded}`, {
      ...routesWith([gate, plan]),
      [`/api/v1/approvals/${encoded}`]: gate,
      [`/api/v1/approvals/${encoded}/gate`]: {
        approval_id: gate.id,
        run_id: "run-9",
        project: "agent-hub",
        workflow: "ship",
        node: "ship",
        attempt: 1,
        form: "decision",
        choices: [
          { id: "approve", label: "Approve" },
          { id: "reject", label: "Reject" },
        ],
        text: "off",
      },
      [`POST /api/v1/approvals/${encoded}/decision`]: {
        approval_id: gate.id,
        run_id: "run-9",
        project: "agent-hub",
        decision: "approve",
      },
    });

    const panel = await screen.findByRole("region", { name: "Human gate needs approval" });
    expect(
      within(panel).getByText("Deciding here records your answer and resumes the run."),
    ).toBeInTheDocument();
    const decide = await within(panel).findByRole("group", { name: "Decide this gate" });
    expect(within(panel).queryByText("P4")).toBeNull();
    expect(within(panel).queryByRole("button", { name: /^Pass gate/ })).toBeNull();
    await userEvent.click(within(decide).getByRole("button", { name: "Approve" }));

    expect(await within(panel).findByText(/^Decision recorded/)).toHaveAttribute("role", "status");
    const post = requests.find((r) => r.method === "POST");
    expect(await post?.json()).toEqual({ decision: "approve" });
  });

  it("keeps P4 actions on a human gate asked outside a workflow run", async () => {
    const hook = anApproval({
      id: anId(7, "0192bbbb"),
      kind: "human_gate",
      title: "Human gate needs approval",
      session_id: "5f21c0aa-6d1e-7b20-9a4c-3e2f1d0c9b8a",
      path: null,
      rule: null,
      requested_at: at(50),
    });
    renderApprovals(`/approvals/${hook.id}`, {
      ...routesWith([hook]),
      [`/api/v1/approvals/${hook.id}`]: hook,
    });

    const panel = await screen.findByRole("region", { name: "Human gate needs approval" });
    expect(within(panel).getByRole("button", { name: /^Pass gate/ })).toBeDisabled();
    expect(within(panel).queryByRole("group", { name: "Decide this gate" })).toBeNull();
  });

  it("has no serious a11y violations (a11y)", async () => {
    const { container } = renderApprovals();

    await screen.findByRole("region", { name: "Approve plan for AGH-48" });
    expect(await seriousViolations(container)).toEqual([]);
  });
});
