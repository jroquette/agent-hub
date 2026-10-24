import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aPage,
  aSession,
  aSessionLabel,
  aSessionSummary,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { TicketDetailScreen } from "./index";

const AGENT_ID = "11111111-2222-4333-8444-555555555555";

const fixing = aSession({
  id: "s-fix",
  issue: null,
  status: "ended",
  outcome: "done",
  agent_session_id: AGENT_ID,
  label: aSessionLabel({ issue: "AGH-112", workflows: ["/fix"], title: "Cap the tracker teams" }),
  pr: { number: 41, state: "open", url: "https://github.com/acme/app/pull/41" },
  cost_usd: "1.0000",
  last_activity_at: "2026-01-02T09:00:00Z",
});
const triage = aSession({
  id: "s-triage",
  issue: null,
  status: "ended",
  outcome: "done",
  label: aSessionLabel({ issue: "AGH-112", workflows: ["/triage"] }),
  cost_usd: "0.2500",
  last_activity_at: "2026-01-01T09:00:00Z",
});

const changes = {
  repos: [
    {
      root: "/w/app",
      label: "app",
      branch: "roquettejh/agh-112-team-cap",
      base: "origin/main",
      source: "worktree",
      pull_request: { number: 41, url: "https://github.com/acme/app/pull/41", state: "OPEN" },
      commits: [
        {
          sha: "abcdef1234",
          subject: "fix(tracker): cap the teams",
          authored_at: "2026-01-02T08:00:00Z",
          author: "José",
        },
      ],
      files: [
        {
          path: "/w/app/src/teams.py",
          status: "modified",
          added: 4,
          removed: 1,
          fingerprint: "f1",
        },
      ],
      truncated: false,
    },
  ],
  warnings: [],
};

const routes: ApiRoutes = {
  "/api/v1/sessions": aPage([fixing, triage]),
  "/api/v1/features": aPage([]),
  [`/api/v1/agent-sessions/${AGENT_ID}/repo-changes`]: changes,
  "/api/v1/sessions/s-fix/summary": aSessionSummary({
    lines: [{ event_id: "e1", text: "Edited 1 file" }],
  }),
  "/api/v1/sessions/s-triage/summary": aSessionSummary({
    lines: [{ event_id: "e2", text: "Read the report" }],
  }),
};

function open(extra: ApiRoutes = {}, path = "/tickets/agent-hub/AGH-112") {
  return renderWithApi(<TicketDetailScreen />, {
    routes: { ...routes, ...extra },
    path,
    route: "/tickets/:project/:issue",
  });
}

describe("TicketDetailScreen", () => {
  it("heads the page with the ticket, its kind, skills, sessions, cost and pull request", async () => {
    const view = open();

    expect(await screen.findByRole("heading", { name: "AGH-112" })).toBeInTheDocument();
    expect(
      screen.getByText("Cap the tracker teams", { selector: ".td-title" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Fix")).toBeInTheDocument();
    expect(screen.getByText("/triage → /fix")).toBeInTheDocument();
    expect(screen.getByText("2 sessions")).toBeInTheDocument();
    expect(screen.getByText("$1.25")).toBeInTheDocument();
    const read = view.requests.find((r) => new URL(r.url).pathname === "/api/v1/sessions");
    const query = new URL(read?.url ?? "http://x").searchParams;
    expect(query.get("issue")).toBe("AGH-112");
    expect(query.get("project")).toBe("agent-hub");
  });

  it("shows the commits and files the sessions changed, with the pull request", async () => {
    open();

    const section = await screen.findByRole("region", { name: /Changes of the session s-fix/ });
    expect(await within(section).findByText("fix(tracker): cap the teams")).toBeInTheDocument();
    expect(within(section).getByText("src/teams.py")).toBeInTheDocument();
    expect(within(section).getByText("roquettejh/agh-112-team-cap")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: "PR #41 open" })).toHaveAttribute(
      "href",
      "https://github.com/acme/app/pull/41",
    );
    expect(screen.getByText(/1 session ran outside hub web/)).toBeInTheDocument();
  });

  it("lists each session oldest first with what it did", async () => {
    const view = open();

    await userEvent.click(await screen.findByRole("tab", { name: /Sessions/ }));
    expect(view.router.state.location.search).toBe("?tab=sessions");
    expect(await screen.findByText("Read the report")).toBeInTheDocument();
    expect(await screen.findByText("Edited 1 file")).toBeInTheDocument();
    const opens = screen.getAllByRole("link", { name: /Open/ }).map((l) => l.getAttribute("href"));
    expect(opens).toEqual(["/sessions/s-triage", `/agent-sessions/${AGENT_ID}`]);
  });

  it("links a feature's ticket to its feature's records", async () => {
    open({ "/api/v1/features": aPage([aFeature({ issues: ["AGH-112"] })]) });

    await userEvent.click(await screen.findByRole("tab", { name: "Feature" }));
    expect(screen.getByRole("link", { name: "Spec" })).toHaveAttribute(
      "href",
      "/features/agent-hub/control-plane?doc=spec",
    );
    expect(screen.getByRole("link", { name: "The ticket in the feature" })).toHaveAttribute(
      "href",
      "/features/agent-hub/control-plane?doc=tickets&ticket=AGH-112",
    );
  });

  it("says no session worked on an unknown ticket", async () => {
    open({ "/api/v1/sessions": aPage([]) }, "/tickets/agent-hub/AGH-9");

    expect(await screen.findByText("No session worked on AGH-9 yet.")).toBeInTheDocument();
  });

  it("has no serious accessibility violations (a11y)", async () => {
    const view = open();
    await screen.findByText("fix(tracker): cap the teams");
    expect(await seriousViolations(view.container)).toEqual([]);
  });
});
