import { render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../testing/axe";
import { NAV, Sidebar } from "./Sidebar";

function renderSidebar(path = "/", props: Partial<Parameters<typeof Sidebar>[0]> = {}) {
  const router = createMemoryRouter(
    [{ path: "*", element: <Sidebar counts={{}} onShortcuts={vi.fn()} {...props} /> }],
    { initialEntries: [path] },
  );
  return render(<RouterProvider router={router} />);
}

describe("Sidebar", () => {
  it("hides Workflow runs until a workflow has run, and lists no Workflows", () => {
    renderSidebar("/", { showRuns: false });

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Workflow runs" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Workflows" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Sessions" })).toBeInTheDocument();
  });

  it("has no P3 tag and hides Metrics, Bench and Tracker queue", () => {
    const { container } = renderSidebar();

    expect(container.querySelector(".ah-phase")).toBeNull();
    expect(screen.getByRole("link", { name: "Learnings" })).toHaveTextContent(/^Learnings$/);
    for (const hidden of ["Metrics", "Bench", "Tracker queue"]) {
      expect(screen.queryByText(hidden)).not.toBeInTheDocument();
    }
  });

  it("turns Portfolio into the overview of the project in scope", () => {
    renderSidebar("/sessions?scope=agent-hub");

    expect(screen.queryByRole("link", { name: "Portfolio" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview · agent-hub" })).toHaveAttribute(
      "href",
      "/projects/agent-hub",
    );
  });

  it("marks the overview as the page only on the project's own overview", () => {
    const { unmount } = renderSidebar("/projects/other%20hub?scope=agent-hub");
    const overview = screen.getByRole("link", { name: "Overview · other hub" });
    expect(overview).toHaveAttribute("href", "/projects/other%20hub");
    expect(overview).toHaveAttribute("aria-current", "page");
    unmount();

    renderSidebar("/projects/agent-hub/brain/now.md");
    expect(screen.getByRole("link", { name: "Overview · agent-hub" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps Portfolio at the root when All projects is in scope", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Portfolio" })).toHaveAttribute("href", "/");
  });

  it("shows Brain under Knowledge for the project in scope", () => {
    renderSidebar("/sessions?scope=agent-hub");

    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain",
    );
  });

  it("points Brain to the project picker when All projects is in scope", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute("href", "/knowledge/brain");
  });

  it("marks Brain as the page when a project's brain note is open", () => {
    renderSidebar("/projects/other%20hub/brain/decisions/index.md?scope=agent-hub");

    const brain = screen.getByRole("link", { name: "Brain" });
    expect(brain).toHaveAttribute("href", "/projects/other%20hub/brain");
    expect(brain).toHaveAttribute("aria-current", "page");
  });

  it("shows Toolkit first under Setup for the project in scope (nav, AC-164.13)", () => {
    renderSidebar("/sessions?scope=agent-hub");

    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names.indexOf("Toolkit")).toBe(names.indexOf("Learnings") + 1);
    expect(screen.getByRole("link", { name: "Toolkit" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/skills",
    );
  });

  it("points Skills to the project picker when All projects is in scope (nav)", () => {
    renderSidebar("/sessions");

    expect(screen.getByRole("link", { name: "Toolkit" })).toHaveAttribute(
      "href",
      "/knowledge/skills",
    );
  });

  it("marks Skills as the page when a project's skill detail is open (nav)", () => {
    renderSidebar("/projects/other%20hub/skills/skill/hub-workflow/feature?scope=agent-hub");

    const skills = screen.getByRole("link", { name: "Toolkit" });
    expect(skills).toHaveAttribute("href", "/projects/other%20hub/skills");
    expect(skills).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Brain" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/brain",
    );
  });

  it("AC-PG-38.2 points Hub config at the project in scope, else the /config picker", () => {
    const { unmount } = renderSidebar("/sessions?scope=agent-hub");
    expect(screen.getByRole("link", { name: "Hub config" })).toHaveAttribute(
      "href",
      "/projects/agent-hub/config",
    );
    unmount();

    renderSidebar("/sessions");
    expect(screen.getByRole("link", { name: "Hub config" })).toHaveAttribute("href", "/config");
  });

  it("AC-PG-38.2 points Hub config at the project in view over the one in scope", () => {
    renderSidebar("/projects/demo/brain?scope=agent-hub");

    expect(screen.getByRole("link", { name: "Hub config" })).toHaveAttribute(
      "href",
      "/projects/demo/config",
    );
  });

  it("marks the current destination as the page when its route is open", () => {
    renderSidebar("/sessions/abc");

    expect(screen.getByRole("link", { name: "Sessions" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Portfolio" })).not.toHaveAttribute("aria-current");
  });

  it("shows badge counts and names them when the stream has counts", () => {
    renderSidebar("/", { counts: { live: 3, learnings: 4, health: 1 } });

    expect(screen.getByRole("link", { name: "Sessions, 3 live" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Learnings, 4 to triage" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Health, 1 doctor error" })).toBeInTheDocument();
  });

  it("badges Features with how many features need you", () => {
    renderSidebar("/", { counts: { features: 2 } });
    expect(screen.getByRole("link", { name: "Features, 2 need you" })).toHaveTextContent("2");
  });

  it("one-tab: has one Sessions entry carrying the live badge and no Live sessions entry", () => {
    const { container } = renderSidebar("/", { counts: { live: 3 } });

    const sessions = screen.getByRole("link", { name: "Sessions, 3 live" });
    expect(sessions).toHaveAttribute("href", "/sessions");
    expect(sessions.querySelector(".ah-nav-count")).toHaveAttribute("data-tone", "live");
    expect(sessions.querySelector(".ah-pulse")).not.toBeNull();
    expect(screen.queryByRole("link", { name: /Live sessions/ })).not.toBeInTheDocument();
    expect(container.querySelector('a[href="/live"]')).toBeNull();
  });

  it("one-tab: draws Sessions with the list icon (spec 01)", () => {
    const sessions = NAV.flatMap((group) => group.items).find((item) => item.id === "sessions");

    expect(sessions?.icon).toBe("list");
  });

  it("one-tab: names Sessions alone when nothing is live", () => {
    renderSidebar("/", { counts: { live: 0 } });

    expect(screen.getByRole("link", { name: "Sessions" })).not.toHaveTextContent("0");
  });

  it("caps a badge at 99+ when the count is larger", () => {
    renderSidebar("/", { counts: { live: 120 } });

    expect(screen.getByRole("link", { name: "Sessions, 120 live" })).toHaveTextContent("99+");
  });

  it("pins Health and Settings to the footer, next to Shortcuts", () => {
    const { container } = renderSidebar();

    const foot = container.querySelector(".ah-sidebar-foot");
    expect(foot).not.toBeNull();
    const names = within(foot as HTMLElement)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names).toEqual(["Health", "Hub config", "Settings"]);
  });

  it("opens the shortcut sheet from its footer button", () => {
    const onShortcuts = vi.fn();
    renderSidebar("/", { onShortcuts });

    screen.getByRole("button", { name: /Shortcuts/ }).click();

    expect(onShortcuts).toHaveBeenCalledOnce();
  });

  it("groups the destinations into Work, Activity, Knowledge, Setup and the Hub footer", () => {
    renderSidebar();

    const nav = screen.getByRole("navigation", { name: "Main" });
    const names = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(names).toEqual([
      "Portfolio",
      "Features",
      "Tickets",
      "Scenarios",
      "Sessions",
      "Workflow runs",
      "Brain",
      "Learnings",
      "Toolkit",
      "Environments",
      "Health",
      "Hub config",
      "Settings",
    ]);
    expect(within(nav).getByRole("link", { name: "Scenarios" })).toHaveAttribute(
      "href",
      "/scenarios",
    );
    for (const group of ["Work", "Activity", "Knowledge", "Setup"]) {
      expect(within(nav).getByText(group)).toBeInTheDocument();
    }
    expect(within(nav).queryByText("Live sessions")).not.toBeInTheDocument();
  });

  it("AC-350.29: shows Scenarios with its clipboard icon before any workflow has run", () => {
    renderSidebar("/", { showRuns: false });

    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("link", { name: "Workflow runs" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Scenarios" })).toBeInTheDocument();
    const scenarios = NAV.flatMap((group) => group.items).find((item) => item.id === "scenarios");
    expect(scenarios?.icon).toBe("clipboard-list");
  });

  it("AC-350.29: marks Scenarios as the page on a scenario run's page", () => {
    renderSidebar("/scenarios/demo/order-lifecycle/runs/3f2a91c0");

    expect(screen.getByRole("link", { name: "Scenarios" })).toHaveAttribute("aria-current", "page");
  });

  it("has no serious or critical a11y violation", async () => {
    const { container } = renderSidebar("/", { counts: { live: 1 } });

    expect(await seriousViolations(container)).toEqual([]);
  });
});
