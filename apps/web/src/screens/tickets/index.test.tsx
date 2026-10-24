import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { seriousViolations } from "../../testing/axe";
import {
  aFeature,
  aPage,
  aProblem,
  aSession,
  aSessionLabel,
  renderWithApi,
  type ApiRoutes,
} from "../../testing/builders";
import { TicketsScreen } from "./index";

const SESSIONS = "/api/v1/sessions";

const label = (issue: string, workflows: string[], title: string | null = null) =>
  aSessionLabel({ issue, workflow: workflows[0] ?? null, workflows, title });

const waiting = aSession({
  id: "s-waiting",
  issue: null,
  status: "waiting",
  waiting_reason: "a permission prompt",
  label: label("AGH-112", ["/kickoff", "/fix"], "Tracker team cap"),
  pr: { number: 41, state: "open", url: "https://github.com/acme/app/pull/41" },
  cost_usd: "1.0000",
});
const earlier = aSession({
  id: "s-earlier",
  issue: null,
  status: "ended",
  outcome: "done",
  label: label("AGH-112", ["/fix"]),
  last_activity_at: "2026-01-01T09:00:00Z",
  cost_usd: "0.2500",
});
const live = aSession({ id: "s-live", status: "live", label: label("AGH-7", ["/upgrade"]) });
const ended = aSession({
  id: "s-ended",
  status: "ended",
  outcome: "done",
  label: label("AGH-3", ["/review"]),
});
const planned = aSession({ id: "s-planned", status: "live", label: label("AGH-200", ["/fix"]) });
const featurePath = aSession({ id: "s-feature", label: label("AGH-48", ["/feature"]) });

const routes: ApiRoutes = {
  [SESSIONS]: aPage([waiting, earlier, live, ended, planned, featurePath]),
  "/api/v1/features": aPage([aFeature({ issues: ["AGH-200"] })]),
};

function open(extra: ApiRoutes = {}, path = "/tickets") {
  return renderWithApi(<TicketsScreen />, { routes: { ...routes, ...extra }, path });
}

function groupOf(title: string): HTMLElement {
  const section = screen
    .getByRole("heading", { name: new RegExp(`^${title} ·`) })
    .closest("section");
  if (!section) throw new Error(`no group ${title}`);
  return section;
}

const issuesIn = (el: HTMLElement) =>
  within(el)
    .queryAllByRole("link")
    .map((link) => link.textContent)
    .filter((text) => /^[A-Z]+-\d+$/.test(text));

describe("TicketsScreen", () => {
  it("lists every ticket a session worked on by Needs you, In progress and Ended (AC-426.2, AC-426.4)", async () => {
    open();

    await waitFor(() => {
      expect(issuesIn(groupOf("Needs you"))).toEqual(["AGH-112"]);
    });
    expect(issuesIn(groupOf("In progress")).sort()).toEqual(["AGH-200", "AGH-48", "AGH-7"]);
    expect(issuesIn(groupOf("Ended"))).toEqual(["AGH-3"]);
    const summary = screen.getByText("need you").closest("p");
    expect(summary).toHaveTextContent(/1 need you\s*3 in progress\s*1 ended/);
    expect(within(summary as HTMLElement).getByText("derived")).toBeInTheDocument();
  });

  it("draws a row with its issue, name, kind, skills, sessions, PR, state and cost (AC-426.5)", async () => {
    open();

    const link = await screen.findByRole("link", { name: "AGH-112" });
    expect(link).toHaveAttribute("href", "/tickets/agent-hub/AGH-112");
    const row = link.closest("li") as HTMLElement;
    expect(within(row).getByText("Tracker team cap")).toBeInTheDocument();
    expect(within(row).getByText("Fix")).toBeInTheDocument();
    expect(
      within(row).getByText("/fix · 2 sessions · PR #41 open · a permission prompt"),
    ).toBeInTheDocument();
    expect(within(row).getByText("$1.25")).toBeInTheDocument();
    const endedRow = screen.getByRole("link", { name: "AGH-3" }).closest("li") as HTMLElement;
    expect(endedRow).toHaveAttribute("data-muted", "true");
    expect(within(endedRow).getByText(/^\/review · 1 session · ended done/)).toBeInTheDocument();
    expect(
      within(screen.getByRole("link", { name: "AGH-7" }).closest("li") as HTMLElement).getByText(
        /^\/upgrade · 1 session · active/,
      ),
    ).toBeInTheDocument();
  });

  it("names a feature's ticket by its feature, linking to the ticket there", async () => {
    open();

    const row = (await screen.findByRole("link", { name: "AGH-200" })).closest("li") as HTMLElement;
    expect(within(row).getByText("Feature")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "control-plane" })).toHaveAttribute(
      "href",
      "/features/agent-hub/control-plane?doc=tickets&ticket=AGH-200",
    );
  });

  it("opens every session of a ticket from its row's sessions toggle", async () => {
    const view = open();

    const row = (await screen.findByRole("link", { name: "AGH-112" })).closest("li") as HTMLElement;
    const toggle = within(row).getByRole("button", { name: /2 sessions/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const links = within(row)
      .getAllByRole("link")
      .map((link) => link.getAttribute("href"))
      .filter((href) => href?.startsWith("/sessions/"));
    expect(links).toEqual(["/sessions/s-waiting", "/sessions/s-earlier"]);
    expect(view.router.state.location.pathname).toBe("/tickets");
  });

  it("filters by search and kind, keeps them in the URL and counts the matches (AC-426.7)", async () => {
    const view = open();

    await userEvent.type(await screen.findByRole("searchbox", { name: "Find tickets" }), "agh-7");
    expect(screen.getByRole("status")).toHaveTextContent("1 of 5 tickets");
    expect(screen.queryByRole("heading", { name: /^Needs you/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AGH-7" })).toBeInTheDocument();
    expect(view.router.state.location.search).toBe("?q=agh-7");

    await userEvent.clear(screen.getByRole("searchbox", { name: "Find tickets" }));
    await userEvent.click(screen.getByRole("button", { name: /Kind:/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Review/ }));
    expect(view.router.state.location.search).toBe("?kind=review");
    expect(screen.getByRole("status")).toHaveTextContent("1 of 5 tickets");
    expect(screen.queryByRole("link", { name: "AGH-112" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AGH-3" })).toBeInTheDocument();
  });

  it("explains how to start when no session worked on a ticket (AC-426.8)", async () => {
    open({
      [SESSIONS]: aPage([
        aSession({ id: "s-none", issue: null, label: aSessionLabel({ issue: null }) }),
      ]),
    });

    expect(await screen.findByText("No ticket work yet.")).toBeInTheDocument();
    expect(screen.getByText("/fix AGH-112")).toBeInTheDocument();
  });

  it("shows the problem with Retry when the sessions cannot be read (AC-426.8)", async () => {
    open({ [SESSIONS]: aProblem({ status: 503, title: "Store unavailable" }) });

    expect(await screen.findByText("Store unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("reads the newest sessions of the scope and opens a row with Enter (AC-426.2, AC-426.9)", async () => {
    const view = open({}, "/tickets?scope=agent-hub");

    const row = (await screen.findByRole("link", { name: "AGH-7" })).closest("li") as HTMLElement;
    const read = view.requests.find((r) => new URL(r.url).pathname === SESSIONS);
    const query = new URL(read?.url ?? "http://x").searchParams;
    expect(query.get("project")).toBe("agent-hub");
    expect(query.get("sort")).toBe("-last_activity_at");
    expect(query.get("limit")).toBe("200");
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(view.router.state.location.pathname).toBe("/tickets/agent-hub/AGH-7");
  });

  it("has no serious accessibility violations (a11y)", async () => {
    const view = open();
    await screen.findByRole("link", { name: "AGH-112" });
    expect(await seriousViolations(view.container)).toEqual([]);
  });
});
